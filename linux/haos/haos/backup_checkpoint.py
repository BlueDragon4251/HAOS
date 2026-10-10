"""Owner-only, bounded SQLite online checkpoint of the live mission ledger.

No WAL file copying, immutable=1, runtime interruption or live restore. Project
files and upstream session databases are deliberately outside this checkpoint.
"""
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from urllib.parse import quote

from .backup import private_directory
from .policy import atomic_json

LIMIT = 512 * 1024 * 1024
DEADLINE = 30


class MissionCheckpoint:
    def __init__(self, root: Path, source: Path, uid: int):
        if os.geteuid() != 0:
            raise PermissionError("live checkpoint requires owner/root authority")
        self.root, self.source, self.uid = root, source, uid

    def source_identity(self):
        if not self.source.is_absolute():
            raise PermissionError("absolute ledger source required")
        for parent in self.source.parents:
            info = parent.lstat()
            expected = self.uid if parent == self.source.parent else 0
            # Disposable tests may live below root's private /tmp directory.
            sticky_tmp = parent == Path('/tmp') and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != expected
                    or info.st_mode & 0o022 and not sticky_tmp
                    or parent == self.source.parent and info.st_mode & 0o077):
                raise PermissionError("untrusted ledger ancestor")
        info = self.source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > LIMIT:
            raise PermissionError("untrusted or oversized ledger")
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(self.source) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                meta = sidecar.lstat()
                if not stat.S_ISREG(meta.st_mode) or meta.st_uid != self.uid or meta.st_mode & 0o077 or meta.st_nlink != 1 or meta.st_size > LIMIT:
                    raise PermissionError("untrusted SQLite sidecar")
        return info.st_dev, info.st_ino

    def prepare(self):
        identity = self.source_identity()
        private_directory(self.root)
        fd, staging = tempfile.mkstemp(prefix='.checkpoint-', dir=self.root)
        os.close(fd)
        deadline = time.monotonic() + DEADLINE

        def progress(status, remaining, total):
            if time.monotonic() > deadline or total * page_size > LIMIT:
                raise TimeoutError("online ledger checkpoint budget exceeded")

        try:
            # Normal read-only WAL-aware connection, never immutable or a /proc/fd
            # alias that would hide the real database's committed WAL pages.
            with closing(sqlite3.connect('file:' + quote(str(self.source), safe='/') + '?mode=ro', uri=True, timeout=1)) as source:
                source.execute('PRAGMA trusted_schema=OFF')
                source.execute('PRAGMA query_only=ON')
                source.execute('PRAGMA cache_size=-16384')
                page_size = source.execute('PRAGMA page_size').fetchone()[0]
                if source.execute('PRAGMA user_version').fetchone()[0] != 1 or source.execute('PRAGMA page_count').fetchone()[0] * page_size > LIMIT:
                    raise ValueError("unsupported or oversized mission ledger")
                with closing(sqlite3.connect(staging)) as destination:
                    destination.execute('PRAGMA cache_size=-16384')
                    source.backup(destination, pages=128, progress=progress, sleep=0.01)
                    destination.execute('PRAGMA trusted_schema=OFF')
                    destination.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                    if destination.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or destination.execute('PRAGMA foreign_key_check').fetchall():
                        raise ValueError("checkpoint integrity failed")
                    # Restore/export must not need a copied live WAL/SHM sidecar.
                    destination.execute('PRAGMA journal_mode=DELETE')
                if self.source_identity() != identity or time.monotonic() > deadline:
                    raise PermissionError("ledger identity changed or checkpoint expired")
            path = Path(staging)
            if path.stat().st_size > LIMIT:
                raise ValueError("checkpoint exceeds storage budget")
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                os.fsync(stream.fileno())
            # A fixed root-private export path keeps Restic's scope/retention
            # grouping stable across runs; interrupted exports never claim success.
            path.replace(self.root / 'missions.db')
            atomic_json(self.root / 'checkpoint.json', {
                'version': 1, 'scope': 'mission-ledger', 'database_version': 1,
                'database_sha256': digest, 'consistency': 'sqlite-online-backup',
                'live_state_replaced': False, 'complete_system_backup': False,
            })
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return [self.root]
        finally:
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(staging + suffix).unlink(missing_ok=True)
