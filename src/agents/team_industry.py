# FILE: src/agents/team_industry.py
"""
Head of Industry & Geopolitical Research's team.

    Industry Research Analyst    sector index vs Nifty, the company against its
                                 peers in this run, sector news outlook
    Geopolitical Risk Analyst    live macro (VIX, INR, crude, US yields) and
                                 your hand-set macro constants, weighted by
                                 how exposed the sector is, plus geopolitical
                                 headlines

The macro snapshot and the geopolitical news read are the same for every
company, so they are computed once per run and kept in ctx.shared.
"""

import math
import statistics
import threading

from agents import settings as S
from agents.base import Agent, Evidence, clamp, weighted_mean
from agents.team_news import _ev_lines, credibility_of, lexicon_score

LEAD = "industry_geo_lead"
_once = threading.Lock()

GEO_WORDS = [
    "war", "sanction", "tariff", "conflict", "border", "attack", "embargo", "missile",
    "tension", "escalat", "terror", "blockade", "trade war", "export ban", "strait",
]


def _ret(px, n):
    if len(px) <= n:
        return None
    return px[-1]["close"] / px[-1 - n]["close"] - 1


# ===================================================================== 9
class IndustryResearchAnalyst(Agent):
    KEY = "industry_research_analyst"
    NAME = "Industry Research Analyst"
    LEAD = LEAD
    ROLE = "Sector cycle, the company against its peers, sector outlook."
    USES_LLM = True

    def analyse(self, ctx, f):
        idx = S.match_sector("sector_index", ctx.sector) or "^NSEI"
        sec_px = ctx.feeds.prices(idx, 400)
        nifty = ctx.shared.get("nifty_prices") or []
        parts = []
        rel6 = rel12 = None
        if sec_px:
            f.evidence.append(Evidence(source="Yahoo Finance index", title=f"Sector index {idx}",
                                       url=f"https://finance.yahoo.com/quote/{idx}", date=sec_px[-1]["date"],
                                       value=sec_px[-1]["close"], kind="data"))
            if idx != "^NSEI" and nifty:
                a6, b6 = _ret(sec_px, 126), _ret(nifty, 126)
                a12, b12 = _ret(sec_px, 250), _ret(nifty, 250)
                rel6 = a6 - b6 if a6 is not None and b6 is not None else None
                rel12 = a12 - b12 if a12 is not None and b12 is not None else None
                if rel6 is not None:
                    parts.append(("index", math.tanh(rel6 / 0.10), 0.4))

        # the company against the other companies of its sector in this run
        peers = [b for n, b in ctx.shared.get("bases", {}).items()
                 if n != ctx.name and b.get("sector") == ctx.sector]
        g_me = ctx.base.get("g_base")
        if peers and g_me is not None:
            pg = [p.get("g_base") for p in peers if p.get("g_base") is not None]
            if pg:
                rel_g = g_me - statistics.median(pg)
                parts.append(("peers", math.tanh(rel_g / 0.05) * 0.5, 0.2))
                f.signals["growth_vs_peers"] = rel_g
                f.evidence.append(Evidence(source="Run peer set", title=f"{len(pg)} {ctx.sector} peers' base growth",
                                           date=ctx.shared.get("as_of", ""), kind="derived"))

        # sector outlook from sector news
        news = ctx.feeds.news(f"{ctx.sector} sector India outlook", limit=15)
        ev = []
        for n in news:
            tier, w = credibility_of(n.get("domain"), n.get("source"))
            ev.append(Evidence(source=n.get("source") or "news", title=n["title"], url=n.get("url", ""),
                               date=n.get("date", ""), kind="news", credibility=w))
        f.evidence.extend(ev)
        outlook = None
        if ev:
            reply = self.ask_llm(
                "smart",
                "You are a sector analyst for Indian equities. From these recent "
                "headlines, judge the sector's business outlook over the next 1-3 "
                "years: -1 deteriorating, 0 stable, 1 improving. Give up to three "
                "drivers, each citing item ids. "
                'Schema: {"outlook":number,"drivers":[{"text":str,"evidence":[id]}]}',
                f"Sector: {ctx.sector}\nHeadlines:\n{_ev_lines(ev, 15)}",
                max_tokens=500,
            )
            if isinstance(reply, dict) and reply.get("outlook") is not None:
                try:
                    outlook = clamp(float(reply["outlook"]), -1, 1)
                    f.used_llm = True
                    from agents.base import cited

                    f.signals["drivers"], _ = cited(reply.get("drivers"), ev)
                except (TypeError, ValueError):
                    outlook = None
            if outlook is None:
                outlook = weighted_mean([(lexicon_score(e.title), e.credibility) for e in ev]) or 0.0
                f.notes.append("lexicon fallback used for sector outlook")
            parts.append(("outlook", outlook, 0.4))

        if not parts:
            f.summary = "No sector index, peers or sector news available."
            return
        tailwind = weighted_mean([(v, w) for _, v, w in parts]) or 0.0
        f.signals.update({
            "sector_index": idx, "sector_rel_6m": rel6, "sector_rel_12m": rel12,
            "sector_outlook": outlook, "industry_tailwind": tailwind,
        })
        f.score = tailwind
        f.confidence = min(1.0, 0.25 * len(parts) + (0.15 if f.used_llm else 0))
        f.summary = (
            f"Sector tailwind {tailwind:+.2f}"
            + (f"; {idx} vs Nifty 6m {rel6:+.1%}" if rel6 is not None else "")
            + (f"; outlook {outlook:+.2f}" if outlook is not None else "")
            + (f"; growth vs peers {f.signals['growth_vs_peers']:+.1%}" if "growth_vs_peers" in f.signals else "")
            + "."
        )


