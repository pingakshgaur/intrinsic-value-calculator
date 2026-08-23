"""
XGBoost gradient-boosted trees.

Each tree corrects the residual error of the ensemble so far. Strong on tabular
financial data with non-linear interactions, and robust to unscaled features.

Hyperparameters are deliberately conservative: shallow trees, heavy L2, high
min_child_weight. With a panel of a few hundred rows an unregularised booster
memorises the training years within a handful of rounds.
"""

import config
from result import Result, R

KEY = "xgboost"
NAME = "XGBoost"
COLUMN = "(XGBoost) Intrinsic Value"


def build_estimator():
    from xgboost import XGBRegressor  # imported late so a missing lib is a
    return XGBRegressor(  # per-model failure, not a crash
        n_estimators=400,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=2.0,
        reg_alpha=0.1,
        min_child_weight=5,
        objective="reg:squarederror",
        random_state=config.ML_RANDOM_STATE,
        n_jobs=-1,
        verbosity=0,
    )


SPEC = {"key": KEY, "name": NAME, "build": build_estimator}


def intrinsic_value(store, company_name, fy) -> Result:
    if store is None:
        return Result.bad(
            R.MODEL_NA, "machine-learning stage disabled (ML_ENABLED = False)"
        )
    return store.get(KEY, company_name, fy)
