# FILE: server/hybrid_api.py
"""
The Hybrid Model Lab's backend: live what-if evaluations of the HYBRID MODEL.

Each company's inputs come from the latest research run (with the agents'
signals) when there is one, otherwise from the valuation report's latest
year (signals from the accounts). Overrides apply to one evaluation only;
nothing is written until /api/hybrid/save.
"""

import math

import hybrid_formula as HM
from agents import settings as S
from server import data as D


def _calibration_from_verdict(v, base, sig):
    """Research runs before the fix in agents/runner.py saved their inputs
    without the lens calibration. The verdict still records each lens's
    multiplier (exp(-c)) and its final weight, which is enough to rebuild it:
    c from the multiplier, and each lens's skill as the ratio of its final
    weight to the weight it gets with no skill weighting. Exact unless a lens
    was dropped as an outlier: it has no final weight to recover a skill from,
    and may still count in the bull or bear case (the value then lands within
    a few per cent; the label is unchanged in every company tested)."""
    mult = v.get("lens_calibration") or {}
    final = v.get("lens_weights") or {}
    cal = {l: {"c": -math.log(m)} for l, m in mult.items() if isinstance(m, (int, float)) and m > 0}
    if not cal:
        return {}
    for l in final:  # every weighted lens, so all skills share one scale
        cal.setdefault(l, {"c": 0.0})
    plain = HM.evaluate({**base, "lens_calibration": cal}, sig).get("lens_weights") or {}
    for l, entry in cal.items():
        if plain.get(l) and final.get(l):
            entry["skill"] = final[l] / plain[l]
    return cal


def _from_verdict(v):
    base = dict(v.get("base") or {})
    if not base.get("shares"):
        return None
    sig = v.get("signals")
    if not sig:
        # research runs from before the HYBRID MODEL kept no merged signals
        sig = {
            "risks": v.get("risks") or {}, "tilts": v.get("tilts") or {}, "quality": v.get("quality") or {},
            "red_flags": v.get("red_flags") or [], "conf_parts": {
                k: x for k, x in (v.get("confidence_parts") or {}).items() if k != "hybrid"},
            "overlay": v.get("overlay", 0.0),
        }
    if "lens_calibration" not in base:
        base["lens_calibration"] = _calibration_from_verdict(v, base, sig)
    return {"base": base, "signals": sig}


def sources():
    """-> {company: {"base", "signals", "source", "sector", "ticker"}}"""
    out = {}
    for name, b in D.hybrid_model_bases().items():
        if b.get("base"):
            out[name] = {**b, "source": "report", "sector": b["base"].get("sector", "")}
    for v in D.intel_latest().get("verdicts") or []:
        got = _from_verdict(v)
        if got:
            out[v["company"]] = {**got, "source": "research", "sector": v.get("sector", ""), "ticker": v.get("ticker", "")}
    return out


def companies():
    S.load()
    rows = []
    for name, s in sorted(sources().items()):
        res = HM.evaluate(s["base"], s["signals"])
        rows.append({
            "company": name, "sector": s.get("sector", ""), "ticker": s.get("ticker", ""),
            "source": s["source"], "price": res["price"], "value": res["value"],
            "label": res["label"], "confidence": res["confidence"], "regime": res["regime"],
            "fy": s["base"].get("fy"),
        })
    return rows


def simulate(company, overrides, with_sensitivity=True):
    S.load()
    src = sources().get(company)
    if src is None:
        raise KeyError(f"no HYBRID MODEL inputs for '{company}' - run the valuation report or the research first")
    base, sig = src["base"], src["signals"]
    saved = HM.evaluate(base, sig)
    live = HM.evaluate(base, sig, overrides or {})
    out = {"company": company, "source": src["source"], "fy": base.get("fy"),
           "saved": saved, "live": live, "inputs": {k: v for k, v in base.items()
                                                    if isinstance(v, (int, float, str)) or v is None}}
    if with_sensitivity:
        out["sensitivity"] = HM.sensitivity(base, sig, overrides or {})
    return D.clean(out)


def simulate_all(overrides):
    """Every company, saved vs. with the overrides - the portfolio view."""
    S.load()
    rows = []
    for name, s in sorted(sources().items()):
        a = HM.evaluate(s["base"], s["signals"])
        b = HM.evaluate(s["base"], s["signals"], overrides or {})
        rows.append({"company": name, "sector": s.get("sector", ""), "price": a["price"],
                     "saved": a["value"], "live": b["value"], "saved_label": a["label"], "live_label": b["label"],
                     "confidence": b["confidence"]})
    return D.clean(rows)


FACTORY = D.ROOT / "agent_settings.defaults.yaml"


def factory():
    """{path: value} for every Studio constant as shipped (agent_settings.defaults.yaml).
    Only constants written in that file - the Studio can reset nothing else."""
    import yaml

    try:
        hm = (yaml.safe_load(FACTORY.read_text(encoding="utf-8")) or {}).get("hybrid_model") or {}
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for g in HM.PARAM_SCHEMA:
        for path, *_ in g["params"]:
            node = hm
            for part in path.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            if isinstance(node, (int, float, bool)):
                out[path] = node
    return out


def params(overrides=None):
    S.load()
    rows = HM.schema_with_values(overrides)
    fac = factory()
    for g in rows:
        for r in g["params"]:
            r["default"] = fac.get(r["path"])
    return D.clean(rows)
