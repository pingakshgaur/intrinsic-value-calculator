"""
FastAPI app: JSON under /api, the built React app everywhere else.
"""

import os
import platform
import re
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

import server  # noqa: F401  (puts src/ on sys.path)
from server import data as D
from server import hybrid_api, llm_api, prefs, yaml_patch
from server.jobs import JobManager

SETTINGS = D.ROOT / "agent_settings.yaml"
ENV_FILE = D.ROOT / ".env"
DIST = D.ROOT / "web" / "dist"
KEY_NAMES = ["GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]

app = FastAPI(title="Intrinsic Value Calculator", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
jobs = JobManager()


@app.exception_handler(Exception)
async def _unhandled(request, exc):
    # the UI shows this text; never let a reader bug become a blank page
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# ================================================================ status
def _env_file_keys():
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _key_status():
    f = _env_file_keys()
    return {k: bool(os.environ.get(k) or f.get(k)) for k in KEY_NAMES}


@app.get("/api/status")
def status():
    v = D.mtime(D.OUTPUT / "Intrinsic_Value_Data.csv")
    latest = D.intel_state() / "latest" / "verdicts.json"
    act = jobs.active()
    return {
        "project": D.ROOT.name,
        "python": platform.python_version(),
        "valuation_updated": v,
        "intel_updated": D.mtime(latest),
        "companies": len(D.companies()),
        "keys": _key_status(),
        "active_job": act.summary() if act else None,
        "server_time": time.time(),
    }


# ================================================================ results
@app.get("/api/valuation")
def valuation():
    return D.valuation()


@app.get("/api/valuation/ensemble")
def ensemble():
    return D.ensemble()


@app.get("/api/valuation/hybrid-model")
def hybrid_model_detail():
    return D.hybrid_model_detail()


@app.get("/api/valuation/metrics")
def metrics():
    return D.metrics()


@app.get("/api/valuation/excluded")
def excluded():
    return D.excluded()


@app.get("/api/charts")
def charts():
    return D.charts()


@app.get("/api/charts/{name}")
def chart(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.png", name):
        raise HTTPException(404)
    p = D.OUTPUT / "charts" / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


DOWNLOADS = {
    "report_xlsx": "Intrinsic_Value_Report.xlsx",
    "report_csv": "Intrinsic_Value_Report.csv",
    "data_csv": "Intrinsic_Value_Data.csv",
    "hybrid_model_csv": "Hybrid_Model_Detail.csv",
    "ensemble_csv": "Ensemble_Detail.csv",
    "excluded_csv": "Why_Companies_Were_Left_Out.csv",
    "methods_csv": "Intrinsic_Value_Methods.csv",
    "diagnostics_csv": "Intrinsic_Value_Diagnostics.csv",
    "analysis_html": "analysis_report.html",
    "run_log": "run_log.txt",
}


@app.get("/api/downloads")
def downloads():
    return [
        {"key": k, "file": f, "updated": D.mtime(D.OUTPUT / f), "size": (D.OUTPUT / f).stat().st_size}
        for k, f in DOWNLOADS.items()
        if (D.OUTPUT / f).exists()
    ]


@app.get("/api/downloads/{key}")
def download(key: str):
    f = DOWNLOADS.get(key)
    if not f or not (D.OUTPUT / f).exists():
        raise HTTPException(404)
    return FileResponse(D.OUTPUT / f, filename=f)


@app.get("/api/intel/latest")
def intel_latest():
    return D.intel_latest()


@app.get("/api/intel/reports")
def intel_reports():
    return D.intel_reports()


@app.get("/api/intel/reports/{name}")
def intel_report(name: str):
    r = D.intel_report(name)
    if r is None:
        raise HTTPException(404, "report not found")
    return r


@app.get("/api/intel/history")
def intel_history(company: str):
    return D.intel_history(company)


@app.get("/api/intel/runs")
def intel_runs():
    return D.intel_runs()


@app.get("/api/intel/latest/dashboard")
def intel_dashboard():
    p = D.intel_state() / "latest" / "dashboard.html"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/html")


# ================================================================ companies
class Company(BaseModel):
    name: str
    sector: str = ""
    cap: str = ""
    ticker: str = ""


@app.get("/api/companies")
def companies():
    return D.companies()


@app.put("/api/companies")
def save_companies(rows: list[Company]):
    try:
        n = D.save_companies([r.model_dump() for r in rows])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"saved": n}


# ================================================================ settings
@app.get("/api/settings/agents")
def get_settings():
    import yaml

    text = SETTINGS.read_text(encoding="utf-8") if SETTINGS.exists() else ""
    try:
        parsed = yaml.safe_load(text) or {}
        err = None
    except yaml.YAMLError as e:
        parsed, err = {}, str(e)
    return {"text": text, "data": D.clean(parsed), "error": err, "updated": D.mtime(SETTINGS)}


class SettingsText(BaseModel):
    text: str


def _write_settings(text):
    import yaml

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"not valid YAML: {e}")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "the settings file must be a mapping of sections")
    if SETTINGS.exists():
        SETTINGS.with_suffix(".yaml.bak").write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
    SETTINGS.write_text(text, encoding="utf-8")
    return parsed


