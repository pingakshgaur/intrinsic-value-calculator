# FILE: src/config.py
"""Global assumptions and knobs. Tune these before running."""

import os
from pathlib import Path

# ---------------- Paths ----------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
# INTVAL_OUTPUT_DIR redirects every report file - used by the tests so a test
# run can never overwrite a real report.
OUTPUT_DIR = Path(os.environ.get("INTVAL_OUTPUT_DIR") or PROJECT_ROOT / "output")
CACHE_DIR = PROJECT_ROOT / ".cache"
DEFAULT_INPUT = DATA_DIR / "companies.csv"
OVERRIDE_FILE = DATA_DIR / "fundamentals_override.csv"

# ---------------- Financial year ----------------
# The span the whole program works over, chosen by the user rather than baked
# in. FY_n is the Indian financial year ENDING in March of year n, so
# FY_START = 2021 and FY_END = 2025 means 2020-21 through 2024-25.
#
# FY_LIST is derived, never edited by hand. Call set_fy_range() to move the
# window - it keeps the three in step. Everything downstream reads FY_LIST, so
# changing it changes the fetch window, the valuation loop, the ML folds, the
# sufficiency gate and the spreadsheet together.
FY_START = 2021
FY_END = 2025
FY_LIST = list(range(FY_START, FY_END + 1))

# Bounds offered in the interface. Yahoo Finance publishes roughly four annual
# statement periods for most Indian scrips, so anything earlier than about 2015
# will fetch prices but very few fundamentals. The floor is deliberately looser
# than that: a user with a populated fundamentals_override.csv can legitimately
# go back further, and the sufficiency gate will tell them the truth either way.
FY_MIN_ALLOWED = 2000
FY_MAX_SPAN = 30

FY_START_MONTH, FY_START_DAY = 4, 1
FY_END_MONTH, FY_END_DAY = 3, 31


def latest_complete_fy(today=None):
    """
    The most recent financial year that has actually finished.

    An FY ending 31 March 2026 is not a valid upper bound until April 2026 -
    before that the accounts do not exist and the run would spend its time
    downloading nothing.
    """
    import datetime as _dt

    today = today or _dt.date.today()
    return today.year if today.month > FY_END_MONTH else today.year - 1


def set_fy_range(start, end):
    """
    Move the financial-year window. -> (start, end) actually applied.

    Guards the obvious mistakes rather than trusting the caller: the two ends
    are swapped if given backwards, clamped into the allowed range, and capped
    at FY_MAX_SPAN years so a typo of 1021 does not launch a thousand-year
    download.
    """
    global FY_START, FY_END, FY_LIST

    start, end = int(start), int(end)
    if start > end:
        start, end = end, start

    ceiling = latest_complete_fy()
    start = max(FY_MIN_ALLOWED, min(start, ceiling))
    end = max(FY_MIN_ALLOWED, min(end, ceiling))
    if end - start + 1 > FY_MAX_SPAN:
        start = end - FY_MAX_SPAN + 1

    FY_START, FY_END = start, end
    FY_LIST = list(range(start, end + 1))
    return FY_START, FY_END

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

# ---------------- Graham Number ----------------
# 22.5 is Graham's own figure: a P/E ceiling of 15 multiplied by a
# price-to-book ceiling of 1.5, so a company can breach one limit provided it
# compensates on the other. Raising it does not make the method less
# conservative in any principled way - it just moves the goalposts, so leave
# it alone unless the thesis says why.
GRAHAM_MULTIPLIER = 22.5

# A very large EPS against a very thin book value can push the square root
# somewhere implausible. Above this multiple of book value per share the
# result is still reported, but flagged on the Methods sheet rather than
# presented as though it were ordinary. Set to 0 to switch the note off.
GRAHAM_MAX_MULTIPLE_OF_BVPS = 8.0

# ---------------- Adjusted beta (Residual Income + Hybrid) ----------------
# beta_adj = w x company beta + (1 - w) x sector median beta. With the sector
# at 1.0 this is the Blume adjustment. The original DCF keeps the raw beta so
# the baseline comparison is unchanged. See src/models/capital.py.
BETA_SHRINK_WEIGHT = 0.67
BETA_MIN_SECTOR_PEERS = 2

# ---------------- Residual Income ----------------
# Persistence of abnormal earnings in Ohlson's linear-information model.
# 0.62 is the pooled estimate of Dechow, Hutton & Sloan (1999); 0 means excess
# returns vanish after a year, 1 means they last forever.
RI_PERSISTENCE = 0.62
RI_ROE_LOOKBACK = 3  # years of ROE in the normalised median (point-in-time)
RI_ROE_BOUNDS = (-0.50, 0.60)

