"""One explicitly inspected local auth retry; no authentication or network claim."""
import math
from pathlib import Path
import re
import time

from .gateway import Conflict, digest
from .gateway_photon import checked_policy
from .gateway_photon_status import checked, selector, read
from .gateway_photon_journal import writable
from .gateway_photon_health import STATES

AUTH = frozenset({'authentication-refused', 'identity-refused'})
HEX = re.compile(r'[a-f0-9]{64}\Z')


def inspection(status):
    return digest(checked(status))


def request(value, owner_uid):
    fields = {'connector', 'credential_scope', 'account_scope', 'credential_aliases', 'inspection_sha256', 'owner_uid', 'note_sha256', 'confirmed'}
    if (type(owner_uid) is not int or not isinstance(value, dict) or set(value) != fields or value['confirmed'] is not True
            or type(value['owner_uid']) is not int or value['owner_uid'] != owner_uid or not 0 <= owner_uid < 2**32 - 1
            or any(not isinstance(value[key], str) or not HEX.fullmatch(value[key]) for key in ['inspection_sha256', 'note_sha256'])
            or not isinstance(value['credential_aliases'], list) or not 1 <= len(value['credential_aliases']) <= 16
            or any(not isinstance(key, str) or not HEX.fullmatch(key) for key in value['credential_aliases'])
            or len(set(value['credential_aliases'])) != len(value['credential_aliases']) or value['credential_scope'] not in value['credential_aliases']):
        raise PermissionError('exact inspected Photon credential epoch and confirmed Owner retry required')
    selector({key: value[key] for key in ['connector', 'credential_scope', 'account_scope']})
    return dict(value)


def retry(path, value, policy, current):
    value = request(value, value.get('owner_uid') if isinstance(value, dict) else None)
    checked_policy(policy); current()
    if (policy.connectors.get(value['connector'], {}).get('platform') != 'photon'
            or not any(row['connector'] == value['connector'] and row['scope'] == value['account_scope'] for row in policy.bindings.values())):
        raise PermissionError('current independently approved Photon connector/account grants required')
    chosen = {key: value[key] for key in ['connector', 'credential_scope', 'account_scope']}
    observed = read(Path(path), chosen, current)
    identity = digest([value, policy.publication, policy.connectors, policy.bindings])
    with writable(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS photon_auth_owner_events(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,account_scope TEXT NOT NULL,credential_scope TEXT NOT NULL,
            inspection_sha256 TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
            receipt TEXT NOT NULL,cleared INTEGER NOT NULL,before_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')
        old = db.execute('SELECT * FROM photon_auth_owner_events WHERE id=?', (identity,)).fetchone()
        if old is not None:
            if (type(old['cleared']) is not int or not 0 <= old['cleared'] <= 65536
                    or not isinstance(old['before_sha256'], str) or not HEX.fullmatch(old['before_sha256'])
                    or old['receipt'] != digest([identity, old['before_sha256'], old['cleared']])):
                raise Conflict('Photon Owner retry receipt is damaged')
            count = old['cleared']; receipt = old['receipt']
        else:
            if observed['status'] not in AUTH or inspection(observed) != value['inspection_sha256']:
                raise Conflict('Photon authentication state changed after inspection; read and confirm it again')
            if db.execute('SELECT COUNT(*) FROM photon_auth_owner_events').fetchone()[0] >= 65536:
                raise Conflict('Photon Owner retry history capacity reached')
            # The profile lease and stopped service exclude native writers. A
            # second read inside the transaction also fences a changed budget.
            actual = read(Path(path), chosen, current)
            if inspection(actual) != value['inspection_sha256']: raise Conflict('Photon retry inspection is stale')
            budget = db.execute('SELECT next_attempt FROM photon_account_budget WHERE account_scope=?', (value['account_scope'],)).fetchone()
            if budget is None or type(budget[0]) not in {int, float} or not math.isfinite(budget[0]): raise Conflict('original Photon account budget required')
            aliases = value['credential_aliases']; placeholders = ','.join('?' for _ in aliases)
            rows = db.execute('SELECT id,status,updated_at FROM photon_profile_status WHERE account_scope=? AND credential_scope IN (' + placeholders + ') ORDER BY id',
                (value['account_scope'], *aliases)).fetchall()
            if len(rows) > 65536: raise Conflict('bounded Photon auth history required')
            if any(row['status'] not in STATES or type(row['updated_at']) not in {int, float}
                    or not math.isfinite(row['updated_at']) for row in rows): raise Conflict('Photon auth history is damaged')
            before = digest([tuple(row) for row in rows])
            count = db.execute("UPDATE photon_profile_status SET status='created',updated_at=? WHERE account_scope=? AND credential_scope IN (" + placeholders + ") AND status IN ('authentication-refused','identity-refused')",
                (time.time(), value['account_scope'], *aliases)).rowcount
            if count != sum(row['status'] in AUTH for row in rows): raise Conflict('Photon authentication blocks were not updated atomically')
            after = db.execute('SELECT next_attempt FROM photon_account_budget WHERE account_scope=?', (value['account_scope'],)).fetchone()
            if after is None or after[0] != budget[0]: raise Conflict('Photon auth retry must preserve the original account budget')
            receipt = digest([identity, before, count])
            db.execute('INSERT INTO photon_auth_owner_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (identity, value['connector'], value['account_scope'], value['credential_scope'], value['inspection_sha256'],
                    value['owner_uid'], value['note_sha256'], receipt, count, before, time.time()))
        current()
    return {'connector': value['connector'], 'authentication_blocks_cleared': count, 'receipt': receipt,
        'network_requested': False, 'message_sent': False, 'authentication_verified': False, 'account_budget_preserved': True,
        'recorded_decision_replayed': old is not None}
