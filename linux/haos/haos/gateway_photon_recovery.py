"""Inspected retired-source disposal with durable, cursor-bound tombstones.

Only an authenticated Owner worker holding the inactive profile lease may call
the mutation. No request here authorizes receipt, delivery or network access.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import time

from .gateway import Conflict, digest
from .gateway_photon import checked_policy, message_id

HEX = re.compile(r'[a-f0-9]{64}\Z')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')


def profile_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'photon-[a-f0-9]{64}', value):
        raise ValueError('exact retained Photon profile required')
    return value


def _hash(value): return isinstance(value, str) and HEX.fullmatch(value)


def open_retained(profile, current):
    """Inspect the existing source schema before any initializer can repair it."""
    from .gateway_runtime import require_runtime_identity
    from .gateway_line_profile import _directory
    from .gateway_photon_journal import readonly, ORIGINAL_COLUMNS
    from .gateway_photon_custody import Originals
    from .redaction import Redactor
    require_runtime_identity(); current(); profile = Path(profile); _directory(profile)
    path = profile / 'originals.db'
    with readonly(path) as db:
        db.execute('SELECT ' + ','.join(ORIGINAL_COLUMNS) + ' FROM photon_originals LIMIT 0')
    current(); return Originals(path, Redactor([]), current)


def _tombstone(event):
    return json.dumps({'purged': True, 'native_cursor': event['native_cursor'], 'proof_sha256': event['proof_sha256'],
        'receipt': event['receipt']}, sort_keys=True, separators=(',', ':'))


def disposed(db, record):
    """A missing body alone must never let the native cursor skip a source."""
    row = dict(record)
    if row['raw']: return False
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photon_source_owner_events'").fetchone()
    if not exists: raise Conflict('Photon source has no inspected owner disposal')
    event = db.execute('SELECT * FROM photon_source_owner_events WHERE id=?', (row['id'],)).fetchone()
    if event is None: raise Conflict('Photon source has no inspected owner disposal')
    event = dict(event)
    fields = {'id', 'owner_uid', 'note_sha256', 'snapshot_sha256', 'receipt', 'native_cursor', 'raw_sha256',
        'normalized_sha256', 'proof_sha256', 'policy_sha256', 'created_at'}
    from .gateway_photon_cursor import sequence
    if (set(event) != fields or any(not _hash(event[key]) for key in ['id', 'note_sha256', 'snapshot_sha256', 'receipt', 'raw_sha256', 'proof_sha256', 'policy_sha256'])
            or event['normalized_sha256'] != '' and not _hash(event['normalized_sha256'])
            or type(event['owner_uid']) is not int or not 0 <= event['owner_uid'] < 2**32 - 1
            or type(event['created_at']) not in {int, float} or not math.isfinite(event['created_at']) or not 0 < event['created_at'] <= 253402300799
            or sequence(event['native_cursor']) < 1
            or event['receipt'] != digest({key: value for key, value in event.items() if key != 'receipt'})
            or event['raw_sha256'] != row['raw_sha256'] or event['normalized_sha256'] != row['normalized_sha256']
            or row['normalized'] or row['parts'] != '{}' or row['proof'] != _tombstone(event)):
        raise Conflict('Photon inspected disposal is damaged')
    return True


def source_view(store, record, policy, profile):
    row = dict(record); profile_name(profile)
    if (any(not _hash(row[key]) for key in ['id', 'credential_scope', 'binding_digest', 'semantic_sha256', 'raw_sha256'])
            or not isinstance(row['account_scope'], str) or not re.fullmatch(r'photon:[a-f0-9]{64}', row['account_scope'])
            or profile != 'photon-' + row['account_scope'].removeprefix('photon:')
            or any(not isinstance(row[key], str) or not NAME.fullmatch(row[key]) for key in ['connector', 'binding_id'])
            or row['admitted_receipt'] != '' and not _hash(row['admitted_receipt'])
            or type(row['created_at']) not in {int, float} or not math.isfinite(row['created_at']) or not 0 < row['created_at'] <= 253402300799):
        raise Conflict('damaged Photon original metadata')
    message_id(row['message_id']); active = False
    if policy is not None:
        checked_policy(policy)
        try:
            binding = policy.current_binding(row)
            active = binding['connector'] == row['connector'] and binding['scope'] == row['account_scope']
        except PermissionError: pass
    state = 'retained'
    if not row['raw']:
        disposed(store.db, row); state = 'purged'
    else:
        try: store._verify(row)
        except (Conflict, ValueError, KeyError, TypeError): state = 'damaged'
    public = {key: row[key] for key in ['id', 'connector', 'message_id', 'binding_id', 'binding_digest', 'created_at', 'admitted_receipt']}
    public.update(profile=profile, source_sha256=row['raw_sha256'], normalized_sha256=row['normalized_sha256'],
        proof_sha256=digest(row['proof']), actual_sha256=hashlib.sha256(row['raw']).hexdigest() if row['raw'] else None,
        stored_bytes=len(row['raw']) + len(row['normalized']), current_grant=active, purge_allowed=not active,
        state=state, authentication_reverified=False, private_bytes_returned=False)
    return {**public, 'snapshot_sha256': digest(public)}


def sources(store, policy, profile, current):
    current(); profile_name(profile)
    rows = store.db.execute('SELECT * FROM photon_originals ORDER BY (length(raw)>0) DESC,created_at DESC LIMIT 129').fetchall()
    result = {'profile': profile, 'sources': [source_view(store, row, policy, profile) for row in rows[:128]],
        'history_truncated': len(rows) > 128, 'network_requested': False, 'private_bytes_returned': False}
    current(); return result


def purge_source(store, policy, request, current):
    fields = {'profile', 'id', 'snapshot_sha256', 'owner_uid', 'note_sha256', 'confirmed'}
    if (not isinstance(request, dict) or set(request) != fields or request['confirmed'] is not True
            or type(request['owner_uid']) is not int or not 0 <= request['owner_uid'] < 2**32 - 1
            or any(not _hash(request[key]) for key in ['id', 'snapshot_sha256', 'note_sha256'])):
        raise PermissionError('closed explicitly confirmed inspected Photon owner disposal required')
    profile_name(request['profile']); current(); db = store.db; db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS photon_source_owner_events(
            id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
            receipt TEXT NOT NULL,native_cursor TEXT NOT NULL,raw_sha256 TEXT NOT NULL,normalized_sha256 TEXT NOT NULL,
            proof_sha256 TEXT NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')
        row = db.execute('SELECT * FROM photon_originals WHERE id=?', (request['id'],)).fetchone()
        if row is None: raise KeyError('unknown retained Photon original')
        view = source_view(store, row, policy, request['profile'])
        if not view['purge_allowed']: raise PermissionError('withdraw the original Photon grant before disposal')
        old = db.execute('SELECT * FROM photon_source_owner_events WHERE id=?', (request['id'],)).fetchone()
        if old is not None:
            if not disposed(db, row) or any(old[key] != request[key] for key in ['owner_uid', 'note_sha256', 'snapshot_sha256']):
                raise Conflict('Photon disposal belongs to another inspected owner decision')
            receipt = old['receipt']
        else:
            if view['snapshot_sha256'] != request['snapshot_sha256']: raise Conflict('Photon original changed after owner inspection')
            # A damaged proof cannot invent a cursor to skip. Inspect/export it
            # separately; this action never clears a server-rejected cursor.
            store._verify(row)
            proof = json.loads(row['proof'])
            from .gateway_photon_cursor import sequence
            if sequence(proof['native_cursor']) < 1: raise Conflict('Photon original has no native cursor')
            event = {'id': request['id'], 'owner_uid': request['owner_uid'], 'note_sha256': request['note_sha256'],
                'snapshot_sha256': request['snapshot_sha256'], 'native_cursor': proof['native_cursor'], 'raw_sha256': row['raw_sha256'],
                'normalized_sha256': row['normalized_sha256'], 'proof_sha256': digest(row['proof']),
                'policy_sha256': digest([policy.publication, policy.connectors, policy.bindings]) if policy is not None else digest({'gateways': 'absent', 'version': 1}), 'created_at': time.time()}
            receipt = digest(event); event['receipt'] = receipt
            db.execute("UPDATE photon_originals SET raw=x'',normalized=x'',parts='{}',proof=? WHERE id=?", (_tombstone(event), request['id']))
            db.execute('INSERT INTO photon_source_owner_events VALUES(?,?,?,?,?,?,?,?,?,?,?)', tuple(event[key] for key in
                ['id', 'owner_uid', 'note_sha256', 'snapshot_sha256', 'receipt', 'native_cursor', 'raw_sha256', 'normalized_sha256', 'proof_sha256', 'policy_sha256', 'created_at']))
        current(); db.execute('COMMIT')
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise
    return {'id': request['id'], 'receipt': receipt, 'network_requested': False, 'message_sent': False,
        'tombstones_retained': True, 'other_copies_backups_and_WAL_erasure_not_claimed': True}
