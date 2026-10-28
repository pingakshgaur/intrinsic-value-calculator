# FILE: src/agents/llm_providers.py
"""
Every AI provider INTVAL can talk to, how to reach it, and its keys.

Two dialects cover almost every service:

    openai      POST {base}/chat/completions - Groq, Gemini (its OpenAI
                endpoint), NVIDIA, OpenAI, OpenRouter, Mistral, DeepSeek,
                Together, Fireworks, Cerebras, xAI, Perplexity, Azure OpenAI,
                local Ollama / LM Studio and any other compatible server
    anthropic   Anthropic's Messages API, through the official SDK

A provider is defined in agent_settings.yaml (llm.providers) or added from the
web app; the web app's additions and edits live in llm_providers.json next to
the settings file and win over the YAML. Keys never live in either file: each
provider names environment variables (GROQ_API_KEY, GROQ_API_KEY_2, ...) held
in .env locally or as secrets in the cloud. A provider with several keys
rotates to the next when one is rate-limited, out of quota or rejected.
"""

import json
import os
import re
import threading
from pathlib import Path

import config
from agents import settings as S

STYLES = ("openai", "anthropic")
AUTHS = ("bearer", "x-api-key", "api-key", "none")
NAME = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,31}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

# Known services, so adding one is a click. Free tiers change; the notes say what to check.
PRESETS = {
    "groq": {"label": "Groq", "style": "openai", "base_url": "https://api.groq.com/openai/v1", "auth": "bearer",
             "models": {"fast": "openai/gpt-oss-20b", "smart": "openai/gpt-oss-120b"}, "rpm": 28, "rpd": 14000, "tpm": 6000,
             "keys_url": "https://console.groq.com/keys", "note": "Generous free tier, very fast."},
    "gemini": {"label": "Google Gemini", "style": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "auth": "bearer",
               "models": {}, "rpm": 9, "rpd": 240, "tpm": 200000, "keys_url": "https://aistudio.google.com/apikey", "note": "Free tier with daily limits."},
    "nvidia": {"label": "NVIDIA NIM", "style": "openai", "base_url": "https://integrate.api.nvidia.com/v1", "auth": "bearer",
               "models": {}, "rpm": 35, "rpd": 5000, "tpm": 100000, "keys_url": "https://build.nvidia.com", "note": "Free credits; some listed models need a paid account."},
    "anthropic": {"label": "Anthropic (Claude)", "style": "anthropic", "base_url": "https://api.anthropic.com", "auth": "x-api-key",
                  "models": {"fast": "claude-haiku-5-5", "smart": "claude-opus-5-5"}, "rpm": 50, "rpd": 10000, "tpm": 400000,
                  "keys_url": "https://platform.claude.com/settings/keys", "note": "Paid; Claude models through the official SDK."},
    "openai": {"label": "OpenAI", "style": "openai", "base_url": "https://api.openai.com/v1", "auth": "bearer", "models": {},
               "rpm": 60, "rpd": 10000, "tpm": 200000, "keys_url": "https://platform.openai.com/api-keys", "note": "Paid."},
    "openrouter": {"label": "OpenRouter", "style": "openai", "base_url": "https://openrouter.ai/api/v1", "auth": "bearer", "models": {},
                   "rpm": 20, "rpd": 50, "tpm": 100000, "keys_url": "https://openrouter.ai/keys", "note": "One key for many providers; some free models."},
    "mistral": {"label": "Mistral", "style": "openai", "base_url": "https://api.mistral.ai/v1", "auth": "bearer", "models": {},
                "rpm": 30, "rpd": 5000, "tpm": 500000, "keys_url": "https://console.mistral.ai/api-keys", "note": "Free experiment tier."},
    "deepseek": {"label": "DeepSeek", "style": "openai", "base_url": "https://api.deepseek.com/v1", "auth": "bearer", "models": {},
                 "rpm": 60, "rpd": 10000, "tpm": 200000, "keys_url": "https://platform.deepseek.com/api_keys", "note": "Low-cost paid."},
    "together": {"label": "Together AI", "style": "openai", "base_url": "https://api.together.xyz/v1", "auth": "bearer", "models": {},
                 "rpm": 60, "rpd": 10000, "tpm": 200000, "keys_url": "https://api.together.ai/settings/api-keys", "note": "Open models, paid."},
    "fireworks": {"label": "Fireworks", "style": "openai", "base_url": "https://api.fireworks.ai/inference/v1", "auth": "bearer", "models": {},
                  "rpm": 60, "rpd": 10000, "tpm": 200000, "keys_url": "https://fireworks.ai/account/api-keys", "note": "Open models, paid."},
    "cerebras": {"label": "Cerebras", "style": "openai", "base_url": "https://api.cerebras.ai/v1", "auth": "bearer", "models": {},
                 "rpm": 30, "rpd": 14000, "tpm": 60000, "keys_url": "https://cloud.cerebras.ai", "note": "Free tier, very fast."},
    "xai": {"label": "xAI (Grok)", "style": "openai", "base_url": "https://api.x.ai/v1", "auth": "bearer", "models": {},
            "rpm": 60, "rpd": 10000, "tpm": 200000, "keys_url": "https://console.x.ai", "note": "Paid."},
    "perplexity": {"label": "Perplexity", "style": "openai", "base_url": "https://api.perplexity.ai", "auth": "bearer", "models": {},
                   "rpm": 50, "rpd": 5000, "tpm": 200000, "keys_url": "https://www.perplexity.ai/settings/api", "note": "Paid; answers with web search."},
    "azure": {"label": "Azure OpenAI", "style": "openai", "base_url": "https://<resource>.openai.azure.com/openai/deployments/<deployment>", "auth": "api-key",
              "models": {}, "rpm": 60, "rpd": 10000, "tpm": 200000, "keys_url": "https://portal.azure.com", "note": "Base URL names your resource and deployment.",
              "query": "api-version=2024-10-21"},
    "ollama": {"label": "Ollama (this computer)", "style": "openai", "base_url": "http://localhost:11434/v1", "auth": "none", "models": {},
               "rpm": 600, "rpd": 1000000, "tpm": 10000000, "keys_url": "https://ollama.com", "note": "Free, runs models locally; no key."},
    "lmstudio": {"label": "LM Studio (this computer)", "style": "openai", "base_url": "http://localhost:1234/v1", "auth": "none", "models": {},
                 "rpm": 600, "rpd": 1000000, "tpm": 10000000, "keys_url": "https://lmstudio.ai", "note": "Free, runs models locally; no key."},
}

