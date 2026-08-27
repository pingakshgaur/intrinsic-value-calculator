# FILE: src/models/ml_common.py
"""
Shared machine-learning pipeline.

Target: label = mean price of FY+1 / mean price of FY   (forward price ratio)
        IV    = mean price of FY x predicted ratio

There is no ground-truth "intrinsic value" to train on; this is the standard
proxy. It learns which fundamental profiles historically preceded a re-rating.

Discipline enforced here:
  * Expanding-window split: fold for year T trains only on years < T.
    ML_SPLIT="hybrid" falls back to leave-one-year-out for early folds and
    MARKS every prediction so produced as estimated.
  * Winsorisation bounds and imputation medians fitted on the TRAINING FOLD
    ONLY, then applied to the test fold.
  * Every prediction is a Result carrying a reason when it fails.
"""

import logging
import math
import os

import numpy as np
import pandas as pd

import config
from result import Result, R

log = logging.getLogger("ml")

NUMERIC_FEATURES = [
    "ebitda_margin",
    "net_margin",
    "roe",
    "roce",
    "debt_to_equity",
    "net_debt_to_ebitda",
    "interest_free_proxy",
    "capex_to_revenue",
    "ocf_to_ebitda",
    "accruals_ratio",
    "asset_turnover",
    "earnings_yield",
    "book_to_price",
    "fcf_yield",
    "ev_ebitda",
    "revenue_growth_1y",
    "ebitda_growth_1y",
    "eps_growth_1y",
    "beta",
    "log_market_cap",
    "cap_tier_ord",
]

CAP_ORDINAL = {"large": 2.0, "mid": 1.0, "small": 0.0}


def _safe_div(a, b):
    if a is None or b is None:
        return None
    try:
        if b == 0:
            return None
        v = a / b
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ZeroDivisionError):
        return None


def _growth(curr, prev):
    if curr is None or prev is None or prev <= 0:
        return None
    return (curr - prev) / prev


def compute_features(years, fy, beta, cap_tier):
    d = years.get(fy)
    if not d:
        return None, Result.bad(R.NO_PERIOD, f"no data assembled for FY{fy}")

    prev = years.get(fy - 1) or {}
    price, shares = d.get("price"), d.get("shares")
    revenue, ebitda, equity = d.get("revenue"), d.get("ebitda"), d.get("equity")
    debt = d.get("total_debt") or 0.0
    cash = d.get("cash") or 0.0
    mcap = (price * shares) if (price and shares) else None
    ev = (mcap + debt - cash) if mcap is not None else None
    fcf = (
        (d.get("ocf") - d.get("capex"))
        if (d.get("ocf") is not None and d.get("capex") is not None)
        else None
    )
    cap_emp = (
        (d.get("assets") - d.get("cur_liab"))
        if (d.get("assets") is not None and d.get("cur_liab") is not None)
        else None
    )

    f = {
        "ebitda_margin": _safe_div(ebitda, revenue),
        "net_margin": _safe_div(d.get("net_income"), revenue),
        "roe": _safe_div(d.get("net_income"), equity),
        "roce": _safe_div(d.get("ebit"), cap_emp),
        "debt_to_equity": _safe_div(debt, equity),
        "net_debt_to_ebitda": _safe_div(debt - cash, ebitda),
        "interest_free_proxy": 1.0 if debt == 0 else 0.0,
        "capex_to_revenue": _safe_div(d.get("capex"), revenue),
        "ocf_to_ebitda": _safe_div(d.get("ocf"), ebitda),
        "accruals_ratio": _safe_div(
            (
                (d.get("net_income") - d.get("ocf"))
                if (d.get("net_income") is not None and d.get("ocf") is not None)
                else None
            ),
            d.get("assets"),
        ),
        "asset_turnover": _safe_div(revenue, d.get("assets")),
        "earnings_yield": _safe_div(d.get("eps"), price),
        "book_to_price": _safe_div(equity, mcap),
        "fcf_yield": _safe_div(fcf, mcap),
        "ev_ebitda": _safe_div(ev, ebitda),
        "revenue_growth_1y": _growth(revenue, prev.get("revenue")),
        "ebitda_growth_1y": _growth(ebitda, prev.get("ebitda")),
        "eps_growth_1y": _growth(d.get("eps"), prev.get("eps")),
        "beta": beta,
        "log_market_cap": math.log(mcap) if (mcap and mcap > 0) else None,
        "cap_tier_ord": CAP_ORDINAL.get((cap_tier or "").strip().lower()),
    }

    present = sum(1 for v in f.values() if v is not None)
    floor = getattr(config, "ML_MIN_FEATURES", 8)
    if present < floor:
        missing = [k for k, v in f.items() if v is None][:6]
        return None, Result.bad(
            R.FEATURES_MISSING,
            f"only {present} of {len(f)} features computable for FY{fy} "
            f"(minimum {floor}); missing include {', '.join(missing)}",
        )
    return f, None


