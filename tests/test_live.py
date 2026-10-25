"""
Tests for the live market layer, the watchlist tracker and the learning
feed. No network: every Yahoo download is replaced by a synthetic frame, and
every file goes to a temporary folder.

    python -m pytest tests -q
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ["INTVAL_OUTPUT_DIR"] = tempfile.mkdtemp(prefix="intval_test_")

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
import learning  # noqa: E402
from server import jobs as J  # noqa: E402
from server import learning_api as LA  # noqa: E402
from server import live as L  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Live state, learning files and company lists all in tmp_path."""
    live = tmp_path / "live"
    for mod in (L, learning):
        monkeypatch.setattr(mod, "LIVE", live)
        monkeypatch.setattr(mod, "WATCHLIST", live / "watchlist.json")
    monkeypatch.setattr(L, "SETTINGS", live / "tracker.json")
    monkeypatch.setattr(L, "DB", live / "market.db")
    monkeypatch.setattr(learning, "UNIVERSE_CSV", live / "learning_universe.csv")
    monkeypatch.setattr(LA, "SETTINGS", live / "learning.json")
    monkeypatch.setattr(LA, "HISTORY", live / "learning_history.json")
    valued = tmp_path / "companies.csv"
    valued.write_text("company name,sector name,market cap,ticker\nAlpha Ltd,Banks,Large,ALPHA.NS\n", encoding="utf-8")
    train = tmp_path / "training.csv"
    train.write_text("company name,sector name,market cap,ticker\n"
                     "Alpha Ltd,Banks,Large,ALPHA.NS\nBeta Ltd,IT,Mid,BETA.NS\nGamma Ltd,IT,Small,GAMMA.NS\n", encoding="utf-8")
    auto = tmp_path / "auto.csv"
    auto.write_text("company name,sector name,market cap,ticker\nBeta Ltd,IT,Mid,BETA.NS\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_INPUT", valued)
    monkeypatch.setattr(learning, "LISTS", (("training list", train), ("auto-train", auto)))
    monkeypatch.setattr(L, "LISTS", (("coverage", valued), ("training", train), ("training", auto)))
    monkeypatch.setattr(L.VALUER, "at_price", lambda ticker, price: None)
    yield tmp_path


def frame(closes, start="2026-10-23 09:15", freq="1min", tz="Asia/Kolkata", volume=1000):
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz=tz)
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Adj Close": c,
                         "Volume": [volume] * len(c)}, index=idx)


# ---------------------------------------------------------------- market hours
@pytest.mark.parametrize("when,state", [
    ("2026-10-26 10:00", "open"),        # Monday
    ("2026-10-26 09:05", "pre-open"),
    ("2026-10-26 15:30", "closed"),
    ("2026-10-24 11:00", "closed"),      # Saturday
])
def test_market_status(when, state):
    now = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=L.IST)
    s = L.market_status(now)
    assert s["state"] == state
    nxt = datetime.fromtimestamp(s["next_open"], L.IST)
    assert nxt.weekday() < 5 and (nxt.hour, nxt.minute) == (9, 15) and nxt > now


# ---------------------------------------------------------------- downloads
def test_download_splits_batches_and_drops_missing(monkeypatch):
    import yfinance as yf

    a, b = frame([10, 11, 12]), frame([20, 21, 22])
    multi = pd.concat({"A.NS": a, "B.NS": b, "DEAD.NS": a * np.nan}, axis=1)
    monkeypatch.setattr(yf, "download", lambda *args, **k: multi)
    got = L.download(["A.NS", "B.NS", "DEAD.NS"], "1d", "1m")
    assert set(got) == {"A.NS", "B.NS"}
    assert got["B.NS"]["Close"].iloc[-1] == 22
    monkeypatch.setattr(yf, "download", lambda *args, **k: a)
    assert list(L.download(["A.NS"], "1d", "1m")) == ["A.NS"]


def test_scan_row_figures():
    df = frame(np.linspace(100, 130, 260), start="2025-10-01", freq="B")
    r = L.Scanner._row({"ticker": "X.NS", "name": "X", "sector": "IT", "cap": "", "lists": []}, df)
    assert r["last"] == pytest.approx(130)
    assert r["chg_pct"] > 0 and r["ret_1y"] == pytest.approx(0.3, rel=1e-3)
    assert r["from_hi"] == pytest.approx(130 / (130 * 1.01) - 1)
    assert r["rsi"] == 100.0            # only rises
    assert len(r["spark"]) == 60


