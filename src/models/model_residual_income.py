# FILE: src/models/model_residual_income.py
"""
Residual Income (Edwards-Bell-Ohlson) - Result-returning.

    V0   = B0 + RI1 / (1 + Ke - w)
    RI1  = (ROE* - Ke) x B0

    B0    book value of equity at FY end
    ROE*  normalised return on equity: median of the last RI_ROE_LOOKBACK
          years up to and including FY t (point-in-time), each computed on
          average equity where the prior year exists
    Ke    CAPM cost of equity on the ADJUSTED beta (see capital.py)
    w     persistence of abnormal earnings, RI_PERSISTENCE. 0 means excess
          returns vanish after one year; 1 means they last forever. The
          closed form above is Ohlson's linear-information model: RI decays
          geometrically at rate w, and the sum of that series is exact.

WHY THIS MODEL IS IN THE PROJECT

It covers the three places where the others are weakest:

  * BANKS AND LENDERS. Debt is raw material for a lender, so FCFF and
    EV/EBITDA are undefined. Book value and ROE are exactly how lenders are
    analysed, so this model works where DCF and EV/EBITDA must refuse.

  * LOSS-MAKERS. P/E and the Graham Number take a negative EPS and stop. Here
    a sub-par ROE simply produces a NEGATIVE residual income, i.e. a value
    below book - which is the economically correct answer, not a refusal.

  * TERMINAL-VALUE DOMINANCE. Most of the value sits in B0, which is
    observed, rather than in a perpetuity assumption. The DCF typically puts
    70-85% of value in its terminal term; this model puts most of it on the
    balance sheet.

It refuses only when book value itself is not positive, or the valuation
lands below zero (a company destroying equity faster than it can be
recovered), and it says which.
"""

import logging
import statistics

import config
import capital
import estimation
from result import Result, R, require
from fy_utils import num, clamp

log = logging.getLogger(__name__)

KEY = "ri"
NAME = "Residual Income"
COLUMN = "(Residual Income) Intrinsic Value"


def roe_series(years, fy):
    """-> [(fy, roe)] for years <= fy, oldest first, average-equity basis."""
    out = []
    for y in sorted(years):
        if y > fy:
            continue
        d = years[y] or {}
        ni, eq = d.get("net_income"), d.get("equity")
        if ni is None or not eq or eq <= 0:
            continue
        prev_eq = (years.get(y - 1) or {}).get("equity")
        base = (eq + prev_eq) / 2 if prev_eq and prev_eq > 0 else eq
        out.append((y, ni / base))
    return out


def normalised_roe(years, fy):
    """-> (roe, n_years) or (None, 0)."""
    series = roe_series(years, fy)
    lookback = getattr(config, "RI_ROE_LOOKBACK", 3)
    vals = [r for _, r in series[-lookback:]]
    if not vals:
        return None, 0
    lo, hi = getattr(config, "RI_ROE_BOUNDS", (-0.50, 0.60))
    return clamp(statistics.median(vals), lo, hi), len(vals)


def compute(rec, fy):
    """Value one company-year. rec is a universe entry. -> Result."""
    years = rec["data"]["years"]
    d = years.get(fy)
    if not d:
        return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

    equity, err = require(d, "equity", fy, "shareholders' equity")
    if err:
        return err
    shares, err = require(d, "shares", fy, "shares in issue")
    if err:
        return err
    if shares <= 0:
        return Result.bad(R.NOT_MEANINGFUL, f"share count reported as {shares:,.0f}")
    if equity <= 0:
        return Result.bad(
            R.NEG_EQUITY,
            f"book value is {config.CURRENCY_SYMBOL}{equity:,.0f}; residual income "
            f"is measured against book value, so a negative base has no meaning",
        )

    roe, n = normalised_roe(years, fy)
    if roe is None:
        _, err = require(d, "net_income", fy, "net income")
        return err or Result.bad(R.FIELD_MISSING, f"no ROE computable up to FY{fy}")

    beta, _ = capital.adjusted_beta(rec)
    ke = capital.cost_of_equity(beta)
    w = getattr(config, "RI_PERSISTENCE", 0.62)

    ri1 = (roe - ke) * equity
    value = equity + ri1 / (1 + ke - w)
    if value <= 0:
        return Result.bad(
            R.NEG_EQUITY,
            f"normalised ROE {roe:.1%} sits so far below the cost of equity "
            f"{ke:.1%} that residual income erases the whole book value",
        )

    val = num(value / shares)
    if val is None:
        return Result.bad(R.CALC_ERROR, "final per-share value was NaN/Inf")

    method = estimation.method_of(d, "net_income", "equity", "shares")
    if n == 1 and len(roe_series(years, fy)) == 1:
        # One year of ROE is a snapshot, not a normal level. Still reported,
        # but marked so the asterisk carries the caveat.
        method = "; ".join(x for x in (method, "ROE from a single year") if x)
    return Result.good(val, method=method)


def intrinsic_value(universe, company_name, fy) -> Result:
    try:
        return compute(universe[company_name], fy)
    except Exception as e:
        log.exception("Residual Income failed %s FY%s", company_name, fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
