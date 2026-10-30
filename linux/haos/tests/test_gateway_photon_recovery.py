"""Actual FULL SQL owner disposition; absent data alone never advances cursors."""
import copy
import hashlib
import json
import sqlite3
import secrets
import time

import pytest

from test_gateway_photon_admission import source, custody, retain, decoded
from haos.gateway import Conflict
from haos.gateway_photon import PreparedPhotonPolicy
from haos.gateway_photon_cursor import Cursor
from haos.gateway_photon_recovery import sources, purge_source, disposed, profile_name


def retired(source):
    config = copy.deepcopy(source[1]); config['bindings'] = []
    return PreparedPhotonPolicy(config)


def request(source, custody, policy):
    store = custody[0]; name = 'photon-' + source[1]['bindings'][0]['scope'].split(':')[1]
    view = sources(store, policy, name, lambda: None)['sources'][0]
    return {'profile': name, 'id': view['id'], 'snapshot_sha256': view['snapshot_sha256'], 'owner_uid': 1000,
        'note_sha256': hashlib.sha256(b'fixture inspected retired original').hexdigest(), 'confirmed': True}


def test_inspection_never_returns_message_or_credentials_and_live_grant_blocks_disposal(source, custody):
    key = retain(source, custody); store, policy, _ = custody
    chosen = request(source, custody, policy)
    with pytest.raises(PermissionError, match='withdraw'): purge_source(store, policy, chosen, lambda: None)
    assert json.loads(store.db.execute('SELECT raw FROM photon_originals WHERE id=?', (key,)).fetchone()[0]) == source[2]
    result = sources(store, policy, chosen['profile'], lambda: None)
    assert not result['network_requested'] and not result['private_bytes_returned']
    assert result['sources'][0]['current_grant'] and not result['sources'][0]['purge_allowed']
    text = json.dumps(result)
    assert 'fixture command' not in text and source[0]['project_secret'] not in text and source[1]['bindings'][0]['sender'] not in text


def test_explicit_retired_source_disposal_releases_only_its_cursor_barrier_and_never_restores(source, custody):
    key = retain(source, custody); store, policy, current = custody; cursor = Cursor(store, source[0], current)
    assert cursor.advance('9') == '0'
    chosen = request(source, custody, retired(source)); result = purge_source(store, retired(source), chosen, lambda: None)
    assert result['tombstones_retained'] and result['other_copies_backups_and_WAL_erasure_not_claimed']
    assert not result['network_requested'] and not result['message_sent']
    row = store.db.execute('SELECT * FROM photon_originals WHERE id=?', (key,)).fetchone()
    assert not row['raw'] and not row['normalized'] and disposed(store.db, row)
    assert cursor.refresh() == '9'
    assert purge_source(store, retired(source), chosen, lambda: None) == result
    with pytest.raises(Conflict, match='automatic restoration'): retain(source, custody)
    with pytest.raises(Conflict): store.load(key, policy, 'phone', source[0])
    view = sources(store, retired(source), chosen['profile'], lambda: None)['sources'][0]
    assert view['state'] == 'purged' and view['stored_bytes'] == 0


def test_disposal_preserves_parent_receipt_and_source_hashes_without_claiming_erasure_of_other_copies(source, custody):
    key = retain(source, custody); store, policy, _ = custody
    store.decode(key, policy, 'phone', source[0], json.dumps(decoded(source)).encode())
    store.admitted(key, 'a' * 64, policy, 'phone', source[0])
    before = dict(store.db.execute('SELECT * FROM photon_originals WHERE id=?', (key,)).fetchone())
    chosen = request(source, custody, retired(source)); purge_source(store, retired(source), chosen, lambda: None)
    after = dict(store.db.execute('SELECT * FROM photon_originals WHERE id=?', (key,)).fetchone())
    for field in ['id', 'connector', 'credential_scope', 'binding_digest', 'raw_sha256', 'normalized_sha256', 'admitted_receipt']:
        assert after[field] == before[field]
    assert after['admitted_receipt'] == 'a' * 64 and not after['normalized']


@pytest.mark.parametrize('change', ['unconfirmed', 'owner-bool', 'owner-negative', 'extra-key', 'bad-note', 'bad-id', 'bad-profile'])
def test_unconfirmed_or_unbounded_owner_decisions_cannot_change_retained_data(source, custody, change):
    key = retain(source, custody); store = custody[0]; chosen = request(source, custody, retired(source))
    if change == 'unconfirmed': chosen['confirmed'] = False
    elif change == 'owner-bool': chosen['owner_uid'] = True
    elif change == 'owner-negative': chosen['owner_uid'] = -1
    elif change == 'extra-key': chosen['credentials'] = {'project_secret': 'must-not-accept'}
    elif change == 'bad-note': chosen['note_sha256'] = 'private note'
    elif change == 'bad-id': chosen['id'] = '../source'
    elif change == 'bad-profile': chosen['profile'] = '../profile'
    with pytest.raises((PermissionError, ValueError)): purge_source(store, retired(source), chosen, lambda: None)
    assert store.db.execute('SELECT length(raw) FROM photon_originals WHERE id=?', (key,)).fetchone()[0] > 0


