# FILE: src/models/model_ensemble.py
"""
Ensemble intrinsic value (formerly 'Hybrid') - an applicability-gated, error-weighted ensemble with
an uncertainty band.

    Hybrid = exp( SUM_k  w_k x ln(V_k) )        over the components k that apply

It draws on every method in the project, but not by averaging their raw
outputs. Each of the original models has a known failure mode; the hybrid
carries an UPGRADED version of each component that addresses it, decides which
components apply to the company in front of it, and weights the survivors by
how accurately each has actually priced that sector in earlier years.

LAYER 1 - REGIME GATE (which methods fit this company-year?)

    lender      sector names a bank / NBFC / insurer      -> no DCF, no EV/EBITDA
    loss_maker  EPS or net income <= 0 this year          -> P/E and Graham damped
    young       first traded inside the window, < 2 years -> DCF and ML damped
    mature      everything else                           -> all components

    The multipliers live in config.HYBRID_REGIME_WEIGHTS. A zero removes the
    component outright; that is how "DCF does not apply to banks" becomes a
    rule rather than a hope.

LAYER 2 - UPGRADED COMPONENTS (fix each model's own weakness)

    DCF+        three-stage FCFF. Growth starts from a blend of the
                fundamental rate (reinvestment rate x ROIC) and the historical
                CAGR, holds for PROJECTION_YEARS, then FADES linearly to the
                terminal rate over HYBRID_FADE_YEARS. The terminal value uses
                the value-driver formula
                    TV = NOPAT x (1 + g)(1 - g / RONIC) / (WACC - g)
                which charges the reinvestment growth requires. The original
                Gordon TV assumes growth is free, which is why terminal value
                ran to 70-85% of EV. Discounted on the ADJUSTED beta.
    RI          Residual Income on normalised ROE (model_residual_income).
                Anchored on book value, so it values banks and loss-makers.
    P/E-reg     the benchmark P/E is PREDICTED from ROE, growth and leverage
                by a ridge regression over every company (point-in-time,
                year-demeaned), then blended with the sector median. A thin
                sector borrows strength from the whole sample instead of
                collapsing to one or two peers.
    EV-reg      the same for EV/EBITDA, on EBITDA margin, growth, leverage.
    Graham      unchanged - the conservative anchor.
    ML          geometric mean of whichever learners ran. One vote, not four:
                the four learners share features and labels, so counting them
                separately would let correlated errors dominate.

LAYER 3 - CALIBRATION AND LEARNED WEIGHTS (trust what has worked, point-in-time)

    For row (company, FY t) and component k, the error history is every
    earlier row (FY < t) where k produced a value and a benchmark exists:
        e = ln(V_k / benchmark)                       (signed)
    The sector's history is used when it holds HYBRID_MIN_ERR_OBS points,
    otherwise the whole sample's.

    Calibration (HYBRID_BIAS_CORRECT): a component that has always priced
    40% low - the Graham Number is a ceiling by design; DCF and RI carry
    whatever bias their assumptions impose - is shifted by its own median
    miss, shrunk by evidence: c_k = lambda_k x median(e). It keeps what it
    knows about RELATIVE value and stops dragging the level.

    Skill is then judged on the error that REMAINS after that correction,
    s_k = median |e - c_k|, so a half-corrected bias is still charged for.
    skill_k = 1 / s_k^2, expressed relative to the average skill, then
    SHRUNK toward 1 by its own evidence:
        lambda_k = n_k / (n_k + HYBRID_SHRINK_K)
        raw_k    = lambda_k x relative_skill_k + (1 - lambda_k) x 1
    so a component with three lucky years cannot seize the blend. The raw
    weight is multiplied by the regime multiplier and by HYBRID_ESTIMATE_
    PENALTY when the component itself rests on estimated inputs, then the
    weights are normalised to sum to one. With no history at all - the first
    year of any run - this reduces to the regime-weighted equal mix, which
    the forecasting literature finds very hard to beat.

    The benchmark of FY t-1 is the close near 1 May of year t-1, inside FY t,
    so it is known before FY t closes. No future information enters a weight.

    Robust guard: with three or more components, any whose log-value sits
    more than ln(HYBRID_OUTLIER_RATIO) from the weighted median is dropped
    before blending. One exploding DCF cannot drag the answer.

    Blending in LOG space makes the hybrid a weighted geometric mean, so a
    model that is 3x too high and one that is 3x too low cancel, as they
    should for a quantity that is naturally multiplicative.

LAYER 4 - UNCERTAINTY (say how sure, not just what)

    Each component's error scale is sigma_k = 1.4826 x median e (the robust
    standard deviation), or HYBRID_DEFAULT_SIGMA without history. A Monte
    Carlo of HYBRID_MC_DRAWS draws perturbs every component with errors
    correlated at HYBRID_ERROR_CORR, adds the models' own disagreement, and
    reads off the 10th and 90th percentiles.

    The confidence score (0-100) is a PROBABILITY: the simulated chance that
    the market price lands within +/- HYBRID_CONF_TOLERANCE (20%) of the
    hybrid value, discounted when applicable components could not report or
    weight rests on estimated inputs. "High" (>= 60) therefore means "better
    than a 60% chance of being within 20%" - and because it is a probability,
    the realised hit rate printed after a run checks it.

WHAT IT CANNOT DO

It cannot see data the source never supplied, cannot know the future, and
its weights reward closeness to the 1-May market price - so it inherits the
study's own definition of "accurate". Those are stated, not hidden: every
row's regime, weights, band and confidence land in Ensemble_Detail.csv.
"""

