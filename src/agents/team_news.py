# FILE: src/agents/team_news.py
"""
Market News Research Lead's team.

    Research Analyst          gathers news + exchange filings, lists key
                              developments, raises red flags from filings
    News Credibility Analyst  weights every source by tier, spots promotion
    Sentiment Analyst         credibility-weighted tone of the coverage
    Stock Movement Analyst    what the price did, against the Nifty
    Market Impact Analyst     which stories actually move value, and how much

They run in that order: credibility weights have to exist before sentiment
and impact are averaged with them.
"""

import math
import re
import urllib.parse

from agents import settings as S
from agents.base import Agent, Evidence, cited, clamp, weighted_mean

LEAD = "market_news_lead"

RED_FLAG_PATTERNS = [
    (r"resign\w*.{0,40}auditor|auditor.{0,40}resign", "statutory auditor resigned"),
    (r"\b(cfo|chief financial officer)\b.{0,40}resign", "CFO resigned"),
    (r"forensic audit", "forensic audit under way"),
    (r"\bsebi\b.{0,60}(order|penalt|show.?cause|bars?|ban)", "SEBI action"),
    (r"\b(ed|enforcement directorate|income.?tax)\b.{0,30}(raid|search|summon)", "enforcement raid or search"),
    (r"\bnclt\b|insolvenc|\bdefault(ed|s)? on\b", "insolvency or debt default"),
    (r"\bfraud\b|siphon|diversion of funds", "fraud allegation"),
    (r"pledge.{0,20}invok", "pledged shares invoked"),
    (r"(rating|outlook).{0,30}downgrad|downgrad.{0,30}(rating|to (bb|b|c|d))", "credit rating downgrade"),
    (r"qualified (audit )?opinion|emphasis of matter", "qualified audit opinion"),
    (r"delay.{0,30}(financial results|audited results)", "results filing delayed"),
    (r"whistle.?blower", "whistle-blower complaint"),
]

POSITIVE = [
    "order", "contract", "bags", "wins", "won", "beats", "record", "surge", "jumps", "rises",
    "upgrade", "expansion", "capacity", "approval", "buyback", "dividend", "raises guidance",
    "strong", "growth", "profit up", "outperform", "launch", "acquires", "partnership",
]
NEGATIVE = [
    "falls", "drops", "slips", "plunge", "declines", "misses", "loss", "downgrade", "cut",
    "weak", "probe", "penalty", "fine", "shutdown", "strike", "fire at", "recall",
    "warning letter", "import alert", "slows", "lawsuit", "resigns", "default", "fraud",
]
PROMO = ["multibagger", "rocket", "to the moon", "double your money", "hidden gem", "must buy", "jackpot"]


def lexicon_score(text):
    t = text.lower()
    pos = sum(1 for w in POSITIVE if w in t)
    neg = sum(1 for w in NEGATIVE if w in t)
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def credibility_of(domain, source=""):
    tiers = S.section("sources.credibility")
    w = tiers.get("tier_weights", {}) or {}
    d = (domain or "").lower()
    if not d and source:
        d = source.lower()
    for tier in ("primary", "tier1", "tier2", "low"):
        for dom in tiers.get(tier, []) or []:
            if dom in d:
                return tier, float(w.get(tier, 0.5))
    if "nse" in (source or "").lower() and "announcement" in (source or "").lower():
        return "primary", float(w.get("primary", 1.0))
    return "unknown", float(w.get("unknown", 0.35))


def _ev_lines(evidence, limit=20):
    return "\n".join(f"[{e.id}] ({e.date or 'undated'}, {e.source}) {e.title[:220]}" for e in evidence[:limit])


