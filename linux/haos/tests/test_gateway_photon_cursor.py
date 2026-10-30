"""Actual FULL SQLite resume/barrier/reopen/failure tests, without an SDK import."""
import copy
import json
import secrets
import sqlite3
import uuid

import pytest

from test_gateway_photon_admission import source, custody, decoded
from haos.gateway import Conflict
from haos.gateway_photon_cursor import Cursor, sequence


def cursor(source, custody):
    store, _, current = custody
    return Cursor(store, source[0], current)


def retain(source, custody):
    return custody[0].retain(custody[1], 'phone', source[0], json.dumps(source[2]).encode())


def decode(source, custody, key):
    custody[0].decode(key, custody[1], 'phone', source[0], json.dumps(decoded(source)).encode())


def test_initial_cursor_requests_available_history_instead_of_assuming_live_is_complete(source, custody):
    journal = cursor(source, custody)
    assert journal.resume() == '0'
    assert journal.status() == {'candidate': '0', 'safe': '0', 'pending_sources': 0, 'state': 'recorded',
        'rejected_cursor': None, 'observed_only': True, 'live_transport_verified': False}


def test_prefetched_candidate_cannot_skip_unfinished_original(source, custody):
    journal = cursor(source, custody); key = retain(source, custody)
    assert journal.advance('9') == '0'
    assert journal.status()['candidate'] == '9'
    assert journal.status()['pending_sources'] == 1
    decode(source, custody, key)
    assert journal.refresh() == '9'
    # A committed decoded source suffices for cursor progress. Controller
    # acceptance is a separate durable queue and not claimed by this receipt.
    assert custody[0].load(key, custody[1], 'phone', source[0])[0]['admitted_receipt'] == ''


def test_safe_cursor_stops_before_each_of_two_unfinished_sources(source, custody):
    journal = cursor(source, custody); first = copy.deepcopy(source[2]); a = retain(source, custody)
    source[2]['cursor'] = '3'; source[2]['event']['sequence'] = 3; source[2]['event']['message']['guid'] = str(uuid.uuid4())
    b = retain(source, custody)
    assert journal.advance('10') == '0'
    second = source[2]; source = (source[0], source[1], first)
    decode(source, custody, a)
    assert journal.refresh() == '2'
    decode((source[0], source[1], second), custody, b)
    assert journal.refresh() == '10'


def test_late_unfinished_original_is_included_in_actual_restart_point(source, custody):
    journal = cursor(source, custody)
    assert journal.advance('20') == '20'
    source[2]['cursor'] = '4'; source[2]['event']['sequence'] = 4; key = retain(source, custody)
    assert journal.resume() == '3'
    decode(source, custody, key)
    assert journal.refresh() == '20'


def test_sqlite_reopen_preserves_pending_barrier_and_decoded_progress(source, custody):
    journal = cursor(source, custody); key = retain(source, custody)
    assert journal.advance('8') == '0'
    reopened = Cursor(custody[0], source[0], custody[2])
    assert reopened.resume() == '0'
    decode(source, custody, key)
    assert reopened.refresh() == '8'
    assert journal.resume() == '8'


def test_rejected_cursor_is_sticky_and_never_silently_resumes_live(source, custody):
    journal = cursor(source, custody)
    assert journal.advance('7') == '7'
    journal.gap('7')
    assert journal.status()['state'] == 'cursor-refused'
    for operation in [journal.resume, lambda: journal.advance('8'), journal.refresh]:
        with pytest.raises(PermissionError, match='inspected owner recovery'): operation()
    changed_key = {**source[0], 'project_secret': secrets.token_urlsafe(32)}
    reopened = Cursor(custody[0], changed_key, custody[2])
    with pytest.raises(PermissionError): reopened.resume()
    with pytest.raises(Conflict): reopened.gap('6')
    assert reopened.status()['rejected_cursor'] == '7'


def test_actual_sql_failure_does_not_commit_candidate_or_safe_cursor(source, custody):
    journal = cursor(source, custody)
    custody[0].db.execute("CREATE TRIGGER refuse_cursor BEFORE UPDATE ON photon_resume BEGIN SELECT RAISE(ABORT,'fixture cursor write refusal'); END")
    with pytest.raises(sqlite3.IntegrityError): journal.advance('8')
    assert journal.status()['candidate'] == '0' and journal.status()['safe'] == '0'
    assert not custody[0].db.in_transaction


def test_other_project_never_inherits_cursor_or_gap(source, custody):
    journal = cursor(source, custody); journal.advance('10'); journal.gap('10')
    other = Cursor(custody[0], {**source[0], 'project_id': 'another-project'}, custody[2])
    assert other.resume() == '0' and other.status()['state'] == 'recorded'


def test_damaged_pending_proof_cannot_advance_resume_beyond_original(source, custody):
    journal = cursor(source, custody); key = retain(source, custody)
    row, _ = custody[0].load(key, custody[1], 'phone', source[0]); proof = json.loads(row['proof']); proof['native_cursor'] = '99'
    custody[0].db.execute('UPDATE photon_originals SET proof=? WHERE id=?', (json.dumps(proof, sort_keys=True, separators=(',', ':')), key))
    with pytest.raises(Conflict): journal.advance('8')
    assert journal.row()['candidate'] == 0


@pytest.mark.parametrize('value', [None, True, 1, -1, '', '-1', '01', '1.0', '9007199254740992', '99999999999999999'])
def test_noncanonical_or_unbounded_cursor_refused(value):
    with pytest.raises(ValueError): sequence(value)
