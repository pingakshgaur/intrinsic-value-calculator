# FILE: tests/test_update.py
"""
Tests for updating an installation without losing data: the migration that
runs after an update (src/migrate.py), the Linux updater's backup and
install lookup (packaging/linux/installer.py), the sector directory and
research runs on a watchlist. Every file goes to a temporary folder.

    python -m pytest tests -q
"""

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "src", "src/sources", "src/models", "src/io_layer", "tools", "packaging/linux"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import migrate  # noqa: E402

HEAD = ["company name", "sector name", "market cap", "ticker"]


def _csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([HEAD, *rows])


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An installed INTVAL with a user's own data, and the new version's defaults beside it."""
    monkeypatch.setattr(migrate, "ROOT", tmp_path)
    monkeypatch.setattr(migrate, "SHIPPED", tmp_path / "defaults" / "data")
    monkeypatch.setattr(migrate, "HISTORY", tmp_path / "data" / "live" / "updates.json")
    _csv(tmp_path / "data" / "training_universe.csv", [["Alpha Ltd", "IT", "Mid", "ALPHA.NS"], ["My Own Pick", "Banks", "Small", "MINE.NS"]])
    _csv(tmp_path / "data" / "companies.csv", [["Alpha Ltd", "IT", "Mid", "ALPHA.NS"]])
    _csv(tmp_path / "defaults" / "data" / "training_universe.csv", [["Alpha Ltd", "IT", "Mid", "ALPHA.NS"], ["Beta Ltd", "Auto", "Large", "BETA.NS"]])
    (tmp_path / "data" / "live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "live" / "watchlists.json").write_text('{"lists": [{"id": "x"}]}', encoding="utf-8")
    (tmp_path / "output" / "intel").mkdir(parents=True)
    (tmp_path / "output" / "intel" / "blackboard.sqlite").write_bytes(b"agent memory")
    (tmp_path / ".env").write_text("GROQ_API_KEY=secret\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.1.0\n", encoding="utf-8")
    (tmp_path / "agent_settings.yaml").write_text("# my notes\nrun:\n  quick: true   # I changed this\nformula:\n  growth: {max: 0.3}\n", encoding="utf-8")
    (tmp_path / "agent_settings.defaults.yaml").write_text(
        "# Factory copy of agent_settings.yaml.\n# Do not edit.\n\nrun:\n  quick: false\n  extra: 1\n"
        "formula:\n  growth: {max: 0.2}\n\n# sources the new version adds\nsources:\n  timeout: 20   # seconds\n", encoding="utf-8")
    return tmp_path


def test_migration_keeps_everything_and_only_adds(home):
    got = migrate.run(previous="1.0.0")
    # the user's own pick stays, the shipped newcomer is appended, nothing is duplicated
    rows = list(csv.reader(open(home / "data" / "training_universe.csv", encoding="utf-8")))
    assert [r[3] for r in rows[1:]] == ["ALPHA.NS", "MINE.NS", "BETA.NS"] and got["added"]["training_universe.csv"] == 1
    # coverage, watchlists, the agents' memory and keys are untouched
    assert (home / "data" / "companies.csv").read_text().count("\n") == 2
    assert json.loads((home / "data" / "live" / "watchlists.json").read_text())["lists"] == [{"id": "x"}]
    assert (home / "output" / "intel" / "blackboard.sqlite").read_bytes() == b"agent memory"
    assert (home / ".env").read_text() == "GROQ_API_KEY=secret\n"
    # settings: the user's values and comments stay; only the new section is added, with its comment
    text = (home / "agent_settings.yaml").read_text()
    assert "quick: true   # I changed this" in text and "max: 0.3" in text and got["sections"] == ["sources"]
    assert "timeout: 20   # seconds" in text and "# sources the new version adds" in text
    # a full backup came first
    b = got["backup"]
    assert (b / "output" / "intel" / "blackboard.sqlite").exists() and (b / ".env").exists() and (b / "data" / "live" / "watchlists.json").exists()
    assert json.loads((home / "data" / "live" / "updates.json").read_text())[-1]["from"] == "1.0.0"


def test_migration_twice_changes_nothing_more(home):
    migrate.run(previous="1.0.0")
    before = ((home / "data" / "training_universe.csv").read_text(), (home / "agent_settings.yaml").read_text())
    again = migrate.run(backup_first=False)
    assert again["added"]["training_universe.csv"] == 0 and again["sections"] == []
    assert before == ((home / "data" / "training_universe.csv").read_text(), (home / "agent_settings.yaml").read_text())


def test_broken_settings_file_is_left_alone(home):
    (home / "agent_settings.yaml").write_text("run: [unclosed\n", encoding="utf-8")
    assert migrate.run(backup_first=False)["sections"] == []
    assert (home / "agent_settings.yaml").read_text() == "run: [unclosed\n"


def test_backups_are_capped(home, monkeypatch):
    monkeypatch.setattr(migrate, "KEEP_BACKUPS", 2)
    for i in range(4):
        migrate.backup(f"t{i}")
    assert len([p for p in (home / "backups").iterdir()]) == 2


def test_linux_updater_finds_the_install_and_backs_up(tmp_path, monkeypatch):
    import installer

    target = tmp_path / "intval"
    (target / "_internal").mkdir(parents=True)
    (target / "INTVAL").write_text("#!/bin/sh\n")
    (target / "VERSION").write_text("1.0.0\n")
    (target / "data" / "live").mkdir(parents=True)
    (target / "data" / "live" / "watchlists.json").write_text("{}")
    (target / "output" / "intel").mkdir(parents=True)
    (target / "output" / "intel" / "blackboard.sqlite").write_bytes(b"memory")
    monkeypatch.setattr(installer, "RECORD", tmp_path / "install.json")
    installer._record(target)
    assert installer.find_install() == target
    assert installer.installed_version(target) == "1.0.0"
    saved = installer.backup(target, "1.0.0")
    assert (saved / "output" / "intel" / "blackboard.sqlite").read_bytes() == b"memory"
    assert (saved / "data" / "live" / "watchlists.json").exists() and saved.parent == target / "backups"


def _payload(folder, version, settings):
    """A release as the build ships it: the installer next to payload.tar.gz and VERSION. The
    program is a stub that records how the updater called it."""
    import shutil
    import tarfile

    stage = folder / "stage"
    (stage / "_internal").mkdir(parents=True)
    (stage / "_internal" / "lib.txt").write_text(version)
    (stage / "INTVAL").write_text('#!/bin/sh\necho "$@" > called.txt\n')
    (stage / "VERSION").write_text(version + "\n")
    (stage / "agent_settings.yaml").write_text(settings)
    (stage / "data").mkdir()
    (stage / "data" / "companies.csv").write_text("company name,sector name,market cap,ticker\nShipped Ltd,IT,Large,SHIP.NS\n")
    (stage / "web" / "dist").mkdir(parents=True)
    (stage / "web" / "dist" / "index.html").write_text(version)
    with tarfile.open(folder / "payload.tar.gz", "w:gz") as tar:
        for p in sorted(stage.rglob("*")):
            tar.add(p, arcname=p.relative_to(stage).as_posix(), recursive=False)
    (folder / "VERSION").write_text(version)
    shutil.copy(ROOT / "packaging" / "linux" / "installer.py", folder / "installer.py")
    return folder / "installer.py"


def test_linux_install_then_update_keeps_every_bit_of_data(tmp_path):
    """The whole path a user takes: install 1.0, use it, run the 1.1 updater."""
    import os
    import subprocess

    env = {**os.environ, "HOME": str(tmp_path / "home"), "XDG_DATA_HOME": str(tmp_path / "home" / "share"),
           "XDG_CONFIG_HOME": str(tmp_path / "home" / "config"), "DISPLAY": "", "WAYLAND_DISPLAY": ""}
    target = tmp_path / "intval"
    old = _payload(tmp_path / "r1", "1.0.0", "run: {quick: false}\n")
    r = subprocess.run([sys.executable, str(old), "--silent", "--dir", str(target), "--no-desktop", "--no-menu"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (target / "INTVAL").exists() and (target / "uninstall.sh").exists()
    # the user works with it: their own settings, companies, watchlists, agent memory and keys
    (target / "agent_settings.yaml").write_text("run: {quick: true}   # mine\n")
    (target / "data" / "companies.csv").write_text("company name,sector name,market cap,ticker\nMy Pick,Banks,Small,MINE.NS\n")
    (target / "data" / "live").mkdir(parents=True)
    (target / "data" / "live" / "watchlists.json").write_text('{"lists": ["mine"]}')
    (target / "output" / "intel").mkdir(parents=True)
    (target / "output" / "intel" / "blackboard.sqlite").write_bytes(b"agent memory")
    (target / ".env").write_text("GROQ_API_KEY=secret\n")

    new = _payload(tmp_path / "r2", "1.1.0", "run: {quick: false, extra: 1}\n")
    r = subprocess.run([sys.executable, str(new), "--update", "--silent"], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "1.0.0" in r.stdout and "1.1.0" in r.stdout
    # the program is the new one ...
    assert (target / "VERSION").read_text().strip() == "1.1.0"
    assert (target / "_internal" / "lib.txt").read_text() == "1.1.0" and (target / "web" / "dist" / "index.html").read_text() == "1.1.0"
    # ... every bit of the user's data is untouched, and backed up first
    assert "# mine" in (target / "agent_settings.yaml").read_text()
    assert "MINE.NS" in (target / "data" / "companies.csv").read_text()
    assert (target / "data" / "live" / "watchlists.json").read_text() == '{"lists": ["mine"]}'
    assert (target / "output" / "intel" / "blackboard.sqlite").read_bytes() == b"agent memory"
    assert (target / ".env").read_text() == "GROQ_API_KEY=secret\n"
    backups = list((target / "backups").iterdir())
    assert len(backups) == 1 and "1.0.0-to-1.1.0" in backups[0].name
    assert (backups[0] / "output" / "intel" / "blackboard.sqlite").exists()
    # ... and the new program was asked to bring the data up to date
    assert (target / "called.txt").read_text().split() == ["--migrate", "--no-backup", "--previous-version", "1.0.0"]
