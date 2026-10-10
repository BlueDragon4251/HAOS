"""Actual WAL-aware online backups and encrypted restore in disposable fixtures."""
from contextlib import closing
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.backup import Repository
from haos.backup_checkpoint import MissionCheckpoint
from haos.backup_schedule import Scheduler
from haos.store import MissionStore
from haos.policy import atomic_json
import uuid


@pytest.fixture
def fixture(tmp_path):
    assert os.geteuid() == 0, 'root authority in disposable fixtures only'
    previous = os.umask(0o077)
    source = tmp_path / 'control'
    source.mkdir(mode=0o700)
    store = MissionStore(source / 'missions.db')
    mission = store.create('fixture', 'live-writes', 'Private ongoing fixture')
    store.claim()
    store.session(mission['id'], 'offline-runtime-fixture', 'offline-stored-fixture')
    store.dispatching(mission['id'])
    checkpoint = MissionCheckpoint(tmp_path / 'checkpoint', source / 'missions.db', 0)
    try:
        yield store, checkpoint, mission['id']
    finally:
        store.close()
        os.umask(previous)


def read_export(checkpoint):
    with closing(sqlite3.connect(checkpoint.root / 'missions.db')) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        return db.execute('SELECT COUNT(*) FROM events').fetchone()[0]


def test_committed_wal_is_included_without_copying_live_sidecars(fixture):
    store, checkpoint, mid = fixture
    store._event(mid, 'fixture.live-committed', {'private': 'Fixture WAL canary'})
    assert Path(str(checkpoint.source) + '-wal').stat().st_size > 0
    assert checkpoint.prepare() == [checkpoint.root]
    with closing(sqlite3.connect(checkpoint.root / 'missions.db')) as db:
        assert db.execute('SELECT payload FROM events WHERE kind=?', ('fixture.live-committed',)).fetchone()
        assert db.execute('SELECT state FROM missions WHERE id=?', (mid,)).fetchone()[0] == 'running'
    assert not Path(str(checkpoint.root / 'missions.db') + '-wal').exists()
    metadata = json.loads((checkpoint.root / 'checkpoint.json').read_text())
    assert metadata['database_sha256'] == hashlib.sha256((checkpoint.root / 'missions.db').read_bytes()).hexdigest()
    assert not metadata['complete_system_backup'] and not metadata['live_state_replaced']
    assert (checkpoint.root / 'missions.db').stat().st_mode & 0o777 == 0o600


def write_continuously(source, mid, stop, started):
    # A separate real process/connection commits pairs atomically in the WAL.
    os.umask(0o077)
    with closing(sqlite3.connect(source, isolation_level=None)) as db:
        while not stop.is_set():
            db.execute('BEGIN IMMEDIATE')
            for _ in range(2):
                db.execute('INSERT INTO events(mission_id,at,kind,payload) VALUES(?,?,?,?)', (mid, time.time(), 'fixture.pair', '{}'))
            db.execute('COMMIT')
            started.set()
            time.sleep(0.002)


def test_live_schedule_and_encrypted_restore_do_not_interrupt_real_writer(fixture, tmp_path):
    store, checkpoint, mid = fixture
    context = multiprocessing.get_context('spawn')
    stop, started = context.Event(), context.Event()
    writer = context.Process(target=write_continuously, args=(str(checkpoint.source), mid, stop, started))
    writer.start()
    try:
        assert started.wait(10)
        repository = Repository(tmp_path / 'encrypted', tmp_path / 'password')
        repository.initialize()
        def busy():
            raise PermissionError('execution remains active')
        audit = []
        scheduler = Scheduler(tmp_path / 'scheduler', tmp_path / 'config/policy.json', repository,
                              lambda: pytest.fail('live scope must not copy arbitrary changing files'), busy,
                              lambda kind, data: audit.append({'kind': kind, **data}), live_sources=checkpoint.prepare)
        scheduler.configure({'version': 1, 'interval': 'daily', 'scope': 'mission-ledger', 'prune': False,
                             'retention': {'keep_last': 1, 'keep_daily': 0, 'keep_weekly': 0, 'keep_monthly': 0}})
        before = store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        receipt = scheduler.tick(1000)
        assert receipt['phase'] == 'succeeded' and receipt['scope'] == 'mission-ledger'
        assert writer.is_alive() and store.get(mid)['state'] == 'running'
        assert store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] > before
        restored = Path(repository.restore(receipt['snapshot_id'])['staging_directory']) / checkpoint.root.relative_to('/')
        with closing(sqlite3.connect(restored / 'missions.db')) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            count = db.execute("SELECT COUNT(*) FROM events WHERE kind='fixture.pair'").fetchone()[0]
            assert count > 0 and count % 2 == 0
        assert 'Private ongoing fixture' not in json.dumps(audit)
        recovered = MissionStore(restored / 'missions.db')
        try:
            recovered.recover()
            assert recovered.get(mid)['state'] == 'blocked'
            assert recovered.claim() is None
        finally:
            recovered.close()
        assert scheduler.tick(1001)['phase'] == 'not-due'
        assert writer.is_alive()
    finally:
        stop.set(); writer.join(10)
        if writer.is_alive():
            writer.kill(); writer.join(5)
        assert writer.exitcode == 0