# ===================================================================== 1
class ResearchAnalyst(Agent):
    KEY = "research_analyst"
    NAME = "Research Analyst"
    LEAD = LEAD
    ROLE = "Collects news and exchange filings; lists key developments and red flags."
    USES_LLM = True

    def analyse(self, ctx, f):
        ev = ctx.news_evidence()
        f.evidence = ev
        if not ev:
            f.summary = "No news or exchange filings found in the look-back window."
            return

        # rule-based red flags: these must never depend on an LLM being up
        flags = []
        for e in ev:
            text = e.title.lower()
            for pat, label in RED_FLAG_PATTERNS:
                if re.search(pat, text):
                    flags.append((label, e))
        seen = set()
        for label, e in flags:
            if label in seen:
                continue
            seen.add(label)
            f.flags.append(f"{label} ({e.source}, {e.date or 'undated'}) [{e.id}]")

        new = sum(1 for e in ev if ctx.board and ctx.board.is_new(e.id, ctx.name))
        f.signals.update({
            "items": len(ev),
            "filings": sum(1 for e in ev if e.kind == "filing"),
            "new_items": new,
            "red_flag_count": len(f.flags),
        })

        reply = self.ask_llm(
            "fast",
            "You are an equity research analyst covering Indian listed companies. "
            "From the items given, list the material developments for the company "
            "and any governance or accounting red flags. Cite item ids exactly. "
            'Schema: {"developments":[{"text":str,"evidence":[id]}],'
            '"red_flags":[{"text":str,"evidence":[id]}]}',
            f"Company: {ctx.name} ({ctx.sector})\nItems:\n{_ev_lines(ev)}",
            max_tokens=700,
        )
        if isinstance(reply, dict):
            f.used_llm = True
            dev, d1 = cited(reply.get("developments"), ev)
            rf, d2 = cited(reply.get("red_flags"), ev)
            f.signals["developments"] = dev[:8]
            # LLM red flags are kept only when a rule also saw trouble in the
            # same item - an LLM alone cannot cut a company's value
            rule_ids = {e.id for _, e in flags}
            for c in rf:
                if set(c["evidence"]) & rule_ids:
                    continue
                f.notes.append(f"possible concern (unconfirmed by rules): {c['text']}")
            if d1 + d2:
                f.notes.append(f"{d1 + d2} uncited LLM claim(s) discarded")
        else:
            f.signals["developments"] = [
                {"text": e.title, "evidence": [e.id]} for e in sorted(ev, key=lambda e: e.date, reverse=True)[:6]
            ]

        f.score = -min(1.0, 0.4 * len(f.flags))
        f.confidence = min(1.0, 0.3 + 0.05 * len(ev))
        f.summary = (
            f"{len(ev)} items ({f.signals['filings']} exchange filings, {new} new since last run); "
            + (f"{len(f.flags)} red flag(s)." if f.flags else "no red flags in filings or headlines.")
        )


# ===================================================================== 2
class NewsCredibilityAnalyst(Agent):
    KEY = "news_credibility_analyst"
    NAME = "News Credibility Analyst"
    LEAD = LEAD
    ROLE = "Rates every source, flags promotional or low-quality coverage."

    def analyse(self, ctx, f):
        weights, tiers = {}, {}
        promo = 0
        for n in ctx.news:
            e = Evidence(source=n.get("source") or n.get("domain") or "news", title=n["title"],
                         url=n.get("url", ""), date=n.get("date", ""), kind="news")
            dom = n.get("domain") or urllib.parse.urlparse(n.get("url", "")).netloc
            tier, w = credibility_of(dom, n.get("source", ""))
            weights[e.id] = w
            tiers[tier] = tiers.get(tier, 0) + 1
            if any(p in n["title"].lower() for p in PROMO):
                promo += 1
                weights[e.id] = min(w, 0.1)
            e.credibility = weights[e.id]
            f.evidence.append(e)
        ctx.shared.setdefault("cred_weights", {})[ctx.name] = weights
        if not weights:
            f.summary = "No news coverage to rate."
            return
        avg = sum(weights.values()) / len(weights)
        low = (tiers.get("low", 0) + tiers.get("unknown", 0)) / len(weights)
        f.signals.update({"avg_credibility": avg, "low_quality_share": low, "promotional_items": promo, "tiers": tiers})
        # promotion with little serious coverage is a pump-and-dump pattern
        pump = promo >= 2 and avg < 0.5
        f.signals["pump_risk"] = 1.0 if pump else min(0.3, 0.1 * promo)
        if pump:
            f.flags.append(f"promotional coverage dominates ({promo} items, average credibility {avg:.2f})")
        f.score = clamp((avg - 0.5) * 1.0 - 0.3 * min(promo, 3) / 3, -1, 1)
        f.confidence = min(1.0, 0.2 + 0.06 * len(weights))
        f.summary = (
            f"{len(weights)} news items; average credibility {avg:.2f}; "
            f"{low:.0%} from unknown or low-quality outlets; {promo} promotional."
        )


