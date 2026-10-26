"""
Live market data for the web app: index quotes, charts, a market scanner and
the watchlist tracker.

Prices come from Yahoo Finance through yfinance. Yahoo's NSE quotes can lag
the exchange by up to 15 minutes, and the UI says so. Every download goes
through one lock: yfinance keeps module-level state that two downloads at
once can mix up.

The tracker is a background thread. While the market is open it polls the
watchlist every `poll_open` seconds (every `poll_closed` otherwise), keeps
the latest quote for each company, stores every minute bar in
data/live/market.db - so a tracked company builds up an intraday history
longer than Yahoo's 7-day window - and raises alerts when a price crosses a
level you set, falls below the HYBRID MODEL's buy-below price, or moves more
than `move_alert` in a day.

Each covered company is also re-valued at the live price: the HYBRID MODEL's
value comes from the accounts, so only the upside, the label and the
buy-below test change as the price moves.
"""

import json
import logging
import math
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from server import data as D

logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # failed symbols are reported, not printed

LIVE = D.DATA / "live"
WATCHLIST = LIVE / "watchlist.json"          # before watchlist libraries; migrated once
WATCHLISTS = LIVE / "watchlists.json"
SETTINGS = LIVE / "tracker.json"
DB = LIVE / "market.db"
IST = timezone(timedelta(hours=5, minutes=30))
TICKER = re.compile(r"^[A-Za-z0-9&^._\-=]{1,25}$")
MAX_TRACKED = 100   # companies across every watchlist (the tracker polls them all)
MAX_LISTS = 50
COLORS = ("#3994bc", "#86cf86", "#e0b97f", "#ad80d7", "#ef8773", "#4ec9b0", "#c586c0", "#d7ba7d", "#9cdcfe")
LISTS = (("coverage", D.COMPANIES_CSV), ("training", D.DATA / "training_universe.csv"),
         ("training", D.DATA / "auto_training_universe.csv"))
INDICES = [("NIFTY 50", "^NSEI"), ("SENSEX", "^BSESN"), ("NIFTY BANK", "^NSEBANK"), ("NIFTY IT", "^CNXIT"),
           ("NIFTY MIDCAP 50", "^NSEMDCP50"), ("FIN SERVICES", "NIFTY_FIN_SERVICE.NS"), ("INDIA VIX", "^INDIAVIX")]
SECTOR_INDICES = [("Auto", "^CNXAUTO"), ("Pharma", "^CNXPHARMA"), ("FMCG", "^CNXFMCG"), ("Metal", "^CNXMETAL"),
                  ("Energy", "^CNXENERGY"), ("Realty", "^CNXREALTY"), ("PSU Bank", "^CNXPSUBANK"), ("IT", "^CNXIT"),
                  ("Bank", "^NSEBANK")]
RANGES = {"1d": ("1d", "1m"), "5d": ("5d", "5m"), "1mo": ("1mo", "30m"), "6mo": ("6mo", "1d"),
          "1y": ("1y", "1d"), "5y": ("5y", "1wk"), "max": ("max", "1mo")}
DEFAULTS = {"paused": False, "poll_open": 30, "poll_closed": 900, "move_alert": 0.05, "retention_days": 120}
LIMITS = {"poll_open": (15, 600), "poll_closed": (60, 7200), "move_alert": (0.0, 0.5), "retention_days": (7, 3650)}


# ================================================================ helpers
def market_status(now=None):
    """NSE cash-market hours, 09:15-15:30 IST on weekdays. Exchange holidays
    are not known here; the tracker flags a quote that stops moving."""
    now = now or datetime.now(IST)
    m = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    state = ("pre-open" if weekday and 540 <= m < 555 else
             "open" if weekday and 555 <= m < 930 else "closed")
    nxt = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if m >= 555:
        nxt += timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return {"state": state, "ist": now.strftime("%a %d %b %Y, %H:%M IST"), "next_open": nxt.timestamp(),
            "closes_at": close.timestamp() if state == "open" else None, "source": "Yahoo Finance",
            "delay_note": "NSE quotes from Yahoo Finance can lag the exchange by up to 15 minutes"}


def is_open():
    return market_status()["state"] in ("open", "pre-open")


_yf_lock = threading.Lock()