_lock = threading.Lock()


def _store():
    """llm_providers.json: the web app's providers and edits."""
    return Path(os.environ.get("LLM_PROVIDERS_FILE") or config.PROJECT_ROOT / "llm_providers.json")


def _read_store():
    p = _store()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _write_store(data):
    p = _store()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def env_base(name):
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") + "_API_KEY"


def normalise(name, p):
    """One provider's settings with every field present."""
    base = p.get("key_env") or env_base(name)
    keys = [k for k in (p.get("key_envs") or [base]) if isinstance(k, str) and k]
    return {
        "name": name,
        "label": p.get("label") or PRESETS.get(name, {}).get("label") or name,
        "style": p.get("style") if p.get("style") in STYLES else "openai",
        "base_url": str(p.get("base_url") or "").rstrip("/"),
        "auth": p.get("auth") if p.get("auth") in AUTHS else "bearer",
        "header": str(p.get("header") or ""),
        "query": str(p.get("query") or ""),
        "key_envs": keys,
        "models": {k: v for k, v in (p.get("models") or {}).items() if v},
        "rpm": int(p.get("requests_per_minute") or p.get("rpm") or 10),
        "rpd": int(p.get("requests_per_day") or p.get("rpd") or 1000),
        "tpm": int(p.get("tokens_per_minute") or p.get("tpm") or 6000),
        "enabled": p.get("enabled", True) is not False,
        "source": p.get("_source", "settings"),
    }


def providers():
    """name -> provider, the settings file's merged with the web app's."""
    out = {}
    for name, p in (S.section("llm.providers") or {}).items():
        if isinstance(p, dict):
            out[name] = normalise(name, {**p, "_source": "settings"})
    for name, p in _read_store().items():
        if not isinstance(p, dict):
            continue
        if p.get("deleted"):
            out.pop(name, None)
            continue
        merged = {**({k: v for k, v in S.section("llm.providers").get(name, {}).items()} if isinstance(S.section("llm.providers").get(name), dict) else {}), **p}
        out[name] = normalise(name, {**merged, "_source": "settings+app" if name in out else "app"})
    return out


