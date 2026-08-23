"""
Manual fundamentals override layer.

data/fundamentals_override.csv ALWAYS wins. This is the only guaranteed route
to a complete FY2021-FY2025 panel, because yfinance serves roughly four annual
periods and no free automated source fills the rest reliably.

Format - one row per company-year, blank cells simply ignored:

    ticker,fy,ebit,ebitda,eps,net_income,da,capex,delta_nwc,ocf,
    total_debt,cash,shares,revenue,assets,cur_liab,equity

Units: absolute rupees for money fields (not crore, not lakh), rupees per
share for eps, absolute count for shares. Get them from Screener.in's
"Balance Sheet" / "Cash Flow" / "Profit & Loss" tabs, or the annual report.
"""

import csv
import logging

import config
from fy_utils import num
from result import R

log = logging.getLogger(__name__)

FIELDS = [
    "ebit",
    "ebitda",
    "eps",
    "net_income",
    "da",
    "capex",
    "delta_nwc",
    "ocf",
    "total_debt",
    "cash",
    "shares",
    "revenue",
    "assets",
    "cur_liab",
    "equity",
]

HEADER = ["ticker", "fy"] + FIELDS

_cache = None


def load():
    """-> {(TICKER, fy): {field: float}}  Loaded once, cached."""
    global _cache
    if _cache is not None:
        return _cache

    _cache = {}
    path = config.OVERRIDE_FILE
    if not config.USE_OVERRIDES or not path.exists():
        return _cache

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                norm = {
                    (k or "").strip().lower(): (v or "").strip()
                    for k, v in row.items()
                    if isinstance(k, str)
                }
                tk = (norm.get("ticker") or "").upper()
                fy = num(norm.get("fy"))
                if not tk or fy is None:
                    continue
                vals = {}
                for fld in FIELDS:
                    v = num(norm.get(fld))
                    if v is not None:
                        vals[fld] = v
                if vals:
                    _cache[(tk, int(fy))] = vals
    except Exception as e:
        log.exception("override file unreadable")
        print(f"[override] could not read {path}: {type(e).__name__}: {e}")
        return _cache

    n_cells = sum(len(v) for v in _cache.values())
    if _cache:
        print(
            f"[override] loaded {n_cells} manual value(s) across "
            f"{len(_cache)} company-year(s) from {path.name}"
        )
    return _cache


def apply(ticker, fy, d, diag, notes):
    """
    Fill any missing field from the override sheet, in place.
    Returns the number of fields supplied.
    """
    table = load()
    vals = table.get((ticker.upper(), int(fy)))
    if not vals:
        return 0

    filled = []
    for fld, v in vals.items():
        if fld not in d:
            continue
        if d.get(fld) is None:
            d[fld] = v
            diag.pop(fld, None)
            filled.append(fld)

    if filled:
        notes.append(
            f"manually supplied from {config.OVERRIDE_FILE.name}: "
            f"{', '.join(sorted(filled))}"
        )
        # derived fields may now be computable
        if (
            d.get("ebitda") is None
            and d.get("ebit") is not None
            and d.get("da") is not None
        ):
            d["ebitda"] = d["ebit"] + d["da"]
            diag.pop("ebitda", None)
        if d.get("eps") is None and d.get("net_income") and d.get("shares"):
            d["eps"] = d["net_income"] / d["shares"]
            diag.pop("eps", None)
    return len(filled)


def ensure_template_exists():
    """Create an empty, correctly-headed override file if none is present."""
    path = config.OVERRIDE_FILE
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerow(HEADER)
    return True
