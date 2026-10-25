"""
HYBRID MODEL - the project's headline intrinsic value.

One formula, used in two places:

    valuation report   every company, every financial year, from the accounts
                       alone (point-in-time), so it is back-tested and scored
                       against the 1-May price like every other model
    research agents    the latest year, with the 23 agents' readings of news,
                       forensics, ownership, macro and geopolitics folded in

Every constant lives in agent_settings.yaml -> hybrid_model, and every one
can be changed live in the web app's Hybrid Model Lab before it is saved.

THE FORMULA

  1  Cost of equity      k = max(Rf + beta_adj x ERP, k_floor) + SUM premia
                         premia: size (market-cap bands), leverage (D/E),
                         liquidity, governance, forensic, macro, geopolitical,
                         earnings volatility - each = cap x risk(0..1), and
                         all together capped
  2  Growth              g = g_base + SUM tilts, clamped to [g_min, g_max]
                         g_T = min(terminal, nominal GDP, k - min spread)

  3  Six valuation lenses, each answering a different question:
       cash_flow        what will the business pay out?  three-stage FCFF DCF
                        (lenders: residual income) at k and g, with starting
                        cash flow = blend(observed FCFF, NOPAT x (1 - g/RONIC))
                        and RONIC = WACC + 2% + 4% x moat
       earnings_power   what is it worth if it never grows?  EPV =
                        normalised NOPAT / WACC + cash - debt (lenders:
                        normalised profit / k)
       asset            what is the balance sheet worth?  book value x
                        justified P/B, (ROE - g_T) / (k - g_T), clamped
       market           what do peers pay?  peer-regression P/E and EV/EBITDA
       conservative     Graham Number
       learning         machine-learning consensus (when the ML stage ran)

  4  Growth-credibility gate
                         PVGO share = 1 - earnings_power / cash_flow
                         allowed share = base + moat_bonus x max(0, moat)
                         above it, cash_flow is cut back to
                         earnings_power / (1 - allowed share)
                         -> growth is only paid for when the moat earns it

  5  Calibrate           each lens is shifted by its own median miss against
                         the 1-May price in EARLIER years (same sector when it
                         has enough history, else all companies), shrunk by
                         evidence; its weight is scaled by its relative skill.
                         Point-in-time: a year never learns from itself.
     Blend               regime weights (mature / lender / loss_maker / young)
                         x skill x estimate penalty; lenses further than outlier_ratio
                         from the weighted median are dropped; then
                         V_core = exp( SUM w ln V / SUM w )          (geometric)

  6  Quality and         V = V_core x Q x (1 - H)
     governance          Q = 1 + SUM cap x score  (moat, earnings quality,
                         financial strength, capital allocation), clamped
                         H = per-red-flag haircut, capped

  7  Scenarios           steps 1-6 again with bull / bear shifts to g, k and
                         Q; probabilities tilted by bull / bear conviction
                         HYBRID MODEL value = SUM p x V

  8  Uncertainty         sigma = sqrt(lens dispersion^2 + base sigma^2)
                         band  = value x exp(-/+ 1.2816 sigma)  (P10 / P90)
                         model confidence = P(|price/value - 1| <= 20%) under
                         that band x sqrt(lens coverage); with agents it is
                         blended with evidence coverage, validation and
                         agreement

  9  Margin of safety    MOS = base + low-confidence add-on + per red flag
                         research buy-below = value x (1 - MOS); label from
                         price / value

Without agents (the valuation report), the signals come from the accounts
themselves - ROIC against k for the moat, cash conversion for earnings
quality, profit volatility, debt, revenue momentum - using only years up to
the one being valued.
"""

import math
import statistics

from agents import settings as S

SECTION = "hybrid_model."
LENSES = ["cash_flow", "earnings_power", "asset", "market", "conservative", "learning"]
LENS_NAMES = {
    "cash_flow": "Cash-flow lens (DCF / RI)",
    "earnings_power": "Earnings-power lens (EPV)",
    "asset": "Asset lens (justified P/B)",
    "market": "Market lens (peer multiples)",
    "conservative": "Conservative lens (Graham)",
    "learning": "Learning lens (ML consensus)",
}
DEFAULT_LENS_WEIGHTS = {
    "mature": {"cash_flow": 1.0, "earnings_power": 0.8, "asset": 0.6, "market": 1.0, "conservative": 0.3, "learning": 0.6},
    "lender": {"cash_flow": 1.0, "earnings_power": 0.8, "asset": 1.0, "market": 0.8, "conservative": 0.4, "learning": 0.5},
    "loss_maker": {"cash_flow": 0.6, "earnings_power": 0.2, "asset": 1.0, "market": 0.4, "conservative": 0.0, "learning": 0.6},
    "young": {"cash_flow": 0.8, "earnings_power": 0.5, "asset": 0.5, "market": 1.2, "conservative": 0.2, "learning": 0.3},
}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _ok(v):
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0


