# FILE: src/sources/keyed_sources.py
"""
Data providers that need a (free) API key: Financial Modeling Prep, EODHD and
Alpha Vantage. Each is skipped when its key is not set (see source_settings).

    statements(provider, ticker) -> {fy: {field: value in rupees}}
    closes(provider, ticker, start, end) -> pd.Series of daily closes, or None

Symbols: FMP and Yahoo share RELIANCE.NS / RELIANCE.BO; EODHD writes
RELIANCE.NSE / RELIANCE.BSE; Alpha Vantage serves Indian prices as
RELIANCE.BSE. Free tiers are small (25-250 calls a day), so these sit behind
the free sources and are asked only for what is still missing.
"""

import datetime as dt
import logging

import pandas as pd
import requests

import source_settings
from fy_utils import fy_for_period_end, num

log = logging.getLogger(__name__)
TIMEOUT = 20


def _get(url, params):
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json()


def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _put(out, when, d):
    if when is None:
        return
    fy = fy_for_period_end(when, 365)
    out.setdefault(fy, {}).update({k: v for k, v in d.items() if v is not None})


# ---------------------------------------------------------------- Financial Modeling Prep
def _fmp_rows(kind, sym, key):
    # the "stable" API first; accounts created before 2025 may still be on v3
    for url, params in ((f"https://financialmodelingprep.com/stable/{kind}", {"symbol": sym, "period": "annual", "limit": 15, "apikey": key}),
                        (f"https://financialmodelingprep.com/api/v3/{kind}/{sym}", {"period": "annual", "limit": 15, "apikey": key})):
        try:
            rows = _get(url, params)
            if isinstance(rows, list) and rows:
                return rows
        except Exception as e:  # noqa: BLE001
            log.info("FMP %s %s: %s", kind, sym, e)
    return []


def fmp_statements(ticker):
    key = source_settings.key("fmp")
    out = {}
    for sym in dict.fromkeys([ticker, ticker.split(".")[0] + ".BO"]):
        inc = _fmp_rows("income-statement", sym, key)
        if not inc:
            continue
        for r in inc:
            pretax, tax = num(r.get("incomeBeforeTax")), num(r.get("incomeTaxExpense"))
            _put(out, _date(r.get("date")), {
                "revenue": num(r.get("revenue")), "ebit": num(r.get("operatingIncome")), "ebitda": num(r.get("ebitda")),
                "net_income": num(r.get("netIncome")), "eps": num(r.get("epsDiluted") or r.get("epsdiluted") or r.get("eps")),
                "da": num(r.get("depreciationAndAmortization")), "pretax": pretax,
                "tax_rate": tax / pretax if pretax and tax is not None and pretax > 0 else None,
                "shares": num(r.get("weightedAverageShsOutDil")),
            })
        for r in _fmp_rows("balance-sheet-statement", sym, key):
            _put(out, _date(r.get("date")), {
                "total_debt": num(r.get("totalDebt")), "cash": num(r.get("cashAndShortTermInvestments") or r.get("cashAndCashEquivalents")),
                "assets": num(r.get("totalAssets")), "cur_liab": num(r.get("totalCurrentLiabilities")),
                "equity": num(r.get("totalStockholdersEquity")),
            })
        for r in _fmp_rows("cash-flow-statement", sym, key):
            capex, cwc = num(r.get("capitalExpenditure")), num(r.get("changeInWorkingCapital"))
            _put(out, _date(r.get("date")), {
                "ocf": num(r.get("operatingCashFlow") or r.get("netCashProvidedByOperatingActivities")),
                "capex": abs(capex) if capex is not None else None, "delta_nwc": -cwc if cwc is not None else None,
            })
        if out:
            break
    return out


