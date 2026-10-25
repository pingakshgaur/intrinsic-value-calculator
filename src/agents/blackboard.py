"""
The blackboard: one SQLite file every agent writes to and reads from.

Why SQLite: it is a single file, ships with Python, and can be committed to a
git branch, which is how the cloud workflow keeps history between runs on
machines that are thrown away after every job.

Tables
    runs         one row per run (mode, start/end, counts)
    findings     every analyst finding, JSON payload
    verdicts     the chief's verdict per company per run, JSON payload
    seen         content hashes of news/filings already reported (for "new")
    llm_cache    prompt hash -> reply, so repeated prompts cost nothing
    llm_usage    calls and tokens per provider per day (free-tier pacing)
"""

import datetime as dt
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT, finished TEXT, mode TEXT, companies INTEGER, llm_calls INTEGER,
    note TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    run_id INTEGER, company TEXT, agent TEXT, lead TEXT, score REAL,
    confidence REAL, status TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_findings ON findings(company, agent, run_id);
CREATE TABLE IF NOT EXISTS verdicts (
    run_id INTEGER, company TEXT, ticker TEXT, created TEXT, label TEXT,
    expected_value REAL, price REAL, confidence REAL, payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_verdicts ON verdicts(company, run_id);
CREATE TABLE IF NOT EXISTS seen (
    hash TEXT PRIMARY KEY, company TEXT, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY, reply TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS llm_usage (
    day TEXT, provider TEXT, calls INTEGER, tokens INTEGER,
    PRIMARY KEY (day, provider)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mid TEXT, run_id INTEGER, ts REAL,
    channel TEXT, sender TEXT, recipient TEXT, company TEXT, kind TEXT,
    text TEXT, data TEXT, refs TEXT
);
CREATE INDEX IF NOT EXISTS ix_messages_run ON messages(run_id, id);
CREATE INDEX IF NOT EXISTS ix_messages_channel ON messages(channel, id);
CREATE TABLE IF NOT EXISTS agent_status (
    run_id INTEGER, agent TEXT, payload TEXT, ts REAL, PRIMARY KEY (run_id, agent)
);
CREATE TABLE IF NOT EXISTS run_progress (
    run_id INTEGER PRIMARY KEY, payload TEXT, ts REAL
);
"""


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


class Blackboard:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        # WAL: the web app reads agent messages live while a run writes them
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        with self._lock:
            self.db.commit()
            self.db.close()

    # ---------------------------------------------------------------- runs
    def start_run(self, mode, companies):
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO runs (started, mode, companies, llm_calls) VALUES (?,?,?,0)",
                (_now(), mode, companies),
            )
            self.db.commit()
            return cur.lastrowid

    def finish_run(self, run_id, llm_calls, note=""):
        with self._lock:
            self.db.execute(
                "UPDATE runs SET finished=?, llm_calls=?, note=? WHERE id=?",
                (_now(), llm_calls, note, run_id),
            )
            self.db.commit()

    # ------------------------------------------------------------ comms
    def save_comms(self, run_id, messages, status, progress):
        """One transaction for a batch of agent messages and status changes."""
        with self._lock:
            if messages:
                self.db.executemany(
                    "INSERT INTO messages (mid, run_id, ts, channel, sender, recipient, company, kind, text, data, refs) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", messages)
            now = time.time()
            for agent, s in (status or {}).items():
                self.db.execute("INSERT OR REPLACE INTO agent_status VALUES (?,?,?,?)",
                                (run_id, agent, json.dumps(s, default=str), now))
            if progress is not None:
                self.db.execute("INSERT OR REPLACE INTO run_progress VALUES (?,?,?)",
                                (run_id, json.dumps(progress, default=str), now))
            self.db.commit()

    # ------------------------------------------------------------ findings
    def save_finding(self, run_id, f):
        with self._lock:
            self.db.execute(
                "INSERT INTO findings VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    f.company,
                    f.agent,
                    f.lead,
                    f.score,
                    f.confidence,
                    f.status,
                    json.dumps(f.to_dict(), default=str),
                ),
            )
            self.db.commit()

    def last_findings(self, company, agents=None):
        """Most recent finding per agent for a company (used by --quick)."""
        q = (
            "SELECT agent, payload FROM findings WHERE company=? AND status='ok' "
            "ORDER BY run_id DESC"
        )
        out = {}
        with self._lock:
            for agent, payload in self.db.execute(q, (company,)):
                if agent in out or (agents and agent not in agents):
                    continue
                out[agent] = json.loads(payload)
        return out

    # ------------------------------------------------------------ verdicts
    def save_verdict(self, run_id, v):
        with self._lock:
            self.db.execute(
                "INSERT INTO verdicts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    v["company"],
                    v.get("ticker", ""),
                    _now(),
                    v.get("label", ""),
                    v.get("expected_value"),
                    v.get("price"),
                    v.get("confidence"),
                    json.dumps(v, default=str),
                ),
            )
            self.db.commit()

    def previous_verdict(self, company, before_run):
        with self._lock:
            row = self.db.execute(
                "SELECT payload FROM verdicts WHERE company=? AND run_id<? "
                "ORDER BY run_id DESC LIMIT 1",
                (company, before_run),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def history(self, company, limit=30):
        with self._lock:
            rows = self.db.execute(
                "SELECT created, label, expected_value, price, confidence FROM verdicts "
                "WHERE company=? ORDER BY run_id DESC LIMIT ?",
                (company, limit),
            ).fetchall()
        return [
            {"date": r[0], "label": r[1], "value": r[2], "price": r[3], "confidence": r[4]}
            for r in reversed(rows)
        ]

    # ---------------------------------------------------------------- seen
    def is_new(self, h, company):
        """True the first time a content hash is offered; records it."""
        with self._lock:
            row = self.db.execute("SELECT 1 FROM seen WHERE hash=?", (h,)).fetchone()
            if row:
                return False
            self.db.execute("INSERT INTO seen VALUES (?,?,?)", (h, company, _now()))
            self.db.commit()
            return True

    # ----------------------------------------------------------- LLM cache
    def cache_get(self, key, max_age_hours):
        with self._lock:
            row = self.db.execute(
                "SELECT reply, created FROM llm_cache WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return None
        try:
            age = dt.datetime.now() - dt.datetime.fromisoformat(row[1])
        except ValueError:
            return None
        if age.total_seconds() > max_age_hours * 3600:
            return None
        return row[0]

    def cache_put(self, key, reply):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)", (key, reply, _now())
            )
            self.db.commit()

    def usage_today(self, provider):
        day = dt.date.today().isoformat()
        with self._lock:
            row = self.db.execute(
                "SELECT calls, tokens FROM llm_usage WHERE day=? AND provider=?",
                (day, provider),
            ).fetchone()
        return row if row else (0, 0)

    def add_usage(self, provider, tokens):
        day = dt.date.today().isoformat()
        with self._lock:
            self.db.execute(
                "INSERT INTO llm_usage VALUES (?,?,1,?) ON CONFLICT(day, provider) "
                "DO UPDATE SET calls=calls+1, tokens=tokens+excluded.tokens",
                (day, provider, int(tokens or 0)),
            )
            self.db.commit()

    def prune(self, keep_days=120):
        """Keep the file small enough to commit: drop old cache and findings."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=keep_days)).isoformat()
        with self._lock:
            self.db.execute("DELETE FROM llm_cache WHERE created<?", (cutoff,))
            self.db.execute("DELETE FROM seen WHERE first_seen<?", (cutoff,))
            old = self.db.execute(
                "SELECT id FROM runs WHERE started<? ORDER BY id DESC LIMIT 1", (cutoff,)
            ).fetchone()
            if old:
                self.db.execute("DELETE FROM findings WHERE run_id<=?", (old[0],))
            # agent chat: the last 30 runs; the feed trace (fetch/share) only the last 5
            last = self.db.execute("SELECT MAX(id) FROM runs").fetchone()[0] or 0
            self.db.execute("DELETE FROM messages WHERE run_id<=? AND run_id>0", (last - 30,))
            self.db.execute("DELETE FROM messages WHERE run_id<=? AND channel='trace'", (last - 5,))
            self.db.execute("DELETE FROM agent_status WHERE run_id<=?", (last - 30,))
            self.db.commit()
            self.db.execute("VACUUM")
