# FILE: src/sufficiency.py
"""
Data-sufficiency gate.

Placement is the whole design. This runs AFTER build_universe() and BEFORE
estimation.fill_universe(). The estimation ladder (back-cast -> own CAGR ->
sector-median ratio) can produce a plausible number for nearly any gap, so a
sufficiency test placed downstream of it would never fail anyone. Every field
this module inspects was either reported by the source or hand-entered in
data/fundamentals_override.csv. Nothing here has been inferred.

Definitions
-----------
A financial year is COMPLETE when every field in
config.SUFFICIENCY_REQUIRED_FIELDS carries a value (plus the in-FY anchor
price, if SUFFICIENCY_REQUIRE_ANCHOR_PRICE is set).

A company is SUFFICIENT when it has at least config.MIN_COMPLETE_FY complete
years AND at least config.MIN_BENCHMARK_FY years carrying a benchmark price.
The second test matters independently: a company with immaculate accounts but
no post-FY traded price cannot be scored against anything, so it contributes
nothing to a comparative accuracy study.

An insufficient company is dropped from the report grid. Under the default
policy it stays inside the peer-median tables and the ML training frame - its
data is thin, not wrong, and removing it would shrink the sector medians that
every surviving company depends on. Flip SUFFICIENCY_KEEP_IN_PEERS or
SUFFICIENCY_KEEP_IN_ML to change that.
"""

import logging

import config
from fy_utils import fy_label

log = logging.getLogger("valuation")

# What each traditional model minimally needs in a given year. Reported for the
# excluded sheet so a near-miss reads as "P/E would have run in 5 years, DCF in
# 2" rather than a bare verdict.
MODEL_REQUIREMENTS = {
    "DCF": ("ocf", "capex", "shares", "total_debt", "cash"),
    "P/E Relative": ("eps", "shares"),
    "EV/EBITDA": ("ebitda", "shares", "total_debt", "cash"),
}


def required_fields():
    fields = list(getattr(config, "SUFFICIENCY_REQUIRED_FIELDS", ()))
    if getattr(config, "SUFFICIENCY_REQUIRE_ANCHOR_PRICE", True):
        if "price" not in fields:
            fields.append("price")
    return fields


def _override_fields(year_data):
    """Field names overrides.apply() reported as manually supplied."""
    out = []
    for note in year_data.get("_notes", []) or []:
        if "manually supplied" in note and ":" in note:
            tail = note.split(":", 1)[1]
            out.extend(part.strip() for part in tail.split(","))
    return [f for f in out if f]


def assess(name, meta, rec, failure=None):
    """One company -> one verdict record."""
    fy_list = sorted(config.FY_LIST)
    fields = required_fields()

    record = {
        "company": name,
        "sector": meta.get("sector", "") if meta else "",
        "cap": meta.get("cap", "") if meta else "",
        "ticker": "",
        "complete_fy": 0,
        "benchmark_fy": 0,
        "need_complete": int(getattr(config, "MIN_COMPLETE_FY", 4)),
        "need_benchmark": int(
            getattr(config, "MIN_BENCHMARK_FY", getattr(config, "MIN_COMPLETE_FY", 4))
        ),
        "total_fy": len(fy_list),
        "missing_by_fy": {},
        "overrides": [],
        "model_ready": {k: 0 for k in MODEL_REQUIREMENTS},
        "reasons": [],
        "passes": False,
    }

    # The company never got off the ground - no ticker, or the download raised.
    if rec is None:
        detail = failure.full() if failure is not None else "no data was assembled"
        record["ticker"] = (meta or {}).get("ticker") or ""
        record["reasons"].append(f"nothing was fetched - {detail}")
        record["missing_by_fy"] = {fy: ["everything"] for fy in fy_list}
        return record

    record["ticker"] = rec.get("ticker") or ""
    years = rec["data"]["years"]

    for fy in fy_list:
        d = years.get(fy) or {}

        missing = [f for f in fields if d.get(f) is None]
        if missing:
            record["missing_by_fy"][fy] = missing
        else:
            record["complete_fy"] += 1

        if d.get("price_bench") is not None:
            record["benchmark_fy"] += 1

        for model, needed in MODEL_REQUIREMENTS.items():
            if all(d.get(f) is not None for f in needed):
                record["model_ready"][model] += 1

        record["overrides"].extend(_override_fields(d))

    record["overrides"] = sorted(set(record["overrides"]))

    if record["complete_fy"] < record["need_complete"]:
        record["reasons"].append(
            f"only {record['complete_fy']} of {record['total_fy']} financial "
            f"years carry a complete set of required fundamentals "
            f"(need {record['need_complete']})"
        )
    if record["benchmark_fy"] < record["need_benchmark"]:
        record["reasons"].append(
            f"only {record['benchmark_fy']} of {record['total_fy']} financial "
            f"years carry a benchmark market price to be scored against "
            f"(need {record['need_benchmark']})"
        )

    record["passes"] = not record["reasons"]
    return record


