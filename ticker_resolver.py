"""Company name -> Yahoo Finance ticker. Manual map first, then Yahoo search."""

import json
import os
import time
import requests
import config

MANUAL = {
    "BHARAT ELECTRONICS": "BEL.NS",
    "RELIANCE INDUSTRIES": "RELIANCE.NS",
    "TATA CONSULTANCY SERVICES": "TCS.NS",
    "INFOSYS": "INFY.NS",
    "HDFC BANK": "HDFCBANK.NS",
    "ITC": "ITC.NS",
    "SUN PHARMACEUTICAL": "SUNPHARMA.NS",
    "MARUTI SUZUKI": "MARUTI.NS",
    "ASIAN PAINTS": "ASIANPAINT.NS",
    "LARSEN & TOUBRO": "LT.NS",
}

_CACHE_FILE = os.path.join(config.CACHE_DIR, "tickers.json")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _load_cache():
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(c):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)


def _yahoo_search(name):
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    try:
        r = requests.get(
            url, params={"q": name, "quotesCount": 10}, headers=_HEADERS, timeout=15
        )
        r.raise_for_status()
        quotes = r.json().get("quotes", [])
    except Exception:
        return None
    # Prefer the configured exchange, then any Indian listing
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(config.EXCHANGE_SUFFIX):
            return sym
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(".NS") or sym.endswith(".BO"):
            return sym
    return None


def resolve(company_name: str, explicit_ticker: str = None) -> str | None:
    """Explicit ticker in CSV wins. Then manual map. Then Yahoo search."""
    if explicit_ticker:
        t = explicit_ticker.strip().upper()
        return t if ("." in t) else t + config.EXCHANGE_SUFFIX

    key = company_name.strip().upper()
    if key in MANUAL:
        return MANUAL[key]

    cache = _load_cache()
    if key in cache:
        return cache[key]

    time.sleep(config.REQUEST_PAUSE)
    sym = _yahoo_search(company_name)
    if sym:
        cache[key] = sym
        _save_cache(cache)
    return sym
