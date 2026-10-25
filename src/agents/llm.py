"""
LLM router for free API tiers (Groq, Gemini, NVIDIA NIM, any OpenAI-compatible).

DESIGNED FOR FREE TIERS

    one client       every provider speaks the OpenAI /chat/completions
                     dialect, so there is one HTTP path and no SDKs to install
    routes           each task asks for a TIER ("fast" for bulk classification,
                     "smart" for reasoning and writing); agent_settings.yaml
                     maps a tier to an ordered list of provider:model slots
    pacing           a per-provider sliding window keeps requests and tokens
                     per minute under the published free limits, and the
                     daily count is kept in the blackboard so it survives
                     separate cloud jobs on the same day
    fall-through     a 429, a 5xx, a timeout or a spent daily quota moves the
                     call to the next slot instead of failing it
    cache            identical prompts within cache_hours are answered from
                     SQLite and cost nothing
    budget           max_calls_per_run caps a runaway loop
    off switch       no keys, llm.enabled false or --no-llm -> complete()
                     returns None and every agent uses its rule-based path

Keys come from the environment only (GROQ_API_KEY, GEMINI_API_KEY,
NVIDIA_API_KEY, ...). They are never logged, cached or written to reports.
"""

import collections
import hashlib
import json
import logging
import os
import re
import threading
import time

import requests

from agents import settings as S

log = logging.getLogger("agents.llm")


class _Pacer:
    """Sliding 60-second window of request times and token counts."""

    def __init__(self, rpm, tpm):
        self.rpm = max(1, int(rpm))
        self.tpm = max(500, int(tpm))
        self.calls = collections.deque()
        self.tokens = collections.deque()
        self.lock = threading.Lock()

    def wait(self, est_tokens):
        # one request bigger than the whole minute's allowance would wait forever
        est_tokens = min(est_tokens, self.tpm)
        while True:
            with self.lock:
                now = time.time()
                while self.calls and now - self.calls[0] > 60:
                    self.calls.popleft()
                while self.tokens and now - self.tokens[0][0] > 60:
                    self.tokens.popleft()
                used = sum(t for _, t in self.tokens)
                if len(self.calls) < self.rpm and used + est_tokens <= self.tpm:
                    self.calls.append(now)
                    self.tokens.append((now, est_tokens))
                    return
                starts = ([self.calls[0]] if self.calls else []) + (
                    [self.tokens[0][0]] if self.tokens else []
                )
                oldest = min(starts) if starts else now
                delay = max(0.5, 60 - (now - oldest) + 0.1)
            time.sleep(min(delay, 10))


