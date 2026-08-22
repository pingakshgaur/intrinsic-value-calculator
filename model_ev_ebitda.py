"""EV/EBITDA relative valuation - Result-returning."""

import logging
import statistics
import config
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
    peers = table.get((sector, fy), {})
    ex_self = [v for k, v in peers.items() if k != company_name]
    if len(ex_self) >= config.MIN_PEERS_FOR_MEDIAN:
        return statistics.median(ex_self), None
    if peers:
        return statistics.median(list(peers.values())), None

    own = [
        v
        for v in (
            observed_multiple(d)
            for d in universe[company_name]["data"]["years"].values()
        )
        if v
    ]
    if own:
        return statistics.median(own), None

    return None, Result.bad(
        R.NO_PEERS,
        f"no usable EV/EBITDA for sector '{sector}' in FY{fy} - no peer produced a "
        f"multiple inside bounds {config.EV_EBITDA_BOUNDS}, and own history is empty. "
        f"Note that banks/NBFCs never yield a meaningful EV/EBITDA.",
    )


def intrinsic_value(universe, table, company_name, sector, fy) -> Result:
    try:
        d = universe[company_name]["data"]["years"].get(fy)
        if not d:
            return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

        ebitda, err = require(d, "ebitda", fy, "EBITDA")
        if err:
            return err
        if ebitda <= 0:
            return Result.bad(
                R.NOT_MEANINGFUL,
                f"EBITDA for FY{fy} is {config.CURRENCY_SYMBOL}{ebitda:,.0f} "
                f"(operating loss); EV/EBITDA is undefined",
            )

        shares, err = require(d, "shares", fy, "shares outstanding")
        if err:
            return err
        if shares <= 0:
            return Result.bad(
                R.NOT_MEANINGFUL, f"share count reported as {shares:,.0f}"
            )

        bench, err = benchmark_multiple(table, universe, sector, fy, company_name)
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

        return Result.good(num(equity / shares))
    except Exception as e:
        log.exception("EV/EBITDA failed %s FY%s", company_name, fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
