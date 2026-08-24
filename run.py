# FILE: run.py
"""
+#!/usr/bin/env python3

Intrinsic Value Calculator - entry point.

    python run.py
    python run.py --input data/companies.csv
    python run.py --no-ml --reasons short
    python run.py --benchmark-basis mean       # robustness re-run
    python run.py --no-analyze                 # skip charts
    python run.py --make-override-template     # writes the fill-in sheet
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for sub in ("src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import argparse
import logging

import config
import ticker_resolver
import inputs
import pipeline

log = logging.getLogger("valuation")


def setup_logging():
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / config.LOG_FILE
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, mode="w", encoding="utf-8")],
    )
    for noisy in ("yfinance", "urllib3", "peewee"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    return path


def main():
    log_path = setup_logging()

    ap = argparse.ArgumentParser(description="Intrinsic value engine (FY2021-FY2025)")
    ap.add_argument("--input", help="path to companies CSV")
    ap.add_argument("--mean-basis", choices=["trading", "calendar"])
    ap.add_argument(
        "--benchmark-basis",
        choices=["high_52w", "mean", "close"],
        help="how the assessment-year market price is drawn (default: high_52w)",
    )
    ap.add_argument(
        "--fy-labels",
        choices=["range", "int"],
        help="Financial Year column as '2023-24' (range) or '2024' (int)",
    )
    ap.add_argument("--exchange", choices=[".NS", ".BO"])
    ap.add_argument(
        "--reasons",
        choices=["code", "detailed", "off"],
        help="how blank cells are annotated in the main report",
    )
    ap.add_argument("--offline", action="store_true")
    ap.add_argument(
        "--train-universe", help="extra CSV used ONLY to train the ML models"
    )
    ap.add_argument("--ml-split", choices=["expanding", "loyo"])
    ap.add_argument("--no-ml", action="store_true")
    ap.add_argument(
        "--no-analyze", action="store_true", help="skip the chart/statistics stage"
    )
    ap.add_argument("--dpi", type=int, help="chart resolution (default 200)")
    ap.add_argument(
        "--no-overrides",
        action="store_true",
        help="ignore data/fundamentals_override.csv",
    )
    ap.add_argument(
        "--make-override-template",
        action="store_true",
        help="fetch, then write a fill-in sheet for every gap",
    )
    args = ap.parse_args()

    if args.mean_basis:
        config.FY_MEAN_BASIS = args.mean_basis
    if args.benchmark_basis:
        config.BENCHMARK_BASIS = args.benchmark_basis
    if args.fy_labels:
        config.FY_LABEL_STYLE = args.fy_labels
    if args.no_analyze:
        config.ANALYSIS_ENABLED = False
    if args.dpi:
        config.CHART_DPI = args.dpi
    if args.exchange:
        config.EXCHANGE_SUFFIX = args.exchange
    if args.ml_split:
        config.ML_SPLIT = args.ml_split
    if args.no_ml:
        config.ML_ENABLED = False
    if args.no_overrides:
        config.USE_OVERRIDES = False
    if args.reasons == "off":
        config.SHOW_REASONS = False
    elif args.reasons:
        config.REASON_STYLE = args.reasons

    if args.offline:
        import mock_source

        config.OFFLINE = True
        ticker_resolver.resolve = mock_source.resolve

    # ---- input ----
    try:
        if args.offline:
            import mock_source

            companies = mock_source.COMPANIES
        elif args.input:
            companies = inputs.read_csv_input(args.input)
        elif config.DEFAULT_INPUT.exists():
            companies = inputs.read_csv_input(config.DEFAULT_INPUT)
        else:
            companies = inputs.read_terminal_input()
    except Exception as e:
        log.exception("input parsing failed")
        sys.exit(
            f"Could not read input: {type(e).__name__}: {e}\n" f"Traceback: {log_path}"
        )

    if not companies:
        sys.exit("No companies supplied.")

    extra = None
    if args.train_universe:
        if not os.path.exists(args.train_universe):
            sys.exit(f"File not found: {args.train_universe}")
        extra = inputs.read_csv_input(args.train_universe)

    try:
        if args.make_override_template:
            import tools.make_override_template as make_override_template

            make_override_template.build(companies)
        else:
            pipeline.run(companies, extra_training=extra)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        log.exception("fatal")
        print(f"\nFATAL: {type(e).__name__}: {e}\nTraceback: {log_path}")
        sys.exit(1)

    print(f"\nFull log: {log_path}")


if __name__ == "__main__":
    main()
