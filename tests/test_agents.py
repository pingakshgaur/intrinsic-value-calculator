"""
Tests for the HYBRID MODEL and the market intelligence agents. No network,
no API keys, and nothing is written to the real output folder:

    python -m pytest tests -q
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Every report file goes to a throw-away folder: a test must never overwrite a
# real report. Set before anything imports config.
os.environ["INTVAL_OUTPUT_DIR"] = tempfile.mkdtemp(prefix="intval_test_")

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import hybrid_model as HM  # noqa: E402
from agents import forensics as FX  # noqa: E402
from agents import settings as S  # noqa: E402
from agents.base import Agent, Evidence, Finding, cited  # noqa: E402
from agents.blackboard import Blackboard  # noqa: E402
from agents.llm import LLMRouter, parse_json  # noqa: E402


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    S.load(ROOT / "agent_settings.yaml")
    S.data().setdefault("run", {})["state_dir"] = str(tmp_path / "intel")
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("AGENT_STATE_DIR", raising=False)
    yield
    S.load(ROOT / "agent_settings.yaml")


def base_company(**kw):
    b = {
        "sector": "Information Technology", "regime": "mature", "price": 500.0,
        "beta_adj": 1.0, "tax": 0.25, "shares": 1.0e8, "debt": 5.0e9, "cash": 2.0e9,
        "equity_book": 2.0e10, "fcff_norm": 3.0e9, "nopat": 3.5e9, "nopat_norm": 3.4e9,
        "ni_norm": 3.0e9, "roe_norm": 0.16, "g_base": 0.10, "market_cap": 5.0e10,
        "market_cap_cr": 5000.0, "de_ratio": 0.25, "pe_reg": 540.0, "ev_reg": 510.0,
        "graham": 380.0, "ml": None,
    }
    b.update(kw)
    return b


NEUTRAL = {"risks": {}, "tilts": {}, "quality": {}, "red_flags": [], "conf_parts": {}}


# ================================================================ settings
def test_settings_lookup_and_defaults():
    assert S.num("hybrid_model.growth.max", 0) == pytest.approx(0.20)
    assert S.get("hybrid_model.does.not.exist", 42) == 42
    assert S.match_sector("sector_exposure", "Information Technology Services")["inr"] == pytest.approx(0.8)
    assert S.match_sector("sector_exposure", "Something Else") == S.section("sector_exposure")["default"]


def test_broken_settings_file_falls_back(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("hybrid_model: [unclosed", encoding="utf-8")
    S.load(bad)
    assert S.num("hybrid_model.growth.max", 0.2) == pytest.approx(0.2)
    assert HM.evaluate(base_company(), NEUTRAL)["value"] > 0


# ================================================================ HYBRID MODEL
def test_premia_raise_cost_of_equity_and_lower_value():
    calm = HM.evaluate(base_company(), NEUTRAL)
    risky = HM.evaluate(base_company(), dict(NEUTRAL, risks={"governance": 1.0, "forensic": 1.0, "liquidity": 1.0}))
    assert risky["cost_of_equity"] > calm["cost_of_equity"]
    assert risky["value"] < calm["value"]


def test_total_premium_is_capped():
    sig = dict(NEUTRAL, risks={k: 1.0 for k in ("liquidity", "governance", "forensic", "macro",
                                                 "geopolitical", "earnings_volatility")})
    v = HM.evaluate(base_company(market_cap_cr=10, de_ratio=5), sig)
    cap = S.num("hybrid_model.max_total_premium", 0.08)
    assert v["cost_of_equity"] - v["cost_of_equity_capm"] == pytest.approx(cap)


def test_cost_of_equity_floor():
    v = HM.evaluate(base_company(beta_adj=0.1), NEUTRAL)
    assert v["cost_of_equity_capm"] == pytest.approx(S.num("hybrid_model.min_cost_of_equity", 0.10))


def test_growth_tilts_and_terminal_bounds():
    up = HM.evaluate(base_company(), dict(NEUTRAL, tilts={"industry_tailwind": 1, "earnings_momentum": 1}))
    down = HM.evaluate(base_company(), dict(NEUTRAL, tilts={"industry_tailwind": -1, "earnings_momentum": -1}))
    assert up["growth"] > down["growth"]
    assert up["value"] > down["value"]
    for v in (up, down):
        assert v["growth_terminal"] <= v["cost_of_equity"] - 0.02 + 1e-9


def test_all_six_lenses_report():
    v = HM.evaluate(base_company(), NEUTRAL)
    assert set(v["lenses"]) == set(HM.LENSES)
    assert sum(v["lens_weights"].values()) == pytest.approx(1.0)
    assert {"cash_flow", "earnings_power", "asset", "market"} <= set(v["lens_weights"])


def test_growth_gate_caps_unearned_growth():
    narrow = HM.evaluate(base_company(g_base=0.20), dict(NEUTRAL, quality={"moat": -0.5}))
    g = narrow["gate"]
    assert g is not None and g["after"] <= g["before"]
    assert 1 - narrow["lenses"]["earnings_power"] / narrow["lenses"]["cash_flow"] <= g["allowed"] + 1e-9
    wide = HM.evaluate(base_company(g_base=0.20), dict(NEUTRAL, quality={"moat": 1.0}))
    assert wide["gate"]["allowed"] > g["allowed"]


def test_quality_multiplier_clamped():
    v = HM.evaluate(base_company(), dict(NEUTRAL, quality={k: 1 for k in
                                                           ("moat", "earnings_quality", "financial_strength", "capital_allocation")}))
    lo, hi = S.get("hybrid_model.quality_bounds")
    assert lo <= v["quality_multiplier"] <= hi


def test_red_flags_haircut_and_avoid_label():
    v = HM.evaluate(base_company(), dict(NEUTRAL, red_flags=["a", "b", "c"]))
    assert v["governance_haircut"] == pytest.approx(min(3 * 0.05, 0.30))
    assert v["label"] == "Avoid - red flags"


def test_scenarios_band_and_probabilities():
    v = HM.evaluate(base_company(), dict(NEUTRAL, bull_conviction=0.8, bear_conviction=0.1))
    assert v["bear_value"] < v["base_value"] < v["bull_value"]
    assert sum(v["probabilities"].values()) == pytest.approx(1.0)
    assert v["probabilities"]["bull"] > v["probabilities"]["bear"]
    assert v["low"] < v["value"] < v["high"]
    assert 0 < v["confidence"] <= 100


def test_lender_uses_residual_income():
    v = HM.evaluate(base_company(regime="lender", fcff_norm=None, sector="Banking"), NEUTRAL)
    assert v["value"] and v["value"] > 0
    assert v["lenses"]["cash_flow"] is not None


def test_no_inputs_means_insufficient_evidence():
    v = HM.evaluate({"price": 100.0}, NEUTRAL)
    assert v["value"] is None
    assert v["label"] == "Insufficient evidence"


def test_labels_follow_price():
    cheap = HM.evaluate(base_company(price=100.0), NEUTRAL, {"labels.min_confidence_for_label": 0})
    dear = HM.evaluate(base_company(price=5000.0), NEUTRAL, {"labels.min_confidence_for_label": 0})
    assert cheap["label"] in ("Deep value", "Undervalued")
    assert dear["label"] == "Overvalued"


def test_overrides_change_one_evaluation_only():
    before = HM.evaluate(base_company(), NEUTRAL)["value"]
    tweaked = HM.evaluate(base_company(), NEUTRAL, {"equity_risk_premium": 0.09})["value"]
    after = HM.evaluate(base_company(), NEUTRAL)["value"]
    assert tweaked < before and after == pytest.approx(before)
    w = HM.evaluate(base_company(), NEUTRAL, {"lens_weights.mature.market": 0.0})
    assert "market" not in w["lens_weights"]


def test_sensitivity_and_schema():
    rows = HM.sensitivity(base_company(), NEUTRAL)
    assert rows and all(r["up"] is not None for r in rows)
    sch = HM.schema_with_values()
    paths = [p["path"] for g in sch for p in g["params"]]
    assert "growth.terminal" in paths and "lens_weights.lender.asset" in paths
    assert all(p["value"] is not None for g in sch for p in g["params"])


def test_signals_from_accounts_point_in_time():
    years = {
        2022: {"revenue": 100, "net_income": 10, "ocf": 12, "equity": 80, "ebit": 15, "total_debt": 10, "cash": 5, "shares": 10},
        2023: {"revenue": 120, "net_income": 13, "ocf": 15, "equity": 90, "ebit": 19, "total_debt": 10, "cash": 5, "shares": 10},
        2024: {"revenue": 10, "net_income": -50, "ocf": -40, "equity": 40, "ebit": -45, "total_debt": 90, "cash": 1, "shares": 30},
    }
    s23 = HM.signals_from_accounts(years, 2023)
    s24 = HM.signals_from_accounts(years, 2024)
    assert s23["quality"]["moat"] > s24["quality"]["moat"]


def test_valuation_report_has_hybrid_model_column():
    import config
    import mock_source
    import pipeline
    import ticker_resolver

    saved = (config.FY_START, config.FY_END, config.OFFLINE, config.ANALYSIS_ENABLED, config.ML_ENABLED, ticker_resolver.resolve)
    try:
        config.OFFLINE, config.ANALYSIS_ENABLED, config.ML_ENABLED = True, False, False
        ticker_resolver.resolve = mock_source.resolve
        pipeline.run(mock_source.COMPANIES)
        assert str(config.OUTPUT_DIR) != str(ROOT / "output")
        head = (config.OUTPUT_DIR / "Intrinsic_Value_Data.csv").read_text(encoding="utf-8-sig").splitlines()[0]
        assert "(HYBRID MODEL) Intrinsic Value" in head and "(Ensemble) Intrinsic Value" in head
        assert (config.OUTPUT_DIR / "Hybrid_Model_Detail.csv").exists()
        bases = json.loads((config.OUTPUT_DIR / "hybrid_model_bases.json").read_text(encoding="utf-8"))
        assert "MOCK CLEAN ALPHA" in bases
    finally:
        config.set_fy_range(saved[0], saved[1])
        config.OFFLINE, config.ANALYSIS_ENABLED, config.ML_ENABLED, ticker_resolver.resolve = saved[2:]



# ================================================================ forensics
CUR = {"revenue": 120, "cogs": 70, "gross_profit": 50, "sga": 12, "ebit": 20, "net_income": 14,
       "ocf": 18, "da": 4, "assets": 150, "cur_assets": 70, "cur_liab": 40, "receivables": 20,
       "ppe_net": 50, "total_liab": 60, "lt_debt": 20, "equity": 90, "retained_earnings": 60,
       "shares": 10, "interest_expense": 2}
PREV = {"revenue": 100, "cogs": 60, "gross_profit": 40, "sga": 11, "ebit": 15, "net_income": 10,
        "ocf": 12, "da": 3.5, "assets": 140, "cur_assets": 60, "cur_liab": 40, "receivables": 17,
        "ppe_net": 48, "total_liab": 62, "lt_debt": 22, "equity": 78, "retained_earnings": 50,
        "shares": 10}


def test_piotroski_healthy_company_scores_high():
    s, mx, tests = FX.piotroski(CUR, PREV)
    assert mx == 9 and s >= 7


def test_altman_and_beneish_on_healthy_company():
    z, zone, n = FX.altman_z_em(CUR)
    assert zone == "safe" and n == 4
    m, n, _ = FX.beneish_m(CUR, PREV)
    assert n == 8 and m < FX.BENEISH_THRESHOLD


def test_beneish_flags_receivable_and_accrual_blowout():
    bad = dict(CUR, receivables=60, ocf=2, net_income=20)
    m, _, _ = FX.beneish_m(bad, PREV)
    assert m > FX.BENEISH_THRESHOLD


def test_forensics_survive_missing_fields():
    assert FX.piotroski({}, {})[1] == 0
    assert FX.altman_z_em({}) == (None, None, 0)
    assert FX.beneish_m({}, {})[0] is None
    assert FX.cash_conversion([{}]) is None


# ================================================================ evidence / LLM
def test_cited_drops_claims_without_real_evidence():
    ev = [Evidence(source="x", title="t1"), Evidence(source="y", title="t2")]
    claims = [{"text": "ok", "evidence": [ev[0].id]}, {"text": "made up", "evidence": ["E00000000"]}, "junk"]
    kept, dropped = cited(claims, ev)
    assert [c["text"] for c in kept] == ["ok"] and dropped == 2


def test_parse_json_handles_fences_and_prose():
    assert parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('result: [1, 2]') == [1, 2]
    assert parse_json("no json here") is None


def test_router_without_keys_is_off(tmp_path):
    r = LLMRouter(Blackboard(tmp_path / "b.sqlite"))
    assert not r.enabled
    assert r.complete("fast", "s", "u") is None


def test_router_falls_through_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_API_KEY", "k2")
    calls = []

    def fake_post(self, p, model, messages, max_tokens, json_mode):
        calls.append(model)
        if "groq" in p["base_url"]:
            return None, 0, 503
        return '{"ok": true}', 10, 200

    monkeypatch.setattr(LLMRouter, "_post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    board = Blackboard(tmp_path / "b.sqlite")
    r = LLMRouter(board)
    assert r.complete("fast", "sys", "user") == {"ok": True}
    n = len(calls)
    assert r.complete("fast", "sys", "user") == {"ok": True}
    assert len(calls) == n and r.cache_hits == 1
    assert board.usage_today("gemini")[0] == 1


def test_router_disables_provider_on_bad_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "bad")
    monkeypatch.setattr(LLMRouter, "_post", lambda *a, **k: (None, 0, 401))
    r = LLMRouter(Blackboard(tmp_path / "b.sqlite"))
    assert r.complete("fast", "s", "u") is None
    assert "groq" in r._dead


def test_agent_crash_becomes_error_finding():
    class Boom(Agent):
        KEY = "boom"

        def analyse(self, ctx, f):
            raise ValueError("kaput")

    class Ctx:
        name = "X"

    f = Boom().run(Ctx())
    assert f.status == "error" and "kaput" in f.summary


def test_finding_roundtrip():
    f = Finding(agent="a", lead="l", company="c", score=0.5, evidence=[Evidence(source="s", title="t")])
    g = Finding.from_dict(json.loads(json.dumps(f.to_dict())))
    assert g.evidence[0].id == f.evidence[0].id and g.score == 0.5


# ================================================================ full run
def test_full_offline_run_then_quick_run():
    import config
    import mock_source
    from agents.runner import run_agents

    saved = (config.FY_START, config.FY_END, config.OFFLINE)
    try:
        out = run_agents(mock_source.COMPANIES, offline=True, use_llm=False)
        vs = out["verdicts"]
        assert len(vs) == len(mock_source.COMPANIES)
        clean = next(v for v in vs if v["company"] == "MOCK CLEAN ALPHA")
        assert clean["model"] == "HYBRID MODEL"
        assert clean["expected_value"] and clean["expected_value"] > 0
        assert set(clean["lenses"]) == set(HM.LENSES)
        assert clean["signals"]["quality"]
        assert len(clean["analysts"]) == 17
        assert {r["lead"] for r in clean["leads"]} == {
            "market_news_lead", "equity_research_lead", "industry_geo_lead",
            "market_activity_lead", "review_lead",
        }
        for p in out["paths"]:
            assert Path(p).exists()

        quick = run_agents(mock_source.COMPANIES, offline=True, use_llm=False, quick=True)
        qc = next(v for v in quick["verdicts"] if v["company"] == "MOCK CLEAN ALPHA")
        reused = [a for a in qc["analysts"] if any("re-used" in n for n in a["notes"])]
        assert len(reused) == 5
        # the second run knows about the first, so it is not "first" any more
        assert not any(c.startswith("first") for c in qc["changes"])
        assert len(qc["history"]) == 2
    finally:
        config.set_fy_range(saved[0], saved[1])
        config.OFFLINE = saved[2]
