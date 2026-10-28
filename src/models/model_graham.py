# FILE: src/models/model_graham.py
"""
Graham Number - Result-returning.

    Graham Number = sqrt( 22.5 x EPS x Book Value Per Share )

Benjamin Graham's rule of thumb for the most a defensive investor should pay.
The 22.5 is 15 x 1.5: his ceilings of a P/E of 15 and a price-to-book of 1.5,
multiplied together so the two limits can trade off against each other. A
company may exceed one of them provided it compensates on the other.

WHAT IT IS AND IS NOT

This is a CEILING, not a valuation. It answers "above what price does this
stop being a defensive purchase", which is a different question from "what is
this business worth". Expect it to sit well below the DCF and the multiples
for any company with real growth, and expect that gap to be the point rather
than an error. Reported alongside the others, it acts as the conservative
floor of the range.

WHY IT REFUSES SO OFTEN

Two hard requirements, and neither can be worked around honestly:

  * EPS must be positive. A loss makes the product negative and the square
    root imaginary. Graham's method simply has nothing to say about a company
    losing money, so a refusal here is the correct answer, not a gap.

  * Book value per share must be positive. Negative equity means the balance
    sheet reports liabilities exceeding assets; a "conservative price" derived
    from it would be arithmetic dressed up as analysis.

Where a company is profitable across its history but had one bad year, the
same normalisation the P/E model uses is applied - the median of its positive
EPS years - and it is recorded as an estimate so the asterisk appears in the
report and the reason lands on the Methods sheet.
"""

import logging
import math

import config
import estimation
from result import Result, R, require
from fy_utils import num

log = logging.getLogger(__name__)

KEY = "graham"
NAME = "Graham Number"
COLUMN = "(Graham Number) Intrinsic Value"


def book_value_per_share(d):
    """-> (bvps, None) or (None, Result). Shareholders' equity / shares."""
    equity, err = require(d, "equity", 0, "shareholders' equity")
    if err:
        return None, err
    shares, err = require(d, "shares", 0, "shares in issue")
    if err:
        return None, err
    if shares <= 0:
        return None, Result.bad(
            R.NOT_MEANINGFUL,
            f"share count is {shares:,.0f}; book value per share needs a "
            f"positive number of shares",
        )
    return num(equity / shares), None


def intrinsic_value(universe, company_name, fy) -> Result:
    try:
        years = universe[company_name]["data"]["years"]
        d = years.get(fy)
        if not d:
            return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

        eps, err = require(d, "eps", fy, "EPS")
        if err:
            return err

        est_method = None
        if eps <= 0:
            norm, n = estimation.normalised(years, fy, "eps")
            if norm is None or norm <= 0:
                return Result.bad(
                    R.NOT_MEANINGFUL,
                    f"EPS for FY{fy} is {config.CURRENCY_SYMBOL}{eps:,.2f}. The "
                    f"Graham Number takes the square root of a product "
                    f"involving EPS, so a loss makes it undefined, and this "
                    f"company has no positive-EPS year to normalise against",
                )
            eps = norm
            est_method = f"normalised EPS (median of {n} positive years)"

        bvps, err = book_value_per_share(d)
        if err:
            return err
        if bvps <= 0:
            return Result.bad(
                R.NEG_EQUITY,
                f"book value per share is {config.CURRENCY_SYMBOL}{bvps:,.2f} - "
                f"the balance sheet reports liabilities above assets, so a "
                f"Graham Number computed from it would be meaningless",
            )

        multiplier = getattr(config, "GRAHAM_MULTIPLIER", 22.5)
        value = math.sqrt(multiplier * eps * bvps)

        field_method = estimation.method_of(d, "eps", "equity", "shares")
        method = "; ".join(x for x in (est_method, field_method) if x) or None

        cap = getattr(config, "GRAHAM_MAX_MULTIPLE_OF_BVPS", 0)
        if cap and value > bvps * cap:
            # A vast EPS against a thin book value can send the square root
            # somewhere silly. Flagged rather than dropped, because the inputs
            # were real and the reader should see what happened.
            method = "; ".join(
                x
                for x in (
                    method,
                    f"unusually high relative to book value "
                    f"({value / bvps:,.1f}x BVPS)",
                )
                if x
            )

        return Result.good(num(value), method=method)

    except Exception as e:
        log.exception("Graham Number failed %s FY%s", company_name, fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
