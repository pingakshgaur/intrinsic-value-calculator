# FILE: src/models/model_hybrid_model.py
"""
HYBRID MODEL inside the valuation report.

Runs after the Ensemble, over every company-year, from the accounts alone and
point-in-time: the signals come from years up to the one being valued, and
the price it is labelled against is that year's in-FY anchor price, never the
1-May benchmark it is scored against. The formula itself is src/hybrid_formula.py.

Writes Hybrid_Model_Detail.csv (every lens, weight, gate and band per row) and
hybrid_model_bases.json (each company's latest inputs, which the web app's
Hybrid Model Lab uses for companies the research agents have not covered).
"""

import csv
import json
import logging
import statistics

import config
import hybrid_formula as HM
from fy_utils import fy_label
from result import R, Result

log = logging.getLogger(__name__)

KEY = "hybrid_model"
NAME = "HYBRID MODEL"
DETAIL_FILE = "Hybrid_Model_Detail.csv"
BASES_FILE = "hybrid_model_bases.json"


def compute(rec, fy, comps, regime, params=None, calibration=None):
    """-> (Result, evaluation dict or None, base, signals)."""
    base = HM.base_from_record(rec, fy, comps, price=None, regime=regime)
    base["lens_calibration"] = calibration or {}
    p = params if isinstance(params, HM.Params) else HM.Params(params)
    k_hint = HM.cost_of_equity(base, HM.NEUTRAL, p)[0]
    sig = HM.signals_from_accounts(rec["data"]["years"], fy, k_hint)
    res = HM.evaluate(base, sig, p)
    if res["value"] is None:
        why = "no lens could value this company-year"
        if not base.get("shares"):
            why = "share count unavailable"
        return Result.bad(R.NOT_COMPUTABLE, why), res, base, sig
    est = sum(res["lens_weights"].get(l, 0) for l in ("market", "conservative", "learning")
              if l in res["lens_weights"] and base.get("estimated_components"))
    method = f"{est:.0%} of lens weight rests on estimated inputs" if est > 0 else None
    return Result.good(res["value"], method=method), res, base, sig


def _history(rows, universe):
    """Pass 1: every lens's signed log miss against the 1-May benchmark."""
    import math

    hist = []
    for row in rows:
        rec = universe.get(row["company"])
        bench = row.get("price")
        if rec is None or "_comps" not in row or bench is None or not getattr(bench, "ok", False) or bench.value <= 0:
            continue
        try:
            _, res, _, _ = compute(rec, row["fy"], row["_comps"], row.get("_regime"))
        except Exception:
            log.exception("HYBRID MODEL history pass failed %s FY%s", row["company"], row["fy"])
            continue
        for lens, v in (res.get("lenses") or {}).items():
            if isinstance(v, (int, float)) and v > 0:
                hist.append((rec["sector"], row["fy"], lens, math.log(v / bench.value)))
    return hist


def calibration_for(rows, universe, name, fy):
    """Lens calibration for one company-year, from the other rows' history."""
    rec = universe.get(name)
    if rec is None:
        return {}
    return HM.lens_calibration(_history(rows, universe), rec["sector"], fy)


def attach(rows, universe, failures, write=True):
    detail, bases = [], {}
    calibrate = bool(HM.Params().get("calibration.enabled", True))
    hist = _history(rows, universe) if calibrate else []
    for row in rows:
        name, fy = row["company"], row["fy"]
        if name in failures:
            row[KEY] = failures[name]
            continue
        rec = universe.get(name)
        if rec is None or "_comps" not in row:
            row[KEY] = Result.bad(R.NOT_COMPUTABLE, "company was not in the universe")
            continue
        try:
            cal = HM.lens_calibration(hist, rec["sector"], fy) if calibrate else {}
            row["_hm_calibration"] = cal
            result, res, base, sig = compute(rec, fy, row["_comps"], row.get("_regime"), calibration=cal)
        except Exception as e:
            log.exception("HYBRID MODEL failed %s FY%s", name, fy)
            row[KEY] = Result.bad(R.CALC_ERROR, f"{type(e).__name__}: {e}")
            continue
        row[KEY] = result
        bench = row.get("price")
        detail.append(_detail_row(name, rec, fy, res, bench))
        prev = bases.get(name)
        if result.ok and (prev is None or fy >= prev["base"]["fy"]):
            bases[name] = {"base": base, "signals": sig, "ticker": rec.get("ticker", "")}

    if write:
        _write(detail, bases)
        _print_summary(detail)
    return detail


def _detail_row(name, rec, fy, res, bench):
    r = lambda v, n=2: round(v, n) if isinstance(v, (int, float)) else ""  # noqa: E731
    out = {
        "Company name": name,
        "Sector Name": rec["sector"],
        "Financial Year": fy_label(fy),
        "Regime": res.get("regime") or "",
        "Market Price": r(bench.value) if bench is not None and getattr(bench, "ok", False) else "",
        "HYBRID MODEL Value": r(res["value"]),
        "Low (P10)": r(res["low"]),
        "High (P90)": r(res["high"]),
        "Confidence": r(res["confidence"], 1),
        "Cost of equity": r(res["cost_of_equity"], 4),
        "Growth": r(res["growth"], 4),
        "Terminal growth": r(res["growth_terminal"], 4),
        "Quality multiplier": r(res["quality_multiplier"], 3),
        "Growth gate applied": "yes" if res["gate"] and res["gate"]["after"] < res["gate"]["before"] else "",
    }
    for lens in HM.LENSES:
        out[f"{lens} value"] = r(res["lenses"].get(lens))
        out[f"{lens} weight"] = r(res["lens_weights"].get(lens, 0.0), 3)
        out[f"{lens} calibration"] = r(res["lens_calibration"].get(lens), 3)
    return out


def _write(detail, bases):
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if detail:
        with open(config.OUTPUT_DIR / DETAIL_FILE, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
            w.writeheader()
            w.writerows(detail)
    try:
        (config.OUTPUT_DIR / BASES_FILE).write_text(json.dumps(bases, default=str), encoding="utf-8")
    except OSError:
        log.exception("could not write %s", BASES_FILE)


def _print_summary(detail):
    valued = [d for d in detail if d["HYBRID MODEL Value"] != ""]
    print(f"\n[hybrid model] valued {len(valued)}/{len(detail)} company-years")
    scored = [d for d in valued if d["Market Price"] != ""]
    if scored:
        errs = [abs(d["HYBRID MODEL Value"] / d["Market Price"] - 1) for d in scored if d["Market Price"]]
        hit = sum(1 for e in errs if e <= 0.20) / len(errs)
        print(
            f"[hybrid model] median |error| vs 1-May price {statistics.median(errs):.0%}; "
            f"within 20%: {hit:.0%} ({len(errs)} scored rows); "
            f"average confidence {statistics.mean(d['Confidence'] for d in valued):.0f}"
        )
    print(f"[hybrid model] lenses, weights and bands -> {config.OUTPUT_DIR / DETAIL_FILE}")