# ======================================================================= params
class Params:
    """
    Settings reader with an optional in-memory overlay.

    The Lab sends {"growth.terminal": 0.045, ...}; those win over the file
    for this one evaluation only. Nothing is written until the user saves.
    """

    def __init__(self, overrides=None):
        self.o = dict(overrides or {})

    def num(self, path, default):
        if path in self.o:
            try:
                return float(self.o[path])
            except (TypeError, ValueError):
                pass
        return S.num(SECTION + path, default)

    def get(self, path, default=None):
        if path in self.o:
            return self.o[path]
        return S.get(SECTION + path, default)

    def section(self, path, default=None):
        base = dict(S.section(SECTION + path) or (default or {}))
        pre = path + "."
        for k, v in self.o.items():
            if k.startswith(pre) and "." not in k[len(pre):]:
                base[k[len(pre):]] = v
        return base


# ================================================================ signals
NEUTRAL = {"risks": {}, "tilts": {}, "quality": {}, "red_flags": [], "conf_parts": {}}


def signals_from_accounts(years, fy, k_hint=0.12):
    """
    Signals from the company's own accounts, point-in-time (years <= fy).
    Used by the valuation report, and as the floor under agent readings.
    """
    ys = sorted(y for y in years if y <= fy and years[y])
    rows = [years[y] for y in ys][-4:]
    out = {"risks": {}, "tilts": {}, "quality": {}, "red_flags": [], "conf_parts": {}}
    if not rows:
        return out
    last = rows[-1]
    tax = last.get("tax_rate") or 0.25

    roics = []
    for d in rows:
        eq, ebit = d.get("equity"), d.get("ebit")
        if eq is None or ebit is None:
            continue
        gross = eq + (d.get("total_debt") or 0)
        inv = max(gross - (d.get("cash") or 0), 0.5 * gross)
        if inv > 0:
            roics.append(ebit * (1 - tax) / inv)
    if roics:
        spread = statistics.median(roics) - k_hint
        stab = 1.0
        if len(roics) >= 3 and statistics.mean(roics) > 0:
            stab = clamp(1 - statistics.pstdev(roics) / statistics.mean(roics), 0, 1)
        out["quality"]["moat"] = math.tanh(spread / 0.08) * (0.5 + 0.5 * stab)

    ni = [d.get("net_income") for d in rows if d.get("net_income") is not None]
    ocf = [d.get("ocf") for d in rows if d.get("ocf") is not None]
    if len(ni) == len(ocf) and ni and sum(ni) > 0:
        conv = sum(ocf) / sum(ni)
        out["quality"]["earnings_quality"] = clamp((conv - 0.8) / 0.4, -1, 1)

    growth = []
    for a, b in zip(rows, rows[1:]):
        if a.get("net_income") and b.get("net_income") and a["net_income"] > 0:
            growth.append(b["net_income"] / a["net_income"] - 1)
    if len(growth) >= 2:
        out["risks"]["earnings_volatility"] = clamp(statistics.pstdev(growth) / 0.5, 0, 1)

    if len(rows) >= 2 and rows[-2].get("revenue") and last.get("revenue"):
        rg = last["revenue"] / rows[-2]["revenue"] - 1
        nominal = S.num("macro.real_gdp_growth", 0.065) + S.num("macro.cpi_inflation", 0.04)
        out["tilts"]["earnings_momentum"] = math.tanh((rg - nominal) / 0.10)

    sh0, sh1 = rows[0].get("shares"), last.get("shares")
    roe = [d["net_income"] / d["equity"] for d in rows if d.get("net_income") is not None and d.get("equity")]
    parts = []
    if len(roe) >= 2:
        parts.append(math.tanh((roe[-1] - roe[0]) / 0.05))
    if sh0 and sh1:
        parts.append(clamp(-(sh1 / sh0 - 1) / 0.05, -1, 0.3))
    if parts:
        out["quality"]["capital_allocation"] = sum(parts) / len(parts)
    return out


def merge_signals(accounts, agents):
    """Agent readings win; the accounts fill whatever the agents left out."""
    if not agents:
        return accounts
    out = {}
    for k in ("risks", "tilts", "quality"):
        out[k] = {**(accounts.get(k) or {}), **{a: b for a, b in (agents.get(k) or {}).items() if b is not None}}
    for k, v in agents.items():
        if k not in out:
            out[k] = v
    out.setdefault("red_flags", [])
    out.setdefault("conf_parts", {})
    return out


