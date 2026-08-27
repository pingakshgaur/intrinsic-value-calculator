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

# growth path -> FCFF CAGR of roughly 12%
MULT = {2021: 0.70, 2022: 0.82, 2023: 0.92, 2024: 1.00, 2025: 1.12}

# Dates the mock reports as the realised benchmark session. Deliberately mixed:
# some land on 1 May, most do not, exactly as the exchange calendar dictates.
BENCH_DATES = {
    2021: "2021-05-03",  # 1 May was a Saturday
    2022: "2022-05-02",  # 1 May was a Sunday
    2023: "2023-05-02",  # Maharashtra Day holiday
    2024: "2024-05-02",  # Maharashtra Day holiday
    2025: "2025-05-02",  # Maharashtra Day holiday
}


def _bench(fy, m):
    """Price one month into FY+1: mostly the FY+1 level, slightly early."""
    nxt = MULT.get(fy + 1, m * 1.12)
    return 500.0 * (0.25 * m + 0.75 * nxt)


def _y(fy, **kw):
    m = MULT[fy]
    d = {
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
        "price_fwd": 500.0 * MULT.get(fy + 1, m * 1.12),
        # close nearest 1 May following FY end -> the benchmark
        "price_bench": _bench(fy, m),
        "price_bench_date": BENCH_DATES.get(fy, f"{fy}-05-02"),
        "_diag": {},
        "_notes": [],
    }
    d.update(kw)
    return d


def _blank(fy, reason, detail, keep_price=True):
    """A year where the statements are missing but the price may survive."""
    d = {k: None for k in ("ebit", "ebitda", "eps", "net_income", "da", "capex", "ocf")}
    m = MULT[fy]
    d.update(
        {
            "delta_nwc": 0.0,
            "total_debt": 0.0,
            "cash": 0.0,
            "shares": 1.0e8,
            "tax_rate": config.DEFAULT_TAX_RATE,
            "price": 500.0 * m if keep_price else None,
            "price_fwd": ((500.0 * MULT.get(fy + 1, m * 1.12)) if keep_price else None),
            "price_bench": _bench(fy, m) if keep_price else None,
            "price_bench_date": (
                BENCH_DATES.get(fy, f"{fy}-05-02") if keep_price else None
            ),
            "_diag": {
                k: (reason, detail)
                for k in ("ebit", "ebitda", "eps", "net_income", "da", "capex", "ocf")
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


REGISTRY = _build()

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
