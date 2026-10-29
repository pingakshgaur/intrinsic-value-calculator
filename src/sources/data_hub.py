# FILE: src/sources/data_hub.py
"""
One company's accounts and prices from every data provider, merged.

    fetch_company(ticker, fy_list) -> the same shape yf_source.fetch_company returns

1. Yahoo Finance (yf_source) goes first: its statements carry a reason for
   every missing field, and its price history falls back through price_chain
   (Yahoo BSE, NSE, BSE, key-based providers) when Yahoo has no prices.
2. Every field still missing - or only assumed (zero debt, statutory tax,
   today's share count) - is then asked of the statement providers in the
   order set in Configuration -> Data sources: Screener.in (ten-plus years),
   Yahoo's BSE listing, Financial Modeling Prep, EODHD.
3. If Yahoo fails outright, the company is built from the other providers
   alone instead of being dropped.

The first provider with a figure wins; manual overrides (data/fundamentals_
override.csv) still beat everything. Each year's notes say which provider
filled what, so the report's diagnostics stay honest about where a number
came from.
"""

import datetime as dt
import logging
import time

import config
import keyed_sources
import overrides
import price_chain
import screener_source
import source_settings
import yf_source
from fy_utils import fy_window
from result import R

log = logging.getLogger(__name__)

# fields a statement provider can fill (prices come from price_chain)
FILLABLE = ["ebit", "ebitda", "eps", "net_income", "da", "capex", "delta_nwc", "ocf", "total_debt", "cash",
            "shares", "revenue", "assets", "cur_liab", "equity", "tax_rate"]
# what each assumption wrote into the notes, so a reported figure can retire it
ASSUMED_NOTE = {"total_debt": "total debt not reported", "cash": "cash balance not reported",
                "delta_nwc": "change in working capital not reported", "tax_rate": "effective tax rate not derivable",
                "shares": "shares outstanding taken from current profile"}
ML_ONLY = ("revenue", "assets", "cur_liab", "equity")


def _bse_statements(ticker):
    bo = ticker.split(".")[0].upper() + ".BO"
    if bo == ticker.upper():
        return {}
    got = yf_source.fetch_company(bo, config.FY_LIST, with_prices=False)
    return {fy: {k: v for k, v in d.items() if k in FILLABLE and v is not None and k not in d.get("_assumed", [])}
            for fy, d in got.get("years", {}).items()}


STATEMENTS = {"screener": screener_source.fetch, "yahoo_bse": _bse_statements, **keyed_sources.STATEMENTS}
# what each one can fill: a provider is not asked when only fields it never has are missing
CAN = {"screener": {"revenue", "ebit", "ebitda", "da", "net_income", "eps", "tax_rate", "total_debt", "equity", "assets", "ocf", "shares", "capex"}}


def _missing(d):
    return [k for k in FILLABLE if d.get(k) is None or k in d.get("_assumed", [])]


def _skeleton(ticker, fy_list, reason):
    """Every field empty, with the reason; prices from the chain. Used when Yahoo is off or fails."""
    p_start = fy_window(min(fy_list))[0] - dt.timedelta(days=10)
    p_end = fy_window(max(fy_list) + 1)[1] + dt.timedelta(days=5)
    closes, used, problems = price_chain.closes(ticker, p_start, p_end, skip=("yahoo",))
    err = None if closes is not None else "; ".join(problems) or "no provider returned prices"
    out = {"ticker": ticker, "beta": config.DEFAULT_BETA, "years": {},
           "price_source": source_settings.BY_KEY[used]["label"] if used else None}
    for fy in fy_list:
        d = {k: None for k in yf_source.FIELDS}
        d["_assumed"] = []
        diag = {k: (R.SOURCE_DOWN, reason) for k in ("ebit", "ebitda", "eps", "net_income", "da", "capex", "ocf", "shares")}
        notes = [f"Yahoo Finance unavailable ({reason}); built from the other data providers"]
        if used:
            notes.append(f"prices from {source_settings.BY_KEY[used]['label']}")
        d["price"] = yf_source._price_for_fy(closes, err, fy, diag, notes)
        d["price_bench"], d["price_bench_date"] = yf_source._benchmark_price_for_fy(closes, err, fy, diag, notes)
        d["price_fwd"] = yf_source._price_for_fy(closes, err, fy + 1, {}, [])
        d["_diag"], d["_notes"] = diag, notes
        out["years"][fy] = d
    return out


