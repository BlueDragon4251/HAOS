"""Durable native SDK resume point, fenced behind unfinished original custody.

The SDK may prefetch before normalization finishes. Its candidate cursor must
never hide an earlier raw source that has not reached durable decoded custody.
"""
import json
import re
import time

from .gateway import Conflict
from .gateway_photon import credentials, scope


def sequence(value):
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,15}', value) or int(value) >= 2**53:
        raise ValueError('exact bounded native Photon resume cursor required')
    return int(value)


class Cursor:
    def __init__(self, originals, value, current):
        if not callable(current): raise PermissionError('current independent Photon authority required')
        current(); self.originals = originals; self.db = originals.db; self.current = current
        self.scope = scope(credentials(value))
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_resume(
            account_scope TEXT PRIMARY KEY,candidate INTEGER NOT NULL,safe INTEGER NOT NULL,
            gap_cursor INTEGER,updated_at REAL NOT NULL)''')
        # Zero requests the server's available history; it does not silently
        # assume that live subscription includes the grant-to-connection gap.
        self.db.execute('INSERT OR IGNORE INTO photon_resume VALUES(?,0,0,NULL,?)', (self.scope, time.time()))

    def row(self):
        row = self.db.execute('SELECT * FROM photon_resume WHERE account_scope=?', (self.scope,)).fetchone()
        if (row is None or any(type(row[key]) is not int or not 0 <= row[key] < 2**53 for key in ['candidate', 'safe'])
                or row['safe'] > row['candidate'] or row['gap_cursor'] is not None and
                (type(row['gap_cursor']) is not int or not 0 <= row['gap_cursor'] <= row['candidate'])):
            raise Conflict('Photon native resume record is damaged')
        return row

    def check(self):
        self.current(); row = self.row()
        if row['gap_cursor'] is not None:
            raise PermissionError('Photon resume cursor was rejected; inspected owner recovery required')
        return row

    def pending(self):
        rows = self.db.execute('SELECT * FROM photon_originals WHERE account_scope=? AND length(normalized)=0', (self.scope,)).fetchall()
        if len(rows) > 128: raise Conflict('Photon pending source cursor capacity exceeded')
        result = []
        for row in rows:
            self.originals._verify(row)
            proof = json.loads(row['proof']); cursor = sequence(proof['native_cursor'])
            if cursor < 1: raise Conflict('Photon message cursor cannot precede the start watermark')
            result.append(cursor)
        return result

    def _advance(self, cursor=None):
        self.current(); self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.check(); candidate = max(row['candidate'], sequence(cursor)) if cursor is not None else row['candidate']
            pending = self.pending(); safe = min(candidate, min(pending) - 1) if pending else candidate
            self.db.execute('UPDATE photon_resume SET candidate=?,safe=?,updated_at=? WHERE account_scope=?',
                (candidate, safe, time.time(), self.scope))
            self.current(); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        return str(safe)

    def resume(self):
        return self._advance()

    def advance(self, cursor):
        sequence(cursor)
        return self._advance(cursor)

    def refresh(self):
        return self._advance()

    def gap(self, cursor):
        cursor = sequence(cursor); self.current(); self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.row()
            if cursor > row['candidate']: raise Conflict('Photon rejected cursor has no committed SDK candidate')
            if row['gap_cursor'] is not None and row['gap_cursor'] != cursor:
                raise Conflict('Photon original rejected cursor must not be overwritten')
            self.db.execute('UPDATE photon_resume SET gap_cursor=?,updated_at=? WHERE account_scope=?', (cursor, time.time(), self.scope))
            self.current(); self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise

    def status(self):
        self.current(); row = self.row(); pending = self.pending()
        return {'candidate': str(row['candidate']), 'safe': str(min(row['candidate'], min(pending) - 1) if pending else row['candidate']),
            'pending_sources': len(pending), 'state': 'cursor-refused' if row['gap_cursor'] is not None else 'recorded',
            'rejected_cursor': str(row['gap_cursor']) if row['gap_cursor'] is not None else None,
            'observed_only': True, 'live_transport_verified': False}
