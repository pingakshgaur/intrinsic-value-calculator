# FILE: server/ollama_api.py
"""
Ollama on this computer: the AI Providers page's local-model section.

    status      is Ollama installed, running, which models it has, free disk
    launch      start Ollama detached, so it keeps running after INTVAL stops
    pull        download a model in the background, with progress
    delete      remove a downloaded model
    settings    switch the 'ollama' provider on or off, pick its fast and smart
                models, try it before the cloud providers, start it with INTVAL

The agents reach Ollama through its OpenAI-compatible endpoint, as the
'ollama' provider in src/agents/llm_providers.py; nothing here talks to the
agents directly. Launch-on-start lives in data/live/ollama.json.
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

import requests

from agents import llm_providers as LP
from agents import settings as S
from server.live import LIVE, _read_json, _write_json

log = logging.getLogger("web.ollama")
HOST = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
NAME = "ollama"
SETTINGS = LIVE / "ollama.json"
DEFAULTS = {"autostart": True}
DOWNLOAD_URL = "https://ollama.com/download"
LIBRARY_URL = "https://ollama.com/library"

# Free, openly licensed models that follow instructions and answer in JSON well
# enough for the agents. Sizes are the default (4-bit) download; RAM is what the
# model wants free to run comfortably. Any other tag from the library can be
# typed in by name.
CATALOG = [
    {"name": "qwen2.5:0.5b", "family": "Qwen 2.5", "params": "0.5B", "size_gb": 0.4, "ram_gb": 1, "note": "Tiny and very fast; rough answers."},
    {"name": "gemma3:1b", "family": "Gemma 3", "params": "1B", "size_gb": 0.8, "ram_gb": 2, "note": "Google's smallest; good for headline sentiment."},
    {"name": "llama3.2:1b", "family": "Llama 3.2", "params": "1B", "size_gb": 1.3, "ram_gb": 2, "note": "Meta's small model; fast on any laptop."},
    {"name": "qwen2.5:1.5b", "family": "Qwen 2.5", "params": "1.5B", "size_gb": 1.0, "ram_gb": 2, "note": "Strong JSON for its size."},
    {"name": "deepseek-r1:1.5b", "family": "DeepSeek R1", "params": "1.5B", "size_gb": 1.1, "ram_gb": 2, "note": "Small reasoning model; slower, thinks first."},
    {"name": "smollm2:1.7b", "family": "SmolLM2", "params": "1.7B", "size_gb": 1.8, "ram_gb": 3, "note": "Hugging Face's compact model."},
    {"name": "llama3.2:3b", "family": "Llama 3.2", "params": "3B", "size_gb": 2.0, "ram_gb": 4, "note": "Best all-rounder under 4 GB. Recommended."},
    {"name": "qwen2.5:3b", "family": "Qwen 2.5", "params": "3B", "size_gb": 1.9, "ram_gb": 4, "note": "Good structured output."},
    {"name": "phi4-mini", "family": "Phi-4 mini", "params": "3.8B", "size_gb": 2.5, "ram_gb": 5, "note": "Microsoft; good reasoning for its size."},
    {"name": "gemma3:4b", "family": "Gemma 3", "params": "4B", "size_gb": 3.3, "ram_gb": 6, "note": "Balanced quality and speed."},
    {"name": "qwen3:4b", "family": "Qwen 3", "params": "4B", "size_gb": 2.5, "ram_gb": 5, "note": "Newer Qwen; can think before answering."},
    {"name": "mistral:7b", "family": "Mistral", "params": "7B", "size_gb": 4.1, "ram_gb": 8, "note": "Solid writer for summaries."},
    {"name": "qwen2.5:7b", "family": "Qwen 2.5", "params": "7B", "size_gb": 4.7, "ram_gb": 8, "note": "Strong analysis and JSON. Good 'smart' model."},
    {"name": "llama3.1:8b", "family": "Llama 3.1", "params": "8B", "size_gb": 4.9, "ram_gb": 8, "note": "Meta's popular mid-size model."},
    {"name": "deepseek-r1:7b", "family": "DeepSeek R1", "params": "7B", "size_gb": 4.7, "ram_gb": 8, "note": "Reasoning model for bull/bear cases."},
    {"name": "qwen3:8b", "family": "Qwen 3", "params": "8B", "size_gb": 5.2, "ram_gb": 10, "note": "Newer Qwen, stronger reasoning."},
    {"name": "gemma3:12b", "family": "Gemma 3", "params": "12B", "size_gb": 8.1, "ram_gb": 16, "note": "High quality; needs a strong machine."},
    {"name": "qwen2.5:14b", "family": "Qwen 2.5", "params": "14B", "size_gb": 9.0, "ram_gb": 16, "note": "Close to cloud quality; slow without a GPU."},
]

_pulls = {}  # model -> {status, completed, total, error, done, started}
_lock = threading.Lock()


# ------------------------------------------------------------------ settings
def settings():
    s = dict(DEFAULTS)
    s.update({k: v for k, v in _read_json(SETTINGS, {}).items() if k in DEFAULTS})
    return s


def _save_settings(patch):
    s = settings()
    if "autostart" in patch:
        s["autostart"] = bool(patch["autostart"])
    _write_json(SETTINGS, s)
    return s


# ------------------------------------------------------------------ finding and starting Ollama
def executable():
    """Path to the ollama program, or None when it is not installed."""
    found = shutil.which("ollama")
    if found:
        return found
    system = platform.system()
    if system == "Windows":
        cands = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                 Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe"]
    elif system == "Darwin":
        cands = [Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama")]
    else:
        cands = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"), Path.home() / ".local" / "bin" / "ollama"]
    return next((str(c) for c in cands if c.is_file()), None)


def version(timeout=1.5):
    """The running server's version, or None when nothing answers."""
    try:
        r = requests.get(HOST + "/api/version", timeout=timeout)
        return r.json().get("version") if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def launch(wait=12.0):
    """Start Ollama so it outlives INTVAL. -> (running, message)."""
    if version():
        return True, "Ollama is already running"
    exe = executable()
    if not exe:
        return False, "Ollama is not installed on this computer"
    system = platform.system()
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    try:
        if system == "Windows":
            # The tray app runs the server and keeps it alive. It is started by a
            # short-lived `cmd /c start`, so its parent is gone at once: closing
            # INTVAL - even killing its whole process tree - leaves Ollama running.
            tray = Path(exe).with_name("ollama app.exe")
            # start's first quoted argument is the window title, so it gets an empty one
            target = f'"{tray}"' if tray.is_file() else f'/b "{exe}" serve'
            cmd = f'cmd /d /c start "" {target}'
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **quiet)
            except OSError:  # the parent's job forbids breaking away
                subprocess.Popen(cmd, creationflags=flags, **quiet)
        elif system == "Darwin" and Path("/Applications/Ollama.app").exists():
            subprocess.Popen(["open", "-g", "-a", "Ollama"], **quiet)
        else:
            subprocess.Popen([exe, "serve"], start_new_session=True, **quiet)
    except OSError as e:
        return False, f"could not start Ollama: {e}"
    end = time.time() + wait
    while time.time() < end:
        if version(timeout=1):
            return True, "Ollama started"
        time.sleep(0.5)
    return False, "Ollama was started but is not answering yet - give it a few seconds"


