"""Real source/capability SQLite state machine; no native SDK or external send."""
import json
import secrets
import sqlite3
import time
from types import SimpleNamespace
import uuid

import pytest

from test_gateway_photon_admission import source, custody, decoded, retain
from haos.gateway import Conflict, digest
from haos.gateway_photon_outbox import Journal
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def outbox(source, custody, tmp_path):
    originals, policy, current = custody; original_id = retain(source, custody)
    originals.decode(original_id, policy, 'phone', source[0], json.dumps(decoded(source)).encode())
    original, proof = originals.load(original_id, policy, 'phone', source[0])
    envelope = {**proof['envelope'], 'text': 'fixture command'}
    inbox = NativeInbox(tmp_path / 'native.db', Redactor([source[0]['project_secret']]))
    key = inbox.admit(policy, 'phone', envelope, {'raw_id': original_id}, received_at=proof['received_at'])
    inbox.claim(key, policy)
    inbox.complete(key, True)
    # Explicit component input contract; the full native profile probe creates
    # this projection through the actual SDK/codec ingress, without this setup.
    inbox.db.execute('''CREATE TABLE photon_native_projection(source_key TEXT PRIMARY KEY,raw_id TEXT,
        raw_sha256 TEXT,normalized_sha256 TEXT,binding_digest TEXT,credential_scope TEXT,envelope_sha256 TEXT)''')
    inbox.db.execute('INSERT INTO photon_native_projection VALUES(?,?,?,?,?,?,?)',
        (key, original_id, original['raw_sha256'], original['normalized_sha256'], proof['binding_digest'], proof['credential_scope'], digest(envelope)))
    originals.admitted(original_id, digest(['phone', *(envelope[k] for k in ['scope', 'chat', 'thread', 'message_id'])]), policy, 'phone', source[0])
    journal = Journal(inbox, originals, 'phone', source[0], lambda: policy, current)
    route = policy.bindings[proof['binding_id']]
    args = [route, secrets.token_hex(32), 1, envelope['message_id'], '', 'approved reply', 'approved reply', digest('controller context')]
    yield SimpleNamespace(journal=journal, args=args, native_key=key, original_id=original_id, inbox=inbox)
    inbox.close()


def test_single_actual_SQL_consumption_before_confirmed_receipt(outbox):
    item = outbox.journal.prepare(*outbox.args)
    assert item['state'] == 'prepared'
    assert outbox.inbox.db.execute('SELECT state FROM photon_output_intents').fetchone()[0] == 'prepared'
    assert outbox.journal.consume(item['wire']) == {'approved': True}
    with pytest.raises(PermissionError): outbox.journal.consume(item['wire'])
    receipt = str(uuid.uuid4())
    assert outbox.journal.result(outbox.args[1], 1, receipt) == 'confirmed'
    assert outbox.journal.prepare(*outbox.args) == {'state': 'confirmed', 'receipt': receipt}


def test_no_vendor_receipt_can_confirm_an_unconsumed_permission(outbox):
    outbox.journal.prepare(*outbox.args)
    with pytest.raises(Conflict): outbox.journal.result(outbox.args[1], 1, str(uuid.uuid4()))
    assert not outbox.inbox.db.in_transaction


def test_atomic_cancel_of_pending_capability_makes_late_consumption_impossible(outbox):
    item = outbox.journal.prepare(*outbox.args)
    assert outbox.journal.result(outbox.args[1], 1) == 'not-dispatched'
    with pytest.raises(PermissionError): outbox.journal.consume(item['wire'])
    args = list(outbox.args); args[2] = 2
    retry = outbox.journal.prepare(*args)
    assert retry['wire']['haosCapability'] != item['wire']['haosCapability']
    assert outbox.journal.consume(retry['wire']) == {'approved': True}


def test_consumed_write_without_receipt_is_never_automatically_resent(outbox):
    item = outbox.journal.prepare(*outbox.args); outbox.journal.consume(item['wire'])
    assert outbox.journal.result(outbox.args[1], 1) == 'uncertain'
    for attempt in [1, 2, 5]:
        args = list(outbox.args); args[2] = attempt
        assert outbox.journal.prepare(*args) == {'state': 'uncertain'}


@pytest.mark.parametrize('consumed,expected', [(False, 'not-dispatched'), (True, 'uncertain')])
def test_reopened_journal_preserves_possible_side_effect_without_reissuing_old_permission(outbox, consumed, expected):
    item = outbox.journal.prepare(*outbox.args)
    if consumed: outbox.journal.consume(item['wire'])
    old = outbox.journal
    fresh = Journal(outbox.inbox, old.originals, old.connector, old.value, old.policy, old.current)
    assert outbox.inbox.db.execute('SELECT state FROM photon_output_intents').fetchone()[0] == expected
    with pytest.raises(PermissionError): fresh.consume(item['wire'])


