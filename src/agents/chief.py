"""
The five research leads and the Chief Market Intelligence Officer.

LEADS combine their analysts into one section score: a weighted mean of
score x confidence, using the weights in agent_settings.yaml -> agents.
Only validated findings count once validation has run.

THE CHIEF turns the team's findings into the formula's inputs, by name:

    risks     liquidity        <- Market Volume: liquidity_risk
              governance       <- max(Insider, Fund Holdings governance_risk,
                                      Credibility pump_risk)
              forensic         <- Forensics: forensic_risk
              macro            <- Geopolitical: macro_risk
              geopolitical     <- Geopolitical: geopolitical_risk
              earnings_volatility <- Fundamental: earnings_volatility_risk
    tilts     industry_tailwind <- Industry: industry_tailwind
              earnings_momentum <- mean(Fundamental, Pre-earnings momentum)
              news_impact       <- Market Impact: news_impact
              macro_growth      <- Geopolitical: macro_growth
    quality   moat, capital_allocation <- Fundamental
              earnings_quality, financial_strength <- Forensics
    red flags every validated analyst's flags, de-duplicated
    scenario  Bull / Bear conviction
    overlay   mean(sentiment, relative strength, accumulation, holdings)

then runs the HYBRID MODEL (src/hybrid_model.py) and writes the verdict, with an LLM-written
executive summary that may cite only validated evidence (template fallback).
"""

import statistics

import hybrid_model as HM
from agents import settings as S
from agents.base import cited, clamp, weighted_mean

LEAD_NAMES = {
    "market_news_lead": "Market News Research Lead",
    "equity_research_lead": "Equity Research Lead",
    "industry_geo_lead": "Head of Industry & Geopolitical Research",
    "market_activity_lead": "Head of Market Activity & Ownership Research",
    "review_lead": "Independent Research Review Lead",
}


def analyst_weight(lead, agent):
    w = S.section(f"agents.{lead}").get(agent)
    try:
        return float(w) if w is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


def lead_report(ctx, lead):
    rows = [f for f in ctx.findings.values() if f.lead == lead]
    use = [f for f in rows if f.status == "ok" and f.validated is not False]
    pairs = [(f.score, analyst_weight(lead, f.agent) * f.confidence) for f in use]
    score = weighted_mean(pairs)
    conf = statistics.mean(f.confidence for f in use) if use else 0.0
    best = sorted(use, key=lambda f: -abs(f.score) * f.confidence)[:2]
    summary = " ".join(f.summary for f in best) if best else "No usable findings."
    rep = {
        "lead": lead,
        "name": LEAD_NAMES.get(lead, lead),
        "score": score if score is not None else 0.0,
        "confidence": conf,
        "analysts": len(rows),
        "usable": len(use),
        "summary": summary,
    }
    ctx.leads[lead] = rep
    return rep


def _sig(ctx, key, name, default=0.0):
    fd = ctx.findings.get(key)
    if fd is None or fd.status != "ok" or fd.validated is False:
        return default
    v = fd.signals.get(name)
    return default if v is None else v