# ================================================================ base inputs
def base_from_record(rec, fy, comps=None, price=None, regime=None):
    """
    The formula's company inputs for one company-year, from the calculator's
    own figures (after gap-filling). comps are the Ensemble's component
    Results for the same row: pe_reg, ev_reg, graham, ml.
    """
    import capital
    import model_dcf

    years = rec["data"]["years"]
    d = years.get(fy) or {}
    fys = sorted(y for y, v in years.items() if v and y <= fy)
    tax = d.get("tax_rate") or 0.25
    beta, _ = capital.adjusted_beta(rec)

    series = {y: model_dcf._fcff_quiet(years[y], y) for y in fys}
    recent = [series.get(y) for y in fys][-3:]
    pos = [v for v in recent if v is not None and v > 0]
    nop = [years[y]["ebit"] * (1 - (years[y].get("tax_rate") or tax)) for y in fys[-3:] if years[y].get("ebit") is not None]
    ni = [years[y]["net_income"] for y in fys[-3:] if years[y].get("net_income") is not None]
    roe = [years[y]["net_income"] / years[y]["equity"] for y in fys[-3:]
           if years[y].get("net_income") is not None and years[y].get("equity")]

    g_hist, _ = model_dcf.growth_from_history(series, fy)
    rev = [(y, years[y].get("revenue")) for y in fys if years[y].get("revenue")]
    g_rev = None
    if len(rev) >= 2 and rev[0][1] > 0 and rev[-1][1] > 0 and rev[-1][0] > rev[0][0]:
        g_rev = (rev[-1][1] / rev[0][1]) ** (1 / (rev[-1][0] - rev[0][0])) - 1
    g_base = g_hist if g_rev is None else 0.5 * g_hist + 0.5 * g_rev

    shares = d.get("shares")
    px = price if _ok(price) else d.get("price")
    mcap = px * shares if _ok(px) and _ok(shares) else None
    eq = d.get("equity")

    def cval(k):
        r = (comps or {}).get(k)
        if r is None or not getattr(r, "ok", False) or not _ok(r.value):
            return None
        return float(r.value)

    est = [k for k in ("pe_reg", "ev_reg", "graham", "ml") if (comps or {}).get(k) is not None and getattr(comps[k], "estimated", False)]
    return {
        "sector": rec.get("sector", ""),
        "fy": fy,
        "regime": regime,
        "price": px,
        "shares": shares,
        "debt": d.get("total_debt") or 0.0,
        "cash": d.get("cash") or 0.0,
        "equity_book": eq,
        "tax": tax,
        "beta_adj": beta,
        "fcff_norm": statistics.median(pos) if pos else None,
        "nopat": d["ebit"] * (1 - tax) if d.get("ebit") is not None else None,
        "nopat_norm": statistics.median(nop) if nop else None,
        "ni_norm": statistics.median(ni) if ni else None,
        "roe_norm": statistics.median(roe) if roe else None,
        "g_base": g_base,
        "market_cap": mcap,
        "market_cap_cr": mcap / 1e7 if mcap else None,
        "de_ratio": (d.get("total_debt") or 0.0) / eq if eq and eq > 0 else None,
        "pe_reg": cval("pe_reg"),
        "ev_reg": cval("ev_reg"),
        "graham": cval("graham"),
        "ml": cval("ml"),
        "estimated_components": est,
    }


# ================================================================ steps 1-2
def size_premium(p, market_cap_cr):
    bands = p.get("size_bands") or [
        {"min_cr": 100000, "premium": 0.0}, {"min_cr": 20000, "premium": 0.005},
        {"min_cr": 5000, "premium": 0.015}, {"min_cr": 1000, "premium": 0.025},
        {"min_cr": 0, "premium": 0.03},
    ]
    cap = p.num("premia_caps.size", 0.03)
    if market_cap_cr is None:
        return min(0.015, cap)
    for b in sorted(bands, key=lambda b: -float(b.get("min_cr", 0))):
        if market_cap_cr >= float(b.get("min_cr", 0)):
            return min(float(b.get("premium", 0)), cap)
    return cap


def cost_of_equity(base, sig, p, shift=0.0):
    rf = p.num("risk_free_rate", 0.064)
    erp = p.num("equity_risk_premium", 0.055)
    beta = base.get("beta_adj") or 1.0
    k0 = max(rf + beta * erp, p.num("min_cost_of_equity", 0.10))
    caps = p.section("premia_caps")
    risks = sig.get("risks") or {}
    premia = {"size": size_premium(p, base.get("market_cap_cr"))}
    de = base.get("de_ratio")
    lo, hi = p.num("leverage_free_de", 0.5), p.num("leverage_full_de", 2.5)
    lev = 0.0 if de is None else (clamp((de - lo) / (hi - lo), 0, 1) if hi > lo else float(de > lo))
    premia["leverage"] = float(caps.get("leverage", 0.02)) * lev
    for k in ("liquidity", "governance", "forensic", "macro", "geopolitical", "earnings_volatility"):
        premia[k] = float(caps.get(k, 0.0)) * clamp(float(risks.get(k, 0.0) or 0.0), 0, 1)
    total = min(sum(premia.values()), p.num("max_total_premium", 0.08))
    return k0, k0 + total + shift, premia


def growth(base, sig, k, p, shift=0.0):
    gmin, gmax = p.num("growth.min", 0.02), p.num("growth.max", 0.20)
    g0 = clamp(base.get("g_base") if base.get("g_base") is not None else 0.08, gmin, gmax)
    tilts = {}
    for name, cap in p.section("growth.tilts_caps").items():
        tilts[name] = float(cap) * clamp(float((sig.get("tilts") or {}).get(name, 0.0) or 0.0), -1, 1)
    g = clamp(g0 + sum(tilts.values()) + shift, gmin, gmax)
    nominal = S.num("macro.real_gdp_growth", 0.065) + S.num("macro.cpi_inflation", 0.04)
    gt = min(p.num("growth.terminal", 0.05), nominal + p.num("growth.terminal_cap_over_gdp", 0.0),
             k - p.num("growth.min_spread_k_minus_g", 0.02))
    return g0, g, gt, tilts


def wacc(base, k, p):
    kd = p.num("cost_of_debt_pre_tax", 0.085)
    tax = base.get("tax") or 0.25
    e = base.get("market_cap") or base.get("equity_book") or 0.0
    d = base.get("debt") or 0.0
    if e <= 0:
        return kd * (1 - tax) if d > 0 else k
    return (e * k + d * kd * (1 - tax)) / (e + d)


