"""
Orchestrator with full exception capture.

    python main.py
    python main.py --input companies.csv
    python main.py --input companies.csv --reasons short
"""

import argparse
import csv
import logging
import os
import sys
import time
import traceback

import config
import yf_source
import ticker_resolver
import model_dcf
import model_pe
import model_ev_ebitda
import exporter
from result import Result, R, field_result

import ml_common
import model_xgboost
import model_random_forest
import model_lightgbm

log = logging.getLogger("valuation")
ML_MODULES = [model_xgboost, model_random_forest, model_lightgbm]


def setup_logging():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, config.LOG_FILE)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, mode="w", encoding="utf-8")],
    )
    logging.getLogger("yfinance").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    return path


# ---------------- input ----------------
def read_csv_input(path):
    """Tolerant CSV reader: never crashes on ragged rows, reports them instead."""
    companies, problems = [], []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, restkey="_extra", restval="")
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header row")
        norm = {k: (k or "").strip().lower() for k in reader.fieldnames}

        for raw in reader:
            line_no = reader.line_num
            row = {}
            for k, v in raw.items():
                key = norm.get(k, k if isinstance(k, str) else "_extra")
                if isinstance(v, list):
                    v = ",".join(str(x) for x in v)
                row[key] = (v or "").strip() if v is not None else ""

            if row.get("_extra"):
                problems.append(
                    f"  line {line_no}: extra unmapped field(s) {row['_extra']!r} - "
                    f"row has more commas than the header. Quote any field that "
                    f'contains a comma, e.g. "Emami, Ltd".'
                )

            name = (
                row.get("company name") or row.get("company") or row.get("name") or ""
            )
            if not name:
                if any(row.get(k) for k in row if k != "_extra"):
                    problems.append(f"  line {line_no}: no company name found; skipped")
                continue

            companies.append(
                {
                    "name": name,
                    "sector": row.get("sector name")
                    or row.get("sector")
                    or "Unclassified",
                    "cap": row.get("market cap") or row.get("cap") or "",
                    "ticker": row.get("ticker") or None,
                }
            )

    if problems:
        print(f"[input] {len(problems)} issue(s) in {path}:")
        for p in problems:
            print(p)
        print()
    if not companies:
        raise ValueError(f"No usable rows in {path}")
    print(f"[input] loaded {len(companies)} companies from {path}\n")
    return companies


def read_terminal_input():
    print("\nEnter companies as:  Company Name, Sector Name [, TICKER]")
    print("Press ENTER on an empty line when done.\n")
    companies = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            print("   Need at least 'Name, Sector'. Try again.")
            continue
        companies.append(
            {
                "name": parts[0],
                "sector": parts[1],
                "cap": parts[2] if len(parts) > 2 else "",
                "ticker": parts[3] if len(parts) > 3 else None,
            }
        )
    return companies


# ---------------- pipeline ----------------
def build_universe(companies):
    """-> (universe, failures{name: Result})"""
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
                f"'{name}' did not match any {config.EXCHANGE_SUFFIX} symbol on Yahoo "
                f"search; add an explicit ticker column in the input CSV",
            )
            print("FAILED (no ticker)")
            continue

        try:
            if getattr(config, "OFFLINE", False):
                import mock_source

                data = mock_source.fetch_by_name(name, config.FY_LIST)
            else:
                data = yf_source.fetch_company(ticker, config.FY_LIST)
        except Exception as e:
            log.exception("fetch crashed for %s (%s)", name, ticker)
            failures[name] = Result.bad(
                R.FETCH_FAILED,
                f"data download for {ticker} raised {type(e).__name__}: {e} "
                f"(see {config.LOG_FILE} for the traceback)",
            )
            print(f"FAILED ({type(e).__name__})")
            continue
        universe[name] = {
            "sector": c["sector"],
            "cap": c.get("cap", ""),
            "ticker": ticker,
            "data": data,
        }
        got = sum(1 for d in data["years"].values() if d.get("price"))
        fund = sum(1 for d in data["years"].values() if d.get("ebit") is not None)
        print(
            f"OK  [{ticker}]  prices {got}/{len(config.FY_LIST)}  "
            f"fundamentals {fund}/{len(config.FY_LIST)}"
        )
        time.sleep(config.REQUEST_PAUSE)
    return universe, failures


