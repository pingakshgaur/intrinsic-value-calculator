"""
Forensic accounting scores. Pure functions over one or two years of figures.

Each function takes plain dicts (one per financial year) and returns its
score together with how many of its inputs were actually available, because
a Beneish M-score computed from three of its eight ratios is a different
claim from one computed from all eight - and the report should say which.

Fields read (all optional; missing ones shrink coverage, never crash):
    revenue, cogs, gross_profit, sga, ebit, net_income, ocf, da, capex,
    assets, cur_assets, cur_liab, receivables, inventory, ppe_net,
    total_liab, lt_debt, total_debt, equity, retained_earnings, shares,
    dividends_paid, interest_expense

References
    Piotroski (2000)  "Value Investing: The Use of Historical Financial
                      Statement Information to Separate Winners from Losers"
    Altman (2005)     Z''-score for emerging-market firms
    Beneish (1999)    "The Detection of Earnings Manipulation", 8-variable model
    Sloan (1996)      accruals anomaly
"""

import math


def _g(d, k):
    v = (d or {}).get(k)
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


# =============================================================== Piotroski
def piotroski(cur, prev):
    """
    -> (score, max_possible, tests) where tests = {name: True/False}.

    Nine binary tests in three groups. A test whose inputs are missing is
    skipped rather than failed, so max_possible tells you the real scale.
    """
    tests = {}
    ta, ta_p = _g(cur, "assets"), _g(prev, "assets")
    ni, ni_p = _g(cur, "net_income"), _g(prev, "net_income")
    ocf = _g(cur, "ocf")

    roa = _div(ni, ta)
    roa_p = _div(ni_p, ta_p)
    # profitability
    if roa is not None:
        tests["positive ROA"] = roa > 0
    if ocf is not None:
        tests["positive operating cash flow"] = ocf > 0
    if roa is not None and roa_p is not None:
        tests["ROA improved"] = roa > roa_p
    if ocf is not None and ni is not None:
        tests["cash flow exceeds profit (low accruals)"] = ocf > ni

    # leverage, liquidity, dilution
    lev = _div(_g(cur, "lt_debt") if _g(cur, "lt_debt") is not None else _g(cur, "total_debt"), ta)
    lev_p = _div(
        _g(prev, "lt_debt") if _g(prev, "lt_debt") is not None else _g(prev, "total_debt"), ta_p
    )
    if lev is not None and lev_p is not None:
        tests["leverage fell"] = lev <= lev_p
    cr = _div(_g(cur, "cur_assets"), _g(cur, "cur_liab"))
    cr_p = _div(_g(prev, "cur_assets"), _g(prev, "cur_liab"))
    if cr is not None and cr_p is not None:
        tests["current ratio improved"] = cr > cr_p
    sh, sh_p = _g(cur, "shares"), _g(prev, "shares")
    if sh is not None and sh_p is not None:
        tests["no dilution"] = sh <= sh_p * 1.005

    # operating efficiency
    gm = _div(_g(cur, "gross_profit"), _g(cur, "revenue"))
    gm_p = _div(_g(prev, "gross_profit"), _g(prev, "revenue"))
    if gm is not None and gm_p is not None:
        tests["gross margin improved"] = gm > gm_p
    at = _div(_g(cur, "revenue"), ta_p)
    at_p = _div(_g(prev, "revenue"), ta_p)
    if at is not None and at_p is not None and _g(prev, "revenue"):
        # asset turnover on opening assets both years where only one prior
        # balance sheet exists; the direction is what the test reads
        tests["asset turnover improved"] = at > at_p

    return sum(1 for v in tests.values() if v), len(tests), tests


# ============================================================ Altman Z''
def altman_z_em(cur):
    """
    Emerging-market Z'' = 3.25 + 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4
        X1 working capital / assets      X2 retained earnings / assets
        X3 EBIT / assets                 X4 book equity / total liabilities
    Zones: > 5.85 safe, 4.15-5.85 grey, < 4.15 distress (with the 3.25
    constant). -> (z, zone, n_inputs) or (None, None, n).
    """
    ta = _g(cur, "assets")
    if not ta or ta <= 0:
        return None, None, 0
    ca, cl = _g(cur, "cur_assets"), _g(cur, "cur_liab")
    re_ = _g(cur, "retained_earnings")
    ebit = _g(cur, "ebit")
    eq = _g(cur, "equity")
    tl = _g(cur, "total_liab")
    if tl is None and eq is not None:
        tl = ta - eq
    xs = {
        "x1": _div(ca - cl, ta) if ca is not None and cl is not None else None,
        "x2": _div(re_, ta),
        "x3": _div(ebit, ta),
        "x4": _div(eq, tl) if tl and tl > 0 else None,
    }
    n = sum(1 for v in xs.values() if v is not None)
    if n < 3:
        return None, None, n
    # a missing ratio contributes its neutral value of zero
    z = 3.25 + 6.56 * (xs["x1"] or 0) + 3.26 * (xs["x2"] or 0) + 6.72 * (xs["x3"] or 0)
    z += 1.05 * (xs["x4"] or 0)
    zone = "safe" if z > 5.85 else ("grey" if z > 4.15 else "distress")
    return z, zone, n


