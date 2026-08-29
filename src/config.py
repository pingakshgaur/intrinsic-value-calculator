# FILE: src/config.py
"""Global assumptions and knobs. Tune these before running."""

from pathlib import Path

# ---------------- Paths ----------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
CACHE_DIR = PROJECT_ROOT / ".cache"
DEFAULT_INPUT = DATA_DIR / "companies.csv"
OVERRIDE_FILE = DATA_DIR / "fundamentals_override.csv"

# ---------------- Financial year ----------------
FY_LIST = [2021, 2022, 2023, 2024, 2025]
FY_START_MONTH, FY_START_DAY = 4, 1
FY_END_MONTH, FY_END_DAY = 3, 31

# ---------------- Market price (VALUATION ANCHOR) ----------------
# This is the price the models CONSUME: it sets the equity weight in WACC, the
# observed P/E and EV/EBITDA multiples, and five of the ML features. It must
# stay inside FY_t. Do not point it at the benchmark date - that would feed a
# post-FY price into this year's valuation, which is look-ahead bias.
PRICE_MODE = "average"
FY_MEAN_BASIS = "trading"  # or "calendar"
MIN_TRADING_DAYS_FOR_FY = 60
PARTIAL_YEAR_SESSIONS = 200

# ---------------- Benchmark price (1 MAY, POST-FY) ----------------
# This is the price the models are SCORED AGAINST. It is the traded close on
# the trading day NEAREST to 1 May of the calendar year in which FY_t ends.
#
#   FY2024 == FY2023-24, fundamentals cover Apr-2023 .. Mar-2024
#   benchmark = close nearest 1-May-2024
#
# The date sits one month after the fundamentals window closes, so it is an
# out-of-sample outcome and never an input. A single dated observation is a
# cleaner accuracy test than an annual aggregate: it is one price a share
# actually traded at, and every model faces the identical figure.
#
#   "may1"   close nearest 1 May following FY end          (default)
#   "mean"   arithmetic mean of the whole assessment year  (robustness re-run)
#   "close"  last traded close of the assessment year      (robustness re-run)
#
# The old "high_52w" basis has been removed. It drew the maximum of a price
# distribution rather than a central value, which forced a constant negative
# bias into every model and inflated every MAPE figure.
BENCHMARK_BASIS = "may1"

# Target date, expressed as (month, day) of the calendar year the FY ends in.
BENCHMARK_MONTH = 5
BENCHMARK_DAY = 1

# Widest gap tolerated between the target date and the chosen trading day.
# 1 May is Maharashtra Day - a market holiday - and frequently abuts a
# weekend, so an exact hit is the exception. Ten calendar days absorbs the
# holiday plus an adjacent weekend plus a stray closure. Anything wider means
# the scrip genuinely was not trading (pre-listing, suspension) and should
# surface as a blank cell with a reason rather than reach for a price weeks
# away and pass it off as a 1 May observation.
BENCHMARK_MAX_OFFSET_DAYS = 10

# Used only by the "mean" and "close" robustness bases, which still operate
# over the whole assessment year (the FY after the one valued).
BENCHMARK_OFFSET_YEARS = 1
MIN_SESSIONS_FOR_BENCHMARK = 60
BENCHMARK_FULL_YEAR_SESSIONS = 200

# ---------------- Cost of capital ----------------
RISK_FREE_RATE = 0.0705
EQUITY_RISK_PREMIUM = 0.0550
DEFAULT_BETA = 1.00
COST_OF_DEBT = 0.0850
DEFAULT_TAX_RATE = 0.2517

# ---------------- DCF ----------------
PROJECTION_YEARS = 5
TERMINAL_GROWTH = 0.0500
MIN_GROWTH = 0.0200
MAX_GROWTH = 0.1800
DEFAULT_GROWTH = 0.0800
WACC_SPREAD_OVER_G = 0.0200

# ---------------- Relative valuation ----------------
PE_BOUNDS = (2.0, 120.0)
EV_EBITDA_BOUNDS = (1.0, 60.0)
MIN_PEERS_FOR_MEDIAN = 2

# ---------------- Market / IO ----------------
EXCHANGE_SUFFIX = ".NS"
CURRENCY_SYMBOL = "₹"
REQUEST_PAUSE = 0.6
OFFLINE = False

# ---------------- Overrides ----------------
USE_OVERRIDES = True

# ---------------- Data sufficiency gate ----------------
# Runs AFTER the fetch and BEFORE the estimation layer. That order is the whole
# point. estimation.py can manufacture a defensible value for almost any gap,
# so a sufficiency test placed after it would never fail anybody. Everything
# the gate inspects is therefore reported by the source or hand-entered in
# fundamentals_override.csv - nothing inferred.
SUFFICIENCY_ENABLED = True

