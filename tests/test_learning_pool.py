# FILE: tests/test_learning_pool.py
"""
The learning pool: every company the app knows is valued and learned from, by
the valuation report and by every agent run. No network:

    python -m pytest tests/test_learning_pool.py -q
"""

import csv
import json
import os
import pickle
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

os.environ["INTVAL_OUTPUT_DIR"] = tempfile.mkdtemp(prefix="intval_test_")

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
from agents import settings as S  # noqa: E402
from agents.blackboard import Blackboard  # noqa: E402


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    S.load(ROOT / "agent_settings.defaults.yaml")
    S.data().setdefault("run", {})["state_dir"] = str(tmp_path / "intel")
    monkeypatch.delenv("AGENT_STATE_DIR", raising=False)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    yield
    S.load(ROOT / "agent_settings.yaml")


def _csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company name", "sector name", "market cap", "ticker"])
        w.writerows(rows)
    return path


def test_pool_takes_in_every_list_and_every_researched_company(tmp_path, monkeypatch):
    import learning

    monkeypatch.setattr(config, "DEFAULT_INPUT", _csv(tmp_path / "companies.csv", [["Alpha Ltd", "Banks", "Large", "ALPHA.NS"]]))
    monkeypatch.setattr(learning, "LISTS", (("training list", _csv(tmp_path / "train.csv", [["Beta Ltd", "IT", "Mid", "BETA.NS"]])),))
    monkeypatch.setattr(learning, "WATCHLISTS", tmp_path / "watchlists.json")
    (tmp_path / "watchlists.json").write_text(json.dumps({"items": {
        "GAMMA.NS": {"name": "Gamma Ltd", "sector": ""}, "BETA.NS": {"name": "Beta Ltd", "sector": "IT"}}}), encoding="utf-8")
    board = Blackboard(S.state_dir() / "blackboard.sqlite")
    board.save_verdict(1, {"company": "Gamma Ltd", "ticker": "GAMMA.NS", "sector": "Pharma", "label": "Undervalued"})
    board.save_verdict(1, {"company": "Delta Ltd", "ticker": "DELTA.NS", "sector": "Metals", "label": "Overvalued"})
    board.save_verdict(2, {"company": "MOCK CLEAN ALPHA", "ticker": "MOCK", "sector": "MockTech"})  # an offline test run
    board.close()

    got = {r["ticker"]: r for r in learning.companies()}
    # every company the app knows; offline test runs never join
    assert set(got) == {"ALPHA.NS", "BETA.NS", "GAMMA.NS", "DELTA.NS"} and got["ALPHA.NS"]["lists"] == ["coverage"]
    assert got["DELTA.NS"]["lists"] == ["researched"] and got["DELTA.NS"]["sector"] == "Metals"
    # a watchlist that does not know the sector learns it from the research
    assert got["GAMMA.NS"]["sector"] == "Pharma" and set(got["GAMMA.NS"]["lists"]) == {"watchlist", "researched"}

    # a run leaves out the companies it values directly (a bare ticker matches too)
    run = [{"name": "Beta", "ticker": "BETA", "sector": "IT"}, {"company name": "Alpha Ltd", "ticker": "ALPHA.NS"}]
    assert {r["ticker"] for r in learning.companies(exclude=run)} == {"GAMMA.NS", "DELTA.NS"}


def test_cache_only_universe_never_downloads(monkeypatch):
    import auto_train
    import data_hub
    import pipeline

    saved = (config.FY_START, config.FY_END, config.OFFLINE)
    try:
        config.OFFLINE = False
        config.set_fy_range(2020, 2024)
        monkeypatch.setattr(data_hub, "fetch_company", lambda *a, **k: pytest.fail("downloaded"))
        folder = auto_train._cache_dir("train_cache")
        data = {"years": {2020: {"price": 10.0}}, "sources": []}
        # cached for the report's longer window: an agent run's shorter one still uses it
        with open(folder / "AAA.NS_2015_2025.pkl", "wb") as f:
            pickle.dump(data, f)
        with open(folder / "CCC.NS_2022_2025.pkl", "wb") as f:   # does not reach back to FY2020
            pickle.dump(data, f)
        uni, fails = pipeline.build_universe([
            {"name": "Aaa", "sector": "IT", "ticker": "AAA.NS"},
            {"name": "Bbb", "sector": "IT", "ticker": "BBB.NS"},
            {"name": "Ccc", "sector": "IT", "ticker": "CCC.NS"},
        ], cached="only", quiet=True)
        assert set(uni) == {"Aaa"} and uni["Aaa"]["data"] == data and uni["Aaa"]["ticker"] == "AAA.NS" and not fails
    finally:
        config.set_fy_range(saved[0], saved[1])
        config.OFFLINE = saved[2]


def test_ml_training_is_reused_until_the_data_changes(monkeypatch):
    import ml_common

    calls = []

    def fake(df, specs, failures, fy_list=None):
        calls.append(len(df))
        return ml_common.MLStore()

    monkeypatch.setattr(ml_common, "run_models", fake)
    df = pd.DataFrame({"company": ["A", "B"], "fy": [2023, 2023], "x": [1.0, 2.0], "label": [0.1, None]})
    specs = [{"key": "rf", "name": "Random Forest"}]
    ml_common.run_models_cached(df, specs, {})
    ml_common.run_models_cached(df.copy(), specs, {})
    assert calls == [2]
    ml_common.run_models_cached(df.assign(x=[1.0, 3.0]), specs, {})
    assert calls == [2, 2]


def test_report_values_the_learning_pool():
    import mock_source
    import pipeline
    import ticker_resolver

    saved = (config.FY_START, config.FY_END, config.OFFLINE, config.ANALYSIS_ENABLED, config.ML_ENABLED, ticker_resolver.resolve)
    mine, pool = mock_source.COMPANIES[:6], mock_source.COMPANIES[6:]
    try:
        config.OFFLINE, config.ANALYSIS_ENABLED, config.ML_ENABLED = True, False, False
        ticker_resolver.resolve = mock_source.resolve
        pipeline.run(mine, extra_training=pool)
        with open(config.OUTPUT_DIR / "Intrinsic_Value_Data.csv", encoding="utf-8-sig") as f:
            names = {r[0] for r in list(csv.reader(f))[1:]}
        # pool companies with accounts are valued (and scored) alongside the user's own
        assert {c["name"] for c in mine} & names and {c["name"] for c in pool} & names
    finally:
        config.set_fy_range(saved[0], saved[1])
        config.OFFLINE, config.ANALYSIS_ENABLED, config.ML_ENABLED, ticker_resolver.resolve = saved[2:]


def test_agent_runs_learn_from_the_pool(monkeypatch):
    import learning
    import pipeline
    from agents import runner

    assert runner._learning_pool([{"name": "X"}], offline=True) == {}   # offline tests stay offline
    seen = {}
    monkeypatch.setattr(learning, "companies", lambda exclude=None: seen.update(exclude=exclude) or [{"name": "P", "sector": "IT", "ticker": "P.NS"}])
    monkeypatch.setattr(pipeline, "build_universe", lambda rows, cached=False, quiet=False: ({r["name"]: {"sector": r["sector"]} for r in rows} if cached == "only" and quiet else pytest.fail("may download"), {}))
    run = [{"name": "X", "ticker": "X.NS", "sector": "IT"}]
    assert runner._learning_pool(run, offline=False) == {"P": {"sector": "IT"}}
    assert seen == {"exclude": run}
    S.data()["run"]["learn_from_pool"] = False
    assert runner._learning_pool(run, offline=False) == {}