def compute_label(years, fy):
    d = years.get(fy) or {}
    p0, p1 = d.get("price"), d.get("price_fwd")
    if not p0 or p0 <= 0:
        return None, Result.bad(
            R.PRICE_MISSING, f"no FY{fy} mean price to anchor the label"
        )
    if not p1 or p1 <= 0:
        return None, Result.bad(
            R.NO_LABEL,
            f"no FY{fy + 1} mean price, so the forward-return label for FY{fy} "
            f"cannot be formed; usable for prediction but not for training",
        )
    return p1 / p0, None


def build_dataset(universe, fy_list=None):
    fy_list = fy_list or config.FY_LIST
    records, failures = [], {}

    for name, rec in universe.items():
        data = rec["data"]
        beta = data.get("beta", config.DEFAULT_BETA)
        cap = rec.get("cap", "")
        for fy in fy_list:
            feats, err = compute_features(data.get("years", {}), fy, beta, cap)
            if err:
                failures[(name, fy)] = err
                continue
            label, lerr = compute_label(data.get("years", {}), fy)
            row = {
                "company": name,
                "sector": rec["sector"],
                "fy": fy,
                "price": (data["years"][fy] or {}).get("price"),
                "label": label,
            }
            row.update(feats)
            records.append(row)
            if lerr:
                row["label"] = np.nan

    if not records:
        return pd.DataFrame(), failures

    df = pd.DataFrame(records)

    if getattr(config, "ML_IMPUTE_FROM_SECTOR", False):
        for col in NUMERIC_FEATURES:
            if col not in df.columns:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            by_sec = df.groupby(["sector", "fy"])[col].transform(
                lambda x: pd.to_numeric(x, errors="coerce").median()
            )
            df[col] = s.fillna(by_sec).fillna(s.median())

    sectors = sorted(df["sector"].dropna().unique())
    for s in sectors:
        df[f"sector_{s}"] = (df["sector"] == s).astype(float)
    df.attrs["sector_cols"] = [f"sector_{s}" for s in sectors]
    return df, failures


def feature_columns(df):
    return NUMERIC_FEATURES + list(df.attrs.get("sector_cols", []))


def fit_preprocessor(train_df, cols):
    lo_q, hi_q = config.ML_WINSOR_PCT
    stats = {}
    for c in cols:
        s = pd.to_numeric(train_df[c], errors="coerce")
        if s.notna().sum() == 0:
            stats[c] = {"lo": 0.0, "hi": 0.0, "med": 0.0}
            continue
        stats[c] = {
            "lo": float(s.quantile(lo_q)),
            "hi": float(s.quantile(hi_q)),
            "med": float(s.median()),
        }
    return stats


def apply_preprocessor(df, cols, stats):
    out = pd.DataFrame(index=df.index)
    for c in cols:
        s = pd.to_numeric(df[c], errors="coerce")
        st = stats[c]
        out[c] = s.clip(st["lo"], st["hi"]).fillna(st["med"])
    return out


class MLStore:
    def __init__(self):
        self.predictions = {}
        self.metrics = []
        self.feature_importance = {}

    def get(self, model_key, company, fy):
        return self.predictions.get(model_key, {}).get(
            (company, fy),
            Result.bad(R.NOT_COMPUTABLE, "model produced no prediction for this row"),
        )


def _train_indices(df, target_fy, mode):
    """-> (index, used_future_years_flag)"""
    labelled = df["label"].notna()
    if mode == "loyo":
        return df.index[labelled & (df["fy"] != target_fy)], True
    idx = df.index[labelled & (df["fy"] < target_fy)]
    if mode == "hybrid" and len(idx) < config.ML_MIN_TRAIN_ROWS:
        return df.index[labelled & (df["fy"] != target_fy)], True
    return idx, False