def download(tickers, period, interval):
    """Batched OHLCV download. -> {ticker: DataFrame with Open/High/Low/Close/Volume}
    Symbols Yahoo has no data for are simply absent."""
    import pandas as pd
    import yfinance as yf

    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return {}
    with _yf_lock:
        df = yf.download(tickers, period=period, interval=interval, group_by="ticker",
                         auto_adjust=False, progress=False, threads=True)
    out = {}
    if df is None or df.empty:
        return out
    if isinstance(df.columns, pd.MultiIndex):
        lvl = 0 if set(df.columns.get_level_values(0)) & set(tickers) else 1
        names = set(df.columns.get_level_values(lvl))
        for t in tickers:
            if t in names:
                sub = df.xs(t, axis=1, level=lvl).dropna(subset=["Close"])
                if not sub.empty:
                    out[t] = sub
    else:
        sub = df.dropna(subset=["Close"])
        if not sub.empty:
            out[tickers[0]] = sub
    return out


def _f(x, nd=2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def bars(df):
    return [{"t": int(ts.timestamp()), "o": _f(r.Open), "h": _f(r.High), "l": _f(r.Low), "c": _f(r.Close),
             "v": int(r.Volume) if r.Volume == r.Volume else 0} for ts, r in df.iterrows()]


def _session(ts):
    return ts.tz_convert(IST).date() if ts.tzinfo else ts.date()


def _prev_close(daily, session):
    """Close of the last session before `session` (a date)."""
    if daily is None or daily.empty:
        return None
    before = [(_session(ts), c) for ts, c in daily["Close"].items() if _session(ts) < session]
    return float(before[-1][1]) if before else None


def _downsample(values, n):
    if len(values) <= n:
        return values
    step = len(values) / n
    return [values[int(i * step)] for i in range(n - 1)] + [values[-1]]


def _rsi(closes, n=14):
    d = closes.diff().dropna()
    if len(d) <= n:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return 100.0 if dn == 0 else float(100 - 100 / (1 + up / dn))


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, value):
    LIVE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


# ================================================================ settings & lists
def settings():
    s = dict(DEFAULTS)
    s.update({k: v for k, v in _read_json(SETTINGS, {}).items() if k in DEFAULTS})
    return s


def save_settings(patch):
    s = settings()
    for k, v in (patch or {}).items():
        if k == "paused":
            s[k] = bool(v)
        elif k in LIMITS:
            lo, hi = LIMITS[k]
            try:
                s[k] = max(lo, min(hi, type(DEFAULTS[k])(v)))
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number")
    _write_json(SETTINGS, s)
    return s


_wl_lock = threading.RLock()

# Watchlist libraries. One file holds every list and the companies on them:
#   items  {ticker: {name, sector, cap, added, added_price, alerts, note}} - shared, because
#          price alerts and notes belong to the company, whichever lists it is on
#   lists  [{id, name, description, color, created, updated, tickers: [...]}]
# The tracker follows every company on any list.


def _slug(name, taken):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "list").lower()).strip("-")[:32] or "list"
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid


def _book():
    """The whole library, migrating the single watchlist of earlier versions on first use."""
    b = _read_json(WATCHLISTS, None)
    if isinstance(b, dict) and isinstance(b.get("lists"), list) and isinstance(b.get("items"), dict):
        b["lists"] = [x for x in b["lists"] if isinstance(x, dict) and x.get("id")]
        return b
    old = [w for w in _read_json(WATCHLIST, []) if isinstance(w, dict) and w.get("ticker")]
    now = time.time()
    b = {"version": 2, "items": {w["ticker"]: {k: v for k, v in w.items()} for w in old},
         "lists": [{"id": "my-watchlist", "name": "My watchlist", "description": "The companies you follow day to day.",
                    "color": COLORS[0], "created": min((w.get("added") or now for w in old), default=now), "updated": now,
                    "tickers": [w["ticker"] for w in old]}]}
    _write_json(WATCHLISTS, b)
    return b


def _save_book(b):
    # drop companies no list holds any more (their minute bars stay in the database)
    held = {t for x in b["lists"] for t in x["tickers"]}
    b["items"] = {t: v for t, v in b["items"].items() if t in held}
    _write_json(WATCHLISTS, b)


