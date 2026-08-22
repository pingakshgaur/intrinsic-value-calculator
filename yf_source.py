"""
yfinance extraction layer with per-field diagnosis.

Hard rule unchanged: only the fields the three models consume are returned.
New: every field that comes back None also records WHY, in d["_diag"][field]
as a (code, detail) tuple.
"""

import datetime as dt
import importlib
import logging
import pandas as pd

import config
import nse_source
from result import R
from fy_utils import fy_window, fy_end, num, clamp
import yfinance as yf

log = logging.getLogger(__name__)

INCOME_ALIASES = {
    "ebit": ["EBIT", "Operating Income", "Total Operating Income As Reported"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "net_income": [
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
    ],
    "eps": ["Diluted EPS", "Basic EPS"],
    "pretax": ["Pretax Income"],
    "tax_provision": ["Tax Provision"],
    "revenue": ["Total Revenue", "Operating Revenue"],
}
BALANCE_ALIASES = {
    "total_debt": [
        "Total Debt",
        "Long Term Debt And Capital Lease Obligation",
        "Long Term Debt",
    ],
    "cash": [
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents",
    ],
    "shares": ["Ordinary Shares Number", "Share Issued"],
    "assets": ["Total Assets"],
    "cur_liab": ["Current Liabilities", "Total Current Liabilities"],
    "equity": ["Stockholders Equity", "Total Equity Gross Minority Interest"],
}
CASHFLOW_ALIASES = {
    "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
    "da": [
        "Depreciation And Amortization",
        "Depreciation Amortization Depletion",
        "Reconciled Depreciation",
    ],
    "cwc": ["Change In Working Capital"],
}

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
    "tax_rate",
    "price",
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
    "tax_rate",
    "price",
    "revenue",
    "assets",
    "cur_liab",
    "equity",
    "price_fwd",
]

DEPTH_HINT = (
    "source publishes only the latest ~4 fiscal periods, so this "
    "older year is not retrievable from yfinance"
)


def _safe_statement(ticker_obj, attr, label):
    """Return (DataFrame|None, error_detail|None)."""
    try:
        df = getattr(ticker_obj, attr)
        if df is None or df.empty:
            return None, f"{label} came back empty for this symbol"
        return df, None
    except Exception as e:
        log.exception("statement fetch failed: %s", label)
        return None, f"{label} download raised {type(e).__name__}: {e}"


def _row(df, aliases):
    for a in aliases:
        if a in df.index:
            return df.loc[a]
    return None


