"""EV/EBITDA relative valuation - Result-returning."""

import logging
import statistics

import config
import estimation
from result import Result, R, require
from fy_utils import num

log = logging.getLogger(__name__)


def observed_multiple(d):
    d = d or {}
    price, shares, ebitda = d.get("price"), d.get("shares"), d.get("ebitda")
    if not price or not shares or not ebitda or ebitda <= 0:
        return None
    ev = price * shares + (d.get("total_debt") or 0.0) - (d.get("cash") or 0.0)
    if ev <= 0:
        return None
    m = ev / ebitda
    lo, hi = config.EV_EBITDA_BOUNDS
    return m if lo <= m <= hi else None


def build_sector_table(universe):
    table = {}
    for name, rec in universe.items():
        for fy, d in rec["data"]["years"].items():
            m = observed_multiple(d)
            if m is not None:
                table.setdefault((rec["sector"], fy), {})[name] = m
    return table


def benchmark_multiple(table, universe, sector, fy, company_name):
    """-> (multiple, method_or_None, None) or (None, None, Result)."""
    peers = table.get((sector, fy), {})
    ex_self = [v for k, v in peers.items() if k != company_name]
    if len(ex_self) >= config.MIN_PEERS_FOR_MEDIAN:
        return statistics.median(ex_self), None, None
    if peers:
        return (
            statistics.median(list(peers.values())),
            "sector median including self (too few peers)",
            None,
        )

    own = [
        v
        for v in (
            observed_multiple(d)
            for d in universe[company_name]["data"]["years"].values()
        )
        if v
    ]
    if own:
        return statistics.median(own), "own historical EV/EBITDA", None

    allv = [
        v
        for (sec, f), pr in table.items()
        if f == fy
        for k, v in pr.items()
        if k != company_name
    ]
    if allv:
        return (
            statistics.median(allv),
            f"whole-universe median EV/EBITDA for FY{fy}",
            None,
        )

    return (
        None,
        None,
        Result.bad(
            R.NO_PEERS,
            f"no usable EV/EBITDA anywhere in FY{fy} inside bounds "
            f"{config.EV_EBITDA_BOUNDS}. Banks and NBFCs never yield one.",
        ),
    )


def intrinsic_value(universe, table, company_name, sector, fy) -> Result:
    try:
        years = universe[company_name]["data"]["years"]
        d = years.get(fy)
        if not d:
            return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

        ebitda, err = require(d, "ebitda", fy, "EBITDA")
        if err:
            return err

        est_method = None
        if ebitda <= 0:
            norm, n = estimation.normalised(years, fy, "ebitda")
            if norm is None:
                return Result.bad(
                    R.NOT_MEANINGFUL,
                    f"EBITDA for FY{fy} is "
                    f"{config.CURRENCY_SYMBOL}{ebitda:,.0f} (operating loss) and no "
                    f"positive history exists to normalise against",
                )
            ebitda = norm
            est_method = f"normalised EBITDA (median of {n} positive years)"

        shares, err = require(d, "shares", fy, "shares outstanding")
        if err:
            return err
        if shares <= 0:
            return Result.bad(
                R.NOT_MEANINGFUL, f"share count reported as {shares:,.0f}"
            )

        bench, bench_method, err = benchmark_multiple(
            table, universe, sector, fy, company_name
        )
        if err:
            return err

        net_debt = (d.get("total_debt") or 0.0) - (d.get("cash") or 0.0)
        equity = ebitda * bench - net_debt
        if equity <= 0:
            return Result.bad(
                R.NEG_EQUITY,
                f"implied EV {config.CURRENCY_SYMBOL}{ebitda * bench:,.0f} "
                f"(EBITDA x {bench:.2f}x) is below net debt "
                f"{config.CURRENCY_SYMBOL}{net_debt:,.0f}; equity value is nil",
            )

        field_method = estimation.method_of(
            d, "ebitda", "ebit", "da", "shares", "total_debt", "cash"
        )
        method = (
            "; ".join(x for x in (est_method, bench_method, field_method) if x) or None
        )
        return Result.good(num(equity / shares), method=method)

    except Exception as e:
        log.exception("EV/EBITDA failed %s FY%s", company_name, fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