# ================================================================ step 3: lenses
def lens_cash_flow(base, k, g, gt, moat, p):
    shares = base.get("shares")
    if not _ok(shares):
        return None
    if base.get("regime") == "lender":
        bv, roe = base.get("equity_book"), base.get("roe_norm")
        if not _ok(bv) or roe is None:
            return None
        omega = clamp(p.num("ri_persistence", 0.62), 0, 0.95)
        n = int(p.num("growth.high_growth_years", 5))
        pv, b, ri = 0.0, bv, 0.0
        for i in range(1, n + 1):
            ri = (roe - k) * b
            pv += ri / (1 + k) ** i
            b *= 1 + min(g, max(roe, 0.0))
        tv = ri * omega / (1 + k - omega) / (1 + k) ** n
        v = (bv + pv + tv) / shares
        return v if v > 0 else None

    r = wacc(base, k, p)
    gt = min(gt, r - p.num("growth.min_spread_k_minus_g", 0.02))
    ronic = r + 0.02 + 0.04 * max(0.0, moat)
    observed = base.get("fcff_norm")
    nopat0 = base.get("nopat")
    driver = nopat0 * (1 - g / ronic) if _ok(nopat0) and g < ronic else None
    wd = clamp(p.num("fcff_value_driver_weight", 0.5), 0, 1)
    if _ok(observed) and _ok(driver):
        cf = (1 - wd) * observed + wd * driver
    else:
        cf = observed if _ok(observed) else driver
    if not _ok(cf):
        return None
    n1 = int(p.num("growth.high_growth_years", 5))
    n2 = max(1, int(p.num("growth.fade_years", 5)))
    pv, nop = 0.0, (nopat0 if _ok(nopat0) else None)
    for i in range(1, n1 + n2 + 1):
        gi = g if i <= n1 else g + (gt - g) * (i - n1) / n2
        cf *= 1 + gi
        if nop:
            nop *= 1 + gi
        pv += cf / (1 + r) ** i
    tv = nop * (1 + gt) * (1 - gt / ronic) / (r - gt) if nop else cf * (1 + gt) / (r - gt)
    equity = pv + tv / (1 + r) ** (n1 + n2) - (base.get("debt") or 0) + (base.get("cash") or 0)
    return equity / shares if equity > 0 else None


def lens_earnings_power(base, k, p):
    shares = base.get("shares")
    if not _ok(shares):
        return None
    if base.get("regime") == "lender":
        ni = base.get("ni_norm")
        return ni / k / shares if _ok(ni) else None
    nop = base.get("nopat_norm") or base.get("nopat")
    if not _ok(nop):
        return None
    eq = nop / wacc(base, k, p) - (base.get("debt") or 0) + (base.get("cash") or 0)
    return eq / shares if eq > 0 else None


def lens_asset(base, k, gt, p):
    bv, roe, shares = base.get("equity_book"), base.get("roe_norm"), base.get("shares")
    if not _ok(bv) or roe is None or not _ok(shares):
        return None
    spread = max(k - gt, 0.01)
    lo, hi = p.get("asset_pb_bounds", [0.5, 6.0])
    pb = clamp((roe - gt) / spread, float(lo), float(hi))
    return bv / shares * pb


def lens_market(base):
    vals = [v for v in (base.get("pe_reg"), base.get("ev_reg")) if _ok(v)]
    if base.get("regime") == "lender":
        vals = [base["pe_reg"]] if _ok(base.get("pe_reg")) else []
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def _weighted_median(vals, wts):
    pairs = sorted(zip(vals, wts))
    half, acc = sum(wts) / 2, 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