def launch_on_startup():
    """Called when the web app starts: open Ollama if the user wants that."""
    if not settings()["autostart"] or not executable():
        return
    threading.Thread(target=lambda: log.info("ollama: %s", launch()[1]), daemon=True, name="ollama-launch").start()


# ------------------------------------------------------------------ models
def installed_models():
    try:
        r = requests.get(HOST + "/api/tags", timeout=4)
        r.raise_for_status()
    except requests.RequestException:
        return None
    out = []
    for m in r.json().get("models") or []:
        d = m.get("details") or {}
        out.append({"name": m.get("name") or m.get("model"), "size": m.get("size") or 0, "modified": m.get("modified_at"),
                    "family": d.get("family") or "", "params": d.get("parameter_size") or "", "quant": d.get("quantization_level") or ""})
    return sorted(out, key=lambda m: m["name"])


def models_dir():
    if os.environ.get("OLLAMA_MODELS"):
        return Path(os.environ["OLLAMA_MODELS"])
    if platform.system() == "Linux" and Path("/usr/share/ollama/.ollama/models").exists():
        return Path("/usr/share/ollama/.ollama/models")  # the Linux install script's service user
    return Path.home() / ".ollama" / "models"


def disk():
    p = models_dir()
    probe = p
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        u = shutil.disk_usage(probe)
        return {"path": str(p), "free": u.free, "total": u.total}
    except OSError:
        return {"path": str(p), "free": None, "total": None}


def _pull_worker(model):
    parts = {}  # digest -> (completed, total): Ollama reports each layer separately
    st = _pulls[model]
    try:
        with requests.post(HOST + "/api/pull", json={"model": model, "stream": True}, stream=True, timeout=(10, 600)) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Ollama answered HTTP {r.status_code}: {r.text[:200]}")
            for line in r.iter_lines():
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
                if ev.get("digest") and ev.get("total"):
                    parts[ev["digest"]] = (ev.get("completed") or 0, ev["total"])
                with _lock:
                    st["status"] = ev.get("status") or st["status"]
                    st["completed"] = sum(c for c, _ in parts.values())
                    st["total"] = sum(t for _, t in parts.values())
        with _lock:
            st.update(done=True, status="success")
    except Exception as e:  # shown on the page; the user can retry
        log.warning("ollama pull %s failed: %s", model, e)
        with _lock:
            st.update(done=True, error=str(e)[:300])


