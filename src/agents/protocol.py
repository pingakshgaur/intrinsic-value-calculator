"""
The research protocol: who tells whom what, and when, for one company.

Every message here is a real exchange in the code, written from data that
already exists - a finding, a score, a validation result. Nothing calls an
API or an LLM. Cross-team messages follow the actual data dependencies
(comms.CONSUMES), and the review team only messages analysts on exceptions,
so the traffic stays proportional to what actually needs saying.
"""

import statistics

from agents import comms
from agents.comms import (
    BY_KEY,
    ROSTER,
    TEAMS,
    dm,
    finding_data,
    finding_text,
    summary_text,
    verdict_text,
)


def _ch(cs):
    return TEAMS[ROSTER[cs]["team"]]["channel"]


def open_company(bus, ctx):
    b = ctx.base or {}
    bus.post("CMD-00", "command",
             f"Opening coverage on {ctx.name} ({ctx.sector or 'sector n/a'}). Price {comms._money(b.get('price'))}; "
             f"HYBRID MODEL inputs from FY{b.get('fy', '?')} are on the blackboard. Leads, over to your teams.",
             kind="task", company=ctx.name, data={"ticker": ctx.ticker, "price": b.get("price"), "fy": b.get("fy")})


def assign(bus, lead_key, keys, ctx, quick_reuse=()):
    lead = BY_KEY[lead_key]
    team = [BY_KEY[k] for k in keys if k in BY_KEY]
    fresh = [cs for cs in team if ROSTER[cs]["key"] not in quick_reuse]
    reused = [cs for cs in team if ROSTER[cs]["key"] in quick_reuse]
    text = f"Picking up {ctx.name}. " + " ".join(f"@{cs}" for cs in fresh) + " - you're up."
    if reused:
        text += " Quick sweep: " + ", ".join(f"@{cs}" for cs in reused) + " reuse the last full run's work."
    bus.post(lead, _ch(lead), text, kind="task", company=ctx.name, data={"members": team})


def analyst_done(bus, cs, f, ctx, reused=False):
    """File the finding with the team; raise red flags; -> message id."""
    text = ("(re-used from the last full run) " if reused else "") + finding_text(f)
    if f.used_llm:
        text += " [LLM-assisted]"
    mid = bus.post(cs, _ch(cs), text, kind="finding", company=ctx.name, data=finding_data(f))
    for fl in f.flags[:4]:
        bus.post(cs, _ch(cs), f"Red flag on {ctx.name}: {fl[:240]}", kind="flag", company=ctx.name,
                 data={"flag": fl}, refs=[mid])
    return mid


def _sig(ctx, key, name):
    f = ctx.findings.get(key)
    return None if f is None or f.status != "ok" else f.signals.get(name)


def consult(bus, cs, ctx):
    """Requests an analyst makes before it works: it reads other agents' output."""
    name = ctx.name
    if cs == "MAO-04":
        acc, liq = _sig(ctx, "market_volume_analyst", "accumulation"), _sig(ctx, "market_volume_analyst", "liquidity_risk")
        rel_all = _sig(ctx, "stock_movement_analyst", "relative_to_nifty")
        rel = rel_all.get("3m") if isinstance(rel_all, dict) else None
        q = bus.post(cs, dm(cs, "MAO-01"), f"@MAO-01 checking {name} for distress: what does the tape say on accumulation and liquidity?",
                     kind="request", company=name, to="MAO-01")
        bus.post("MAO-01", dm(cs, "MAO-01"),
                 f"@{cs} {name}: accumulation {acc:+.2f}, liquidity risk {liq:.2f}." if isinstance(acc, (int, float)) and isinstance(liq, (int, float))
                 else f"@{cs} no reliable volume read on {name}.", kind="reply", company=name, to=cs,
                 data={"accumulation": acc, "liquidity_risk": liq}, refs=[q])
        q = bus.post(cs, dm(cs, "NWS-04"), f"@NWS-04 cross-team ask: how has {name} done against the Nifty over 3 months?",
                     kind="request", company=name, to="NWS-04")
        bus.post("NWS-04", dm(cs, "NWS-04"),
                 f"@{cs} {name} is {rel:+.1%} relative to the Nifty over 3 months." if isinstance(rel, (int, float))
                 else f"@{cs} not enough price history on {name} for a 3-month comparison.",
                 kind="reply", company=name, to=cs, data={"relative_3m": rel}, refs=[q])


def exchanges(bus, cs, ctx):
    """Cross-agent messages that follow this analyst's work."""
    name = ctx.name
    if cs == "NWS-02":
        w = (ctx.shared.get("cred_weights") or {}).get(name) or {}
        if w:
            low = sum(1 for v in w.values() if isinstance(v, (int, float)) and v < 0.6)
            bus.post(cs, "nws", f"@NWS-03 @NWS-05 credibility weights for {len(w)} {name} items are on the blackboard"
                     + (f"; {low} low-credibility source(s) down-weighted." if low else "."),
                     kind="reply", company=name, data={"weighted": len(w), "low": low})
    elif cs == "EQR-02":
        f = ctx.findings.get("financial_forensics_analyst")
        if f and f.flags:
            bus.post(cs, dm(cs, "IRV-03"), f"@IRV-03 for your {name} bear case: {f.flags[0][:220]}",
                     kind="request", company=name, to="IRV-03", data={"flags": f.flags[:3]})
    elif cs == "EQR-03":
        a, b = _sig(ctx, "fundamental_research_analyst", "earnings_momentum"), _sig(ctx, "pre_earnings_analyst", "earnings_momentum")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a * b < 0 and abs(a - b) > 0.3:
            bus.post(cs, "eqr", f"@EQR-01 we disagree on {name}'s earnings momentum: your yearly read {a:+.2f}, "
                     f"my quarterly read {b:+.2f}. The chief averages the two; flagging so @EQR-00 sees it.",
                     kind="request", company=name, to="EQR-01", data={"yearly": a, "quarterly": b})