# ================================================================ steps 3-6
def value_once(base, sig, p, g_shift=0.0, k_shift=0.0, q_shift=0.0):
    k0, k, premia = cost_of_equity(base, sig, p, k_shift)
    g0, g, gt, tilts = growth(base, sig, k, p, g_shift)
    quality = sig.get("quality") or {}
    moat = float(quality.get("moat", 0.0) or 0.0)

    lenses = {
        "cash_flow": lens_cash_flow(base, k, g, gt, moat, p),
        "earnings_power": lens_earnings_power(base, k, p),
        "asset": lens_asset(base, k, gt, p),
        "market": lens_market(base),
        "conservative": base.get("graham") if _ok(base.get("graham")) else None,
        "learning": base.get("ml") if _ok(base.get("ml")) else None,
    }

    # growth-credibility gate
    gate = None
    cf, ep = lenses["cash_flow"], lenses["earnings_power"]
    if _ok(cf) and _ok(ep) and cf > ep:
        allowed = clamp(p.num("gate.base_pvgo_share", 0.45) + p.num("gate.moat_bonus", 0.30) * max(0.0, moat), 0.0, 0.95)
        share = 1 - ep / cf
        if share > allowed:
            capped = ep / (1 - allowed)
            gate = {"pvgo_share": share, "allowed": allowed, "before": cf, "after": capped}
            lenses["cash_flow"] = capped
        else:
            gate = {"pvgo_share": share, "allowed": allowed, "before": cf, "after": cf}

    # calibration: each lens's typical miss in earlier years (point-in-time,
    # computed by the report) is removed, and lenses that have priced well
    # earn more weight
    cal = base.get("lens_calibration") or {}
    if not p.get("calibration.enabled", True):
        cal = {}
    for l, c in cal.items():
        if _ok(lenses.get(l)) and isinstance(c, dict) and c.get("c"):
            lenses[l] *= math.exp(-float(c["c"]))

    regime = base.get("regime") or "mature"
    table = p.section(f"lens_weights.{regime}", DEFAULT_LENS_WEIGHTS.get(regime, DEFAULT_LENS_WEIGHTS["mature"]))
    applicable = [l for l in LENSES if float(table.get(l, 0) or 0) > 0]
    if not p.get("use_learning_lens", True):
        applicable = [l for l in applicable if l != "learning"]
    used = [l for l in applicable if _ok(lenses.get(l))]
    penalty = p.num("estimate_penalty", 0.75)
    est = set(base.get("estimated_components") or [])
    est_map = {"market": {"pe_reg", "ev_reg"}, "conservative": {"graham"}, "learning": {"ml"}}
    raw = {}
    for l in used:
        w = float(table.get(l, 0))
        if est_map.get(l, set()) & est:
            w *= penalty
        if p.get("calibration.skill_weighting", True) and isinstance(cal.get(l), dict):
            w *= float(cal[l].get("skill", 1.0) or 1.0)
        raw[l] = w

    dropped = []
    if len(used) >= 3:
        logs = {l: math.log(lenses[l]) for l in used}
        centre = _weighted_median([logs[l] for l in used], [raw[l] for l in used])
        lim = math.log(max(1.1, p.num("outlier_ratio", 3.0)))
        dropped = [l for l in used if abs(logs[l] - centre) > lim]
        if len(dropped) < len(used):
            used = [l for l in used if l not in dropped]
        else:
            dropped = []

    tw = sum(raw[l] for l in used)
    if not used or tw <= 0:
        core, weights, disp = None, {}, None
    else:
        weights = {l: raw[l] / tw for l in used}
        c = sum(weights[l] * math.log(lenses[l]) for l in used)
        core = math.exp(c)
        disp = math.sqrt(sum(weights[l] * (math.log(lenses[l]) - c) ** 2 for l in used))

    qcaps = p.section("quality_caps")
    q_terms = {n: float(cap) * clamp(float(quality.get(n, 0.0) or 0.0), -1, 1) for n, cap in qcaps.items()}
    lo, hi = p.get("quality_bounds", [0.75, 1.25])
    q = clamp(1 + sum(q_terms.values()) + q_shift, float(lo), float(hi))
    n_flags = len(sig.get("red_flags") or [])
    h = min(n_flags * p.num("governance.haircut_per_red_flag", 0.05), p.num("governance.max_haircut", 0.30))
    value = core * q * (1 - h) if core else None
    return {
        "k0": k0, "k": k, "premia": premia, "g0": g0, "g": g, "g_terminal": gt, "tilts": tilts,
        "lenses": lenses, "weights": weights, "dropped": dropped, "gate": gate, "calibration": cal,
        "applicable": applicable, "dispersion": disp, "core": core,
        "q": q, "q_terms": q_terms, "haircut": h, "red_flags": n_flags, "value": value,
    }