def pull(model):
    model = (model or "").strip()
    if not model or len(model) > 120 or any(c.isspace() for c in model):
        raise ValueError("give a model name such as llama3.2:3b")
    if not version():
        ok, msg = launch()
        if not ok:
            raise RuntimeError(msg)
    with _lock:
        cur = _pulls.get(model)
        if cur and not cur["done"]:
            return cur
        _pulls[model] = {"status": "starting", "completed": 0, "total": 0, "error": None, "done": False, "started": time.time()}
    threading.Thread(target=_pull_worker, args=(model,), daemon=True, name=f"ollama-pull-{model}").start()
    return _pulls[model]


def dismiss_pull(model):
    with _lock:
        if model in _pulls and _pulls[model]["done"]:
            _pulls.pop(model)


def delete(model):
    try:
        r = requests.delete(HOST + "/api/delete", json={"model": model}, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError("Ollama is not running") from e
    if r.status_code == 404:
        raise KeyError(model)
    if not r.ok:
        raise RuntimeError(f"Ollama answered HTTP {r.status_code}: {r.text[:200]}")
    _check_chosen_models()


# ------------------------------------------------------------------ the agents' 'ollama' provider
def provider():
    S.load()
    return LP.providers().get(NAME)


def _ensure_provider():
    if provider() is None:
        pre = LP.PRESETS[NAME]
        LP.save(NAME, {"label": pre["label"], "style": "openai", "auth": "none", "base_url": HOST + "/v1",
                       "rpm": pre["rpm"], "rpd": pre["rpd"], "tpm": pre["tpm"], "enabled": False})
    return provider()


def _check_chosen_models():
    """Forget a chosen model that is no longer downloaded."""
    p = provider()
    models = installed_models()
    if p and models is not None:
        have = {m["name"] for m in models}
        keep = {t: m for t, m in p["models"].items() if m in have}
        if keep != p["models"]:
            LP.save(NAME, {"models": keep})


def routes_with(prefer_local):
    """llm.routes with Ollama first (prefer_local) or out of the order (tried last)."""
    S.load()
    routes = {t: [s for s in (S.section("llm.routes").get(t) or []) if str(s).split(":")[0] != NAME] for t in ("fast", "smart")}
    if prefer_local:
        for t in routes:
            routes[t] = [f"{NAME}:{t}"] + routes[t]
    return routes


def prefer_local():
    S.load()
    routes = S.section("llm.routes")
    return any(str((routes.get(t) or [""])[0]).split(":")[0] == NAME for t in ("fast", "smart") if routes.get(t))


def save(patch):
    """Apply the section's switches. Returns the routes to write, or None."""
    _ensure_provider()
    prov = {}
    if "models" in patch:
        prov["models"] = {t: m for t, m in (patch["models"] or {}).items() if t in ("fast", "smart") and m}
    if "enabled" in patch:
        enabled = bool(patch["enabled"])
        p = provider()
        models = prov.get("models", p["models"])
        if enabled and not models:
            # switching on with nothing chosen: use the first downloaded model for both tiers
            have = installed_models() or []
            if not have:
                raise ValueError("download a model first, then switch Ollama on")
            prov["models"] = {"fast": have[0]["name"], "smart": have[0]["name"]}
        if enabled and not version():
            launch()
        prov["enabled"] = enabled
    if prov:
        LP.save(NAME, prov)
    if "autostart" in patch:
        _save_settings(patch)
    if "prefer_local" in patch:
        return routes_with(bool(patch["prefer_local"]))
    return None


def status():
    exe = executable()
    ver = version()
    models = installed_models() if ver else None
    p = provider()
    with _lock:
        pulls = {k: dict(v) for k, v in _pulls.items()}
    return {
        "installed": bool(exe) or bool(ver),
        "executable": exe,
        "running": bool(ver),
        "version": ver,
        "models": models or [],
        "enabled": bool(p and p["enabled"]),
        "chosen": (p or {}).get("models") or {},
        "prefer_local": prefer_local(),
        "autostart": settings()["autostart"],
        "disk": disk(),
        "pulls": pulls,
        "catalog": CATALOG,
        "download_url": DOWNLOAD_URL,
        "library_url": LIBRARY_URL,
        "platform": platform.system(),
    }
