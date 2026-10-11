"""Durable outbox: commit locally before sending, acknowledge after server response."""

import hashlib
import json
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager


class Journal:
    def __init__(self, path: Path, scope: str):
        self.path = path
        self.scope = scope
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS shots (
                scope TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                source_time INTEGER NOT NULL, log_event INTEGER NOT NULL,
                confirmed REAL, PRIMARY KEY(scope, fingerprint))""")
            db.execute("CREATE INDEX IF NOT EXISTS pending_order ON shots(scope, confirmed, source_time, log_event)")
            db.execute("""CREATE TABLE IF NOT EXISTS invalid (
                scope TEXT NOT NULL, fingerprint TEXT NOT NULL, raw TEXT NOT NULL,
                PRIMARY KEY(scope, fingerprint))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def stage(self, shots, invalid):
        with self.connect() as db:
            for shot in shots:
                payload = json.dumps(shot, sort_keys=True, ensure_ascii=False, allow_nan=False)
                fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                db.execute("INSERT OR IGNORE INTO shots VALUES (?, ?, ?, ?, ?, NULL)",
                           (self.scope, fingerprint, payload, shot["ZeitSeitJahresbeginn"], shot["LogEvent"]))
            for raw in invalid:
                fingerprint = hashlib.sha256(raw.encode("latin-1")).hexdigest()
                db.execute("INSERT OR IGNORE INTO invalid VALUES (?, ?, ?)", (self.scope, fingerprint, raw))

    def pending(self, limit=500):
        with self.connect() as db:
            return db.execute("""SELECT fingerprint, payload FROM shots
                WHERE scope=? AND confirmed IS NULL ORDER BY source_time, log_event, rowid LIMIT ?""",
                              (self.scope, limit)).fetchall()

    def acknowledge(self, fingerprints):
        with self.connect() as db:
            db.executemany("UPDATE shots SET confirmed=? WHERE scope=? AND fingerprint=?",
                           [(time.time(), self.scope, key) for key in fingerprints])

    def replay(self):
        with self.connect() as db:
            db.execute("UPDATE shots SET confirmed=NULL WHERE scope=?", (self.scope,))

    def stats(self):
        with self.connect() as db:
            total, confirmed, last = db.execute("SELECT COUNT(*), COUNT(confirmed), MAX(confirmed) FROM shots WHERE scope=?", (self.scope,)).fetchone()
            invalid = db.execute("SELECT COUNT(*) FROM invalid WHERE scope=?", (self.scope,)).fetchone()[0]
            recent = db.execute("SELECT payload FROM shots WHERE scope=? AND confirmed IS NOT NULL ORDER BY source_time DESC, log_event DESC, rowid DESC LIMIT 100", (self.scope,)).fetchall()
        return {"queued": total - confirmed, "shots": confirmed, "invalid": invalid,
                "confirmed_at": last, "recent": [json.loads(row[0]) for row in reversed(recent)]}