def _col_for_fy(df, fy, tolerance_days=100):
    if df is None or df.empty:
        return None, "statement unavailable"
    target = pd.Timestamp(fy_end(fy))
    best, best_gap = None, None
    for c in df.columns:
        try:
            ts = pd.Timestamp(c).tz_localize(None)
        except Exception:
            continue
        gap = abs((ts - target).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = c, gap
    if best is None:
        return None, "statement has no dated periods"
    if best_gap > tolerance_days:
        avail = ", ".join(sorted(str(pd.Timestamp(c).date()) for c in df.columns))
        return None, (
            f"no period ending near 31-Mar-{fy} (nearest is {best_gap} "
            f"days away; available periods: {avail}) - {DEPTH_HINT}"
        )
    return best, None


def _pick(df, df_err, aliases, col, col_err, label, fy, diag, key, human):
    """Extract one line item, recording the precise reason on failure."""
    if df is None:
        diag[key] = (R.SOURCE_DOWN, df_err or f"{label} unavailable")
        return None
    if col is None:
        diag[key] = (R.NO_PERIOD, f"{label}: {col_err}")
        return None
    row = _row(df, aliases)
    if row is None:
        diag[key] = (
            R.FIELD_MISSING,
            f"'{human}' line item is not reported in the {label} "
            f"(checked: {', '.join(aliases)})",
        )
        return None
    v = num(row.get(col))
    if v is None:
        diag[key] = (
            R.FIELD_MISSING,
            f"'{human}' is blank/NaN in the {label} for FY{fy}",
        )
        return None
    return v


def _price_for_fy(closes, closes_err, fy, diag, notes):
    """
    Market price for FY = mean of that financial year's daily closing prices.

    Yahoo's 'Close' is already back-adjusted for splits and bonus issues, so a
    1:2 split mid-year will not put a discontinuity in the mean. It is NOT
    dividend-adjusted, which is correct here: we want the price a share
    actually traded at, to compare against intrinsic value per share.
    """
    start, end = fy_window(fy)

    if closes is None or len(closes) == 0:
        diag["price"] = (
            R.PRICE_MISSING,
            closes_err or "no price history from yfinance or NSE portal",
        )
        return None

    window = closes[
        (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
    ].dropna()

    if window.empty:
        have = f"{closes.index.min().date()} to {closes.index.max().date()}"
        diag["price"] = (
            R.PRICE_MISSING,
            f"no traded closes between {start} and {end} "
            f"(history available only for {have}; listing may post-date "
            f"this FY or the scrip was suspended)",
        )
        return None

    n = len(window)
    if n < config.MIN_TRADING_DAYS_FOR_FY:
        diag["price"] = (
            R.PRICE_MISSING,
            f"only {n} trading session(s) inside FY{fy} "
            f"({window.index.min().date()} to {window.index.max().date()}); "
            f"a mean over fewer than {config.MIN_TRADING_DAYS_FOR_FY} "
            f"sessions is not a full-year average - the scrip most likely "
            f"listed part-way through this financial year",
        )
        return None

    if config.FY_MEAN_BASIS == "calendar":
        daily = window.resample("D").ffill()
        daily = daily[
            (daily.index >= pd.Timestamp(start)) & (daily.index <= pd.Timestamp(end))
        ]
        mean_price = daily.mean()
        basis = f"{len(daily)} calendar days (forward-filled from {n} sessions)"
    else:
        mean_price = window.mean()
        basis = f"{n} trading sessions"

    lo, hi = window.min(), window.max()
    notes.append(
        f"FY{fy} market price = mean of {basis}; "
        f"range {config.CURRENCY_SYMBOL}{lo:,.2f}-{config.CURRENCY_SYMBOL}{hi:,.2f}"
    )

    if n < config.PARTIAL_YEAR_SESSIONS:
        notes.append(
            f"FY{fy} price is a PARTIAL-year mean ({n} sessions, "
            f"first traded {window.index.min().date()}) - not comparable "
            f"to a full-year mean for peers"
        )

    return num(mean_price)


def fetch_company(ticker: str, fy_list=None) -> dict:
    fy_list = fy_list or config.FY_LIST
    try:
        yf = importlib.import_module("yfinance")
        t = yf.Ticker(ticker)
    except ImportError:
        t = None

    inc, inc_err = _safe_statement(t, "income_stmt", "income statement")
    bs, bs_err = _safe_statement(t, "balance_sheet", "balance sheet")
    cf, cf_err = _safe_statement(t, "cashflow", "cash flow statement")

    # ---- prices ----
    p_start = fy_window(min(fy_list))[0] - dt.timedelta(days=10)
    # +1 year: the ML label needs the mean price of the FY AFTER the last one
    p_end = fy_window(max(fy_list) + 1)[1] + dt.timedelta(days=5)
    closes, closes_err = None, None
    try:
        hist = t.history(
            start=p_start.isoformat(), end=p_end.isoformat(), auto_adjust=False
        )
        if hist is None or hist.empty:
            closes_err = "yfinance returned no price rows for this symbol"
        else:
            closes = hist["Close"]
            closes.index = pd.to_datetime(closes.index).tz_localize(None)
    except Exception as e:
        log.exception("price history failed for %s", ticker)
        closes_err = f"yfinance price download raised {type(e).__name__}: {e}"

    if closes is None or closes.dropna().empty:
        try:
            closes = nse_source.fetch_close_series(ticker, p_start, p_end)
            if closes is None or closes.empty:
                closes_err = (
                    (closes_err or "") + "; NSE portal fallback also returned nothing "
                    "(NSE blocks datacentre/VPN IPs)"
                )
                closes = None
        except Exception as e:
            log.exception("NSE fallback failed for %s", ticker)
            closes_err = f"{closes_err}; NSE fallback raised {type(e).__name__}: {e}"
            closes = None

    beta = config.DEFAULT_BETA
    fallback_shares = None
    try:
        info = t.info or {}
        b = num(info.get("beta"))
        if b and 0.1 < b < 3.0:
            beta = b
        fallback_shares = num(info.get("sharesOutstanding"))
    except Exception as e:
        log.warning("info block unavailable for %s: %s", ticker, e)

    out = {"ticker": ticker, "beta": beta, "years": {}}

    for fy in fy_list:
        ic, ic_err = _col_for_fy(inc, fy)
        bc, bc_err = _col_for_fy(bs, fy)
        cc, cc_err = _col_for_fy(cf, fy)
        d = {k: None for k in FIELDS}
        diag, notes = {}, []

        P = _pick
        d["ebit"] = P(
            inc,
            inc_err,
            INCOME_ALIASES["ebit"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "ebit",
            "EBIT / Operating Income",
        )
        d["ebitda"] = P(
            inc,
            inc_err,
            INCOME_ALIASES["ebitda"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "ebitda",
            "EBITDA",
        )
        d["net_income"] = P(
            inc,
            inc_err,
            INCOME_ALIASES["net_income"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "net_income",
            "Net Income",
        )
        d["eps"] = P(
            inc,
            inc_err,
            INCOME_ALIASES["eps"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "eps",
            "Diluted EPS",
        )

        d["total_debt"] = P(
            bs,
            bs_err,
            BALANCE_ALIASES["total_debt"],
            bc,
            bc_err,
            "balance sheet",
            fy,
            diag,
            "total_debt",
            "Total Debt",
        )
        d["cash"] = P(
            bs,
            bs_err,
            BALANCE_ALIASES["cash"],
            bc,
            bc_err,
            "balance sheet",
            fy,
            diag,
            "cash",
            "Cash & Equivalents",
        )
        d["shares"] = P(
            bs,
            bs_err,
            BALANCE_ALIASES["shares"],
            bc,
            bc_err,
            "balance sheet",
            fy,
            diag,
            "shares",
            "Ordinary Shares Number",
        )

        d["revenue"] = P(
            inc,
            inc_err,
            INCOME_ALIASES["revenue"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "revenue",
            "Total Revenue",
        )

        d["assets"] = P(
            bs,
            bs_err,
            BALANCE_ALIASES["assets"],
            bc,
            bc_err,
            "balance sheet",
            fy,
            diag,
            "assets",
            "Total Assets",
        )
        d["cur_liab"] = P(
            bs,
            bs_err,
            BALANCE_ALIASES["cur_liab"],
            bc,
            bc_err,
            "balance sheet",
            fy,
            diag,
            "cur_liab",
            "Current Liabilities",
        )
        d["price"] = _price_for_fy(closes, closes_err, fy, diag, notes)
        # forward-year mean price -> the ML label
        _fwd_diag, _fwd_notes = {}, []
        d["price_fwd"] = _price_for_fy(
            closes, closes_err, fy + 1, _fwd_diag, _fwd_notes
        )
        d["equity"] = P(
            bs,
            bs_err,
            BALANCE_ALIASES["equity"],
            bc,
            bc_err,
            "balance sheet",
            fy,
            diag,
            "equity",
            "Stockholders Equity",
        )

        d["ocf"] = P(
            cf,
            cf_err,
            CASHFLOW_ALIASES["ocf"],
            cc,
            cc_err,
            "cash flow statement",
            fy,
            diag,
            "ocf",
            "Operating Cash Flow",
        )
        capex_raw = P(
            cf,
            cf_err,
            CASHFLOW_ALIASES["capex"],
            cc,
            cc_err,
            "cash flow statement",
            fy,
            diag,
            "capex",
            "Capital Expenditure",
        )
        d["capex"] = abs(capex_raw) if capex_raw is not None else None
        d["da"] = P(
            cf,
            cf_err,
            CASHFLOW_ALIASES["da"],
            cc,
            cc_err,
            "cash flow statement",
            fy,
            diag,
            "da",
            "Depreciation & Amortisation",
        )
        cwc_raw = P(
            cf,
            cf_err,
            CASHFLOW_ALIASES["cwc"],
            cc,
            cc_err,
            "cash flow statement",
            fy,
            diag,
            "cwc",
            "Change In Working Capital",
        )
        if cwc_raw is None:
            d["delta_nwc"] = 0.0
            notes.append("change in working capital not reported; treated as zero")
            diag.pop("cwc", None)
        else:
            d["delta_nwc"] = -cwc_raw

        # --- non-fatal zero assumptions for capital structure ---
        if d["total_debt"] is None:
            d["total_debt"] = 0.0
            notes.append("total debt not reported; assumed zero (debt-free)")
        if d["cash"] is None:
            d["cash"] = 0.0
            notes.append("cash balance not reported; assumed zero")

        if d["shares"] is None and fallback_shares:
            d["shares"] = fallback_shares
            diag.pop("shares", None)
            notes.append(
                "shares outstanding taken from current profile, "
                "not the FY balance sheet (ignores later dilution/buybacks)"
            )

        for _k in ("revenue", "assets", "cur_liab", "equity"):
            diag.pop(_k, None)  # ML-only fields: absence must not block DCF/PE

        # --- effective tax rate ---
        pretax = P(
            inc,
            inc_err,
            INCOME_ALIASES["pretax"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "pretax",
            "Pretax Income",
        )
        taxp = P(
            inc,
            inc_err,
            INCOME_ALIASES["tax_provision"],
            ic,
            ic_err,
            "income statement",
            fy,
            diag,
            "tax_provision",
            "Tax Provision",
        )
        diag.pop("pretax", None)
        diag.pop("tax_provision", None)
        if pretax and taxp is not None and pretax > 0:
            d["tax_rate"] = clamp(taxp / pretax, 0.05, 0.45)
        else:
            d["tax_rate"] = config.DEFAULT_TAX_RATE
            notes.append(
                f"effective tax rate not derivable; used statutory "
                f"{config.DEFAULT_TAX_RATE:.2%}"
            )

        # --- derived gap-fills (clear the diagnosis if we succeed) ---
        if d["ebitda"] is None and d["ebit"] is not None and d["da"] is not None:
            d["ebitda"] = d["ebit"] + d["da"]
            diag.pop("ebitda", None)
            notes.append("EBITDA derived as EBIT + D&A")
        if d["eps"] is None and d["net_income"] and d["shares"]:
            d["eps"] = d["net_income"] / d["shares"]
            diag.pop("eps", None)
            notes.append("EPS derived as Net Income / Shares")

        if d["price_fwd"] is None:
            notes.append(
                f"no FY{fy + 1} mean price; this row cannot be used as "
                f"an ML training example"
            )

        d["_diag"] = diag
        d["_notes"] = notes
        out["years"][fy] = d

    return out