# ==================================================================== 10
def macro_read(feeds):
    """Run-wide macro risk and growth tilt from live data + settings."""
    snap = feeds.macro()
    m = {}
    vix = (snap.get("india_vix") or {}).get("last")
    if vix:
        m["vix"] = clamp((vix - S.num("macro.normal_india_vix", 15)) / 15, -0.5, 1)
    inr = (snap.get("usd_inr") or {}).get("chg_1y")
    if inr is not None:
        m["inr"] = clamp((inr - S.num("macro.inr_depreciation_tolerance_1y", 0.04)) / 0.08, -0.5, 1)
    brent = (snap.get("brent") or {}).get("last")
    if brent:
        m["crude"] = clamp((brent - S.num("macro.normal_brent_usd", 75)) / 40, -0.5, 1)
    us10 = snap.get("us_10y") or {}
    if us10.get("chg_1y") is not None:
        m["us_rates"] = clamp(us10["chg_1y"] / 0.25, -0.5, 1)
    infl_gap = S.num("macro.cpi_inflation", 0.04) - S.num("macro.rbi_inflation_target", 0.04)
    m["inflation"] = clamp(infl_gap / 0.03, -0.5, 1)
    real_rate = S.num("macro.repo_rate", 0.055) - S.num("macro.cpi_inflation", 0.04)
    m["policy"] = clamp((real_rate - 0.015) / 0.02, -0.5, 1)
    gdp = S.num("macro.real_gdp_growth", 0.065)
    growth_tilt = clamp((gdp - 0.06) / 0.02, -1, 1) - 0.5 * max(0.0, m["inflation"])
    return snap, m, clamp(growth_tilt, -1, 1)