def run(companies, extra_training=None):
    universe, failures = build_universe(companies)

    # ---- optional wider training universe (not valued, only used to fit) ----
    train_universe = dict(universe)
    if extra_training:
        extra_uni, extra_fail = build_universe(extra_training)
        for k, v in extra_uni.items():
            train_universe.setdefault(k, v)
        print(
            f"\n[ml] training universe extended to {len(train_universe)} "
            f"companies ({len(extra_fail)} extras failed to fetch)"
        )

    pe_table = model_pe.build_sector_pe_table(universe) if universe else {}
    ev_table = model_ev_ebitda.build_sector_table(universe) if universe else {}

    # ---- machine-learning stage ----
    ml_store, ml_df = None, None
    if config.ML_ENABLED and universe:
        print("\n[ml] building feature matrix ...")
        ml_df, ml_failures = ml_common.build_dataset(train_universe)
        n_lab = int(ml_df["label"].notna().sum()) if not ml_df.empty else 0
        print(
            f"[ml] {len(ml_df)} company-year rows, {n_lab} with a forward label, "
            f"{len(ml_common.feature_columns(ml_df)) if not ml_df.empty else 0} "
            f"features, split='{config.ML_SPLIT}'"
        )
        specs = [m.SPEC for m in ML_MODULES]
        ml_store = ml_common.run_models(ml_df, specs, ml_failures)
        for p in ml_common.write_diagnostics(ml_store, ml_df):
            print(f"[ml] wrote {p}")

    rows = []
    for c in companies:
        name, sector = c["name"], c["sector"]
        for fy in sorted(config.FY_LIST, reverse=True):
            base = {"company": name, "sector": sector, "fy": fy}

            if name in failures:
                fail = failures[name]
                rows.append(
                    {
                        **base,
                        "price": fail,
                        "dcf": fail,
                        "pe": fail,
                        "ev": fail,
                        "xgboost": fail,
                        "random_forest": fail,
                        "lightgbm": fail,
                    }
                )
                continue

            data = universe[name]["data"]
            d = data["years"].get(fy, {})

            def guard(fn, *a):
                try:
                    return fn(*a)
                except Exception as e:
                    log.error("model crashed: %s", traceback.format_exc())
                    return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")

            row = {
                **base,
                "price": field_result(d, "price", fy, "market price"),
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

    csv_p, xlsx_p = exporter.export(rows)
    print()
    print(f"[export] {len(rows)} company-year rows -> {csv_p}")
    print(f"[export] {' ' * 30} {xlsx_p}")

    print("\n[model coverage]")
    labels = [("dcf", "DCF"), ("pe", "P/E Relative"), ("ev", "EV/EBITDA")]
    labels += [(m.KEY, m.NAME) for m in ML_MODULES]
    for key, label in labels:
        ok = sum(1 for r in rows if r[key].ok)
        print(f"   {label:16s} {ok:4d}/{len(rows)} valued")
    ok_price = sum(1 for r in rows if r["price"].ok)
    print(f"   {'Market Price':16s} {ok_price:4d}/{len(rows)} available")

    if ml_store and ml_store.metrics:
        print("\n[ml fold performance]  (on the forward-ratio target)")
        for m in ml_store.metrics:
            if m.get("status") != "ok":
                print(
                    f"   FY{m['fold_fy']} {m['model']:16s} {m.get('status')}"
                    f"  (n_train={m['n_train']})"
                )
            else:
                print(
                    f"   FY{m['fold_fy']} {m['model']:16s} "
                    f"RMSE {m['rmse_ratio']:.4f}  MAE {m['mae_ratio']:.4f}  "
                    f"dir {m['directional_accuracy']:.0%}  "
                    f"(train {m['n_train']}, test {m['n_test']})"
                )

    tally = {}
    for r in rows:
        for key, _ in labels:
            if not r[key].ok:
                tally[r[key].code] = tally.get(r[key].code, 0) + 1
    if tally:
        print("\n[why cells are blank]")
        for code, n in sorted(tally.items(), key=lambda x: -x[1]):
            print(f"   {n:4d}  {code}")


def main():
    log_path = setup_logging()
    ap = argparse.ArgumentParser(description="Intrinsic value engine (FY2021-FY2025)")

    ap.add_argument("--input", help="path to companies CSV")
    ap.add_argument(
        "--mean-basis",
        choices=["trading", "calendar"],
        help="average over traded sessions (default) or all calendar days",
    )
    ap.add_argument("--exchange", choices=[".NS", ".BO"])
    ap.add_argument(
        "--reasons",
        choices=["detailed", "short", "off"],
        help="how blank cells are annotated",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="use the synthetic mock dataset, no network",
    )
    ap.add_argument(
        "--train-universe",
        help="extra CSV of companies used ONLY to train the ML models",
    )
    ap.add_argument(
        "--ml-split",
        choices=["expanding", "loyo"],
        help="expanding window (default, correct) or leave-one-year-out",
    )
    ap.add_argument("--no-ml", action="store_true", help="skip the ML stage")

    args = ap.parse_args()

    if args.offline:
        import mock_source
        config.OFFLINE = True
        ticker_resolver.resolve = mock_source.resolve

    if args.mean_basis:
        config.FY_MEAN_BASIS = args.mean_basis

    if args.exchange:
        config.EXCHANGE_SUFFIX = args.exchange

    if args.ml_split:
        config.ML_SPLIT = args.ml_split

    if args.no_ml:
        config.ML_ENABLED = False

    extra = None

    if args.train_universe:
        if not os.path.exists(args.train_universe):
            sys.exit(f"File not found: {args.train_universe}")
        extra = read_csv_input(args.train_universe)

    if args.reasons == "off":
        config.SHOW_REASONS = False

    elif args.reasons:
        config.REASON_STYLE = args.reasons

    try:
        if args.offline:
            import mock_source
            companies = mock_source.COMPANIES
        elif os.path.exists("companies.csv"):
            use = input("Found companies.csv. Use it? [Y/n]: ").strip().lower()
            companies = (
                read_csv_input("companies.csv") if use != "n" else read_terminal_input()
            )
        else:
            companies = read_terminal_input()
    except Exception as e:
        log.exception("input parsing failed")
        sys.exit(f"Could not read input: {type(e).__name__}: {e}")

    if not companies:
        sys.exit("No companies supplied.")

    try:
        run(companies, extra_training=extra)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        log.exception("fatal")
        print(f"\nFATAL: {type(e).__name__}: {e}\nTraceback written to {log_path}")
        sys.exit(1)
    print(f"\nFull log: {log_path}")


if __name__ == "__main__":
    main()