# ================================================================ steps 7-9
def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def evaluate(base, sig=None, params=None):
    """The whole HYBRID MODEL. -> dict with value, band, confidence, waterfall."""
    p = params if isinstance(params, Params) else Params(params)
    sig = sig or NEUTRAL
    sc = p.section("scenarios")
    bull_s, bear_s = sc.get("bull") or {}, sc.get("bear") or {}

    b = value_once(base, sig, p)
    bull = value_once(base, sig, p,
                      g_shift=p.num("scenarios.bull.growth_shift", float(bull_s.get("growth_shift", 0.02))),
                      k_shift=p.num("scenarios.bull.rate_shift", float(bull_s.get("rate_shift", -0.01))),
                      q_shift=p.num("scenarios.bull.quality_shift", float(bull_s.get("quality_shift", 0.05))))
    bear = value_once(base, sig, p,
                      g_shift=p.num("scenarios.bear.growth_shift", float(bear_s.get("growth_shift", -0.03))),
                      k_shift=p.num("scenarios.bear.rate_shift", float(bear_s.get("rate_shift", 0.015))),
                      q_shift=p.num("scenarios.bear.quality_shift", float(bear_s.get("quality_shift", -0.08))))

    pb = p.num("scenarios.probabilities.bull", 0.25)
    pm = p.num("scenarios.probabilities.base", 0.50)
    pr = p.num("scenarios.probabilities.bear", 0.25)
    tilt = p.num("scenarios.max_probability_tilt", 0.10) * (
        clamp(float(sig.get("bull_conviction", 0) or 0), 0, 1) - clamp(float(sig.get("bear_conviction", 0) or 0), 0, 1))
    pb, pr = max(0.0, pb + tilt), max(0.0, pr - tilt)
    tot = (pb + pm + pr) or 1.0
    probs = {"bull": pb / tot, "base": pm / tot, "bear": pr / tot}

    vals = {"bull": bull["value"], "base": b["value"], "bear": bear["value"]}
    value = None
    if b["value"]:
        avail = {s: v for s, v in vals.items() if v}
        pt = sum(probs[s] for s in avail)
        value = sum(probs[s] * v for s, v in avail.items()) / pt
        ow = p.num("overlay_weight", 0.0)
        value *= 1 + ow * clamp(float(sig.get("overlay", 0) or 0), -1, 1)

    # uncertainty and confidence
    base_sigma = p.num("base_sigma", 0.20)
    sigma = math.sqrt((b["dispersion"] or 0.0) ** 2 + base_sigma ** 2)
    tol = p.num("confidence_tolerance", 0.20)
    p_within = _phi(math.log(1 + tol) / sigma) - _phi(math.log(1 - tol) / sigma)
    coverage = len(b["weights"]) / max(1, len(b["applicable"]))
    model_conf = 100 * p_within * math.sqrt(coverage)
    parts = dict(sig.get("conf_parts") or {})
    if parts:
        cw = p.section("confidence_weights", {"model": 0.4, "evidence_coverage": 0.2, "validation": 0.25, "agreement": 0.15})
        parts["model"] = model_conf / 100
        pairs = [(clamp(float(parts.get(k, 0) or 0), 0, 1), float(w)) for k, w in cw.items()]
        tw = sum(w for _, w in pairs) or 1.0
        confidence = 100 * sum(x * w for x, w in pairs) / tw
    else:
        confidence = model_conf
        parts = {"model": model_conf / 100}
    if value is None:
        confidence *= 0.5

    low = value * math.exp(-1.2816 * sigma) if value else None
    high = value * math.exp(1.2816 * sigma) if value else None

    n_flags = b["red_flags"]
    mos = min(p.num("margin_of_safety.base", 0.15)
              + p.num("margin_of_safety.per_low_confidence", 0.15) * (1 - confidence / 100)
              + p.num("margin_of_safety.per_red_flag", 0.03) * n_flags,
              p.num("margin_of_safety.max", 0.45))
    buy_below = value * (1 - mos) if value else None
    price = base.get("price")

    if n_flags >= p.num("labels.red_flags_for_avoid", 3):
        label = "Avoid - red flags"
    elif not value or not _ok(price) or confidence < p.num("labels.min_confidence_for_label", 25):
        label = "Insufficient evidence"
    else:
        r = price / value
        label = ("Deep value" if r < p.num("labels.deep_value_below", 0.65)
                 else "Undervalued" if r < p.num("labels.undervalued_below", 0.90)
                 else "Overvalued" if r > p.num("labels.overvalued_above", 1.15)
                 else "Fairly valued")

    waterfall = [{"step": LENS_NAMES[l], "value": b["lenses"].get(l),
                  "note": (f"weight {b['weights'][l]:.0%}" if l in b["weights"]
                           else "dropped as outlier" if l in b["dropped"]
                           else "not applicable" if l not in b["applicable"] else "no value")}
                 for l in LENSES]
    if b["gate"] and b["gate"]["after"] < b["gate"]["before"]:
        waterfall.insert(1, {"step": "Growth-credibility gate", "value": b["gate"]["after"],
                             "note": f"growth share {b['gate']['pvgo_share']:.0%} > allowed {b['gate']['allowed']:.0%}"})
    waterfall += [
        {"step": "Blended core value", "value": b["core"], "note": "weighted geometric mean of the lenses"},
        {"step": "After quality multiplier", "value": b["core"] * b["q"] if b["core"] else None, "note": f"Q = {b['q']:.3f}"},
        {"step": "After governance haircut", "value": b["value"], "note": f"H = {b['haircut']:.0%} for {n_flags} red flag(s)"},
        {"step": "Bear case", "value": bear["value"], "note": f"p = {probs['bear']:.0%}"},
        {"step": "Bull case", "value": bull["value"], "note": f"p = {probs['bull']:.0%}"},
        {"step": "HYBRID MODEL value", "value": value, "note": "probability-weighted bull / base / bear"},
        {"step": "Research buy-below", "value": buy_below, "note": f"margin of safety {mos:.0%}"},
    ]

    return {
        "value": value, "low": low, "high": high,
        "base_value": b["value"], "bull_value": bull["value"], "bear_value": bear["value"],
        "probabilities": probs, "confidence": clamp(confidence, 0, 100), "confidence_parts": parts,
        "model_confidence": model_conf, "sigma": sigma,
        "buy_below": buy_below, "margin_of_safety": mos, "label": label, "price": price,
        "upside": (value / price - 1) if value and _ok(price) else None,
        "cost_of_equity": b["k"], "cost_of_equity_capm": b["k0"], "premia": b["premia"],
        "growth": b["g"], "growth_base": b["g0"], "growth_terminal": b["g_terminal"], "growth_tilts": b["tilts"],
        "lenses": b["lenses"], "lens_weights": b["weights"], "lenses_dropped": b["dropped"],
        "lenses_applicable": b["applicable"], "gate": b["gate"], "core_value": b["core"],
        "lens_calibration": {l: math.exp(-c["c"]) for l, c in b["calibration"].items() if isinstance(c, dict) and c.get("c")},
        "quality_multiplier": b["q"], "quality_terms": b["q_terms"],
        "governance_haircut": b["haircut"], "red_flag_count": n_flags,
        "regime": base.get("regime"), "waterfall": waterfall,
    }


