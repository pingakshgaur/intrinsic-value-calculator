# FILE: src/models/model_mlp.py
"""
Multi-Layer Perceptron - a small feed-forward neural network (scikit-learn).

Where the three tree models split the feature space into boxes, this one fits
a smooth surface across it. Two hidden layers of ReLU units learn combinations
of the inputs that no single feature carries on its own - a margin that only
matters at a particular level of debt, say. Where the trees would need a
staircase of splits to approximate that, the network draws the curve.

That is the argument for including it. The argument for reading it carefully
is that it is the least interpretable model here and the hungriest for data:
with a few hundred company-years it can settle into a quite different solution
on a different random seed. ML_RANDOM_STATE is fixed so a given run is
reproducible, but do not mistake reproducibility for stability.

WHY THIS ONE IS WRAPPED IN A PIPELINE AND THE OTHERS ARE NOT

Trees split on one feature at a time, so the scale of each feature is
irrelevant to them - ml_common therefore winsorises and median-fills, and
stops there. A neural network is the opposite case: it sums weighted inputs,
so a feature measured in crores swamps one measured as a ratio, and gradient
descent then spends its whole budget on the large-numbered column. Feeding raw
features to an MLP does not error, it just quietly produces a bad model.

So the estimator handed back here is a Pipeline: StandardScaler first, network
second. Because it is fitted as one object, the scaler learns its mean and
scale from the TRAINING fold only and then applies them to the test fold -
which is exactly what must happen, and what a scaler fitted outside the fold
loop would get wrong.

early_stopping holds back 15% of the training rows and stops when the
validation loss stops improving, which is what keeps a 400-iteration budget
from turning into 400 iterations of memorising.
"""

import config
from result import Result, R

KEY = "mlp"
NAME = "MLP Neural Network"
COLUMN = "(MLP Neural Network) Intrinsic Value"


def build_estimator():
    # Imported late so that a missing or broken scikit-learn is reported as a
    # per-model failure in the diagnostics, exactly like the other learners,
    # rather than taking the whole run down at import time.
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    net = MLPRegressor(
        hidden_layer_sizes=(64, 32),
        activation="relu",
        solver="adam",
        alpha=1e-3,  # L2 penalty; the panel is small, so keep it real
        learning_rate="adaptive",
        learning_rate_init=1e-3,
        batch_size="auto",
        max_iter=400,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
        tol=1e-4,
        shuffle=True,
        random_state=config.ML_RANDOM_STATE,
    )
    return Pipeline([("scale", StandardScaler()), ("net", net)])


SPEC = {"key": KEY, "name": NAME, "build": build_estimator}


def intrinsic_value(store, company_name, fy) -> Result:
    if store is None:
        return Result.bad(
            R.MODEL_NA, "machine-learning stage disabled (ML_ENABLED = False)"
        )
    return store.get(KEY, company_name, fy)