import csv
import logging
import math
import statistics

import numpy as np

import config
import capital
import estimation
import model_dcf
import model_ev_ebitda
import model_graham
import model_pe
import model_residual_income
from plain_reasons import LENDER_HINTS
from result import Result, R, require
from fy_utils import num, clamp, fy_label

log = logging.getLogger(__name__)

KEY = "ensemble"
NAME = "Ensemble"
COLUMN = "(Ensemble) Intrinsic Value"

COMPONENTS = ["dcf_plus", "ri", "pe_reg", "ev_reg", "graham", "ml"]
COMPONENT_NAMES = {
    "dcf_plus": "DCF+",
    "ri": "Residual Income",
    "pe_reg": "P/E (regression)",
    "ev_reg": "EV/EBITDA (regression)",
    "graham": "Graham",
    "ml": "ML consensus",
}

DETAIL_FILE = "Ensemble_Detail.csv"


# =============================================================== regime gate
def regime(rec, fy):
    """-> 'lender' | 'loss_maker' | 'young' | 'mature'"""
    sector = (rec.get("sector") or "").lower()
    # "Financial Technology" matches the "financ" hint, but platforms such as
    # PB Fintech and Paytm report ordinary operating accounts - DCF and
    # EV/EBITDA apply to them, so they must not be gated out as lenders.
    if any(h in sector for h in LENDER_HINTS) and "technolog" not in sector:
        return "lender"

    years = rec["data"]["years"]
    d = years.get(fy) or {}
    eps, ni = d.get("eps"), d.get("net_income")
    if (eps is not None and eps <= 0) or (ni is not None and ni <= 0):
        return "loss_maker"

    priced = sorted(y for y, v in years.items() if (v or {}).get("price"))
    if priced and priced[0] > min(config.FY_LIST) and fy - priced[0] < 2:
        return "young"
    return "mature"


def regime_multiplier(reg, comp):
    table = getattr(config, "HYBRID_REGIME_WEIGHTS", {})
    return float(table.get(reg, {}).get(comp, 1.0))


