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
# stay inside FY_t. Do not point it at the assessment year - that would feed
# next year's price into this year's valuation, which is look-ahead bias.
PRICE_MODE = "average"
FY_MEAN_BASIS = "trading"  # or "calendar"
MIN_TRADING_DAYS_FOR_FY = 60
PARTIAL_YEAR_SESSIONS = 200

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
# Numeric twin of the report: same headers, plain floats, no blank separator
# rows, no currency glyphs. This is what the analyzer consumes.
# "range" -> Financial Year column reads 2023-24
# "int"   -> Financial Year column reads 2024   (the internal FY number)
OUTPUT_BASENAME = "Intrinsic_Value_Report"
DATA_BASENAME = "Intrinsic_Value_Data"
FY_LABEL_STYLE = "range"
DIAGNOSTICS_BASENAME = "Intrinsic_Value_Diagnostics"
METHODS_BASENAME = "Intrinsic_Value_Methods"

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

# ---------------- Analysis ----------------
ANALYSIS_ENABLED = True
CHART_DIR_NAME = "charts"
CHART_DPI = 200
