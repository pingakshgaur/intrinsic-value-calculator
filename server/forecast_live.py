# FILE: server/forecast_live.py
"""
Live price forecasts for one company, from the next 15 minutes to five
years, computed on request (well under a second) from what the app already
holds:

  * the tracker's stored minute bars (data/live/market.db) - intraday moves;
  * up to five years of daily closes (Yahoo, then the price_chain fallbacks,
    then the tracker's own bars) - volatility, short-term reversal / momentum;
  * the HYBRID MODEL value at the live price - where the price tends to go
    over months and years.

Every horizon is a median price with a P10-P90 band, the chance it ends
higher, and the share of the move each driver explains:

    log move(h) = drift·h + reversal/momentum(h) + value pull(h)
    band        = ± 1.28 · sigma(h)·sqrt(h)                   (lognormal)

  drift        the market's long-run return (11 % a year)
  reversal     AR(1) on 15-minute and daily returns, fitted to this stock's
               own history and clamped, so a noisy fit cannot dominate
  momentum     a shrunk 3-month trend, fading out beyond three months
  value pull   the gap to the HYBRID MODEL value, closed at a half-life of
               about 1.7 years (the pace prices close valuation gaps in the
               report's back-test), weighted by the model's confidence
  sigma(h)     recent (EWMA, lambda 0.94) volatility for short horizons,
               blending into the long-run volatility for long ones

The same rules are re-run on the stock's own past (walk-forward, no
look-ahead) to say how often the 1-day and 15-minute direction was right and
how often the 1-day band held the outcome - shown next to the forecast, so
it is never taken for more than it is. A statistical projection, not advice.
"""

import math
import threading
import time
from datetime import date, timedelta

import numpy as np

from server import live