def build_signals(ctx):
    gov = max(
        _sig(ctx, "insider_activity_analyst", "governance_risk", 0.0),
        _sig(ctx, "fund_holdings_analyst", "governance_risk", 0.0),
        _sig(ctx, "news_credibility_analyst", "pump_risk", 0.0),
        _sig(ctx, "short_seller_analyst", "short_risk", 0.0),
    )
    momentum = [
        v for v in (
            _sig(ctx, "fundamental_research_analyst", "earnings_momentum", None),
            _sig(ctx, "pre_earnings_analyst", "earnings_momentum", None),
        ) if v is not None
    ]
    flags = []
    seen = set()
    for fd in ctx.findings.values():
        if fd.validated is False or fd.status != "ok":
            continue
        for fl in fd.flags:
            k = fl.split("(")[0].strip().lower()[:60]
            if k not in seen:
                seen.add(k)
                flags.append(f"{fl} - {fd.agent.replace('_', ' ')}")

    rel = (_sig(ctx, "stock_movement_analyst", "relative_to_nifty", {}) or {}).get("3m")
    overlay_parts = [
        _sig(ctx, "sentiment_analyst", "sentiment", None),
        clamp(rel / 0.2, -1, 1) if rel is not None else None,
        _sig(ctx, "market_volume_analyst", "accumulation", None),
        ctx.findings["fund_holdings_analyst"].score if "fund_holdings_analyst" in ctx.findings else None,
    ]
    overlay_parts = [v for v in overlay_parts if v is not None]

    val = ctx.findings.get("research_validation_analyst")
    lead_scores = [r["score"] for k, r in ctx.leads.items() if k != "review_lead" and r["usable"]]
    if lead_scores:
        pos = sum(1 for s in lead_scores if s > 0.05)
        neg = sum(1 for s in lead_scores if s < -0.05)
        agreement = max(pos, neg, len(lead_scores) - pos - neg) / len(lead_scores)
    else:
        agreement = 0.0

    return {
        "risks": {
            "liquidity": _sig(ctx, "market_volume_analyst", "liquidity_risk", 0.3),
            "governance": gov,
            "forensic": _sig(ctx, "financial_forensics_analyst", "forensic_risk", 0.2),
            "macro": _sig(ctx, "geopolitical_risk_analyst", "macro_risk", 0.2),
            "geopolitical": _sig(ctx, "geopolitical_risk_analyst", "geopolitical_risk", 0.2),
            "earnings_volatility": _sig(ctx, "fundamental_research_analyst", "earnings_volatility_risk", 0.3),
        },
        "tilts": {
            "industry_tailwind": _sig(ctx, "industry_research_analyst", "industry_tailwind", 0.0),
            "earnings_momentum": statistics.mean(momentum) if momentum else 0.0,
            "news_impact": _sig(ctx, "market_impact_analyst", "news_impact", 0.0),
            "macro_growth": _sig(ctx, "geopolitical_risk_analyst", "macro_growth", 0.0),
        },
        "quality": {
            "moat": _sig(ctx, "fundamental_research_analyst", "moat", 0.0),
            "earnings_quality": _sig(ctx, "financial_forensics_analyst", "earnings_quality", 0.0),
            "financial_strength": _sig(ctx, "financial_forensics_analyst", "financial_strength", 0.0),
            "capital_allocation": _sig(ctx, "fundamental_research_analyst", "capital_allocation", 0.0),
        },
        "red_flags": flags,
        "bull_conviction": _sig(ctx, "bull_case_analyst", "conviction", 0.0),
        "bear_conviction": _sig(ctx, "bear_case_analyst", "conviction", 0.0),
        "overlay": statistics.mean(overlay_parts) if overlay_parts else 0.0,
        "conf_parts": {
            "evidence_coverage": val.signals.get("coverage", 0.0) if val else 0.0,
            "validation": val.signals.get("pass_rate", 0.0) if val else 0.0,
            "agreement": agreement,
        },
    }


def research_score(ctx):
    w = S.section("agents.chief")
    pairs = []
    for lead, rep in ctx.leads.items():
        try:
            pairs.append((rep["score"], float(w.get(lead, 0.2)) * max(rep["confidence"], 0.05)))
        except (TypeError, ValueError):
            continue
    return weighted_mean(pairs) or 0.0


def _fmt(v):
    return f"{v:,.2f}" if isinstance(v, (int, float)) else "n/a"