# =================================================================== DCF+
def dcf_plus(rec, fy):
    years = rec["data"]["years"]
    d = years.get(fy)
    if not d:
        return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

    shares, err = require(d, "shares", fy, "shares outstanding")
    if err:
        return err
    if shares <= 0:
        return Result.bad(R.NOT_MEANINGFUL, f"share count reported as {shares:,.0f}")

    base, err = model_dcf.fcff(d, fy)
    if err:
        return err

    series = {y: model_dcf._fcff_quiet(v, y) for y, v in years.items()}
    notes = []
    if base <= 0:
        pos = [v for y, v in series.items() if y <= fy and v is not None and v > 0]
        if len(pos) < 2:
            return Result.bad(
                R.NOT_MEANINGFUL,
                f"FCFF for FY{fy} is negative and fewer than two positive years "
                f"exist to normalise against",
            )
        base = statistics.median(pos)
        notes.append(f"normalised FCFF (median of {len(pos)} positive years)")

    tax = d.get("tax_rate") or config.DEFAULT_TAX_RATE
    beta, _ = capital.adjusted_beta(rec)
    r = model_dcf.wacc(d, beta)
    gt = getattr(config, "HYBRID_TERMINAL_GROWTH", None) or config.TERMINAL_GROWTH
    gt = min(gt, r - config.WACC_SPREAD_OVER_G)

    # ---- growth: fundamental (reinvestment x ROIC) blended with history ----
    ebit = d.get("ebit")
    nopat = ebit * (1 - tax) if ebit is not None else None
    eq = d.get("equity")
    invested = None
    if eq is not None:
        invested = eq + (d.get("total_debt") or 0.0) - (d.get("cash") or 0.0)
    g_fund = None
    if nopat and nopat > 0 and invested and invested > 0:
        capex, da = d.get("capex"), d.get("da")
        if capex is not None and da is not None:
            roic = nopat / invested
            reinv = (capex - da + (d.get("delta_nwc") or 0.0)) / nopat
            g_fund = clamp(reinv * roic, config.MIN_GROWTH, config.MAX_GROWTH)
    g_hist, _ = model_dcf.growth_from_history(series, fy)
    g0 = g_hist if g_fund is None else (g_fund + g_hist) / 2
    g0 = clamp(g0, config.MIN_GROWTH, config.MAX_GROWTH)

    # ---- three stages: hold, fade, value-driver terminal ----
    n1 = config.PROJECTION_YEARS
    n2 = getattr(config, "HYBRID_FADE_YEARS", 5)
    pv, cf = 0.0, base
    nop = nopat if (nopat and nopat > 0) else None
    for i in range(1, n1 + n2 + 1):
        g_i = g0 if i <= n1 else g0 + (gt - g0) * (i - n1) / n2
        cf *= 1 + g_i
        if nop:
            nop *= 1 + g_i
        pv += cf / (1 + r) ** i
    horizon = n1 + n2

    if nop:
        ronic = r + getattr(config, "HYBRID_RONIC_PREMIUM", 0.02)
        tv = nop * (1 + gt) * (1 - gt / ronic) / (r - gt)
    else:
        tv = cf * (1 + gt) / (r - gt)
        notes.append("Gordon terminal value (EBIT unavailable for value-driver)")
    ev = pv + tv / (1 + r) ** horizon

    net_debt = (d.get("total_debt") or 0.0) - (d.get("cash") or 0.0)
    equity = ev - net_debt
    if equity <= 0:
        return Result.bad(
            R.NEG_EQUITY,
            f"enterprise value {config.CURRENCY_SYMBOL}{ev:,.0f} is below net debt "
            f"{config.CURRENCY_SYMBOL}{net_debt:,.0f}",
        )
    val = num(equity / shares)
    if val is None:
        return Result.bad(R.CALC_ERROR, "final per-share value was NaN/Inf")

    field_method = estimation.method_of(
        d, "ebit", "da", "capex", "ocf", "shares", "total_debt", "cash"
    )
    method = "; ".join(x for x in (*notes, field_method) if x) or None
    return Result.good(val, method=method)


# ===================================================== regression multiples
def _growth(curr, prev):
    if curr is None or prev is None or prev <= 0:
        return None
    return clamp((curr - prev) / prev, -0.5, 1.0)


def _leverage(d):
    eq = d.get("equity")
    if not eq or eq <= 0:
        return None
    return clamp((d.get("total_debt") or 0.0) / eq, 0.0, 5.0)


def _pe_features(years, fy):
    d, prev = years.get(fy) or {}, years.get(fy - 1) or {}
    eq, ni = d.get("equity"), d.get("net_income")
    roe = clamp(ni / eq, -0.5, 0.6) if (ni is not None and eq and eq > 0) else None
    g = _growth(d.get("revenue"), prev.get("revenue"))
    lev = _leverage(d)
    x = [roe, g, lev]
    return None if any(v is None for v in x) else x