def _finish(ticker, fy, d):
    """Overrides first, then the derivations and assumptions yf_source makes, for a year a provider (partly) filled."""
    diag, notes, assumed = d["_diag"], d["_notes"], d["_assumed"]
    # the override sheet beats every provider and every assumption
    forced = []
    for k, v in (overrides.load().get((ticker.upper(), int(fy))) or {}).items():
        if k in d and v is not None and d.get(k) != v:
            d[k] = v
            diag.pop(k, None)
            if k in assumed:
                assumed.remove(k)
            forced.append(k)
    if forced and not any(n.startswith("manually supplied") for n in notes):
        notes.append(f"manually supplied from {config.OVERRIDE_FILE.name}: {', '.join(sorted(forced))}")
    if d.get("ebitda") is None and d.get("ebit") is not None and d.get("da") is not None:
        d["ebitda"] = d["ebit"] + d["da"]
        diag.pop("ebitda", None)
        notes.append("EBITDA derived as EBIT + D&A")
    if d.get("eps") is None and d.get("net_income") and d.get("shares"):
        d["eps"] = d["net_income"] / d["shares"]
        diag.pop("eps", None)
        notes.append("EPS derived as Net Income / Shares")
    for k, zero, note in (("total_debt", 0.0, "total debt not reported; assumed zero (debt-free)"),
                          ("cash", 0.0, "cash balance not reported; assumed zero"),
                          ("delta_nwc", 0.0, "change in working capital not reported; treated as zero"),
                          ("tax_rate", config.DEFAULT_TAX_RATE, f"effective tax rate not derivable; used statutory {config.DEFAULT_TAX_RATE:.2%}")):
        if d.get(k) is None:
            d[k] = zero
            if k not in assumed:
                assumed.append(k)
                notes.append(note)
            diag.pop(k, None)
    for k in ML_ONLY:
        diag.pop(k, None)


def fetch_company(ticker, fy_list=None):
    fy_list = fy_list or config.FY_LIST
    order = source_settings.enabled()
    data = None
    if "yahoo" in order:
        try:
            data = yf_source.fetch_company(ticker, fy_list)
        except Exception as e:  # noqa: BLE001 - the other providers can still build the company
            log.exception("Yahoo Finance failed for %s", ticker)
            data = _skeleton(ticker, fy_list, f"{type(e).__name__}: {e}")
    else:
        data = _skeleton(ticker, fy_list, "switched off in Configuration -> Data sources")

    used = {"Yahoo Finance"} if "yahoo" in order else set()
    years = data["years"]
    for key in source_settings.enabled("statements"):
        if key == "yahoo" or key not in STATEMENTS:
            continue
        can = CAN.get(key, set(FILLABLE))
        want = {fy: [k for k in _missing(d) if k in can] for fy, d in years.items()}
        if not any(want.values()):
            continue
        try:
            got = STATEMENTS[key](ticker) or {}
        except Exception as e:  # noqa: BLE001
            log.info("%s failed for %s: %s", key, ticker, e)
            got = {}
        label = source_settings.BY_KEY[key]["label"]
        for fy, fields in want.items():
            src = got.get(fy) or {}
            took = []
            for k in fields:
                v = src.get(k)
                if v is None:
                    continue
                d = years[fy]
                was_assumed = k in d["_assumed"]
                d[k] = abs(v) if k == "capex" else v
                d["_diag"].pop(k, None)
                if was_assumed:
                    d["_assumed"].remove(k)
                    d["_notes"] = [n for n in d["_notes"] if not n.startswith(ASSUMED_NOTE.get(k, "\0"))]
                took.append(k)
            if took:
                est = [k for k in took if k in src.get("_estimated", [])]
                years[fy]["_notes"].append(f"filled from {label}: {', '.join(sorted(took))}"
                                           + (f" ({', '.join(est)} estimated)" if est else ""))
                used.add(label)
        if got and not config.OFFLINE:
            time.sleep(config.REQUEST_PAUSE)

    for fy, d in years.items():
        _finish(ticker, fy, d)
    data["sources"] = sorted(used) + ([data["price_source"]] if data.get("price_source") and data["price_source"] not in used else [])
    return data
