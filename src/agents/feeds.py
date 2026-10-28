# FILE: src/agents/feeds.py
"""
Every outside fact the agents use comes through here.

Free, primary-first sources:
    yfinance          prices, volumes, extended statements, quarterly results,
                      holders, insider transactions, earnings calendar
    NSE portal        corporate announcements, insider (PIT) disclosures,
                      shareholding pattern, promoter pledges, delivery %,
                      board-meeting calendar
    Google News RSS   headlines with their publishing outlet
    Yahoo macro       Nifty, India VIX, USD/INR, Brent, US 10Y, gold

Each call is cached on disk for run.feed_cache_hours, so the quick sweeps
between full runs, and agents that share a feed, never download twice.

Nothing here raises. A blocked site returns an empty result and records why
in self.problems, which ends up in the run report - the agents then work
with whatever did arrive, and the validator marks the gap.

offline=True returns deterministic synthetic data so the whole team can be
exercised in tests without the network.
"""

import datetime as dt
import hashlib
import json
import logging
import math
import random
import threading
import time
import urllib.parse

from agents import settings as S

log = logging.getLogger("agents.feeds")


def _fy_of(ts):
    """Statement column date -> Indian FY number (March year-end)."""
    d = ts.date() if hasattr(ts, "date") else ts
    return d.year if d.month <= 6 else d.year + 1


