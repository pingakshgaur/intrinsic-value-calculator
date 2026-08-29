# FILE: run.py
"""
+#!/usr/bin/env python3

Intrinsic Value Calculator - entry point.

    python run.py
    python run.py --gui                        # open the desktop window
    python run.py --input data/companies.csv
    python run.py --no-ml --reasons short
    python run.py --benchmark-basis mean       # robustness re-run
    python run.py --no-analyze                 # skip charts
    python run.py --make-override-template     # writes the fill-in sheet
    python run.py --screen-only                # sufficiency dry run, no valuation
    python run.py --min-complete-fy 3          # loosen the gate for one run
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


def build_parser():
    ap = argparse.ArgumentParser(description="Intrinsic value engine (FY2021-FY2025)")
    ap.add_argument(
        "--gui",
        action="store_true",
        help="open the desktop window instead of running in the terminal",
    )
    ap.add_argument("--input", help="path to companies CSV")
    ap.add_argument("--mean-basis", choices=["trading", "calendar"])
    ap.add_argument(
        "--benchmark-basis",
        choices=["may1", "mean", "close"],
        help=(
            "how the benchmark market price is drawn. 'may1' (default) takes "
            "the close on the trading day nearest 1 May following FY end; "
            "'mean' and 'close' aggregate the whole following FY and exist "
            "only as robustness re-runs"
        ),
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

    # ---- data-sufficiency gate ----
    ap.add_argument(
        "--screening",
        choices=["enforce", "report", "off"],
        help=(
            "'enforce' drops companies with insufficient reported data; "
            "'report' lists them without dropping anyone; 'off' disables "
            "the check entirely"
        ),
    )
    ap.add_argument(
        "--min-complete-fy",
        type=int,
        help="financial years of complete reported fundamentals required to stay in",
    )
    ap.add_argument(
        "--min-benchmark-fy",
        type=int,
        help="financial years that must carry a benchmark price",
    )
    ap.add_argument(
        "--screen-only",
        action="store_true",
        help=(
            "fetch and screen, print the verdict, write the exclusion sheet, "
            "then stop. Use this to calibrate the threshold before it starts "
            "deleting companies"
        ),
    )
    return ap


def apply_args(args):
    """Push CLI flags onto config. Shared with the GUI, which builds the same
    namespace from its widgets."""
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

    if args.screening == "off":
        config.SUFFICIENCY_ENABLED = False
    elif args.screening == "report":
        config.SUFFICIENCY_ENABLED = True
        config.SUFFICIENCY_MODE = "report_only"
    elif args.screening == "enforce":
        config.SUFFICIENCY_ENABLED = True
        config.SUFFICIENCY_MODE = "enforce"

    if args.min_complete_fy:
        config.MIN_COMPLETE_FY = args.min_complete_fy
    if args.min_benchmark_fy:
        config.MIN_BENCHMARK_FY = args.min_benchmark_fy


def load_companies(args):
    if args.offline:
        import mock_source

        return mock_source.COMPANIES
    if args.input:
        return inputs.read_csv_input(args.input)
    if config.DEFAULT_INPUT.exists():
        return inputs.read_csv_input(config.DEFAULT_INPUT)
    return inputs.read_terminal_input()


def main():
    log_path = setup_logging()
    args = build_parser().parse_args()

    if args.gui:
        try:
            import gui
        except ImportError as e:
            sys.exit(
                f"GUI unavailable: {e}\n"
                "Install the toolkit with:  pip install ttkbootstrap"
            )
        gui.launch()
        return

    apply_args(args)

    if args.offline:
        import mock_source

        config.OFFLINE = True
        ticker_resolver.resolve = mock_source.resolve

    # ---- input ----
    try:
        companies = load_companies(args)
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
        elif args.screen_only:
            pipeline.screen_only(companies)
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
