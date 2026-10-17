"""Root-configured local encrypted scheduling; never interrupts live missions.

An interrupted modifying attempt blocks until owner inspection. No automatic
restore, secret initialization, arbitrary destinations or runtime stop/start.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
import uuid
from contextlib import contextmanager

from .backup import Repository, Retention, owner_sources, private_directory, private_password, SNAPSHOT
from .policy import atomic_json
from .sandbox import trusted_json

INTERVALS = {"off": None, "daily": 86400, "weekly": 604800}
COUNTS = {"keep_last", "keep_daily", "keep_weekly", "keep_monthly"}
SCOPES = {"system", "mission-ledger"}


def policy(value):
    if (not isinstance(value, dict) or set(value) not in ({"version", "interval", "prune", "retention"}, {"version", "interval", "prune", "retention", "scope"})
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["interval"], str) or value["interval"] not in INTERVALS
            or type(value["prune"]) is not bool
            or not isinstance(value["retention"], dict) or set(value["retention"]) != COUNTS
            or not isinstance(value.get("scope", "system"), str) or value.get("scope", "system") not in SCOPES):
        raise ValueError("invalid owner backup schedule")
    Retention(**value["retention"]).arguments()
    return value


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid schedule timestamp")
    return value


class Scheduler:
    def __init__(self, root, configuration, repository, sources, check_stopped, audit, *, live_sources=None):
        if os.geteuid() != 0:
            raise PermissionError("backup scheduling requires owner/root authority")
        self.root, self.configuration, self.repository = root, configuration, repository
        self.sources, self.check_stopped, self.audit = sources, check_stopped, audit
        self.live_sources = live_sources
        private_directory(root)

    @contextmanager
    def lock(self):
        fd = os.open(self.root / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077 or metadata.st_nlink != 1:
                raise PermissionError("untrusted scheduler lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def state(self):
        path = self.root / "state.json"
        if not path.exists() and not path.is_symlink():
            return {"version": 1, "last_success": None, "phase": "idle", "attempt": None, "snapshot_id": None}
        value = trusted_json(path)
        if (set(value) != {"version", "last_success", "phase", "attempt", "snapshot_id"}
                or type(value["version"]) is not int or value["version"] != 1
                or value["phase"] not in {"idle", "running", "blocked"}):
            raise ValueError("invalid scheduler state")
        if value["last_success"] is not None:
            timestamp(value["last_success"])
        if value["attempt"] is not None and str(uuid.UUID(value["attempt"])) != value["attempt"]:
            raise ValueError("invalid schedule attempt")
        if value["snapshot_id"] is not None and not SNAPSHOT.fullmatch(value["snapshot_id"]):
            raise ValueError("invalid schedule snapshot")
        if value["phase"] in {"running", "blocked"} and not value["attempt"]:
            raise ValueError("missing modifying attempt")
        return value

    def configuration_value(self):
        if not self.configuration.exists() and not self.configuration.is_symlink():
            return {"version": 1, "interval": "off", "prune": False, "retention": Retention().__dict__}
        return policy(trusted_json(self.configuration))

    def configure(self, value):
        policy(value)
        with self.lock():
            if value.get('scope', 'system') == 'mission-ledger' and not callable(self.live_sources):
                raise PermissionError('online checkpoint capability unavailable')
            changed_scope = value.get('scope', 'system') != self.configuration_value().get('scope', 'system')
            state = self.state()
            if changed_scope and state['phase'] != 'idle':
                raise PermissionError('inspect interrupted attempt before changing backup scope')
            if value["interval"] != "off":
                # Timer setup must not silently initialize a new/missing key.
                private_password(self.repository.password)
                if not (self.repository.repository / "config").is_file():
                    raise PermissionError("initialize the encrypted owner repository first")
            self.configuration.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            parent = self.configuration.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
                raise PermissionError("untrusted schedule configuration directory")
            atomic_json(self.configuration, value)
            if changed_scope:
                atomic_json(self.root / 'state.json', {**state, 'last_success': None, 'snapshot_id': None})
            self.audit("backup.schedule-configured", value)
        return value

    def status(self, now=None):
        now = timestamp(time.time() if now is None else now)
        value, state = self.configuration_value(), self.state()
        interval = INTERVALS[value["interval"]]
        due = interval is not None and (state["last_success"] is None or now - state["last_success"] >= interval)
        return {"configuration": value, **state, "due": due,
                "clock_behind_last_success": state["last_success"] is not None and now < state["last_success"]}

    def clear(self, note, confirmed):
        if confirmed is not True or not isinstance(note, str) or not 1 <= len(note.encode()) <= 4096:
            raise PermissionError("inspect the repository and explicitly confirm before clearing")
        with self.lock():
            self.check_stopped()
            state = self.state()
            if state["phase"] not in {"running", "blocked"}:
                raise ValueError("no interrupted schedule attempt")
            self.audit("backup.schedule-cleared", {"attempt": state["attempt"], "snapshot_id": state["snapshot_id"],
                       "inspection_sha256": hashlib.sha256(note.encode()).hexdigest()})
            state.update(phase="idle", attempt=None)
            atomic_json(self.root / "state.json", state)
        return {"cleared": True, "snapshots_deleted": False}

    def tick(self, now=None):
        now = timestamp(time.time() if now is None else now)
        with self.lock():
            status = self.status(now)
            state = {key: status[key] for key in ("version", "last_success", "phase", "attempt", "snapshot_id")}
            if state["phase"] == "running":
                state["phase"] = "blocked"
                atomic_json(self.root / "state.json", state)
                self.audit("backup.schedule-interrupted", {"attempt": state["attempt"], "snapshot_id": state["snapshot_id"]})
            if state["phase"] == "blocked":
                return {"phase": "blocked", "requires_owner_inspection": True}
            if not status["due"]:
                return {"phase": "not-due"}
            live = status['configuration'].get('scope', 'system') == 'mission-ledger'
            if not live:
                try:
                    self.check_stopped()
                except PermissionError:
                    return {"phase": "deferred", "reason": "execution-not-stopped"}
            # These read-only checks precede durable modifying intent. An unavailable
            # medium/key is retried later without claiming a snapshot was produced.
            try:
                private_password(self.repository.password)
                if not (self.repository.repository / "config").is_file():
                    raise PermissionError("missing initialized repository")
                self.repository.command("check", "--read-data")
            except Exception:
                return {"phase": "unavailable", "reason": "repository-or-key"}
            if not live:
                try:
                    self.check_stopped()
                except PermissionError:
                    return {"phase": "deferred", "reason": "execution-not-stopped"}
            state.update(phase="running", attempt=str(uuid.uuid4()), snapshot_id=None)
            atomic_json(self.root / "state.json", state)
            try:
                if live and not callable(self.live_sources):
                    raise PermissionError('online checkpoint capability unavailable')
                created = self.repository.create(self.live_sources() if live else self.sources())
                state["snapshot_id"] = created["snapshot_id"]
                atomic_json(self.root / "state.json", state)
                value = status["configuration"]
                retained = self.repository.retain(Retention(**value["retention"]), apply=value["prune"])
                completed = {**state, "phase": "idle", "last_success": now, "attempt": None}
                atomic_json(self.root / "state.json", completed)
            except Exception:
                state["phase"] = "blocked"
                atomic_json(self.root / "state.json", state)
                self.audit("backup.schedule-blocked", {"attempt": state["attempt"], "snapshot_id": state["snapshot_id"],
                           "repository_may_have_changed": True})
                return {"phase": "blocked", "requires_owner_inspection": True}
            result = {"phase": "succeeded", "snapshot_id": created["snapshot_id"], "retention_applied": not retained["dry_run"], 'scope': status['configuration'].get('scope', 'system')}
            self.audit("backup.schedule-succeeded", result)
            return result


def installed_scheduler():
    import pwd
    from .backup_checkpoint import MissionCheckpoint
    from .owner import stopped, audit
    root = Path("/var/lib/haos-owner")
    private_directory(root)
    repository = Repository(root / "backup", Path("/etc/haos/backup-password"))
    checkpoint = MissionCheckpoint(root / 'live-mission-checkpoint', Path('/var/lib/haos-control/missions.db'), pwd.getpwnam('haos-control').pw_uid)
    return Scheduler(root / "backup-scheduler", Path("/etc/haos/backup-schedule.json"), repository, owner_sources, stopped, audit, live_sources=checkpoint.prepare)


def main():
    # Logs are fixed scalar receipts, never Restic output, source files or keys.
    try:
        result = installed_scheduler().tick()
    except Exception:
        result = {"phase": "unavailable", "reason": "scheduler-or-runtime"}
    print(json.dumps(result), flush=True)
    if result["phase"] in {"unavailable", "blocked"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
