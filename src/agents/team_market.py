# FILE: src/agents/team_market.py
"""
Head of Market Activity & Ownership Research's team.

    Market Volume Intelligence   liquidity, volume spikes, delivery %,
                                 price-volume divergence
    Insider Activity             promoter / director buying and selling
                                 (SEBI PIT disclosures via NSE)
    Fund Holdings Research       shareholding pattern trend, promoter pledges,
                                 institutional ownership
    Short-Seller Research        published short reports and allegations,
                                 distress-style price and volume behaviour
"""

import datetime as dt
import math

from agents import settings as S
from agents.base import Agent, Evidence, clamp
from agents.team_news import _ev_lines, credibility_of

LEAD = "market_activity_lead"
CRORE = 1.0e7


# ==================================================================== 11
class MarketVolumeAnalyst(Agent):
    KEY = "market_volume_analyst"
    NAME = "Market Volume Intelligence Analyst"
    LEAD = LEAD
    ROLE = "Liquidity, unusual volume and delivery-based accumulation."

    def analyse(self, ctx, f):
        px = [p for p in ctx.prices if p.get("volume")]
        if len(px) < 30:
            f.summary = "Volume history unavailable."
            return
        tv = [p["close"] * p["volume"] for p in px]
        adtv_3m = sum(tv[-63:]) / len(tv[-63:]) / CRORE
        v5 = sum(p["volume"] for p in px[-5:]) / 5
        v50 = sum(p["volume"] for p in px[-50:]) / len(px[-50:])
        spike = v5 / v50 if v50 else 1.0
        r5 = px[-1]["close"] / px[-6]["close"] - 1 if len(px) > 6 else 0.0
        # illiquid below ~1 crore a day, comfortably liquid above ~50 crore
        liquidity_risk = clamp(1 - math.log10(max(adtv_3m, 0.1) / 1.0) / math.log10(50), 0, 1)

        trade = ctx.feeds.nse_trade_info(ctx.symbol) if ctx.symbol else {}
        dpct = trade.get("delivery_pct")
        f.evidence.append(Evidence(source="Yahoo Finance volumes", title=f"{ctx.ticker} daily volume",
                                   url=f"https://finance.yahoo.com/quote/{ctx.ticker}/history",
                                   date=px[-1]["date"], value=adtv_3m, kind="data"))
        if dpct is not None:
            f.evidence.append(Evidence(source="NSE trade info", title=f"{ctx.symbol} delivery {dpct:.0%}",
                                       url=f"https://www.nseindia.com/get-quotes/equity?symbol={ctx.symbol}",
                                       date=dt.date.today().isoformat(), value=dpct, kind="data"))

        # accumulation: rising price on heavy, delivery-backed volume
        acc = 0.0
        if spike > 1.5:
            acc = math.copysign(min(1.0, (spike - 1) / 2), r5)
        if dpct is not None:
            acc += clamp((dpct - 0.45) / 0.3, -0.5, 0.5) * (1 if r5 >= 0 else -1)
        acc = clamp(acc, -1, 1)
        f.signals.update({
            "adtv_cr_3m": adtv_3m, "volume_spike_5d": spike, "return_5d": r5,
            "delivery_pct": dpct, "liquidity_risk": liquidity_risk, "accumulation": acc,
        })
        if spike > 3 and r5 < -0.08:
            f.notes.append(f"heavy selling: volume {spike:.1f}x normal while price fell {r5:.1%}")
        f.score = clamp(0.6 * acc - 0.4 * liquidity_risk + 0.2, -1, 1)
        f.confidence = 0.5 + (0.2 if dpct is not None else 0)
        f.summary = (
            f"Average traded value {adtv_3m:,.1f} crore/day (liquidity risk {liquidity_risk:.2f}); "
            f"5-day volume {spike:.1f}x normal with price {r5:+.1%}"
            + (f"; delivery {dpct:.0%}" if dpct is not None else "")
            + "."
        )


