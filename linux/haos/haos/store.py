"""Transactional mission receipts, independent of Hermes and the desktop process."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .redaction import Redactor

ACTIVE = {"running", "waiting"}
TERMINAL = {"completed", "failed", "cancelled"}


class Conflict(ValueError):
    pass


class MissionStore:
    def __init__(self, path: Path, *, redactor: Redactor | None = None):
        self.redactor = redactor or Redactor()
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise RuntimeError(f"unsupported mission database version {version}")
        self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY, actor TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                goal TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued'
                    CHECK(state IN ('queued','running','waiting','blocked','failed','completed','cancelled')),
                phase TEXT NOT NULL DEFAULT 'pending', session_id TEXT, stored_session_id TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL, deadline REAL NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
                next_run REAL NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
                error TEXT, result TEXT, UNIQUE(actor, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT NOT NULL
                    REFERENCES missions(id), at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                receipt TEXT, UNIQUE(mission_id, receipt)
            );
            CREATE TABLE IF NOT EXISTS locks (
                resource TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id)
            );
            PRAGMA user_version=1;
            COMMIT;
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def get(self, mission_id: str) -> dict:
        row = self.db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            raise KeyError(mission_id)
        return dict(row)

    def list(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM missions ORDER BY created_at DESC LIMIT ?", (min(max(limit, 1), 200),))]

    def _event(self, mid: str, kind: str, payload: dict, receipt: str | None = None):
        self.db.execute("INSERT OR IGNORE INTO events(mission_id,at,kind,payload,receipt) VALUES(?,?,?,?,?)",
                        (mid, time.time(), kind, json.dumps(self.redactor.clean(payload), ensure_ascii=False), receipt))

    def events(self, mid: str, after: int = 0) -> list[dict]:
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in self.db.execute(
            "SELECT * FROM events WHERE mission_id=? AND seq>? ORDER BY seq LIMIT 200", (mid, after))]

    def create(self, actor: str, key: str, goal: str, *, timeout: int = 3600, max_attempts: int = 3) -> dict:
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 32000:
            raise ValueError("goal must contain 1–32000 characters")
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError("an idempotency key is required")
        if type(timeout) is not int or not 60 <= timeout <= 86400:
            raise ValueError("timeout must be 60–86400 seconds")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be 1–5")
        goal = self.redactor.text(goal.strip())
        with self.transaction():
            old = self.db.execute("SELECT * FROM missions WHERE actor=? AND idempotency_key=?", (actor, key)).fetchone()
            if old:
                if old["goal"] != goal:
                    raise Conflict("idempotency key already belongs to a different goal")
                return dict(old)
            now, mid = time.time(), str(uuid.uuid4())
            self.db.execute("""INSERT INTO missions(id,actor,idempotency_key,goal,created_at,updated_at,deadline,max_attempts)
                               VALUES(?,?,?,?,?,?,?,?)""", (mid, actor, key, goal, now, now, now + timeout, max_attempts))
            self._event(mid, "mission.queued", {"actor": actor})
        return self.get(mid)

    def claim(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        with self.transaction():
            expired = self.db.execute("SELECT id FROM missions WHERE state='queued' AND deadline<=?", (now,)).fetchall()
            for r in expired:
                self._settle(r["id"], "failed", "deadline expired before dispatch")
            # Hermes sessions share an execution home: serialize them until per-project isolation is available.
            if self.db.execute("SELECT 1 FROM locks WHERE resource='agent-home'").fetchone():
                return None
            row = self.db.execute("""SELECT * FROM missions WHERE state='queued' AND next_run<=?
                                     ORDER BY created_at LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            mid = row["id"]
            self.db.execute("INSERT INTO locks VALUES('agent-home',?)", (mid,))
            self.db.execute("UPDATE missions SET state='running',phase='connecting',attempt=attempt+1,updated_at=? WHERE id=?", (now, mid))
            self._event(mid, "mission.claimed", {"attempt": row["attempt"] + 1})
        return self.get(mid)

    def session(self, mid: str, runtime_id: str, stored_id: str):
        if not runtime_id or not stored_id:
            raise ValueError("Hermes did not return session identifiers")
        with self.transaction():
            self.db.execute("UPDATE missions SET session_id=?,stored_session_id=?,phase='session-created',updated_at=? WHERE id=?",
                            (runtime_id, stored_id, time.time(), mid))
            self._event(mid, "mission.session", {"session_id": runtime_id, "stored_session_id": stored_id})

    def dispatching(self, mid: str):
        # Written BEFORE sending: a crash after this point cannot prove that the prompt was not admitted.
        with self.transaction():
            if self.get(mid)["state"] != "running":
                raise Conflict("mission is no longer dispatchable")
            self.db.execute("UPDATE missions SET phase='dispatching',updated_at=? WHERE id=?", (time.time(), mid))
            self._event(mid, "mission.dispatching", {})

    def record(self, mid: str, event: dict, epoch: str | None):
        kind = event.get("type")
        if not isinstance(kind, str):
            raise ValueError("invalid Hermes event")
        receipt = f"{epoch}:{event['seq']}" if epoch and type(event.get("seq")) is int else None
        with self.transaction():
            self._event(mid, f"hermes.{kind}", event.get("payload") or {}, receipt)

    def waiting(self, mid: str, request: dict):
        with self.transaction():
            if self.get(mid)["state"] not in ACTIVE:
                raise Conflict("mission is not active")
            self.db.execute("UPDATE missions SET state='waiting',updated_at=? WHERE id=?", (time.time(), mid))
            self._event(mid, "mission.request", request)

    def answered(self, mid: str, actor: str, choice: str):
        with self.transaction():
            self.db.execute("UPDATE missions SET state='running',updated_at=? WHERE id=? AND state='waiting'", (time.time(), mid))
            self._event(mid, "mission.answer", {"actor": actor, "choice": choice})

    def request_cancel(self, mid: str, actor: str) -> dict:
        with self.transaction():
            row = self.get(mid)
            if row["state"] in TERMINAL:
                return row
            if row["state"] == "blocked":
                raise Conflict("blocked execution must be reconciled before releasing its lock")
            self.db.execute("UPDATE missions SET cancel_requested=1,updated_at=? WHERE id=?", (time.time(), mid))
            self._event(mid, "mission.cancel-requested", {"actor": actor})
            if row["state"] == "queued":
                self._settle(mid, "cancelled", None)
        return self.get(mid)

    def _settle(self, mid: str, state: str, error: str | None, result: str | None = None):
        error = self.redactor.clean(error)
        result = self.redactor.clean(result)
        self.db.execute("UPDATE missions SET state=?,error=?,result=?,updated_at=? WHERE id=?",
                        (state, error, result, time.time(), mid))
        if state in TERMINAL:
            self.db.execute("DELETE FROM locks WHERE mission_id=?", (mid,))
        self._event(mid, f"mission.{state}", {"error": error, "result": result})

    def settle(self, mid: str, state: str, *, error: str | None = None, result: str | None = None):
        if state not in TERMINAL | {"blocked"}:
            raise ValueError("invalid terminal state")
        with self.transaction():
            if self.get(mid)["state"] not in ACTIVE:
                raise Conflict("mission is not active")
            self._settle(mid, state, error, result)

    def unavailable(self, mid: str, error: str):
        error = self.redactor.text(error)
        with self.transaction():
            row = self.get(mid)
            if row["phase"] == "dispatching":
                self._settle(mid, "blocked", "execution outcome unknown: " + error)
            elif row["cancel_requested"]:
                self._settle(mid, "cancelled", None)
            elif row["attempt"] >= row["max_attempts"] or row["deadline"] <= time.time():
                self._settle(mid, "failed", error)
            else:
                delay = min(30, 2 ** row["attempt"])
                self.db.execute("UPDATE missions SET state='queued',phase='pending',error=?,next_run=?,updated_at=? WHERE id=?",
                                (error, time.time() + delay, time.time(), mid))
                self.db.execute("DELETE FROM locks WHERE mission_id=?", (mid,))
                self._event(mid, "mission.retry-scheduled", {"error": error, "delay": delay})

    def recover(self):
        with self.transaction():
            for row in self.db.execute("SELECT * FROM missions WHERE state IN ('running','waiting')").fetchall():
                if row["phase"] == "dispatching":
                    self._settle(row["id"], "blocked", "controller restarted; reconcile Hermes before resubmission")
                elif row["attempt"] >= row["max_attempts"] or row["deadline"] <= time.time():
                    self._settle(row["id"], "failed", "recovery retry budget or deadline exhausted before dispatch")
                else:
                    self.db.execute("UPDATE missions SET state='queued',phase='pending',updated_at=? WHERE id=?", (time.time(), row["id"]))
                    self.db.execute("DELETE FROM locks WHERE mission_id=?", (row["id"],))
                    self._event(row["id"], "mission.recovered-before-dispatch", {})

    def reconcile(self, mid: str, actor: str, note: str):
        """Owner-only, offline recovery after the owner has stopped/inspected the runtime."""
        if not note.strip():
            raise ValueError("a reconciliation receipt is required")
        with self.transaction():
            if self.get(mid)["state"] != "blocked":
                raise Conflict("only blocked missions can be reconciled")
            self._event(mid, "owner.reconciled", {"actor": actor, "note": note})
            self._settle(mid, "cancelled", "owner reconciled uncertain execution")
