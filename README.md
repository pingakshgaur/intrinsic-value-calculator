# Intrinsic Value Calculator — Technical Documentation

**Version:** 1.0
**Scope:** Traditional intrinsic-value estimation (DCF, P/E Relative, EV/EBITDA) for Indian listed equities, FY2021–FY2025
**Audience:** the researcher running it, an examiner auditing it, and anyone extending it later

---

## Table of contents

1. [What this system does](#1-what-this-system-does)
2. [Architecture at a glance](#2-architecture-at-a-glance)
3. [Installation and first run](#3-installation-and-first-run)
4. [The financial-year convention](#4-the-financial-year-convention)
5. [How market price is determined](#5-how-market-price-is-determined)
6. [The data layer](#6-the-data-layer)
7. [The valuation engine](#7-the-valuation-engine)
8. [The error-handling architecture](#8-the-error-handling-architecture)
9. [Output format](#9-output-format)
10. [The screener](#10-the-screener)
11. [Testing without a network](#11-testing-without-a-network)
12. [Configuration reference](#12-configuration-reference)
13. [Known limitations and methodological caveats](#13-known-limitations-and-methodological-caveats)
14. [Troubleshooting](#14-troubleshooting)
15. [Extending the system](#15-extending-the-system)
16. [Glossary](#16-glossary)

---

## 1. What this system does

Given a list of Indian listed companies, the system computes — for each company, for each of five financial years — an estimate of what one share is *worth* under three independent valuation methods, alongside what that share actually *traded* at during the year.

It produces a single spreadsheet with one row per company-year:

| Company name | Sector Name | Financial Year | Market Price | (DCF) Intrinsic Value | (P/E Relative) Intrinsic Value | (EV/EBITDA) Intrinsic Value |
|---|---|---|---|---|---|---|

The comparison between column 4 and columns 5–7 is the research output. The system deliberately does **not** compute a verdict, a difference, or a buy/sell signal — that interpretation belongs to the analyst, not the code.

### Design commitments

Four principles shaped every decision in the codebase. They're worth stating up front because they explain choices that would otherwise look odd.

**Minimal extraction.** Each data source returns *only* the fields the three formulae consume — fourteen per company-year — and discards everything else at the boundary. Yahoo's API returns hundreds of line items; the system keeps EBIT, EBITDA, EPS, net income, D&A, CapEx, ΔNWC, operating cash flow, total debt, cash, shares, tax rate, price, and beta. Nothing more.

**Never a silent blank.** Every cell either holds a number or holds the specific reason no number exists. A company whose FY2021 cash-flow statement isn't published says so, in those words, in that cell. A blank cell is a bug; a reason string is data.

**Per-method exclusion.** A negative-FCFF year kills the DCF but leaves P/E and EV/EBITDA intact. Failures are isolated to the model they affect, never propagated across the row.

**Point-in-time discipline.** Valuing FY2022 uses only data from FY2022 and earlier. Growth rates, peer medians, and cash-flow histories are all truncated at the year being valued, so no FY2025 information leaks backward into an FY2022 estimate.

---

## 2. Architecture at a glance

```
Intrinsic Value Calculator/
│
├── config.py               All assumptions and thresholds. Single source of truth.
├── fy_utils.py             Financial-year date maths, numeric coercion, formatting.
├── result.py               The Result carrier and the reason-code vocabulary.
│
├── ticker_resolver.py      Company name → Yahoo ticker (manual map → search → cache).
├── yf_source.py            Primary extraction layer. Statements, prices, diagnosis.
├── nse_source.py           NSE portal fallback for price history only.
│
├── model_dcf.py            Two-stage FCFF discounted cash flow.
├── model_pe.py             Sector-median P/E relative valuation.
├── model_ev_ebitda.py      Sector-median EV/EBITDA relative valuation.
│
├── exporter.py             Combined seven-column report, CSV + XLSX.
├── main.py                 Orchestrator. Input → fetch → value → export.
│
├── screener.py             Optional. Builds companies.csv from a screened universe.
├── mock_source.py          Optional. Offline synthetic dataset for testing.
│
├── companies.csv           Input: company name, sector name, market cap, ticker.
├── requirements.txt
│
├── .cache/                 Ticker lookups and screener metrics (auto-created).
└── output/                 Reports and logs (auto-created).
    ├── Intrinsic_Value_Report.csv
    ├── Intrinsic_Value_Report.xlsx
    ├── screening_report.csv
    ├── run_log.txt
    └── screener_log.txt
```

### Execution flow

```
main.py
  │
  ├─ read input               companies.csv or terminal prompt
  │
  ├─ build_universe()         for each company:
  │     ticker_resolver ─────► ticker
  │     yf_source ───────────► {beta, years: {FY: {14 fields, _diag, _notes}}}
  │       └─ nse_source        (price fallback only, if yfinance is empty)
  │
  ├─ build peer tables        two passes over the universe:
  │     model_pe ────────────► {(sector, FY): {company: observed P/E}}
  │     model_ev_ebitda ─────► {(sector, FY): {company: observed EV/EBITDA}}
  │
  ├─ value                    for each company × each FY:
  │     model_dcf ───────────► Result
  │     model_pe ────────────► Result
  │     model_ev_ebitda ─────► Result
  │
  └─ exporter ───────────────► one CSV + one XLSX, plus terminal coverage summary
```

The two-pass structure matters. Relative valuation needs sector medians, and sector medians need every company's observed multiple, so nothing can be valued until every company has been fetched. This is why the fetch loop completes fully before any valuation begins.

---

## 3. Installation and first run

### Requirements

```
yfinance>=0.2.40
pandas>=2.0
numpy>=1.24
requests>=2.31
openpyxl>=3.1
```

Python 3.10 or later (the code uses `float | None` union syntax).

```bash
pip install -r requirements.txt
```

### Input file

`companies.csv` in the project root:

```csv
company name,sector name,market cap,ticker
Bharat Electronics Limited,Defence and Aerospace,Large,BEL.NS
Bharat Dynamics Limited,Defence and Aerospace,Mid,BDL.NS
...
```

`company name` and `sector name` are required. `ticker` is optional but strongly recommended — supplying it skips the Yahoo name-search entirely, which is both faster and more reliable. `market cap` is read and carried through but not currently used in any calculation.

The reader is deliberately tolerant: it accepts `company`/`name` as aliases for `company name`, `sector` for `sector name`, ignores blank lines, and reports ragged rows with their line number instead of crashing.

> **Comma trap.** A company name containing a comma must be quoted: `"Emami, Ltd",FMCG,Mid,EMAMILTD.NS`. Unquoted, the extra comma shifts every subsequent field by one column. The reader detects this and warns, but the row will be wrong.

### Running

```bash
python main.py --input companies.csv
```

Other invocations:

| Command | Effect |
|---|---|
| `python main.py` | Prompts for terminal input, or offers `companies.csv` if present |
| `python main.py --mean-basis calendar` | Averages over calendar days rather than trading sessions |
| `python main.py --exchange .BO` | Default suffix becomes BSE for tickers without one |
| `python main.py --reasons short` | Blank cells show the reason code only, no explanation |
| `python main.py --reasons off` | Reverts to plain `N/A` |
| `python main.py --offline` | Runs against the synthetic dataset, no network |

### Expected runtime

Roughly 3–5 seconds per company: three statement downloads, one price history, one info block, plus the configured 0.6-second courtesy pause. Thirty companies takes about three minutes. Ticker lookups are cached in `.cache/tickers.json` and persist across runs.

---

## 4. The financial-year convention

Indian companies report on an April–March fiscal year. Throughout this system, **FY *N* means 1 April *N*−1 through 31 March *N***.

| Label | Period covered | Statement period-end |
|---|---|---|
| FY2021 | 01-Apr-2020 → 31-Mar-2021 | 31-Mar-2021 |
| FY2022 | 01-Apr-2021 → 31-Mar-2022 | 31-Mar-2022 |
| FY2023 | 01-Apr-2022 → 31-Mar-2023 | 31-Mar-2023 |
| FY2024 | 01-Apr-2023 → 31-Mar-2024 | 31-Mar-2024 |
| FY2025 | 01-Apr-2024 → 31-Mar-2025 | 31-Mar-2025 |

Implemented in `fy_utils.py`:

```python
def fy_window(fy):
    return (dt.date(fy - 1, 4, 1), dt.date(fy, 3, 31))

def fy_end(fy):
    return dt.date(fy, 3, 31)
```

### Matching statements to financial years

Yahoo returns annual statements as a DataFrame whose *columns* are period-end timestamps. These don't always land exactly on 31 March — a company may report to 30 March, or Yahoo may carry a slightly different date. `_col_for_fy()` therefore picks the column whose period-end is *closest* to 31 March of the target FY, and accepts it only if the gap is within **100 days**.

The 100-day tolerance absorbs ordinary reporting variation while refusing to match, say, a December period-end to a March financial year. When no column falls inside the tolerance, the failure message lists every period Yahoo actually returned — which is how you diagnose the depth problem described in §13.

---

## 5. How market price is determined

**The market price for FY *N* is the arithmetic mean of every daily closing price inside that financial year.** This is a long-term moving average over the year, not a single-day snapshot.

### Why a mean and not a closing price

A financial year's market price should represent how the market valued the company *over that year*. A 31 March close is one observation out of roughly 247, and 31 March in India is a fiscal-year-end date with its own tax-driven trading patterns. Using it would make the entire intrinsic-versus-market comparison hostage to one day's noise — a stock that spent the year at ₹400 but closed March at ₹520 would appear overvalued by 30% for reasons that have nothing to do with the year.

The mean also matches how the price is *used*. It feeds the equity weight in WACC and the observed P/E and EV/EBITDA multiples that build the sector medians. Those are year-level constructs; a year-level price is the consistent input.

### Two averaging bases

Set by `FY_MEAN_BASIS` in `config.py`:

**`"trading"` (default)** — mean of the ~247 sessions the stock actually traded. This is standard practice and what most academic and commercial sources mean by an annual average price.

**`"calendar"`** — the daily series is resampled to all ~365 calendar days with forward-fill, then averaged. Weekends and holidays carry the prior close forward, so Fridays and pre-holiday sessions are counted two or three times. This is literally an average over 365 days.

In practice the two differ by well under one percent, because forward-filling just repeats Friday's price. `trading` is recommended; `calendar` exists so the choice can be stated explicitly rather than assumed.

### Split and bonus adjustment

Prices are fetched with `auto_adjust=False`, which in current yfinance still returns a `Close` series adjusted for splits and bonus issues but **not** for dividends. That combination is exactly right here:

- **Split adjustment is essential.** A 1:2 split mid-year would otherwise halve the price series overnight and corrupt the mean.
- **Dividend adjustment would be wrong.** Intrinsic value is expressed per share as a price. Comparing it against a total-return-adjusted series would compare unlike quantities.

### Coverage guards

A mean over eight sessions is not a year average. Two thresholds enforce this:

| Threshold | Default | Behaviour below it |
|---|---|---|
| `MIN_TRADING_DAYS_FOR_FY` | 60 | Price reported as unavailable, with the session count and date range in the reason |
| `PARTIAL_YEAR_SESSIONS` | 200 | Mean is used, but flagged in `_notes` as a partial-year average, not comparable to peers |

This matters because recent IPOs are common in the thematic sectors this project covers. A company listing in August has roughly 160 sessions in that financial year — usable, but not equivalent to a peer's full 247, and the flag records that.

Every successful price also logs its provenance to `_notes`:

```
FY2024 market price = mean of 247 trading sessions; range ₹198.40-₹341.75
```

A mean of ₹280 drawn from a ₹150–₹460 range is a fundamentally different data point from one drawn from ₹270–₹290, and this note preserves that distinction.

---

## 6. The data layer

### 6.1 `ticker_resolver.py`

Resolution order:

1. **Explicit ticker from the input CSV** — used as given. If it has no dot, `EXCHANGE_SUFFIX` is appended.
2. **Manual map** — a small hard-coded dictionary of common names.
3. **Yahoo search API** — `query2.finance.yahoo.com/v1/finance/search`, filtered to prefer the configured exchange, then any `.NS` or `.BO` listing.
4. **Persistent cache** — successful lookups are written to `.cache/tickers.json` and reused indefinitely.

Failure returns `None`, which becomes a `TICKER NOT RESOLVED` reason on all five of that company's rows. The company is **not** dropped from the output.

### 6.2 `yf_source.py` — the primary extraction layer

This is the most substantial module. It does four things.

**Downloads three statements and one price series.** Each download is individually wrapped; a failure records a descriptive error string rather than raising, so a company with a broken cash-flow statement still gets valued by P/E.

**Resolves line items through alias lists.** Yahoo renames rows between companies and over time — operating profit may appear as `EBIT`, `Operating Income`, or `Total Operating Income As Reported`. Each field carries an ordered alias list and takes the first match:

```python
INCOME_ALIASES = {
    "ebit":   ["EBIT", "Operating Income", "Total Operating Income As Reported"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "eps":    ["Diluted EPS", "Basic EPS"],
    ...
}
```

The order encodes preference: diluted EPS before basic, because diluted is the conservative figure.

**Normalises signs.** Yahoo reports CapEx as a negative number (a cash outflow) and `Change In Working Capital` as its cash-flow impact (negative when working capital increases). The extractor converts both to intuitive conventions — `capex` is stored as a positive magnitude, `delta_nwc` as positive-means-NWC-increased — so the FCFF formula in `model_dcf.py` reads as it does in a textbook. **This is the single most common source of sign errors in hand-built valuation code**, and centralising it here means it's fixed in one place.

**Records why each missing field is missing.** Every field that comes back `None` writes a `(code, detail)` tuple into `d["_diag"][field]`. This is what makes downstream reason messages specific rather than generic.

#### Derived fields and gap-fills

Some absences are recoverable:

| Situation | Fallback | Note recorded |
|---|---|---|
| EBITDA missing, EBIT and D&A present | `ebitda = ebit + da` | "EBITDA derived as EBIT + D&A" |
| EPS missing, net income and shares present | `eps = net_income / shares` | "EPS derived as Net Income / Shares" |
| Shares missing from balance sheet | Current count from the info block | Flagged — ignores later dilution/buybacks |
| Tax provision or pretax income unusable | `DEFAULT_TAX_RATE` (25.17%) | Statutory rate substituted |
| Total debt not reported | `0.0` | "assumed zero (debt-free)" |
| Cash not reported | `0.0` | "assumed zero" |
| ΔNWC not reported | `0.0` | "treated as zero" |

When a gap-fill succeeds, the corresponding `_diag` entry is **cleared** — the field is no longer missing, so it should no longer carry a failure reason.

The zero-fills for debt and cash deserve a word. A genuinely debt-free company reports no debt line at all, so treating absence as zero is usually correct. But it is an assumption, not a fact, and it is recorded as one. If you would rather these hard-fail, delete the corresponding blocks; the reason machinery will then report `FIELD MISSING` instead.

#### Effective tax rate

```
t = tax_provision / pretax_income,  clamped to [0.05, 0.45]
fallback: 0.2517 (Indian statutory rate under the new regime)
```

The clamp guards against a loss year producing a nonsensical or negative rate.

### 6.3 `nse_source.py` — the fallback

Used **only** when yfinance returns no price rows at all, and **only** for price history. It never supplies fundamentals.

NSE's public API requires cookie priming: a request to the homepage, then to a quote page, before `/api/historical/cm/equity` will respond. The module maintains a primed session, chunks requests into ≤350-day windows (NSE caps each call at roughly a year), extracts only the closing price from each row, and pauses between calls.

> **It will not work everywhere.** NSE blocks datacentre and VPN IP ranges. On a cloud VM or behind a corporate VPN, every call returns nothing and the module silently yields `None`, at which point the price reason string says so explicitly. From a home connection it generally works. This is expected behaviour, not a defect.

---

## 7. The valuation engine

All three models share an interface: given the company data and a financial year, return a `Result` that either holds a per-share value or holds a reason. None of them raises; all failure paths are explicit.

### 7.1 DCF — `model_dcf.py`

A two-stage free-cash-flow-to-firm model.

#### Free cash flow to firm

```
FCFF = EBIT × (1 − t) + D&A − CapEx − ΔNWC
```

Fallback when EBIT or D&A is unavailable:

```
FCFF = Operating Cash Flow − CapEx
```

The fallback is less precise — operating cash flow is already net of interest paid, so it approximates free cash flow to *equity* more than to the *firm* — but it keeps a company valuable when only the cash-flow statement survives. The choice of formula used is not currently recorded; if that matters for your audit trail, it's a one-line addition to `_notes`.

#### Cost of equity (CAPM)

```
Ke = Rf + β × ERP
   = 0.0705 + β × 0.0550
```

`Rf` is the 10-year G-Sec yield; `ERP` is the India equity risk premium. Beta comes from Yahoo's info block, accepted only if it falls in (0.1, 3.0), otherwise defaulting to 1.0.

> Yahoo's beta is computed against a global or US benchmark for many Indian scrips and is frequently absent for small caps. This is the weakest input in the WACC chain. If precision matters, compute beta yourself from 60 monthly returns against the NIFTY 500 — you already have the price history to do it.

#### Weighted average cost of capital

```
E = mean FY price × shares outstanding
D = total debt

WACC = E/(D+E) × Ke + D/(D+E) × Kd × (1 − t)
```

with `Kd = 0.085` (pre-tax cost of debt) and `t` the effective tax rate.

WACC is then floored:

```
WACC = max(WACC, g_terminal + 0.02)
```

This guarantees the terminal-value denominator stays positive and meaningfully above zero. Without it, a low-beta debt-free company can produce a WACC below the terminal growth rate, which makes the Gordon formula return a negative or explosive value.

#### Growth rate

The explicit-period growth rate is the CAGR of FCFF across all *positive* FCFF years at or before the year being valued:

```python
g = (FCFF_last / FCFF_first) ** (1 / n) - 1
clamped to [MIN_GROWTH, MAX_GROWTH] = [2%, 18%]
```

Fewer than two positive observations falls back to `DEFAULT_GROWTH` (8%).

The clamp is doing real work. FCFF is volatile — a single heavy-CapEx year can produce a 300% apparent CAGR off a depressed base. Winsorising to a defensible band keeps one bad year from producing an absurd valuation. Note the truncation at `fy`: valuing FY2022 never sees FY2023–25 cash flows.

#### Projection and terminal value

```
FCFF_n = FCFF_0 × (1 + g)^n          for n = 1..5
PV_n   = FCFF_n / (1 + WACC)^n

TV     = FCFF_5 × (1 + g_t) / (WACC − g_t)      g_t = 5%
PV_TV  = TV / (1 + WACC)^5

EV           = Σ PV_n + PV_TV
Equity Value = EV − (Total Debt − Cash)
Value/share  = Equity Value / Shares Outstanding
```

> **On the 5% terminal growth rate.** This is high for a perpetuity — it assumes the company grows forever at roughly India's long-run nominal GDP growth, which no firm does indefinitely. It is defensible for a high-growth emerging market and it is the figure specified for this project, but it makes terminal value dominate: expect TV to contribute 70–85% of enterprise value. That concentration is itself a finding worth reporting. A more conservative 3–4% would shift every DCF estimate down materially, and running both is a legitimate sensitivity analysis.

#### Exclusion conditions

| Condition | Reason code | Message |
|---|---|---|
| No data assembled for the FY | `NO DATA FOR THIS FY` | — |
| Shares outstanding missing | propagated from `_diag` | field-specific |
| Shares ≤ 0 | `NOT MEANINGFUL` | share count as reported |
| FCFF inputs incomplete | propagated | names the blocking field |
| FCFF ≤ 0 | `NOT MEANINGFUL` | "a going-concern DCF cannot be run off a negative base cash flow" |
| WACC ≤ terminal growth | `CALCULATION ERROR` | "terminal value would be infinite" |
| Equity value ≤ 0 | `NEGATIVE EQUITY VALUE` | shows EV, net debt, WACC and growth used |
| Any unhandled exception | `CALCULATION ERROR` | exception type and message; traceback to log |

### 7.2 P/E Relative — `model_pe.py`

```
Intrinsic Value per share = EPS(FY) × benchmark P/E(FY)
```

#### Constructing the benchmark

The benchmark is the **median trailing P/E of the same sector in the same financial year**, computed from the companies in your own input file.

Observed P/E for each company-year:

```
P/E = mean FY price / diluted EPS      accepted only if EPS > 0 and 2.0 ≤ P/E ≤ 120
```

The bounds discard degenerate multiples — a company with near-zero EPS produces a P/E of 4,000 that would drag any median it entered.

Benchmark selection, in order:

1. **Median of sector peers excluding the company itself**, if at least `MIN_PEERS_FOR_MEDIAN` (2) remain. Self-exclusion is deliberate: including a company in the median used to value it makes the estimate partly self-referential and biases it toward the observed price.
2. **Median of the sector including self**, if peers exist but too few.
3. **Median of the company's own historical P/E** across all available years.

If none of these produces a number, the result is `NO PEER BENCHMARK` with an explanation of how many peers had valid multiples.

> **Sector composition drives this model.** With two companies in a sector, self-exclusion leaves one peer, fallback 2 triggers, and the estimate becomes weakly self-referential. With four or five, the median is meaningful. Aim for at least four names per sector; fewer than three and the model is largely measuring the company against itself.

#### Exclusions

| Condition | Reason code |
|---|---|
| No data for the FY | `NO DATA FOR THIS FY` |
| EPS missing | propagated from `_diag` |
| EPS ≤ 0 | `NOT MEANINGFUL` — "P/E valuation is undefined for negative earnings" |
| No usable benchmark | `NO PEER BENCHMARK` |

### 7.3 EV/EBITDA — `model_ev_ebitda.py`

```
Implied Enterprise Value = EBITDA(FY) × benchmark EV/EBITDA(FY)
Equity Value             = Implied EV − Net Debt
Value per share          = Equity Value / Shares Outstanding

where Net Debt = Total Debt − Cash
```

Observed multiple for the peer median:

```
EV = mean FY price × shares + total debt − cash
EV/EBITDA = EV / EBITDA      accepted only if EBITDA > 0, EV > 0, 1.0 ≤ multiple ≤ 60
```

Benchmark selection follows the same three-step ladder as P/E, with the same self-exclusion logic.

> **Net debt is subtracted exactly once.** A common error in worked examples is to compute net debt, subtract it, and then subtract total debt and cash separately as well — double-counting the bridge. The implementation subtracts `(total_debt − cash)` from implied enterprise value one time.

#### Exclusions

| Condition | Reason code |
|---|---|
| EBITDA missing | propagated from `_diag` |
| EBITDA ≤ 0 | `NOT MEANINGFUL` — operating loss |
| Shares missing or ≤ 0 | propagated or `NOT MEANINGFUL` |
| No usable benchmark | `NO PEER BENCHMARK` |
| Implied EV below net debt | `NEGATIVE EQUITY VALUE` — shows the implied EV and the multiple used |

### 7.4 Which model suits which company

| Model | Works well for | Breaks down for |
|---|---|---|
| DCF | Mature, cash-generative firms with stable CapEx | Loss-makers, early-stage growth, banks, heavy cyclicals in a trough year |
| P/E Relative | Profitable firms in a well-populated sector | Loss-makers, thin sectors, companies with no true peers |
| EV/EBITDA | Capital-intensive industrials, capital-structure-neutral comparison | Banks and NBFCs (no meaningful EBITDA), asset-light firms |

**Banks and financial companies are structurally outside two of these three models.** For a lender, debt is raw material rather than financing, so enterprise value is meaningless and free cash flow is unreliable. If your sample includes banks or NBFCs, expect their EV/EBITDA and DCF columns to be reason strings. The honest treatment is to value them on P/E only and state the exclusion in your methodology — not to force a number out of a model that doesn't apply.

---

## 8. The error-handling architecture

This is the part that distinguishes the system from a script that prints `N/A`.

### 8.1 The `Result` carrier

```python
@dataclass
class Result:
    value:  float | None
    code:   str   | None
    detail: str   | None
```

Constructed via `Result.good(v)` or `Result.bad(code, detail)`. `.ok` tests for a value; `.text()` renders the cell — a formatted currency string when there's a value, otherwise the reason.

Every value that can fail travels as a `Result` from the point of failure to the spreadsheet cell. Nothing is coerced to `None` and forgotten along the way.

### 8.2 The reason vocabulary

Stable, greppable codes defined in `result.py`:

| Code | Meaning |
|---|---|
| `TICKER NOT RESOLVED` | Company name matched no exchange symbol |
| `FETCH FAILED` | Download raised an exception |
| `SOURCE UNAVAILABLE` | A whole statement came back empty or errored |
| `NO DATA FOR THIS FY` | No statement period matched this financial year |
| `FIELD MISSING` | The statement exists; this line item isn't in it |
| `PRICE UNAVAILABLE` | No price history, or too few sessions inside the FY |
| `NOT MEANINGFUL` | The maths is defined but economically nonsensical (negative EPS, negative EBITDA, zero shares) |
| `NO PEER BENCHMARK` | No usable sector median and no own history |
| `NEGATIVE EQUITY VALUE` | Enterprise value fell below net debt |
| `CALCULATION ERROR` | Division by zero, NaN, or an unhandled exception |
| `NOT COMPUTABLE` | A dependency was itself unavailable |
| `MODEL NOT APPLICABLE` | Reserved for structural exclusions |

Because the codes are stable strings, you can pivot the output spreadsheet on them, count them, or filter for a specific failure mode — which is exactly what the end-of-run tally does.

### 8.3 Reason propagation

The mechanism that makes messages specific rather than generic:

```
yf_source                model                    exporter
    │                      │                          │
    │ field missing        │                          │
    ├─ _diag["ebit"] = (NO_PERIOD, "no period ending near 31-Mar-2021;
    │                              source publishes only the latest ~4
    │                              fiscal periods")
    │                      │                          │
    │                      │ require(d,"ebit",...)    │
    │                      ├─ reads _diag, wraps in Result
    │                      ├─ adds model context:     │
    │                      │  "FCFF needs EBIT + D&A − CapEx; EBIT is
    │                      │   the blocker → <original detail>"
    │                      │                          │
    │                      │                          ├─ Result.text()
    │                      │                          └─► cell content
```

The cell ends up saying not just *that* the DCF failed, but that it failed because FCFF needed EBIT, that EBIT was unavailable, and that the underlying cause was a statement-depth limit at the source. That chain is reconstructed from the point of failure, not guessed at the point of display.

### 8.4 Layered exception capture

Five independent layers, so no single failure can take down a run:

1. **Statement download** — each of the three statements is wrapped separately.
2. **Field extraction** — every `_pick` call records rather than raises.
3. **Whole-company fetch** — a crash produces `FETCH FAILED` on all five of that company's rows; the run continues.
4. **Model invocation** — a `guard()` closure catches anything a model throws and converts it to `CALCULATION ERROR`.
5. **Export and top level** — a failed XLSX write still leaves the CSV; a fatal error prints the exception and points at the log.

Full tracebacks go to `output/run_log.txt` at DEBUG level. The terminal stays readable.

> **Logging must be initialised first.** `setup_logging()` belongs on the first line of `main()`, before argument parsing and before input reading. If it runs later, any exception raised during input parsing is logged to a handler that doesn't exist yet, and you get a one-line message with no traceback.

### 8.5 Failed companies still appear

A company that can't be resolved or fetched produces its full five rows, every cell carrying the reason. It is never silently dropped.

This is a research decision as much as an engineering one. A reader of your output can see the gap and its cause. If failures vanished, the sample would appear complete when it wasn't, and the reader would have no way to know.

---

## 9. Output format

Two files per run, written to `output/`:

- `Intrinsic_Value_Report.csv` — UTF-8 with BOM, so Excel renders ₹ correctly
- `Intrinsic_Value_Report.xlsx` — bold wrapped header, panes frozen at `D2`, columns widened for reason strings

### Layout

| Company name | Sector Name | Financial Year | Market Price | (DCF) Intrinsic Value | (P/E Relative Valuation) Intrinsic Value | (EV/EBITDA Valuation) Intrinsic Value |
|---|---|---|---|---|---|---|
| Bharat Electronics | Defence and Aerospace | 2025 | ₹287.14 | ₹243.86 | ₹261.02 | ₹255.71 |
| Bharat Electronics | Defence and Aerospace | 2024 | ₹198.40 | ₹211.55 | ₹224.19 | ₹207.33 |
| Bharat Electronics | Defence and Aerospace | 2023 | ₹104.72 | ₹118.90 | ₹131.44 | ₹126.08 |
| Bharat Electronics | Defence and Aerospace | 2022 | ₹81.35 | ₹94.27 | ₹88.61 | ₹90.15 |
| Bharat Electronics | Defence and Aerospace | 2021 | ₹58.90 | NO DATA FOR THIS FY: no period ending near 31-Mar-2021… | NO DATA FOR THIS FY: … | NO DATA FOR THIS FY: … |
| *(blank row)* | | | | | | |
| Next Company | … | 2025 | … | … | … | … |

Years run newest first within each company. A blank separator row sits between companies. The row count is exactly `companies × 5`, including failed companies, so the sheet is rectangular and safe to pivot on — which matters for a sector × market-cap research design.

### Terminal summary

```
[export] 150 company-year rows -> output/Intrinsic_Value_Report.csv

[model coverage]
   DCF             98/150 valued
   P/E Relative   112/150 valued
   EV/EBITDA      104/150 valued
   Market Price   132/150 available

[why cells are blank]
     54  NO DATA FOR THIS FY
     31  NOT MEANINGFUL
     18  PRICE UNAVAILABLE
     12  NO PEER BENCHMARK
      3  NEGATIVE EQUITY VALUE
```

The tally is the fastest diagnostic available. One dominant code means one fixable problem; five codes spread evenly means the sample itself needs rethinking.

### A note on cell types

Values are written as **formatted strings** (`₹1,234.56`), not numbers, because a cell must be able to hold either a value or a sentence. If you intend to chart or regress on this output, either post-process with `=IFERROR(VALUE(SUBSTITUTE(D2,"₹","")),"")` in Excel, or modify `Result.text()` to emit raw floats and move the ₹ into the workbook's number format.

---

## 10. The screener

`screener.py` is optional and runs *before* `main.py`. It screens a candidate universe on fundamental criteria and writes the survivors into `companies.csv`.

```bash
python screener.py --relax
```

### Criteria

Defined in the `THRESHOLDS` dict:

| Criterion | Default | Computed as |
|---|---|---|
| ROCE floor | 18% | `EBIT / (Total Assets − Current Liabilities)`, must hold every year checked |
| Years of ROCE required | 4 | See the depth caveat below |
| P/E ceiling | 20 | Trailing, or derived from latest FY EPS |
| Drawdown from 52-week high | ≥ 25% | The "trading near the lows" condition |
| Debt/equity ceiling | 1.0 | Latest available FY |
| Sales CAGR floor | 5% | Across the available revenue span |
| Complete financial years | 4 | Years with usable EBIT, revenue and assets |
| Market cap floor | ₹300 cr | From the info block |

Market-cap buckets: Large ≥ ₹50,000 cr, Mid ≥ ₹15,000 cr, Small below. These approximate AMFI's top-100 / 101-250 / 251+ rule with absolute cut-offs — state whichever definition you use.

### Relaxation ladder

With `--relax`, thresholds loosen in a fixed order until every sector × cap bucket fills:

1. Drop the near-the-lows condition
2. P/E ceiling → 30
3. ROCE floor → 15%
4. P/E ceiling → 40
5. ROCE floor → 12%
6. Drop the sales-growth condition

Each step applied is printed and reported, so you can state in your methodology exactly which conditions had to be loosened — considerably more defensible than a hand-picked list.

### Audit output

`output/screening_report.csv` contains **every** candidate — passing and failing — with each metric, the per-year ROCE, the pass/fail verdict, and the specific reason for every failed criterion. This is the file to cite when asked how the sample was constructed.

### Three honest limits

**FII holding is not actually available.** yfinance exposes no FII/DII split for Indian listings. The `fii_pct_unverified` column carries Yahoo's generic institutional-holding field, which is frequently blank or wrong for NSE scrips. Pull real FII numbers from Screener.in or Trendlyne if that criterion matters.

**ROCE runs over four years, not five.** Capital employed needs a balance sheet, and FY2021's usually isn't retrievable. `roce_min_years` defaults to 4.

**The universe is a seed list of roughly 90 tickers, not the exchange.** For genuinely exhaustive coverage, run this Screener.in query and feed its CSV export in via `--universe`:

```
Average return on capital employed 5Years > 18 AND
Return on capital employed > 18 AND
Price to Earning < 20 AND
Down from 52w high > 25 AND
Market Capitalization > 300 AND
Debt to equity < 1 AND
Sales growth 5Years > 5
```

> **A methodological warning about using the screener at all.** Selecting companies on low P/E and price drawdown, then running a valuation study that compares intrinsic value against market price, is circular. Low P/E is simultaneously your selection filter and an input to your P/E and EV/EBITDA models — so the study will mechanically report "undervalued" for nearly every row. A dataset for this kind of comparison should be selected on grounds independent of valuation: sector, market cap, listing vintage, data availability. If you want the screened names too, keep them as a **separate labelled sub-sample** so the difference between the two groups becomes a finding rather than an artefact.

---

## 11. Testing without a network

`mock_source.py` provides a deterministic synthetic dataset that exercises every reason code in under a second.

```bash
python main.py --offline
```

### Fixtures

| Company | Exercises |
|---|---|
| MOCK CLEAN ALPHA / BETA / GAMMA | The happy path — three peers in one sector, all three models value cleanly |
| MOCK DEPTH GAP | `NO DATA FOR THIS FY` for FY2021–22 |
| MOCK LOSS MAKER | `NOT MEANINGFUL` from FY2023 on negative EPS and EBITDA |
| MOCK NO PRICE SOLO | `PRICE UNAVAILABLE` and `NO PEER BENCHMARK` together |
| MOCK HEAVY DEBT | `NEGATIVE EQUITY VALUE` |
| MOCK BANK STYLE | `FIELD MISSING` where EBITDA is simply not reported |
| MOCK ZERO SHARES | `NOT MEANINGFUL` on a zero share count |
| MOCK GHOST CORP | `TICKER NOT RESOLVED` |
| MOCK CRASH CORP | `FETCH FAILED` from a simulated `ConnectionError` |

The pass condition is that all relevant codes appear in the tally *and* the clean trio produces real numbers in all three model columns. Exact counts shift with `config.py` assumptions; the presence of every code is what matters.

There is also `companies_edgecases.csv` for live testing against real recent IPOs, loss-makers, banks, and a deliberately unresolvable name.

---

## 12. Configuration reference

Everything in `config.py`. These are your stated assumptions — every one of them belongs in a methodology appendix.

### Financial year and price

| Setting | Default | Notes |
|---|---|---|
| `FY_LIST` | `[2021…2025]` | Years to compute |
| `FY_START_MONTH/DAY` | 4 / 1 | Indian fiscal year start |
| `FY_END_MONTH/DAY` | 3 / 31 | Fiscal year end |
| `PRICE_MODE` | `"average"` | Fixed by design; not a tunable |
| `FY_MEAN_BASIS` | `"trading"` | Or `"calendar"` |
| `MIN_TRADING_DAYS_FOR_FY` | 60 | Below this, price is unavailable |
| `PARTIAL_YEAR_SESSIONS` | 200 | Below this, mean is flagged as partial |

### Cost of capital

| Setting | Default | Notes |
|---|---|---|
| `RISK_FREE_RATE` | 0.0705 | 10-year G-Sec yield |
| `EQUITY_RISK_PREMIUM` | 0.0550 | India ERP |
| `DEFAULT_BETA` | 1.00 | When Yahoo's beta is missing or implausible |
| `COST_OF_DEBT` | 0.0850 | Pre-tax |
| `DEFAULT_TAX_RATE` | 0.2517 | Indian statutory, new regime |

### DCF

| Setting | Default | Notes |
|---|---|---|
| `PROJECTION_YEARS` | 5 | Explicit forecast horizon |
| `TERMINAL_GROWTH` | 0.0500 | See the caveat in §7.1 |
| `MIN_GROWTH` / `MAX_GROWTH` | 0.02 / 0.18 | Growth winsorisation band |
| `DEFAULT_GROWTH` | 0.0800 | When history is too thin |
| `WACC_SPREAD_OVER_G` | 0.0200 | Minimum WACC-minus-terminal-growth gap |

### Relative valuation

| Setting | Default | Notes |
|---|---|---|
| `PE_BOUNDS` | (2.0, 120.0) | Multiples outside this are excluded from medians |
| `EV_EBITDA_BOUNDS` | (1.0, 60.0) | Same |
| `MIN_PEERS_FOR_MEDIAN` | 2 | Peers required after self-exclusion |

### Runtime

| Setting | Default | Notes |
|---|---|---|
| `EXCHANGE_SUFFIX` | `".NS"` | Default suffix for bare tickers |
| `CURRENCY_SYMBOL` | `"₹"` | |
| `OUTPUT_DIR` / `CACHE_DIR` | `output` / `.cache` | |
| `OUTPUT_BASENAME` | `Intrinsic_Value_Report` | |
| `REQUEST_PAUSE` | 0.6 | Seconds between network calls |
| `SHOW_REASONS` | `True` | `False` reverts to plain `N/A` |
| `REASON_STYLE` | `"detailed"` | Or `"short"` for code only |
| `LOG_FILE` | `run_log.txt` | Inside `OUTPUT_DIR` |

---

## 13. Known limitations and methodological caveats

Every one of these is a real constraint on what the results can support. They belong in a limitations section, not in a footnote.

### 13.1 Source depth — the binding constraint

**yfinance publishes roughly the latest four annual statement periods.** Not five. For a run covering FY2021–FY2025 executed in 2026, FY2021 fundamentals are typically unavailable for most companies — even though the company has filed a decade of accounts.

Consequences: FY2021 valuations will be largely reason strings; the DCF growth CAGR computes over three or four points rather than five; the screener's ROCE test runs over four years.

Mitigation: supply the older figures yourself. Add a `fundamentals_override.csv` keyed on `ticker,fy` with the fields listed in §6.2, read it in `fetch_company`, and let it fill any `None`. Screener.in or the annual reports have the numbers. This is the single highest-value addition to the codebase.

### 13.2 Recent listings

Companies that IPO'd inside the window have no price for the years before listing, and their first partial year produces a mean over fewer sessions than their peers'. In the thematic sectors this project targets — defence, renewables, semiconductors — recent listings are common; a third of a typical 30-name sample can be affected.

This also degrades the peer medians. A sector where only three of six names traded in FY2021 has a median built from three observations.

### 13.3 Selection bias if the screener is used

Covered fully in §10. Restating because it's the most consequential threat to the study's validity: screening on low P/E and price drawdown pre-determines the finding.

### 13.4 Circularity in WACC

The equity weight in WACC uses market capitalisation, which uses the market price — the same quantity the intrinsic value is being compared against. This is standard practice (Damodaran and every corporate finance text weight WACC at market values), but it does mean the DCF is not fully independent of market price. A book-value weighting alternative would be independent but less defensible on other grounds. Worth one sentence in the methodology.

### 13.5 Beta quality

Yahoo's beta for Indian scrips is often computed against a non-Indian benchmark and is frequently missing for small caps, in which case 1.0 is substituted. Since beta drives cost of equity, drives WACC, drives the discount rate, this is a meaningful source of error — a beta of 1.8 versus 0.8 can move a DCF result by 30–40%. Computing beta from 60 monthly returns against the NIFTY 500 is the fix, and the price history needed is already being downloaded.

### 13.6 Terminal-value dominance

At 5% terminal growth and a 5-year horizon, terminal value typically accounts for 70–85% of enterprise value. The DCF is therefore mostly a statement about the perpetuity assumption rather than about the forecast cash flows. Reporting the TV share per company is itself a legitimate finding.

### 13.7 Consolidated versus standalone

The system takes whatever Yahoo returns, which is usually consolidated but is not guaranteed to be consistent across companies. For a firm with large subsidiaries this materially changes revenue, EBITDA and debt. If consistency matters, verify against the annual report and use the override file.

### 13.8 No look-ahead guard on publication dates

The system uses point-in-time discipline at the *financial year* level — FY2022 valuations use only FY2022-and-earlier data. It does **not** model the publication lag: FY2023 accounts aren't public on 31 March 2023, typically appearing 60–90 days later. Market data for FY2023 therefore overlaps a period when FY2023 fundamentals weren't yet known.

For a retrospective valuation study this is usually acceptable and is standard in the literature. For anything resembling a trading strategy it is not. If you need the stricter treatment, add `publication_date = period_end + 90 days` and gate every fundamentals-to-price join on it.

### 13.9 Banks and financials

Two of the three models are structurally undefined for lenders. See §7.4.

### 13.10 Not investment advice

This is a research instrument. Its outputs are only as good as the assumptions in `config.py`, and those assumptions are contestable. Nothing it produces is a recommendation to buy or sell anything.

---

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `AttributeError: 'list' object has no attribute 'strip'` | A CSV row has more commas than the header — usually an unquoted comma in a company name | Quote the field: `"Emami, Ltd",…`. The tolerant reader in §3 reports the line number instead of crashing |
| Every cell says `TICKER NOT RESOLVED` | No network, or Yahoo search unreachable | Supply explicit tickers in the `ticker` column |
| All FY2021 cells blank with `NO DATA FOR THIS FY` | Source depth limit (§13.1) | Expected. Add the override file if you need FY2021 |
| A whole sector says `NO PEER BENCHMARK` | Fewer than two peers with valid multiples | Add more companies to that sector |
| Banks show `NOT MEANINGFUL` on EV/EBITDA | Structural — no meaningful EBITDA | Expected. Value on P/E only |
| NSE fallback always returns nothing | NSE blocks datacentre and VPN IPs | Run from a home connection, or rely on yfinance |
| ₹ renders as `â‚¹` in Excel | Encoding | Already handled via `utf-8-sig`; if it persists, open via Data → From Text with UTF-8 |
| Reason strings make the sheet unwieldy | Detailed style | `--reasons short` gives codes only, which sort and pivot cleanly |
| Error message with no traceback | `setup_logging()` running after the failing code | Move it to the first line of `main()` (§8.4) |
| Rate-limit errors from Yahoo | Too many rapid calls | Raise `REQUEST_PAUSE` to 1.5–2.0 |

---

## 15. Extending the system

### Adding a fourth valuation model

The interface is a single function:

```python
def intrinsic_value(...) -> Result
```

Steps:

1. Create `model_<name>.py` returning `Result.good(value)` or `Result.bad(code, detail)` on every path.
2. If it needs a peer benchmark, add a `build_*_table(universe)` function following the pattern in `model_pe.py`.
3. In `main.py`, add the model to the `rows.append({...})` dict with a new key.
4. In `exporter.py`, append the column name to `COLUMNS` and the `(key, column)` pair to `VALUE_KEYS`.

Nothing else changes. Residual Income and Graham Number are the natural next additions — both need only fields already being extracted.

### Adding a data source

Implement a module exposing `fetch_close_series(ticker, start, end)` and/or field getters, then insert it in the fallback chain in `yf_source.fetch_company`. Record its provenance in `_notes` so the audit trail shows which source supplied what.

### The fundamentals override file

The highest-value extension, per §13.1. Read a `fundamentals_override.csv` keyed on `(ticker, fy)` at the end of the per-FY loop in `fetch_company`, fill any `None` field from it, clear the corresponding `_diag` entry, and append a note recording that the value was manually supplied.

### Surfacing the audit notes

`d["_notes"]` accumulates provenance for every company-year — session counts, price ranges, derived fields, substituted assumptions — and nothing currently prints it. Adding it as a second worksheet, or as an eighth column, turns the output from a results table into a fully auditable record. Recommended before submission.

---

## 16. Glossary

**Beta (β)** — sensitivity of a stock's returns to the market's. 1.0 tracks the market; 1.8 moves roughly 1.8× as far in both directions.

**Capital employed** — total assets minus current liabilities. The denominator of ROCE.

**CAGR** — compound annual growth rate; the constant rate that takes a starting value to an ending value over *n* periods.

**CAPM** — Capital Asset Pricing Model. Cost of equity = risk-free rate + β × equity risk premium.

**Enterprise value (EV)** — market capitalisation plus total debt minus cash. The value of the whole business, independent of how it's financed.

**Equity risk premium (ERP)** — the excess return investors demand for holding equities over risk-free government bonds.

**FCFF** — free cash flow to firm. Cash available to all capital providers, debt and equity, after operating costs, taxes, capital expenditure and working-capital investment.

**Gordon Growth Model** — the perpetuity formula behind terminal value: `TV = CF × (1 + g) / (r − g)`.

**Intrinsic value** — an estimate of what a share is fundamentally worth, derived from the business's economics rather than from its current price.

**Net debt** — total debt minus cash and equivalents. The bridge from enterprise value to equity value.

**ROCE** — return on capital employed. EBIT divided by capital employed; a measure of how efficiently a business converts capital into operating profit.

**Terminal value** — the present value of all cash flows beyond the explicit forecast horizon, typically the majority of a DCF result.

**Trailing twelve months (TTM)** — the most recent twelve months of reported results, as opposed to a fiscal year or a forecast.

**WACC** — weighted average cost of capital. The blended required return of debt and equity holders, weighted by their share of the capital structure, used as the DCF discount rate.

**Winsorisation** — clamping extreme values to a defined band rather than discarding them, to limit the influence of outliers.

---

*End of documentation.*