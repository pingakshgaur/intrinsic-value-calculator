"""
Generate a fill-in sheet for every missing fundamental.

    python run.py --make-override-template

Writes data/fundamentals_override.csv with one row per company-year, values
already filled where yfinance had them and BLANK where it did not. Fill the
blanks from Screener.in or the annual report, save, and re-run normally.
"""

import csv
import time

import config
import ticker_resolver
import yf_source
import overrides

def build(companies):
    config.USE_OVERRIDES = False  # fetch the raw picture first
    existing = {}
    if config.OVERRIDE_FILE.exists():
        config.USE_OVERRIDES = True
        existing = dict(overrides.load())
        config.USE_OVERRIDES = False

    rows, blanks = [], 0
    for c in companies:
        name = c["name"]
        ticker = ticker_resolver.resolve(name, c.get("ticker"))
        if not ticker:
            print(f"[skip] {name}: no ticker")
            continue
        print(f"[scan] {name} ...", end=" ", flush=True)
        try:
            data = yf_source.fetch_company(ticker, config.FY_LIST)
        except Exception as e:
            print(f"FAILED ({type(e).__name__})")
            continue

        missing_here = 0
        for fy in config.FY_LIST:
            d = data["years"].get(fy, {})
            prior = existing.get((ticker.upper(), fy), {})
            row = {"ticker": ticker, "fy": fy}
            for fld in overrides.FIELDS:
                v = d.get(fld)
                if v is None:
                    v = prior.get(fld)
                if v is None:
                    row[fld] = ""
                    missing_here += 1
                else:
                    row[fld] = round(float(v), 4)
            rows.append(row)
        blanks += missing_here
        print(f"{missing_here} blank cell(s)")
        time.sleep(config.REQUEST_PAUSE)

    config.OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.OVERRIDE_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=overrides.HEADER)
        w.writeheader()
        w.writerows(rows)

    print(f"\n[template] {len(rows)} company-year rows, {blanks} blank cells")
    print(f"[template] -> {config.OVERRIDE_FILE}")
    print("\nFill the blanks from Screener.in (Profit & Loss / Balance Sheet /")
    print("Cash Flow tabs) in ABSOLUTE RUPEES, then re-run:  python run.py")