def _ev_features(years, fy):
    d, prev = years.get(fy) or {}, years.get(fy - 1) or {}
    rev, ebitda = d.get("revenue"), d.get("ebitda")
    margin = clamp(ebitda / rev, -0.5, 0.8) if (ebitda is not None and rev and rev > 0) else None
    g = _growth(rev, prev.get("revenue"))
    lev = _leverage(d)
    x = [margin, g, lev]
    return None if any(v is None for v in x) else x


class MultipleRegression:
    """
    Pooled, year-demeaned ridge regression of ln(multiple) on fundamentals.

    For FY t it trains on every company-year with FY <= t except the company
    being valued. Each year's median ln(multiple) is subtracted first, so the
    regression learns how a company's fundamentals move it RELATIVE to its
    year, and the FY t median is added back at prediction. That pools all
    available years without letting a market-wide re-rating masquerade as a
    fundamental effect.
    """

    def __init__(self, universe, observe, features):
        self.obs = []  # (name, fy, x, ln_multiple)
        for name, rec in universe.items():
            years = rec["data"]["years"]
            for fy, d in years.items():
                m = observe(d)
                x = features(years, fy)
                if m is None or m <= 0 or x is None:
                    continue
                self.obs.append((name, fy, x, math.log(m)))
        self.year_med = {}
        by_year = {}
        for _, fy, _, lm in self.obs:
            by_year.setdefault(fy, []).append(lm)
        self.year_med = {fy: statistics.median(v) for fy, v in by_year.items()}
        self.features = features

    def predict(self, company, years, fy):
        """-> ln(multiple) or None."""
        x0 = self.features(years, fy)
        if x0 is None or fy not in self.year_med:
            return None
        train = [
            (x, lm - self.year_med[f])
            for n, f, x, lm in self.obs
            if f <= fy and n != company and f in self.year_med
        ]
        if len(train) < getattr(config, "HYBRID_REG_MIN_OBS", 8):
            return None
        X = np.array([t[0] for t in train], dtype=float)
        y = np.array([t[1] for t in train], dtype=float)
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1.0
        Z = (X - mu) / sd
        z0 = (np.array(x0, dtype=float) - mu) / sd
        lam = getattr(config, "HYBRID_RIDGE_LAMBDA", 1.0)
        ym = y.mean()
        coef = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - ym))
        return float(ym + z0 @ coef + self.year_med[fy])


def _blend_multiple(reg_log, peers, company, lo_hi):
    """Regression prediction blended with the ex-self sector median."""
    ex_self = [v for k, v in peers.items() if k != company and v > 0]
    sector_log = (
        math.log(statistics.median(ex_self))
        if len(ex_self) >= config.MIN_PEERS_FOR_MEDIAN
        else None
    )
    a = getattr(config, "HYBRID_REG_BLEND", 0.5)
    if reg_log is not None and sector_log is not None:
        m, how = math.exp(a * reg_log + (1 - a) * sector_log), "regression + sector median"
    elif reg_log is not None:
        m, how = math.exp(reg_log), "regression (sector too thin for a median)"
    elif sector_log is not None:
        m, how = math.exp(sector_log), "sector median (regression had too few points)"
    else:
        return None, None
    lo, hi = lo_hi
    return clamp(m, lo, hi), how


def pe_reg(ctx, name, rec, fy):
    years = rec["data"]["years"]
    d = years.get(fy)
    if not d:
        return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")
    eps, err = require(d, "eps", fy, "EPS")
    if err:
        return err
    notes = []
    if eps <= 0:
        norm, n = estimation.normalised(years, fy, "eps")
        if norm is None:
            return Result.bad(R.NOT_MEANINGFUL, f"EPS for FY{fy} is not positive")
        eps = norm
        notes.append(f"normalised EPS (median of {n} positive years)")

    peers = ctx["pe_table"].get((rec["sector"], fy), {})
    mult, how = _blend_multiple(
        ctx["pe_model"].predict(name, years, fy), peers, name, config.PE_BOUNDS
    )
    if mult is None:
        bench, bm, err = model_pe.benchmark_pe(
            ctx["pe_table"], ctx["universe"], rec["sector"], fy, name
        )
        if err:
            return err
        mult, how = bench, bm or "sector median"
    if how != "regression + sector median":
        notes.append(f"P/E from {how}")
    method = "; ".join(
        x for x in (*notes, estimation.method_of(d, "eps", "net_income", "shares")) if x
    ) or None
    return Result.good(num(eps * mult), method=method)