def run_models(df, specs, failures, fy_list=None):
    fy_list = fy_list or config.FY_LIST
    store = MLStore()
    for s in specs:
        store.predictions[s["key"]] = {}

    if df.empty:
        for s in specs:
            for (comp, fy), res in failures.items():
                store.predictions[s["key"]][(comp, fy)] = res
        return store

    cols = feature_columns(df)
    mode = config.ML_SPLIT
    lo_r, hi_r = config.ML_RATIO_BOUNDS

    for fy in fy_list:
        test_idx = df.index[df["fy"] == fy]
        if len(test_idx) == 0:
            continue

        train_idx, leaked = _train_indices(df, fy, mode)
        n_train = len(train_idx)

        if n_train < config.ML_MIN_TRAIN_ROWS:
            reason = Result.bad(
                R.NO_TRAINING_DATA,
                f"FY{fy} fold had only {n_train} labelled training row(s), below "
                f"the minimum of {config.ML_MIN_TRAIN_ROWS}. Widen the training "
                f"universe with --train-universe.",
            )
            for s in specs:
                for i in test_idx:
                    store.predictions[s["key"]][(df.at[i, "company"], fy)] = reason
            store.metrics.append(
                {
                    "fold_fy": fy,
                    "model": "(all)",
                    "n_train": n_train,
                    "n_test": len(test_idx),
                    "status": "skipped",
                }
            )
            continue

        stats = fit_preprocessor(df.loc[train_idx], cols)
        X_train = apply_preprocessor(df.loc[train_idx], cols, stats)
        y_train = df.loc[train_idx, "label"].astype(float)
        X_test = apply_preprocessor(df.loc[test_idx], cols, stats)

        leak_note = (
            (
                f"leave-one-year-out fold (training included years after "
                f"FY{fy}; not a forward-looking prediction)"
            )
            if leaked
            else None
        )

        for s in specs:
            key, name = s["key"], s["name"]
            try:
                est = s["build"]()
            except Exception as e:
                log.exception("estimator construction failed: %s", name)
                bad = Result.bad(
                    R.LIB_MISSING, f"{name} unavailable: {type(e).__name__}: {e}"
                )
                for i in test_idx:
                    store.predictions[key][(df.at[i, "company"], fy)] = bad
                continue

            try:
                est.fit(X_train.values, y_train.values)
                preds = est.predict(X_test.values)
            except Exception as e:
                log.exception("%s failed on FY%s fold", name, fy)
                bad = Result.bad(
                    R.CALC_ERROR,
                    f"{name} training/prediction raised " f"{type(e).__name__}: {e}",
                )
                for i in test_idx:
                    store.predictions[key][(df.at[i, "company"], fy)] = bad
                continue

            try:
                imp = getattr(est, "feature_importances_", None)
                if imp is not None:
                    acc = store.feature_importance.setdefault(key, {})
                    for c, v in zip(cols, imp):
                        acc[c] = acc.get(c, 0.0) + float(v)
            except Exception:
                pass

            for i, ratio in zip(test_idx, preds):
                comp = df.at[i, "company"]
                price = df.at[i, "price"]
                if price is None or (isinstance(price, float) and math.isnan(price)):
                    store.predictions[key][(comp, fy)] = Result.bad(
                        R.PRICE_MISSING,
                        f"{name} predicted a ratio of {ratio:.3f} but there is no "
                        f"FY{fy} mean price to multiply it by",
                    )
                    continue

                methods = [leak_note] if leak_note else []
                r = float(ratio)
                if not (lo_r <= r <= hi_r):
                    if config.ESTIMATION_MODE == "off":
                        store.predictions[key][(comp, fy)] = Result.bad(
                            R.IMPLAUSIBLE,
                            f"{name} predicted a forward ratio of {r:.2f}, outside "
                            f"the plausible band {lo_r}-{hi_r}",
                        )
                        continue
                    clipped = min(max(r, lo_r), hi_r)
                    methods.append(
                        f"prediction clipped from {r:.2f} to {clipped:.2f} "
                        f"(outside plausible band {lo_r}-{hi_r})"
                    )
                    r = clipped

                store.predictions[key][(comp, fy)] = Result.good(
                    price * r, method="; ".join(methods) if methods else None
                )

            truth = df.loc[test_idx, "label"].astype(float)
            mask = truth.notna().values
            if mask.sum() >= 2:
                err = np.asarray(preds)[mask] - truth.values[mask]
                direction = (
                    (np.asarray(preds)[mask] > 1.0) == (truth.values[mask] > 1.0)
                ).mean()
                store.metrics.append(
                    {
                        "fold_fy": fy,
                        "model": name,
                        "n_train": n_train,
                        "n_test": int(mask.sum()),
                        "rmse_ratio": round(float(np.sqrt((err**2).mean())), 4),
                        "mae_ratio": round(float(np.abs(err).mean()), 4),
                        "directional_accuracy": round(float(direction), 3),
                        "leaked": bool(leaked),
                        "status": "ok",
                    }
                )
            else:
                store.metrics.append(
                    {
                        "fold_fy": fy,
                        "model": name,
                        "n_train": n_train,
                        "n_test": 0,
                        "leaked": bool(leaked),
                        "status": "no labelled test rows",
                    }
                )

    for s in specs:
        for (comp, fy), res in failures.items():
            store.predictions[s["key"]].setdefault((comp, fy), res)

    return store


def write_diagnostics(store, df):
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    if store.metrics:
        p = config.OUTPUT_DIR / "ml_metrics.csv"
        pd.DataFrame(store.metrics).to_csv(p, index=False, encoding="utf-8-sig")
        paths.append(p)

    if store.feature_importance:
        rows = []
        for key, acc in store.feature_importance.items():
            total = sum(acc.values()) or 1.0
            for feat, v in sorted(acc.items(), key=lambda x: -x[1]):
                rows.append(
                    {
                        "model": key,
                        "feature": feat,
                        "importance_share": round(v / total, 4),
                    }
                )
        p = config.OUTPUT_DIR / "ml_feature_importance.csv"
        pd.DataFrame(rows).to_csv(p, index=False, encoding="utf-8-sig")
        paths.append(p)

    if not df.empty:
        p = config.OUTPUT_DIR / "ml_dataset.csv"
        df.to_csv(p, index=False, encoding="utf-8-sig")
        paths.append(p)

    return paths
