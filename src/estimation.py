"""
Gap-filling layer. Runs after every company is fetched, before any valuation.

Design rule: an estimated value is NEVER indistinguishable from a fetched one.
Each filled field records its method in d["_method"][field], which propagates to
Result.method, to the asterisk in the report, and to the Methods sheet.

Fallback ladder per field (first that succeeds wins):
  1. reported          - yfinance returned it
  2. override          - data/fundamentals_override.csv
  3. derived           - identity, e.g. EBITDA = EBIT + D&A
  4. backcast_revenue  - nearest known year scaled by the revenue ratio
  5. backcast_cagr     - nearest known year scaled by the company's own CAGR
  6. sector_ratio      - revenue x sector-median margin for that sector-year
"""

import logging
import statistics

import config

log = logging.getLogger(__name__)

RATIO_BASIS = {
    "ebit": "ebit_margin",
    "ebitda": "ebitda_margin",
    "net_income": "net_margin",
    "ocf": "ocf_margin",
    "capex": "capex_ratio",
    "da": "da_ratio",
    "assets": "asset_ratio",
    "cur_liab": "cur_liab_ratio",
    "equity": "equity_ratio",
    "total_debt": "debt_ratio",
    "cash": "cash_ratio",
}


def _r(a, b):
    try:
        return a / b if (a is not None and b) else None
    except ZeroDivisionError:
        return None


def build_sector_stats(universe):
    """-> {(sector, fy): {ratio_name: median}}  plus ('*', fy) as global fallback."""
    buckets = {}
    for name, rec in universe.items():
        sector = rec["sector"]
        for fy, d in rec["data"]["years"].items():
            rev = d.get("revenue")
            if not rev or rev <= 0:
                continue
            ratios = {
                "ebit_margin": _r(d.get("ebit"), rev),
                "ebitda_margin": _r(d.get("ebitda"), rev),
                "net_margin": _r(d.get("net_income"), rev),
                "ocf_margin": _r(d.get("ocf"), rev),
                "capex_ratio": _r(d.get("capex"), rev),
                "da_ratio": _r(d.get("da"), rev),
                "asset_ratio": _r(d.get("assets"), rev),
                "cur_liab_ratio": _r(d.get("cur_liab"), rev),
                "equity_ratio": _r(d.get("equity"), rev),
                "debt_ratio": _r(d.get("total_debt"), rev),
                "cash_ratio": _r(d.get("cash"), rev),
            }
            for key in ((sector, fy), ("*", fy)):
                slot = buckets.setdefault(key, {})
                for rname, rv in ratios.items():
                    if rv is not None:
                        slot.setdefault(rname, []).append(rv)

    return {
        key: {rn: statistics.median(vs) for rn, vs in slot.items() if vs}
        for key, slot in buckets.items()
    }


def _sector_ratio(stats, sector, fy, ratio_name):
    for key in ((sector, fy), ("*", fy)):
        v = stats.get(key, {}).get(ratio_name)
        if v is not None:
            return v
    for (sec, _fy), slot in stats.items():
        if sec == sector and ratio_name in slot:
            return slot[ratio_name]
    for slot in stats.values():
        if ratio_name in slot:
            return slot[ratio_name]
    return None


def _nearest_known(years, fy, field):
    """Closest FY (prefer later, then earlier) that has this field."""
    cands = [
        (abs(y - fy), -y, y)
        for y, d in years.items()
        if y != fy and d.get(field) is not None
    ]
    if not cands:
        return None
    cands.sort()
    return cands[0][2]


def _clamped(v, ref):
    if ref is None or ref == 0:
        return v
    ratio = v / ref
    if ratio > config.BACKCAST_MAX_RATIO:
        return ref * config.BACKCAST_MAX_RATIO
    if ratio < config.BACKCAST_MIN_RATIO:
        return ref * config.BACKCAST_MIN_RATIO
    return v


def _own_cagr(years, field):
    pts = sorted(
        (y, d[field])
        for y, d in years.items()
        if d.get(field) is not None and d[field] > 0
    )
    if len(pts) < 2:
        return None
    (y0, v0), (y1, v1) = pts[0], pts[-1]
    n = y1 - y0
    if n <= 0 or v0 <= 0:
        return None
    try:
        return (v1 / v0) ** (1.0 / n) - 1.0
    except (ValueError, ZeroDivisionError):
        return None


