"""
LightGBM gradient-boosted trees.

Note on the library: LightGBM is its own package (`pip install lightgbm`), not
part of scikit-learn - though it ships a scikit-learn-compatible wrapper, which
is what is used here, so it drops into the same fit/predict harness.

Differs from XGBoost by growing leaf-wise rather than level-wise, which is
faster but overfits more readily on small data. num_leaves is therefore capped
tightly and min_child_samples raised.
"""

import config
from result import Result, R

KEY = "lightgbm"
NAME = "LightGBM"
COLUMN = "(LightGBM) Intrinsic Value"


def build_estimator():
    from lightgbm import LGBMRegressor
    return LGBMRegressor(
        n_estimators=400,
        max_depth=4,
        num_leaves=15,
        learning_rate=0.05,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=2.0,
        reg_alpha=0.1,
        min_child_samples=10,
        random_state=config.ML_RANDOM_STATE,
        n_jobs=-1,
        verbose=-1,
    )


SPEC = {"key": KEY, "name": NAME, "build": build_estimator}


def intrinsic_value(store, company_name, fy) -> Result:
    if store is None:
        return Result.bad(
            R.MODEL_NA, "machine-learning stage disabled (ML_ENABLED = False)"
        )
    return store.get(KEY, company_name, fy)
