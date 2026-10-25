"""
Equity Research Lead's team. Numbers only - no LLM is needed here, which is
also why this team carries the most weight in the chief's score.

    Fundamental Research Analyst   returns on capital, growth, margins,
                                   leverage; moat, momentum, capital allocation
    Financial Forensics Analyst    Piotroski, Altman Z'', Beneish M, accruals,
                                   cash conversion, receivable days
    Pre-Earnings Intelligence      quarterly trend into the next results date
"""

import datetime as dt
import math
import statistics

from agents import forensics as FX
from agents import settings as S
from agents.base import Agent, Evidence, clamp

LEAD = "equity_research_lead"


def _statement_evidence(ctx, fy, title):
    return Evidence(
        source="Annual financial statements (Yahoo Finance)",
        title=f"{ctx.name} {title} FY{fy}",
        url=f"https://finance.yahoo.com/quote/{ctx.ticker}/financials",
        date=f"{fy}-03-31",
        kind="data",
    )


def _ratio(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


# ===================================================================== 6
class FundamentalResearchAnalyst(Agent):
    KEY = "fundamental_research_analyst"
    NAME = "Fundamental Research Analyst"
    LEAD = LEAD
    ROLE = "Returns on capital, growth, margins and balance-sheet strength."

    def analyse(self, ctx, f):
        yrs = ctx.annual
        if len(yrs) < 2:
            f.summary = "Fewer than two years of statements - fundamentals not assessed."
            return
        fys = [fy for fy, _ in yrs]
        last_fy, last = yrs[-1]
        first_fy, first = yrs[0]
        n = last_fy - first_fy
        tax = last.get("tax_rate") or 0.25

        roe = [_ratio(d.get("net_income"), d.get("equity")) for _, d in yrs]
        roic = []
        for _, d in yrs:
            inv = None
            if d.get("equity") is not None:
                gross = d["equity"] + (d.get("total_debt") or 0)
                # a cash-rich company's net invested capital can approach zero
                # and send ROIC into the hundreds of percent; treat at most
                # half of the capital base as surplus cash
                inv = max(gross - (d.get("cash") or 0), 0.5 * gross)
            roic.append(_ratio((d.get("ebit") or 0) * (1 - tax), inv) if inv and inv > 0 and d.get("ebit") is not None else None)
        margins = [_ratio(d.get("ebit"), d.get("revenue")) for _, d in yrs]
        rev_cagr = FX.cagr(first.get("revenue"), last.get("revenue"), n)
        eps_cagr = FX.cagr(first.get("eps"), last.get("eps"), n)
        ni_growth = [
            _ratio(yrs[i][1].get("net_income"), yrs[i - 1][1].get("net_income"))
            for i in range(1, len(yrs))
        ]
        ni_growth = [g - 1 for g in ni_growth if g is not None and g > 0]
        de = _ratio(last.get("total_debt"), last.get("equity"))
        icov = FX.interest_cover(last)

        k_base = ctx.base.get("k_capm") or 0.12
        roic_ok = [r for r in roic if r is not None]
        moat = 0.0
        if roic_ok:
            spread = statistics.median(roic_ok) - k_base
            stab = 1.0
            if len(roic_ok) >= 3 and statistics.mean(roic_ok) > 0:
                stab = clamp(1 - statistics.pstdev(roic_ok) / statistics.mean(roic_ok), 0, 1)
            moat = math.tanh(spread / 0.08) * (0.5 + 0.5 * stab)

        recent_g = rev_cagr if rev_cagr is not None else 0.0
        if len(yrs) >= 2 and yrs[-2][1].get("revenue"):
            recent_g = 0.5 * recent_g + 0.5 * (last.get("revenue", 0) / yrs[-2][1]["revenue"] - 1)
        nominal = S.num("macro.real_gdp_growth", 0.065) + S.num("macro.cpi_inflation", 0.04)
        momentum = math.tanh((recent_g - nominal) / 0.10)

        cap_alloc_parts = []
        roe_ok = [r for r in roe if r is not None]
        if len(roe_ok) >= 2:
            cap_alloc_parts.append(math.tanh((roe_ok[-1] - roe_ok[0]) / 0.05))
        sh0, sh1 = first.get("shares"), last.get("shares")
        if sh0 and sh1:
            dil = sh1 / sh0 - 1
            cap_alloc_parts.append(clamp(-dil / 0.05, -1, 0.3))
        if last.get("dividends_paid") and last.get("net_income") and last["net_income"] > 0:
            payout = last["dividends_paid"] / last["net_income"]
            cap_alloc_parts.append(0.3 if 0.1 <= payout <= 0.7 else -0.2)
        capital_allocation = statistics.mean(cap_alloc_parts) if cap_alloc_parts else 0.0

        vol = FX.stdev(ni_growth)
        earnings_volatility = clamp((vol or 0.15) / 0.5, 0, 1)

        f.evidence = [_statement_evidence(ctx, fy, "income statement, balance sheet, cash flow") for fy in fys]
        f.signals.update({
            "roe": roe_ok[-1] if roe_ok else None,
            "roic_median": statistics.median(roic_ok) if roic_ok else None,
            "ebit_margin": margins[-1],
            "margin_change": (margins[-1] - margins[0]) if margins[-1] is not None and margins[0] is not None else None,
            "rev_cagr": rev_cagr, "eps_cagr": eps_cagr,
            "de_ratio": de, "interest_cover": icov,
            "moat": moat, "earnings_momentum": momentum,
            "capital_allocation": capital_allocation,
            "earnings_volatility_risk": earnings_volatility,
            "years": len(yrs),
        })
        strength = 0.0
        if de is not None:
            strength += clamp((1.0 - de) / 1.5, -1, 0.5)
        if icov is not None:
            strength += clamp((icov - 3) / 6, -0.5, 0.5)
        f.score = clamp(0.4 * moat + 0.3 * momentum + 0.15 * capital_allocation + 0.15 * strength, -1, 1)
        f.confidence = min(1.0, 0.3 + 0.15 * len(yrs))
        f.summary = (
            f"ROIC {f.signals['roic_median']:.1%}" if f.signals["roic_median"] is not None else "ROIC n/a"
        ) + (
            f", ROE {f.signals['roe']:.1%}" if f.signals["roe"] is not None else ""
        ) + (
            f", revenue CAGR {rev_cagr:.1%}" if rev_cagr is not None else ""
        ) + (
            f", EBIT margin {margins[-1]:.1%}" if margins[-1] is not None else ""
        ) + (
            f", debt/equity {de:.2f}" if de is not None else ""
        ) + f"; moat {moat:+.2f}, momentum {momentum:+.2f}."
        if de is not None and de > 2.5:
            f.flags.append(f"debt/equity of {de:.1f} (FY{last_fy})")
        if icov is not None and icov < 1.5:
            f.flags.append(f"interest cover only {icov:.1f}x (FY{last_fy})")


# ===================================================================== 7
class FinancialForensicsAnalyst(Agent):
    KEY = "financial_forensics_analyst"
    NAME = "Financial Forensics Analyst"
    LEAD = LEAD
    ROLE = "Accounting quality and manipulation / distress screens."

    def analyse(self, ctx, f):
        yrs = ctx.annual
        if len(yrs) < 2:
            f.summary = "Fewer than two years of statements - forensic screens need a prior year."
            return
        (fy0, prev), (fy1, cur) = yrs[-2], yrs[-1]
        f.evidence = [_statement_evidence(ctx, fy, "statements for forensic screens") for fy in (fy0, fy1)]

        fscore, fmax, tests = FX.piotroski(cur, prev)
        z, zone, zn = FX.altman_z_em(cur)
        m, mn, ratios = FX.beneish_m(cur, prev)
        acc = FX.accrual_ratio(cur, prev)
        conv = FX.cash_conversion([d for _, d in yrs[-3:]])
        rd0, rd1 = FX.receivable_days(prev), FX.receivable_days(cur)
        icov = FX.interest_cover(cur)

        risk = 0.0
        notes = []
        threshold = S.num("forensics.beneish_threshold", FX.BENEISH_THRESHOLD)
        margin = S.num("forensics.beneish_flag_margin", 0.25)
        if m is not None and m > threshold:
            # graded: a score just over the line is a much weaker signal than
            # one a full point above it
            w = 0.5 * (mn / 8) * clamp((m - threshold) / 1.0, 0.1, 1.0)
            risk += w
            notes.append(f"Beneish M {m:.2f} above {threshold} ({mn}/8 ratios)")
            if mn >= 6 and m > threshold + margin:
                f.flags.append(f"Beneish M-score {m:.2f} matches the earnings-manipulation profile (FY{fy1})")
        if zone == "distress":
            risk += 0.3
            notes.append(f"Altman Z'' {z:.2f} in distress zone")
            f.flags.append(f"Altman Z'' {z:.2f} in the distress zone (FY{fy1})")
        elif zone == "grey":
            risk += 0.1
        if conv is not None and conv < 0.6:
            risk += 0.2
            notes.append(f"only {conv:.0%} of profit turned into operating cash")
            if conv < 0.4:
                f.flags.append(f"cash conversion of {conv:.0%} over {min(3, len(yrs))} years")
        if acc is not None and acc > 0.10:
            risk += 0.15
            notes.append(f"accruals {acc:.1%} of assets")
        if rd0 and rd1 and rd1 > rd0 * 1.3 and rd1 - rd0 > 15:
            risk += 0.15
            notes.append(f"receivable days up from {rd0:.0f} to {rd1:.0f}")
        if icov is not None and icov < 1.5:
            risk += 0.2
        risk = clamp(risk, 0, 1)

        financial_strength = ((fscore / fmax) - 0.5) * 2 if fmax >= 5 else 0.0
        eq_parts = []
        if conv is not None:
            eq_parts.append(clamp((conv - 0.8) / 0.4, -1, 1))
        if acc is not None:
            eq_parts.append(clamp(-acc / 0.08, -1, 1))
        earnings_quality = statistics.mean(eq_parts) if eq_parts else 0.0

        f.signals.update({
            "piotroski": fscore, "piotroski_max": fmax, "piotroski_tests": tests,
            "altman_z": z, "altman_zone": zone, "beneish_m": m, "beneish_ratios": mn,
            "accruals": acc, "cash_conversion": conv,
            "receivable_days": rd1, "receivable_days_prev": rd0,
            "forensic_risk": risk, "financial_strength": financial_strength,
            "earnings_quality": earnings_quality,
        })
        f.notes.extend(notes)
        f.score = clamp(0.4 * financial_strength + 0.3 * earnings_quality - 0.8 * risk + 0.2, -1, 1)
        coverage = (min(fmax, 9) / 9 + (zn / 4) + (mn / 8)) / 3
        f.confidence = clamp(0.2 + 0.7 * coverage, 0, 1)
        f.summary = (
            f"Piotroski {fscore}/{fmax}"
            + (f", Altman Z'' {z:.2f} ({zone})" if z is not None else "")
            + (f", Beneish M {m:.2f}" if m is not None else "")
            + (f", cash conversion {conv:.0%}" if conv is not None else "")
            + f"; forensic risk {risk:.2f}."
        )


# ===================================================================== 8
class PreEarningsAnalyst(Agent):
    KEY = "pre_earnings_analyst"
    NAME = "Pre-Earnings Intelligence Analyst"
    LEAD = LEAD
    ROLE = "Quarterly trend going into the next results date."

    def analyse(self, ctx, f):
        q = [r for r in (ctx.statements.get("quarterly") or []) if r.get("revenue")]
        q = sorted(q, key=lambda r: r["date"], reverse=True)
        events = ctx.feeds.nse_events(ctx.symbol) if ctx.symbol else []
        nxt = ""
        for e in events:
            if "result" in (e.get("purpose", "") + e.get("desc", "")).lower() and e.get("date", "") >= dt.date.today().isoformat():
                nxt = e["date"]
                f.evidence.append(Evidence(source="NSE event calendar", title=f"{ctx.symbol} {e.get('purpose')}",
                                           url="https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
                                           date=e["date"], kind="filing"))
                break
        if not nxt and ctx.ticker:
            nxt = ctx.feeds.earnings_date(ctx.ticker) or ""
            if nxt:
                f.evidence.append(Evidence(source="Yahoo Finance calendar", title=f"{ctx.ticker} earnings date",
                                           url=f"https://finance.yahoo.com/quote/{ctx.ticker}", date=nxt, kind="data"))
        days_to = None
        if nxt:
            try:
                days_to = (dt.date.fromisoformat(nxt) - dt.date.today()).days
            except ValueError:
                pass
        if days_to is not None and days_to < 0:
            # the source still lists the last results date; the next one is
            # not announced yet
            f.notes.append(f"last results were {-days_to} days ago; next date not yet announced")
            nxt, days_to = "", None

        def year_ago(a):
            """The quarter 11-13 months before a, matched by date: the source
            skips quarters, so 'four rows back' is not always a year back."""
            da = dt.date.fromisoformat(a["date"])
            for b in q:
                gap = (da - dt.date.fromisoformat(b["date"])).days
                if 335 <= gap <= 395:
                    return b
            return None

        yoy_rev, yoy_ni = [], []
        for a in q[:4]:
            b = year_ago(a)
            if b is None:
                continue
            if b.get("revenue"):
                yoy_rev.append(a["revenue"] / b["revenue"] - 1)
            if b.get("net_income") and b["net_income"] > 0 and a.get("net_income") is not None:
                yoy_ni.append(a["net_income"] / b["net_income"] - 1)
        seq = None
        if len(q) >= 2 and q[1].get("revenue"):
            gap = (dt.date.fromisoformat(q[0]["date"]) - dt.date.fromisoformat(q[1]["date"])).days
            if 80 <= gap <= 100:
                seq = q[0]["revenue"] / q[1]["revenue"] - 1
        if q:
            f.evidence.append(Evidence(source="Quarterly results (Yahoo Finance)",
                                       title=f"{ctx.name} last {len(q)} quarters",
                                       url=f"https://finance.yahoo.com/quote/{ctx.ticker}/financials",
                                       date=q[0]["date"], kind="data"))
        if not q and not nxt:
            f.summary = "No quarterly results or results date available."
            return

        accel = None
        if len(yoy_rev) >= 2:
            accel = yoy_rev[0] - yoy_rev[1]
        momentum = 0.0
        parts = []
        if yoy_rev:
            parts.append(math.tanh((yoy_rev[0] - 0.10) / 0.12))
        if yoy_ni:
            parts.append(math.tanh((yoy_ni[0] - 0.10) / 0.20))
        if accel is not None:
            parts.append(math.tanh(accel / 0.05) * 0.5)
        if parts:
            momentum = statistics.mean(parts)
        vol = ctx.signal("stock_movement_analyst", "annual_vol", 0.3)
        surprise_risk = clamp((vol or 0.3) / 0.6, 0, 1) if days_to is not None and 0 <= days_to <= 14 else 0.0
        f.signals.update({
            "next_results": nxt, "days_to_results": days_to,
            "yoy_revenue": yoy_rev[:4], "yoy_profit": yoy_ni[:4], "qoq_revenue": seq,
            "acceleration": accel, "earnings_momentum": momentum, "surprise_risk": surprise_risk,
        })
        f.score = momentum
        f.confidence = min(1.0, 0.2 + 0.1 * len(q))
        f.summary = (
            (f"Latest quarter revenue {yoy_rev[0]:+.1%} YoY" if yoy_rev else "Quarterly trend unavailable")
            + (f", profit {yoy_ni[0]:+.1%} YoY" if yoy_ni else "")
            + (f"; next results {nxt} ({days_to} days)" if nxt and days_to is not None else "")
            + (" - results within two weeks, expect volatility." if surprise_risk > 0.5 else ".")
        )


TEAM = [FundamentalResearchAnalyst, FinancialForensicsAnalyst, PreEarningsAnalyst]