def watchlist():
    """Every company on any watchlist, once each, in the order they were first listed."""
    b = _book()
    seen, out = set(), []
    for x in b["lists"]:
        for t in x["tickers"]:
            if t not in seen and t in b["items"]:
                seen.add(t)
                out.append({"ticker": t, **b["items"][t]})
    return out


def _find_list(b, list_id):
    hit = next((x for x in b["lists"] if x["id"] == list_id), None)
    if not hit:
        raise KeyError(f"no watchlist {list_id}")
    return hit


def _list_view(b, x):
    return {k: x.get(k) for k in ("id", "name", "description", "color", "icon", "created", "updated", "pinned")} | {
        "tickers": list(x["tickers"]), "count": len(x["tickers"]),
        "companies": [{"ticker": t, "name": b["items"].get(t, {}).get("name", t), "sector": b["items"].get(t, {}).get("sector", "")} for t in x["tickers"]],
    }


def watchlists():
    b = _book()
    return {"lists": [_list_view(b, x) for x in b["lists"]], "tracked": len(watchlist()), "max_tracked": MAX_TRACKED, "colors": list(COLORS)}


def _clean_meta(patch, current=None):
    out = {}
    if "name" in patch:
        name = str(patch.get("name") or "").strip()[:60]
        if not name:
            raise ValueError("a watchlist needs a name")
        out["name"] = name
    if "description" in patch:
        out["description"] = str(patch.get("description") or "").strip()[:400]
    if "color" in patch:
        c = str(patch.get("color") or "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError("a colour is #rrggbb")
        out["color"] = c
    if "icon" in patch:
        out["icon"] = re.sub(r"[^a-z0-9\-]", "", str(patch.get("icon") or ""))[:40]
    if "pinned" in patch:
        out["pinned"] = bool(patch.get("pinned"))
    return out


def create_list(patch):
    with _wl_lock:
        b = _book()
        if len(b["lists"]) >= MAX_LISTS:
            raise ValueError(f"up to {MAX_LISTS} watchlists")
        meta = _clean_meta({"name": patch.get("name"), "description": patch.get("description", ""),
                            "color": patch.get("color") or COLORS[len(b["lists"]) % len(COLORS)], **({"icon": patch["icon"]} if "icon" in patch else {})})
        now = time.time()
        x = {"id": _slug(meta["name"], {y["id"] for y in b["lists"]}), **meta, "created": now, "updated": now, "tickers": []}
        b["lists"].append(x)
        _save_book(b)
    for t in patch.get("tickers") or []:
        if isinstance(t, dict):
            add(t.get("ticker"), t.get("name"), t.get("sector"), t.get("cap"), list_id=x["id"])
        else:
            add(t, list_id=x["id"])
    return _list_view(_book(), _find_list(_book(), x["id"]))


def update_list(list_id, patch):
    with _wl_lock:
        b = _book()
        x = _find_list(b, list_id)
        x.update(_clean_meta(patch, x))
        if "tickers" in patch:  # a new order, same companies
            order = [t for t in patch["tickers"] if t in x["tickers"]]
            x["tickers"] = order + [t for t in x["tickers"] if t not in order]
        x["updated"] = time.time()
        _save_book(b)
        return _list_view(b, x)


def delete_list(list_id):
    with _wl_lock:
        b = _book()
        _find_list(b, list_id)
        if len(b["lists"]) <= 1:
            raise ValueError("keep at least one watchlist - empty it instead")
        b["lists"] = [x for x in b["lists"] if x["id"] != list_id]
        _save_book(b)
    TRACKER.poke()
    return watchlists()


def duplicate_list(list_id, name=None):
    b = _book()
    x = _find_list(b, list_id)
    return create_list({"name": name or f"{x['name']} (copy)", "description": x.get("description", ""), "color": x.get("color"),
                        "tickers": list(x["tickers"])})


def universe():
    """Every company the app knows: {ticker: {ticker, name, sector, cap, lists}}"""
    out = {}

    def add(tag, t, name, sector, cap):
        t = (t or "").strip()
        if not t or not TICKER.match(t) or t.upper().startswith("DUMMY"):
            return
        e = out.setdefault(t, {"ticker": t, "name": (name or t).strip(), "sector": (sector or "").strip(),
                               "cap": (cap or "").strip(), "lists": []})
        if tag not in e["lists"]:
            e["lists"].append(tag)

    for tag, path in LISTS:
        for r in D.read_csv(path, numeric=False):
            add(tag, r.get("ticker"), r.get("company name"), r.get("sector name"), r.get("market cap"))
    for w in watchlist():
        add("watchlist", w["ticker"], w.get("name"), w.get("sector"), w.get("cap"))
    return out


def sectors():
    return sorted({e["sector"] for e in universe().values() if e["sector"]})


def search(q, limit=12):
    q = (q or "").strip()
    if not q:
        return []
    ql = q.lower()
    hits = []
    for e in universe().values():
        name, t = e["name"].lower(), e["ticker"].lower()
        score = (0 if t.split(".")[0] == ql else 1 if t.startswith(ql) else 2 if name.startswith(ql)
                 else 3 if ql in name or ql in t else None)
        if score is not None:
            hits.append((score, e["name"], e))
    hits.sort(key=lambda h: (h[0], h[1]))
    out = [h[2] for h in hits[:limit]]
    sym = q.upper()
    if TICKER.match(sym) and not any(e["ticker"].split(".")[0] == sym.split(".")[0] for e in out):
        guess = sym if "." in sym or sym.startswith("^") else sym + ".NS"
        out.append({"ticker": guess, "name": guess, "sector": "", "cap": "", "lists": [], "lookup": True})
    return out


# ================================================================ HYBRID MODEL at the live price
class Valuer:
    """HYBRID MODEL inputs by ticker, re-read whenever the report, the research
    or the settings file changes."""

    def __init__(self):
        self.key, self.by_ticker, self.lock = None, {}, threading.Lock()

    def _load(self):
        key = (D.mtime(D.OUTPUT / "hybrid_model_bases.json"),
               D.mtime(D.intel_state() / "latest" / "verdicts.json"),
               D.mtime(D.ROOT / "agent_settings.yaml"))
        with self.lock:
            if key != self.key:
                from agents import settings as S
                from server import hybrid_api

                S.load()
                by = {}
                try:
                    for name, s in hybrid_api.sources().items():
                        t = s.get("ticker") or (s.get("base") or {}).get("ticker")
                        if t:
                            by[t] = {**s, "company": name}
                except Exception:  # noqa: BLE001 - no report yet is a normal state
                    by = {}
                self.key, self.by_ticker = key, by
        return self.by_ticker

    def covered(self):
        return set(self._load())

    def at_price(self, ticker, price):
        s = self._load().get(ticker)
        if not s or not price:
            return None
        import hybrid_model as HM

        base = {**s["base"], "price": float(price)}
        if base.get("shares"):  # as a quick sweep does: market cap follows the price
            base["market_cap"] = base["price"] * base["shares"]
            base["market_cap_cr"] = base["market_cap"] / 1e7
        try:
            r = HM.evaluate(base, s["signals"])
        except Exception:  # noqa: BLE001
            return None
        return D.clean({"company": s["company"], "value": r["value"], "low": r["low"], "high": r["high"],
                        "buy_below": r["buy_below"], "label": r["label"], "upside": r["upside"],
                        "confidence": r["confidence"], "fy": s["base"].get("fy"), "source": s["source"]})


VALUER = Valuer()


# ================================================================ cache
class _TTL:
    def __init__(self):
        self.d, self.lock = {}, threading.Lock()

    def get(self, key, ttl, fn):
        with self.lock:
            hit = self.d.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = fn()
        with self.lock:
            self.d[key] = (time.time(), val)
            if len(self.d) > 300:
                for k in sorted(self.d, key=lambda k: self.d[k][0])[:100]:
                    self.d.pop(k, None)
        return val


_cache = _TTL()


# ================================================================ indices & charts
def _quote_rows(pairs, spark_interval="5m"):
    ticks = [t for _, t in pairs]
    daily = download(ticks, "1mo", "1d")
    intra = download(ticks, "1d", spark_interval)
    rows = []
    for name, t in pairs:
        dd, it = daily.get(t), intra.get(t)
        src = it if it is not None else dd
        if src is None:
            continue
        last = float(src["Close"].iloc[-1])
        session = _session(src.index[-1])
        prev = _prev_close(dd, session)
        rows.append({"name": name, "ticker": t, "last": _f(last), "prev": _f(prev),
                     "chg_pct": (last / prev - 1) if prev else None, "t": int(src.index[-1].timestamp()),
                     "spark": [_f(x) for x in _downsample(list(it["Close"]) if it is not None else [], 78)],
                     "month": [_f(x) for x in dd["Close"].tolist()] if dd is not None else []})
    return D.clean(rows)


def indices():
    ttl = 30 if is_open() else 600
    return {"market": market_status(),
            "indices": _cache.get(("indices",), ttl, lambda: _quote_rows(INDICES)),
            "sectors": _cache.get(("sectors",), ttl * 2, lambda: _quote_rows(SECTOR_INDICES, "15m"))}


def chart(ticker, rng="1d"):
    ticker = (ticker or "").strip()
    if not TICKER.match(ticker):
        raise ValueError("not a ticker symbol")
    if rng == "tracked":
        return tracked_chart(ticker)
    if rng not in RANGES:
        raise ValueError(f"range must be one of {', '.join(RANGES)} or tracked")
    period, interval = RANGES[rng]
    intraday = interval.endswith("m")
    ttl = (20 if is_open() else 600) if intraday else 900

    def go():
        df = download([ticker], period, interval).get(ticker)
        if df is None:
            raise LookupError(f"Yahoo Finance has no prices for {ticker}")
        daily = download([ticker], "1mo", "1d").get(ticker) if intraday else df
        b = bars(df)
        last = b[-1]["c"]
        if rng == "1d":
            prev = _prev_close(daily, _session(df.index[-1]))
        elif len(b) > 1:
            prev = b[0]["o"] or b[0]["c"]
        else:
            prev = None
        return {"ticker": ticker, "range": rng, "interval": interval, "bars": b, "last": last,
                "prev_close": _f(prev), "chg_pct": (last / prev - 1) if prev and last else None}

    out = dict(_cache.get(("chart", ticker, rng), ttl, go))
    meta = universe().get(ticker) or {"ticker": ticker, "name": ticker, "sector": "", "cap": "", "lists": []}
    out.update(meta=meta, hm=VALUER.at_price(ticker, out["last"]), tracked=ticker in {w["ticker"] for w in watchlist()},
               market=market_status())
    return D.clean(out)


# ================================================================ scanner
class Scanner:
    """One batched daily download of every known company (~8 s for 400),
    refreshed every minute while the market is open and every 30 otherwise."""

    def __init__(self):
        self.rows, self.at, self.running, self.error, self.took = [], 0.0, False, None, None
        self.lock = threading.Lock()

    def snapshot(self, refresh=False):
        age = 60 if is_open() else 1800
        if refresh or time.time() - self.at > age:
            self.start()
        return {"rows": self.rows, "as_of": self.at or None, "scanning": self.running, "error": self.error,
                "seconds": self.took, "market": market_status()}

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
        threading.Thread(target=self._run, daemon=True, name="scanner").start()

    def _run(self):
        t0 = time.time()
        try:
            uni = universe()
            got = download(list(uni), "1y", "1d")
            rows = [r for r in (self._row(uni[t], df) for t, df in got.items()) if r]
            self.rows, self.at, self.error = D.clean(rows), time.time(), None
            self.took = round(time.time() - t0, 1)
        except Exception as e:  # noqa: BLE001 - shown in the UI, the old snapshot stays
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.running = False

    @staticmethod
    def _row(meta, df):
        c = df["Close"].astype(float)
        v = df["Volume"].fillna(0).astype(float)
        if len(c) < 2:
            return None
        last, prev = float(c.iloc[-1]), float(c.iloc[-2])
        avg = float(v.iloc[-21:-1].mean()) if len(v) > 5 else None
        hi, lo = float(df["High"].max()), float(df["Low"].min())

        def ret(n):
            return last / float(c.iloc[-1 - n]) - 1 if len(c) > n else None

        row = {**meta, "last": last, "prev": prev, "chg": last - prev, "chg_pct": last / prev - 1 if prev else None,
               "open": _f(df["Open"].iloc[-1]), "high": _f(df["High"].iloc[-1]), "low": _f(df["Low"].iloc[-1]),
               "volume": float(v.iloc[-1]), "avg_volume": avg, "vol_ratio": float(v.iloc[-1]) / avg if avg else None,
               "turnover": last * float(v.iloc[-1]), "hi_52": hi, "lo_52": lo, "from_hi": last / hi - 1 if hi else None,
               "from_lo": last / lo - 1 if lo else None, "ret_1w": ret(5), "ret_1m": ret(21), "ret_3m": ret(63),
               "ret_1y": last / float(c.iloc[0]) - 1, "rsi": _rsi(c), "date": str(_session(df.index[-1])),
               "spark": [_f(x) for x in c.iloc[-60:].tolist()]}
        hm = VALUER.at_price(meta["ticker"], last)
        if hm:
            row["hm"] = hm
        return row


SCANNER = Scanner()


# ================================================================ tracker
def _db():
    LIVE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _init_db():
    with _db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS bars (ticker TEXT, t INTEGER, o REAL, h REAL, l REAL, c REAL, "
                    "v INTEGER, PRIMARY KEY (ticker, t))")
        con.execute("CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, ticker TEXT, "
                    "name TEXT, kind TEXT, message TEXT, price REAL, level REAL, session TEXT, seen INTEGER DEFAULT 0)")


class Tracker:
    def __init__(self):
        self.quotes, self.last_poll, self.next_poll, self.error, self.polls = {}, None, 0.0, None, 0
        self.armed = {}
        self.wake = threading.Event()
        self.dirty = False  # a poke that arrived mid-poll still gets its poll
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        _init_db()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="tracker")
        self.thread.start()

    def poke(self):
        """Poll now (the watchlist or the settings changed)."""
        self.dirty = True
        self.wake.set()

    def state(self):
        s = settings()
        return {"running": bool(self.thread and self.thread.is_alive()), "paused": s["paused"],
                "interval": s["poll_open"] if is_open() else s["poll_closed"], "last_poll": self.last_poll,
                "next_poll": self.next_poll or None, "error": self.error, "polls": self.polls, "settings": s,
                "market": market_status(), "stored_bars": self._count()}

    def _count(self):
        try:
            with _db() as con:
                return con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        except sqlite3.Error:
            return None

    def _loop(self):
        while True:
            s = settings()
            wl = watchlist()
            if wl and not s["paused"] and (self.dirty or time.time() >= self.next_poll):
                self.dirty = False
                try:
                    self.poll(wl, s)
                    self.error = None
                except Exception as e:  # noqa: BLE001 - keep tracking; show the problem
                    self.error = f"{type(e).__name__}: {e}"
                self.next_poll = time.time() + (s["poll_open"] if is_open() else s["poll_closed"])
            self.wake.wait(timeout=2)
            self.wake.clear()

    def poll(self, wl, s):
        ticks = [w["ticker"] for w in wl]
        intra = download(ticks, "5d", "1m")
        daily = download(ticks, "3mo", "1d")
        now = time.time()
        rows = []
        for t, df in intra.items():
            rows += [(t, b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in bars(df)]
        with _db() as con:
            con.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?)", rows)
            con.execute("DELETE FROM bars WHERE t < ?", (now - s["retention_days"] * 86400,))
        changed = False
        for w in wl:
            q = self._quote(w["ticker"], intra.get(w["ticker"]), daily.get(w["ticker"]), now)
            self.quotes[w["ticker"]] = q
            if q.get("last") and w.get("added_price") is None:
                w["added_price"] = q["last"]
                changed = True
            if q.get("last"):
                self._alerts(w, q, s)
        if changed:
            with _wl_lock:
                b = _book()
                for w in wl:
                    it = b["items"].get(w["ticker"])
                    if it is not None and it.get("added_price") is None:
                        it["added_price"] = w.get("added_price")
                _save_book(b)
        self.last_poll, self.polls = now, self.polls + 1

    @staticmethod
    def _quote(t, intra, daily, now):
        if intra is None and daily is None:
            return {"ticker": t, "error": "Yahoo Finance returned no prices for this symbol", "polled": now}
        src = intra if intra is not None else daily
        session = _session(src.index[-1])
        today = src[[_session(ts) == session for ts in src.index]]
        last = float(today["Close"].iloc[-1])
        prev = _prev_close(daily, session)
        bar_t = int(today.index[-1].timestamp())
        q = {"ticker": t, "last": _f(last), "t": bar_t, "session": str(session), "prev_close": _f(prev),
             "chg": _f(last - prev) if prev else None, "chg_pct": (last / prev - 1) if prev else None,
             "open": _f(today["Open"].iloc[0]), "high": _f(today["High"].max()), "low": _f(today["Low"].min()),
             "volume": int(today["Volume"].fillna(0).sum()), "polled": now,
             "spark": [_f(x) for x in _downsample(list(today["Close"]), 80)] if intra is not None else [],
             "month": [_f(x) for x in daily["Close"].tolist()[-22:]] if daily is not None else [],
             "hi_3m": _f(daily["High"].max()) if daily is not None else None,
             "lo_3m": _f(daily["Low"].min()) if daily is not None else None,
             "stale": is_open() and now - bar_t > 20 * 60}
        q["hm"] = VALUER.at_price(t, last)
        return D.clean(q)

    def _alerts(self, w, q, s):
        t, last = w["ticker"], q["last"]
        name = w.get("name") or t
        conds = {}
        if w.get("alert_below") and last <= float(w["alert_below"]):
            conds["below"] = (f"{name} fell to {last:,.2f}, at or below your alert level {float(w['alert_below']):,.2f}",
                              float(w["alert_below"]))
        if w.get("alert_above") and last >= float(w["alert_above"]):
            conds["above"] = (f"{name} rose to {last:,.2f}, at or above your alert level {float(w['alert_above']):,.2f}",
                              float(w["alert_above"]))
        bb = (q.get("hm") or {}).get("buy_below")
        if bb and last <= bb:
            conds["buy_below"] = (f"{name} at {last:,.2f} is below the HYBRID MODEL buy-below price {bb:,.2f}", bb)
        mv = s.get("move_alert") or 0
        if mv and q.get("chg_pct") is not None and abs(q["chg_pct"]) >= mv:
            conds["move"] = (f"{name} has moved {q['chg_pct']:+.1%} today", mv)
        with _db() as con:
            for kind, (msg, level) in conds.items():
                if not self.armed.get((t, kind)):
                    seen = con.execute("SELECT 1 FROM alerts WHERE ticker=? AND kind=? AND session=? LIMIT 1",
                                       (t, kind, q["session"])).fetchone()
                    if not seen:
                        con.execute("INSERT INTO alerts (t, ticker, name, kind, message, price, level, session) "
                                    "VALUES (?,?,?,?,?,?,?,?)", (time.time(), t, name, kind, msg, last, level, q["session"]))
                self.armed[(t, kind)] = True
        for kind in ("below", "above", "buy_below", "move"):
            if kind not in conds:
                self.armed[(t, kind)] = False


