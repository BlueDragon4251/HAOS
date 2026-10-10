"""Durable transport-side admission while the mission controller is unavailable."""

import json
import sqlite3
import time
from pathlib import Path

from .gateway import Conflict, digest
from .redaction import Redactor


class RelayInbox:
    def __init__(self, path: Path, redactor: Redactor):
        self.redactor = redactor
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        if self.db.execute("PRAGMA user_version").fetchone()[0] not in {0, 1}:
            self.db.close()
            raise RuntimeError("unsupported gateway relay database")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS inbox (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, connector TEXT NOT NULL,
            binding_id TEXT NOT NULL, binding_digest TEXT NOT NULL, envelope TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempt INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, next_attempt REAL NOT NULL DEFAULT 0, mission_id TEXT
        ); PRAGMA user_version=1;""")

    def close(self):
        self.db.close()

    def admit(self, policy, connector, envelope):
        binding = policy.authorize(connector, envelope)
        if not isinstance(envelope["text"], str) or not 1 <= len(envelope["text"].strip()) <= 32000:
            raise ValueError("transport text must contain 1–32000 characters")
        key = digest([connector, envelope["scope"], envelope["chat"], envelope["thread"], envelope["message_id"]])
        fingerprint = digest(envelope)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT fingerprint FROM inbox WHERE id=?", (key,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise Conflict("transport replay changed content")
            else:
                if self.db.execute("SELECT COUNT(*) FROM inbox WHERE state='pending'").fetchone()[0] >= 4096:
                    raise Conflict("transport admission queue is full")
                sanitized = {**envelope, "text": self.redactor.text(envelope["text"])}
                self.db.execute("""INSERT INTO inbox
                    (id,fingerprint,connector,binding_id,binding_digest,envelope,created_at) VALUES(?,?,?,?,?,?,?)""",
                    (key, fingerprint, connector, binding["id"], digest(binding), json.dumps(sanitized), time.time()))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return key

    def next(self, policy, now=None):
        now = time.time() if now is None else now
        for row in self.db.execute("SELECT * FROM inbox WHERE state='pending' AND next_attempt<=? ORDER BY created_at LIMIT 100", (now,)).fetchall():
            item = dict(row)
            try:
                policy.current_binding(item)
            except PermissionError:
                self.db.execute("UPDATE inbox SET state='revoked' WHERE id=?", (item["id"],))
                continue
            if item["created_at"] + 86400 <= now:
                self.db.execute("UPDATE inbox SET state='expired' WHERE id=?", (item["id"],))
                continue
            item["envelope"] = json.loads(item["envelope"])
            return item
        return None

    def retry(self, key):
        attempt = self.db.execute("SELECT attempt FROM inbox WHERE id=?", (key,)).fetchone()[0] + 1
        self.db.execute("UPDATE inbox SET attempt=?,next_attempt=? WHERE id=? AND state='pending'",
                        (attempt, time.time() + min(60, 2 ** min(attempt, 6)), key))

    def admitted(self, key, mission_id):
        self.db.execute("UPDATE inbox SET state='admitted',mission_id=? WHERE id=? AND state='pending'", (mission_id, key))

    def denied(self, key):
        self.db.execute("UPDATE inbox SET state='denied' WHERE id=? AND state='pending'", (key,))