def review(bus, ctx):
    """Validation talks only to the analysts whose work failed (exceptions only)."""
    v = ctx.findings.get("research_validation_analyst")
    if not v:
        return
    failed = [fd for fd in ctx.findings.values() if fd.validated is False and fd.lead != "review_lead"]
    for fd in failed[:8]:
        cs = BY_KEY.get(fd.agent)
        if not cs:
            continue
        why = ("it didn't complete" if fd.status == "error" else "it found no usable data" if fd.status == "no_data"
               else f"none of its {len(fd.evidence)} evidence item(s) passed the source and age rules")
        q = bus.post("IRV-01", dm("IRV-01", cs), f"@{cs} your {ctx.name} finding is excluded from the team score: {why}.",
                     kind="review", company=ctx.name, to=cs, data={"status": fd.status, "evidence": len(fd.evidence)})
        bus.post(cs, dm("IRV-01", cs), f"@IRV-01 understood - {ctx.name} stays out of my team's score this run.",
                 kind="reply", company=ctx.name, to="IRV-01", refs=[q])
    s = v.signals
    bus.post("IRV-01", "irv", f"{ctx.name}: {s.get('passed', 0)}/{s.get('checked', 0)} findings passed validation"
             + (f"; {len(failed)} excluded." if failed else ".")
             + (f" Note: {s['problems'][-1][:160]}" if s.get("problems") and "price mismatch" in s["problems"][-1] else ""),
             kind="review", company=ctx.name, data={"passed": s.get("passed"), "checked": s.get("checked"),
                                                    "pass_rate": s.get("pass_rate")})


def cases(bus, ctx):
    """Bull and bear ask the lead pushing hardest their way for the best evidence."""
    for cs, positive in (("IRV-02", True), ("IRV-03", False)):
        leads = [r for k, r in ctx.leads.items() if k != "review_lead" and r["usable"]]
        if not leads:
            continue
        r = max(leads, key=lambda r: r["score"] * (1 if positive else -1))
        if (r["score"] > 0.05) if positive else (r["score"] < -0.05):
            lead = BY_KEY[r["lead"]]
            q = bus.post(cs, dm(cs, lead), f"@{lead} building the {'bull' if positive else 'bear'} case on {ctx.name}: "
                         f"your team scored {r['score']:+.2f}. What's the strongest validated point?",
                         kind="request", company=ctx.name, to=lead)
            bus.post(lead, dm(cs, lead), f"@{cs} {r['summary'][:300]}", kind="reply", company=ctx.name, to=cs, refs=[q])


def team_reports(bus, ctx, finding_mids):
    """Each lead aggregates its analysts' findings into one report for the chief."""
    out = {}
    for lead_key, rep in ctx.leads.items():
        cs = BY_KEY.get(lead_key)
        if not cs:
            continue
        refs = [m for k, m in finding_mids.items() if ROSTER[BY_KEY[k]]["team"] == ROSTER[cs]["team"]]
        out[cs] = bus.post(cs, "command", summary_text(rep, ctx.name), kind="summary", company=ctx.name,
                           data={"score": rep["score"], "confidence": rep["confidence"], "usable": rep["usable"],
                                 "analysts": rep["analysts"]}, refs=refs)
    return out


def chief(bus, ctx, verdict, report_mids):
    scores = {BY_KEY[k]: r["score"] for k, r in ctx.leads.items() if k != "review_lead" and r["usable"] and k in BY_KEY}
    if len(scores) >= 3:
        mean = statistics.mean(scores.values())
        cs, s = max(scores.items(), key=lambda kv: abs(kv[1] - mean))
        if abs(s - mean) > 0.4:
            rep = next(r for k, r in ctx.leads.items() if BY_KEY.get(k) == cs)
            q = bus.post("CMD-00", dm("CMD-00", cs), f"@{cs} your {ctx.name} score {s:+.2f} is the outlier "
                         f"(teams average {mean:+.2f}). What's driving it?", kind="request", company=ctx.name, to=cs)
            bus.post(cs, dm("CMD-00", cs), f"@CMD-00 {rep['summary'][:300]}", kind="reply", company=ctx.name,
                     to="CMD-00", refs=[q])
    bus.post("CMD-00", "command", verdict_text(verdict), kind="verdict", company=ctx.name,
             data={"label": verdict.get("label"), "value": verdict.get("expected_value"), "price": verdict.get("price"),
                   "upside": verdict.get("upside"), "confidence": verdict.get("confidence"),
                   "buy_below": verdict.get("buy_below"), "flags": len(verdict.get("red_flags") or []),
                   "headline": (verdict.get("summary") or {}).get("headline")},
             refs=list(report_mids.values()))