def executive_summary(ctx, verdict, llm_ask):
    """LLM summary citing validated evidence; template when no LLM answers."""
    evidence = [e for fd in ctx.findings.values() if fd.validated for e in fd.evidence[:3]]
    lines = "\n".join(
        f"- {rep['name']}: score {rep['score']:+.2f}. {rep['summary'][:300]}" for rep in ctx.leads.values()
    )
    ev_lines = "\n".join(f"[{e.id}] {e.source}: {e.title[:120]}" for e in evidence[:30])
    reply = llm_ask(
        "smart",
        "You are the Chief Market Intelligence Officer of an Indian equity research "
        "team. Write a plain-English research note for a private investor: what the "
        "business is worth against its price, the 2-3 facts that matter most, the main "
        "risk, and what to watch next. Use ONLY the numbers and findings given. Do not "
        "recommend buying or selling; describe. Cite evidence ids on every key point. "
        '{"headline":str,"note":str,"key_points":[{"text":str,"evidence":[id]}],"watch_next":[str]}',
        f"Company: {ctx.name} ({ctx.sector})\n"
        f"Price {_fmt(verdict['price'])}; HYBRID MODEL value {_fmt(verdict['expected_value'])} "
        f"(bear {_fmt(verdict['bear_value'])}, bull {_fmt(verdict['bull_value'])}); "
        f"label {verdict['label']}; confidence {verdict['confidence']:.0f}/100; "
        f"red flags: {verdict['red_flags'] or 'none'}\n"
        f"Lead reports:\n{lines}\nEvidence:\n{ev_lines}",
        max_tokens=900,
    )
    if isinstance(reply, dict) and reply.get("note"):
        points, dropped = cited(reply.get("key_points"), evidence)
        return {
            "headline": str(reply.get("headline", ""))[:200],
            "note": str(reply["note"])[:2000],
            "key_points": points,
            "watch_next": [str(x)[:200] for x in (reply.get("watch_next") or [])][:5],
            "by": "llm",
            "uncited_dropped": dropped,
        }
    up = verdict.get("upside")
    head = f"{ctx.name}: {verdict['label']}" + (f", {up:+.0%} to the HYBRID MODEL value" if up is not None else "")
    best = sorted(ctx.leads.values(), key=lambda r: -abs(r["score"]) * r["confidence"])
    note = " ".join(f"{r['name']}: {r['summary']}" for r in best[:3])
    watch = []
    pe = ctx.findings.get("pre_earnings_analyst")
    if pe and pe.signals.get("next_results"):
        watch.append(f"results on {pe.signals['next_results']}")
    if verdict["red_flags"]:
        watch.append("resolution of the red flags listed")
    return {"headline": head, "note": note, "key_points": [], "watch_next": watch, "by": "template"}


def decide(ctx, llm_ask):
    """Run the HYBRID MODEL and assemble the verdict for one company."""
    agent_sig = build_signals(ctx)
    sig = HM.merge_signals(getattr(ctx, "account_signals", None) or HM.NEUTRAL, agent_sig)
    res = HM.evaluate(ctx.base, sig)
    verdict = dict(res)
    verdict.update({
        "model": "HYBRID MODEL",
        "expected_value": res["value"],
        "company": ctx.name,
        "ticker": ctx.ticker,
        "sector": ctx.sector,
        "valuation_fy": ctx.base.get("fy"),
        "research_score": research_score(ctx),
        "leads": list(ctx.leads.values()),
        "red_flags": sig["red_flags"],
        "risks": sig.get("risks", {}),
        "tilts": sig.get("tilts", {}),
        "quality": sig.get("quality", {}),
        "overlay": sig.get("overlay", 0.0),
        "signals": sig,
        "bull_case": (ctx.findings.get("bull_case_analyst").signals.get("case")
                      if ctx.findings.get("bull_case_analyst") else None),
        "bear_case": (ctx.findings.get("bear_case_analyst").signals.get("case")
                      if ctx.findings.get("bear_case_analyst") else None),
        "analysts": [
            {"agent": f.agent, "lead": f.lead, "score": f.score, "confidence": f.confidence,
             "status": f.status, "validated": f.validated, "summary": f.summary,
             "used_llm": f.used_llm, "flags": f.flags, "notes": f.notes[:5],
             "evidence": [{"id": e.id, "source": e.source, "title": e.title, "url": e.url, "date": e.date}
                          for e in f.evidence[:6]]}
            for f in ctx.findings.values()
        ],
    })
    verdict["summary"] = executive_summary(ctx, verdict, llm_ask)
    return verdict