def screen(companies, universe, failures):
    """
    -> list of verdict records, one per input company, in input order.

    Order is preserved deliberately: the excluded sheet then reads in the same
    sequence as companies.csv, which makes it easy to cross-check by eye.
    """
    records = []
    for c in companies:
        name = c["name"]
        rec = universe.get(name)
        records.append(assess(name, c, rec, failures.get(name)))
    return records


def excluded_names(records):
    """Names to drop from the report grid. Empty unless the gate is enforcing."""
    if not getattr(config, "SUFFICIENCY_ENABLED", True):
        return set()
    if getattr(config, "SUFFICIENCY_MODE", "enforce") != "enforce":
        return set()
    return {r["company"] for r in records if not r["passes"]}


def missing_text(record, limit=None):
    """'2021-22: eps, ocf | 2022-23: capex' - for the sheet's audit column."""
    parts = []
    for fy in sorted(record["missing_by_fy"]):
        fields = record["missing_by_fy"][fy]
        shown = fields if limit is None else fields[:limit]
        tail = "" if limit is None or len(fields) <= limit else ", ..."
        parts.append(f"{fy_label(fy)}: {', '.join(shown)}{tail}")
    return " | ".join(parts)


def model_ready_text(record):
    total = record["total_fy"]
    return "; ".join(
        f"{model} {record['model_ready'][model]}/{total}"
        for model in MODEL_REQUIREMENTS
    )


def reason_text(record):
    return " | ".join(record["reasons"])


def print_summary(records):
    """Console report. Mirrors what lands in the Excluded Companies sheet."""
    if not getattr(config, "SUFFICIENCY_ENABLED", True):
        print("\n[gate] data-sufficiency check DISABLED - every company retained")
        return

    mode = getattr(config, "SUFFICIENCY_MODE", "enforce")
    need = int(getattr(config, "MIN_COMPLETE_FY", 4))
    need_b = int(getattr(config, "MIN_BENCHMARK_FY", need))
    total = len(records)
    failing = [r for r in records if not r["passes"]]
    passing = total - len(failing)

    verb = "dropped from the report" if mode == "enforce" else "FLAGGED ONLY"
    print(
        f"\n[gate] data sufficiency: {need} of {len(config.FY_LIST)} complete "
        f"financial years required, {need_b} with a benchmark price"
    )
    print(f"[gate] checked before the estimation layer, on reported data only")
    print(f"[gate] {passing}/{total} companies pass; {len(failing)} {verb}")

    if failing:
        print("\n[gate] insufficient data:")
        for r in failing:
            print(
                f"   {r['company'][:38]:38s} "
                f"complete {r['complete_fy']}/{r['total_fy']}  "
                f"bench {r['benchmark_fy']}/{r['total_fy']}"
            )
            print(f"      {reason_text(r)}")
            if r["missing_by_fy"]:
                print(f"      missing: {missing_text(r, limit=6)}")

    if mode == "enforce" and passing == 0:
        print(
            "\n[gate] NOTHING SURVIVED. Before loosening anything, check whether "
            "MIN_COMPLETE_FY exceeds what the source can supply: yfinance "
            "publishes roughly four annual periods, so FY2021 is usually "
            "absent and 4 is the observable ceiling, not a middling bar."
        )
    elif mode == "enforce" and passing < 10:
        print(
            f"\n[gate] only {passing} companies survived. A sample this small "
            f"weakens the sector medians and every cross-sector comparison "
            f"downstream. Consider MIN_COMPLETE_FY = {max(1, need - 1)}, and "
            f"say so explicitly in the methodology."
        )