# ===================================================================== 3
class SentimentAnalyst(Agent):
    KEY = "sentiment_analyst"
    NAME = "Sentiment Analyst"
    LEAD = LEAD
    ROLE = "Credibility-weighted tone of news and filings."
    USES_LLM = True

    def analyse(self, ctx, f):
        ev = ctx.news_evidence()
        f.evidence = ev
        if not ev:
            f.summary = "No coverage to read sentiment from."
            return
        scores = {}
        reply = self.ask_llm(
            "fast",
            "Classify the tone of each headline for the named company's shareholders. "
            "sentiment is -1 (clearly bad) to 1 (clearly good); relevant is false when "
            "the item is not really about this company. "
            'Schema: {"items":[{"id":str,"sentiment":number,"relevant":bool}]}',
            f"Company: {ctx.name}\nHeadlines:\n{_ev_lines(ev, 25)}",
            max_tokens=900,
        )
        ids = {e.id: e for e in ev}
        if isinstance(reply, dict) and isinstance(reply.get("items"), list):
            for it in reply["items"]:
                if not isinstance(it, dict) or it.get("id") not in ids:
                    continue
                if it.get("relevant") is False:
                    continue
                try:
                    scores[it["id"]] = clamp(float(it.get("sentiment", 0)), -1, 1)
                except (TypeError, ValueError):
                    continue
            f.used_llm = bool(scores)
        if not scores:
            scores = {e.id: lexicon_score(e.title) for e in ev}
            f.notes.append("lexicon fallback used")

        # newer and more credible items count for more
        pairs = []
        for i, s in scores.items():
            e = ids[i]
            age = e.age_days()
            recency = math.exp(-(age or 15) / 20)
            pairs.append((s, e.credibility * recency))
        mean = weighted_mean(pairs) or 0.0
        pos = sum(1 for s in scores.values() if s > 0.2)
        neg = sum(1 for s in scores.values() if s < -0.2)
        f.signals.update({"sentiment": mean, "positive": pos, "negative": neg, "scored": len(scores)})
        f.score = mean
        f.confidence = min(1.0, 0.15 + 0.04 * len(scores)) * (1.0 if f.used_llm else 0.7)
        f.summary = f"Coverage tone {mean:+.2f} ({pos} positive, {neg} negative of {len(scores)} items)."


