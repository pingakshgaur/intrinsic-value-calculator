# FILE: server/prefs.py
"""
Run preferences: everything the old desktop app's Settings dialog held.

Stored in data/run_preferences.json and turned into run.py flags for every
valuation run started from the browser, so a run from the terminal with the
same flags gives the same answer.
"""

import json

import config
import model_registry

from server.data import DATA

PATH = DATA / "run_preferences.json"


def defaults():
    g = getattr
    return {
        "models": {m.key: bool((g(config, "MODELS_ENABLED", {}) or {}).get(m.key, True)) for m in model_registry.ALL_MODELS},
        "ml_enabled": g(config, "ML_ENABLED", True),
        "ml_split": g(config, "ML_SPLIT", "hybrid"),
        "estimation": g(config, "ESTIMATION_MODE", "balanced"),
        "screening": "off" if not g(config, "SUFFICIENCY_ENABLED", True) else
                     ("report" if g(config, "SUFFICIENCY_MODE", "enforce") == "report_only" else "enforce"),
        "min_complete_fy": g(config, "MIN_COMPLETE_FY", 3),
        "min_benchmark_fy": g(config, "MIN_BENCHMARK_FY", 3),
        "auto_relax": g(config, "SUFFICIENCY_AUTO_RELAX", True),
        "keep_in_peers": g(config, "SUFFICIENCY_KEEP_IN_PEERS", True),
        "keep_in_ml": g(config, "SUFFICIENCY_KEEP_IN_ML", True),
        "require_price": g(config, "SUFFICIENCY_REQUIRE_ANCHOR_PRICE", True),
        "audit_all": g(config, "EXCLUSION_SHEET_INCLUDE_PASSED", False),
        "benchmark_basis": g(config, "BENCHMARK_BASIS", "may1"),
        "bench_offset_days": g(config, "BENCHMARK_MAX_OFFSET_DAYS", 10),
        "mean_basis": g(config, "FY_MEAN_BASIS", "trading"),
        "exchange": g(config, "EXCHANGE_SUFFIX", ".NS"),
        "analyze": g(config, "ANALYSIS_ENABLED", True),
        "dpi": g(config, "CHART_DPI", 200),
        "fy_labels": g(config, "FY_LABEL_STYLE", "range"),
        "reasons": "off" if not g(config, "SHOW_REASONS", True) else g(config, "REASON_STYLE", "code"),
        "overrides": g(config, "USE_OVERRIDES", True),
        "start_year": g(config, "FY_START", 2021),
        "end_year": g(config, "FY_END", 2025),
    }


CHOICES = {
    "ml_split": ("hybrid", "expanding", "loyo"),
    "estimation": ("off", "balanced", "aggressive"),
    "screening": ("enforce", "report", "off"),
    "benchmark_basis": ("may1", "mean", "close"),
    "mean_basis": ("trading", "calendar"),
    "exchange": (".NS", ".BO"),
    "fy_labels": ("range", "int"),
    "reasons": ("code", "detailed", "off"),
}
INTS = {"min_complete_fy": (1, 30), "min_benchmark_fy": (0, 30), "bench_offset_days": (1, 45),
        "dpi": (72, 600), "start_year": (2000, 2100), "end_year": (2000, 2100)}
BOOLS = ("ml_enabled", "auto_relax", "keep_in_peers", "keep_in_ml", "require_price", "audit_all", "analyze", "overrides")


def clean(p):
    """Validate a preferences dict; unknown or bad values fall back to defaults."""
    d = defaults()
    out = dict(d)
    for k, v in (p or {}).items():
        if k in CHOICES and v in CHOICES[k]:
            out[k] = v
        elif k in INTS:
            try:
                lo, hi = INTS[k]
                out[k] = max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                pass
        elif k in BOOLS:
            out[k] = bool(v)
        elif k == "models" and isinstance(v, dict):
            out["models"] = {m: bool(v.get(m, d["models"][m])) for m in d["models"]}
    if not any(out["models"].values()):
        raise ValueError("at least one valuation model must stay switched on")
    if out["start_year"] > out["end_year"]:
        out["start_year"], out["end_year"] = out["end_year"], out["start_year"]
    return out


def load():
    try:
        return clean(json.loads(PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return defaults()


def save(p):
    c = clean(p)
    PATH.write_text(json.dumps(c, indent=2), encoding="utf-8")
    return c


def to_args(p):
    """Preferences -> run.py flags for a valuation run."""
    a = ["--start-year", str(p["start_year"]), "--end-year", str(p["end_year"])]
    on = [k for k, v in p["models"].items() if v]
    if len(on) != len(p["models"]):
        a += ["--models", ",".join(on)]
    if not p["ml_enabled"]:
        a.append("--no-ml")
    a += ["--ml-split", p["ml_split"], "--estimation", p["estimation"], "--screening", p["screening"]]
    a += ["--min-complete-fy", str(p["min_complete_fy"]), "--min-benchmark-fy", str(p["min_benchmark_fy"])]
    if not p["auto_relax"]:
        a.append("--no-auto-relax")
    if not p["keep_in_peers"]:
        a.append("--drop-from-peers")
    if not p["keep_in_ml"]:
        a.append("--drop-from-ml")
    if not p["require_price"]:
        a.append("--no-require-price")
    if p["audit_all"]:
        a.append("--audit-all")
    a += ["--benchmark-basis", p["benchmark_basis"], "--bench-offset-days", str(p["bench_offset_days"])]
    a += ["--mean-basis", p["mean_basis"], "--exchange", p["exchange"]]
    if not p["analyze"]:
        a.append("--no-analyze")
    a += ["--dpi", str(p["dpi"]), "--fy-labels", p["fy_labels"], "--reasons", p["reasons"]]
    if not p["overrides"]:
        a.append("--no-overrides")
    return a