def fmp_closes(ticker, start, end):
    key = source_settings.key("fmp")
    for url, params in (("https://financialmodelingprep.com/stable/historical-price-eod/light", {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat(), "apikey": key}),
                        (f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}", {"from": start.isoformat(), "to": end.isoformat(), "serietype": "line", "apikey": key})):
        try:
            body = _get(url, params)
            rows = body.get("historical", []) if isinstance(body, dict) else body
            s = _series(rows, "date", ("close", "price"))
            if s is not None:
                return s
        except Exception as e:  # noqa: BLE001
            log.info("FMP prices %s: %s", ticker, e)
    return None


# ---------------------------------------------------------------- EODHD
def _eod_symbol(ticker):
    sym, _, ex = ticker.partition(".")
    return f"{sym.upper()}.{'BSE' if ex.upper() == 'BO' else 'NSE'}"


def eodhd_statements(ticker):
    key = source_settings.key("eodhd")
    try:
        body = _get(f"https://eodhd.com/api/fundamentals/{_eod_symbol(ticker)}", {"api_token": key, "fmt": "json"})
    except Exception as e:  # noqa: BLE001
        log.info("EODHD fundamentals %s: %s", ticker, e)
        return {}
    fin = body.get("Financials", {}) if isinstance(body, dict) else {}
    out = {}
    for when, r in (fin.get("Income_Statement", {}).get("yearly") or {}).items():
        pretax, tax = num(r.get("incomeBeforeTax")), num(r.get("incomeTaxExpense"))
        _put(out, _date(when), {
            "revenue": num(r.get("totalRevenue")), "ebit": num(r.get("ebit") or r.get("operatingIncome")), "ebitda": num(r.get("ebitda")),
            "net_income": num(r.get("netIncome")), "da": num(r.get("depreciationAndAmortization")), "pretax": pretax,
            "tax_rate": tax / pretax if pretax and tax is not None and pretax > 0 else None,
        })
    for when, r in (fin.get("Balance_Sheet", {}).get("yearly") or {}).items():
        _put(out, _date(when), {
            "total_debt": num(r.get("shortLongTermDebtTotal") or r.get("longTermDebt")),
            "cash": num(r.get("cashAndShortTermInvestments") or r.get("cash")), "assets": num(r.get("totalAssets")),
            "cur_liab": num(r.get("totalCurrentLiabilities")), "equity": num(r.get("totalStockholderEquity")),
            "shares": num(r.get("commonStockSharesOutstanding")),
        })
    for when, r in (fin.get("Cash_Flow", {}).get("yearly") or {}).items():
        capex, cwc = num(r.get("capitalExpenditures")), num(r.get("changeInWorkingCapital"))
        _put(out, _date(when), {
            "ocf": num(r.get("totalCashFromOperatingActivities")), "capex": abs(capex) if capex is not None else None,
            "delta_nwc": -cwc if cwc is not None else None,
        })
    for d in out.values():
        if d.get("net_income") and d.get("shares") and "eps" not in d:
            d["eps"] = d["net_income"] / d["shares"]
    return out


def eodhd_closes(ticker, start, end):
    key = source_settings.key("eodhd")
    try:
        rows = _get(f"https://eodhd.com/api/eod/{_eod_symbol(ticker)}", {"api_token": key, "fmt": "json", "from": start.isoformat(), "to": end.isoformat()})
        return _series(rows, "date", ("close",))
    except Exception as e:  # noqa: BLE001
        log.info("EODHD prices %s: %s", ticker, e)
        return None


# ---------------------------------------------------------------- Alpha Vantage
def alphavantage_closes(ticker, start, end):
    key = source_settings.key("alphavantage")
    sym = ticker.split(".")[0].upper() + ".BSE"
    try:
        body = _get("https://www.alphavantage.co/query", {"function": "TIME_SERIES_DAILY", "symbol": sym, "outputsize": "full", "apikey": key})
        ts = body.get("Time Series (Daily)") or {}
        s = _series([{"date": d, "close": v.get("4. close")} for d, v in ts.items()], "date", ("close",))
        if s is None:
            return None
        return s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    except Exception as e:  # noqa: BLE001
        log.info("Alpha Vantage prices %s: %s", ticker, e)
        return None


# ---------------------------------------------------------------- shared
def _series(rows, date_key, close_keys):
    pts = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = _date(r.get(date_key))
        c = next((num(r.get(k)) for k in close_keys if num(r.get(k)) is not None), None)
        if d and c:
            pts[pd.Timestamp(d)] = c
    if not pts:
        return None
    return pd.Series(pts).sort_index()


STATEMENTS = {"fmp": fmp_statements, "eodhd": eodhd_statements}
CLOSES = {"fmp": fmp_closes, "eodhd": eodhd_closes, "alphavantage": alphavantage_closes}