# ---------------- Hybrid ----------------
# See src/models/model_ensemble.py for the full method.
HYBRID_FADE_YEARS = 5  # DCF+ growth fades to terminal over these years
HYBRID_TERMINAL_GROWTH = None  # None -> TERMINAL_GROWTH
HYBRID_RONIC_PREMIUM = 0.02  # return on new invested capital = WACC + this

HYBRID_REG_MIN_OBS = 8  # regression multiples need this many points
HYBRID_RIDGE_LAMBDA = 1.0
HYBRID_REG_BLEND = 0.5  # share of the regression in the final multiple

HYBRID_MIN_ERR_OBS = 4  # error history needed before skill counts
# Remove each component's typical prior-year miss (median signed log error in
# the sector, shrunk by evidence) before blending. Point-in-time. Turn off to
# see the raw ensemble; state in the methodology which was used.
HYBRID_BIAS_CORRECT = True
HYBRID_SHRINK_K = 10  # evidence needed to move halfway off equal weight
HYBRID_ESTIMATE_PENALTY = 0.75  # weight multiplier for estimated components
HYBRID_OUTLIER_RATIO = 3.0  # drop components > 3x away from the centre

HYBRID_DEFAULT_SIGMA = 0.35  # log-error scale when a component has no history
HYBRID_ERROR_CORR = 0.5  # assumed correlation of component errors
HYBRID_MC_DRAWS = 2000
HYBRID_BAND = (10, 90)  # percentiles reported as the value range
# Confidence = predicted chance the market price lands within this tolerance
# of the hybrid value. 60 = "better than 60% chance of being within 20%".
HYBRID_CONF_TOLERANCE = 0.20
HYBRID_CONF_HIGH = 60
HYBRID_CONF_MEDIUM = 35

# Which component applies to which kind of company-year. 0 removes it.
# Graham sits at half weight everywhere: it is a ceiling for a defensive
# buyer, not a central estimate, and the learned weights can raise it if it
# turns out to price a sector well.
HYBRID_REGIME_WEIGHTS = {
    "mature": {"dcf_plus": 1.0, "ri": 1.0, "pe_reg": 1.0, "ev_reg": 1.0, "graham": 0.5, "ml": 0.75},
    "lender": {"dcf_plus": 0.0, "ri": 1.5, "pe_reg": 1.0, "ev_reg": 0.0, "graham": 0.75, "ml": 0.75},
    "loss_maker": {"dcf_plus": 0.75, "ri": 1.25, "pe_reg": 0.5, "ev_reg": 0.75, "graham": 0.25, "ml": 0.75},
    "young": {"dcf_plus": 0.5, "ri": 1.0, "pe_reg": 1.25, "ev_reg": 1.25, "graham": 0.5, "ml": 0.5},
}

# ---------------- Which models run ----------------
# Every model on by default. The Settings page writes this dictionary, and
# model_registry.py is what the rest of the program asks - so unticking a
# model here removes it from the calculation AND from both of its spreadsheet
# columns AND from the charts, rather than leaving an empty column behind.
#
# The machine-learning entries are additionally subject to ML_ENABLED, which
# is the master switch for that whole stage.
MODELS_ENABLED = {
    "dcf": True,
    "pe": True,
    "ev": True,
    "graham": True,
    "ri": True,
    "xgboost": True,
    "random_forest": True,
    "lightgbm": True,
    "mlp": True,
    "ensemble": True,
    "hybrid_model": True,
}

# ---------------- Market / IO ----------------
EXCHANGE_SUFFIX = ".NS"
CURRENCY_SYMBOL = "₹"
REQUEST_PAUSE = 0.6
OFFLINE = False

# On Windows, let Python trust the certificates Windows trusts. Needed when an
# antivirus (Norton, Kaspersky, Avast...) or a proxy scans HTTPS traffic -
# otherwise every download fails with CERTIFICATE_VERIFY_FAILED. Verification
# stays on. See src/ssl_trust.py.
USE_SYSTEM_CERTS = True

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
# CALIBRATED, not assumed. The 52-company screening run of 30 Aug 2026 returned
# a maximum complete_fy of 3 across the entire sample - including TCS, Infosys,
# HUL, ITC and Power Grid. yfinance serves ~4 annual statement periods, so
# FY2020-21 is absent for every company and FY2021-22 for most. Three is
# therefore the observable ceiling, and a higher bar excludes 100% of the
# sample regardless of which companies are listed.
#
# State this in the methodology as a data-availability constraint of the
# source, not a quality judgement about the firms. The honest framing is:
# "the panel is FY2022-23 to FY2024-25, three years, because the price and
# fundamentals provider does not serve deeper annual history."
MIN_COMPLETE_FY = 3

