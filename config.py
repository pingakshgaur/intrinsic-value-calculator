"""Global assumptions and knobs. Tune these before running."""

# --- Financial year (India: FY2025 = 01-Apr-2024 to 31-Mar-2025) ---
FY_LIST = [2021, 2022, 2023, 2024, 2025]
FY_START_MONTH, FY_START_DAY = 4, 1
FY_END_MONTH, FY_END_DAY = 3, 31

# --- Market price convention for a financial year ---
# Fixed by design: the market price for FY X is the LONG-TERM MEAN of that
# year's daily closing prices (Apr 1 of X-1 through Mar 31 of X). This is not
# a tunable - a single-day close is not representative of a year's market
# performance and would make the intrinsic-vs-market comparison arbitrary.
PRICE_MODE = "average"  # kept for backward compat; do not change

# "trading"  -> mean of the ~247 traded sessions in the FY (standard practice)
# "calendar" -> daily series forward-filled to all ~365 calendar days, then
#               averaged. Weekends/holidays carry the prior close, which
#               slightly overweights Fridays and pre-holiday sessions.
FY_MEAN_BASIS = "trading"

# A mean over a handful of sessions is not a year average. Below this count
# the price is reported as unavailable with the session count in the reason.
MIN_TRADING_DAYS_FOR_FY = 60

# Below this, the mean is still used but flagged as partial-year in _notes.
PARTIAL_YEAR_SESSIONS = 200

# --- Cost of capital inputs (India) ---
RISK_FREE_RATE = 0.0705        # 10Y G-Sec yield
EQUITY_RISK_PREMIUM = 0.0550   # India ERP
DEFAULT_BETA = 1.00
COST_OF_DEBT = 0.0850          # pre-tax
DEFAULT_TAX_RATE = 0.2517      # 25.17% new regime

# --- DCF ---
PROJECTION_YEARS = 5
TERMINAL_GROWTH = 0.0500
MIN_GROWTH = 0.0200
MAX_GROWTH = 0.1800
DEFAULT_GROWTH = 0.0800        # used when history is too thin
WACC_SPREAD_OVER_G = 0.0200    # WACC forced to be >= g_terminal + this

# --- Relative valuation sanity filters (drop absurd multiples from medians) ---
PE_BOUNDS = (2.0, 120.0)
EV_EBITDA_BOUNDS = (1.0, 60.0)
MIN_PEERS_FOR_MEDIAN = 2       # peers excluding the company itself

# --- Market / IO ---
EXCHANGE_SUFFIX = ".NS"        # ".NS" NSE, ".BO" BSE
CURRENCY_SYMBOL = "₹"
OUTPUT_DIR = "output"
CACHE_DIR = ".cache"
REQUEST_PAUSE = 0.6            # seconds between network hits

# --- Diagnostics ---
SHOW_REASONS = True  # False -> print plain "N/A" like before
REASON_STYLE = "detailed"  # "detailed" (CODE: explanation) | "short" (CODE only)
LOG_FILE = "run_log.txt"  # full tracebacks land here, inside OUTPUT_DIR

# --- Output ---
OUTPUT_BASENAME = "Intrinsic_Value_Report"
OFFLINE = False

# ---------------- Machine learning ----------------
ML_ENABLED = True

# "expanding" -> train only on years strictly before the year being predicted.
#                Methodologically correct. FY2021 gets no prediction (no prior
#                year exists) and FY2022 trains on one year only.
# "loyo"      -> leave-one-year-out: train on every other year, including later
#                ones. Fills every cell but LEAKS FUTURE INFORMATION. Use for
#                coverage comparison only; never report as the headline result.
ML_SPLIT = "expanding"

ML_MIN_TRAIN_ROWS = 25  # below this, the fold is refused
ML_WINSOR_PCT = (0.01, 0.99)  # bounds fitted on the training fold only
ML_RANDOM_STATE = 42

# Sanity band on the predicted ratio. A model claiming a 6x re-rating in one
# year is extrapolating, not predicting.
ML_RATIO_BOUNDS = (0.25, 4.0)