# "enforce"      -> failing companies are dropped from the report grid
# "report_only"  -> nobody is dropped; the sheet is still written (dry run)
SUFFICIENCY_MODE = "enforce"

# A financial year counts as COMPLETE only when every one of these carries a
# value. Trim the tuple to loosen the gate; that is a cheaper adjustment than
# lowering MIN_COMPLETE_FY, because it keeps the year count honest.
SUFFICIENCY_REQUIRED_FIELDS = (
    "revenue",
    "ebit",
    "ebitda",
    "net_income",
    "eps",
    "ocf",
    "capex",
    "shares",
    "total_debt",
    "cash",
    "equity",
)

# Whether the in-FY anchor price must also be present for a year to count.
SUFFICIENCY_REQUIRE_ANCHOR_PRICE = True

# How many of the FY_LIST years must be complete for a company to stay in.
#
# CALIBRATION WARNING: yfinance publishes roughly the latest four annual
# statement periods, so FY2021 is usually unavailable and 4 is effectively the
# observable ceiling, not a comfortable middle. output/screening_report.csv
# already records HAL and BEL at three usable years. Run
# 'python run.py --screen-only' before trusting this number.
MIN_COMPLETE_FY = 4

# How many years must carry a benchmark price for the company to be scorable.
# A company with fundamentals but no post-FY price cannot be evaluated against
# anything, which makes it useless as a test case however clean its accounts.
MIN_BENCHMARK_FY = 4

# What happens to an excluded company elsewhere in the run. Both default True:
# thin data is not wrong data, and pulling these firms out of the sector
# medians would degrade the valuations of every company that survived.
SUFFICIENCY_KEEP_IN_PEERS = True
SUFFICIENCY_KEEP_IN_ML = True

# Write the passing companies into the sheet too, so it reads as a full audit
# of the sample rather than a list of casualties.
EXCLUSION_SHEET_INCLUDE_PASSED = False

EXCLUSIONS_BASENAME = "Intrinsic_Value_Excluded"
EXCLUSIONS_SHEET_NAME = "Excluded Companies"

# ---------------- Estimation layer ----------------
# "off"        -> report only what was fetched
# "balanced"   -> fill gaps with documented methods (recommended)
# "aggressive" -> additionally back-cast pre-listing prices from sector proxies
ESTIMATION_MODE = "balanced"
ESTIMATE_MARKER = "*"
WRITE_METHOD_SHEET = True

BACKCAST_MAX_RATIO = 3.0
BACKCAST_MIN_RATIO = 0.33

USE_NORMALISED_EARNINGS = True
NORMALISED_MIN_YEARS = 2

# ---------------- Diagnostics ----------------
SHOW_REASONS = True
REASON_STYLE = "code"  # "code" | "detailed"
WRITE_DIAGNOSTICS = True
LOG_FILE = "run_log.txt"

# ---------------- Output ----------------
OUTPUT_BASENAME = "Intrinsic_Value_Report"
DIAGNOSTICS_BASENAME = "Intrinsic_Value_Diagnostics"
METHODS_BASENAME = "Intrinsic_Value_Methods"
# Numeric twin of the report: same headers, plain floats, no blank separator
# rows, no currency glyphs. This is what the analyzer consumes.
DATA_BASENAME = "Intrinsic_Value_Data"

# "range" -> Financial Year column reads 2023-24
# "int"   -> Financial Year column reads 2024   (the internal FY number)
FY_LABEL_STYLE = "range"

# ---------------- Analysis ----------------
ANALYSIS_ENABLED = True
CHART_DIR_NAME = "charts"
CHART_DPI = 200

# ---------------- Machine learning ----------------
ML_ENABLED = True
# "expanding" -> only prior years (correct, leaves early years empty)
# "loyo"      -> all other years (leaks; comparison only)
# "hybrid"    -> expanding where possible, loyo for early folds, marked as such
ML_SPLIT = "hybrid"
ML_MIN_TRAIN_ROWS = 25
ML_WINSOR_PCT = (0.01, 0.99)
ML_RANDOM_STATE = 42
ML_RATIO_BOUNDS = (0.25, 4.0)
ML_IMPUTE_FROM_SECTOR = True
ML_MIN_FEATURES = 4

# ---------------- GUI ----------------
GUI_THEME = "flatly"  # ttkbootstrap light theme; "darkly" for dark
GUI_THEME_DARK = "darkly"
GUI_WINDOW_SIZE = "1280x820"
GUI_MIN_SIZE = (1060, 700)