SESSION_MIN = 375          # 09:15-15:30
YEAR = 252
LONG_DRIFT = math.log(1.11) / YEAR
HALF_LIFE_Y = 1.7
Z90 = 1.2816
HORIZONS = [  # key, label, trading days
    ("15m", "15 minutes", 15 / SESSION_MIN), ("1h", "1 hour", 60 / SESSION_MIN), ("1d", "1 day", 1), ("1w", "1 week", 5),
    ("1m", "1 month", 21), ("3m", "3 months", 63), ("6m", "6 months", 126), ("1y", "1 year", 252),
    ("3y", "3 years", 756), ("5y", "5 years", 1260),
]
_cache, _lock = {}, threading.Lock()


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _ar1(r, cap):
    """Lag-1 autocorrelation of a return series, shrunk towards zero by its sample size and clamped."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if len(r) < 30:
        return 0.0
    a, b = r[:-1] - r[:-1].mean(), r[1:] - r[1:].mean()
    den = math.sqrt((a * a).sum() * (b * b).sum())
    if not den:
        return 0.0
    phi = float((a * b).sum() / den)
    phi *= len(r) / (len(r) + 100)        # shrink: 100 returns count as much as the prior of zero
    return max(-cap, min(cap, phi))


def _ewma_sigma(r, lam=0.94):
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if not len(r):
        return None
    v = float(np.var(r[: min(20, len(r))])) or float(r[0] ** 2)
    for x in r:
        v = lam * v + (1 - lam) * x * x
    return math.sqrt(v)


def _ar_sum(phi, h):
    """Sum of phi + phi^2 + ... over h steps (fractional h allowed)."""
    if abs(phi) < 1e-9:
        return 0.0
    if abs(phi) >= 1:
        return phi * h
    return phi * (1 - phi ** h) / (1 - phi)


_fetching = set()


def _daily_closes(ticker):
    """Up to five years of daily closes (ascending numpy array) and where they came from - or
    (None, None) while they are still being downloaded: the first forecast for a company never
    waits on the network, it uses the stored prices and the next one has the full history."""
    hit = live._cache.d.get(("daily5y", ticker))
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    with _lock:
        if ticker in _fetching:
            return None, None
        _fetching.add(ticker)

    def run():
        try:
            live._cache.get(("daily5y", ticker), 0, go)
        finally:
            with _lock:
                _fetching.discard(ticker)
            _cache.pop(ticker, None)  # the next request recomputes with the longer history

    def go():
        try:
            df = live.download([ticker], "5y", "1d").get(ticker)
            if df is not None and len(df) > 30:
                return df["Close"].astype(float).dropna().to_numpy(), "Yahoo Finance"
        except Exception:  # noqa: BLE001
            pass
        try:
            import price_chain
            import source_settings

            s, used, _ = price_chain.closes(ticker, date.today() - timedelta(days=5 * 365), date.today(), skip=("yahoo",))
            if s is not None and len(s) > 30:
                return s.astype(float).to_numpy(), source_settings.BY_KEY[used]["label"]
        except Exception:  # noqa: BLE001
            pass
        return None, None

    threading.Thread(target=run, daemon=True, name=f"history-{ticker}").start()
    return None, None


def _stored_bars(ticker, days=10):
    since = time.time() - days * 86400
    try:
        with live._db() as con:
            rows = con.execute("SELECT t, c FROM bars WHERE ticker=? AND t>=? AND c IS NOT NULL ORDER BY t", (ticker, since)).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    return rows


def _sessions_from_bars(rows):
    """Last close of each session in the stored minute bars."""
    out = {}
    for t, c in rows:
        out[live.datetime.fromtimestamp(t, live.IST).date()] = c
    return np.array([out[k] for k in sorted(out)], float)


def _minute_returns(rows):
    """15-minute log returns within sessions (overnight gaps left out), and 1-minute ones."""
    if len(rows) < 20:
        return np.array([]), np.array([])
    t = np.array([r[0] for r in rows], float)
    c = np.array([r[1] for r in rows], float)
    day = np.array([live.datetime.fromtimestamp(x, live.IST).toordinal() for x in t])
    same = day[1:] == day[:-1]
    r1 = np.diff(np.log(c))[same & (np.diff(t) <= 300)]
    buckets = {}
    for x, cc, d in zip(t, c, day):
        buckets[(d, int(x // 900))] = cc
    keys = sorted(buckets)
    r15 = [math.log(buckets[b] / buckets[a]) for a, b in zip(keys, keys[1:]) if a[0] == b[0] and b[1] - a[1] == 1]
    return np.array(r15, float), r1


def _backtest_daily(c, phi_cap=0.2):
    """Walk-forward over the last year: direction hit-rate and P10-P90 cover of the 1-day forecast."""
    if len(c) < 320:
        return None
    r = np.diff(np.log(c))
    hits = cover = n = 0
    for i in range(len(r) - 250, len(r)):
        past = r[max(0, i - 500):i]
        phi = _ar1(past[-250:], phi_cap)
        mom = 0.25 * past[-63:].mean() if len(past) >= 63 else 0.0
        mu = LONG_DRIFT + phi * past[-1] + mom
        sig = math.sqrt(0.5 * (_ewma_sigma(past[-250:]) or 0) ** 2 + 0.5 * float(np.std(past)) ** 2)
        if not sig or r[i] == 0:
            continue
        n += 1
        hits += (mu > 0) == (r[i] > 0)
        cover += abs(r[i] - mu) <= Z90 * sig
    return {"n": n, "direction": hits / n, "band": cover / n} if n else None


def _backtest_15m(r15, phi):
    if len(r15) < 120:
        return None
    pred, act = np.sign(phi * r15[:-1]), np.sign(r15[1:])
    keep = (pred != 0) & (act != 0)
    if keep.sum() < 60:
        return None
    return {"n": int(keep.sum()), "direction": float((pred[keep] == act[keep]).mean())}


def forecast(ticker):
    ticker = (ticker or "").strip()
    if not live.TICKER.match(ticker):
        raise ValueError("not a ticker symbol")
    is_open = live.is_open()
    ttl = 20 if is_open else 300
    with _lock:
        hit = _cache.get(ticker)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    out = _forecast(ticker, is_open)
    with _lock:
        _cache[ticker] = (time.time(), out)
    return out


def _forecast(ticker, is_open):
    notes = []
    rows = _stored_bars(ticker)
    quote = live.TRACKER.quotes.get(ticker) or {}
    daily, src = _daily_closes(ticker)
    if daily is None or len(daily) < 30:
        own = _sessions_from_bars(_stored_bars(ticker, 3650))
        month = np.array([x for x in quote.get("month") or [] if x], float)
        daily = own if len(own) >= len(month) else month
        src = "the tracker's stored prices" if len(own) >= len(month) else "the last month of daily closes"
        if ticker in _fetching:
            notes.append("Downloading up to five years of daily prices - the next update uses them.")
        elif len(daily) < 30:
            notes.append("Little daily history was available, so the long-range bands lean on typical market volatility.")
    price = quote.get("last") or (rows[-1][1] if rows else None) or (float(daily[-1]) if len(daily) else None)
    if not price:
        raise LookupError(f"no price for {ticker} yet: no data provider answered and the tracker has not stored one (check Configuration -> Data sources)")
    price = float(price)
    as_of = quote.get("t") or (rows[-1][0] if rows else None)

    r = np.diff(np.log(daily[daily > 0])) if len(daily) > 1 else np.array([])
    r = r[np.isfinite(r)]
    sig_long = float(np.std(r[-756:])) if len(r) >= 30 else 0.02
    sig_short = _ewma_sigma(r[-250:]) if len(r) >= 30 else sig_long
    phi_d = _ar1(r[-500:], 0.2)
    r_last = float(r[-1]) if len(r) else 0.0
    mom = 0.25 * float(r[-63:].mean()) if len(r) >= 63 else 0.0

    r15, r1 = _minute_returns(rows)
    phi_15 = _ar1(r15, 0.3)
    # today's move so far since the last 15-minute mark: what intraday reversal / follow-through works on
    last15 = float(r15[-1]) if len(r15) else 0.0
    sig_min = float(np.std(r1)) if len(r1) >= 60 else sig_short / math.sqrt(SESSION_MIN)
    if not len(r15):
        notes.append("No minute prices are stored for it yet: the intraday forecasts use its daily volatility only.")

    hm = live.VALUER.at_price(ticker, price)
    gap = math.log(hm["value"] / price) if hm and hm.get("value") and hm["value"] > 0 else None
    conf = max(0.2, min(1.0, (hm.get("confidence") or 50) / 100)) if hm else 0
    if gap is None:
        notes.append("Not valued by the HYBRID MODEL yet, so months-to-years forecasts follow the market's long-run drift only.")

    horizons = []
    for key, label, h in HORIZONS:
        if h < 1:
            steps = h * SESSION_MIN / 15
            rev = _ar_sum(phi_15, steps) * last15
            sig = sig_min * math.sqrt(h * SESSION_MIN)
            momentum, value = 0.0, 0.0
        else:
            rev = _ar_sum(phi_d, h) * r_last
            momentum = mom * min(h, 63)
            value = conf * (1 - 0.5 ** (h / (HALF_LIFE_Y * YEAR))) * gap if gap is not None else 0.0
            w = math.exp(-h / 21)
            sig = math.sqrt(w * sig_short ** 2 + (1 - w) * sig_long ** 2) * math.sqrt(h)
        drift = LONG_DRIFT * h
        mu = drift + rev + momentum + value
        sig = max(sig, 1e-6)
        parts = {"drift": drift, "reversal": rev, "momentum": momentum, "value": value}
        lead = max(parts, key=lambda k: abs(parts[k]))
        horizons.append({
            "key": key, "label": label, "days": h, "price": price * math.exp(mu),
            "low": price * math.exp(mu - Z90 * sig), "high": price * math.exp(mu + Z90 * sig),
            "change": math.exp(mu) - 1, "p_up": _norm_cdf(mu / sig), "parts": parts, "lead": lead,
        })

    acc = {"1d": _backtest_daily(daily) if len(daily) >= 320 else None, "15m": _backtest_15m(r15, phi_15)}
    meta = live.universe().get(ticker) or {"name": ticker, "sector": ""}
    return live.D.clean({
        "ticker": ticker, "name": meta.get("name"), "price": price, "as_of": as_of, "computed": time.time(),
        "market": live.market_status(), "live": bool(is_open and quote.get("last")),
        "value": hm, "gap": gap, "horizons": horizons, "accuracy": acc,
        "inputs": {"daily_closes": int(len(daily)), "daily_source": src, "minute_bars": len(rows),
                   "sigma_day": sig_short, "sigma_long": sig_long, "phi_day": phi_d, "phi_15m": phi_15,
                   "momentum_3m": mom * 63 / 0.25 if mom else 0.0},
        "notes": notes,
    })


def quick(tickers):
    """The 1-hour, 1-day and 1-month view for many tracked companies at once (Markets' radar):
    the same rules on the tracker's stored bars and last month of closes - no downloads."""
    out = {}
    for t in tickers:
        q = live.TRACKER.quotes.get(t) or {}
        rows = _stored_bars(t, 5)
        price = q.get("last") or (rows[-1][1] if rows else None)
        if not price:
            continue
        month = np.array([x for x in q.get("month") or [] if x], float)
        r = np.diff(np.log(month)) if len(month) > 2 else np.array([])
        sig_d = float(np.std(r)) if len(r) > 5 else 0.02
        r15, r1 = _minute_returns(rows)
        phi = _ar1(r15, 0.3)
        sig_min = float(np.std(r1)) if len(r1) >= 60 else sig_d / math.sqrt(SESSION_MIN)
        hm = q.get("hm") or live.VALUER.at_price(t, price) or {}
        gap = math.log(hm["value"] / price) if hm.get("value") and hm["value"] > 0 else None
        conf = max(0.2, min(1.0, (hm.get("confidence") or 50) / 100))
        res = {}
        for key, h in (("1h", 60 / SESSION_MIN), ("1d", 1), ("1m", 21)):
            if h < 1:
                mu = _ar_sum(phi, h * SESSION_MIN / 15) * (float(r15[-1]) if len(r15) else 0.0)
                sig = sig_min * math.sqrt(h * SESSION_MIN)
            else:
                mu = LONG_DRIFT * h + (conf * (1 - 0.5 ** (h / (HALF_LIFE_Y * YEAR))) * gap if gap is not None else 0.0)
                sig = sig_d * math.sqrt(h)
            res[key] = {"change": math.exp(mu) - 1, "p_up": _norm_cdf(mu / max(sig, 1e-6)),
                        "low": price * math.exp(mu - Z90 * sig), "high": price * math.exp(mu + Z90 * sig)}
        out[t] = res
    return live.D.clean(out)
