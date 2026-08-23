"""P/E relative valuation - Result-returning."""

import logging
import statistics

import config
import estimation
from result import Result, R, require
from fy_utils import num

log = logging.getLogger(__name__)


def observed_pe(d):
    price, eps = (d or {}).get("price"), (d or {}).get("eps")
    if not price or not eps or eps <= 0:
        return None
    pe = price / eps
    lo, hi = config.PE_BOUNDS
    return pe if lo <= pe <= hi else None


def build_sector_pe_table(universe):
    table = {}
    for name, rec in universe.items():
        for fy, d in rec["data"]["years"].items():
            pe = observed_pe(d)
            if pe is not None:
                table.setdefault((rec["sector"], fy), {})[name] = pe
    return table


def benchmark_pe(table, universe, sector, fy, company_name):
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
            observed_pe(d) for d in universe[company_name]["data"]["years"].values()
        )
        if v
    ]
    if own:
        return statistics.median(own), "own historical P/E (no sector peers)", None

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
            f"whole-universe median P/E for FY{fy} (sector '{sector}' empty)",
            None,
        )

    return (
        None,
        None,
        Result.bad(
            R.NO_PEERS,
            f"no usable P/E anywhere in FY{fy} - no company produced a multiple inside "
            f"bounds {config.PE_BOUNDS}, and this company has no own-history P/E",
        ),
    )


def intrinsic_value(universe, table, company_name, sector, fy) -> Result:
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
            if norm is None:
                return Result.bad(
                    R.NOT_MEANINGFUL,
                    f"EPS for FY{fy} is {config.CURRENCY_SYMBOL}{eps:,.2f} and no "
                    f"positive-EPS history exists to normalise against",
                )
            eps = norm
            est_method = f"normalised EPS (median of {n} positive years)"

        bench, bench_method, err = benchmark_pe(
            table, universe, sector, fy, company_name
        )
        if err:
            return err

        field_method = estimation.method_of(d, "eps", "net_income", "shares")
        method = (
            "; ".join(x for x in (est_method, bench_method, field_method) if x) or None
        )
        return Result.good(num(eps * bench), method=method)

    except Exception as e:
        log.exception("P/E failed %s FY%s", company_name, fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
