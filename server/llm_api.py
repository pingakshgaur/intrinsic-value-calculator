"""
AI provider management for the browser: which providers have keys, which
models each key can actually reach, a one-click test of any model, and the
routing order. Keys are read from the environment / .env and never returned.
"""

import os
import re
import time

import requests

from agents import settings as S

# Model ids that cannot answer a chat prompt: speech, embeddings, images,
# safety classifiers and the like. Listed by providers, useless to the agents.
NOT_CHAT = re.compile(
    r"embed|tts|whisper|transcrib|guard|safety|image|vision|audio|speech|lyria|"
    r"robotics|nano-banana|parse|clip|reward|translate|retriever|deplot|fuyu|kosmos|"
    r"neva|vila|starcoder|codegemma|codellama|code-instruct|coder|aqa|live|omni|"
    r"computer-use|orpheus|calibration|detector|nvclip|recurrentgemma|cosmos",
    re.I,
)
_cache = {}


def _env_keys(env_file):
    out = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _key(p, env_file):
    name = p.get("key_env", "")
    return (os.environ.get(name) or _env_keys(env_file).get(name) or "").strip()


def providers(env_file):
    S.load()
    routes = S.section("llm.routes")
    out = []
    for name, p in S.section("llm.providers").items():
        if not isinstance(p, dict):
            continue
        out.append({
            "name": name,
            "base_url": p.get("base_url", ""),
            "key_env": p.get("key_env", ""),
            "has_key": bool(_key(p, env_file)),
            "models": p.get("models", {}) or {},
            "limits": {k: p.get(k) for k in ("requests_per_minute", "requests_per_day", "tokens_per_minute")},
        })
    return {"providers": out, "routes": {k: list(v or []) for k, v in routes.items()}}


def list_models(name, env_file, refresh=False):
    S.load()
    p = S.section("llm.providers").get(name)
    if not isinstance(p, dict):
        raise KeyError(f"unknown provider '{name}'")
    key = _key(p, env_file)
    if not key:
        raise PermissionError(f"no key for {name} - add {p.get('key_env')} first")
    hit = _cache.get(name)
    if hit and not refresh and time.time() - hit[0] < 600:
        return hit[1]
    r = requests.get(str(p["base_url"]).rstrip("/") + "/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"{name} answered HTTP {r.status_code}: {r.text[:200]}")
    ids = []
    for m in (r.json().get("data") or []):
        mid = str(m.get("id") or "")
        if mid.startswith("models/"):
            mid = mid[len("models/"):]
        if mid:
            ids.append({"id": mid, "chat": not NOT_CHAT.search(mid)})
    ids.sort(key=lambda m: (not m["chat"], m["id"]))
    _cache[name] = (time.time(), ids)
    return ids


def test_model(name, model, env_file):
    """Send a tiny JSON task; -> {ok, status, seconds, reply | error}."""
    S.load()
    p = S.section("llm.providers").get(name)
    if not isinstance(p, dict):
        raise KeyError(f"unknown provider '{name}'")
    key = _key(p, env_file)
    if not key:
        raise PermissionError(f"no key for {name}")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with valid JSON only."},
            {"role": "user", "content": 'Rate the headline "Company wins a large order" as {"sentiment": number from -1 to 1}.'},
        ],
        "max_tokens": 200,
        "temperature": 0.0,
    }
    t0 = time.time()
    try:
        r = requests.post(str(p["base_url"]).rstrip("/") + "/chat/completions",
                          headers={"Authorization": f"Bearer {key}"}, json=body, timeout=60)
    except requests.RequestException as e:
        return {"ok": False, "status": None, "seconds": round(time.time() - t0, 1),
                "error": f"{type(e).__name__}: the provider did not answer in time"}
    secs = round(time.time() - t0, 1)
    if r.status_code != 200:
        msg = r.text
        try:
            j = r.json()
            if isinstance(j, list) and j:
                j = j[0]
            msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else (j.get("detail") or j.get("error") or r.text)
        except ValueError:
            pass
        return {"ok": False, "status": r.status_code, "seconds": secs, "error": str(msg)[:300]}
    try:
        text = r.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return {"ok": False, "status": 200, "seconds": secs, "error": "answered, but not in the expected format"}
    from agents.llm import parse_json

    return {"ok": parse_json(text) is not None, "status": 200, "seconds": secs, "reply": (text or "")[:200],
            "error": None if parse_json(text) is not None else "answered, but not with valid JSON"}


def set_routes(text, routes):
    """Rewrite the two route lines in the settings text (flow lists)."""
    for tier in ("fast", "smart"):
        slots = routes.get(tier)
        if slots is None:
            continue
        if not all(re.fullmatch(r"[a-z0-9_\-]+:(fast|smart)", s) for s in slots):
            raise ValueError("route entries look like provider:fast or provider:smart")
        pat = re.compile(rf"^(\s*{tier}:\s*)\[[^\]]*\](.*)$", re.M)
        if not pat.search(text):
            raise ValueError(f"could not find llm.routes.{tier} in the settings file")
        text = pat.sub(lambda m: f"{m.group(1)}[{', '.join(slots)}]{m.group(2)}", text, count=1)
    return text
