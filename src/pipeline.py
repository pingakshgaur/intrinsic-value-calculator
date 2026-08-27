# FILE: pipeline.py
"""Fetch -> estimate -> value -> export -> analyse. All exception capture lives here."""

import logging
import time
import traceback

import config
import yf_source
import ticker_resolver
import overrides
import estimation
import model_dcf
import model_pe
import model_ev_ebitda
import exporter
import csv_analyzer
import ml_common
import model_xgboost
import model_random_forest
import model_lightgbm
from result import Result, R, field_result

log = logging.getLogger("valuation")
ML_MODULES = [model_xgboost, model_random_forest, model_lightgbm]


def build_universe(companies):
    universe, failures = {}, {}
    for c in companies:
        name = c["name"]
        print(f"[fetch] {name} ...", end=" ", flush=True)
        try:
            ticker = ticker_resolver.resolve(name, c.get("ticker"))
        except Exception as e:
            log.exception("ticker resolution crashed for %s", name)
            failures[name] = Result.bad(
                R.TICKER, f"lookup raised {type(e).__name__}: {e}"
            )
            print("FAILED (lookup error)")
            continue

        if not ticker:
            failures[name] = Result.bad(
                R.TICKER,
                f"'{name}' matched no {config.EXCHANGE_SUFFIX} or .BO symbol; add "
                f"an explicit ticker column in the input CSV",
            )
            print("FAILED (no ticker)")
            continue

        try:
            if config.OFFLINE:
                import mock_source

                data = mock_source.fetch_by_name(name, config.FY_LIST)
            else:
                data = yf_source.fetch_company(ticker, config.FY_LIST)
        except Exception as e:
            log.exception("fetch crashed for %s (%s)", name, ticker)
            failures[name] = Result.bad(
                R.FETCH_FAILED, f"download for {ticker} raised {type(e).__name__}: {e}"
            )
            print(f"FAILED ({type(e).__name__})")
            continue

        universe[name] = {
            "sector": c["sector"],
            "cap": c.get("cap", ""),
            "ticker": ticker,
            "data": data,
        }

        n = len(config.FY_LIST)
        px = sum(1 for d in data["years"].values() if d.get("price"))
        bench = sum(1 for d in data["years"].values() if d.get("price_bench"))
        fund = sum(1 for d in data["years"].values() if d.get("ebit") is not None)
        ovr = sum(
            1
            for d in data["years"].values()
            if any("manually supplied" in s for s in d.get("_notes", []))
        )
        tag = f"  overrides {ovr}" if ovr else ""
        print(
            f"OK  [{ticker}]  prices {px}/{n}  benchmarks {bench}/{n}  "
            f"fundamentals {fund}/{n}{tag}"
        )
        if not config.OFFLINE:
            time.sleep(config.REQUEST_PAUSE)
    return universe, failures


