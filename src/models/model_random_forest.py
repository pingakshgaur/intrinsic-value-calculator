"""
Random Forest regressor (scikit-learn).

Hundreds of decorrelated trees, each grown on a bootstrap sample and a random
feature subset, averaged. Bagging rather than boosting, so it is the most
resistant of the three to overfitting on a small panel - which makes it the
sensible baseline to read the other two against.

min_samples_leaf=5 stops leaves forming on one or two company-years.
"""

import config
from result import Result, R

KEY = "random_forest"
NAME = "Random Forest"
COLUMN = "(Random Forest) Intrinsic Value"


def build_estimator():
    from sklearn.ensemble import RandomForestRegressor

    return RandomForestRegressor(
        n_estimators=500,
        max_depth=8,
        min_samples_leaf=5,
        min_samples_split=10,
        max_features="sqrt",
        bootstrap=True,
        random_state=config.ML_RANDOM_STATE,
        n_jobs=-1,
    )


SPEC = {"key": KEY, "name": NAME, "build": build_estimator}


def intrinsic_value(store, company_name, fy) -> Result:
    if store is None:
        return Result.bad(
            R.MODEL_NA, "machine-learning stage disabled (ML_ENABLED = False)"
        )
    return store.get(KEY, company_name, fy)