def fill_company(rec, stats):
    """Fill every gap in one company's year dict, in place. -> count filled."""
    if config.ESTIMATION_MODE == "off":
        return 0

    years = rec["data"]["years"]
    sector = rec["sector"]
    filled_total = 0

    for d in years.values():
        d.setdefault("_method", {})
        d.setdefault("_diag", {})
        d.setdefault("_notes", [])

    # ---- pass A: revenue first, everything else keys off it ----
    for fy in sorted(years):
        d = years[fy]
        if d.get("revenue") is None:
            src = _nearest_known(years, fy, "revenue")
            if src is not None:
                base = years[src]["revenue"]
                g = _own_cagr(years, "revenue") or 0.0
                d["revenue"] = _clamped(base * ((1 + g) ** (fy - src)), base)
                d["_method"]["revenue"] = f"backcast_cagr from FY{src}"
                d["_diag"].pop("revenue", None)
                filled_total += 1

    # ---- pass B: shares barely move year to year ----
    for fy in sorted(years):
        d = years[fy]
        if d.get("shares") is None:
            src = _nearest_known(years, fy, "shares")
            if src is not None:
                d["shares"] = years[src]["shares"]
                d["_method"]["shares"] = f"carried from FY{src}"
                d["_diag"].pop("shares", None)
                filled_total += 1

    # ---- pass C: everything else ----
    for fy in sorted(years):
        d = years[fy]
        rev = d.get("revenue")

        for field, ratio_name in RATIO_BASIS.items():
            if d.get(field) is not None:
                continue

            src = _nearest_known(years, fy, field)
            if src is not None:
                base = years[src][field]
                src_rev = years[src].get("revenue")
                if rev and src_rev:
                    d[field] = _clamped(base * (rev / src_rev), base)
                    d["_method"][field] = f"backcast_revenue from FY{src}"
                else:
                    g = _own_cagr(years, field) or 0.0
                    d[field] = _clamped(base * ((1 + g) ** (fy - src)), base)
                    d["_method"][field] = f"backcast_cagr from FY{src}"
                d["_diag"].pop(field, None)
                filled_total += 1
                continue

            if rev:
                r = _sector_ratio(stats, sector, fy, ratio_name)
                if r is not None:
                    d[field] = rev * r
                    d["_method"][field] = f"sector_ratio ({ratio_name})"
                    d["_diag"].pop(field, None)
                    filled_total += 1

        # ---- identities, now that inputs may exist ----
        if (
            d.get("ebitda") is None
            and d.get("ebit") is not None
            and d.get("da") is not None
        ):
            d["ebitda"] = d["ebit"] + d["da"]
            d["_method"]["ebitda"] = "derived (EBIT + D&A)"
            d["_diag"].pop("ebitda", None)
            filled_total += 1

        if d.get("eps") is None and d.get("net_income") is not None and d.get("shares"):
            d["eps"] = d["net_income"] / d["shares"]
            d["_method"]["eps"] = "derived (Net Income / Shares)"
            d["_diag"].pop("eps", None)
            filled_total += 1

        if d.get("delta_nwc") is None:
            d["delta_nwc"] = 0.0
            d["_method"]["delta_nwc"] = "assumed zero"
        if d.get("tax_rate") is None:
            d["tax_rate"] = config.DEFAULT_TAX_RATE
            d["_method"]["tax_rate"] = "statutory rate"

        if d["_method"]:
            d["_notes"].append("estimated fields: " + ", ".join(sorted(d["_method"])))

    return filled_total


def fill_universe(universe):
    if config.ESTIMATION_MODE == "off":
        return 0
    stats = build_sector_stats(universe)
    total = sum(fill_company(rec, stats) for rec in universe.values())
    if total:
        print(
            f"[estimate] filled {total} missing field(s) across "
            f"{len(universe)} companies (mode='{config.ESTIMATION_MODE}')"
        )
    return total


def normalised(years, fy, field):
    """
    Median of the field's positive values up to and including fy.
    Used when one year is loss-making but the business is not.
    -> (value, n_years) or (None, 0)
    """
    if not config.USE_NORMALISED_EARNINGS:
        return None, 0
    vals = [
        d[field]
        for y, d in years.items()
        if y <= fy and d.get(field) is not None and d[field] > 0
    ]
    if len(vals) < config.NORMALISED_MIN_YEARS:
        return None, 0
    return statistics.median(vals), len(vals)


def method_of(d, *fields):
    """Join methods used for the given fields, or None if all were fetched."""
    m = (d or {}).get("_method", {})
    used = [f"{f}={m[f]}" for f in fields if f in m]
    return "; ".join(used) if used else None