@pytest.mark.parametrize('field,new', [('text', 'different reply'), ('spaceId', 'any;-;+15550100009'),
    ('replyTo', 'spc-foreign-source'), ('format', 'markdown'), ('haosCapability', '0' * 64)])
def test_native_wire_changes_cannot_consume_permission(outbox, field, new):
    item = outbox.journal.prepare(*outbox.args); wire = {**item['wire'], field: new}
    with pytest.raises(PermissionError): outbox.journal.consume(wire)
    assert outbox.inbox.db.execute('SELECT state FROM photon_output_intents').fetchone()[0] == 'prepared'


def test_expired_permission_cannot_reach_native_write(outbox):
    item = outbox.journal.prepare(*outbox.args)
    outbox.inbox.db.execute('UPDATE photon_output_intents SET expires_at=?', (time.time() - 1,))
    with pytest.raises(PermissionError): outbox.journal.consume(item['wire'])


def test_actual_SQL_write_failure_does_not_acknowledge_consumption(outbox):
    item = outbox.journal.prepare(*outbox.args)
    outbox.inbox.db.execute("CREATE TRIGGER refuse_consumption BEFORE UPDATE ON photon_output_intents BEGIN SELECT RAISE(ABORT,'fixture write refusal'); END")
    with pytest.raises(sqlite3.IntegrityError): outbox.journal.consume(item['wire'])
    assert outbox.inbox.db.execute('SELECT state FROM photon_output_intents').fetchone()[0] == 'prepared'
    assert not outbox.inbox.db.in_transaction


@pytest.mark.parametrize('column,new', [('native_state', 'pending'), ('raw_sha256', '0' * 64),
    ('normalized_sha256', '0' * 64), ('credential_scope', '0' * 64), ('binding_digest', '0' * 64), ('envelope_sha256', '0' * 64)])
def test_missing_or_changed_completed_source_denies_outgoing_intent(outbox, column, new):
    if column == 'native_state': outbox.inbox.db.execute('UPDATE native_inbox SET state=?', (new,))
    else: outbox.inbox.db.execute('UPDATE photon_native_projection SET ' + column + '=?', (new,))
    with pytest.raises(PermissionError): outbox.journal.prepare(*outbox.args)
    assert outbox.inbox.db.execute('SELECT COUNT(*) FROM photon_output_intents').fetchone()[0] == 0


def test_withdrawal_denies_pending_capability_but_does_not_erase_consumed_write(outbox):
    item = outbox.journal.prepare(*outbox.args); outbox.journal.consume(item['wire'])
    def withdrawn(): raise PermissionError('fixture owner withdrew authority')
    outbox.journal.current = withdrawn
    with pytest.raises(PermissionError): outbox.journal.prepare(*outbox.args)
    assert outbox.journal.result(outbox.args[1], 1) == 'uncertain'


def test_reusing_delivery_identity_for_changed_body_is_refused(outbox):
    outbox.journal.prepare(*outbox.args)
    args = list(outbox.args); args[5] = args[6] = 'changed body'
    with pytest.raises(Conflict): outbox.journal.prepare(*args)


def test_delivery_authority_requires_explicit_whole_thread_grant_and_validated_policy(source):
    from copy import deepcopy
    from haos.gateway_delivery_authority import current_delivery
    from haos.gateway_photon import PreparedPhotonPolicy
    config = deepcopy(source[1]); config['bindings'][0]['all_threads'] = True
    policy = PreparedPhotonPolicy(config); binding = next(iter(policy.bindings.values()))
    adapter = SimpleNamespace(_haos_native=SimpleNamespace(connector='phone', policy=lambda: policy))
    metadata = {'haos_scope': binding['scope'], 'haos_binding': {'binding_id': binding['id'], 'binding_digest': digest(binding)},
        'thread_id': str(uuid.uuid4())}
    operation = current_delivery(adapter, 'photon', binding['chat'], metadata); operation()
    config['bindings'][0]['all_threads'] = False
    latest = PreparedPhotonPolicy(config); adapter._haos_native.policy = lambda: latest
    with pytest.raises(PermissionError): operation()
    metadata['haos_binding']['binding_digest'] = digest(next(iter(latest.bindings.values())))
    with pytest.raises(PermissionError): current_delivery(adapter, 'photon', binding['chat'], metadata)
