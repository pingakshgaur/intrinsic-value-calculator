"""DCF (FCFF, two-stage) - returns Result with a reason on every failure path."""

import logging
import statistics

import config
import estimation
from result import Result, R, require
from fy_utils import num, clamp

log = logging.getLogger(__name__)


def fcff(d, fy):
    """-> (value, None) or (None, Result)."""
    if not d:
        return None, Result.bad(R.NO_PERIOD, f"no financials assembled for FY{fy}")
    tax = d.get("tax_rate") or config.DEFAULT_TAX_RATE
    ebit, da, capex = d.get("ebit"), d.get("da"), d.get("capex")
    dnwc = d.get("delta_nwc") or 0.0

    if ebit is not None and da is not None and capex is not None:
        return ebit * (1 - tax) + da - capex - dnwc, None
    if d.get("ocf") is not None and capex is not None:
        return d["ocf"] - capex, None

    for lbl, key in (
        ("EBIT", "ebit"),
        ("D&A", "da"),
        ("CapEx", "capex"),
        ("Operating Cash Flow", "ocf"),
    ):
        if d.get(key) is not None:
            continue
        res = require(d, key, fy, lbl)[1]
        if res:
            return None, Result.bad(
                res.code,
                f"FCFF needs EBIT + D&A - CapEx - dNWC (or OCF - CapEx); "
                f"{lbl} is the blocker -> {res.detail}",
            )
    return None, Result.bad(R.FIELD_MISSING, "FCFF inputs incomplete")


def _fcff_quiet(d, fy):
    try:
        return fcff(d, fy)[0]
    except Exception:
        return None


def growth_from_history(series, fy):
    ys = sorted(y for y, v in series.items() if y <= fy and v is not None and v > 0)
    if len(ys) < 2:
        return config.DEFAULT_GROWTH, (
            f"only one usable FCFF observation; used default growth "
            f"{config.DEFAULT_GROWTH:.2%}"
        )
    first, last, n = series[ys[0]], series[ys[-1]], ys[-1] - ys[0]
    if first <= 0 or n <= 0:
        return config.DEFAULT_GROWTH, "growth base non-positive; used default"
    g = (last / first) ** (1.0 / n) - 1.0
    return clamp(g, config.MIN_GROWTH, config.MAX_GROWTH), None


def wacc(d, beta):
    tax = d.get("tax_rate") or config.DEFAULT_TAX_RATE
    ke = config.RISK_FREE_RATE + beta * config.EQUITY_RISK_PREMIUM
    e = (d.get("price") or 0) * (d.get("shares") or 0)
    dbt = d.get("total_debt") or 0.0
    w = (
        ke
        if (e + dbt) <= 0
        else (
            (e / (e + dbt)) * ke + (dbt / (e + dbt)) * config.COST_OF_DEBT * (1 - tax)
        )
    )
    return max(w, config.TERMINAL_GROWTH + config.WACC_SPREAD_OVER_G)


def intrinsic_value(company_data: dict, fy: int) -> Result:
    try:
        years = company_data.get("years", {})
        d = years.get(fy)
        if not d:
            return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

        shares, err = require(d, "shares", fy, "shares outstanding")
        if err:
            return err
        if shares <= 0:
            return Result.bad(
                R.NOT_MEANINGFUL, f"share count reported as {shares:,.0f}"
            )

        base, err = fcff(d, fy)
        if err:
            return err

        series = {y: _fcff_quiet(v, y) for y, v in years.items()}
        est_method = None

        if base <= 0:
            pos = [v for y, v in series.items() if y <= fy and v is not None and v > 0]
            if config.ESTIMATION_MODE != "off" and len(pos) >= 2:
                base = statistics.median(pos)
                est_method = (
                    f"normalised FCFF (median of {len(pos)} positive "
                    f"years; FY{fy} reported negative)"
                )
            else:
                return Result.bad(
                    R.NOT_MEANINGFUL,
                    f"FCFF for FY{fy} is negative "
                    f"({config.CURRENCY_SYMBOL}{base:,.0f}) and fewer than two "
                    f"positive years exist to normalise against",
                )

        g, _ = growth_from_history(series, fy)
        r = wacc(d, company_data.get("beta", config.DEFAULT_BETA))
        gt = min(config.TERMINAL_GROWTH, r - config.WACC_SPREAD_OVER_G)
        if r <= gt:
            return Result.bad(
                R.CALC_ERROR,
                f"WACC ({r:.2%}) not above terminal growth ({gt:.2%}); "
                f"terminal value would be infinite",
            )

        pv, cash_n = 0.0, base
        for i in range(1, config.PROJECTION_YEARS + 1):
            cash_n = base * ((1 + g) ** i)
            pv += cash_n / ((1 + r) ** i)
        ev = pv + ((cash_n * (1 + gt)) / (r - gt)) / (
            (1 + r) ** config.PROJECTION_YEARS
        )

        net_debt = (d.get("total_debt") or 0.0) - (d.get("cash") or 0.0)
        equity = ev - net_debt
        if equity <= 0:
            return Result.bad(
                R.NEG_EQUITY,
                f"enterprise value {config.CURRENCY_SYMBOL}{ev:,.0f} is below net "
                f"debt {config.CURRENCY_SYMBOL}{net_debt:,.0f}; equity value is nil "
                f"under these assumptions (WACC {r:.2%}, growth {g:.2%})",
            )

        val = num(equity / shares)
        if val is None:
            return Result.bad(R.CALC_ERROR, "final per-share value was NaN/Inf")

        field_method = estimation.method_of(
            d, "ebit", "da", "capex", "ocf", "shares", "total_debt", "cash"
        )
        method = "; ".join(x for x in (est_method, field_method) if x) or None
        return Result.good(val, method=method)

    except ZeroDivisionError as e:
        log.exception("DCF div-by-zero FY%s", fy)
        return Result.bad(R.CALC_ERROR, f"division by zero ({e})")
    except Exception as e:
        log.exception("DCF failed FY%s", fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
