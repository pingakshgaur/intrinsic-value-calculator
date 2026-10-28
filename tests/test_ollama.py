# FILE: tests/test_ollama.py
"""
Tests for the Ollama section (server/ollama_api.py) and local-server calls.
No Ollama needed: its HTTP API is replaced by fakes, and every file goes to a
temporary folder.

    python -m pytest tests -q
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ["INTVAL_OUTPUT_DIR"] = tempfile.mkdtemp(prefix="intval_test_")

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from agents import llm_providers as LP  # noqa: E402
from agents import settings as S  # noqa: E402
from server import ollama_api as O  # noqa: E402

MODELS = [{"name": "llama3.2:3b", "size": 2_000_000_000, "modified": None, "family": "llama", "params": "3B", "quant": "Q4_K_M"},
          {"name": "qwen2.5:7b", "size": 4_700_000_000, "modified": None, "family": "qwen2", "params": "7B", "quant": "Q4_K_M"}]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """The shipped settings, providers and Ollama state in tmp_path; Ollama 'running' with two models."""
    monkeypatch.setenv("AGENT_SETTINGS", str(ROOT / "agent_settings.defaults.yaml"))
    monkeypatch.setenv("LLM_PROVIDERS_FILE", str(tmp_path / "llm_providers.json"))
    monkeypatch.setattr(O, "SETTINGS", tmp_path / "ollama.json")
    monkeypatch.setattr(O, "_write_json", lambda path, value: Path(path).write_text(json.dumps(value)))
    monkeypatch.setattr(O, "version", lambda timeout=1.5: "0.9.0")
    monkeypatch.setattr(O, "installed_models", lambda: [dict(m) for m in MODELS])
    monkeypatch.setattr(O, "launch", lambda wait=12.0: (True, "already running"))
    O._pulls.clear()
    S.load()
    yield
    S.load()


def test_switching_on_needs_a_model_and_picks_the_first(monkeypatch):
    monkeypatch.setattr(O, "installed_models", lambda: [])
    with pytest.raises(ValueError):
        O.save({"enabled": True})
    monkeypatch.setattr(O, "installed_models", lambda: [dict(m) for m in MODELS])
    O.save({"enabled": True})
    p = LP.providers()["ollama"]
    assert p["enabled"] and p["auth"] == "none" and p["base_url"].endswith(":11434/v1")
    assert p["models"] == {"fast": "llama3.2:3b", "smart": "llama3.2:3b"}
    O.save({"models": {"smart": "qwen2.5:7b", "fast": "llama3.2:3b"}})
    assert LP.providers()["ollama"]["models"]["smart"] == "qwen2.5:7b"
    O.save({"enabled": False})
    st = O.status()
    assert not st["enabled"] and st["chosen"]["smart"] == "qwen2.5:7b"  # the choice is kept while off


def test_prefer_local_puts_ollama_first_and_back_out():
    first = O.routes_with(True)
    assert first["fast"][0] == "ollama:fast" and first["smart"][0] == "ollama:smart"
    shipped = S.section("llm.routes")
    assert O.routes_with(False) == {t: list(shipped[t]) for t in ("fast", "smart")}


def test_autostart_setting_round_trips():
    assert O.settings()["autostart"] is True  # on unless the user turns it off
    O.save({"autostart": False})
    assert O.settings()["autostart"] is False


def test_pull_adds_up_every_layer(monkeypatch):
    lines = [{"status": "pulling manifest"},
             {"status": "pulling a", "digest": "sha:a", "total": 100, "completed": 40},
             {"status": "pulling b", "digest": "sha:b", "total": 300, "completed": 0},
             {"status": "pulling a", "digest": "sha:a", "total": 100, "completed": 100},
             {"status": "pulling b", "digest": "sha:b", "total": 300, "completed": 150},
             {"status": "success"}]
    seen = []

    class Resp:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            for ev in lines:
                yield json.dumps(ev).encode()
                seen.append(dict(O._pulls["m:1b"]))

    monkeypatch.setattr(O.requests, "post", lambda *a, **k: Resp())
    O._pulls["m:1b"] = {"status": "starting", "completed": 0, "total": 0, "error": None, "done": False, "started": 0}
    O._pull_worker("m:1b")
    assert seen[4]["completed"] == 250 and seen[4]["total"] == 400
    assert O._pulls["m:1b"]["done"] and O._pulls["m:1b"]["error"] is None

    lines[:] = [{"error": "pull model manifest: file does not exist"}]
    O._pulls["bad:1b"] = {"status": "starting", "completed": 0, "total": 0, "error": None, "done": False, "started": 0}
    O._pull_worker("bad:1b")
    assert O._pulls["bad:1b"]["done"] and "does not exist" in O._pulls["bad:1b"]["error"]
    with pytest.raises(ValueError):
        O.pull("two words")


def test_a_local_server_gets_a_long_timeout(monkeypatch):
    got = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 3}}

    def post(url, headers, json, timeout):
        got["timeout"], got["auth"] = timeout, headers.get("Authorization")
        return Resp()

    import requests
    monkeypatch.setattr(requests, "post", post)
    local = LP.normalise("ollama", {"base_url": "http://127.0.0.1:11434/v1", "auth": "none"})
    LP.chat(local, "", "llama3.2:3b", "sys", "user", timeout=60)
    assert got["timeout"] >= LP.LOCAL_TIMEOUT and got["auth"] is None
    cloud = LP.normalise("groq", {"base_url": "https://api.groq.com/openai/v1", "auth": "bearer"})
    LP.chat(cloud, "k", "m", "sys", "user", timeout=60)
    assert got["timeout"] == 60