# Benchmark prices are far better covered than fundamentals - most companies
# returned 5/5 - so this can stay stricter than MIN_COMPLETE_FY without
# excluding anyone. It exists to catch recent IPOs whose pre-listing years
# have no traded price to be scored against.
MIN_BENCHMARK_FY = 3

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

# The plain-English twin of the sheet above. Same companies, same verdicts,
# written for someone who has never opened an annual report: a named category
# of problem, two or three ordinary sentences, and a concrete next step. The
# technical sheet stays exactly as it was - this sits beside it.
PLAIN_EXCLUSIONS_BASENAME = "Why_Companies_Were_Left_Out"
PLAIN_SUMMARY_SHEET_NAME = "Left Out - Summary"
PLAIN_EXCLUSIONS_SHEET_NAME = "Left Out - In Plain English"
PLAIN_YEARS_SHEET_NAME = "Left Out - Year By Year"

# If the gate would reject every single company, drop the threshold to the
# best figure any company actually achieved and screen again, printing a loud
# notice. Returning an empty report is never the helpful answer: the user gets
# no files and no way to tell whether the engine broke or the bar was too high.
SUFFICIENCY_AUTO_RELAX = True

# ---------------- Plain-language output ----------------
# Print a jargon-free summary after the technical one. The technical output is
# what you cite in the thesis; this is what makes the tool usable by someone
# who has never heard of EV/EBITDA.
PLAIN_SUMMARY = True

# A model value this far from the market price is called cheap or expensive in
# the plain-language summary. Inside the band, the verdict is "about right".
PLAIN_VERDICT_BAND = 0.10

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

# ---------------- Auto-train (python run.py --train-universe auto) ----------------
# Fetches training companies one by one from public NSE lists + Yahoo Finance,
# retrains the ML models every AUTO_BATCH companies, re-scores the Hybrid, and
# stops at the FIRST of: confidence target reached, learning plateaued,
# AUTO_MAX_COMPANIES learned, candidates exhausted, or the user says stop.
# See src/auto_train.py.
AUTO_TARGET = None  # None -> HYBRID_CONF_HIGH ("High")
AUTO_MAX_COMPANIES = 100
AUTO_SECTORS = 10  # how many of the best-ranked sectors to draw from
AUTO_MIN_LISTED_YEARS = 10  # NSE listing date at least this long ago
AUTO_BATCH = 10  # retrain + re-score after this many new companies
# Optional early stop: this many retrains in a row each gaining < AUTO_MIN_GAIN.
# 0 = off, so a run goes on to AUTO_MAX_COMPANIES unless the target is hit.
AUTO_PATIENCE = 0
AUTO_MIN_GAIN = 0.5  # confidence points
# "performance": median price return over AUTO_RANK_YEARS ending at the START
#                of the valuation window - point-in-time, no hindsight
# "breadth":     sectors with the most long-listed companies
AUTO_SECTOR_RANK = "performance"
AUTO_RANK_YEARS = 5
AUTO_INCLUDE_FINANCIALS = False
AUTO_CACHE_DAYS = 7  # reuse a fetched training company for this long

# ---------------- GUI ----------------
# Base ttkbootstrap theme, tried in order - the first one this installation
# actually ships is used. ttkbootstrap 2.x carries the "-light"/"-dark" curated
# families; 1.x does not, so the older names sit at the end as a fallback.
# The palette in gui.py is layered on top of whichever base wins, so the app
# looks the same either way.
GUI_LIGHT_THEMES = ("one-light", "nord-light", "litera", "flatly", "cosmo")
GUI_DARK_THEMES = ("one-dark", "nord-dark", "darkly", "superhero", "cyborg")

# Kept for backwards compatibility with older copies of gui.py.
GUI_THEME = "flatly"
GUI_THEME_DARK = "darkly"

GUI_WINDOW_SIZE = "1360x880"
GUI_MIN_SIZE = (1120, 720)

# Remember the light/dark choice between sessions.
GUI_START_IN_DARK = False

# How many "units" one notch of the mouse wheel scrolls. Three is the Windows
# default for text; the stock Tk canvas binding uses one, which is what made
# the settings page feel like it was not scrolling at all.
GUI_SCROLL_STEP = 3