# ---------------------------------------------------------------- watchlist
def test_watchlist_add_update_remove():
    L.add("BETA.NS")
    L.add("BETA.NS")                     # no duplicates
    wl = L.watchlist()
    assert len(wl) == 1 and wl[0]["name"] == "Beta Ltd" and wl[0]["sector"] == "IT"
    L.update("BETA.NS", {"alert_below": "95.5", "note": "watch the margin"})
    assert L.watchlist()[0]["alert_below"] == 95.5
    with pytest.raises(ValueError):
        L.update("BETA.NS", {"alert_above": -3})
    with pytest.raises(ValueError):
        L.add("bad ticker; rm -rf")
    with pytest.raises(KeyError):
        L.update("NOPE.NS", {"note": "x"})
    assert L.remove("BETA.NS") == []


def test_tracker_quote_and_alerts_fire_once():
    L._init_db()
    t = L.Tracker()
    intra = pd.concat([frame([100] * 5, start="2026-10-22 09:15"), frame([95, 94, 93], start="2026-10-23 09:15")])
    daily = frame([101, 100, 93], start="2026-10-21", freq="D")
    q = t._quote("BETA.NS", intra, daily, now=1e10)
    assert q["last"] == 93 and q["prev_close"] == 100 and q["session"] == "2026-10-23"
    assert q["chg_pct"] == pytest.approx(-0.07)
    assert q["high"] == pytest.approx(95 * 1.01)
    w = {"ticker": "BETA.NS", "name": "Beta", "alert_below": 94.0}
    s = {**L.DEFAULTS, "move_alert": 0.05}
    t._alerts(w, q, s)
    t._alerts(w, q, s)                       # still below: no repeat
    kinds = sorted(a["kind"] for a in L.alerts())
    assert kinds == ["below", "move"]
    t.armed.clear()                          # a server restart in the same session
    t._alerts(w, q, s)
    assert len(L.alerts()) == 2              # still only once per session


def test_poke_during_a_poll_is_not_lost():
    t = L.Tracker()
    t.next_poll = 1e12
    t.poke()
    assert t.dirty


# ---------------------------------------------------------------- learning
def test_learning_companies_dedupe_and_skip_valued():
    L.add("ZETA.NS", name="Zeta Ltd", sector="Energy")
    rows = {r["ticker"]: r for r in learning.companies()}
    assert set(rows) == {"BETA.NS", "GAMMA.NS", "ZETA.NS"}      # Alpha is being valued
    assert rows["BETA.NS"]["lists"] == ["training list", "auto-train"]
    assert rows["ZETA.NS"]["lists"] == ["watchlist"] and rows["ZETA.NS"]["sector"] == "Energy"
    path = learning.write_csv()
    assert path.read_text(encoding="utf-8").splitlines()[0] == "company name,sector name,market cap,ticker"


def test_build_args_learning(monkeypatch):
    monkeypatch.setattr(LA, "learning_csv", lambda: "/tmp/learning.csv")
    a = J.build_args("valuation", {"learning": True})
    assert a[a.index("--train-universe") + 1] == "/tmp/learning.csv"
    assert "--train-universe" not in J.build_args("valuation", {"learning": False})
    assert "--train-universe" not in J.build_args("valuation", {"learning": True, "offline": True})
    a = J.build_args("valuation", {"learning": True, "auto_train": {"target": 60}}, "t1")
    assert a[a.index("--train-universe") + 1] == "auto"
    a = J.build_args("learn", {"start_year": 2026, "end_year": 2020})
    assert a[:5] == ["--learn", "--start-year", "2020", "--end-year", "2026"]
    with pytest.raises(ValueError):
        J.build_args("learn", {"offline": True})


def test_learning_settings_validate():
    assert LA.save_settings({"auto_retrain": 1, "feed_after": "17:05"})["feed_after"] == "17:05"
    with pytest.raises(ValueError):
        LA.save_settings({"feed_after": "5pm"})
    assert json.loads(LA.SETTINGS.read_text())["auto_retrain"] is True