def ev_reg(ctx, name, rec, fy):
    years = rec["data"]["years"]
    d = years.get(fy)
    if not d:
        return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")
    ebitda, err = require(d, "ebitda", fy, "EBITDA")
    if err:
        return err
    notes = []
    if ebitda <= 0:
        norm, n = estimation.normalised(years, fy, "ebitda")
        if norm is None:
            return Result.bad(R.NOT_MEANINGFUL, f"EBITDA for FY{fy} is not positive")
        ebitda = norm
        notes.append(f"normalised EBITDA (median of {n} positive years)")
    shares, err = require(d, "shares", fy, "shares outstanding")
    if err:
        return err
    if shares <= 0:
        return Result.bad(R.NOT_MEANINGFUL, f"share count reported as {shares:,.0f}")

    peers = ctx["ev_table"].get((rec["sector"], fy), {})
    mult, how = _blend_multiple(
        ctx["ev_model"].predict(name, years, fy), peers, name, config.EV_EBITDA_BOUNDS
    )
    if mult is None:
        bench, bm, err = model_ev_ebitda.benchmark_multiple(
            ctx["ev_table"], ctx["universe"], rec["sector"], fy, name
        )
        if err:
            return err
        mult, how = bench, bm or "sector median"
    if how != "regression + sector median":
        notes.append(f"EV/EBITDA from {how}")

    net_debt = (d.get("total_debt") or 0.0) - (d.get("cash") or 0.0)
    equity = ebitda * mult - net_debt
    if equity <= 0:
        return Result.bad(R.NEG_EQUITY, "implied EV is below net debt")
    method = "; ".join(
        x
        for x in (
            *notes,
            estimation.method_of(d, "ebitda", "shares", "total_debt", "cash"),
        )
        if x
    ) or None
    return Result.good(num(equity / shares), method=method)


def ml_consensus(store, name, fy):
    if store is None or not store.predictions:
        return Result.bad(R.MODEL_NA, "no machine-learning model ran")
    got = [store.get(k, name, fy) for k in store.predictions]
    ok = [r for r in got if r.ok and r.value > 0]
    if not ok:
        return got[0] if got else Result.bad(R.NOT_COMPUTABLE, "no ML prediction")
    gm = math.exp(sum(math.log(r.value) for r in ok) / len(ok))
    est = [r for r in ok if r.estimated]
    method = f"{len(est)} of {len(ok)} learners estimated/leaked" if est else None
    return Result.good(gm, method=method)


# ============================================================== components
def components_for(ctx, name, fy):
    rec = ctx["universe"][name]
    guarded = {
        "dcf_plus": lambda: dcf_plus(rec, fy),
        "ri": lambda: model_residual_income.compute(rec, fy),
        "pe_reg": lambda: pe_reg(ctx, name, rec, fy),
        "ev_reg": lambda: ev_reg(ctx, name, rec, fy),
        "graham": lambda: model_graham.intrinsic_value(ctx["universe"], name, fy),
        "ml": lambda: ml_consensus(ctx["ml_store"], name, fy),
    }
    out = {}
    for k, fn in guarded.items():
        try:
            out[k] = fn()
        except Exception as e:
            log.exception("hybrid component %s failed %s FY%s", k, name, fy)
            out[k] = Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
    return out


# ================================================================ weighting
def _error_history(table):
    """-> list of (sector, fy, comp, ln(V/benchmark)) for every scored cell.
    SIGNED, so both the bias and the spread can be read from it."""
    hist = []
    for (name, fy), row in table.items():
        b = row["bench"]
        if not (b.ok and b.value > 0):
            continue
        for k, res in row["comps"].items():
            if res.ok and res.value > 0:
                hist.append((row["sector"], fy, k, math.log(res.value / b.value)))
    return hist