# ============================================================== Beneish
BENEISH_THRESHOLD = -1.78


def beneish_m(cur, prev):
    """
    8-variable M-score. -> (m, n_ratios, ratios). Above -1.78 = the profile
    of companies later found to have manipulated earnings. Missing ratios
    take their neutral value (1 for the indices, 0 for TATA), which biases a
    partial score toward 'clean' - so the caller should weight it by n.
    """
    rev, rev_p = _g(cur, "revenue"), _g(prev, "revenue")
    if not rev or not rev_p:
        return None, 0, {}

    def idx(a, b):
        v = _div(a, b)
        return v if v is not None and v > 0 else None

    rec, rec_p = _g(cur, "receivables"), _g(prev, "receivables")
    dsri = idx(_div(rec, rev), _div(rec_p, rev_p))

    gp, gp_p = _g(cur, "gross_profit"), _g(prev, "gross_profit")
    if gp is None and _g(cur, "cogs") is not None:
        gp = rev - _g(cur, "cogs")
    if gp_p is None and _g(prev, "cogs") is not None:
        gp_p = rev_p - _g(prev, "cogs")
    gmi = idx(_div(gp_p, rev_p), _div(gp, rev))

    def aq(d):
        ta = _g(d, "assets")
        ca, ppe = _g(d, "cur_assets"), _g(d, "ppe_net")
        if not ta or ca is None or ppe is None:
            return None
        return 1 - (ca + ppe) / ta

    aqi = idx(aq(cur), aq(prev))
    sgi = idx(rev, rev_p)

    def dep_rate(d):
        da, ppe = _g(d, "da"), _g(d, "ppe_net")
        return _div(da, (da or 0) + (ppe or 0)) if da is not None and ppe is not None else None

    depi = idx(dep_rate(prev), dep_rate(cur))
    sgai = idx(_div(_g(cur, "sga"), rev), _div(_g(prev, "sga"), rev_p))

    def lev(d):
        tl = _g(d, "total_liab")
        return _div(tl, _g(d, "assets"))

    lvgi = idx(lev(cur), lev(prev))
    ni, ocf, ta = _g(cur, "net_income"), _g(cur, "ocf"), _g(cur, "assets")
    tata = _div(ni - ocf, ta) if ni is not None and ocf is not None else None

    ratios = {
        "DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
        "DEPI": depi, "SGAI": sgai, "LVGI": lvgi, "TATA": tata,
    }
    n = sum(1 for v in ratios.values() if v is not None)
    if n < 4:
        return None, n, ratios
    r = {k: (v if v is not None else (0.0 if k == "TATA" else 1.0)) for k, v in ratios.items()}
    m = (
        -4.84
        + 0.920 * r["DSRI"]
        + 0.528 * r["GMI"]
        + 0.404 * r["AQI"]
        + 0.892 * r["SGI"]
        + 0.115 * r["DEPI"]
        - 0.172 * r["SGAI"]
        + 4.679 * r["TATA"]
        - 0.327 * r["LVGI"]
    )
    return m, n, ratios


# ============================================================ cash quality
def accrual_ratio(cur, prev):
    """Sloan accruals: (net income - OCF) / average assets. High = low quality."""
    ni, ocf = _g(cur, "net_income"), _g(cur, "ocf")
    ta, ta_p = _g(cur, "assets"), _g(prev, "assets")
    if ni is None or ocf is None or not ta:
        return None
    avg = (ta + ta_p) / 2 if ta_p else ta
    return (ni - ocf) / avg


def cash_conversion(years):
    """Sum of OCF / sum of net income over the years given (profitable only)."""
    ni = [_g(d, "net_income") for d in years]
    ocf = [_g(d, "ocf") for d in years]
    pairs = [(o, n) for o, n in zip(ocf, ni) if o is not None and n is not None]
    tot_ni = sum(n for _, n in pairs)
    if not pairs or tot_ni <= 0:
        return None
    return sum(o for o, _ in pairs) / tot_ni


def receivable_days(d):
    v = _div(_g(d, "receivables"), _g(d, "revenue"))
    return v * 365 if v is not None else None


def interest_cover(d):
    ie = _g(d, "interest_expense")
    if ie is None or ie == 0:
        return None
    return _div(_g(d, "ebit"), abs(ie))


def cagr(first, last, years):
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def stdev(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
