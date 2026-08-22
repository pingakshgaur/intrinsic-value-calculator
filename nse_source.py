"""
Direct NSE portal access (fallback price source when yfinance is thin/blocked).
NSE requires cookie priming; it also rate-limits aggressively. Everything here
is wrapped in try/except and returns None on failure so the pipeline never dies.
Only CLOSE prices are extracted - nothing else.
"""

import datetime as dt
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
        try:
            r = s.get(BASE + "/api/historical/cm/equity", params=params, timeout=20)
            rows = r.json().get("data", [])
        except Exception:
            rows = []
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
