import secrets
import sqlite3
import time

import pytest

from test_gateway_photon_admission import source, custody
from haos.gateway_photon_health import Ledger
from haos.gateway import Conflict


def ledger(source, custody, *, connector='phone', publication='fixture-publication', value=None):
    return Ledger(custody[0].store, connector, value or source[0], publication, custody[2])


def test_recorded_status_does_not_claim_a_live_transport(source, custody):
    health = ledger(source, custody)
    assert health.permitted()
    assert health.read() == {'status': 'created', 'next_attempt': 0, 'observed_only': True, 'live_transport_verified': False}


@pytest.mark.parametrize('state', ['authentication-refused', 'identity-refused', 'cursor-refused', 'revoked'])
def test_late_network_error_preserves_terminal_reason_and_extends_budget(source, custody, state):
    health = ledger(source, custody); health.update(state)
    assert health.update('transport-unavailable', 30)['status'] == state
    assert health.read()['next_attempt'] > time.time() + 25
    assert not health.permitted()


def test_account_rate_budget_survives_key_rotation_connector_and_publication(source, custody):
    health = ledger(source, custody); health.update('rate-limited', 120)
    changed = {**source[0], 'project_secret': secrets.token_urlsafe(32)}
    other = ledger(source, custody, connector='renamed-phone', publication='new-publication', value=changed)
    assert not other.permitted()
    assert other.read()['next_attempt'] == health.read()['next_attempt']
    assert other.read()['status'] == 'created'


def test_generic_startup_error_does_not_hide_an_active_native_rate_limit(source, custody):
    health = ledger(source, custody); first = health.update('rate-limited', 90)
    after = health.update('transport-unavailable', 2)
    assert after['status'] == 'rate-limited' and after['next_attempt'] == first['next_attempt']
    assert not health.permitted()


@pytest.mark.parametrize('state', ['source-unavailable', 'storage-unavailable'])
def test_late_SDK_transport_error_preserves_active_receive_recovery_diagnostic(source, custody, state):
    health = ledger(source, custody); first = health.update(state, 30)
    after = health.update('transport-unavailable', 2)
    assert after['status'] == state and after['next_attempt'] == first['next_attempt'] and not health.permitted()


def test_auth_refusal_survives_republication_with_the_same_key(source, custody):
    health = ledger(source, custody); health.update('authentication-refused')
    other = ledger(source, custody, publication='new-publication')
    assert other.read()['status'] == 'authentication-refused' and not other.permitted()


def test_service_toggles_do_not_turn_a_rejected_project_key_into_a_fresh_credential(source, custody):
    health = ledger(source, custody); health.update('authentication-refused')
    other = ledger(source, custody, publication='new-services', value={**source[0], 'services': ['iMessage', 'SMS']})
    assert other.read()['status'] == 'authentication-refused' and not other.permitted()


def test_legacy_prepared_auth_refusal_is_preserved_without_deleting_original_rows(source, custody):
    from haos.gateway import digest
    health = ledger(source, custody); value = source[0]; db = custody[0].db
    db.execute('UPDATE photon_profile_status SET credential_scope=?,status=? WHERE id=?',
        (digest(value), 'authentication-refused', health.identity))
    other = ledger(source, custody, publication='changed-publication', value={**value, 'services': ['SMS', 'iMessage']})
    assert other.read()['status'] == 'authentication-refused' and not other.permitted()
    assert db.execute('SELECT credential_scope,status FROM photon_profile_status WHERE id=?', (health.identity,)).fetchone()[:] == (digest(value), 'authentication-refused')


def test_actual_sql_failure_rolls_back_both_status_and_account_deadline(source, custody):
    health = ledger(source, custody)
    custody[0].db.execute("CREATE TRIGGER refuse_status BEFORE UPDATE ON photon_profile_status BEGIN SELECT RAISE(ABORT,'fixture status write refusal'); END")
    with pytest.raises(sqlite3.IntegrityError): health.update('rate-limited', 120)
    assert health.read()['status'] == 'created' and health.read()['next_attempt'] == 0
    assert not custody[0].db.in_transaction


