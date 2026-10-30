"""Finite recorded Photon state and stable account retry budgets; no SDK import."""
import math
import time

from .gateway import Conflict, digest
from .gateway_photon import credentials, scope

STATES = frozenset({'created', 'connecting', 'local-ready', 'upstream-observed', 'disconnected', 'closed', 'revoked',
    'authentication-refused', 'identity-refused', 'cursor-refused', 'rate-limited', 'transport-unavailable',
    'source-unavailable', 'storage-unavailable'})
TERMINAL = frozenset({'authentication-refused', 'identity-refused', 'cursor-refused', 'revoked'})


class Ledger:
    def __init__(self, inbox, connector, value, publication, current):
        if not callable(current): raise PermissionError('current independent Photon authority required')
        current(); value = credentials(value); self.current = current; self.db = inbox.db
        self.account = scope(value); self.credential = digest(value)
        self.identity = digest([self.account, self.credential, connector, publication])
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_profile_status(
            id TEXT PRIMARY KEY,account_scope TEXT NOT NULL,credential_scope TEXT NOT NULL,
            connector TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_account_budget(
            account_scope TEXT PRIMARY KEY,next_attempt REAL NOT NULL)''')
        # Auth refusal follows the same credential across publication/connector
        # changes. The rate budget follows the account across key rotation too.
        prior = self.db.execute('SELECT status FROM photon_profile_status WHERE account_scope=? AND credential_scope=? ORDER BY updated_at DESC',
            (self.account, self.credential)).fetchall()
        blocked = next((row['status'] for row in prior if row['status'] in TERMINAL - {'revoked'}), None)
        self.db.execute('INSERT OR IGNORE INTO photon_account_budget VALUES(?,0)', (self.account,))
        self.db.execute('INSERT OR IGNORE INTO photon_profile_status VALUES(?,?,?,?,?,?)',
            (self.identity, self.account, self.credential, connector, blocked or 'created', time.time()))

    def recorded(self):
        row = self.db.execute('SELECT status,updated_at FROM photon_profile_status WHERE id=?', (self.identity,)).fetchone()
        budget = self.db.execute('SELECT next_attempt FROM photon_account_budget WHERE account_scope=?', (self.account,)).fetchone()
        if (row is None or row['status'] not in STATES or budget is None or type(budget[0]) not in {int, float}
                or not math.isfinite(budget[0]) or budget[0] < 0):
            raise Conflict('Photon recorded status or account budget is damaged')
        return {'status': row['status'], 'next_attempt': budget[0], 'observed_only': True, 'live_transport_verified': False}

    def read(self):
        self.current(); return self.recorded()

    def update(self, state, delay=0):
        if (state not in STATES or type(delay) not in {int, float} or not math.isfinite(delay) or not 0 <= delay <= 86400):
            raise ValueError('finite Photon native state and bounded retry delay required')
        # Recording a denial after authority vanished cannot grant any action.
        # Other status/budget changes still require the current publication.
        if state != 'revoked': self.current()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous = self.recorded()
            # Delayed network errors cannot overwrite the original terminal
            # reason. Budget and state either both commit or both roll back.
            selected = previous['status'] if previous['status'] in TERMINAL else state
            deadline = max(previous['next_attempt'], time.time() + delay) if delay else previous['next_attempt']
            self.db.execute('UPDATE photon_account_budget SET next_attempt=? WHERE account_scope=?', (deadline, self.account))
            self.db.execute('UPDATE photon_profile_status SET status=?,updated_at=? WHERE id=?', (selected, time.time(), self.identity))
            if state != 'revoked': self.current()
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        return self.recorded()

    def permitted(self):
        value = self.read()
        return value['status'] not in TERMINAL and value['next_attempt'] <= time.time()
