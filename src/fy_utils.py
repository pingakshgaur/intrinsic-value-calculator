"""Financial-year date maths + tiny helpers."""

import datetime as dt
import math
import config


def fy_window(fy: int):
    """FY2025 -> (2024-04-01, 2025-03-31)"""
    return (
        dt.date(fy - 1, config.FY_START_MONTH, config.FY_START_DAY),
        dt.date(fy, config.FY_END_MONTH, config.FY_END_DAY),
    )


def fy_end(fy: int) -> dt.date:
    return dt.date(fy, config.FY_END_MONTH, config.FY_END_DAY)


def fy_label(fy: int) -> str:
    """
    FY2024 -> '2023-24'.  Display only; the internal key stays the integer.

    Note the convention this codebase already uses, set by fy_window(): FY_n
    ENDS in March of year n. So config.FY_LIST = [2021..2025] spans the five
    years 2020-21 through 2024-25. If the thesis is meant to report 2021-22
    through 2025-26, FY_LIST must become [2022..2026] - the label style does
    not shift the data, it only renames it.
    """
    if getattr(config, "FY_LABEL_STYLE", "range") != "range":
        return str(fy)
    return f"{fy - 1}-{str(fy)[-2:]}"


def assessment_fy(fy: int) -> int:
    """The FY whose traded prices score FY_t's intrinsic value."""
    return fy + getattr(config, "BENCHMARK_OFFSET_YEARS", 1)


def assessment_window(fy: int):
    """Date span of the assessment year for FY_t."""
    return fy_window(assessment_fy(fy))


def fy_of_date(d: dt.date) -> int:
    """Which Indian FY does a calendar date fall in? Mar-2025 -> FY2025."""
    return d.year + 1 if d.month >= config.FY_START_MONTH else d.year


def fy_for_period_end(period_end: dt.date, period_days: int = 365) -> int:
    """
    Map a statement period-end to an Indian financial year using the MIDPOINT
    of the reporting period.

    Why the midpoint and not the end date: not every Indian company reports
    April-March. Siemens Ltd runs October-September; a period ending
    30-Sep-2024 covers Oct-2023 to Sep-2024, whose midpoint is Mar-2024, so it
    belongs to FY2024. Matching on the end date alone would either reject it
    outright or shift it a full year.
    """
    midpoint = period_end - dt.timedelta(days=period_days // 2)
    return fy_of_date(midpoint)


def num(x):
    """Coerce anything to a clean float, else None."""
    try:
        if x is None:
            return None
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def money(v):
    return "N/A" if v is None else f"{config.CURRENCY_SYMBOL}{v:,.2f}"