@pytest.mark.parametrize('attack', ['source-symlink', 'source-hardlink', 'sidecar-symlink', 'directory-mode', 'version'])
def test_untrusted_ledger_sources_are_not_exported(fixture, attack):
    store, checkpoint, _ = fixture
    store.close()
    if attack == 'source-symlink':
        original = checkpoint.source.with_name('original.db')
        checkpoint.source.rename(original); checkpoint.source.symlink_to(original)
    elif attack == 'source-hardlink':
        os.link(checkpoint.source, checkpoint.source.with_name('link.db'))
    elif attack == 'sidecar-symlink':
        Path(str(checkpoint.source) + '-wal').symlink_to(checkpoint.source)
    elif attack == 'directory-mode':
        checkpoint.source.parent.chmod(0o777)
    else:
        with closing(sqlite3.connect(checkpoint.source)) as db:
            db.execute('PRAGMA user_version=999')
    with pytest.raises((PermissionError, ValueError)):
        checkpoint.prepare()
    assert not (checkpoint.root / 'missions.db').exists()


def test_failed_checkpoint_preserves_previous_complete_export(fixture, monkeypatch):
    store, checkpoint, mid = fixture
    checkpoint.prepare()
    before = (checkpoint.root / 'missions.db').read_bytes()
    store._event(mid, 'new-real-event', {})
    monkeypatch.setattr('haos.backup_checkpoint.DEADLINE', -1)
    with pytest.raises((TimeoutError, PermissionError, sqlite3.Error)):
        checkpoint.prepare()
    assert (checkpoint.root / 'missions.db').read_bytes() == before
    assert not list(checkpoint.root.glob('.checkpoint-*'))
    read_export(checkpoint)


def test_actual_read_only_mount_still_reads_committed_wal(fixture):
    store, checkpoint, mid = fixture
    mount = checkpoint.source.parent.with_name('read-only-ledger')
    mount.mkdir(mode=0o700)
    subprocess.run(['mount', '--bind', str(checkpoint.source.parent), str(mount)], check=True, capture_output=True)
    try:
        subprocess.run(['mount', '-o', 'remount,bind,ro', str(mount)], check=True, capture_output=True)
        with pytest.raises(OSError):
            fd = os.open(mount / 'missions.db', os.O_RDWR)
            os.close(fd)
        store._event(mid, 'fixture.read-only-wal', {})
        readonly = MissionCheckpoint(checkpoint.root, mount / 'missions.db', 0)
        readonly.prepare()
        with closing(sqlite3.connect(checkpoint.root / 'missions.db')) as db:
            assert db.execute("SELECT COUNT(*) FROM events WHERE kind='fixture.read-only-wal'").fetchone()[0] == 1
    finally:
        # SQLite's same-process VFS may retain a read-only descriptor while the
        # other connection to that inode is open. Production's scheduler and
        # writer are separate processes; close our fixture before unmounting.
        store.close()
        subprocess.run(['umount', str(mount)], check=True, capture_output=True)


def test_scope_change_cannot_inherit_success_or_clear_interrupted_intent(fixture, tmp_path):
    _, checkpoint, _ = fixture
    repository = Repository(tmp_path / 'encrypted', tmp_path / 'password')
    repository.initialize()
    def busy():
        raise PermissionError('live runtime')
    scheduler = Scheduler(tmp_path / 'scheduler', tmp_path / 'config/policy.json', repository,
                          lambda: [checkpoint.source.parent], busy, lambda *_: None, live_sources=checkpoint.prepare)
    policy = {'version': 1, 'interval': 'daily', 'scope': 'mission-ledger', 'prune': False,
              'retention': {'keep_last': 1, 'keep_daily': 0, 'keep_weekly': 0, 'keep_monthly': 0}}
    scheduler.configure(policy)
    snapshot = scheduler.tick(1000)['snapshot_id']
    scheduler.configure({**policy, 'scope': 'system'})
    assert scheduler.status(1001)['last_success'] is None and scheduler.status(1001)['due']
    assert scheduler.tick(1001)['phase'] == 'deferred'
    assert repository.snapshots()['snapshot_ids'] == [snapshot]
    state = scheduler.state()
    atomic_json(scheduler.root / 'state.json', {**state, 'phase': 'blocked', 'attempt': str(uuid.uuid4())})
    with pytest.raises(PermissionError):
        scheduler.configure(policy)
    assert scheduler.status(1002)['phase'] == 'blocked'


def test_policy_alone_cannot_create_unavailable_online_capability(tmp_path):
    assert os.geteuid() == 0
    scheduler = Scheduler(tmp_path / 'scheduler', tmp_path / 'config/policy.json', None, None, None, None)
    with pytest.raises(PermissionError):
        scheduler.configure({'version': 1, 'interval': 'daily', 'scope': 'mission-ledger', 'prune': False,
                             'retention': {'keep_last': 1, 'keep_daily': 0, 'keep_weekly': 0, 'keep_monthly': 0}})
    assert not scheduler.configuration.exists()
