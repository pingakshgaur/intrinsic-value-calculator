"""P/E relative valuation - Result-returning."""

import logging
import statistics
import config
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
    """-> (multiple, None) or (None, Result)."""
    peers = table.get((sector, fy), {})
    ex_self = [v for k, v in peers.items() if k != company_name]
    if len(ex_self) >= config.MIN_PEERS_FOR_MEDIAN:
        return statistics.median(ex_self), None
    if peers:
        return statistics.median(list(peers.values())), None

    own = [
        v
        for v in (
            observed_pe(d) for d in universe[company_name]["data"]["years"].values()
        )
        if v
    ]
    if own:
        return statistics.median(own), None

    return None, Result.bad(
        R.NO_PEERS,
        f"no usable P/E for sector '{sector}' in FY{fy} - {len(peers)} peer(s) had a "
        f"valid multiple inside bounds {config.PE_BOUNDS}, and this company has no "
        f"own-history P/E either (loss-making or price/EPS missing across all years). "
        f"Add more companies to this sector in the input CSV.",
    )


def intrinsic_value(universe, table, company_name, sector, fy) -> Result:
    try:
        d = universe[company_name]["data"]["years"].get(fy)
        if not d:
            return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

        eps, err = require(d, "eps", fy, "EPS")
        if err:
            return err
        if eps <= 0:
            return Result.bad(
                R.NOT_MEANINGFUL,
                f"EPS for FY{fy} is {config.CURRENCY_SYMBOL}{eps:,.2f} (loss-making); "
                f"P/E valuation is undefined for negative earnings",
            )

        bench, err = benchmark_pe(table, universe, sector, fy, company_name)
        if err:
            return err

        return Result.good(num(eps * bench))
    except Exception as e:
        log.exception("P/E failed %s FY%s", company_name, fy)
        return Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