# ==================================================================== 12
class InsiderActivityAnalyst(Agent):
    KEY = "insider_activity_analyst"
    NAME = "Insider Activity Analyst"
    LEAD = LEAD
    ROLE = "Promoter and insider trades from SEBI PIT disclosures."

    def analyse(self, ctx, f):
        rows = ctx.insider
        source = "NSE insider trading (SEBI PIT) disclosures"
        url = f"https://www.nseindia.com/companies-listing/corporate-filings-insider-trading?symbol={ctx.symbol}"
        if not rows and ctx.ticker:
            rows = [
                {"name": r["name"], "category": r["role"], "type": r["text"], "shares": r["shares"],
                 "value": r["value"], "date": r["date"], "url": ""}
                for r in ctx.feeds.yf_insiders(ctx.ticker)
            ]
            source, url = "Yahoo Finance insider transactions", f"https://finance.yahoo.com/quote/{ctx.ticker}/insider-transactions"
        if not rows:
            f.summary = "No insider disclosures in the look-back window."
            return

        mcap = ctx.base.get("market_cap") or 0
        buy = sell = pledged = 0.0
        promoter_sell = 0.0
        for r in rows:
            t = (r.get("type") or "").lower()
            v = r.get("value") or 0.0
            cat = (r.get("category") or "").lower()
            if "pledge" in t and "revok" not in t and "release" not in t:
                pledged += v
            elif "buy" in t or "acqui" in t or "purchase" in t:
                buy += v
            elif "sell" in t or "sale" in t or "dispos" in t:
                sell += v
                if "promoter" in cat:
                    promoter_sell += v
            f.evidence.append(Evidence(source=source, title=f"{r.get('name', '')} ({r.get('category', '')}) {r.get('type', '')}",
                                       url=r.get("url") or url, date=r.get("date", ""), value=v, kind="filing"))
        net = buy - sell
        net_pct = net / mcap if mcap else None
        promoter_sell_pct = promoter_sell / mcap if mcap else None
        thr = S.num("hybrid_model.governance.promoter_selling_flag_above", 0.02)
        if promoter_sell_pct is not None and promoter_sell_pct > thr:
            f.flags.append(f"promoters sold {promoter_sell_pct:.1%} of the company in the look-back window")
        if pledged and mcap and pledged / mcap > 0.005:
            f.flags.append(f"new promoter pledges worth {pledged / CRORE:,.0f} crore")
        gov = clamp((promoter_sell_pct or 0) / max(thr, 1e-6) * 0.5 + (0.3 if pledged else 0), 0, 1)
        f.signals.update({
            "buy_value": buy, "sell_value": sell, "net_value": net, "net_pct_mcap": net_pct,
            "promoter_sell_pct": promoter_sell_pct, "new_pledges": pledged, "governance_risk": gov,
            "transactions": len(rows),
        })
        f.score = math.tanh((net_pct or 0) / 0.003) if net_pct is not None else (0.3 if net > 0 else -0.3 if net < 0 else 0)
        f.confidence = min(1.0, 0.3 + 0.05 * len(rows)) * (1.0 if "NSE" in source else 0.6)
        f.summary = (
            f"{len(rows)} insider transactions: bought {buy / CRORE:,.1f} cr, sold {sell / CRORE:,.1f} cr"
            + (f" (net {net_pct:+.2%} of market cap)" if net_pct is not None else "")
            + (f"; {pledged / CRORE:,.1f} cr newly pledged" if pledged else "")
            + "."
        )


# ==================================================================== 13
class FundHoldingsAnalyst(Agent):
    KEY = "fund_holdings_analyst"
    NAME = "Fund Holdings Research Analyst"
    LEAD = LEAD
    ROLE = "Shareholding pattern trend, promoter pledges, institutional ownership."

    def analyse(self, ctx, f):
        shp = ctx.shareholding
        pledge = ctx.feeds.nse_pledge(ctx.symbol) if ctx.symbol else None
        yh = ctx.feeds.yf_holders(ctx.ticker) if ctx.ticker else {}
        url = f"https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern?symbol={ctx.symbol}"
        for r in shp[:4]:
            f.evidence.append(Evidence(source="NSE shareholding pattern", title=f"promoter {r['promoter']:.2%}" if r.get("promoter") is not None else "shareholding",
                                       url=url, date=r.get("date", ""), value=r.get("promoter"), kind="filing"))
        if pledge is not None:
            f.evidence.append(Evidence(source="NSE pledge disclosures", title=f"promoter shares pledged {pledge:.1%}",
                                       url=f"https://www.nseindia.com/companies-listing/corporate-filings-pledged-data?symbol={ctx.symbol}",
                                       date=dt.date.today().isoformat(), value=pledge, kind="filing"))
        if yh.get("institutions") is not None:
            f.evidence.append(Evidence(source="Yahoo Finance holders", title=f"institutions hold {yh['institutions']:.1%}",
                                       url=f"https://finance.yahoo.com/quote/{ctx.ticker}/holders",
                                       date=dt.date.today().isoformat(), value=yh["institutions"], kind="data"))
        if not f.evidence:
            f.summary = "No shareholding data available."
            return

        chg = None
        prom = [r["promoter"] for r in shp if r.get("promoter") is not None]
        if len(prom) >= 2:
            chg = prom[0] - prom[-1]
        parts = []
        if chg is not None:
            parts.append(math.tanh(chg / 0.02))
        inst = yh.get("institutions")
        if inst is not None:
            parts.append(clamp((inst - 0.15) / 0.25, -0.5, 0.5))
        pledge_risk = 0.0
        if pledge is not None:
            lim = S.num("hybrid_model.governance.pledge_flag_above", 0.25)
            pledge_risk = clamp(pledge / max(lim, 1e-6), 0, 1)
            parts.append(-pledge_risk)
            if pledge > lim:
                f.flags.append(f"{pledge:.0%} of promoter holding is pledged")
        f.signals.update({
            "promoter_holding": prom[0] if prom else yh.get("insiders"),
            "promoter_change": chg, "pledge_pct": pledge, "pledge_risk": pledge_risk,
            "institutions": inst, "governance_risk": pledge_risk,
        })
        f.score = sum(parts) / len(parts) if parts else 0.0
        f.confidence = min(1.0, 0.25 + 0.15 * len(parts) + (0.2 if shp else 0))
        f.summary = (
            (f"Promoters hold {prom[0]:.1%}" if prom else "Promoter holding unavailable")
            + (f" ({chg:+.2%} over {len(prom)} quarters)" if chg is not None else "")
            + (f"; pledged {pledge:.1%}" if pledge is not None else "")
            + (f"; institutions {inst:.1%}" if inst is not None else "")
            + "."
        )


