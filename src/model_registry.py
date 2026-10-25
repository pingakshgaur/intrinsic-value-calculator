# FILE: src/model_registry.py
"""
The single list of valuation models, and which of them are switched on.

WHY THIS EXISTS

The model set used to be written down in four separate places: pipeline.py
computed them, exporter.py named their columns, csv_analyzer.py charted them,
and gui.py described them. Adding one model meant editing all four and hoping
none was missed; letting the user switch one OFF meant they would have
disagreed with each other immediately - the engine skipping a model the
exporter still expected a column for.

So the list lives here once, and everything else asks this module. Turning a
model off in Settings removes it from the calculation, from BOTH of its
spreadsheet columns, from the diagnostics and methods sheets, and from the
charts, because all four read the same answer.

WHAT A MODEL IS

    key          the short name used as the row key inside the pipeline
    name         what a person calls it
    column       header of its intrinsic-value column in the report
    diff_column  header of its "Market Price - Intrinsic Value" column
    kind         "traditional" (reasons from the accounts),
                 "ml" (learns a pattern from the whole panel), or
                 "hybrid" (blends the others; computed last)
    blurb        two or three plain sentences for the Settings page

ORDER matters: it is the left-to-right order of the spreadsheet. Traditional
methods first, then the machine-learning ones, so the sheet reads from
"worked out from first principles" to "inferred from everybody else".
"""

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    column: str
    diff_column: str
    kind: str
    blurb: str

    @property
    def is_ml(self) -> bool:
        return self.kind == "ml"


ALL_MODELS = [
    ModelSpec(
        key="dcf",
        name="DCF",
        column="(DCF) Intrinsic Value",
        diff_column="Difference (Market - DCF)",
        kind="traditional",
        blurb=(
            "Forecasts the cash the business should generate over the next few "
            "years and works out what that is worth today. Best for steady, "
            "cash-generating companies; weakest for young or loss-making ones."
        ),
    ),
    ModelSpec(
        key="pe",
        name="P/E Relative",
        column="(P/E Relative Valuation) Intrinsic Value",
        diff_column="Difference (Market - P/E Rel. Val.)",
        kind="traditional",
        blurb=(
            "Asks what rival companies in the same sector are worth for each "
            "rupee of profit, then applies that to this company's profit. It "
            "needs the company to actually be making a profit."
        ),
    ),
    ModelSpec(
        key="ev",
        name="EV/EBITDA",
        column="(EV/EBITDA Valuation) Intrinsic Value",
        diff_column="Difference (Market - EV/EBITDA)",
        kind="traditional",
        blurb=(
            "Values the whole business - shares plus borrowings - against its "
            "operating profit, then takes the debt back off. The fairest way to "
            "compare companies that carry very different amounts of debt."
        ),
    ),
    ModelSpec(
        key="graham",
        name="Graham Number",
        column="(Graham Number) Intrinsic Value",
        diff_column="Difference (Market - Graham Number)",
        kind="traditional",
        blurb=(
            "Benjamin Graham's rule of thumb: a deliberately cautious price "
            "worked out from profit per share and the company's own book value. "
            "It is blunt and conservative on purpose, and it says nothing at all "
            "about companies making a loss."
        ),
    ),
    ModelSpec(
        key="ri",
        name="Residual Income",
        column="(Residual Income) Intrinsic Value",
        diff_column="Difference (Market - Residual Income)",
        kind="traditional",
        blurb=(
            "Starts from what the company owns (its book value) and adds the "
            "value of any profit it earns above what shareholders demand. "
            "Unlike the others it still works for banks and for companies "
            "having a bad year."
        ),
    ),
    ModelSpec(
        key="xgboost",
        name="XGBoost",
        column="(XGBoost) Intrinsic Value",
        diff_column="Difference (Market - XGBoost)",
        kind="ml",
        blurb=(
            "Builds hundreds of small decision trees, each one correcting the "
            "mistakes of the last. Usually the sharpest of the learners on "
            "financial tables, and the quickest to overfit a small sample."
        ),
    ),
    ModelSpec(
        key="random_forest",
        name="Random Forest",
        column="(Random Forest) Intrinsic Value",
        diff_column="Difference (Market - Random Forest)",
        kind="ml",
        blurb=(
            "Averages hundreds of independent decision trees. The steadiest of "
            "the learners and the hardest to fool with a small sample, which "
            "makes it the sensible one to read the others against."
        ),
    ),
    ModelSpec(
        key="lightgbm",
        name="LightGBM",
        column="(LightGBM) Intrinsic Value",
        diff_column="Difference (Market - LightGBM)",
        kind="ml",
        blurb=(
            "The same idea as XGBoost, grown a different way and much faster. "
            "Running both is a useful check: where they disagree, neither is "
            "seeing a stable pattern."
        ),
    ),
    ModelSpec(
        key="mlp",
        name="MLP Neural Network",
        column="(MLP Neural Network) Intrinsic Value",
        diff_column="Difference (Market - MLP)",
        kind="ml",
        blurb=(
            "A small neural network. Unlike the tree models it draws smooth "
            "curves rather than steps, so it can catch relationships the others "
            "miss - and it needs more data before its answers settle down."
        ),
    ),
    ModelSpec(
        key="ensemble",
        name="Ensemble",
        column="(Ensemble) Intrinsic Value",
        diff_column="Difference (Market - Ensemble)",
        kind="hybrid",
        blurb=(
            "Combines improved versions of every method above. It first decides "
            "which methods suit this company (no cash-flow model for a bank, "
            "say), then trusts each one in proportion to how well it priced "
            "the sector in earlier years, and reports a likely range and a "
            "confidence score alongside the number."
        ),
    ),
    ModelSpec(
        key="hybrid_model",
        name="HYBRID MODEL",
        column="(HYBRID MODEL) Intrinsic Value",
        diff_column="Difference (Market - HYBRID MODEL)",
        kind="hybrid",
        blurb=(
            "The project's headline value. Six lenses - cash flow, earnings "
            "power, assets, peer multiples, Graham and machine learning - "
            "blended by company type, with growth only paid for when the "
            "company's returns on capital earn it, then adjusted for quality, "
            "governance and bull / base / bear scenarios. Every constant is "
            "editable in the web app's Hybrid Model Lab."
        ),
    ),
]

