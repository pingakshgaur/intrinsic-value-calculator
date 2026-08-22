"""Financial-year date maths + tiny helpers."""

import datetime as dt
import math
import config


def fy_window(fy: int):
    """FY2025 -> (2024-04-01, 2025-03-31)"""
    start = dt.date(fy - 1, config.FY_START_MONTH, config.FY_START_DAY)
    end = dt.date(fy, config.FY_END_MONTH, config.FY_END_DAY)
    return start, end


def fy_end(fy: int) -> dt.date:
    return dt.date(fy, config.FY_END_MONTH, config.FY_END_DAY)


def num(x):
    """Coerce anything to a clean float, else None."""
    try:
        if x is None:
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def money(v):
    if v is None:
        return "N/A"
    return f"{config.CURRENCY_SYMBOL}{v:,.2f}"
