"""
Loads agent_settings.yaml and answers dotted lookups with a default.

Every caller passes its own default, so a key deleted or mistyped in the YAML
never crashes a scheduled run: the default is used and the miss is logged
once. That is also why there is no second copy of the whole settings tree in
Python to keep in step with the file.
"""

import logging
import os
from pathlib import Path

import config

log = logging.getLogger("agents.settings")

DEFAULT_FILE = config.PROJECT_ROOT / "agent_settings.yaml"

_data = None
_path = None
_missed = set()


def load(path=None):
    """(Re)load the settings file. -> the parsed dict ({} on any failure)."""
    global _data, _path
    _path = Path(path or os.environ.get("AGENT_SETTINGS") or DEFAULT_FILE)
    try:
        import yaml

        with open(_path, encoding="utf-8") as f:
            _data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.warning("settings file %s not found - built-in defaults used", _path)
        _data = {}
    except Exception as e:
        log.error("settings file %s unreadable (%s) - built-in defaults used", _path, e)
        print(f"[agents] WARNING: {_path.name} could not be parsed ({e}); using defaults")
        _data = {}
    _missed.clear()
    return _data


def data():
    if _data is None:
        load()
    return _data


def get(dotted, default=None):
    """S.get('formula.growth.max', 0.2) -> the value, or the default."""
    node = data()
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            if dotted not in _missed:
                _missed.add(dotted)
                log.debug("setting %s missing - default %r used", dotted, default)
            return default
    return default if node is None else node


def num(dotted, default):
    """Numeric lookup that survives a string or junk in the YAML."""
    v = get(dotted, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        log.warning("setting %s=%r is not a number - default %r used", dotted, v, default)
        return float(default)


def section(dotted):
    """A dict section, or {} - convenient for weight tables."""
    v = get(dotted, {})
    return v if isinstance(v, dict) else {}


def match_sector(table_key, sector):
    """
    Look a sector up in a substring-keyed table such as sector_exposure.
    The longest matching key wins, so 'information tech' beats 'tech'.
    """
    table = section(table_key)
    s = (sector or "").lower()
    hits = [k for k in table if k != "default" and k in s]
    if hits:
        return table[max(hits, key=len)]
    return table.get("default")


def state_dir():
    # AGENT_STATE_DIR lets the cloud job point at its checkout of the
    # intel-reports branch without editing the settings file
    p = Path(os.environ.get("AGENT_STATE_DIR") or get("run.state_dir", "output/intel"))
    if not p.is_absolute():
        p = config.PROJECT_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_dotenv(path=None):
    """
    Minimal .env reader: KEY=VALUE lines into os.environ, without overriding
    anything already set (so GitHub secrets always win). No dependency.
    """
    path = Path(path or config.PROJECT_ROOT / ".env")
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n