def _estimate_tokens(text):
    # roughly four characters a token for English prose and JSON
    return max(1, len(text) // 4)


def parse_json(text):
    """Pull the first JSON object or array out of a model reply."""
    if text is None:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


class LLMRouter:
    def __init__(self, board=None, enabled=True):
        self.board = board
        self.enabled = enabled and bool(S.get("llm.enabled", True))
        self.max_calls = int(S.num("llm.max_calls_per_run", 400))
        self.cache_hours = S.num("llm.cache_hours", 20)
        self.retries = int(S.num("llm.retries", 2))
        self.timeout = S.num("llm.timeout_seconds", 60)
        self.temperature = S.num("llm.temperature", 0.2)
        self.calls = 0
        self.cache_hits = 0
        self.failures = collections.Counter()
        self.per_provider = collections.Counter()
        self._lock = threading.Lock()
        self._dead = set()  # providers that rejected the key this run
        self.providers = {}
        for name, p in S.section("llm.providers").items():
            if not isinstance(p, dict):
                continue
            key = os.environ.get(p.get("key_env", ""), "").strip()
            if not key:
                continue
            self.providers[name] = {
                "base_url": str(p.get("base_url", "")).rstrip("/"),
                "key": key,
                "models": p.get("models", {}) or {},
                "rpd": int(p.get("requests_per_day", 1000)),
                "pacer": _Pacer(p.get("requests_per_minute", 10), p.get("tokens_per_minute", 6000)),
            }
        if not self.providers:
            self.enabled = False

    # ------------------------------------------------------------ status
    def describe(self):
        if not self.enabled:
            return "LLM off - every agent uses its rule-based path"
        return "LLM on via " + ", ".join(sorted(self.providers))

    def stats(self):
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "by_provider": dict(self.per_provider),
            "failures": dict(self.failures),
        }

    def _slots(self, tier):
        routes = S.section("llm.routes")
        out = []
        for slot in routes.get(tier, []) or []:
            prov, _, model_tier = str(slot).partition(":")
            p = self.providers.get(prov)
            if not p or prov in self._dead:
                continue
            model = p["models"].get(model_tier or tier)
            if model:
                out.append((prov, model))
        # any configured provider not named in the route is a last resort
        for prov, p in self.providers.items():
            if prov in self._dead:
                continue
            model = p["models"].get(tier) or next(iter(p["models"].values()), None)
            if model and (prov, model) not in out:
                out.append((prov, model))
        return out

    # ------------------------------------------------------------ calling
    def complete(self, tier, system, user, max_tokens=600, json_mode=True, agent=""):
        """-> parsed JSON (json_mode) or text, or None when nothing answered."""
        if not self.enabled:
            return None
        key = hashlib.sha256(
            json.dumps([tier, system, user, max_tokens, json_mode]).encode("utf-8")
        ).hexdigest()
        if self.board is not None:
            hit = self.board.cache_get(key, self.cache_hours)
            if hit is not None:
                self.cache_hits += 1
                return parse_json(hit) if json_mode else hit

        with self._lock:
            if self.calls >= self.max_calls:
                self.failures["run budget spent"] += 1
                return None
            self.calls += 1

        if json_mode:
            system = system + "\nReply with valid JSON only. No prose outside the JSON."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        est = _estimate_tokens(system + user) + max_tokens

        for prov, model in self._slots(tier):
            p = self.providers[prov]
            if self.board is not None and self.board.usage_today(prov)[0] >= p["rpd"]:
                self.failures[f"{prov} daily quota"] += 1
                continue
            for attempt in range(self.retries):
                p["pacer"].wait(est)
                text, tokens, status = self._post(p, model, messages, max_tokens, json_mode)
                if text is not None:
                    if self.board is not None:
                        self.board.add_usage(prov, tokens)
                        self.board.cache_put(key, text)
                    self.per_provider[prov] += 1
                    if json_mode:
                        parsed = parse_json(text)
                        if parsed is not None:
                            return parsed
                        self.failures[f"{prov} bad JSON"] += 1
                        break  # a different model may format better
                    return text
                if status in (401, 403):
                    log.error("%s rejected the API key - provider disabled this run", prov)
                    self._dead.add(prov)
                    break
                if status == 400 and json_mode:
                    # some models refuse response_format; retry once without it
                    text, tokens, status = self._post(p, model, messages, max_tokens, False)
                    if text is not None:
                        parsed = parse_json(text)
                        if parsed is not None:
                            self.per_provider[prov] += 1
                            if self.board is not None:
                                self.board.add_usage(prov, tokens)
                                self.board.cache_put(key, text)
                            return parsed
                    break
                if status == 429:
                    time.sleep(min(20, 4 * (attempt + 1)))
                elif status and status >= 500:
                    time.sleep(2 * (attempt + 1))
                else:
                    break
        log.warning("no LLM answered a %s request for %s", tier, agent)
        self.failures["unanswered"] += 1
        return None

    def _post(self, p, model, messages, max_tokens, json_mode):
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": self.temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(
                p["base_url"] + "/chat/completions",
                headers={"Authorization": f"Bearer {p['key']}", "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            log.warning("LLM request failed (%s): %s", model, type(e).__name__)
            return None, 0, None
        if r.status_code != 200:
            log.warning("LLM %s returned HTTP %s: %s", model, r.status_code, r.text[:200])
            return None, 0, r.status_code
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            tokens = (data.get("usage") or {}).get("total_tokens", 0)
            return text, tokens, 200
        except (ValueError, KeyError, IndexError, TypeError):
            return None, 0, 502

    # ------------------------------------------------------------ check
    def check(self):
        """Ping every configured provider once. -> list of (provider, model, ok, note)."""
        out = []
        configured = S.section("llm.providers")
        for name, p in configured.items():
            if name not in self.providers:
                out.append((name, "-", False, f"no key in ${p.get('key_env', '?')}"))
                continue
            for tier in ("fast", "smart"):
                model = self.providers[name]["models"].get(tier)
                if not model:
                    continue
                t0 = time.time()
                text, _, status = self._post(
                    self.providers[name],
                    model,
                    [{"role": "user", "content": 'Reply with {"ok": true}'}],
                    20,
                    False,
                )
                ok = text is not None
                note = f"{time.time() - t0:.1f}s" if ok else f"HTTP {status}"
                out.append((name, model, ok, note))
        return out