def _skill(hist, sector, fy, comp):
    """
    -> (correction, error_scale, n) from rows strictly before fy,
       or (0, None, 0) without enough history.

    correction   the log calibration actually applied: the median signed log
                 error (how far, and which way, this component has typically
                 missed in this sector), shrunk toward zero by evidence,
                 lambda = n / (n + HYBRID_SHRINK_K). Zero with calibration off.
    error_scale  median absolute error REMAINING after that correction. It is
                 measured on the residual actually left, not on a full
                 de-biasing, so a component whose bias is only partly removed
                 is still charged for the part that remains.
    """
    need = getattr(config, "HYBRID_MIN_ERR_OBS", 4)
    errs = [e for s, f, k, e in hist if k == comp and f < fy and s == sector]
    if len(errs) < need:
        errs = [e for s, f, k, e in hist if k == comp and f < fy]
    if len(errs) < need:
        return 0.0, None, 0
    n = len(errs)
    correction = 0.0
    if getattr(config, "HYBRID_BIAS_CORRECT", True):
        lam = n / (n + getattr(config, "HYBRID_SHRINK_K", 10))
        correction = lam * statistics.median(errs)
    scale = statistics.median(abs(e - correction) for e in errs)
    return correction, scale, n


def _weighted_median(values, weights):
    pairs = sorted(zip(values, weights))
    half, acc = sum(weights) / 2, 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def blend(comps, reg, sector, fy, hist, rng):
    """
    -> dict with value, low, high, confidence, weights, dropped, est_share,
       or None when nothing applicable survived.
    """
    applicable = [k for k in COMPONENTS if regime_multiplier(reg, k) > 0]
    usable = [k for k in applicable if comps[k].ok and comps[k].value > 0]
    if not usable:
        return None

    shrink_k = getattr(config, "HYBRID_SHRINK_K", 10)
    hist_k = {k: _skill(hist, sector, fy, k) for k in usable}
    errs = {k: (scale, n) for k, (_, scale, n) in hist_k.items()}

    # calibration: remove each component's own systematic miss, shrunk by
    # evidence, so a method that has always priced 40% low stops dragging
    # the blend down while keeping its information about RELATIVE value
    logs, corrections = {}, {}
    for k in usable:
        c = hist_k[k][0]
        corrections[k] = c
        logs[k] = math.log(comps[k].value) - c

    # relative skill, shrunk toward 1 by each component's own evidence
    skills = {k: 1.0 / (e * e + 1e-4) for k, (e, n) in errs.items() if e is not None}
    mean_skill = statistics.mean(skills.values()) if skills else None
    penalty = getattr(config, "HYBRID_ESTIMATE_PENALTY", 0.75)
    raw = {}
    for k in usable:
        e, n = errs[k]
        rel = 1.0
        if e is not None and mean_skill:
            lam = n / (n + shrink_k)
            rel = lam * (skills[k] / mean_skill) + (1 - lam)
        w = rel * regime_multiplier(reg, k)
        if comps[k].estimated:
            w *= penalty
        raw[k] = w

    # robust guard against a single exploding component
    dropped = []
    if len(usable) >= 3:
        centre = _weighted_median([logs[k] for k in usable], [raw[k] for k in usable])
        limit = math.log(getattr(config, "HYBRID_OUTLIER_RATIO", 3.0))
        dropped = [k for k in usable if abs(logs[k] - centre) > limit]
        if len(dropped) < len(usable):
            usable = [k for k in usable if k not in dropped]
        else:
            dropped = []

    total = sum(raw[k] for k in usable)
    if total <= 0:
        return None
    w = {k: raw[k] / total for k in usable}
    centre = sum(w[k] * logs[k] for k in usable)

    # ---- uncertainty: correlated Monte Carlo + model disagreement ----
    default_sigma = getattr(config, "HYBRID_DEFAULT_SIGMA", 0.35)
    sig = np.array(
        [
            1.4826 * errs[k][0] if (errs[k][0] is not None and errs[k][1] >= 3) else default_sigma
            for k in usable
        ]
    )
    wv = np.array([w[k] for k in usable])
    disagreement = math.sqrt(sum(w[k] * (logs[k] - centre) ** 2 for k in usable))
    rho = getattr(config, "HYBRID_ERROR_CORR", 0.5)
    draws = getattr(config, "HYBRID_MC_DRAWS", 2000)
    zc = rng.standard_normal((draws, 1))
    zk = rng.standard_normal((draws, len(usable)))
    shocks = sig * (math.sqrt(rho) * zc + math.sqrt(1 - rho) * zk)
    sim = centre + shocks @ wv + disagreement * rng.standard_normal(draws)
    lo_q, hi_q = getattr(config, "HYBRID_BAND", (10, 90))
    low, high = np.exp(np.percentile(sim, [lo_q, hi_q]))

    est_share = sum(w[k] for k in usable if comps[k].estimated)
    coverage = len(usable) / max(1, len(applicable))

    # Confidence = the hybrid's own estimate of the chance that the market
    # price lands within +/- HYBRID_CONF_TOLERANCE of its value, read straight
    # off the simulated distribution, then discounted for components that
    # could not report and for weight resting on estimated inputs. It is a
    # probability, so it can be checked: across many rows, the share that
    # actually landed inside the tolerance should match the average score.
    tol = getattr(config, "HYBRID_CONF_TOLERANCE", 0.20)
    inside = (sim >= centre + math.log(1 - tol)) & (sim <= centre + math.log(1 + tol))
    p_within = float(inside.mean())
    confidence = 100.0 * p_within * math.sqrt(coverage) * (1 - 0.25 * est_share)

    return {
        "value": math.exp(centre),
        "low": float(low),
        "high": float(high),
        "confidence": clamp(confidence, 0.0, 100.0),
        "weights": w,
        "corrections": corrections,
        "dropped": dropped,
        "est_share": est_share,
    }