TRACKER = Tracker()


def tracked(list_id=None):
    """A watchlist (or every company on any list) joined with the tracker's latest quotes."""
    b = _book()
    if list_id:
        x = _find_list(b, list_id)
        rows = [{"ticker": t, **b["items"][t]} for t in x["tickers"] if t in b["items"]]
    else:
        rows = watchlist()
    out = []
    for w in rows:
        q = TRACKER.quotes.get(w["ticker"]) or {}
        since = (q["last"] / w["added_price"] - 1) if q.get("last") and w.get("added_price") else None
        lists = [y["id"] for y in b["lists"] if w["ticker"] in y["tickers"]]
        out.append({**w, "quote": q or None, "since_added": since, "lists": lists})
    view = _list_view(b, _find_list(b, list_id)) if list_id else None
    return D.clean({"items": out, "tracker": TRACKER.state(), "list": view})


def add(ticker, name=None, sector=None, cap=None, list_id=None):
    """Put a company on a watchlist (the first one when none is named)."""
    ticker = (ticker or "").strip()
    if not TICKER.match(ticker):
        raise ValueError("not a ticker symbol")
    with _wl_lock:
        b = _book()
        x = _find_list(b, list_id) if list_id else b["lists"][0]
        if ticker in x["tickers"]:
            return watchlist()
        if ticker not in b["items"]:
            if len({t for y in b["lists"] for t in y["tickers"]}) >= MAX_TRACKED:
                raise ValueError(f"the watchlists track up to {MAX_TRACKED} different companies")
            meta = universe().get(ticker) or {}
            b["items"][ticker] = {"name": (name or meta.get("name") or ticker).strip()[:120],
                                  "sector": (sector or meta.get("sector") or "Unclassified").strip()[:80],
                                  "cap": (cap or meta.get("cap") or "").strip()[:10], "added": time.time(),
                                  "added_price": None, "alert_below": None, "alert_above": None, "note": ""}
        x["tickers"].append(ticker)
        x["updated"] = time.time()
        _save_book(b)
    TRACKER.poke()
    return watchlist()


