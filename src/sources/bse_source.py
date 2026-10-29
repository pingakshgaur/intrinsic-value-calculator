# FILE: src/sources/bse_source.py
"""
BSE India website: daily closes and the last price, by BSE scrip code.

The website's JSON endpoints are unofficial (they serve bseindia.com's own
pages) and need a browser-like Referer. An NSE symbol is first turned into a
scrip code through the site's search box endpoint; codes are cached in
.cache/bse_codes.json. A numeric ticker ("500325" or "500325.BO") is taken as
a scrip code directly. Every call returns None on failure.
"""

import datetime as dt
import json
import logging
import re
import time

import pandas as pd
import requests

import config
from fy_utils import num

log = logging.getLogger(__name__)
API = "https://api.bseindia.com/BseIndiaAPI/api"
SEARCH = "https://api.bseindia.com/Msource/1D/getQouteSearch.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
CODES = config.CACHE_DIR / "bse_codes.json"
_session = None


def _s():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _codes():
    try:
        return json.loads(CODES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def scrip_code(ticker):
    """RELIANCE.NS / RELIANCE.BO / 500325 -> '500325', or None."""
    sym = ticker.split(".")[0].upper()
    if sym.isdigit():
        return sym
    known = _codes()
    if sym in known:
        return known[sym] or None
    code = None
    try:
        r = _s().get(SEARCH, params={"Type": "EQ", "text": sym, "flag": "site"}, timeout=15)
        if r.status_code != 200:
            return None  # blocked or down: ask again next time rather than remember "no code"
        # the reply is an HTML list of links: .../stock-share-price/<name>/<symbol>/<code>/
        for m in re.finditer(r"stock-share-price/[^/]+/([^/]+)/(\d{6})/", r.text):
            if m.group(1).upper() == sym:
                code = m.group(2)
                break
        if code is None:
            m = re.search(r"/(\d{6})/", r.text)
            code = m.group(1) if m else None
    except Exception as e:  # noqa: BLE001
        log.info("BSE code lookup failed for %s: %s", sym, e)
        return None
    known[sym] = code or ""
    try:
        CODES.parent.mkdir(parents=True, exist_ok=True)
        CODES.write_text(json.dumps(known, indent=1), encoding="utf-8")
    except OSError:
        pass
    return code


def _series(rows):
    pts = {}
    for row in rows or []:
        d = row.get("dttm") or row.get("Date") or row.get("date")
        c = num(row.get("vale1") or row.get("Close") or row.get("close") or row.get("ClosePrice"))
        if d and c:
            try:
                pts[pd.to_datetime(d, dayfirst=False).normalize()] = c
            except (ValueError, TypeError):
                continue
    if not pts:
        return None
    s = pd.Series(pts).sort_index()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s[~s.index.duplicated(keep="last")]


def fetch_close_series(ticker, start, end):
    """Daily closes between start and end, or None."""
    code = scrip_code(ticker)
    if not code:
        return None
    frames = []
    cursor = start
    while cursor < end:
        stop = min(cursor + dt.timedelta(days=360), end)
        try:
            r = _s().get(f"{API}/StockReachGraph/w", params={"scripcode": code, "flag": "0", "fromdate": cursor.strftime("%Y%m%d"),
                                                            "todate": stop.strftime("%Y%m%d"), "seriesid": ""}, timeout=20)
            body = r.json()
            data = body.get("Data") if isinstance(body, dict) else None
            if isinstance(data, str):
                data = json.loads(data)
            s = _series(data)
            if s is not None:
                frames.append(s)
        except Exception as e:  # noqa: BLE001
            log.info("BSE history failed for %s %s-%s: %s", code, cursor, stop, e)
        cursor = stop + dt.timedelta(days=1)
        time.sleep(config.REQUEST_PAUSE)
    if not frames:
        return None
    s = pd.concat(frames).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]


def fetch_last_price(ticker):
    code = scrip_code(ticker)
    if not code:
        return None
    try:
        r = _s().get(f"{API}/getScripHeaderData/w", params={"Debtflag": "", "scripcode": code, "seriesid": ""}, timeout=15)
        h = r.json().get("Header", {})
        return num(str(h.get("LTP", "")).replace(",", ""))
    except Exception as e:  # noqa: BLE001
        log.info("BSE quote failed for %s: %s", code, e)
        return None