def confidence_label(c):
    if c >= getattr(config, "HYBRID_CONF_HIGH", 60):
        return "High"
    if c >= getattr(config, "HYBRID_CONF_MEDIUM", 35):
        return "Medium"
    return "Low"


# ================================================================== driver
def attach(
    rows, universe, peer_universe, pe_table, ev_table, ml_store, failures, write=True,
    set_value=True,
):
    """
    Compute row["hybrid"] for every report row, in place, and (when write is
    set) write Ensemble_Detail.csv and print the summary. Runs after every other
    model, because the weights are learned from the whole panel's earlier-year
    errors. -> the detail rows, which the auto-trainer reads its meter from.
    """
    capital.build_sector_betas(universe)
    ctx = {
        "universe": universe,
        "pe_table": pe_table,
        "ev_table": ev_table,
        "ml_store": ml_store,
        "pe_model": MultipleRegression(peer_universe, model_pe.observed_pe, _pe_features),
        "ev_model": MultipleRegression(
            peer_universe, model_ev_ebitda.observed_multiple, _ev_features
        ),
    }

    # pass 1: every component for every row, plus its benchmark
    table = {}
    for row in rows:
        name, fy = row["company"], row["fy"]
        if name in failures or name not in universe:
            continue
        rec = universe[name]
        table[(name, fy)] = {
            "sector": rec["sector"],
            "regime": regime(rec, fy),
            "bench": row["price"],
            "comps": components_for(ctx, name, fy),
        }
    hist = _error_history(table)

    # pass 2: weights from strictly earlier years, then blend
    rng = np.random.default_rng(config.ML_RANDOM_STATE)
    detail = []
    for row in rows:
        name, fy = row["company"], row["fy"]
        if name in failures:
            if set_value:
                row[KEY] = failures[name]
            continue
        t = table.get((name, fy))
        if t is None:
            if set_value:
                row[KEY] = Result.bad(R.NOT_COMPUTABLE, "company was not in the universe")
            continue
        # The HYBRID MODEL reads the same components; keep them on the row
        # (underscore keys are never exported).
        row["_comps"], row["_regime"] = t["comps"], t["regime"]
        if not set_value:
            continue
        try:
            b = blend(t["comps"], t["regime"], t["sector"], fy, hist, rng)
        except Exception as e:
            log.exception("hybrid blend failed %s FY%s", name, fy)
            row[KEY] = Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
            continue

        if b is None:
            reasons = "; ".join(
                f"{COMPONENT_NAMES[k]} - {t['comps'][k].code}"
                for k in COMPONENTS
                if regime_multiplier(t["regime"], k) > 0 and not t["comps"][k].ok
            )
            row[KEY] = Result.bad(
                R.NOT_COMPUTABLE,
                f"no applicable component could value this {t['regime']} "
                f"company-year ({reasons})",
            )
        else:
            method = (
                f"{b['est_share']:.0%} of the weight rests on estimated inputs"
                if b["est_share"] > 0
                else None
            )
            row[KEY] = Result.good(b["value"], method=method)
        detail.append(_detail_row(name, t, fy, row, b))

    if write and set_value:
        path = _write_detail(detail)
        _print_summary(rows, detail, path)
    return detail