def clean(name, patch, existing=None):
    """Validate a provider patch. Raises ValueError."""
    if not NAME.match(name):
        raise ValueError("a provider name is lower-case letters, digits, - or _ (up to 32)")
    out = {}
    for k, v in (patch or {}).items():
        if k == "label":
            out[k] = str(v).strip()[:60]
        elif k == "style":
            if v not in STYLES:
                raise ValueError(f"style must be one of {', '.join(STYLES)}")
            out[k] = v
        elif k == "auth":
            if v not in AUTHS:
                raise ValueError(f"auth must be one of {', '.join(AUTHS)}")
            out[k] = v
        elif k == "base_url":
            v = str(v).strip().rstrip("/")
            if not re.match(r"^https?://[^\s]+$", v):
                raise ValueError("the base URL must start with http:// or https://")
            out[k] = v
        elif k in ("header", "query"):
            v = str(v or "").strip()
            if k == "header" and v and not re.fullmatch(r"[A-Za-z0-9\-]{1,64}", v):
                raise ValueError("a header name is letters, digits and dashes")
            if k == "query" and v and not re.fullmatch(r"[A-Za-z0-9_\-.=&]{1,200}", v):
                raise ValueError("query text is name=value pairs joined with &")
            out[k] = v
        elif k == "models":
            if not isinstance(v, dict):
                raise ValueError("models is {fast: ..., smart: ...}")
            out[k] = {t: str(m).strip()[:200] for t, m in v.items() if t in ("fast", "smart") and m}
        elif k in ("rpm", "rpd", "tpm"):
            out[k] = max(1, min(10_000_000, int(v)))
        elif k == "enabled":
            out[k] = bool(v)
        elif k == "key_envs":
            keys = [str(x).strip().upper() for x in v or []]
            bad = [x for x in keys if not ENV_NAME.match(x)]
            if bad:
                raise ValueError(f"not a valid variable name: {bad[0]}")
            out[k] = list(dict.fromkeys(keys))
        else:
            raise ValueError(f"unknown provider setting {k}")
    return out


def save(name, patch):
    with _lock:
        data = _read_store()
        cur = {k: v for k, v in (data.get(name) or {}).items() if k != "deleted"}
        cur.update(clean(name, patch, cur))
        data[name] = cur
        _write_store(data)
    return providers().get(name)


def delete(name):
    with _lock:
        data = _read_store()
        if name in (S.section("llm.providers") or {}):
            data[name] = {"deleted": True}  # a provider from the settings file is hidden, not erased from it
        else:
            data.pop(name, None)
        _write_store(data)


# ------------------------------------------------------------------ keys (.env)
def env_file():
    return config.PROJECT_ROOT / ".env"


def env_read(path=None):
    path = Path(path or env_file())
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def env_write(updates, path=None):
    """Set or (value None/"") remove variables in .env, keeping every other line and comment."""
    path = Path(path or env_file())
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else ["# Written by the web UI. Never commit this file."]
    left = dict(updates)
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if k in left:
            v = left.pop(k)
            if v:
                out.append(f"{k}={v}")
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in left.items() if v]
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    for k, v in updates.items():  # this process sees the change at once
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def key_value(env):
    return (os.environ.get(env) or env_read().get(env) or "").strip()


def keys(p):
    """[(env name, value)] for the keys this provider has; a local server needs none."""
    if p["auth"] == "none":
        return [("", "")]
    return [(e, v) for e in p["key_envs"] if (v := key_value(e))]


def mask(v):
    return "" if not v else ("•" * 4 + v[-4:]) if len(v) > 8 else "••••"


def next_key_env(p):
    base = p["key_envs"][0] if p["key_envs"] else env_base(p["name"])
    used = set(p["key_envs"])
    if base not in used or not key_value(base):
        return base
    n = 2
    while f"{base}_{n}" in used:
        n += 1
    return f"{base}_{n}"


def add_key(name, value):
    value = (value or "").strip()
    if not value or any(c in value for c in "\r\n\"' "):
        raise ValueError("paste the key alone, without spaces or quotes")
    p = providers().get(name)
    if not p:
        raise KeyError(name)
    if any(v == value for _, v in keys(p) if v):
        raise ValueError("this key is already saved for this provider")
    env = next_key_env(p)
    env_write({env: value})
    if env not in p["key_envs"]:
        save(name, {"key_envs": p["key_envs"] + [env]})
    return env


