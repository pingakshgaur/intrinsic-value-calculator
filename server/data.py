# FILE: server/data.py
"""
Readers for everything the calculator and the agents write to disk.

Every reader returns plain JSON-safe values: NaN / inf become None, numbers
stay numbers, and a missing file returns an empty result rather than an
error, because "you have not run this yet" is a normal state for the UI.
"""

import csv
import json
import math
import re
import os
import sqlite3
from pathlib import Path

ROOT = Path(os.environ.get("INTVAL_HOME") or Path(__file__).resolve().parent.parent)  # see config.PROJECT_ROOT
OUTPUT = ROOT / "output"
DATA = ROOT / "data"
COMPANIES_CSV = DATA / "companies.csv"


def clean(v):
    """Recursively make a value JSON-safe (no NaN / inf)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


_NUM = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def _cell(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    if _NUM.match(s):
        f = float(s)
        return f if math.isfinite(f) else None
    return s


def read_csv(path, numeric=True):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append({(k or "").strip(): (_cell(v) if numeric else (v or "").strip()) for k, v in r.items()})
    return out


def mtime(path):
    p = Path(path)
    return p.stat().st_mtime if p.exists() else None


# ================================================================ valuation
MODEL_COL = re.compile(r"^\((.+)\) Intrinsic Value$")


def valuation():
    """The numeric twin of the main report, reshaped for charts."""
    path = OUTPUT / "Intrinsic_Value_Data.csv"
    rows = read_csv(path)
    if not rows:
        return {"available": False, "models": [], "rows": [], "updated": None}
    models = []
    for col in rows[0].keys():
        m = MODEL_COL.match(col)
        if m:
            models.append(m.group(1))
    out = []
    for r in rows:
        values = {m: r.get(f"({m}) Intrinsic Value") for m in models}
        out.append({
            "company": r.get("Company name"),
            "sector": r.get("Sector Name"),
            "fy": r.get("Financial Year"),
            "price": r.get("Market Price"),
            "values": {k: (v if isinstance(v, float) else None) for k, v in values.items()},
        })
    return clean({"available": True, "models": models, "rows": out, "updated": mtime(path)})


def ensemble():
    rows = read_csv(OUTPUT / "Ensemble_Detail.csv")
    return clean({"available": bool(rows), "rows": rows})


def hybrid_model_detail():
    rows = read_csv(OUTPUT / "Hybrid_Model_Detail.csv")
    return clean({"available": bool(rows), "rows": rows, "updated": mtime(OUTPUT / "Hybrid_Model_Detail.csv")})


def hybrid_model_bases():
    """Each company's latest HYBRID MODEL inputs from the valuation report."""
    p = OUTPUT / "hybrid_model_bases.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def metrics():
    def rd(name):
        return read_csv(OUTPUT / name)

    summary = {}
    p = OUTPUT / "analysis_summary.json"
    if p.exists():
        try:
            summary = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            summary = {}
    return clean({
        "overall": rd("metrics_overall.csv"),
        "by_year": rd("metrics_by_year.csv"),
        "by_sector": rd("metrics_by_sector.csv"),
        "by_company": rd("metrics_by_company.csv"),
        "win_rate": rd("metrics_win_rate.csv"),
        "feature_importance": rd("ml_feature_importance.csv"),
        "auto_train": rd("auto_train_log.csv"),
        "summary": summary,
        "updated": mtime(OUTPUT / "metrics_overall.csv"),
    })


def excluded():
    plain = read_csv(OUTPUT / "Why_Companies_Were_Left_Out.csv", numeric=False)
    plain = [r for r in plain if r.get("Company name") not in ("(none)", "")]
    return {"rows": plain}


def charts():
    d = OUTPUT / "charts"
    if not d.exists():
        return []
    return sorted(p.name for p in d.glob("*.png"))


# ================================================================ agents
def intel_state():
    import os

    p = os.environ.get("AGENT_STATE_DIR")
    if p:
        return Path(p)
    try:
        import yaml

        cfg = yaml.safe_load((ROOT / "agent_settings.yaml").read_text(encoding="utf-8")) or {}
        sd = (cfg.get("run") or {}).get("state_dir") or "output/intel"
    except Exception:
        sd = "output/intel"
    p = Path(sd)
    return p if p.is_absolute() else ROOT / p


