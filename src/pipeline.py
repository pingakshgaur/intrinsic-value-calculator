# FILE: src/pipeline.py
"""Fetch -> screen -> estimate -> value -> export -> analyse. All exception capture lives here."""

import logging
import time
import traceback

import config
import yf_source
import ticker_resolver
import overrides
import sufficiency
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
            # cap is now stored. It was previously dropped here, which left
            # cap_tier_ord null for every ML row - one of the 21 features was
            # silently dead. Carrying it costs nothing and revives the feature.
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


def screen_only(companies):
    """
    Dry run: fetch, screen, report, stop.

    Exists so the sufficiency threshold can be calibrated against what the
    source actually supplies before it is allowed to delete anything.
    """
    if overrides.ensure_template_exists():
        print(f"[override] created empty {config.OVERRIDE_FILE}\n")
    overrides.load()

    universe, failures = build_universe(companies)
    records = sufficiency.screen(companies, universe, failures)
    sufficiency.print_summary(records)

    path = exporter.export_exclusions(records)
    print(f"\n[export] sufficiency screen -> {path}")
    print("[gate] dry run only; no valuation was performed")
    return records


def run(companies, extra_training=None):
    if overrides.ensure_template_exists():
        print(
            f"[override] created empty {config.OVERRIDE_FILE} - run "
            f"'python run.py --make-override-template' to populate it\n"
        )
    overrides.load()

    universe, failures = build_universe(companies)

    # ---- sufficiency gate: AFTER fetch, BEFORE estimation ----
    # Order is load-bearing. estimation.fill_universe() below can fabricate a
    # documented value for almost any gap, so screening afterwards would pass
    # everybody. Screening here tests reported data only.
    records = sufficiency.screen(companies, universe, failures)
    excluded = sufficiency.excluded_names(records)
    sufficiency.print_summary(records)

    valued = [c for c in companies if c["name"] not in excluded]

    # ---- auto-relax safety valve ----
    # A gate that rejects everybody has told you about the data source, not
    # about the companies. Rather than return nothing, fall back to the best
    # figure actually observed and say so in the loudest possible terms.
    if not valued and getattr(config, "SUFFICIENCY_AUTO_RELAX", True) and records:
        best_fy = max((r["complete_fy"] for r in records), default=0)
        best_bench = max((r["benchmark_fy"] for r in records), default=0)
        if best_fy >= 1:
            old_fy = config.MIN_COMPLETE_FY
            old_bench = config.MIN_BENCHMARK_FY
            config.MIN_COMPLETE_FY = best_fy
            config.MIN_BENCHMARK_FY = min(old_bench, best_bench)
            print(
                f"\n[gate] AUTO-ADJUSTED. No company reached "
                f"{old_fy} complete financial years, so nothing would have "
                f"been valued and no report written."
                f"\n[gate] The best any company managed was {best_fy}. The "
                f"threshold has been lowered to {config.MIN_COMPLETE_FY} "
                f"complete years / {config.MIN_BENCHMARK_FY} benchmark years "
                f"for this run only - config.py is unchanged."
                f"\n[gate] This is a limit of the data source, not a fault in "
                f"the companies. Record the figure actually used in your "
                f"methodology; do not report the one in config.py."
            )
            records = sufficiency.screen(companies, universe, failures)
            excluded = sufficiency.excluded_names(records)
            valued = [c for c in companies if c["name"] not in excluded]
            # sufficiency.print_summary(records)

    if not valued:
        exporter.export_exclusions(records)
        print(
            "\n[gate] no company cleared the gate even after auto-adjustment, "
            "so there is nothing to value. Every company returned zero usable "
            "financial years - that points at the data source or the ticker "
            "symbols, not at the threshold. The exclusion sheet was still "
            "written; read it first."
        )
        return

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

    # Excluded companies stay in the peer medians and the ML training frame by
    # default. Thin data is not wrong data, and pulling these firms out would
    # thin the sector medians every surviving company is valued against.
    if getattr(config, "SUFFICIENCY_KEEP_IN_PEERS", True):
        peer_universe = universe
    else:
        peer_universe = {k: v for k, v in universe.items() if k not in excluded}

    if getattr(config, "SUFFICIENCY_KEEP_IN_ML", True):
        ml_universe = train_universe
    else:
        ml_universe = {k: v for k, v in train_universe.items() if k not in excluded}

    if excluded:
        print(
            f"[gate] excluded companies retained in peer medians: "
            f"{getattr(config, 'SUFFICIENCY_KEEP_IN_PEERS', True)}; "
            f"in ML training: {getattr(config, 'SUFFICIENCY_KEEP_IN_ML', True)}"
        )

    pe_table = model_pe.build_sector_pe_table(peer_universe) if peer_universe else {}
    ev_table = (
        model_ev_ebitda.build_sector_table(peer_universe) if peer_universe else {}
    )

    ml_store, ml_df = None, None
    if config.ML_ENABLED and universe:
        print("\n[ml] building feature matrix ...")
        ml_df, ml_failures = ml_common.build_dataset(ml_universe)
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
    for c in valued:
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

    csv_p, xlsx_p, aux_p = exporter.export(rows, exclusions=records)
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
    plain_summary(rows, len(excluded))

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


def plain_summary(rows, excluded_count):
    """
    Jargon-free closing summary.

    The technical block above is what goes in the thesis. This is what makes
    the output legible to someone who has never met an EV/EBITDA multiple. It
    deliberately says "looks cheap" rather than "trades at a discount to
    intrinsic value" - the second phrasing is more precise and less useful.
    """
    if not getattr(config, "PLAIN_SUMMARY", True):
        return

    band = getattr(config, "PLAIN_VERDICT_BAND", 0.10)
    keys = ["dcf", "pe", "ev", "xgboost", "random_forest", "lightgbm"]
    cheap = dear = fair = unknown = 0
    companies = set()

    for r in rows:
        companies.add(r["company"])
        price = r.get("price")
        vals = [r[k].value for k in keys if k in r and getattr(r[k], "ok", False)]
        if not (price is not None and getattr(price, "ok", False)) or not vals:
            unknown += 1
            continue
        avg = sum(vals) / len(vals)
        if avg <= 0:
            unknown += 1
        elif price.value < avg * (1 - band):
            cheap += 1
        elif price.value > avg * (1 + band):
            dear += 1
        else:
            fair += 1

    total = len(rows)
    print("\n" + "=" * 74)
    print("  IN PLAIN ENGLISH")
    print("=" * 74)
    print(
        f"  We looked at {len(companies)} companies across "
        f"{len(config.FY_LIST)} financial years - {total} company-years in all."
    )
    if excluded_count:
        print(
            f"  {excluded_count} more were set aside because their published "
            f"accounts were too incomplete to value fairly. They are listed, "
            f"with the reason for each, on the 'Excluded Companies' sheet."
        )
    print(
        f"\n  For each company-year we worked out what the business appears to "
        f"be worth,\n  then compared that with what its shares actually traded "
        f"at on the following 1 May."
    )
    print(f"\n  Of the {total} comparisons:")
    print(f"    {cheap:5d}  the share price looked LOW next to the estimated worth")
    print(f"    {dear:5d}  the share price looked HIGH next to the estimated worth")
    print(f"    {fair:5d}  the two were within {int(band * 100)}% of each other")
    if unknown:
        print(f"    {unknown:5d}  could not be judged - not enough data that year")
    print(
        "\n  A low price is not automatically a buy signal. These are estimates "
        "built\n  from past accounts, and every method here has known blind "
        "spots. Read the\n  'Methods' sheet to see how each number was arrived "
        "at before trusting it."
    )
    print("=" * 74)