def run(companies, extra_training=None):
    if overrides.ensure_template_exists():
        print(
            f"[override] created empty {config.OVERRIDE_FILE} - run "
            f"'python run.py --make-override-template' to populate it\n"
        )
    overrides.load()

    universe, failures = build_universe(companies)

    train_universe = dict(universe)
    if extra_training:
        extra_uni, extra_fail = build_universe(extra_training)
        for k, v in extra_uni.items():
            train_universe.setdefault(k, v)
        print(
            f"\n[ml] training universe extended to {len(train_universe)} "
            f"companies ({len(extra_fail)} extras failed)"
        )

    # ---- gap filling MUST run before the peer tables are built ----
    estimation.fill_universe(train_universe)

    pe_table = model_pe.build_sector_pe_table(universe) if universe else {}
    ev_table = model_ev_ebitda.build_sector_table(universe) if universe else {}

    ml_store, ml_df = None, None
    if config.ML_ENABLED and universe:
        print("\n[ml] building feature matrix ...")
        ml_df, ml_failures = ml_common.build_dataset(train_universe)
        n_lab = int(ml_df["label"].notna().sum()) if not ml_df.empty else 0
        print(f"[ml] {len(ml_df)} rows, {n_lab} labelled, split='{config.ML_SPLIT}'")
        ml_store = ml_common.run_models(
            ml_df, [m.SPEC for m in ML_MODULES], ml_failures
        )
        for p in ml_common.write_diagnostics(ml_store, ml_df):
            print(f"[ml] wrote {p}")

    def guard(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            log.error("model crashed: %s", traceback.format_exc())
            return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")

    rows = []
    for c in companies:
        name, sector = c["name"], c["sector"]
        # ascending, so each company block reads oldest FY first
        for fy in sorted(config.FY_LIST):
            base = {"company": name, "sector": sector, "fy": fy}
            if name in failures:
                f = failures[name]
                rows.append(
                    {
                        **base,
                        "price": f,
                        "price_anchor": f,
                        "price_bench_date": "",
                        "dcf": f,
                        "pe": f,
                        "ev": f,
                        "xgboost": f,
                        "random_forest": f,
                        "lightgbm": f,
                    }
                )
                continue

            data = universe[name]["data"]
            d = data["years"].get(fy, {})
            row = {
                **base,
                # "price" is the BENCHMARK: the close on the trading day
                # nearest 1 May following FY end. It is what every model is
                # scored against.
                "price": field_result(
                    d, "price_bench", fy, "1-May benchmark market price"
                ),
                # the in-FY mean price the models actually consumed. Carried
                # for the numeric twin so anchor and benchmark can be compared
                # during review; never shown in the main grid.
                "price_anchor": field_result(d, "price", fy, "in-FY mean price"),
                # the date the benchmark close was actually taken from - 1 May
                # is a market holiday, so this is rarely 1 May itself.
                "price_bench_date": d.get("price_bench_date") or "",
                "dcf": guard(model_dcf.intrinsic_value, data, fy),
                "pe": guard(
                    model_pe.intrinsic_value, universe, pe_table, name, sector, fy
                ),
                "ev": guard(
                    model_ev_ebitda.intrinsic_value,
                    universe,
                    ev_table,
                    name,
                    sector,
                    fy,
                ),
            }
            for m in ML_MODULES:
                row[m.KEY] = guard(m.intrinsic_value, ml_store, name, fy)
            rows.append(row)

    csv_p, xlsx_p, aux_p = exporter.export(rows)
    print(f"\n[export] {len(rows)} rows -> {csv_p}")
    print(f"[export]              -> {xlsx_p}")
    for p in aux_p:
        print(f"[export]              -> {p}")

    labels = [("dcf", "DCF"), ("pe", "P/E Relative"), ("ev", "EV/EBITDA")] + [
        (m.KEY, m.NAME) for m in ML_MODULES
    ]

    print(
        "\n[model coverage]   (est = estimated, marked with "
        f"'{config.ESTIMATE_MARKER}' in the report)"
    )
    for key, label in labels:
        ok = sum(1 for r in rows if r[key].ok)
        est = sum(1 for r in rows if r[key].estimated)
        print(f"   {label:16s} {ok:4d}/{len(rows)}   est {est:4d}")
    okp = sum(1 for r in rows if r["price"].ok)
    oka = sum(1 for r in rows if r.get("price_anchor") and r["price_anchor"].ok)
    print(
        f"   {'Market Price':16s} {okp:4d}/{len(rows)}   "
        f"(benchmark, basis='{config.BENCHMARK_BASIS}')"
    )
    print(
        f"   {'  in-FY anchor':16s} {oka:4d}/{len(rows)}   "
        f"(valuation input, not a benchmark)"
    )

    if config.BENCHMARK_BASIS == "may1":
        exact = sum(1 for r in rows if r.get("price_bench_date", "").endswith("-05-01"))
        dated = sum(1 for r in rows if r.get("price_bench_date"))
        print(
            f"   benchmark date = close nearest 1 May following FY end "
            f"({exact}/{dated} landed exactly on 1 May; the rest are the "
            f"nearest session, since 1 May is Maharashtra Day)"
        )

    if ml_store and ml_store.metrics:
        print("\n[ml fold performance]  (forward-ratio target)")
        for m in ml_store.metrics:
            flag = "  [LEAKED]" if m.get("leaked") else ""
            if m.get("status") != "ok":
                print(f"   FY{m['fold_fy']} {m['model']:16s} {m['status']}{flag}")
            else:
                print(
                    f"   FY{m['fold_fy']} {m['model']:16s} "
                    f"RMSE {m['rmse_ratio']:.4f}  MAE {m['mae_ratio']:.4f}  "
                    f"dir {m['directional_accuracy']:.0%}{flag}"
                )

    tally = {}
    for r in rows:
        for key, _ in labels:
            if not r[key].ok:
                tally[r[key].code] = tally.get(r[key].code, 0) + 1
    if tally:
        print("\n[why cells are blank]  (full text in the diagnostics file)")
        for code, n in sorted(tally.items(), key=lambda x: -x[1]):
            print(f"   {n:4d}  {code}")
    else:
        print("\n[why cells are blank]  none - every cell has a value")

    # ---- analysis ----
    if not getattr(config, "ANALYSIS_ENABLED", True):
        return
    data_path = config.OUTPUT_DIR / f"{config.DATA_BASENAME}.csv"
    if not data_path.exists():
        print(f"\n[analyzer] skipped: {data_path.name} was not written")
        return
    print("\n[analyzer] running statistical analysis ...")
    try:
        csv_analyzer.run_analysis(
            data_path,
            outdir=config.OUTPUT_DIR,
            dpi=getattr(config, "CHART_DPI", 200),
        )
    except Exception as e:
        log.exception("analysis stage failed")
        print(f"[analyzer] FAILED: {type(e).__name__}: {e}")
        print(
            "[analyzer] the CSV exports above are unaffected; re-run with "
            "'python tools/analyze.py' once fixed"
        )
