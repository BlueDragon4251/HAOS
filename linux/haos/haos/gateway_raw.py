"""Bounded private native ingress journal, committed before protocol acknowledgement."""
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time

from .gateway import digest, Conflict


class NativeInbox:
    def __init__(self, path, redactor):
        path = Path(path)
        parent = path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or parent.st_mode & 0o077):
            raise PermissionError('native ingress directory must be private to its service')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                raise PermissionError('native ingress journal must be private and owned by its service')
        finally:
            os.close(fd)
        for sidecar in (path.with_name(path.name + '-wal'), path.with_name(path.name + '-shm')):
            try:
                info = sidecar.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                raise PermissionError('untrusted native ingress journal sidecar')
        self.redactor = redactor
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA journal_size_limit=8388608')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0, 1}:
            self.db.close(); raise ValueError('unsupported native ingress journal')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS native_inbox (
            id TEXT PRIMARY KEY, connector TEXT NOT NULL, platform TEXT NOT NULL,
            message_id TEXT NOT NULL, binding_id TEXT NOT NULL, binding_digest TEXT NOT NULL,
            fingerprint TEXT NOT NULL, envelope TEXT NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempt INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, next_attempt REAL NOT NULL DEFAULT 0
        ); PRAGMA user_version=1;''')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS discord_native_id ON native_inbox(connector,message_id) WHERE platform='discord'")
        # A new daemon owns all processing. A crashed decoder cannot consume its
        # pending input merely by having started a volatile native callback.
        self.db.execute("UPDATE native_inbox SET state='pending' WHERE state='processing'")

    def close(self):
        self.db.close()

    @staticmethod
    def key(connector, envelope):
        return digest([connector, *(envelope[key] for key in ('platform','scope','chat','thread','message_id'))])

    def admit(self, policy, connector, envelope, payload, *, received_at=None):
        binding = policy.authorize(connector, envelope)
        now = time.time()
        received_at = now if received_at is None else received_at
        if (type(received_at) not in {int,float} or not 0 < received_at <= now+300
                or not math.isfinite(received_at)):
            raise ValueError('invalid original native input time')
        if not isinstance(payload, dict):
            raise ValueError('native payload must be an object')
        if not isinstance(envelope['text'], str) or not 1 <= len(envelope['text'].strip()) <= 32000:
            raise ValueError('native ingress requires bounded text')
        serialized = json.dumps(self.redactor.clean(payload), ensure_ascii=False, allow_nan=False)
        if len(serialized.encode()) > 65536:
            raise ValueError('native payload exceeds its bound')
        key, fingerprint = self.key(connector, envelope), digest(envelope)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT * FROM native_inbox WHERE id=?', (key,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint or old['binding_digest'] != digest(binding):
                    raise Conflict('native replay changed its input or owner grant')
            else:
                pending = self.db.execute("SELECT COUNT(*) FROM native_inbox WHERE state IN ('pending','processing')").fetchone()[0]
                count = self.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
                pages = self.db.execute('PRAGMA page_count').fetchone()[0] - self.db.execute('PRAGMA freelist_count').fetchone()[0]
                if pending >= 4096 or count >= 65536 or pages*self.db.execute('PRAGMA page_size').fetchone()[0] >= 64*1024*1024:
                    raise Conflict('native ingress journal capacity reached')
                self.db.execute('''INSERT INTO native_inbox
                    (id,connector,platform,message_id,binding_id,binding_digest,fingerprint,envelope,payload,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''', (key,connector,envelope['platform'],envelope['message_id'],binding['id'],digest(binding),
                    fingerprint,json.dumps(self.redactor.clean(envelope)),serialized,received_at))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise
        return key

    def claim(self, key, policy, now=None):
        now = time.time() if now is None else now
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM native_inbox WHERE id=?', (key,)).fetchone()
            result = None
            if row and row['state'] == 'pending' and row['next_attempt'] <= now:
                try:
                    policy.current_binding(dict(row))
                except PermissionError:
                    self.db.execute("UPDATE native_inbox SET state='revoked' WHERE id=?", (key,))
                else:
                    if now >= row['created_at']+86400:
                        self.db.execute("UPDATE native_inbox SET state='expired' WHERE id=?", (key,))
                    else:
                        self.db.execute("UPDATE native_inbox SET state='processing' WHERE id=?", (key,))
                        result = {**dict(row),'envelope':json.loads(row['envelope']),'payload':json.loads(row['payload'])}
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise
        return result

    def due(self, connector, now=None):
        now = time.time() if now is None else now
        row = self.db.execute("SELECT id FROM native_inbox WHERE connector=? AND state='pending' AND next_attempt<=? ORDER BY created_at LIMIT 1", (connector,now)).fetchone()
        return row['id'] if row else None

    def find_discord(self, connector, message_id):
        row = self.db.execute("SELECT id FROM native_inbox WHERE connector=? AND platform='discord' AND message_id=?",
            (connector,str(message_id))).fetchone()
        return row['id'] if row else None

    def complete(self, key, accepted):
        if type(accepted) is not bool:
            raise ValueError('explicit native admission outcome required')
        # The actual mission/relay ledger retains admitted content. Compact only
        # completed transient payloads; keep receipt keys and unresolved inputs.
        self.db.execute("UPDATE native_inbox SET state=?,payload='{}',envelope='{}' WHERE id=? AND state='processing'",
            ('committed' if accepted else 'ignored',key))

    def retry(self, key):
        row = self.db.execute('SELECT attempt FROM native_inbox WHERE id=?', (key,)).fetchone()
        if row:
            attempt = row['attempt']+1
            self.db.execute("UPDATE native_inbox SET state=?,attempt=?,next_attempt=? WHERE id=? AND state='processing'",
                ('failed' if attempt>=8 else 'pending',attempt,time.time()+min(60,2**min(attempt,6)),key))
