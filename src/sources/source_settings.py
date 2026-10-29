# FILE: src/sources/source_settings.py
"""
Which data providers the fetch layer may use, in which order, and their keys.

The order is the order of trust: the first provider that has a figure supplies
it, later ones only fill what is still missing. Yahoo Finance stays first
because its statements carry the richest per-field diagnosis; the others fill
the years and fields Yahoo does not serve (it publishes only ~4 annual periods).

Choices made in the web app (Configuration -> Data sources) live in
data/live/sources.json; API keys live in .env like the AI keys. Nothing here
needs a key to work - providers without one are simply skipped.
"""

import json
import os
from pathlib import Path

import config

SETTINGS = config.PROJECT_ROOT / "data" / "live" / "sources.json"
ENV_FILE = config.PROJECT_ROOT / ".env"

# key, label, what it supplies, the .env key it needs (None = free), where to get one
PROVIDERS = [
    {"key": "yahoo", "label": "Yahoo Finance (NSE)", "supplies": ["statements", "prices", "quotes"], "env": None,
     "about": "Statements for the latest ~4 years, full price history, live quotes.", "url": "https://finance.yahoo.com"},
    {"key": "screener", "label": "Screener.in", "supplies": ["statements"], "env": None,
     "about": "Ten or more years of annual results, balance sheets and cash flows for every NSE and BSE company.",
     "url": "https://www.screener.in"},
    {"key": "yahoo_bse", "label": "Yahoo Finance (BSE)", "supplies": ["statements", "prices", "quotes"], "env": None,
     "about": "The same company through its BSE listing (.BO) - fills gaps when the NSE symbol is thin or missing.",
     "url": "https://finance.yahoo.com"},
    {"key": "nse", "label": "NSE India", "supplies": ["prices", "quotes", "sectors"], "env": None,
     "about": "Daily closes, live quotes and index constituents with their industry, straight from the exchange.",
     "url": "https://www.nseindia.com"},
    {"key": "bse", "label": "BSE India", "supplies": ["prices", "quotes"], "env": None,
     "about": "Daily closes and live quotes from the Bombay Stock Exchange website.", "url": "https://www.bseindia.com"},
    {"key": "fmp", "label": "Financial Modeling Prep", "supplies": ["statements", "prices"], "env": "FMP_API_KEY",
     "about": "Annual statements and prices for NSE/BSE symbols. Free key: 250 requests a day.",
     "url": "https://site.financialmodelingprep.com/developer/docs"},
    {"key": "eodhd", "label": "EODHD", "supplies": ["statements", "prices"], "env": "EODHD_API_KEY",
     "about": "Fundamentals and end-of-day prices for NSE and BSE. Free key: 20 requests a day.",
     "url": "https://eodhd.com"},
    {"key": "alphavantage", "label": "Alpha Vantage", "supplies": ["prices"], "env": "ALPHAVANTAGE_API_KEY",
     "about": "Daily prices for BSE symbols. Free key: 25 requests a day.", "url": "https://www.alphavantage.co"},
]
BY_KEY = {p["key"]: p for p in PROVIDERS}
KEY_NAMES = [p["env"] for p in PROVIDERS if p["env"]]
DEFAULT = {"order": [p["key"] for p in PROVIDERS], "off": []}


def _read():
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load():
    """-> {"order": [keys...], "off": [keys...]} with unknown keys dropped and new providers appended."""
    d = _read()
    order = [k for k in d.get("order", []) if k in BY_KEY]
    order += [k for k in DEFAULT["order"] if k not in order]
    off = [k for k in d.get("off", []) if k in BY_KEY]
    return {"order": order, "off": off}


def save(order=None, off=None):
    cur = load()
    if order is not None:
        bad = [k for k in order if k not in BY_KEY]
        if bad:
            raise ValueError(f"unknown data provider: {', '.join(bad)}")
        cur["order"] = list(dict.fromkeys(order)) + [k for k in cur["order"] if k not in order]
    if off is not None:
        bad = [k for k in off if k not in BY_KEY]
        if bad:
            raise ValueError(f"unknown data provider: {', '.join(bad)}")
        cur["off"] = sorted(set(off))
    if "yahoo" in cur["off"] and "screener" in cur["off"] and not any(
            k not in cur["off"] and "statements" in BY_KEY[k]["supplies"] and has_key(k) for k in cur["order"]):
        raise ValueError("leave at least one source of company accounts switched on")
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return cur


def _env_file():
    out = {}
    try:
        for line in Path(ENV_FILE).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def key(provider):
    """The API key a provider needs, from the environment or .env; '' when none is set."""
    env = BY_KEY[provider]["env"]
    if not env:
        return ""
    return os.environ.get(env) or _env_file().get(env, "")


def has_key(provider):
    return not BY_KEY[provider]["env"] or bool(key(provider))


def enabled(supplies=None):
    """Provider keys switched on, usable (key present when one is needed) and, optionally,
    supplying `supplies` ("statements", "prices", "quotes", "sectors") - in trust order."""
    s = load()
    return [k for k in s["order"] if k not in s["off"] and has_key(k)
            and (supplies is None or supplies in BY_KEY[k]["supplies"])]


def status():
    """For the web app: every provider with its state."""
    s = load()
    return [{**p, "on": p["key"] not in s["off"], "has_key": has_key(p["key"]), "position": s["order"].index(p["key"])}
            for p in sorted(PROVIDERS, key=lambda p: s["order"].index(p["key"]))]