def intel_latest():
    """The latest verdict on every company the agents have researched, in any run.

    The latest run's report (latest/verdicts.json) comes first; a company that
    run did not cover keeps its verdict from the run that last did, so researching
    one watchlist never hides what was found on another. Each verdict says which
    run it is from (run_id) and when (researched)."""
    p = intel_state() / "latest" / "verdicts.json"
    d, err = {"meta": None, "verdicts": []}, None
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            err = "verdicts.json is unreadable"
    meta = d.get("meta") or {}
    latest = meta.get("run_id")
    out = []
    for v in d.get("verdicts") or []:
        out.append({**v, "run_id": latest, "researched": meta.get("started")})
    seen = {v.get("company") for v in out}
    con = _db()
    if con is not None:
        try:
            rows = con.execute(
                "SELECT payload, run_id, created FROM verdicts WHERE rowid IN "
                "(SELECT MAX(rowid) FROM verdicts GROUP BY company) ORDER BY run_id DESC, rowid DESC").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            con.close()
        for payload, run_id, created in rows:
            try:
                v = json.loads(payload)
            except ValueError:
                continue
            if v.get("company") and v["company"] not in seen:
                seen.add(v["company"])
                out.append({**v, "run_id": run_id, "researched": created})
    if not out:
        return {"available": False, "meta": None, "verdicts": [], **({"error": err} if err else {})}
    meta = {**meta, "companies_total": len(out), "runs": sorted({v["run_id"] for v in out if v.get("run_id") is not None}, reverse=True)}
    return clean({"available": True, "meta": meta, "verdicts": out})


def intel_reports():
    d = intel_state() / "reports"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.iterdir(), reverse=True):
        if p.is_dir() and (p / "verdicts.json").exists():
            out.append({"name": p.name, "mode": p.name.rsplit("_", 1)[-1], "updated": mtime(p / "verdicts.json")})
    return out


def intel_report(name):
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", name or ""):
        return None
    p = intel_state() / "reports" / name / "verdicts.json"
    if not p.exists():
        return None
    return clean(json.loads(p.read_text(encoding="utf-8")))


def _db():
    p = intel_state() / "blackboard.sqlite"
    if not p.exists():
        return None
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=5)
    return con


def intel_history(company):
    con = _db()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT v.run_id, v.created, v.label, v.expected_value, v.price, v.confidence, r.mode "
            "FROM verdicts v LEFT JOIN runs r ON r.id = v.run_id WHERE v.company=? ORDER BY v.run_id",
            (company,),
        ).fetchall()
    finally:
        con.close()
    return clean([
        {"run": r[0], "date": r[1], "label": r[2], "value": r[3], "price": r[4], "confidence": r[5], "mode": r[6]}
        for r in rows
    ])


def intel_runs():
    con = _db()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, started, finished, mode, companies, llm_calls, note FROM runs ORDER BY id DESC LIMIT 200"
        ).fetchall()
    finally:
        con.close()
    return [
        {"id": r[0], "started": r[1], "finished": r[2], "mode": r[3], "companies": r[4], "llm_calls": r[5], "note": r[6]}
        for r in rows
    ]


# ================================================================ companies
HEADER = ["company name", "sector name", "market cap", "ticker"]


def companies():
    if not COMPANIES_CSV.exists():
        return []
    with open(COMPANIES_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    start = 1 if rows[0] and rows[0][0].strip().lower() in ("company name", "company", "name") else 0
    out = []
    for r in rows[start:]:
        if not any((c or "").strip() for c in r):
            continue
        r = (r + ["", "", "", ""])[:4]
        out.append({"name": r[0].strip(), "sector": r[1].strip(), "cap": r[2].strip(), "ticker": r[3].strip()})
    return out


def save_companies(rows):
    clean_rows = []
    seen = set()
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            raise ValueError(f"'{name}' is listed twice")
        seen.add(key)
        ticker = (r.get("ticker") or "").strip().upper()
        if ticker and not re.fullmatch(r"[A-Z0-9&\-_.]{1,30}", ticker):
            raise ValueError(f"ticker '{ticker}' for {name} has unexpected characters")
        cap = (r.get("cap") or "").strip()
        clean_rows.append([name, (r.get("sector") or "").strip(), cap, ticker])
    if not clean_rows:
        raise ValueError("the list must contain at least one company")
    if COMPANIES_CSV.exists():
        COMPANIES_CSV.with_suffix(".csv.bak").write_bytes(COMPANIES_CSV.read_bytes())
    with open(COMPANIES_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(clean_rows)
    return len(clean_rows)