def test_build_universe_uses_the_cache(monkeypatch):
    import ticker_resolver

    import auto_train
    import pipeline
    import yf_source

    monkeypatch.setattr(ticker_resolver, "resolve", lambda name, t=None: t)
    monkeypatch.setattr(auto_train, "load_cached", lambda t: {"ticker": t, "years": {}})
    monkeypatch.setattr(yf_source, "fetch_company", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    uni, fails = pipeline.build_universe([{"name": "Beta Ltd", "sector": "IT", "cap": "Mid", "ticker": "BETA.NS"}], cached=True)
    assert "Beta Ltd" in uni and not fails


def test_verdict_without_saved_calibration_is_rebuilt():
    """Old research runs saved their inputs without lens_calibration; the
    Studio and the live views must still reproduce the verdict's value."""
    import hybrid_model as HM
    from agents import settings as S
    from server import hybrid_api

    S.load(ROOT / "agent_settings.yaml")
    base = {"sector": "Information Technology", "regime": "mature", "price": 500.0, "beta_adj": 1.0, "tax": 0.25,
            "shares": 1.0e8, "debt": 5.0e9, "cash": 2.0e9, "equity_book": 2.0e10, "fcff_norm": 3.0e9,
            "nopat": 3.5e9, "nopat_norm": 3.4e9, "ni_norm": 3.0e9, "roe_norm": 0.16, "g_base": 0.10,
            "market_cap": 5.0e10, "market_cap_cr": 5000.0, "de_ratio": 0.25, "pe_reg": 540.0, "ev_reg": 510.0,
            "graham": 380.0, "ml": None}
    cal = {"cash_flow": {"c": 0.3, "skill": 0.6}, "conservative": {"c": -0.8, "skill": 1.4},
           "market": {"c": 0.1, "skill": 1.1}}
    sig = {"risks": {}, "tilts": {}, "quality": {}, "red_flags": [], "conf_parts": {}}
    want = HM.evaluate({**base, "lens_calibration": cal}, sig)
    verdict = {**want, "base": base, "signals": sig, "company": "X"}
    got = hybrid_api._from_verdict(verdict)
    again = HM.evaluate(got["base"], got["signals"])
    assert again["lens_weights"] == pytest.approx(want["lens_weights"])
    # one lens is dropped as an outlier here, so its skill cannot be recovered
    assert again["value"] == pytest.approx(want["value"], rel=0.02)
    assert again["label"] == want["label"]
    # without the rebuild the value would be uncalibrated - far off
    assert HM.evaluate(base, sig)["value"] != pytest.approx(want["value"], rel=0.02)


def test_alerts_delete_and_clear():
    L._init_db()
    t = L.Tracker()
    q = {"ticker": "BETA.NS", "last": 90.0, "chg_pct": -0.1, "session": "2026-10-23", "hm": {"buy_below": 95.0}}
    t._alerts({"ticker": "BETA.NS", "name": "Beta", "alert_below": 92.0}, q, {**L.DEFAULTS})
    got = L.alerts()
    assert sorted(a["kind"] for a in got) == ["below", "buy_below", "move"]
    L.delete_alert(got[0]["id"])
    assert len(L.alerts()) == 2
    with pytest.raises(LookupError):
        L.delete_alert(got[0]["id"])
    assert L.clear_alerts() == 2 and L.alerts() == []


def test_autostart_settings_and_start(monkeypatch, isolated):
    from server import autostart as A

    monkeypatch.setattr(A, "SETTINGS", isolated / "live" / "autostart.json")
    assert A.settings() == A.DEFAULTS and A.settings()["llm"] is False   # rule-based unless switched on
    assert A.save({"mode": "full", "skip_recent": "5", "llm": 1})["mode"] == "full"
    with pytest.raises(ValueError):
        A.save({"skip_recent": "soon"})
    posted = []
    monkeypatch.setattr(A.agents_api, "post_system", lambda text: posted.append(text))

    class Jobs:
        def __init__(self, busy):
            self.busy, self.started = busy, []
        def active(self):
            return object() if self.busy else None
        def start(self, kind, opts):
            self.started.append((kind, opts))
            return type("J", (), {"id": "j1"})()

    busy = Jobs(True)
    assert A.start_now(busy) == (None, "another job is running") and not busy.started
    free = Jobs(False)
    job, why = A.start_now(free)
    assert why == "started" and free.started == [("agents", {"quick": False, "no_llm": False, "auto": "startup"})]
    assert posted and "full run" in posted[0]
