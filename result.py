"""
Result carrier + reason vocabulary.

Every value that can fail is wrapped in a Result. When it fails it carries a
CODE (stable, greppable) and a DETAIL (human, specific). The spreadsheet prints
that instead of leaving the cell empty.
"""

from dataclasses import dataclass
from typing import Optional
import config


class R:
    """Reason codes. Keep these stable - you can pivot/filter on them later."""

    TICKER = "TICKER NOT RESOLVED"
    FETCH_FAILED = "FETCH FAILED"
    SOURCE_DOWN = "SOURCE UNAVAILABLE"
    NO_PERIOD = "NO DATA FOR THIS FY"
    FIELD_MISSING = "FIELD MISSING"
    PRICE_MISSING = "PRICE UNAVAILABLE"
    NOT_MEANINGFUL = "NOT MEANINGFUL"
    NO_PEERS = "NO PEER BENCHMARK"
    NEG_EQUITY = "NEGATIVE EQUITY VALUE"
    CALC_ERROR = "CALCULATION ERROR"
    NOT_COMPUTABLE = "NOT COMPUTABLE"
    MODEL_NA = "MODEL NOT APPLICABLE"
    NO_TRAINING_DATA = "INSUFFICIENT TRAINING DATA"
    NO_LABEL         = "NO FORWARD PRICE"
    FEATURES_MISSING = "FEATURES INCOMPLETE"
    LIB_MISSING      = "LIBRARY NOT INSTALLED"
    IMPLAUSIBLE      = "PREDICTION OUT OF BAND"


@dataclass
class Result:
    value: Optional[float] = None
    code: Optional[str] = None
    detail: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.value is not None

    @classmethod
    def good(cls, value):
        return cls(value=float(value))

    @classmethod
    def bad(cls, code, detail=""):
        return cls(value=None, code=code, detail=detail)

    def text(self) -> str:
        """What goes in the cell when there is no number."""
        if self.ok:
            return f"{config.CURRENCY_SYMBOL}{self.value:,.2f}"
        if not config.SHOW_REASONS:
            return "N/A"
        if config.REASON_STYLE == "short" or not self.detail:
            return self.code or "N/A"
        return f"{self.code}: {self.detail}"


# ---------- helpers used by every model ----------
def field_result(year_data: dict, field: str, fy: int, label: str) -> Result:
    """Turn a raw field into a Result, pulling the recorded diagnosis if absent."""
    if not year_data:
        return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")
    v = year_data.get(field)
    if v is not None:
        return Result.good(v)
    diag = year_data.get("_diag", {})
    if field in diag:
        code, detail = diag[field]
        return Result.bad(code, detail)
    return Result.bad(R.FIELD_MISSING, f"{label} unavailable for FY{fy}")


def require(year_data: dict, field: str, fy: int, label: str):
    """-> (value, None) on success, (None, Result) on failure."""
    res = field_result(year_data, field, fy, label)
    return (res.value, None) if res.ok else (None, res)
