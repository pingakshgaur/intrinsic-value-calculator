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
