"""
The Hybrid Model Lab's backend: live what-if evaluations of the HYBRID MODEL.

Each company's inputs come from the latest research run (with the agents'
signals) when there is one, otherwise from the valuation report's latest
year (signals from the accounts). Overrides apply to one evaluation only;
nothing is written until /api/hybrid/save.
"""

import hybrid_model as HM
from agents import settings as S

from server import data as D


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


def params(overrides=None):
    S.load()
    return D.clean(HM.schema_with_values(overrides))