class GeopoliticalRiskAnalyst(Agent):
    KEY = "geopolitical_risk_analyst"
    NAME = "Geopolitical Risk Analyst"
    LEAD = LEAD
    ROLE = "Macro and geopolitical shocks, weighted by the sector's exposure."
    USES_LLM = True

    def _run_wide(self, ctx):
        with _once:
            if "macro" in ctx.shared:
                return ctx.shared["macro"]
            snap, comps, growth_tilt = macro_read(ctx.feeds)
            news = ctx.feeds.news("India economy geopolitical risk tariffs sanctions markets", limit=20)
            ev = []
            for n in news:
                _, w = credibility_of(n.get("domain"), n.get("source"))
                ev.append(Evidence(source=n.get("source") or "news", title=n["title"], url=n.get("url", ""),
                                   date=n.get("date", ""), kind="news", credibility=w))
            geo = {}
            reply = None
            if ev:
                reply = self.ask_llm(
                    "smart",
                    "You are a geopolitical risk analyst for Indian equity markets. "
                    "From these headlines rate current intensity 0 (calm) to 1 (severe) "
                    "for each channel: crude, inr, us_rates, china, geopolitics, "
                    "regulation. Add up to three key risks citing item ids. "
                    'Schema: {"channels":{"crude":n,"inr":n,"us_rates":n,"china":n,'
                    '"geopolitics":n,"regulation":n},"risks":[{"text":str,"evidence":[id]}]}',
                    f"Headlines:\n{_ev_lines(ev, 20)}",
                    max_tokens=500,
                )
            used = False
            if isinstance(reply, dict) and isinstance(reply.get("channels"), dict):
                for k, v in reply["channels"].items():
                    try:
                        geo[k] = clamp(float(v), 0, 1)
                        used = True
                    except (TypeError, ValueError):
                        pass
            if not geo:
                hits = sum(e.credibility for e in ev if any(w in e.title.lower() for w in GEO_WORDS))
                geo["geopolitics"] = clamp(hits / 6, 0, 1)
            from agents.base import cited

            risks = cited(reply.get("risks"), ev)[0] if isinstance(reply, dict) else []
            out = {"snapshot": snap, "components": comps, "growth_tilt": growth_tilt,
                   "geo": geo, "risks": risks, "evidence": ev, "used_llm": used}
            ctx.shared["macro"] = out
            return out

    def analyse(self, ctx, f):
        m = self._run_wide(ctx)
        f.used_llm = m["used_llm"]
        exp = S.match_sector("sector_exposure", ctx.sector) or {}
        comps = m["components"]

        # macro risk: each live reading x how much this sector cares about it
        channels = {"crude": comps.get("crude"), "inr": comps.get("inr"), "us_rates": comps.get("us_rates")}
        pairs = [(max(0.0, v), float(exp.get(k, 0.3))) for k, v in channels.items() if v is not None]
        pairs.append((max(0.0, comps.get("vix", 0.0)), 0.5))
        pairs.append((max(0.0, comps.get("inflation", 0.0)), 0.3))
        pairs.append((max(0.0, comps.get("policy", 0.0)), 0.3))
        macro_risk = clamp(sum(v * w for v, w in pairs) / max(1e-9, sum(w for _, w in pairs)) * 1.5, 0, 1)

        geo = m["geo"]
        gpairs = [(geo.get(k, 0.0), float(exp.get(k, 0.3))) for k in ("geopolitics", "china", "regulation", "crude")]
        geo_risk = clamp(sum(v * w for v, w in gpairs) / max(1e-9, sum(w for _, w in gpairs)) * 1.3, 0, 1)

        for name, s in (m["snapshot"] or {}).items():
            f.evidence.append(Evidence(source="Yahoo Finance macro", title=f"{name} ({s['ticker']}) = {s['last']:.2f}",
                                       url=f"https://finance.yahoo.com/quote/{s['ticker']}", date=s["date"],
                                       value=s["last"], kind="macro"))
        f.evidence.append(Evidence(source="agent_settings.yaml macro constants",
                                   title=f"repo {S.num('macro.repo_rate', 0):.2%}, CPI {S.num('macro.cpi_inflation', 0):.2%}, "
                                         f"GDP {S.num('macro.real_gdp_growth', 0):.2%}",
                                   date=ctx.shared.get("as_of", ""), kind="macro"))
        f.evidence.extend(m["evidence"][:10])
        f.signals.update({
            "macro_risk": macro_risk, "geopolitical_risk": geo_risk,
            "macro_growth": m["growth_tilt"], "exposure": exp,
            "macro_components": comps, "geo_channels": geo, "key_risks": m["risks"],
        })
        f.score = clamp(0.5 * m["growth_tilt"] - 0.6 * macro_risk - 0.6 * geo_risk + 0.3, -1, 1)
        f.confidence = 0.4 + 0.2 * bool(m["snapshot"]) + 0.2 * f.used_llm
        f.summary = (
            f"Macro risk {macro_risk:.2f}, geopolitical risk {geo_risk:.2f} for a {ctx.sector or 'this'} "
            f"business; macro growth tilt {m['growth_tilt']:+.2f}."
        )


TEAM = [IndustryResearchAnalyst, GeopoliticalRiskAnalyst]