def scorecard(detail):
    """
    -> {confidence, hit20, n_valued, n_scored} over the detail rows.

    confidence  the average predicted chance of landing within the tolerance
    hit20       the share that actually DID land within it (rows with a
                benchmark only). Comparing the two is the calibration check.
    """
    tol = getattr(config, "HYBRID_CONF_TOLERANCE", 0.20)
    valued = [d for d in detail if d["Hybrid Value"] != ""]
    scored = [d for d in valued if d["Market Price"] != ""]
    hits = sum(
        1
        for d in scored
        if abs(d["Hybrid Value"] / d["Market Price"] - 1) <= tol
    )
    return {
        "confidence": statistics.mean(d["Confidence"] for d in valued) if valued else 0.0,
        "hit20": 100.0 * hits / len(scored) if scored else 0.0,
        "n_valued": len(valued),
        "n_scored": len(scored),
    }


def _detail_row(name, t, fy, row, b):
    out = {
        "Company name": name,
        "Sector Name": t["sector"],
        "Financial Year": fy_label(fy),
        "Regime": t["regime"],
        "Market Price": round(t["bench"].value, 2) if t["bench"].ok else "",
        "Hybrid Value": round(b["value"], 2) if b else "",
        "Low (P10)": round(b["low"], 2) if b else "",
        "High (P90)": round(b["high"], 2) if b else "",
        "Confidence": round(b["confidence"], 1) if b else "",
        "Confidence label": confidence_label(b["confidence"]) if b else "",
        "Components used": len(b["weights"]) if b else 0,
        "Dropped as outliers": ", ".join(COMPONENT_NAMES[k] for k in b["dropped"]) if b else "",
        "Estimated share of weight": round(b["est_share"], 3) if b else "",
    }
    for k in COMPONENTS:
        res = t["comps"][k]
        label = COMPONENT_NAMES[k]
        out[f"{label} value"] = round(res.value, 2) if res.ok else res.code
        out[f"{label} weight"] = round(b["weights"].get(k, 0.0), 3) if b else ""
        # the multiplicative calibration applied: 1.25 means the raw value
        # was scaled up 25% because this component has historically priced low
        c = b["corrections"].get(k) if b else None
        out[f"{label} calibration"] = round(math.exp(-c), 3) if c is not None else ""
    return out


def _write_detail(detail):
    if not detail:
        return None
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / DETAIL_FILE
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)
    return path


def _print_summary(rows, detail, path):
    valued = [d for d in detail if d["Hybrid Value"] != ""]
    print(f"\n[ensemble] valued {len(valued)}/{len(rows)} company-years")
    if valued:
        regimes = {}
        for d in detail:
            regimes[d["Regime"]] = regimes.get(d["Regime"], 0) + 1
        print(
            "[ensemble] regimes: "
            + ", ".join(f"{k} {v}" for k, v in sorted(regimes.items()))
        )
        labels = {}
        for d in valued:
            labels[d["Confidence label"]] = labels.get(d["Confidence label"], 0) + 1
        sc = scorecard(detail)
        print(
            f"[ensemble] confidence: average {sc['confidence']:.0f}/100  ("
            + ", ".join(f"{k} {labels.get(k, 0)}" for k in ("High", "Medium", "Low"))
            + ")"
        )
        print(
            f"[ensemble] calibration check: predicted {sc['confidence']:.0f}% within "
            f"+/-{getattr(config, 'HYBRID_CONF_TOLERANCE', 0.20):.0%}, actually "
            f"{sc['hit20']:.0f}% ({sc['n_scored']} scored rows)"
        )
    if path:
        print(f"[ensemble] weights, ranges and components -> {path}")
