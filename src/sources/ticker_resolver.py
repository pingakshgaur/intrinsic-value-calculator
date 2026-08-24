"""Company name -> Yahoo ticker. Explicit -> manual map -> cache -> search -> BSE."""

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
    # --- BSE-only or awkward names; VERIFY each before trusting ---
    "UNIFINZ CAPITAL INDIA": "UNIFINZ.NS",
    "ROYAL INDIA CORPORATION": "512047.BO",
    "KSL HOLDINGS": "526209.BO",
    "MAHALAXMI RUBTECH": "514450.BO",
    "CALIFORNIA SOFTWARE COMPANY": "532386.BO",
    "TAPARIA TOOLS": "505685.BO",
}

_CACHE_FILE = os.path.join(str(config.CACHE_DIR), "tickers.json")
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
    os.makedirs(str(config.CACHE_DIR), exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)


def _yahoo_search(name, prefer_suffix):
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    try:
        r = requests.get(
            url, params={"q": name, "quotesCount": 10}, headers=_HEADERS, timeout=15
        )
        r.raise_for_status()
        quotes = r.json().get("quotes", [])
    except Exception:
        return None
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(prefer_suffix):
            return sym
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(".NS") or sym.endswith(".BO"):
            return sym
    return None


def _strip_suffixes(name):
    """'Hikal Limited' -> 'Hikal'. Improves search hit rate."""
    n = name.strip()
    for tail in (
        " limited",
        " ltd.",
        " ltd",
        " corporation",
        " corp.",
        " company",
        " co.",
        " (india)",
        " india limited",
    ):
        if n.lower().endswith(tail):
            # Strip ONE suffix, not every matching one. The loop used to keep
            # going, so "Royal India Corporation Limited" lost both " limited"
            # and " corporation" and became "Royal India", which matches no
            # MANUAL key and searches for the wrong company.
            return n[: -len(tail)].strip()
    return n


def _lookup_keys(company_name: str):
    """
    Both the raw name and the suffix-stripped name, uppercased.

    The MANUAL map is keyed without the corporate suffix ("BHARAT ELECTRONICS")
    while companies.csv carries it ("Bharat Electronics Limited"), so an exact
    match never fired and every hand-verified entry was being skipped in favour
    of whatever the Yahoo search happened to return. For a thesis that is worse
    than a crash: the wrong scrip resolves silently and the numbers look fine.
    """
    raw = company_name.strip().upper()
    stripped = _strip_suffixes(company_name).strip().upper()
    return [raw] if raw == stripped else [raw, stripped]


def resolve(company_name: str, explicit_ticker: str = None):
    """Explicit ticker wins. Then manual map, cache, NSE search, BSE search."""
    if explicit_ticker:
        t = explicit_ticker.strip().upper()
        return t if ("." in t) else t + config.EXCHANGE_SUFFIX

    keys = _lookup_keys(company_name)

    # MANUAL is hand-verified and must outrank the cache, which is populated
    # from unverified search results.
    for k in keys:
        if MANUAL.get(k):
            return MANUAL[k]

    cache = _load_cache()
    for k in keys:
        if cache.get(k):
            return cache[k]
    key = keys[0]
    
    if key in MANUAL and MANUAL[key]:
        return MANUAL[key]

    cache = _load_cache()
    if key in cache and cache[key]:
        return cache[key]

    time.sleep(config.REQUEST_PAUSE)
    sym = _yahoo_search(company_name, config.EXCHANGE_SUFFIX)

    if not sym:  # retry on the trimmed name
        time.sleep(config.REQUEST_PAUSE)
        sym = _yahoo_search(_strip_suffixes(company_name), config.EXCHANGE_SUFFIX)

    if not sym:  # retry preferring BSE
        time.sleep(config.REQUEST_PAUSE)
        sym = _yahoo_search(_strip_suffixes(company_name), ".BO")

    if sym:
        cache[key] = sym
        _save_cache(cache)
    return sym