# ==================================================================== 14
SHORT_WORDS = ["short seller", "short-seller", "short report", "hindenburg", "allegation",
               "accounting irregular", "forensic", "fraud", "manipulat", "governance concern"]


class ShortSellerAnalyst(Agent):
    KEY = "short_seller_analyst"
    NAME = "Short-Seller Research Analyst"
    LEAD = LEAD
    ROLE = "Published short theses and allegations; distress-style trading."
    USES_LLM = True

    def analyse(self, ctx, f):
        q = ctx.name.replace(" Limited", "").replace(" Ltd", "")
        news = ctx.feeds.news(f'"{q}" short seller OR allegations OR irregularities', limit=12)
        ev = []
        for n in news:
            _, w = credibility_of(n.get("domain"), n.get("source"))
            ev.append(Evidence(source=n.get("source") or "news", title=n["title"], url=n.get("url", ""),
                               date=n.get("date", ""), kind="news", credibility=w))
        hits = [e for e in ev if any(w in e.title.lower() for w in SHORT_WORDS) and q.split()[0].lower() in e.title.lower()]
        severity = 0.0
        if hits:
            reply = self.ask_llm(
                "fast",
                "Do these headlines report a short-seller report or a specific allegation "
                "of fraud or accounting irregularity against the named company itself "
                "(not its sector)? severity 0 none, 0.5 unconfirmed allegation, 1 formal "
                'report or regulator action. Schema: {"severity":number,"evidence":[id],"summary":str}',
                f"Company: {ctx.name}\nHeadlines:\n{_ev_lines(hits, 10)}",
                max_tokens=250,
            )
            if isinstance(reply, dict) and reply.get("severity") is not None:
                try:
                    severity = clamp(float(reply["severity"]), 0, 1)
                    f.used_llm = True
                    if reply.get("summary"):
                        f.notes.append(str(reply["summary"])[:300])
                except (TypeError, ValueError):
                    pass
            if not f.used_llm:
                severity = clamp(sum(e.credibility for e in hits) / 3, 0, 1)
            if severity >= 0.7:
                f.flags.append(f"short-seller report or formal allegation: '{hits[0].title[:100]}' [{hits[0].id}]")

        mv = ctx.findings.get("market_volume_analyst")
        sm = ctx.findings.get("stock_movement_analyst")
        distress = 0.0
        if mv and sm and mv.status == "ok" and sm.status == "ok":
            r1m = (sm.signals.get("returns") or {}).get("1m") or 0.0
            spike = mv.signals.get("volume_spike_5d") or 1.0
            if r1m < -0.15 and spike > 2:
                distress = clamp((-r1m - 0.15) / 0.2 + (spike - 2) / 4, 0, 1)
                f.notes.append(f"distress-style trading: {r1m:.0%} in a month on {spike:.1f}x volume")
        f.evidence = ev
        if distress:
            f.evidence.append(Evidence(source="Yahoo Finance prices and volumes",
                                       title=f"{ctx.ticker} one-month price and volume",
                                       date=dt.date.today().isoformat(), kind="derived"))
        if not ev and not distress:
            f.summary = "No short-seller coverage found."
            # absence of a short report is itself information, if weak
            f.evidence.append(Evidence(source="Google News search", title=f"no short-seller coverage of {q}",
                                       date=dt.date.today().isoformat(), kind="derived"))
        risk = max(severity, 0.6 * distress)
        f.signals.update({"short_severity": severity, "distress_trading": distress, "short_risk": risk, "hits": len(hits)})
        f.score = -risk
        f.confidence = 0.5 if hits else 0.3
        if hits or distress:
            f.summary = f"Short-seller / allegation risk {risk:.2f} ({len(hits)} relevant headline(s))."
        elif ev:
            f.summary = "Searched for short reports and allegations; none relevant found."


TEAM = [MarketVolumeAnalyst, InsiderActivityAnalyst, FundHoldingsAnalyst, ShortSellerAnalyst]
