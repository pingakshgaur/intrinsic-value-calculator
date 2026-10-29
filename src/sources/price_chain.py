# FILE: src/sources/price_chain.py
"""
Daily closing prices from the first provider that has them.

    closes(ticker, start, end, skip=()) -> (pd.Series | None, provider key | None, [problems])

Providers are tried in the order set in source_settings (Configuration ->
Data sources): Yahoo's NSE listing, Yahoo's BSE listing, the NSE and BSE
websites, then the key-based providers. A series counts only if it covers at
least a quarter of the requested window, so a provider that knows only the
last few weeks does not stop the search.
"""

import logging
import time

import pandas as pd

import bse_source
import keyed_sources
import nse_source
import source_settings

log = logging.getLogger(__name__)


def _yahoo(symbol, start, end):
    import yfinance as yf

    hist = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
    if hist is None or hist.empty:
        return None
    s = hist["Close"]
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def _alt(ticker, suffix):
    return ticker.split(".")[0].upper() + suffix


FETCH = {
    "yahoo": lambda t, a, b: _yahoo(t if "." in t else t + ".NS", a, b),
    "yahoo_bse": lambda t, a, b: _yahoo(_alt(t, ".BO"), a, b),
    "nse": nse_source.fetch_close_series,
    "bse": bse_source.fetch_close_series,
    **keyed_sources.CLOSES,
}


def _enough(s, start, end):
    s = s.dropna() if s is not None else None
    if s is None or s.empty:
        return False
    days = max(1, (end - start).days)
    return (s.index.max() - s.index.min()).days >= 0.25 * days or len(s) >= 0.25 * days * 5 / 7


def closes(ticker, start, end, skip=()):
    problems = []
    for key in source_settings.enabled("prices"):
        if key in skip or key not in FETCH:
            continue
        try:
            s = FETCH[key](ticker, start, end)
        except Exception as e:  # noqa: BLE001 - the next provider is tried
            log.info("prices from %s failed for %s: %s", key, ticker, e)
            problems.append(f"{source_settings.BY_KEY[key]['label']}: {type(e).__name__}")
            continue
        if _enough(s, start, end):
            s = s.dropna().sort_index()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            return s[~s.index.duplicated(keep="last")], key, problems
        problems.append(f"{source_settings.BY_KEY[key]['label']}: no prices for this window")
    return None, None, problems


# the tracker asks for quotes every 30 seconds: a symbol or a website that did
# not answer is left alone for a while, so a blocked network never stalls a poll
_QUOTE_RETRY = 900      # seconds before asking again for a symbol that had no quote
_SITE_RETRY = 600       # seconds a website is skipped after three failures in a row
_quote_miss, _site_fail = {}, {}


def last_price(ticker):
    """A single spot price from the exchange websites, for when Yahoo has no quote. -> (price, provider) or (None, None)"""
    now = time.time()
    if now - _quote_miss.get(ticker, 0) < _QUOTE_RETRY:
        return None, None
    for key, fn in (("nse", nse_source.fetch_last_price), ("bse", bse_source.fetch_last_price)):
        if key not in source_settings.enabled("quotes"):
            continue
        fails, since = _site_fail.get(key, (0, 0))
        if fails >= 3 and now - since < _SITE_RETRY:
            continue
        try:
            p = fn(ticker)
        except Exception:  # noqa: BLE001
            p = None
        if p:
            _site_fail[key] = (0, 0)
            _quote_miss.pop(ticker, None)
            return p, key
        _site_fail[key] = (fails + 1, now)
    _quote_miss[ticker] = now
    return None, None
