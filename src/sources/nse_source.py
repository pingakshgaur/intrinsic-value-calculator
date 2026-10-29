# FILE: src/sources/nse_source.py
"""
Direct NSE portal access: daily closes and the last price (fallbacks when
Yahoo Finance is thin or blocked - see price_chain), and the index
constituent lists with each company's industry (the sector directory the
watchlists import whole sectors from - see server/directory.py).
NSE requires cookie priming; it also rate-limits aggressively. Everything here
is wrapped in try/except and returns None on failure so the pipeline never dies.
"""

import csv
import datetime as dt
import io
import time
import requests
import pandas as pd
import config
from fy_utils import num

BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quotes/equity",
}

_session = None


def _get_session():
    global _session
    if _session is not None:
        return _session
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(BASE, timeout=15)
        time.sleep(config.REQUEST_PAUSE)
        s.get(BASE + "/get-quotes/equity?symbol=SBIN", timeout=15)
    except Exception:
        pass
    _session = s
    return s


def _symbol(ticker: str) -> str:
    """RELIANCE.NS -> RELIANCE"""
    return ticker.split(".")[0].upper()


def fetch_close_series(ticker: str, start: dt.date, end: dt.date):
    """Return pd.Series of daily closes indexed by date, or None."""
    s = _get_session()
    sym = _symbol(ticker)
    frames = []
    cursor = start
    while cursor < end:  # NSE caps each call at ~1 year
        stop = min(cursor + dt.timedelta(days=350), end)
        params = {
            "symbol": sym,
            "series": '["EQ"]',
            "from": cursor.strftime("%d-%m-%Y"),
            "to": stop.strftime("%d-%m-%Y"),
        }
        rows = []
        # the newer endpoint first; the older one still answers for some symbols
        for path in ("/api/historicalOR/cm/equity", "/api/historical/cm/equity"):
            try:
                r = s.get(BASE + path, params=params, timeout=20)
                rows = r.json().get("data", [])
            except Exception:
                rows = []
            if rows:
                break
        for row in rows:
            d = row.get("CH_TIMESTAMP") or row.get("mTIMESTAMP")
            c = num(row.get("CH_CLOSING_PRICE"))
            if d and c:
                frames.append((pd.to_datetime(d).date(), c))
        cursor = stop + dt.timedelta(days=1)
        time.sleep(config.REQUEST_PAUSE)

    if not frames:
        return None
    ser = pd.Series({d: c for d, c in frames}).sort_index()
    ser.index = pd.to_datetime(ser.index)
    return ser


def fetch_last_price(ticker: str):
    """Single spot price. Only lastPrice is read from the payload."""
    s = _get_session()
    try:
        r = s.get(
            BASE + "/api/quote-equity", params={"symbol": _symbol(ticker)}, timeout=20
        )
        return num(r.json().get("priceInfo", {}).get("lastPrice"))
    except Exception:
        return None


ARCHIVES = "https://nsearchives.nseindia.com/content/indices/"
# broadest first: the Total Market index holds ~750 companies, the Nifty 500 its core
INDEX_LISTS = ("ind_niftytotalmarket_list.csv", "ind_nifty500list.csv", "ind_niftymicrocap250_list.csv")


def index_list(file_name):
    """One of NSE's published index lists (e.g. ind_nifty50list.csv).
    -> [{"name", "industry", "symbol"}], or [] when NSE did not answer."""
    out = []
    try:
        r = _get_session().get(ARCHIVES + file_name, timeout=20)
        if r.status_code != 200 or "Symbol" not in r.text[:400]:
            return []
        for row in csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))):
            sym = (row.get("Symbol") or "").strip().upper()
            if sym:
                out.append({"name": (row.get("Company Name") or sym).strip(),
                            "industry": (row.get("Industry") or "").strip(), "symbol": sym})
    except Exception:
        return []
    return out


def index_constituents():
    """-> [{"name", "industry", "symbol"}] from NSE's broad index lists, de-duplicated, or [] on failure."""
    seen, out = set(), []
    for name in INDEX_LISTS:
        for row in index_list(name):
            if row["symbol"] not in seen:
                seen.add(row["symbol"])
                out.append(row)
    return out
