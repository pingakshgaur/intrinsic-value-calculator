# FILE: src/sources/mock_source.py
"""
Offline synthetic dataset. Fires every reason code deterministically.
Usage:  python run.py --offline

Three price fields per year, and they are NOT interchangeable:

    price        in-FY mean. The valuation ANCHOR the models consume.
    price_fwd    mean price of FY+1. Numerator of the ML forward-ratio label.
    price_bench  close nearest 1 May following FY end. The BENCHMARK every
                model is scored against. 1 May of year `fy` sits one month
                into FY+1, so it is modelled here as a point early on the
                path from the FY mean to the FY+1 mean - which is where a
                real one lands.

A fourth, price_bench_date, mirrors the live source: 1 May 2024 was a
Wednesday but a market holiday, so the mock returns 2 May to exercise the
"nearest session, not exact" path through the exporter and Methods sheet.
"""

import config
from result import R

# Growth path -> FCFF CAGR of roughly 12%.
#
# This used to be a hard-coded dict keyed 2021..2025, which meant offline mode
# broke with a KeyError the moment the financial-year window moved. It is now
# derived from the company's position within config.FY_LIST, so the mock
# universe follows whatever range the user picked.
BASE_MULT = 0.70
YEARLY_GROWTH = 1.12


def _mult(fy):
    """Compound the growth path from the first year of the chosen window."""
    years = sorted(config.FY_LIST)
    first = years[0] if years else fy
    return BASE_MULT * (YEARLY_GROWTH ** (int(fy) - int(first)))


# The realised benchmark session. 1 May is Maharashtra Day and the exchanges
# are shut, and it lands on a weekend often enough besides, so the mock returns
# 2 May for every year - which exercises the "nearest session, not the exact
# date" path through the exporter and the Methods sheet.
def _bench_date(fy):
    return f"{int(fy)}-05-02"


def _bench(fy, m):
    """Price one month into FY+1: mostly the FY+1 level, slightly early."""
    nxt = _mult(fy + 1)
    return 500.0 * (0.25 * m + 0.75 * nxt)


def _y(fy, **kw):
    m = _mult(fy)
    d = {
        # revenue and equity were absent here, and both are named in
        # SUFFICIENCY_REQUIRED_FIELDS - so every mock company failed the gate
        # and offline mode could never produce a report at all.
        "revenue": 2.0e10 * m,
        "equity": 1.8e10 * m,
        "ebit": 3.5e9 * m,
        "ebitda": 4.0e9 * m,
        "eps": 25.0 * m,
        "net_income": 2.5e9 * m,
        "da": 5.0e8 * m,
        "capex": 8.0e8 * m,
        "delta_nwc": 1.0e8 * m,
        "ocf": 3.0e9 * m,
        "total_debt": 6.0e9,
        "cash": 2.0e9,
        "shares": 1.0e8,
        "tax_rate": 0.25,
        "price": 500.0 * m,
        # mean price of FY+1 -> the ML label
        "price_fwd": 500.0 * _mult(fy + 1),
        # close nearest 1 May following FY end -> the benchmark
        "price_bench": _bench(fy, m),
        "price_bench_date": _bench_date(fy),
        "_diag": {},
        "_notes": [],
    }
    d.update(kw)
    return d


def _blank(fy, reason, detail, keep_price=True):
    """A year where the statements are missing but the price may survive."""
    d = {
        k: None
        for k in (
            "revenue",
            "ebit",
            "ebitda",
            "eps",
            "net_income",
            "da",
            "capex",
            "ocf",
        )
    }
    m = _mult(fy)
    d.update(
        {
            "delta_nwc": 0.0,
            "total_debt": 0.0,
            "cash": 0.0,
            "equity": None,
            "shares": 1.0e8,
            "tax_rate": config.DEFAULT_TAX_RATE,
            "price": 500.0 * m if keep_price else None,
            "price_fwd": (500.0 * _mult(fy + 1)) if keep_price else None,
            "price_bench": _bench(fy, m) if keep_price else None,
            "price_bench_date": _bench_date(fy) if keep_price else None,
            "_diag": {
                k: (reason, detail)
                for k in (
                    "revenue",
                    "equity",
                    "ebit",
                    "ebitda",
                    "eps",
                    "net_income",
                    "da",
                    "capex",
                    "ocf",
                )
            },
            "_notes": [],
        }
    )
    if not keep_price:
        d["_diag"]["price"] = (R.PRICE_MISSING, detail)
        d["_diag"]["price_bench"] = (R.PRICE_MISSING, detail)
    return d