# Older settings and command lines said "hybrid" for what is now the Ensemble.
ALIASES = {"hybrid": "ensemble"}

BY_KEY = {m.key: m for m in ALL_MODELS}
ALL_KEYS = [m.key for m in ALL_MODELS]


def default_switches():
    """Every model on. Used as the starting point and by 'Reset to defaults'."""
    return {m.key: True for m in ALL_MODELS}


def is_enabled(key) -> bool:
    """
    Is this model switched on for the current run?

    Unknown keys answer False rather than raising: a stale key left in a saved
    setting should quietly do nothing, not stop the program.
    """
    key = ALIASES.get(key, key)
    spec = BY_KEY.get(key)
    if spec is None:
        return False
    switches = getattr(config, "MODELS_ENABLED", None) or {}
    old = [a for a, k in ALIASES.items() if k == key]
    if not switches.get(key, all(switches.get(a, True) for a in old)):
        return False
    # The machine-learning stage has a master switch of its own. When it is
    # off, no learner runs whatever its individual tick-box says.
    if spec.is_ml and not getattr(config, "ML_ENABLED", True):
        return False
    return True


def enabled_models():
    """The models that will actually be computed, in spreadsheet order."""
    return [m for m in ALL_MODELS if is_enabled(m.key)]


def enabled_keys():
    return [m.key for m in enabled_models()]


def traditional_models():
    return [m for m in enabled_models() if not m.is_ml]


def ml_models():
    return [m for m in enabled_models() if m.is_ml]


def describe_selection() -> str:
    """One line for the console header, so a run says what it ran."""
    on = enabled_models()
    if not on:
        return "no models selected"
    trad = [m.name for m in on if not m.is_ml]
    learners = [m.name for m in on if m.is_ml]
    parts = []
    if trad:
        parts.append("traditional: " + ", ".join(trad))
    if learners:
        parts.append("machine learning: " + ", ".join(learners))
    return "; ".join(parts)
