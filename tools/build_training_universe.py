#!/usr/bin/env python3
# FILE: tools/build_training_universe.py
"""
Build data/training_universe.csv - the extra companies the machine-learning
models (and so the Hybrid's ML component) train on.

    python tools/build_training_universe.py
    python tools/build_training_universe.py --include-financials
    python tools/build_training_universe.py --max-per-sector 15
    python tools/build_training_universe.py --from-dir path/to/csvs   # offline

Then:

    python run.py --train-universe data/training_universe.csv

WHERE THE LIST COMES FROM

NSE's own index constituent files on niftyindices.com, which are published
for download:

    ind_nifty500list.csv          name, industry, symbol     (the universe)
    ind_nifty100list.csv          -> market cap "Large"
    ind_niftymidcap150list.csv    -> market cap "Mid"
    ind_niftysmallcap250list.csv  -> market cap "Small"

That is the same top-100 / next-150 / rest split AMFI uses for its large,
mid and small cap categories, so the cap column is the official one rather
than a guess from a rupee cut-off.

Screener.in is deliberately NOT scraped: its robots.txt disallows the
paginated and sorted result pages, and its terms forbid copying its
material. If you want a Screener screen as the universe, export it from your
own logged-in account and pass the file to run.py yourself.

WHAT THE SCRIPT DOES TO THE LIST

  * Industry names are mapped onto the sector names data/companies.csv
    already uses (NSE's "Metals & Mining" -> "Metals and Mining", and so on),
    so the ML sector indicators line up between the two files. Industries
    with no counterpart keep NSE's name.
  * Every company already in data/companies.csv is removed (matched on
    ticker). run.py would otherwise fetch it twice and count it twice in
    the training data.
  * Financial Services is left out unless --include-financials is given.
    Banks and NBFCs do not report EBITDA, capex or operating cash flow in
    the form the 21 ML features need, so most of their rows would be
    imputed noise - and the main sample values no lenders.

The output has exactly the four companies.csv columns:
    company name,sector name,market cap,ticker
"""

import argparse
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://www.niftyindices.com/IndexConstituent/"

UNIVERSE_FILE = "ind_nifty500list.csv"
CAP_FILES = {
    "ind_nifty100list.csv": "Large",
    "ind_niftymidcap150list.csv": "Mid",
    "ind_niftysmallcap250list.csv": "Small",
}

# NSE industry -> the sector names used in data/companies.csv
SECTOR_MAP = {
    "Automobile and Auto Components": "Automobiles and Auto Components",
    "Fast Moving Consumer Goods": "Fast Moving Consumer Goods",
    "Information Technology": "Information Technology",
    "Healthcare": "Healthcare and Medical Devices",
    "Metals & Mining": "Metals and Mining",
    "Power": "Power and Renewable Energy",
}

FINANCIAL = "Financial Services"


def _read_text(name, from_dir):
    if from_dir:
        path = Path(from_dir) / name
        return path.read_text(encoding="utf-8-sig")
    import requests

    sys.path.insert(0, str(ROOT / "src"))
    import ssl_trust

    ssl_trust.install()
    r = requests.get(
        BASE_URL + name, headers={"User-Agent": "Mozilla/5.0"}, timeout=30
    )
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def _rows(text):
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _existing_tickers(path):
    if not path or not Path(path).exists():
        return set()
    out = set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip().upper()
            if t:
                out.add(t.split(".")[0])
    return out


def build(args):
    universe = _rows(_read_text(UNIVERSE_FILE, args.from_dir))
    cap_of = {}
    for fname, label in CAP_FILES.items():
        for row in _rows(_read_text(fname, args.from_dir)):
            cap_of.setdefault(row["Symbol"].upper(), label)

    skip = _existing_tickers(args.exclude)
    out, dropped = [], {"already in main list": 0, "financial services": 0}
    per_sector = {}

    for row in universe:
        sym = row["Symbol"].upper()
        industry = row["Industry"]
        if row.get("Series", "EQ") != "EQ":
            continue
        if sym in skip:
            dropped["already in main list"] += 1
            continue
        if industry == FINANCIAL and not args.include_financials:
            dropped["financial services"] += 1
            continue

        sector = SECTOR_MAP.get(industry, industry)
        if args.max_per_sector and per_sector.get(sector, 0) >= args.max_per_sector:
            continue
        per_sector[sector] = per_sector.get(sector, 0) + 1

        out.append(
            {
                "company name": row["Company Name"],
                "sector name": sector,
                "market cap": cap_of.get(sym, "Small"),
                "ticker": f"{sym}.NS",
            }
        )

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["company name", "sector name", "market cap", "ticker"]
        )
        w.writeheader()
        w.writerows(out)

    print(f"[universe] {len(universe)} NIFTY 500 constituents read")
    for why, n in dropped.items():
        if n:
            print(f"[universe] skipped {n} ({why})")
    print(f"[universe] {len(out)} companies -> {dest}")
    caps = {}
    for r in out:
        caps[r["market cap"]] = caps.get(r["market cap"], 0) + 1
    print("[universe] caps: " + ", ".join(f"{k} {v}" for k, v in sorted(caps.items())))
    print("[universe] sectors:")
    for s, n in sorted(per_sector.items(), key=lambda x: -x[1]):
        print(f"   {n:4d}  {s}")
    print(
        f"\nNext:  python run.py --train-universe {dest.relative_to(ROOT) if dest.is_relative_to(ROOT) else dest}"
    )
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "data" / "training_universe.csv"))
    ap.add_argument(
        "--exclude",
        default=str(ROOT / "data" / "companies.csv"),
        help="companies already valued; their tickers are left out",
    )
    ap.add_argument("--include-financials", action="store_true")
    ap.add_argument(
        "--max-per-sector",
        type=int,
        default=0,
        help="cap each sector, for a quicker first run (0 = no cap)",
    )
    ap.add_argument(
        "--from-dir", help="read the four NSE CSVs from this folder instead of downloading"
    )
    args = ap.parse_args(argv)
    try:
        build(args)
    except Exception as e:
        print(f"[universe] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