def remove_key(name, env):
    p = providers().get(name)
    if not p or env not in p["key_envs"]:
        raise KeyError(env)
    env_write({env: None})
    rest = [e for e in p["key_envs"] if e != env]
    save(name, {"key_envs": rest or [p["key_envs"][0]]})


def promote_key(name, env):
    """Move a key to the front: it is tried first."""
    p = providers().get(name)
    if not p or env not in p["key_envs"]:
        raise KeyError(env)
    save(name, {"key_envs": [env] + [e for e in p["key_envs"] if e != env]})


# ------------------------------------------------------------------ talking to a provider
class CallError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _headers(p, key):
    h = {"Content-Type": "application/json"}
    if p["auth"] == "none" or not key:
        return h
    if p["auth"] == "bearer":
        h["Authorization"] = f"Bearer {key}"
    elif p["auth"] == "x-api-key":
        h["x-api-key"] = key
    else:  # api-key: Azure and similar, under a header you can rename
        h[p["header"] or "api-key"] = key
    return h


def _url(p, path):
    u = p["base_url"] + path
    return u + ("?" + p["query"] if p["query"] else "")


def _anthropic(p, key, timeout):
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - listed in requirements.txt
        raise CallError(None, "the anthropic package is not installed - pip install anthropic") from e
    return anthropic, anthropic.Anthropic(api_key=key or None, base_url=p["base_url"] or None, timeout=timeout, max_retries=0)


def chat(p, key, model, system, user, max_tokens=600, json_mode=False, timeout=60, temperature=0.2, tier="smart"):
    """One reply. -> (text, tokens). Raises CallError(status, message)."""
    if p["style"] == "anthropic":
        anthropic, client = _anthropic(p, key, timeout)
        try:
            # current Claude models think by default and take no temperature; effort sets the depth,
            # and thinking shares max_tokens, so leave room for it
            r = client.messages.create(
                model=model, max_tokens=max(int(max_tokens) * 4, 2048), system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low" if tier == "fast" else "medium"},
            )
        except anthropic.AuthenticationError as e:
            raise CallError(401, str(e)) from e
        except anthropic.PermissionDeniedError as e:
            raise CallError(403, str(e)) from e
        except anthropic.RateLimitError as e:
            raise CallError(429, str(e)) from e
        except anthropic.APIStatusError as e:
            raise CallError(e.status_code, str(e)) from e
        except anthropic.APIConnectionError as e:
            raise CallError(None, f"{type(e).__name__}: the provider did not answer") from e
        if r.stop_reason == "refusal":
            raise CallError(422, "the model declined this request")
        text = "".join(b.text for b in r.content if b.type == "text")
        u = r.usage
        return text, (u.input_tokens or 0) + (u.output_tokens or 0)

    import requests

    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": int(max_tokens), "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(_url(p, "/chat/completions"), headers=_headers(p, key), json=body, timeout=timeout)
    except requests.RequestException as e:
        raise CallError(None, f"{type(e).__name__}: the provider did not answer") from e
    if r.status_code != 200:
        msg = r.text
        try:
            j = r.json()
            j = j[0] if isinstance(j, list) and j else j
            msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else (j.get("detail") or j.get("error") or r.text)
        except (ValueError, AttributeError):
            pass
        raise CallError(r.status_code, str(msg)[:300])
    try:
        data = r.json()
        return data["choices"][0]["message"]["content"] or "", (data.get("usage") or {}).get("total_tokens", 0)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise CallError(502, "answered, but not in the expected format") from e


def list_models(p, key, timeout=25):
    """-> [model id] the key can see."""
    if p["style"] == "anthropic":
        anthropic, client = _anthropic(p, key, timeout)
        try:
            return [m.id for m in client.models.list()]
        except anthropic.APIStatusError as e:
            raise CallError(e.status_code, str(e)) from e
        except anthropic.APIConnectionError as e:
            raise CallError(None, "the provider did not answer") from e
    import requests

    try:
        r = requests.get(_url(p, "/models"), headers=_headers(p, key), timeout=timeout)
    except requests.RequestException as e:
        raise CallError(None, f"{type(e).__name__}: the provider did not answer") from e
    if r.status_code != 200:
        raise CallError(r.status_code, r.text[:200])
    out = []
    for m in (r.json().get("data") or r.json().get("models") or []):
        mid = str(m.get("id") or m.get("name") or "")
        if mid.startswith("models/"):
            mid = mid[len("models/"):]
        if mid:
            out.append(mid)
    return out