# ================================================================ the Lab
# What the web app's Hybrid Model Lab shows, in order. One list, so the
# backend, the settings file and the UI cannot drift apart.
PARAM_SCHEMA = [
    {"group": "Cost of equity", "params": [
        ("risk_free_rate", "Risk-free rate", "pct", 0.0, 0.15, "India 10-year government bond yield."),
        ("equity_risk_premium", "Equity risk premium", "pct", 0.0, 0.12, "Extra return investors demand for owning equities."),
        ("min_cost_of_equity", "Cost-of-equity floor", "pct", 0.0, 0.20, "No company is discounted below this, whatever its beta."),
        ("cost_of_debt_pre_tax", "Cost of debt (pre-tax)", "pct", 0.0, 0.20, None),
        ("max_total_premium", "Cap on all premia", "pct", 0.0, 0.20, None),
    ]},
    {"group": "Risk premia (cap × agent risk)", "params": [
        ("premia_caps.liquidity", "Liquidity", "pct", 0.0, 0.06, None),
        ("premia_caps.governance", "Governance", "pct", 0.0, 0.08, "Insider selling, pledges, promotion, short reports."),
        ("premia_caps.forensic", "Forensic", "pct", 0.0, 0.08, "Beneish, Altman, accruals, cash conversion."),
        ("premia_caps.leverage", "Leverage", "pct", 0.0, 0.06, None),
        ("premia_caps.macro", "Macro", "pct", 0.0, 0.05, None),
        ("premia_caps.geopolitical", "Geopolitical", "pct", 0.0, 0.06, None),
        ("premia_caps.earnings_volatility", "Earnings volatility", "pct", 0.0, 0.05, None),
        ("premia_caps.size", "Size (maximum)", "pct", 0.0, 0.06, None),
    ]},
    {"group": "Growth", "params": [
        ("growth.min", "Minimum growth", "pct", -0.05, 0.10, None),
        ("growth.max", "Maximum growth", "pct", 0.05, 0.40, None),
        ("growth.terminal", "Terminal growth", "pct", 0.0, 0.08, "Long-run growth after the fade."),
        ("growth.high_growth_years", "High-growth years", "int", 1, 15, None),
        ("growth.fade_years", "Fade years", "int", 1, 15, None),
        ("growth.min_spread_k_minus_g", "Minimum k − g spread", "pct", 0.005, 0.06, None),
        ("growth.tilts_caps.industry_tailwind", "Industry tilt (cap)", "pct", 0.0, 0.05, None),
        ("growth.tilts_caps.earnings_momentum", "Momentum tilt (cap)", "pct", 0.0, 0.05, None),
        ("growth.tilts_caps.news_impact", "News tilt (cap)", "pct", 0.0, 0.04, None),
        ("growth.tilts_caps.macro_growth", "Macro tilt (cap)", "pct", 0.0, 0.03, None),
    ]},
    {"group": "Lens weights · mature companies", "params": [
        (f"lens_weights.mature.{l}", LENS_NAMES[l], "num", 0.0, 2.0, None) for l in LENSES]},
    {"group": "Lens weights · banks & lenders", "params": [
        (f"lens_weights.lender.{l}", LENS_NAMES[l], "num", 0.0, 2.0, None) for l in LENSES]},
    {"group": "Lens weights · loss-makers", "params": [
        (f"lens_weights.loss_maker.{l}", LENS_NAMES[l], "num", 0.0, 2.0, None) for l in LENSES]},
    {"group": "Lens weights · young companies", "params": [
        (f"lens_weights.young.{l}", LENS_NAMES[l], "num", 0.0, 2.0, None) for l in LENSES]},
    {"group": "Calibration (learning from earlier years)", "params": [
        ("calibration.enabled", "Remove each lens's past bias", "bool", 0, 1, "Learned point-in-time from earlier years' misses."),
        ("calibration.skill_weighting", "Weight lenses by past accuracy", "bool", 0, 1, None),
        ("calibration.shrink_k", "Evidence needed to trust history", "int", 1, 50, "Observations needed to move halfway from neutral."),
        ("calibration.min_obs", "Minimum history per lens", "int", 2, 30, None),
    ]},
    {"group": "Lens mechanics", "params": [
        ("gate.base_pvgo_share", "Growth share allowed (base)", "pct", 0.0, 0.95, "Share of the cash-flow value that may come from growth."),
        ("gate.moat_bonus", "Extra growth share per unit of moat", "pct", 0.0, 0.6, None),
        ("fcff_value_driver_weight", "Value-driver share of starting FCFF", "num", 0.0, 1.0, "0 = observed cash flow, 1 = NOPAT × (1 − g/RONIC)."),
        ("ri_persistence", "Residual-income persistence", "num", 0.0, 0.95, "Lenders' cash-flow lens."),
        ("outlier_ratio", "Outlier lens ratio", "num", 1.5, 10.0, "Lenses further than this multiple from the centre are dropped."),
        ("estimate_penalty", "Weight on estimated inputs", "num", 0.0, 1.0, None),
    ]},
    {"group": "Quality & governance", "params": [
        ("quality_caps.moat", "Moat (cap)", "pct", 0.0, 0.25, None),
        ("quality_caps.earnings_quality", "Earnings quality (cap)", "pct", 0.0, 0.2, None),
        ("quality_caps.financial_strength", "Financial strength (cap)", "pct", 0.0, 0.15, None),
        ("quality_caps.capital_allocation", "Capital allocation (cap)", "pct", 0.0, 0.1, None),
        ("governance.haircut_per_red_flag", "Haircut per red flag", "pct", 0.0, 0.2, None),
        ("governance.max_haircut", "Maximum haircut", "pct", 0.0, 0.6, None),
    ]},
    {"group": "Scenarios", "params": [
        ("scenarios.probabilities.bull", "Bull probability", "num", 0.0, 1.0, None),
        ("scenarios.probabilities.base", "Base probability", "num", 0.0, 1.0, None),
        ("scenarios.probabilities.bear", "Bear probability", "num", 0.0, 1.0, None),
        ("scenarios.max_probability_tilt", "Max conviction tilt", "num", 0.0, 0.3, None),
        ("scenarios.bull.growth_shift", "Bull growth shift", "pct", 0.0, 0.08, None),
        ("scenarios.bull.rate_shift", "Bull discount-rate shift", "pct", -0.05, 0.0, None),
        ("scenarios.bear.growth_shift", "Bear growth shift", "pct", -0.10, 0.0, None),
        ("scenarios.bear.rate_shift", "Bear discount-rate shift", "pct", 0.0, 0.06, None),
    ]},
    {"group": "Uncertainty, safety & labels", "params": [
        ("base_sigma", "Base uncertainty (σ)", "num", 0.05, 0.6, "Added to the lenses' disagreement."),
        ("confidence_tolerance", "Confidence tolerance", "pct", 0.05, 0.5, "Confidence = chance the price lands within this of the value."),
        ("margin_of_safety.base", "Base margin of safety", "pct", 0.0, 0.5, None),
        ("margin_of_safety.per_low_confidence", "Added at zero confidence", "pct", 0.0, 0.4, None),
        ("margin_of_safety.per_red_flag", "Added per red flag", "pct", 0.0, 0.1, None),
        ("margin_of_safety.max", "Maximum margin of safety", "pct", 0.1, 0.8, None),
        ("labels.deep_value_below", "Deep value below (price ÷ value)", "num", 0.3, 1.0, None),
        ("labels.undervalued_below", "Undervalued below", "num", 0.5, 1.0, None),
        ("labels.overvalued_above", "Overvalued above", "num", 1.0, 2.0, None),
    ]},
]