def _f(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _pct(v):
    """'72.30' / 72.3 / '72.3%' -> 0.723"""
    if isinstance(v, str):
        v = v.replace("%", "").replace(",", "").strip()
    x = _f(v)
    return x / 100.0 if x is not None else None


def _parse_date(s):
    if not s:
        return ""
    s = str(s).strip()
    for fmt in (
        "%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y",
        "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        import pandas as pd

        return pd.to_datetime(s).date().isoformat()
    except Exception:
        return ""


ANNUAL_ROWS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cogs": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "sga": ["Selling General And Administration", "General And Administrative Expense"],
    "ebit": ["EBIT", "Operating Income"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "da": ["Reconciled Depreciation", "Depreciation And Amortization"],
    "eps": ["Diluted EPS", "Basic EPS"],
    "assets": ["Total Assets"],
    "cur_assets": ["Current Assets"],
    "cur_liab": ["Current Liabilities"],
    "receivables": ["Accounts Receivable", "Receivables", "Gross Accounts Receivable"],
    "inventory": ["Inventory"],
    "ppe_net": ["Net PPE"],
    "total_liab": ["Total Liabilities Net Minority Interest"],
    "lt_debt": ["Long Term Debt"],
    "total_debt": ["Total Debt"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "equity": ["Stockholders Equity", "Common Stock Equity"],
    "retained_earnings": ["Retained Earnings"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
    "ocf": ["Operating Cash Flow"],
    "capex": ["Capital Expenditure"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
}


class Feeds:
    def __init__(self, offline=False, cache_hours=None):
        self.offline = offline
        self.cache_hours = cache_hours if cache_hours is not None else S.num("run.feed_cache_hours", 6)
        self.dir = S.state_dir() / "feeds"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.problems = []
        self._lock = threading.Lock()
        self._nse_lock = threading.Lock()
        self._nse_dead = not S.get("sources.use_nse", True)

    # ------------------------------------------------------------ cache
    def _cached(self, key, fn):
        if self.offline:
            return fn()
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        path = self.dir / f"{h}.json"
        if path.exists() and time.time() - path.stat().st_mtime < self.cache_hours * 3600:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        val = fn()
        if val not in (None, [], {}):
            try:
                path.write_text(json.dumps(val, default=str), encoding="utf-8")
            except OSError:
                pass
        return val

    def _problem(self, where, e):
        msg = f"{where}: {type(e).__name__}: {str(e)[:120]}" if isinstance(e, Exception) else f"{where}: {e}"
        with self._lock:
            if msg not in self.problems:
                self.problems.append(msg)
        log.warning(msg)

    # ======================================================== yfinance
    def _yf(self, ticker):
        import yfinance as yf

        return yf.Ticker(ticker)

    def prices(self, ticker, days=400):
        """-> list of {date, close, volume}, oldest first."""
        if self.offline:
            return _synthetic_prices(ticker, days)

        def go():
            try:
                h = self._yf(ticker).history(period=f"{max(days, 30)}d", auto_adjust=False)
                if h is None or h.empty:
                    self._problem(f"prices {ticker}", "no rows")
                    return []
                return [
                    {"date": i.date().isoformat(), "close": _f(r["Close"]), "volume": _f(r["Volume"])}
                    for i, r in h.iterrows()
                    if _f(r["Close"])
                ]
            except Exception as e:
                self._problem(f"prices {ticker}", e)
                return []

        return self._cached(f"prices|{ticker}|{days}|{dt.date.today()}", go)

    def info(self, ticker):
        if self.offline:
            p = _synthetic_prices(ticker, 5)[-1]["close"]
            return {"marketCap": p * 1.0e8, "currentPrice": p, "sharesOutstanding": 1.0e8,
                    "averageVolume": 2.0e6, "beta": 1.0}

        def go():
            try:
                i = self._yf(ticker).info or {}
                keep = ("marketCap", "currentPrice", "regularMarketPrice", "previousClose",
                        "sharesOutstanding", "averageVolume", "averageDailyVolume10Day",
                        "beta", "heldPercentInsiders", "heldPercentInstitutions",
                        "trailingPE", "priceToBook", "dividendYield", "longName",
                        "industry", "sector", "fiftyTwoWeekHigh", "fiftyTwoWeekLow")
                return {k: i.get(k) for k in keep if i.get(k) is not None}
            except Exception as e:
                self._problem(f"info {ticker}", e)
                return {}

        return self._cached(f"info|{ticker}|{dt.date.today()}", go)

    def statements(self, ticker):
        """-> {"annual": {fy: {...}}, "quarterly": [{date, revenue, net_income, eps, ebit}]}"""
        if self.offline:
            return _synthetic_statements(ticker)

        def go():
            out = {"annual": {}, "quarterly": []}
            try:
                t = self._yf(ticker)
                frames = [t.income_stmt, t.balance_sheet, t.cashflow]
            except Exception as e:
                self._problem(f"statements {ticker}", e)
                return out
            for df in frames:
                if df is None or getattr(df, "empty", True):
                    continue
                for col in df.columns:
                    fy = _fy_of(col)
                    d = out["annual"].setdefault(str(fy), {})
                    for field, aliases in ANNUAL_ROWS.items():
                        if d.get(field) is not None:
                            continue
                        for a in aliases:
                            if a in df.index:
                                v = _f(df.loc[a, col])
                                if v is not None:
                                    d[field] = abs(v) if field in ("capex", "dividends_paid") else v
                                    break
            try:
                q = t.quarterly_income_stmt
                if q is not None and not q.empty:
                    for col in q.columns[:8]:
                        row = {"date": col.date().isoformat()}
                        for field in ("revenue", "net_income", "eps", "ebit"):
                            for a in ANNUAL_ROWS[field]:
                                if a in q.index and _f(q.loc[a, col]) is not None:
                                    row[field] = _f(q.loc[a, col])
                                    break
                        out["quarterly"].append(row)
            except Exception as e:
                self._problem(f"quarterly {ticker}", e)
            return out

        return self._cached(f"statements|{ticker}|{dt.date.today().isocalendar()[:2]}", go)

    def yf_insiders(self, ticker):
        if self.offline:
            return []

        def go():
            try:
                df = self._yf(ticker).insider_transactions
                if df is None or df.empty:
                    return []
                rows = []
                for _, r in df.head(50).iterrows():
                    rows.append({
                        "name": str(r.get("Insider", "")),
                        "role": str(r.get("Position", "")),
                        "text": str(r.get("Text", "") or r.get("Transaction", "")),
                        "shares": _f(r.get("Shares")),
                        "value": _f(r.get("Value")),
                        "date": _parse_date(r.get("Start Date")),
                    })
                return rows
            except Exception as e:
                self._problem(f"yf insiders {ticker}", e)
                return []

        return self._cached(f"yfins|{ticker}|{dt.date.today()}", go)

    def yf_holders(self, ticker):
        if self.offline:
            return {"insiders": 0.55, "institutions": 0.22}

        def go():
            try:
                i = self.info(ticker)
                return {
                    "insiders": _f(i.get("heldPercentInsiders")),
                    "institutions": _f(i.get("heldPercentInstitutions")),
                }
            except Exception as e:
                self._problem(f"yf holders {ticker}", e)
                return {}

        return go()

    def earnings_date(self, ticker):
        if self.offline:
            return (dt.date.today() + dt.timedelta(days=20)).isoformat()

        def go():
            try:
                cal = self._yf(ticker).calendar
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if isinstance(ed, (list, tuple)) and ed:
                        ed = ed[0]
                    return _parse_date(ed) if ed else ""
            except Exception as e:
                self._problem(f"calendar {ticker}", e)
            return ""

        return self._cached(f"cal|{ticker}|{dt.date.today()}", go)

    # ======================================================== macro
    def macro(self):
        """-> {name: {last, chg_1m, chg_1y, ticker}} for the live macro tickers."""
        tickers = S.section("macro.live_tickers") or {
            "nifty": "^NSEI", "india_vix": "^INDIAVIX", "usd_inr": "INR=X",
            "brent": "BZ=F", "us_10y": "^TNX", "gold": "GC=F",
        }
        out = {}
        for name, tk in tickers.items():
            px = self.prices(tk, 400)
            if len(px) < 5:
                continue
            last = px[-1]["close"]
            m1 = px[-22]["close"] if len(px) > 22 else px[0]["close"]
            y1 = px[-250]["close"] if len(px) > 250 else px[0]["close"]
            out[name] = {
                "ticker": tk,
                "last": last,
                "date": px[-1]["date"],
                "chg_1m": last / m1 - 1 if m1 else None,
                "chg_1y": last / y1 - 1 if y1 else None,
            }
        return out

    # ======================================================== news
    def news(self, query, days=None, limit=None):
        """Google News RSS. -> list of {title, url, source, domain, date}."""
        days = days or int(S.num("run.news_lookback_days", 30))
        limit = limit or int(S.num("sources.news_max_items", 25))
        if self.offline:
            return _synthetic_news(query, limit)
        if not S.get("sources.use_google_news_rss", True):
            return []

        def go():
            try:
                import feedparser
            except ImportError:
                self._problem("news", "feedparser not installed (pip install feedparser)")
                return []
            q = urllib.parse.quote(f"{query} when:{days}d")
            url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            try:
                import requests

                r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(r.content)
            except Exception as e:
                self._problem(f"news '{query}'", e)
                return []
            items = []
            for e in feed.entries[: limit * 2]:
                src = e.get("source") or {}
                href = src.get("href", "") if isinstance(src, dict) else ""
                domain = urllib.parse.urlparse(href).netloc.replace("www.", "")
                title = e.get("title", "")
                outlet = src.get("title", "") if isinstance(src, dict) else ""
                if outlet and title.endswith(" - " + outlet):
                    title = title[: -len(outlet) - 3]
                items.append({
                    "title": title.strip(),
                    "url": e.get("link", ""),
                    "source": outlet or domain or "Google News",
                    "domain": domain,
                    "date": _parse_date(e.get("published", "")),
                })
            # newest first, de-duplicated on headline
            seen, out = set(), []
            for it in sorted(items, key=lambda x: x["date"], reverse=True):
                k = it["title"].lower()[:80]
                if k and k not in seen:
                    seen.add(k)
                    out.append(it)
            return out[:limit]

        return self._cached(f"news|{query}|{days}|{limit}|{dt.date.today()}|{dt.datetime.now().hour // 6}", go)

    # ======================================================== NSE
    def _nse(self, path, params):
        """GET an NSE API path with a primed session. -> JSON or None."""
        if self.offline or self._nse_dead:
            return None
        import nse_source

        with self._nse_lock:
            try:
                s = nse_source._get_session()
                r = s.get(nse_source.BASE + path, params=params, timeout=20)
                time.sleep(0.8)
                if r.status_code in (401, 403):
                    self._nse_dead = True
                    self._problem("NSE", f"HTTP {r.status_code} - NSE is blocking this IP; NSE feeds skipped for this run")
                    return None
                if r.status_code != 200:
                    self._problem(f"NSE {path}", f"HTTP {r.status_code}")
                    return None
                return r.json()
            except Exception as e:
                self._problem(f"NSE {path}", e)
                return None

    def nse_announcements(self, symbol, days=None):
        days = days or int(S.num("run.news_lookback_days", 30))
        if self.offline:
            return _synthetic_announcements(symbol)

        def go():
            end = dt.date.today()
            start = end - dt.timedelta(days=days)
            js = self._nse("/api/corporate-announcements", {
                "index": "equities", "symbol": symbol,
                "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y"),
            })
            rows = js if isinstance(js, list) else (js or {}).get("data", []) if isinstance(js, dict) else []
            out = []
            for r in rows[:40]:
                out.append({
                    "title": (r.get("desc") or "").strip(),
                    "text": (r.get("attchmntText") or "")[:500],
                    "url": r.get("attchmntFile") or "",
                    "date": _parse_date(r.get("an_dt") or r.get("sort_date")),
                })
            return out

        return self._cached(f"nseann|{symbol}|{days}|{dt.date.today()}", go)

    def nse_insider(self, symbol, days=None):
        days = days or int(S.num("run.ownership_lookback_days", 180))
        if self.offline:
            return _synthetic_insider(symbol)

        def go():
            end = dt.date.today()
            start = end - dt.timedelta(days=days)
            js = self._nse("/api/corporates-pit", {
                "index": "equities", "symbol": symbol,
                "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y"),
            })
            rows = (js or {}).get("data", []) if isinstance(js, dict) else []
            out = []
            for r in rows:
                out.append({
                    "name": r.get("acqName", ""),
                    "category": r.get("personCategory", ""),
                    "type": r.get("tdpTransactionType", "") or r.get("acqMode", ""),
                    "shares": _f(r.get("secAcq")),
                    "value": _f(r.get("secVal")),
                    "pct_after": _pct(r.get("afterAcqSharesPer")),
                    "date": _parse_date(r.get("acqfromDt") or r.get("date") or r.get("intimDt")),
                    "url": r.get("xbrl") or "",
                })
            return out

        return self._cached(f"nsepit|{symbol}|{days}|{dt.date.today()}", go)

    def nse_shareholding(self, symbol):
        """-> list of {date, promoter, public} newest first."""
        if self.offline:
            return _synthetic_shareholding(symbol)

        def go():
            js = self._nse("/api/corporate-share-holdings-master", {"index": "equities", "symbol": symbol})
            rows = js if isinstance(js, list) else []
            out = []
            for r in rows[:8]:
                out.append({
                    "date": _parse_date(r.get("date")),
                    "promoter": _pct(r.get("pr_and_prgrp")),
                    "public": _pct(r.get("public_val")),
                    "employee_trusts": _pct(r.get("employeeTrusts")),
                })
            return sorted(out, key=lambda x: x["date"], reverse=True)

        return self._cached(f"nseshp|{symbol}|{dt.date.today().isocalendar()[:2]}", go)

    def nse_pledge(self, symbol):
        """-> fraction of promoter holding pledged, or None."""
        if self.offline:
            return 0.0

        def go():
            js = self._nse("/api/corporate-pledgedata", {"index": "equities", "symbol": symbol})
            rows = (js or {}).get("data", []) if isinstance(js, dict) else (js or [])
            for r in rows[:1]:
                for k, v in r.items():
                    lk = k.lower()
                    if "pledg" in lk and ("per" in lk or "pct" in lk) and "promot" in lk:
                        return _pct(v)
                for k, v in r.items():
                    if "per3" in k.lower() or "percpromoter" in k.lower():
                        return _pct(v)
            return None

        return self._cached(f"nsepledge|{symbol}|{dt.date.today().isocalendar()[:2]}", go)

    def nse_trade_info(self, symbol):
        """-> {delivery_pct, ...} for the latest session, or {}."""
        if self.offline:
            return {"delivery_pct": 0.48}

        def go():
            js = self._nse("/api/quote-equity", {"symbol": symbol, "section": "trade_info"})
            if not isinstance(js, dict):
                return {}
            dp = (js.get("securityWiseDP") or {})
            return {
                "delivery_pct": _pct(dp.get("deliveryToTradedQuantity")),
                "traded_qty": _f(dp.get("quantityTraded")),
            }

        return self._cached(f"nsetrade|{symbol}|{dt.date.today()}", go)

    def nse_events(self, symbol):
        if self.offline:
            return [{"purpose": "Financial Results", "date": (dt.date.today() + dt.timedelta(days=20)).isoformat()}]

        def go():
            js = self._nse("/api/event-calendar", {"index": "equities", "symbol": symbol})
            rows = js if isinstance(js, list) else []
            return [
                {"purpose": r.get("purpose", ""), "desc": r.get("bm_desc", ""), "date": _parse_date(r.get("date"))}
                for r in rows[:10]
            ]

        return self._cached(f"nseevt|{symbol}|{dt.date.today()}", go)


# ============================================================ synthetic data
def _rng(key):
    return random.Random(int(hashlib.sha1(key.encode()).hexdigest()[:8], 16))


def _synthetic_prices(ticker, days):
    rng = _rng("px" + ticker)
    p = 400 + rng.random() * 600
    vol = 2.0e6
    out = []
    start = dt.date.today() - dt.timedelta(days=days)
    for i in range(days):
        d = start + dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        p *= math.exp(rng.gauss(0.0004, 0.015))
        v = vol * math.exp(rng.gauss(0, 0.3))
        out.append({"date": d.isoformat(), "close": round(p, 2), "volume": round(v)})
    return out


def _synthetic_statements(ticker):
    rng = _rng("st" + ticker)
    fy_now = dt.date.today().year if dt.date.today().month > 3 else dt.date.today().year - 1
    annual = {}
    rev = 2.0e10 * (0.8 + 0.4 * rng.random())
    for i, fy in enumerate(range(fy_now - 3, fy_now + 1)):
        r = rev * (1.11 ** i)
        ni = r * 0.12
        annual[str(fy)] = {
            "revenue": r, "cogs": r * 0.55, "gross_profit": r * 0.45, "sga": r * 0.12,
            "ebit": r * 0.17, "net_income": ni, "interest_expense": r * 0.01, "da": r * 0.025,
            "eps": ni / 1.0e8, "assets": r * 1.3, "cur_assets": r * 0.6, "cur_liab": r * 0.35,
            "receivables": r * 0.15, "inventory": r * 0.1, "ppe_net": r * 0.5,
            "total_liab": r * 0.4, "lt_debt": r * 0.15, "total_debt": r * 0.2, "cash": r * 0.08,
            "equity": r * 0.9, "retained_earnings": r * 0.6, "shares": 1.0e8,
            "ocf": ni * (1.05 + 0.2 * rng.random()), "capex": r * 0.04, "dividends_paid": ni * 0.3,
        }
    quarterly = []
    for q in range(8):
        d = dt.date.today() - dt.timedelta(days=95 * (q + 1))
        base = rev * 1.11 ** 3 / 4 * (0.97 ** q)
        quarterly.append({"date": d.isoformat(), "revenue": base, "net_income": base * 0.12,
                          "eps": base * 0.12 / 1e8, "ebit": base * 0.17})
    return {"annual": annual, "quarterly": quarterly}


_HEADLINES = [
    ("{q} bags large order worth Rs 2,000 crore", "economictimes.indiatimes.com", "Economic Times"),
    ("{q} Q2 results: net profit rises 18% YoY, beats estimates", "livemint.com", "Mint"),
    ("{q} shares slip as brokerage trims target price", "moneycontrol.com", "Moneycontrol"),
    ("{q} announces capacity expansion at new plant", "business-standard.com", "Business Standard"),
    ("Is {q} the next multibagger? Experts weigh in", "someblog.blogspot.com", "Some Blog"),
]


def _synthetic_news(query, limit):
    q = query.split(" ")[0]
    out = []
    for i, (t, dom, src) in enumerate(_HEADLINES[:limit]):
        out.append({
            "title": t.format(q=q), "url": f"https://{dom}/article/{i}",
            "source": src, "domain": dom,
            "date": (dt.date.today() - dt.timedelta(days=i * 3)).isoformat(),
        })
    return out


def _synthetic_announcements(symbol):
    return [
        {"title": "Outcome of Board Meeting - financial results", "text": "", "date": (dt.date.today() - dt.timedelta(days=12)).isoformat(),
         "url": f"https://nsearchives.nseindia.com/{symbol}/1.pdf"},
        {"title": "Award of order", "text": "The company has received an order", "date": (dt.date.today() - dt.timedelta(days=5)).isoformat(),
         "url": f"https://nsearchives.nseindia.com/{symbol}/2.pdf"},
    ]


def _synthetic_insider(symbol):
    return [
        {"name": "Promoter Holdings Pvt Ltd", "category": "Promoter Group", "type": "Buy",
         "shares": 50000, "value": 2.5e7, "pct_after": 0.52,
         "date": (dt.date.today() - dt.timedelta(days=40)).isoformat(), "url": ""},
    ]


def _synthetic_shareholding(symbol):
    today = dt.date.today()
    return [
        {"date": (today - dt.timedelta(days=30 + 91 * i)).isoformat(),
         "promoter": 0.52 - 0.002 * i, "public": 0.48 + 0.002 * i, "employee_trusts": None}
        for i in range(4)
    ]