def test_authority_loss_can_record_denial_and_cannot_record_a_new_connection(source, custody):
    health = ledger(source, custody)
    def withdrawn(): raise PermissionError('fixture publication withdrawn')
    health.current = withdrawn
    assert health.update('revoked')['status'] == 'revoked'
    with pytest.raises(PermissionError): health.update('local-ready')
    with pytest.raises(PermissionError): health.permitted()


@pytest.mark.parametrize('state,delay', [('invented', 0), ('rate-limited', True), ('rate-limited', float('inf')), ('rate-limited', -1), ('rate-limited', 86401)])
def test_unbounded_or_unknown_state_input_refused(source, custody, state, delay):
    with pytest.raises(ValueError): ledger(source, custody).update(state, delay)


@pytest.fixture
def separated(source, custody, tmp_path):
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    inbox = NativeInbox(tmp_path / 'native.db', Redactor([source[0]['project_secret']]))
    def make(publication='original', value=None):
        return Ledger(inbox, 'phone', value or source[0], publication, custody[2], profile=custody[0])
    yield inbox, make
    inbox.close()


@pytest.mark.parametrize('change', ['status-table', 'budget-table', 'both-tables', 'status-row', 'budget-row', 'budget-key-rotation',
    'credential-row', 'unknown-state', 'invalid-time', 'infinite-budget'])
def test_damaged_persistent_status_cannot_be_recreated_as_a_fresh_account(source, custody, separated, change):
    inbox, make = separated; health = make(); health.update('authentication-refused', 90); db = inbox.db
    value = None
    if change == 'status-table': db.execute('DROP TABLE photon_profile_status')
    elif change == 'budget-table': db.execute('DROP TABLE photon_account_budget')
    elif change == 'both-tables':
        db.execute('DROP TABLE photon_profile_status'); db.execute('DROP TABLE photon_account_budget')
    elif change == 'status-row': db.execute('DELETE FROM photon_profile_status')
    elif change in {'budget-row', 'budget-key-rotation'}:
        db.execute('DELETE FROM photon_account_budget')
        if change == 'budget-key-rotation': value = {**source[0], 'project_secret': secrets.token_urlsafe(32)}
    elif change == 'credential-row': db.execute('UPDATE photon_profile_status SET credential_scope=?', ('f' * 64,))
    elif change == 'unknown-state': db.execute("UPDATE photon_profile_status SET status='private malformed state'")
    elif change == 'invalid-time': db.execute('UPDATE photon_profile_status SET updated_at=?', (float('inf'),))
    elif change == 'infinite-budget': db.execute('UPDATE photon_account_budget SET next_attempt=?', (float('inf'),))
    def snapshot():
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name IN ('photon_profile_status','photon_account_budget')")}
        return {name: [tuple(row) for row in db.execute('SELECT * FROM ' + name)] for name in tables}
    before = snapshot()
    with pytest.raises(Conflict): make('changed-publication', value)
    assert snapshot() == before
    assert custody[0].db.execute('SELECT COUNT(*) FROM photon_health_profiles').fetchone()[0] == 1


def test_original_status_provenance_survives_reopen_key_rotation_and_publication(source, custody, separated):
    inbox, make = separated; first = make(); first.update('rate-limited', 120)
    same = make(); assert same.identity == first.identity and same.read() == first.read()
    changed = make('new', {**source[0], 'project_secret': secrets.token_urlsafe(32)})
    assert changed.read()['next_attempt'] == first.read()['next_attempt'] and not changed.permitted()
    assert custody[0].db.execute('SELECT COUNT(*) FROM photon_health_profiles').fetchone()[0] == 2
    inbox.db.execute('DELETE FROM photon_profile_status WHERE id=?', (first.identity,))
    with pytest.raises(Conflict): make('new', {**source[0], 'project_secret': secrets.token_urlsafe(32)})


def test_missing_status_tables_beside_legacy_native_records_are_not_a_new_empty_account(source, custody, separated):
    inbox, make = separated
    inbox.db.execute('CREATE TABLE photon_output_intents(retained_fixture_id TEXT)')
    with pytest.raises(Conflict, match='retained native'): make()
    assert not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='photon_profile_status'").fetchone()
    assert inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='photon_output_intents'").fetchone()
