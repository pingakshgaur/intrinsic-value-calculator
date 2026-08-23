"""
screener.py - builds companies.csv by screening a candidate universe.

    python screener.py                     # run the screen with default thresholds
    python screener.py --relax             # walk the relaxation ladder if too few pass
    python screener.py --per-bucket 2      # names per (sector x cap) bucket
    python screener.py --universe my.csv   # screen your own list instead
    python screener.py --report-only       # write the report, don't touch companies.csv

Outputs
    companies.csv                     -> input for main.py (same 4-column format)
    output/screening_report.csv       -> EVERY candidate, every metric, every
                                         pass/fail reason. This is your audit trail;
                                         cite it in your methodology.

Honest scope note: ROCE, P/E, D/E and price data come from yfinance. FII holding
does NOT - see FII_NOTE below. Read the caveats printed at the end of the run.
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
import datetime as dt

import pandas as pd
import yfinance as yf

try:
    import config
except ImportError:  # standalone fallback

    class config:
        FY_LIST = [2021, 2022, 2023, 2024, 2025]
        OUTPUT_DIR = "output"
        CACHE_DIR = ".cache"
        REQUEST_PAUSE = 0.6


log = logging.getLogger("screener")

# ======================================================================
# THRESHOLDS - edit these, they are your stated methodology
# ======================================================================
THRESHOLDS = {
    "roce_min": 18.0,  # %, must hold in every year checked
    "roce_min_years": 4,  # how many FYs must clear it (see DEPTH NOTE)
    "pe_max": 20.0,
    "down_from_high_min": 25.0,  # %, "trading near the lows"
    "de_max": 1.0,
    "sales_cagr_min": 5.0,  # %
    "min_fy_complete": 4,  # FYs with usable fundamentals
    "mcap_min_cr": 300.0,
}

# Relaxation ladder, applied in order by --relax until buckets fill.
RELAX_LADDER = [
    ("down_from_high_min", 0.0, "dropped the near-the-lows condition"),
    ("pe_max", 30.0, "P/E ceiling raised to 30"),
    ("roce_min", 15.0, "ROCE floor lowered to 15%"),
    ("pe_max", 40.0, "P/E ceiling raised to 40"),
    ("roce_min", 12.0, "ROCE floor lowered to 12%"),
    ("sales_cagr_min", 0.0, "sales growth condition dropped"),
]

# Market-cap buckets in Rs crore. Approximates AMFI's top-100 / 101-250 / 251+
# rule with absolute cut-offs. State whichever definition you use.
CAP_LARGE_MIN_CR = 50_000.0
CAP_MID_MIN_CR = 15_000.0

FII_NOTE = (
    "yfinance exposes no FII/DII split for Indian listings. The "
    "'fii_pct_unverified' column is Yahoo's generic institutional-holding "
    "field and is frequently blank or wrong for NSE/BSE scrips. Verify FII "
    "holding manually on screener.in or trendlyne.com before relying on it."
)

DEPTH_NOTE = (
    "yfinance publishes roughly the latest 4 annual statements, so a "
    "strict 5-year ROCE test is usually impossible. roce_min_years "
    "defaults to 4. Raise it to 5 only if you supply older fundamentals."
)

# ======================================================================
# CANDIDATE UNIVERSE - a seed list, not the whole exchange. Extend freely.
# ======================================================================
UNIVERSE = {
    "Defence and Aerospace": [
        "HAL.NS",
        "BEL.NS",
        "BDL.NS",
        "MAZDOCK.NS",
        "COCHINSHIP.NS",
        "GRSE.NS",
        "SOLARINDS.NS",
        "BHARATFORG.NS",
        "DATAPATTNS.NS",
        "MTARTECH.NS",
        "ZENTEC.NS",
        "ASTRAMICRO.NS",
        "PARAS.NS",
        "APOLLO.NS",
        "IDEAFORGE.NS",
        "DYNAMATECH.NS",
        "AZAD.NS",
        "UNIMECH.NS",
        "TASTYBITE.NS",
    ],
    "Power and Renewable Energy": [
        "NTPC.NS",
        "POWERGRID.NS",
        "TATAPOWER.NS",
        "JSWENERGY.NS",
        "NHPC.NS",
        "SJVN.NS",
        "TORNTPOWER.NS",
        "CESC.NS",
        "ADANIGREEN.NS",
        "ADANIPOWER.NS",
        "SUZLON.NS",
        "INOXWIND.NS",
        "KPIGREEN.NS",
        "INOXGREEN.NS",
        "WAAREEENER.NS",
        "PREMIERENE.NS",
        "GREENPOWER.NS",
        "JPPOWER.NS",
    ],
    "Semiconductor and Electronics Manufacturing": [
        "DIXON.NS",
        "KAYNES.NS",
        "SYRMA.NS",
        "AVALON.NS",
        "CENTUM.NS",
        "AMBER.NS",
        "PGEL.NS",
        "CYIENTDLM.NS",
        "MOSCHIP.NS",
        "TATAELXSI.NS",
        "ELIN.NS",
        "OPTIEMUS.NS",
        "EPACK.NS",
        "517035.BO",
    ],
    "Capital Goods and Industrial Manufacturing": [
        "LT.NS",
        "SIEMENS.NS",
        "ABB.NS",
        "CUMMINSIND.NS",
        "CARBORUNIV.NS",
        "THERMAX.NS",
        "AIAENG.NS",
        "GRINDWELL.NS",
        "TIMKEN.NS",
        "SKFINDIA.NS",
        "SCHAEFFLER.NS",
        "ELGIEQUIP.NS",
        "KIRLOSENG.NS",
        "KIRLOSBROS.NS",
        "TDPOWERSYS.NS",
        "BEML.NS",
        "GMMPFAUDLR.NS",
        "KSB.NS",
        "TRITURBINE.NS",
        "ESABINDIA.NS",
        "POWERINDIA.NS",
        "BHEL.NS",
    ],
    "Healthcare and Medical Devices": [
        "APOLLOHOSP.NS",
        "FORTIS.NS",
        "MAXHEALTH.NS",
        "NH.NS",
        "KIMS.NS",
        "ASTERDM.NS",
        "RAINBOW.NS",
        "YATHARTH.NS",
        "INDRAMEDCO.NS",
        "GLOBALHLTH.NS",
        "HCG.NS",
        "SHALBY.NS",
        "KRSNAA.NS",
        "VIJAYA.NS",
        "METROPOLIS.NS",
        "DRLALPATHLABS.NS",
        "THYROCARE.NS",
        "POLYMED.NS",
        "TARSONS.NS",
    ],
}

# ======================================================================
# yfinance extraction - only the fields the screen consumes
# ======================================================================
ALIASES = {
    "ebit": ["EBIT", "Operating Income", "Total Operating Income As Reported"],
    "revenue": ["Total Revenue", "Operating Revenue"],
    "eps": ["Diluted EPS", "Basic EPS"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
    "assets": ["Total Assets"],
    "cur_liab": ["Current Liabilities", "Total Current Liabilities"],
    "equity": ["Stockholders Equity", "Total Equity Gross Minority Interest"],
    "debt": ["Total Debt", "Long Term Debt And Capital Lease Obligation"],
}


def _num(x):
    try:
        v = float(x)
        return None if (pd.isna(v) or v in (float("inf"), float("-inf"))) else v
    except (TypeError, ValueError):
        return None


def _row(df, keys):
    if df is None or df.empty:
        return None
    for k in keys:
        if k in df.index:
            return df.loc[k]
    return None


def _col_for_fy(df, fy, tol=100):
    if df is None or df.empty:
        return None
    target = pd.Timestamp(dt.date(fy, 3, 31))
    best, gap = None, None
    for c in df.columns:
        try:
            ts = pd.Timestamp(c).tz_localize(None)
        except Exception:
            continue
        g = abs((ts - target).days)
        if gap is None or g < gap:
            best, gap = c, g
    return best if (best is not None and gap <= tol) else None


def _val(df, key, col):
    r = _row(df, ALIASES[key])
    if r is None or col is None or col not in r.index:
        return None
    return _num(r[col])


def _cache_path(ticker):
    return os.path.join(config.CACHE_DIR, "screen", ticker.replace(".", "_") + ".json")


def _load_cache(ticker, max_age_hours=24):
    p = _cache_path(ticker)
    if not os.path.exists(p):
        return None
    age = (time.time() - os.path.getmtime(p)) / 3600.0
    if age > max_age_hours:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(ticker, payload):
    p = _cache_path(ticker)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        log.warning("cache write failed for %s", ticker)


def fetch_metrics(ticker, sector, use_cache=True):
    """Return a flat metrics dict. Never raises."""
    if use_cache:
        cached = _load_cache(ticker)
        if cached:
            cached["sector"] = sector
            cached["from_cache"] = True
            return cached

    m = {
        "ticker": ticker,
        "sector": sector,
        "name": "",
        "from_cache": False,
        "errors": [],
        "notes": [],
    }
    try:
        t = yf.Ticker(ticker)

        try:
            info = t.info or {}
        except Exception as e:
            info = {}
            m["errors"].append(f"info block unavailable ({type(e).__name__})")

        m["name"] = (
            info.get("longName") or info.get("shortName") or ticker.split(".")[0]
        )

        def stmt(attr, label):
            try:
                df = getattr(t, attr)
                if df is None or df.empty:
                    m["errors"].append(f"{label} empty")
                    return None
                return df
            except Exception as e:
                m["errors"].append(f"{label} failed ({type(e).__name__})")
                return None

        inc = stmt("income_stmt", "income statement")
        bs = stmt("balance_sheet", "balance sheet")

        # ---- price, 52w high, drawdown ----
        price = high52 = None
        try:
            h = t.history(period="1y", auto_adjust=False)
            if h is not None and not h.empty:
                price = _num(h["Close"].iloc[-1])
                high52 = _num(h["High"].max())
        except Exception as e:
            m["errors"].append(f"price history failed ({type(e).__name__})")
        price = price or _num(info.get("currentPrice"))
        high52 = high52 or _num(info.get("fiftyTwoWeekHigh"))
        m["price"] = price
        m["high_52w"] = high52
        m["down_from_high_pct"] = (
            round((high52 - price) / high52 * 100, 2)
            if (price and high52 and high52 > 0)
            else None
        )

        # ---- market cap (Rs crore) ----
        mc = _num(info.get("marketCap"))
        m["mcap_cr"] = round(mc / 1e7, 1) if mc else None

        # ---- ROCE per FY = EBIT / (Total Assets - Current Liabilities) ----
        roce, rev = {}, {}
        complete = 0
        for fy in config.FY_LIST:
            ic, bc = _col_for_fy(inc, fy), _col_for_fy(bs, fy)
            ebit = _val(inc, "ebit", ic)
            assets = _val(bs, "assets", bc)
            cl = _val(bs, "cur_liab", bc)
            rv = _val(inc, "revenue", ic)
            if rv is not None:
                rev[fy] = rv
            if ebit is not None and assets is not None and cl is not None:
                ce = assets - cl
                roce[fy] = round(ebit / ce * 100, 2) if ce > 0 else None
            else:
                roce[fy] = None
            if ebit is not None and rv is not None and assets is not None:
                complete += 1
        m["roce_by_fy"] = roce
        m["fy_complete"] = complete
        vals = [v for v in roce.values() if v is not None]
        m["roce_years_available"] = len(vals)
        m["roce_min_observed"] = round(min(vals), 2) if vals else None
        m["roce_avg"] = round(sum(vals) / len(vals), 2) if vals else None

        # ---- sales CAGR over available span ----
        ys = sorted(rev)
        if len(ys) >= 2 and rev[ys[0]] > 0:
            n = ys[-1] - ys[0]
            m["sales_cagr_pct"] = (
                round(((rev[ys[-1]] / rev[ys[0]]) ** (1 / n) - 1) * 100, 2)
                if n
                else None
            )
        else:
            m["sales_cagr_pct"] = None

        # ---- P/E ----
        pe = _num(info.get("trailingPE"))
        if pe is None:
            latest_eps = None
            for fy in sorted(config.FY_LIST, reverse=True):
                latest_eps = _val(inc, "eps", _col_for_fy(inc, fy))
                if latest_eps:
                    break
            if price and latest_eps and latest_eps > 0:
                pe = price / latest_eps
                m["notes"].append("P/E derived from latest FY EPS, not TTM")
        m["pe"] = round(pe, 2) if pe else None

        # ---- debt / equity, latest available FY ----
        de = None
        for fy in sorted(config.FY_LIST, reverse=True):
            bc = _col_for_fy(bs, fy)
            d, e = _val(bs, "debt", bc), _val(bs, "equity", bc)
            if e and e > 0:
                de = (d or 0.0) / e
                break
        m["de_ratio"] = round(de, 2) if de is not None else None

        # ---- FII: not actually available, see FII_NOTE ----
        inst = _num(info.get("heldPercentInstitutions"))
        m["fii_pct_unverified"] = round(inst * 100, 2) if inst else None

    except Exception as e:
        log.exception("fetch_metrics crashed for %s", ticker)
        m["errors"].append(f"fatal: {type(e).__name__}: {e}")

    _save_cache(ticker, m)
    return m


# ======================================================================
# Screening
# ======================================================================
def cap_bucket(mcap_cr):
    if mcap_cr is None:
        return None
    if mcap_cr >= CAP_LARGE_MIN_CR:
        return "Large"
    if mcap_cr >= CAP_MID_MIN_CR:
        return "Mid"
    return "Small"


def evaluate(m, th):
    """Attach pass/fail verdict and the reason for each failed criterion."""
    fails = []

    if m.get("fy_complete", 0) < th["min_fy_complete"]:
        fails.append(
            f"only {m.get('fy_complete', 0)} FY(s) of usable fundamentals "
            f"(need {th['min_fy_complete']})"
        )

    n_ok = th["roce_min_years"]
    got = m.get("roce_years_available", 0)
    if got < n_ok:
        fails.append(f"ROCE computable for only {got} FY(s) (need {n_ok})")
    else:
        below = {
            fy: v
            for fy, v in (m.get("roce_by_fy") or {}).items()
            if v is not None and v < th["roce_min"]
        }
        if below:
            worst = min(below.items(), key=lambda x: x[1])
            fails.append(
                f"ROCE below {th['roce_min']}% in FY{worst[0]} " f"({worst[1]}%)"
            )

    pe = m.get("pe")
    if pe is None:
        fails.append("P/E unavailable (loss-making or EPS missing)")
    elif pe > th["pe_max"]:
        fails.append(f"P/E {pe} above ceiling {th['pe_max']}")

    dfh = m.get("down_from_high_pct")
    if th["down_from_high_min"] > 0:
        if dfh is None:
            fails.append("drawdown from 52w high not computable")
        elif dfh < th["down_from_high_min"]:
            fails.append(
                f"only {dfh}% off 52w high " f"(need {th['down_from_high_min']}%)"
            )

    de = m.get("de_ratio")
    if de is not None and de > th["de_max"]:
        fails.append(f"debt/equity {de} above {th['de_max']}")

    sg = m.get("sales_cagr_pct")
    if th["sales_cagr_min"] > 0:
        if sg is None:
            fails.append("sales growth not computable")
        elif sg < th["sales_cagr_min"]:
            fails.append(f"sales CAGR {sg}% below {th['sales_cagr_min']}%")

    mc = m.get("mcap_cr")
    if mc is None:
        fails.append("market cap unavailable")
    elif mc < th["mcap_min_cr"]:
        fails.append(f"market cap Rs {mc} cr below Rs {th['mcap_min_cr']} cr")

    m["cap_bucket"] = cap_bucket(mc)
    m["fail_reasons"] = fails
    m["passes"] = not fails
    return m


def rank_key(m):
    """Best first: highest minimum ROCE, then cheapest, then deepest drawdown."""
    return (
        -(m.get("roce_min_observed") or -999),
        m.get("pe") or 9999,
        -(m.get("down_from_high_pct") or 0),
    )


def select_buckets(passing, per_bucket):
    chosen, shortfalls = [], []
    for sector in UNIVERSE:
        for cap in ("Large", "Mid", "Small"):
            pool = sorted(
                [
                    m
                    for m in passing
                    if m["sector"] == sector and m["cap_bucket"] == cap
                ],
                key=rank_key,
            )
            chosen.extend(pool[:per_bucket])
            if len(pool) < per_bucket:
                shortfalls.append((sector, cap, len(pool), per_bucket))
    return chosen, shortfalls


# ======================================================================
# Output
# ======================================================================
REPORT_COLS = [
    "ticker",
    "name",
    "sector",
    "cap_bucket",
    "mcap_cr",
    "price",
    "high_52w",
    "down_from_high_pct",
    "pe",
    "roce_min_observed",
    "roce_avg",
    "roce_years_available",
    "sales_cagr_pct",
    "de_ratio",
    "fy_complete",
    "fii_pct_unverified",
    "passes",
    "fail_reasons",
    "notes",
    "errors",
]


def write_report(all_metrics):
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, "screening_report.csv")
    rows = []
    for m in all_metrics:
        r = {c: m.get(c) for c in REPORT_COLS}
        for fy in config.FY_LIST:
            r[f"ROCE_FY{fy}"] = (m.get("roce_by_fy") or {}).get(fy)
        r["fail_reasons"] = " | ".join(m.get("fail_reasons") or [])
        r["notes"] = " | ".join(m.get("notes") or [])
        r["errors"] = " | ".join(m.get("errors") or [])
        rows.append(r)
    cols = REPORT_COLS + [f"ROCE_FY{fy}" for fy in config.FY_LIST]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def write_companies_csv(chosen, path="companies.csv"):
    if os.path.exists(path):
        backup = path + ".bak"
        try:
            os.replace(path, backup)
            print(f"[backup] previous {path} moved to {backup}")
        except Exception as e:
            print(f"[backup] could not back up {path}: {e}")
    order = {s: i for i, s in enumerate(UNIVERSE)}
    cap_order = {"Large": 0, "Mid": 1, "Small": 2}
    chosen = sorted(
        chosen,
        key=lambda m: (
            order.get(m["sector"], 99),
            cap_order.get(m["cap_bucket"], 9),
            rank_key(m),
        ),
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company name", "sector name", "market cap", "ticker"])
        for m in chosen:
            w.writerow([m["name"], m["sector"], m["cap_bucket"], m["ticker"]])
    return path


# ======================================================================
def load_universe(path):
    uni = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            row = {
                (k or "").strip().lower(): (v or "").strip()
                for k, v in row.items()
                if isinstance(v, str) or v is None
            }
            tk, sec = row.get("ticker"), row.get("sector name") or row.get("sector")
            if tk and sec:
                uni.setdefault(sec, []).append(tk)
    return uni


def main():
    ap = argparse.ArgumentParser(description="Screen a universe into companies.csv")
    ap.add_argument("--per-bucket", type=int, default=2)
    ap.add_argument(
        "--relax",
        action="store_true",
        help="loosen thresholds step by step until buckets fill",
    )
    ap.add_argument("--universe", help="CSV with ticker + sector name columns")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--out", default="companies.csv")
    args = ap.parse_args()

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(
                os.path.join(config.OUTPUT_DIR, "screener_log.txt"),
                mode="w",
                encoding="utf-8",
            )
        ],
    )
    logging.getLogger("yfinance").setLevel(logging.ERROR)

    global UNIVERSE
    if args.universe:
        UNIVERSE = load_universe(args.universe)

    total = sum(len(v) for v in UNIVERSE.values())
    print(f"Screening {total} candidates across {len(UNIVERSE)} sectors.\n")

    metrics = []
    i = 0
    for sector, tickers in UNIVERSE.items():
        for tk in tickers:
            i += 1
            print(f"[{i:3d}/{total}] {tk:16s}", end=" ", flush=True)
            m = fetch_metrics(tk, sector, use_cache=not args.no_cache)
            metrics.append(m)
            tag = "cached" if m.get("from_cache") else "fetched"
            roce = m.get("roce_min_observed")
            print(
                f"{tag:8s} ROCEmin={roce if roce is not None else '--':>7} "
                f"P/E={m.get('pe') or '--':>7} "
                f"cap={m.get('cap_bucket') or '--'}"
            )
            if not m.get("from_cache"):
                time.sleep(config.REQUEST_PAUSE)

    th = dict(THRESHOLDS)
    applied = []
    for step in range(len(RELAX_LADDER) + 1):
        for m in metrics:
            evaluate(m, th)
        passing = [m for m in metrics if m["passes"]]
        chosen, shortfalls = select_buckets(passing, args.per_bucket)
        if not shortfalls or not args.relax or step == len(RELAX_LADDER):
            break
        key, val, desc = RELAX_LADDER[step]
        th[key] = val
        applied.append(desc)
        print(f"\n[relax] {len(chosen)}/{args.per_bucket * 15} slots filled -> {desc}")

    report = write_report(metrics)
    print(f"\n[report] {len(metrics)} candidates -> {report}")

    print(
        f"\n[result] {len(passing)} passed the screen; "
        f"{len(chosen)} selected across buckets"
    )
    if applied:
        print("[relax]  thresholds applied: " + "; ".join(applied))
    if shortfalls:
        print("\n[shortfall] buckets that could not be filled:")
        for sec, cap, got, want in shortfalls:
            print(f"   {sec} / {cap}: {got} of {want}")
        print("   -> extend UNIVERSE for these buckets, or run with --relax")

    if args.report_only:
        print("\n[skip] --report-only: companies.csv left untouched")
    elif chosen:
        out = write_companies_csv(chosen, args.out)
        print(f"\n[written] {len(chosen)} companies -> {out}")
        for m in chosen:
            print(
                f"   {m['cap_bucket']:5s} {m['name'][:42]:44s} "
                f"ROCEmin {m.get('roce_min_observed')}%  P/E {m.get('pe')}"
            )
    else:
        print("\n[written] nothing passed - companies.csv not modified")

    print("\n--- caveats ---")
    print(" *", DEPTH_NOTE)
    print(" *", FII_NOTE)
    print(" * Selecting on low P/E and drawdown biases the valuation study toward")
    print("   'undervalued' findings. Keep the screened set as a labelled")
    print("   sub-sample, not as your only dataset.")
    print(f"\nLog: {os.path.join(config.OUTPUT_DIR, 'screener_log.txt')}")


if __name__ == "__main__":
    main()
