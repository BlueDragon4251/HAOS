"""Finite recorded Photon state and stable account retry budgets; no SDK import."""
import math
from itertools import permutations
import time

from .gateway import Conflict, digest
from .gateway_photon import credentials, scope

STATES = frozenset({'created', 'connecting', 'local-ready', 'upstream-observed', 'disconnected', 'closed', 'revoked',
    'authentication-refused', 'identity-refused', 'cursor-refused', 'rate-limited', 'transport-unavailable',
    'source-unavailable', 'storage-unavailable'})
TERMINAL = frozenset({'authentication-refused', 'identity-refused', 'cursor-refused', 'revoked'})


class Ledger:
    def __init__(self, inbox, connector, value, publication, current, *, profile=None):
        if not callable(current): raise PermissionError('current independent Photon authority required')
        current(); value = credentials(value); self.current = current; self.db = inbox.db
        self.account = scope(value)
        # Service toggles change receive authority, not the rejected project
        # credential. They must not re-enable the same refused key.
        self.credential = digest([value['project_id'], value['project_secret'], value['phone']])
        self.identity = digest([self.account, self.credential, connector, publication])
        expected = {'photon_profile_status', 'photon_account_budget'}
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('photon_profile_status','photon_account_budget')")}
        if tables and tables != expected:
            raise Conflict('Photon status schema is incomplete; preserve and inspect it')
        if not tables and profile is not None and self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('photon_output_intents','photon_native_projection') LIMIT 1").fetchone():
            raise Conflict('Photon status history is missing beside retained native records')
        remember = False
        if profile is not None:
            profile.current()
            # This second FULL journal remembers that a concrete profile once
            # required a status row. Missing rows/tables cannot become a fresh
            # identity merely by reopening the central native inbox.
            profile.db.execute('''CREATE TABLE IF NOT EXISTS photon_health_profiles(
                id TEXT PRIMARY KEY,account_scope TEXT NOT NULL,credential_scope TEXT NOT NULL)''')
            remembered = profile.db.execute('SELECT * FROM photon_health_profiles LIMIT 65537').fetchall()
            if len(remembered) > 65536: raise Conflict('Photon status provenance history capacity exceeded')
            for row in remembered:
                if (not tables or row['account_scope'] != self.account or any(not isinstance(row[key], str)
                        or len(row[key]) != 64 or any(c not in '0123456789abcdef' for c in row[key]) for key in ['id', 'credential_scope'])
                        or row['id'] == self.identity and row['credential_scope'] != self.credential):
                    raise Conflict('Photon remembered status provenance is missing or damaged')
                old = self.db.execute('SELECT account_scope,credential_scope FROM photon_profile_status WHERE id=?', (row['id'],)).fetchone()
                if old is None or old['account_scope'] != row['account_scope'] or old['credential_scope'] != row['credential_scope']:
                    raise Conflict('Photon remembered status row is missing or changed')
            if not any(row['id'] == self.identity for row in remembered):
                if len(remembered) >= 65536: raise Conflict('Photon status provenance history capacity reached')
                remember = True
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_profile_status(
            id TEXT PRIMARY KEY,account_scope TEXT NOT NULL,credential_scope TEXT NOT NULL,
            connector TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS photon_account_budget(
            account_scope TEXT PRIMARY KEY,next_attempt REAL NOT NULL)''')
        account_rows = self.db.execute('SELECT status,updated_at FROM photon_profile_status WHERE account_scope=? LIMIT 65537', (self.account,)).fetchall()
        if (len(account_rows) > 65536 or any(row['status'] not in STATES or type(row['updated_at']) not in {int, float}
                or not math.isfinite(row['updated_at']) or not 0 <= row['updated_at'] <= 253402300799 for row in account_rows)):
            raise Conflict('Photon retained status history is damaged or exceeds capacity')
        budget = self.db.execute('SELECT next_attempt FROM photon_account_budget WHERE account_scope=?', (self.account,)).fetchone()
        if (account_rows and budget is None or budget is not None and (type(budget[0]) not in {int, float}
                or not math.isfinite(budget[0]) or not 0 <= budget[0] <= 253402300799)):
            raise Conflict('Photon original account retry budget is missing or damaged')
        if self.db.execute('SELECT COUNT(*) FROM photon_profile_status').fetchone()[0] >= 65536 and not self.db.execute(
                'SELECT 1 FROM photon_profile_status WHERE id=?', (self.identity,)).fetchone():
            raise Conflict('Photon status history capacity reached; inspected owner recovery required')
        # Auth refusal follows the same credential across publication/connector
        # changes. The rate budget follows the account across key rotation too.
        # Earlier prepared profiles hashed the service list into the credential
        # key. Preserve their refusals without resetting or deleting recovery
        # data. The three finite service names give only 15 legacy permutations.
        credential_keys = [self.credential, *[digest({**value, 'services': list(items)})
            for count in range(1, 4) for items in permutations(('iMessage', 'SMS', 'RCS'), count)]]
        prior = self.db.execute('SELECT status FROM photon_profile_status WHERE account_scope=? AND credential_scope IN (' +
            ','.join('?' for _ in credential_keys) + ') ORDER BY updated_at DESC', (self.account, *credential_keys)).fetchall()
        blocked = next((row['status'] for row in prior if row['status'] in TERMINAL - {'revoked'}), None)
        self.db.execute('INSERT OR IGNORE INTO photon_account_budget VALUES(?,0)', (self.account,))
        self.db.execute('INSERT OR IGNORE INTO photon_profile_status VALUES(?,?,?,?,?,?)',
            (self.identity, self.account, self.credential, connector, blocked or 'created', time.time()))
        if remember:
            # No native connection can begin until construction returns. An
            # interrupted first initialization therefore cannot lose a real
            # authentication refusal between these two durable journals.
            profile.current()
            profile.db.execute('INSERT INTO photon_health_profiles VALUES(?,?,?)', (self.identity, self.account, self.credential))

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
            active_limit = (previous['status'] in {'rate-limited', 'source-unavailable', 'storage-unavailable'} and previous['next_attempt'] > time.time()
                and state in {'transport-unavailable', 'connecting', 'local-ready', 'upstream-observed'})
            selected = previous['status'] if previous['status'] in TERMINAL or active_limit else state
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