def _build():
    fys = config.FY_LIST
    u = {}

    # --- clean trio: one sector, full peer set, everything should value ---
    for name, beta in (
        ("MOCK CLEAN ALPHA", 0.9),
        ("MOCK CLEAN BETA", 1.1),
        ("MOCK CLEAN GAMMA", 1.0),
    ):
        u[name] = {
            "sector": "MockTech",
            "beta": beta,
            "years": {fy: _y(fy) for fy in fys},
        }

    # --- statement depth gap: FY2021-22 unavailable (the yfinance reality) ---
    u["MOCK DEPTH GAP"] = {
        "sector": "MockTech",
        "beta": 1.0,
        "years": {
            fy: (
                _y(fy)
                if fy >= 2023
                else _blank(
                    fy,
                    R.NO_PERIOD,
                    f"no period ending near 31-Mar-{fy}; source publishes "
                    f"only the latest ~4 fiscal periods",
                )
            )
            for fy in fys
        },
    }

    # --- loss maker: negative EPS and EBITDA from FY2023 ---
    u["MOCK LOSS MAKER"] = {
        "sector": "MockTech",
        "beta": 1.4,
        "years": {
            fy: (
                _y(fy)
                if fy <= 2022
                else _y(
                    fy,
                    eps=-8.0,
                    net_income=-8.0e8,
                    ebit=-1.2e9,
                    ebitda=-6.0e8,
                    ocf=-4.0e8,
                )
            )
            for fy in fys
        },
    }

    # --- alone in its sector AND no price at all -> NO PEERS + PRICE MISSING ---
    u["MOCK NO PRICE SOLO"] = {
        "sector": "MockSolo",
        "beta": 1.0,
        "years": {
            fy: _y(
                fy,
                price=None,
                price_bench=None,
                price_bench_date=None,
                _diag={
                    "price": (
                        R.PRICE_MISSING,
                        "scrip listed after this FY; no traded " "closes in the window",
                    ),
                    "price_bench": (
                        R.PRICE_MISSING,
                        f"no trading session within "
                        f"{getattr(config, 'BENCHMARK_MAX_OFFSET_DAYS', 10)} "
                        f"day(s) of the {fy}-05-01 benchmark date",
                    ),
                },
            )
            for fy in fys
        },
    }

    # --- leverage swamps enterprise value -> NEGATIVE EQUITY VALUE ---
    u["MOCK HEAVY DEBT"] = {
        "sector": "MockInfra",
        "beta": 1.6,
        "years": {fy: _y(fy, total_debt=5.0e11, cash=1.0e8) for fy in fys},
    }
    u["MOCK INFRA PEER"] = {
        "sector": "MockInfra",
        "beta": 1.2,
        "years": {fy: _y(fy) for fy in fys},
    }

    # --- bank-like: no EBITDA line reported at all ---
    u["MOCK BANK STYLE"] = {
        "sector": "MockFinance",
        "beta": 1.0,
        "years": {
            fy: _y(
                fy,
                ebitda=None,
                ebit=None,
                _diag={
                    "ebitda": (
                        R.FIELD_MISSING,
                        "'EBITDA' is not reported in the income "
                        "statement for a banking entity",
                    ),
                    "ebit": (R.FIELD_MISSING, "'EBIT / Operating Income' not reported"),
                },
            )
            for fy in fys
        },
    }

    # --- zero share count -> NOT MEANINGFUL ---
    u["MOCK ZERO SHARES"] = {
        "sector": "MockFinance",
        "beta": 1.0,
        "years": {fy: _y(fy, shares=0.0) for fy in fys},
    }

    return u


# Built lazily and rebuilt whenever the financial-year window moves. It used
# to be a module-level constant, which froze the mock universe to whatever
# FY_LIST happened to say at import time - so changing the year range in the
# interface left offline mode still generating the old years.
_CACHE = {"fys": None, "registry": None}


def _registry():
    fys = tuple(config.FY_LIST)
    if _CACHE["fys"] != fys:
        _CACHE["fys"] = fys
        _CACHE["registry"] = _build()
    return _CACHE["registry"]


class _RegistryProxy(dict):
    """Keeps `mock_source.REGISTRY[...]` working for any existing caller."""

    def __getitem__(self, key):
        return _registry()[key]

    def __iter__(self):
        return iter(_registry())

    def __len__(self):
        return len(_registry())

    def __contains__(self, key):
        return key in _registry()

    def get(self, key, default=None):
        return _registry().get(key, default)

    def items(self):
        return _registry().items()

    def keys(self):
        return _registry().keys()

    def values(self):
        return _registry().values()


REGISTRY = _RegistryProxy()

COMPANIES = [
    {"name": n, "sector": v["sector"], "ticker": "MOCK"} for n, v in REGISTRY.items()
] + [
    {"name": "MOCK GHOST CORP", "sector": "MockTech", "ticker": None},
    {"name": "MOCK CRASH CORP", "sector": "MockTech", "ticker": "CRASH"},
]


def resolve(company_name, explicit_ticker=None):
    name = company_name.strip().upper()
    if name == "MOCK GHOST CORP":
        return None  # -> TICKER NOT RESOLVED
    if name == "MOCK CRASH CORP":
        return "CRASH"
    return "MOCK" if name in REGISTRY else None


def fetch_company(ticker, fy_list=None):
    if ticker == "CRASH":
        raise ConnectionError("simulated network failure from the data source")
    raise RuntimeError("fetch_company must be called via fetch_by_name in offline mode")


def fetch_by_name(name, fy_list=None):
    if name.strip().upper() == "MOCK CRASH CORP":
        raise ConnectionError("simulated network failure from the data source")
    rec = REGISTRY[name.strip().upper()]
    return {"ticker": "MOCK", "beta": rec["beta"], "years": rec["years"]}
