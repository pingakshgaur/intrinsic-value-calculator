# FILE: server/llm_api.py
"""
AI provider management for the browser: which providers have keys, which
models each key can actually reach, a one-click test of any model, and the
routing order, for every provider (src/agents/llm_providers.py) and each of
its keys. Keys are read from the environment / .env and never returned.
"""

import re
import time

from agents import llm_providers as LP
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


def _provider(name):
    S.load()
    p = LP.providers().get(name)
    if not p:
        raise KeyError(f"unknown provider '{name}'")
    return p


def _pick_key(p, key_env=None):
    ks = LP.keys(p)
    if key_env:
        ks = [k for k in ks if k[0] == key_env]
    if not ks:
        raise PermissionError(f"no key for {p['name']} - add one first")
    return ks[0]


def providers(env_file=None):
    """Every provider with its keys (masked), models and limits, plus the presets and routes."""
    S.load()
    routes = S.section("llm.routes")
    out = []
    for name, p in LP.providers().items():
        out.append({
            **{k: p[k] for k in ("name", "label", "style", "base_url", "auth", "header", "query", "models", "enabled", "source")},
            "limits": {"requests_per_minute": p["rpm"], "requests_per_day": p["rpd"], "tokens_per_minute": p["tpm"]},
            "keys": [{"env": e, "set": bool(LP.key_value(e)), "masked": LP.mask(LP.key_value(e))} for e in p["key_envs"]] if p["auth"] != "none" else [],
            "has_key": p["auth"] == "none" or bool(LP.keys(p)),
            "key_env": p["key_envs"][0] if p["key_envs"] else "",
            "preset": LP.PRESETS.get(name, {}).get("keys_url"),
        })
    presets = [{"name": k, **{f: v for f, v in p.items() if f != "models"}, "models": p.get("models", {})} for k, p in LP.PRESETS.items()]
    return {"providers": out, "routes": {k: list(v or []) for k, v in routes.items()}, "presets": presets,
            "styles": list(LP.STYLES), "auths": list(LP.AUTHS)}


def list_models(name, env_file=None, refresh=False, key_env=None):
    p = _provider(name)
    env, key = _pick_key(p, key_env)
    ck = (name, env)
    hit = _cache.get(ck)
    if hit and not refresh and time.time() - hit[0] < 600:
        return hit[1]
    try:
        ids = LP.list_models(p, key)
    except LP.CallError as e:
        raise RuntimeError(f"{name} answered {'HTTP ' + str(e.status) if e.status else 'nothing'}: {str(e)[:200]}") from e
    out = sorted(({"id": m, "chat": not NOT_CHAT.search(m)} for m in ids), key=lambda m: (not m["chat"], m["id"]))
    _cache[ck] = (time.time(), out)
    return out


def test_model(name, model, env_file=None, key_env=None):
    """Send a tiny JSON task; -> {ok, status, seconds, reply | error, key}."""
    p = _provider(name)
    env, key = _pick_key(p, key_env)
    t0 = time.time()
    try:
        text, _ = LP.chat(p, key, model, "Reply with valid JSON only.",
                          'Rate the headline "Company wins a large order" as {"sentiment": number from -1 to 1}.',
                          max_tokens=200, temperature=0.0, tier="fast")
    except LP.CallError as e:
        return {"ok": False, "status": e.status, "seconds": round(time.time() - t0, 1), "error": str(e)[:300], "key": env}
    from agents.llm import parse_json

    ok = parse_json(text) is not None
    return {"ok": ok, "status": 200, "seconds": round(time.time() - t0, 1), "reply": (text or "")[:200],
            "error": None if ok else "answered, but not with valid JSON", "key": env}


def set_routes(text, routes):
    """Rewrite the two route lines in the settings text (flow lists)."""
    for tier in ("fast", "smart"):
        slots = routes.get(tier)
        if slots is None:
            continue
        if not all(re.fullmatch(r"[a-z0-9][a-z0-9_\-]{0,31}:(fast|smart)", s) for s in slots):
            raise ValueError("route entries look like provider:fast or provider:smart")
        pat = re.compile(rf"^(\s*{tier}:\s*)\[[^\]]*\](.*)$", re.M)
        if not pat.search(text):
            raise ValueError(f"could not find llm.routes.{tier} in the settings file")
        text = pat.sub(lambda m: f"{m.group(1)}[{', '.join(slots)}]{m.group(2)}", text, count=1)
    return text