def update(ticker, patch):
    with _wl_lock:
        b = _book()
        hit = b["items"].get(ticker)
        if not hit:
            raise KeyError(ticker)
        for k in ("alert_below", "alert_above"):
            if k in patch:
                v = patch[k]
                if v in (None, ""):
                    hit[k] = None
                else:
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        raise ValueError(f"{k} must be a price")
                    if v <= 0:
                        raise ValueError(f"{k} must be above zero")
                    hit[k] = v
        if "note" in patch:
            hit["note"] = str(patch["note"] or "")[:500]
        if patch.get("sector"):
            hit["sector"] = str(patch["sector"])[:80]
        _save_book(b)
    TRACKER.poke()
    return {"ticker": ticker, **hit}


def remove(ticker, list_id=None):
    """Take a company off one watchlist, or off every list when none is named."""
    with _wl_lock:
        b = _book()
        for x in b["lists"]:
            if (list_id is None or x["id"] == list_id) and ticker in x["tickers"]:
                x["tickers"] = [t for t in x["tickers"] if t != ticker]
                x["updated"] = time.time()
        _save_book(b)
        still = ticker in b["items"]
    if not still:
        TRACKER.quotes.pop(ticker, None)
    return watchlist()


def tracked_chart(ticker, days=30, bucket=300):
    """Every stored minute bar of a tracked company, in 5-minute candles."""
    since = time.time() - days * 86400
    with _db() as con:
        rows = con.execute("SELECT t,o,h,l,c,v FROM bars WHERE ticker=? AND t>=? ORDER BY t", (ticker, since)).fetchall()
    agg = []
    for t, o, h, l, c, v in rows:
        k = t - t % bucket
        if agg and agg[-1]["t"] == k:
            a = agg[-1]
            a["h"], a["l"], a["c"], a["v"] = max(a["h"], h), min(a["l"], l), c, a["v"] + (v or 0)
        else:
            agg.append({"t": k, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    last = agg[-1]["c"] if agg else None
    meta = universe().get(ticker) or {"ticker": ticker, "name": ticker, "sector": "", "cap": "", "lists": []}
    return D.clean({"ticker": ticker, "range": "tracked", "interval": "5m", "bars": agg, "last": last,
                    "prev_close": agg[0]["o"] if agg else None,
                    "chg_pct": (last / agg[0]["o"] - 1) if agg and agg[0]["o"] else None, "meta": meta,
                    "hm": VALUER.at_price(ticker, last), "tracked": True, "market": market_status(),
                    "stored": len(rows)})


def alerts(limit=100):
    _init_db()
    with _db() as con:
        rows = con.execute("SELECT id,t,ticker,name,kind,message,price,level,session,seen FROM alerts "
                           "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    keys = ("id", "t", "ticker", "name", "kind", "message", "price", "level", "session", "seen")
    return [dict(zip(keys, r)) for r in rows]


def mark_alerts_seen():
    _init_db()
    with _db() as con:
        con.execute("UPDATE alerts SET seen=1 WHERE seen=0")
    return True


def delete_alert(alert_id):
    """Remove one alert. The tracker never re-raises it in the same session:
    it only fires when a condition becomes true again after being false."""
    _init_db()
    with _db() as con:
        n = con.execute("DELETE FROM alerts WHERE id=?", (int(alert_id),)).rowcount
    if not n:
        raise LookupError(f"no alert {alert_id}")
    return True


def clear_alerts():
    _init_db()
    with _db() as con:
        return con.execute("DELETE FROM alerts").rowcount
