"""
Result carrier + reason vocabulary.

Every value that can fail is wrapped in a Result. On failure it carries a stable
CODE and a specific DETAIL. On success it may carry a METHOD, which is set only
when the value was estimated rather than computed from reported figures.
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
    NO_LABEL = "NO FORWARD PRICE"
    FEATURES_MISSING = "FEATURES INCOMPLETE"
    LIB_MISSING = "LIBRARY NOT INSTALLED"
    IMPLAUSIBLE = "PREDICTION OUT OF BAND"


@dataclass
class Result:
    value: Optional[float] = None
    code: Optional[str] = None
    detail: Optional[str] = None
    method: Optional[str] = None  # None = computed from reported figures

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def estimated(self) -> bool:
        return self.ok and self.method is not None

    @classmethod
    def good(cls, value, method=None):
        return cls(value=float(value), method=method)

    @classmethod
    def bad(cls, code, detail=""):
        return cls(value=None, code=code, detail=detail)

    def text(self) -> str:
        """Cell content for the MAIN report."""
        if self.ok:
            mark = config.ESTIMATE_MARKER if self.estimated else ""
            return f"{config.CURRENCY_SYMBOL}{self.value:,.2f}{mark}"
        if not config.SHOW_REASONS:
            return ""
        if config.REASON_STYLE == "detailed" and self.detail:
            return f"{self.code}: {self.detail}"
        return self.code or ""

    def full(self) -> str:
        """Provenance or failure text, for the auxiliary sheets."""
        if self.ok:
            return f"estimated via {self.method}" if self.estimated else "fetched"
        return f"{self.code}: {self.detail}" if self.detail else (self.code or "")


# ---------- helpers used by every model ----------
def field_result(year_data: dict, field: str, fy: int, label: str) -> Result:
    """Turn a raw field into a Result, pulling the recorded diagnosis if absent."""
    if not year_data:
        return Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")
    v = year_data.get(field)
    if v is not None:
        method = (year_data.get("_method") or {}).get(field)
        return Result.good(v, method=method)
    diag = year_data.get("_diag", {})
    if field in diag:
        code, detail = diag[field]
        return Result.bad(code, detail)
    return Result.bad(R.FIELD_MISSING, f"{label} unavailable for FY{fy}")


def require(year_data: dict, field: str, fy: int, label: str):
    """-> (value, None) on success, (None, Result) on failure."""
    res = field_result(year_data, field, fy, label)
    return (res.value, None) if res.ok else (None, res)
