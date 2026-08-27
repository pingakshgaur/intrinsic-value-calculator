# FILE: yf_source.py
"""
yfinance extraction layer with per-field diagnosis.

Hard rule unchanged: only the fields the three models consume are returned.
Every field that comes back None also records WHY, in d["_diag"][field] as a
(code, detail) tuple.

Three price fields, and they are NOT interchangeable:
    price        in-FY mean. The valuation ANCHOR the models consume.
    price_fwd    mean price of FY+1. Numerator of the ML forward-ratio label.
    price_bench  close on the trading day NEAREST 1 May following FY end. The
                BENCHMARK every model is scored against. Never an input.

A fourth, d["price_bench_date"], carries the ISO date the benchmark close was
actually taken from, so the Methods sheet and the numeric twin can state it
rather than leave the reader to assume 1 May was a trading day. It usually
is not.
"""

import datetime as dt
import importlib
import logging

import pandas as pd
import yfinance as yf

import config
import nse_source
import overrides
from result import R
from fy_utils import (
    fy_window,
    fy_for_period_end,
    benchmark_date,
    assessment_fy,
    assessment_window,
    num,
    clamp,
)

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
    "price_bench",
    "price_bench_date",
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


def _fiscal_map(df):
    """
    Map every statement column to an Indian FY using the period midpoint.
    Handles non-March fiscal year-ends (Siemens runs Oct-Sep).
    -> ({fy: column}, note_or_None)
    """
    if df is None or df.empty:
        return {}, None

    dated = []
    for c in df.columns:
        try:
            dated.append((pd.Timestamp(c).tz_localize(None), c))
        except Exception:
            continue
    if not dated:
        return {}, None
    dated.sort()

    # infer the reporting period length from consecutive columns
    if len(dated) >= 2:
        gaps = [(dated[i][0] - dated[i - 1][0]).days for i in range(1, len(dated))]
        period_days = (
            int(min(g for g in gaps if g > 200)) if any(g > 200 for g in gaps) else 365
        )
    else:
        period_days = 365

    mapping, note = {}, None
    months = set()
    for ts, col in dated:
        months.add(ts.month)
        fy = fy_for_period_end(ts.date(), period_days)
        mapping[fy] = col

    if months and months != {config.FY_END_MONTH}:
        m = sorted(months)[0]
        note = (
            f"company reports a fiscal year ending in month {m}, not March; "
            f"periods mapped to Indian FYs by period midpoint"
        )
    return mapping, note


def _col_for_fy(fmap, fy, available):
    """-> (column, error_detail). fmap comes from _fiscal_map."""
    if not fmap:
        return None, "statement unavailable"
    if fy in fmap:
        return fmap[fy], None
    return None, (
        f"no reporting period maps to FY{fy} "
        f"(source provides FY{min(fmap)}-FY{max(fmap)}) - {DEPTH_HINT}"
    )


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


def _nearest_session(series, target):
    """
    Position of the trading day closest to `target`.

    Ties break in favour of the LATER date: if 30 April and 2 May are both one
    day out, 2 May wins. Arbitrary but deterministic, and stating it in the
    thesis is a one-line footnote rather than an unexplained asymmetry.

    -> (positional index, signed offset in days). Offset is negative when the
    chosen session precedes the target.
    """
    t = pd.Timestamp(target)
    idx = series.index.normalize()
    best = min(
        range(len(idx)),
        key=lambda i: (abs((idx[i] - t).days), -((idx[i] - t).days)),
    )
    return best, int((idx[best] - t).days)