# ===================================================================== 4
class StockMovementAnalyst(Agent):
    KEY = "stock_movement_analyst"
    NAME = "Stock Movement Analyst"
    LEAD = LEAD
    ROLE = "Explains price moves against the Nifty and flags abnormal ones."

    def analyse(self, ctx, f):
        px = ctx.prices
        if len(px) < 30:
            f.summary = "Price history unavailable."
            return
        nifty = ctx.shared.get("nifty_prices") or []
        closes = [p["close"] for p in px]

        def ret(series, n):
            return series[-1] / series[-1 - n] - 1 if len(series) > n else None

        r = {k: ret(closes, n) for k, n in (("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 250))}
        nc = [p["close"] for p in nifty]
        rel = {k: (r[k] - ret(nc, n)) if r[k] is not None and ret(nc, n) is not None else None
               for k, n in (("1m", 21), ("3m", 63), ("1y", 250))}
        daily = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        vol = (sum(x * x for x in daily[-60:]) / max(1, len(daily[-60:]))) ** 0.5
        z_week = (math.log(1 + r["1w"]) / (vol * math.sqrt(5))) if r["1w"] is not None and vol else 0.0
        hi = max(closes[-250:])
        f.evidence.append(Evidence(source="Yahoo Finance prices", title=f"{ctx.ticker} daily closes",
                                   url=f"https://finance.yahoo.com/quote/{ctx.ticker}", date=px[-1]["date"],
                                   value=closes[-1], kind="data"))
        f.signals.update({
            "returns": r, "relative_to_nifty": rel, "daily_vol": vol,
            "annual_vol": vol * math.sqrt(250), "week_z": z_week,
            "drawdown_from_high": closes[-1] / hi - 1,
        })
        if abs(z_week) > 2.5:
            # link the move to news from the same week if there is any
            recent = [e for e in ctx.news_evidence() if (e.age_days() or 99) <= 7]
            why = f"; same-week coverage: '{recent[0].title[:90]}'" if recent else "; no same-week news found"
            f.notes.append(f"abnormal week: {r['1w']:+.1%} ({z_week:+.1f} sigma){why}")
        rs = rel.get("3m") if rel.get("3m") is not None else (r.get("3m") or 0.0)
        f.score = math.tanh(rs / 0.15)
        f.confidence = 0.6 if nifty else 0.4
        parts = [f"{k} {v:+.1%}" for k, v in r.items() if v is not None]
        f.summary = "Price " + ", ".join(parts) + (
            f"; vs Nifty 3m {rel['3m']:+.1%}" if rel.get("3m") is not None else ""
        ) + f"; {f.signals['drawdown_from_high']:+.0%} from 52-week high."


# ===================================================================== 5
class MarketImpactAnalyst(Agent):
    KEY = "market_impact_analyst"
    NAME = "Market Impact Analyst"
    LEAD = LEAD
    ROLE = "Judges which stories change the business's value, by how much, and for how long."
    USES_LLM = True

    def analyse(self, ctx, f):
        ev = sorted(ctx.news_evidence(), key=lambda e: (e.credibility, e.date), reverse=True)[:15]
        f.evidence = ev
        if not ev:
            f.summary = "Nothing material to assess."
            return
        impacts = []
        reply = self.ask_llm(
            "fast",
            "You assess how news changes a company's long-term business value (not "
            "tomorrow's share price). For each material item give direction -1..1, "
            "magnitude 0..1 relative to the company's size, horizon short|medium|long "
            "and channel revenue|margin|risk|capital. Skip immaterial items. "
            'Schema: {"impacts":[{"id":str,"direction":number,"magnitude":number,'
            '"horizon":str,"channel":str}]}',
            f"Company: {ctx.name} ({ctx.sector})\nItems:\n{_ev_lines(ev, 15)}",
            max_tokens=700,
        )
        ids = {e.id: e for e in ev}
        if isinstance(reply, dict) and isinstance(reply.get("impacts"), list):
            for it in reply["impacts"]:
                if isinstance(it, dict) and it.get("id") in ids:
                    try:
                        impacts.append({
                            "id": it["id"],
                            "direction": clamp(float(it.get("direction", 0)), -1, 1),
                            "magnitude": clamp(float(it.get("magnitude", 0)), 0, 1),
                            "horizon": str(it.get("horizon", "medium")),
                            "channel": str(it.get("channel", "")),
                        })
                    except (TypeError, ValueError):
                        continue
            f.used_llm = bool(impacts)
        if not impacts:
            f.notes.append("keyword fallback used")
            for e in ev:
                s = lexicon_score(e.title)
                if s:
                    impacts.append({"id": e.id, "direction": s, "magnitude": 0.3, "horizon": "medium", "channel": ""})

        h_w = {"short": 0.3, "medium": 0.7, "long": 1.0}
        pairs = [
            (i["direction"] * i["magnitude"], ids[i["id"]].credibility * h_w.get(i["horizon"], 0.7))
            for i in impacts
        ]
        raw = weighted_mean(pairs) or 0.0
        # a single huge item should count; ten small ones should not add up to it
        news_impact = clamp(raw * 2.0, -1, 1)
        f.signals.update({"news_impact": news_impact, "impacts": impacts[:10]})
        f.score = news_impact
        f.confidence = min(1.0, 0.2 + 0.08 * len(impacts)) * (1.0 if f.used_llm else 0.6)
        top = sorted(impacts, key=lambda i: -abs(i["direction"] * i["magnitude"]))[:2]
        f.summary = f"Net value impact of recent news {news_impact:+.2f}" + (
            "; biggest: " + "; ".join(f"'{ids[i['id']].title[:70]}' ({i['direction']:+.1f})" for i in top)
            if top else ""
        )


TEAM = [ResearchAnalyst, NewsCredibilityAnalyst, SentimentAnalyst, StockMovementAnalyst, MarketImpactAnalyst]