SENSITIVITY = [
    ("equity_risk_premium", 0.01), ("risk_free_rate", 0.005), ("min_cost_of_equity", 0.01),
    ("growth.terminal", 0.005), ("growth.high_growth_years", 2), ("growth.max", 0.03),
    ("gate.base_pvgo_share", 0.10), ("fcff_value_driver_weight", 0.25),
    ("quality_caps.moat", 0.05), ("governance.haircut_per_red_flag", 0.03),
    ("base_sigma", 0.05), ("scenarios.bear.growth_shift", 0.01),
]


def schema_with_values(overrides=None):
    p = Params(overrides)
    out = []
    for g in PARAM_SCHEMA:
        rows = []
        for path, label, kind, lo, hi, desc in g["params"]:
            if path.startswith("lens_weights."):
                _, regime, lens = path.split(".")
                cur = p.section(f"lens_weights.{regime}", DEFAULT_LENS_WEIGHTS[regime]).get(lens)
            else:
                cur = p.get(path, None)
            rows.append({"path": path, "label": label, "kind": kind, "min": lo, "max": hi,
                         "desc": desc, "value": cur, "in_file": S.get(SECTION + path, None) is not None})
        out.append({"group": g["group"], "params": rows})
    return out


def lens_calibration(hist, sector, fy, params=None):
    """
    hist: [(sector, fy, lens, ln(V / benchmark))] over the whole report.
    -> {lens: {"c": log correction, "skill": relative weight, "n": obs}}
    using only rows strictly before fy - same rule as the Ensemble.
    """
    p = params if isinstance(params, Params) else Params(params)
    need = int(p.num("calibration.min_obs", 4))
    k = p.num("calibration.shrink_k", 10)
    stats = {}
    for lens in LENSES:
        errs = [e for s, f, l, e in hist if l == lens and f < fy and s == sector]
        if len(errs) < need:
            errs = [e for s, f, l, e in hist if l == lens and f < fy]
        if len(errs) < need:
            continue
        n = len(errs)
        lam = n / (n + k)
        c = lam * statistics.median(errs)
        scale = statistics.median(abs(e - c) for e in errs)
        stats[lens] = (c, scale, n)
    if not stats:
        return {}
    skills = {l: 1.0 / (s * s + 1e-4) for l, (c, s, n) in stats.items()}
    mean = statistics.mean(skills.values())
    out = {}
    for l, (c, s, n) in stats.items():
        lam = n / (n + k)
        out[l] = {"c": c, "skill": lam * (skills[l] / mean) + (1 - lam), "n": n}
    return out


def sensitivity(base, sig, overrides=None):
    """Tornado: change in the HYBRID MODEL value for +/- one step of each knob."""
    p0 = Params(overrides)
    v0 = evaluate(base, sig, p0)["value"]
    if not v0:
        return []
    out = []
    for path, step in SENSITIVITY:
        cur = p0.num(path, 0.0)
        res = {}
        for sign in (-1, 1):
            o = dict(p0.o)
            o[path] = cur + sign * step
            v = evaluate(base, sig, Params(o))["value"]
            res[sign] = (v / v0 - 1) if v else None
        out.append({"path": path, "step": step, "down": res[-1], "up": res[1]})
    out.sort(key=lambda r: -max(abs(r["down"] or 0), abs(r["up"] or 0)))
    return out
