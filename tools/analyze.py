# FILE: tools/analyze.py
"""
#!/usr/bin/env python3

Re-run the analysis stage over an already-exported results CSV.

The analyzer fires automatically at the end of `python run.py`. This wrapper
exists so you can regenerate charts without re-fetching anything, which is what
you want while iterating on the presentation.

    python tools/analyze.py
    python tools/analyze.py --dpi 300
    python tools/analyze.py output/Intrinsic_Value_Data.csv -o output/run7

Fully non-interactive: every argument has a default, nothing blocks on stdin.
"""

import argparse
import sys
from pathlib import Path

# Same bootstrap as run.py, and for the same reason: every module in this
# project is imported flat (`import config`), never as `src.config`. Mixing the
# two loads two separate copies of config and the CLI flags stop taking effect.
ROOT = Path(__file__).resolve().parents[1]
for sub in ("src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
import csv_analyzer  # noqa: E402


def main(argv=None):
    default_csv = config.OUTPUT_DIR / f"{config.DATA_BASENAME}.csv"

    ap = argparse.ArgumentParser(
        prog="analyze",
        description="Analyse the results grid and write HD charts.",
    )
    ap.add_argument(
        "csv",
        nargs="?",
        default=str(default_csv),
        help="results CSV (default: %(default)s)",
    )
    ap.add_argument(
        "-o",
        "--outdir",
        default=None,
        help="output folder (default: alongside the CSV)",
    )
    ap.add_argument(
        "--dpi",
        type=int,
        default=getattr(config, "CHART_DPI", 200),
        help="chart resolution; 200 is print quality (default: %(default)s)",
    )
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(
            f"Not found: {csv_path}\n" f"Run the pipeline first:  python run.py",
            file=sys.stderr,
        )
        return 2

    try:
        result = csv_analyzer.run_analysis(
            csv_path,
            Path(args.outdir) if args.outdir else None,
            dpi=args.dpi,
            quiet=args.quiet,
        )
    except Exception as e:
        print(f"[analyze] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"[analyze] open in a browser: {result['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