@pytest.mark.parametrize('change', ['source', 'snapshot', 'profile', 'different-repeat', 'lost-authority', 'SQL-refusal'])
def test_changed_inspection_or_failed_commit_keeps_source_and_cursor_barrier(source, custody, change):
    key = retain(source, custody); store, _, current = custody; cursor = Cursor(store, source[0], current)
    assert cursor.advance('9') == '0'
    policy = retired(source); chosen = request(source, custody, policy)
    authority = lambda: None; expected = (Conflict, PermissionError, sqlite3.Error)
    if change == 'source': store.db.execute('UPDATE photon_originals SET admitted_receipt=? WHERE id=?', ('a' * 64, key))
    elif change == 'snapshot': chosen['snapshot_sha256'] = 'f' * 64
    elif change == 'profile': chosen['profile'] = 'photon-' + 'c' * 64
    elif change == 'different-repeat':
        purge_source(store, policy, chosen, authority); chosen['note_sha256'] = 'e' * 64
    elif change == 'lost-authority':
        calls = []
        def authority():
            calls.append(True)
            if len(calls) > 1: raise PermissionError('fixture owner changed during disposal')
    elif change == 'SQL-refusal':
        # A first real disposition establishes the journal. Refuse the audit
        # insert for a second source and require its body deletion to roll back.
        purge_source(store, policy, chosen, authority)
        source[2]['event']['message']['guid'] = 'spc-second-fixture-source'
        key = retain(source, custody); chosen = request(source, custody, policy)
        chosen['id'] = key
        chosen['snapshot_sha256'] = next(row for row in sources(store, policy, chosen['profile'], authority)['sources'] if row['id'] == key)['snapshot_sha256']
        store.db.execute("CREATE TRIGGER refuse_owner_receipt BEFORE INSERT ON photon_source_owner_events BEGIN SELECT RAISE(ABORT,'fixture owner audit write refusal'); END")
    with pytest.raises(expected): purge_source(store, policy, chosen, authority)
    if change != 'different-repeat':
        assert store.db.execute('SELECT length(raw) FROM photon_originals WHERE id=?', (key,)).fetchone()[0] > 0
        assert cursor.refresh() == '0'
    assert not store.db.in_transaction


@pytest.mark.parametrize('change', ['missing-body', 'missing-audit', 'changed-cursor', 'changed-receipt', 'changed-source-hash'])
def test_missing_or_tampered_disposal_cannot_skip_pending_cursor(source, custody, change):
    key = retain(source, custody); store, _, current = custody; cursor = Cursor(store, source[0], current)
    assert cursor.advance('9') == '0'
    if change == 'missing-body': store.db.execute("UPDATE photon_originals SET raw=x'' WHERE id=?", (key,))
    else:
        chosen = request(source, custody, retired(source)); purge_source(store, retired(source), chosen, lambda: None)
        if change == 'missing-audit': store.db.execute('DELETE FROM photon_source_owner_events WHERE id=?', (key,))
        elif change == 'changed-cursor': store.db.execute("UPDATE photon_source_owner_events SET native_cursor='9' WHERE id=?", (key,))
        elif change == 'changed-receipt': store.db.execute('UPDATE photon_source_owner_events SET receipt=? WHERE id=?', ('f' * 64, key))
        elif change == 'changed-source-hash': store.db.execute('UPDATE photon_originals SET raw_sha256=? WHERE id=?', ('f' * 64, key))
    with pytest.raises(Conflict): cursor.refresh()
    assert store.db.execute('SELECT safe FROM photon_resume').fetchone()[0] == 0


def test_owner_source_disposal_does_not_clear_server_rejected_cursor(source, custody):
    retain(source, custody); store, _, current = custody; cursor = Cursor(store, source[0], current)
    cursor.advance('9'); cursor.gap('0')
    purge_source(store, retired(source), request(source, custody, retired(source)), lambda: None)
    assert cursor.status()['state'] == 'cursor-refused'
    with pytest.raises(PermissionError, match='rejected'): cursor.resume()


def test_full_live_source_quota_requires_owner_disposal_and_fresh_regrant_without_skipping_other_pending_sources(source, custody):
    store, policy, current = custody; cursor = Cursor(store, source[0], current)
    keys = []
    for index in range(128):
        source[2]['event']['message']['guid'] = 'spc-quota-' + str(index)
        source[2]['cursor'] = str(index + 1); source[2]['event']['sequence'] = index + 1
        keys.append(retain(source, custody))
    assert cursor.advance('128') == '0'
    source[2]['event']['message']['guid'] = 'spc-quota-new'
    source[2]['cursor'] = '129'; source[2]['event']['sequence'] = 129
    with pytest.raises(Conflict, match='capacity'): retain(source, custody)
    name = 'photon-' + source[1]['bindings'][0]['scope'].split(':')[1]
    view = next(row for row in sources(store, retired(source), name, lambda: None)['sources'] if row['id'] == keys[0])
    chosen = {'profile': name, 'id': view['id'], 'snapshot_sha256': view['snapshot_sha256'], 'owner_uid': 1000,
        'note_sha256': hashlib.sha256(b'fixture inspected full quota').hexdigest(), 'confirmed': True}
    purge_source(store, retired(source), chosen, lambda: None)
    config = copy.deepcopy(source[1]); config['bindings'][0]['generation'] = secrets.token_hex(32)
    config['bindings'][0]['since'] = int(time.time() * 1000)
    renewed = PreparedPhotonPolicy(config); store.current = lambda: renewed
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    source[2]['event']['occurredAt'] = now; source[2]['event']['message']['dateCreated'] = now
    store.retain(renewed, 'phone', source[0], json.dumps(source[2]).encode())
    assert store.db.execute('SELECT COUNT(*) FROM photon_originals WHERE length(raw)>0').fetchone()[0] == 128
    assert store.db.execute('SELECT COUNT(*) FROM photon_originals').fetchone()[0] == 129
    assert cursor.refresh() == '1'  # 127 other unfinished old originals still fence the restart point.
    assert not store.db.execute('SELECT raw FROM photon_originals WHERE id=?', (keys[0],)).fetchone()[0]
