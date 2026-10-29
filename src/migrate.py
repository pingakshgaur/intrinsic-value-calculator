# FILE: src/migrate.py
"""
Bring an existing installation's data up to the version just installed,
without losing anything the user made. Run by the updaters after they copy
the new program files (packaging/):

    INTVAL --migrate            (python run.py --migrate from a checkout)

What it does, and what it never does:

  * backs up first: data/ (company lists, watchlists, learning cache state),
    agent_settings.yaml, .env, llm_providers.json and output/intel (the
    research workforce's memory - the SQLite blackboard, reports, agent
    profiles) into backups/<timestamp>-<old>-to-<new>/ - unless the updater
    already made that backup (--no-backup);
  * adds the training companies the new version ships (defaults/data/) that
    the user's training lists do not have yet - rows are only ever added;
  * adds settings sections the new version introduces to agent_settings.yaml,
    copied with their comments from the new defaults; every value the user
    set stays as it is (keys missing inside an existing section simply use
    the built-in defaults, as they always have);
  * records the update in data/live/updates.json.

It never deletes or rewrites the user's companies, watchlists, research
history, trained models' inputs, keys or reports. Running it twice is harmless.
"""

import csv
import json
import shutil
import time

import config

ROOT = config.PROJECT_ROOT
SHIPPED = ROOT / "defaults" / "data"        # the new version's own copies of the starter lists
MERGE_LISTS = ("training_universe.csv", "auto_training_universe.csv")
BACKUP_ITEMS = ("data", "agent_settings.yaml", ".env", "llm_providers.json", "output/intel", "VERSION")
HISTORY = ROOT / "data" / "live" / "updates.json"
KEEP_BACKUPS = 5


def version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def backup(label=None):
    """Copy everything the user owns into backups/<stamp>-<label>/. -> the folder."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = ROOT / "backups" / (f"{stamp}-{label}" if label else stamp)
    dest.mkdir(parents=True, exist_ok=True)
    for item in BACKUP_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, dest / item, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.tmp", "__pycache__"))
        elif src.is_file():
            (dest / item).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / item)
    # old backups beyond the last few are removed, oldest first
    olds = sorted((p for p in (ROOT / "backups").iterdir() if p.is_dir()), key=lambda p: p.name)
    for p in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(p, ignore_errors=True)
    return dest


def _rows(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))
    except OSError:
        return []


def merge_list(name):
    """Append the shipped list's companies the user's copy lacks (matched by ticker, else name). -> rows added."""
    new = _rows(SHIPPED / name)
    if len(new) < 2:
        return 0
    mine_path = ROOT / "data" / name
    mine = _rows(mine_path)
    if not mine:
        mine_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SHIPPED / name, mine_path)
        return len(new) - 1
    head = [h.strip().lower() for h in mine[0]]
    nhead = [h.strip().lower() for h in new[0]]
    ti, ni = (head.index("ticker") if "ticker" in head else -1), (head.index("company name") if "company name" in head else 0)
    have = {(r[ti].strip().upper() if ti >= 0 and ti < len(r) and r[ti].strip() else r[ni].strip().lower()) for r in mine[1:] if r}
    add = []
    for r in new[1:]:
        if not r:
            continue
        d = dict(zip(nhead, r))
        key = d.get("ticker", "").strip().upper() or d.get("company name", "").strip().lower()
        if key and key not in have:
            have.add(key)
            add.append([d.get(h, "") for h in head])
    if add:
        with open(mine_path, "a", encoding="utf-8", newline="") as f:
            text = mine_path.read_text(encoding="utf-8-sig")
            if text and not text.endswith("\n"):
                f.write("\n")
            csv.writer(f).writerows(add)
    return len(add)


def _top_blocks(text):
    """Top-level YAML sections as {key: block text}, comments directly above a key included."""
    blocks, order, cur, pending = {}, [], None, []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n")
        if bare and not bare[0].isspace() and not bare.startswith("#") and ":" in bare:
            cur = bare.split(":", 1)[0].strip()
            blocks[cur] = "".join(pending) + line
            order.append(cur)
            pending = []
        elif cur is None or (bare.startswith("#") and not line[0].isspace()):
            pending.append(line)
        else:
            blocks[cur] += "".join(pending) + line
            pending = []
    return blocks, order


def merge_settings():
    """Add top-level sections the new defaults have and the user's file lacks. -> section names added."""
    import yaml

    mine_path, new_path = ROOT / "agent_settings.yaml", ROOT / "agent_settings.defaults.yaml"
    if not new_path.exists():
        return []
    if not mine_path.exists():
        body = new_path.read_text(encoding="utf-8")
        mine_path.write_text(body.split("\n", 3)[3] if body.startswith("# Factory copy") else body, encoding="utf-8")
        return ["(all)"]
    text = mine_path.read_text(encoding="utf-8")
    try:
        mine = yaml.safe_load(text) or {}
        new = yaml.safe_load(new_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []  # a hand-broken settings file is the user's to fix; never overwrite it
    missing = [k for k in new if k not in mine]
    if not missing:
        return []
    blocks, _ = _top_blocks(new_path.read_text(encoding="utf-8"))
    add = "".join(blocks[k] for k in missing if k in blocks)
    if add:
        stamp = time.strftime("%Y-%m-%d")
        mine_path.write_text(text.rstrip("\n") + f"\n\n# ---- added by the update on {stamp} (new in this version) ----\n" + add, encoding="utf-8")
    return missing


def run(backup_first=True, previous=None):
    old = previous or "earlier version"
    new = version()
    where = backup(f"{old}-to-{new}".replace(" ", "-")) if backup_first else None
    added = {name: merge_list(name) for name in MERGE_LISTS if (SHIPPED / name).exists()}
    sections = merge_settings()
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    try:
        hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hist = []
    hist.append({"at": time.time(), "from": old, "to": new, "backup": str(where) if where else None,
                 "training_rows_added": added, "settings_sections_added": sections})
    HISTORY.write_text(json.dumps(hist[-50:], indent=2), encoding="utf-8")
    print(f"[update] INTVAL {new} - your data was kept")
    if where:
        print(f"[update] backup of your data: {where}")
    for name, n in added.items():
        print(f"[update] {name}: {n} new training compan{'y' if n == 1 else 'ies'} added")
    print(f"[update] settings: {', '.join(sections) + ' added' if sections else 'nothing new to add'}")
    return {"backup": where, "added": added, "sections": sections}