def _benchmark_price_for_fy(closes, closes_err, fy, diag, notes):
    """
    Benchmark price for FY_t = the traded close on the trading day NEAREST to
    1 May of the calendar year in which FY_t ends.

        FY2024 intrinsic value   (fundamentals Apr-2023 .. Mar-2024)
        is scored against        (close nearest 1-May-2024)

    The date sits one month after the fundamentals window closes, so this price
    is an out-of-sample OUTCOME. It is never fed back into any model -
    d["price"] remains the valuation anchor for WACC, the observed multiples
    and the ML features. Conflating the two would put a post-FY price inside
    this year's P/E, which is the exact look-ahead the specification forbids.

    Why a single dated close rather than an annual aggregate: an aggregate over
    the whole following year mixes twelve months of unrelated news into the
    figure the valuation is judged against, and if the aggregate is a maximum
    it is not a central value at all - it forced a constant negative bias into
    every model. One dated price is what a share actually changed hands at,
    and all six models face the identical number.

    Why the NEAREST session rather than the next one forward: 1 May is
    Maharashtra Day and the exchanges are closed; it also lands on a weekend
    two years in seven. Rolling strictly forward would systematically pick a
    later date than rolling to the nearest, introducing a small directional
    drift for no benefit. 30 April is as valid an observation as 2 May.

    Yahoo back-adjusts OHLC for splits and bonus issues regardless of
    auto_adjust (that flag governs dividend adjustment only), so a split
    between the FY end and the benchmark date will not produce a phantom jump.

    -> (value, iso_date_string) or (None, None)
    """
    basis = getattr(config, "BENCHMARK_BASIS", "may1")

    if closes is None or len(closes) == 0:
        diag["price_bench"] = (
            R.PRICE_MISSING,
            closes_err or "no price history from yfinance or NSE portal",
        )
        return None, None

    series = closes.dropna()
    if series.empty:
        diag["price_bench"] = (
            R.PRICE_MISSING,
            closes_err or "price history contains no non-NaN closes",
        )
        return None, None

    # ------------------------------------------------------------------
    # Default basis: single dated close nearest 1 May
    # ------------------------------------------------------------------
    if basis == "may1":
        target = benchmark_date(fy)
        max_off = int(getattr(config, "BENCHMARK_MAX_OFFSET_DAYS", 10))

        pos, offset = _nearest_session(series, target)

        if abs(offset) > max_off:
            have = f"{series.index.min().date()} to {series.index.max().date()}"
            diag["price_bench"] = (
                R.PRICE_MISSING,
                f"no trading session within {max_off} day(s) of the benchmark "
                f"date {target}; the nearest available close is "
                f"{abs(offset)} day(s) away. Price history covers {have}. "
                f"Either the scrip listed after this date, it was suspended "
                f"around it, or {target} has not been reached yet.",
            )
            return None, None

        value = num(series.iloc[pos])
        when = series.index[pos].normalize().date()

        if value is None:
            diag["price_bench"] = (
                R.PRICE_MISSING,
                f"the close on {when}, nearest to benchmark date {target}, "
                f"is blank/NaN in the price history",
            )
            return None, None

        if offset == 0:
            notes.append(
                f"FY{fy} benchmark = close on {when}, "
                f"{config.CURRENCY_SYMBOL}{value:,.2f} (1 May, exact match)"
            )
        else:
            side = "after" if offset > 0 else "before"
            notes.append(
                f"FY{fy} benchmark = close on {when}, "
                f"{config.CURRENCY_SYMBOL}{value:,.2f} - the nearest trading "
                f"day to {target}, {abs(offset)} day(s) {side}. 1 May is "
                f"Maharashtra Day, a market holiday, so an exact match is "
                f"the exception rather than the rule."
            )

        return value, when.isoformat()

    # ------------------------------------------------------------------
    # Robustness bases: aggregate over the whole assessment year
    # ------------------------------------------------------------------
    a_fy = assessment_fy(fy)
    start, end = assessment_window(fy)

    window = series[
        (series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))
    ]

    if window.empty:
        have = f"{series.index.min().date()} to {series.index.max().date()}"
        diag["price_bench"] = (
            R.PRICE_MISSING,
            f"no traded prices in the FY{a_fy} assessment window "
            f"({start} to {end}); history available only for {have}. "
            f"If {end} is still in the future this year cannot be scored yet.",
        )
        return None, None

    n = len(window)
    floor = getattr(config, "MIN_SESSIONS_FOR_BENCHMARK", 60)
    if n < floor:
        diag["price_bench"] = (
            R.PRICE_MISSING,
            f"only {n} session(s) in the FY{a_fy} assessment window "
            f"({window.index.min().date()} to {window.index.max().date()}); "
            f"an annual aggregate over fewer than {floor} sessions is not an "
            f"annual aggregate. Either the assessment year is still running "
            f"or the scrip was suspended.",
        )
        return None, None

    if basis == "mean":
        value = float(window.mean())
        when = window.index[-1].normalize().date()
        notes.append(
            f"FY{fy} benchmark = mean of {n} sessions in assessment year "
            f"FY{a_fy} ({start} to {end}) [robustness basis, not the default]"
        )
    elif basis == "close":
        value = float(window.iloc[-1])
        when = window.index[-1].normalize().date()
        notes.append(
            f"FY{fy} benchmark = final close of assessment year FY{a_fy} "
            f"on {when} [robustness basis, not the default]"
        )
    else:
        diag["price_bench"] = (
            R.CALC_ERROR,
            f"unknown BENCHMARK_BASIS {basis!r}; expected 'may1', 'mean' "
            f"or 'close'",
        )
        return None, None

    full = getattr(config, "BENCHMARK_FULL_YEAR_SESSIONS", 200)
    if n < full:
        notes.append(
            f"FY{fy} benchmark drawn from a PARTIAL assessment year "
            f"({n} sessions, first {window.index.min().date()}); the aggregate "
            f"does not cover a full year and is not comparable to peers."
        )

    return num(value), when.isoformat()


def fetch_company(ticker: str, fy_list=None) -> dict:
    fy_list = fy_list or config.FY_LIST
    try:
        yf = importlib.import_module("yfinance")
        t = yf.Ticker(ticker)
    except ImportError:
        t = yf.Ticker(ticker)

    inc, inc_err = _safe_statement(t, "income_stmt", "income statement")
    bs, bs_err = _safe_statement(t, "balance_sheet", "balance sheet")
    cf, cf_err = _safe_statement(t, "cashflow", "cash flow statement")

    # ---- prices ----
    p_start = fy_window(min(fy_list))[0] - dt.timedelta(days=10)
    # +1 year: the ML label still needs the mean price of the FY AFTER the last
    # one. The 1-May benchmark for the last FY falls a month after that FY ends
    # and is comfortably inside this window.
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

    inc_map, inc_note = _fiscal_map(inc)
    bs_map, bs_note = _fiscal_map(bs)
    cf_map, cf_note = _fiscal_map(cf)
    fiscal_note = inc_note or bs_note or cf_note

    out = {"ticker": ticker, "beta": beta, "years": {}}

    for fy in fy_list:
        ic, ic_err = _col_for_fy(inc_map, fy, inc)
        bc, bc_err = _col_for_fy(bs_map, fy, bs)
        cc, cc_err = _col_for_fy(cf_map, fy, cf)
        d = {k: None for k in FIELDS}
        diag, notes = {}, []
        if fiscal_note:
            notes.append(fiscal_note)

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
        # 1-May benchmark -> the "Market Price" column and every difference
        # column. Never an input to any model.
        d["price_bench"], d["price_bench_date"] = _benchmark_price_for_fy(
            closes, closes_err, fy, diag, notes
        )
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

        # ---- manual overrides always win ----
        overrides.apply(ticker, fy, d, diag, notes)

        d["_diag"] = diag
        d["_notes"] = notes
        out["years"][fy] = d

    return out