@app.put("/api/settings/agents")
def put_settings(body: SettingsText):
    _write_settings(body.text)
    return get_settings()


class SettingsPatch(BaseModel):
    values: dict[str, float | int | bool | str]


@app.patch("/api/settings/agents")
def patch_settings(body: SettingsPatch):
    text = SETTINGS.read_text(encoding="utf-8")
    for path, value in body.values.items():
        try:
            text = yaml_patch.set_value(text, path, value)
        except KeyError as e:
            raise HTTPException(400, str(e).strip("'\""))
    _write_settings(text)
    return get_settings()


@app.get("/api/settings/keys")
def get_keys():
    return _key_status()


class Keys(BaseModel):
    values: dict[str, str]


@app.put("/api/settings/keys")
def put_keys(body: Keys):
    """Write API keys to the local .env. Values are never sent back."""
    cur = _env_file_keys()
    for k, v in body.values.items():
        if k not in KEY_NAMES:
            raise HTTPException(400, f"unknown key {k}")
        v = (v or "").strip()
        if any(c in v for c in "\r\n\"'"):
            raise HTTPException(400, f"{k} contains characters a key cannot have")
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    lines = ["# Written by the web UI. Never commit this file.", *(f"{k}={cur[k]}" for k in KEY_NAMES if cur.get(k))]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _key_status()


# ================================================================ jobs
class JobRequest(BaseModel):
    kind: str
    options: dict = {}


@app.post("/api/jobs")
def start_job(req: JobRequest):
    try:
        job = jobs.start(req.kind, req.options)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return job.summary()


@app.get("/api/jobs")
def list_jobs():
    return jobs.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, since: int = 0):
    j = jobs.get(job_id, since)
    if j is None:
        raise HTTPException(404, "job not found")
    return j


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return {"cancelled": jobs.cancel(job_id)}


class Control(BaseModel):
    action: str
    value: float | None = None


@app.post("/api/jobs/{job_id}/control")
def control_job(job_id: str, body: Control):
    try:
        return {"sent": jobs.control(job_id, body.action, body.value)}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ================================================================ run preferences
@app.get("/api/run-preferences")
def get_prefs():
    import config

    return {"values": prefs.load(), "defaults": prefs.defaults(), "latest_fy": config.latest_complete_fy(),
            "min_fy": getattr(config, "FY_MIN_ALLOWED", 2000)}


