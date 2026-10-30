"""Private SQLite snapshots shared by Photon diagnostics and recovery preflight."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat

ORIGINAL_COLUMNS = ('id', 'connector', 'account_scope', 'message_id', 'credential_scope', 'binding_id', 'binding_digest',
    'semantic_sha256', 'raw', 'raw_sha256', 'proof', 'normalized', 'normalized_sha256', 'parts', 'admitted_receipt', 'created_at')


@contextmanager
def readonly(path):
    from .gateway_line_profile import _directory
    path = Path(path); _directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        def private(item):
            if (not stat.S_ISREG(item.st_mode) or item.st_uid != os.geteuid() or item.st_gid != os.getegid()
                    or item.st_nlink != 1 or item.st_mode & 0o077):
                raise PermissionError('private Photon journal and sidecars required')
        before = os.fstat(descriptor); private(before)
        if path.resolve() != path: raise PermissionError('canonical private Photon journal required')
        for suffix in ['-wal', '-shm']:
            try: private(path.with_name(path.name + suffix).lstat())
            except FileNotFoundError: pass
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2, isolation_level=None)
        try:
            after = path.lstat(); private(after)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise PermissionError('Photon journal replaced while opening')
            db.row_factory = sqlite3.Row; db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            yield db
            db.execute('COMMIT')
        finally: db.close()
    finally: os.close(descriptor)