@app.put("/api/run-preferences")
def put_prefs(body: dict):
    try:
        return {"values": prefs.save(body)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/run-preferences")
def reset_prefs():
    if prefs.PATH.exists():
        prefs.PATH.unlink()
    return {"values": prefs.load()}


@app.get("/api/models")
def models():
    import model_registry

    return [{"key": m.key, "name": m.name, "kind": m.kind, "blurb": m.blurb} for m in model_registry.ALL_MODELS]


# ================================================================ AI providers
@app.get("/api/llm/providers")
def llm_providers():
    return llm_api.providers(ENV_FILE)


@app.get("/api/llm/models")
def llm_models(provider: str, refresh: bool = False):
    try:
        return llm_api.list_models(provider, ENV_FILE, refresh)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))
    except PermissionError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"could not list models: {e}")


class ModelTest(BaseModel):
    provider: str
    model: str


@app.post("/api/llm/test")
def llm_test(body: ModelTest):
    try:
        return llm_api.test_model(body.provider, body.model, ENV_FILE)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))
    except PermissionError as e:
        raise HTTPException(400, str(e))


class Routes(BaseModel):
    fast: list[str] | None = None
    smart: list[str] | None = None


@app.put("/api/llm/routes")
def llm_routes(body: Routes):
    text = SETTINGS.read_text(encoding="utf-8")
    try:
        text = llm_api.set_routes(text, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _write_settings(text)
    return llm_api.providers(ENV_FILE)


# ================================================================ HYBRID MODEL Lab
@app.get("/api/hybrid/companies")
def hybrid_companies():
    return hybrid_api.companies()


class Simulate(BaseModel):
    company: str
    overrides: dict[str, float | int | bool] = {}
    sensitivity: bool = True


@app.post("/api/hybrid/params")
def hybrid_params(body: dict | None = None):
    return hybrid_api.params((body or {}).get("overrides"))


@app.post("/api/hybrid/simulate")
def hybrid_simulate(body: Simulate):
    try:
        return hybrid_api.simulate(body.company, body.overrides, body.sensitivity)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


class Overrides(BaseModel):
    overrides: dict[str, float | int | bool] = {}


@app.post("/api/hybrid/simulate-all")
def hybrid_simulate_all(body: Overrides):
    return hybrid_api.simulate_all(body.overrides)


@app.post("/api/hybrid/save")
def hybrid_save(body: Overrides):
    """Write the Lab's overrides into agent_settings.yaml -> hybrid_model."""
    text = SETTINGS.read_text(encoding="utf-8")
    for path, value in body.overrides.items():
        try:
            text = yaml_patch.set_value(text, "hybrid_model." + path, value)
        except KeyError as e:
            raise HTTPException(400, f"cannot save {path}: {str(e).strip(chr(39))}")
    _write_settings(text)
    return {"saved": len(body.overrides), "params": hybrid_api.params()}


_market = {"at": 0.0, "data": None}


@app.get("/api/market")
def market():
    """Market tape: Nifty, VIX, USD/INR, Brent, US 10Y, gold. Cached 10 min;
    an empty list (never an error) when the network or Yahoo is down."""
    if _market["data"] is not None and time.time() - _market["at"] < 600:
        return _market["data"]
    rows = []
    try:
        from agents import settings as S
        from agents.feeds import Feeds

        S.load()
        for name, s in Feeds().macro().items():
            rows.append({"name": name, "ticker": s["ticker"], "last": s["last"], "date": s["date"],
                         "chg_1m": s["chg_1m"], "chg_1y": s["chg_1y"]})
    except Exception:
        rows = []
    _market.update(at=time.time(), data=D.clean(rows))
    return _market["data"]


@app.get("/api/health")
def health():
    return {"ok": True}


# ================================================================ the SPA
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    if not DIST.exists():
        return PlainTextResponse(
            "The web UI is not built yet. Run:\n\n  cd web\n  npm install\n  npm run build\n\n"
            "then restart 'python run.py --web'.",
            status_code=503,
        )
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(DIST / "index.html")


def serve(port=8765, open_browser=True):
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"[web] Intrinsic Value Calculator UI on {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    serve(int(os.environ.get("PORT", "8765")), open_browser=False)
