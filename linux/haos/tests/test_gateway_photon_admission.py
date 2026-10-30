import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import secrets
import time
import uuid

import pytest

from haos.gateway import GatewayPolicy, SUPPORTED
from haos.gateway_photon import PreparedPhotonPolicy, credentials, scope
from haos.gateway_photon_admission import approve, Refused


@pytest.fixture
def source():
    account = {'project_id': 'fixture-project', 'project_secret': secrets.token_urlsafe(32), 'phone': 'shared', 'services': ['iMessage']}
    binding = {'id': 'phone-owner', 'connector': 'phone', 'identity': 'owner', 'sender': '+15550100001',
        'chat': 'any;-;+15550100001', 'thread': '', 'scope': scope(account), 'capabilities': ['create', 'read'],
        'generation': secrets.token_hex(32), 'since': int(time.time() * 1000) - 10000}
    config = {'version': 1, 'connectors': [{'id': 'phone', 'platform': 'photon'}], 'bindings': [binding]}
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    data = {'phone': 'shared', 'cursor': '1', 'event': {'type': 'message.received', 'sequence': 1,
        'occurredAt': now, 'chatGuid': binding['chat'], 'message': {'guid': str(uuid.uuid4()), 'isFromMe': False,
            'dateCreated': now, 'sender': {'address': binding['sender'], 'service': 'iMessage'},
            'chatGuids': [binding['chat']], 'content': {'text': 'fixture command', 'attachments': []}}}}
    return account, config, data


def admit(source):
    account, config, data = source
    return approve(PreparedPhotonPolicy(config), 'phone', account, json.dumps(data).encode())


def test_exact_project_sender_chat_timed_source(source):
    result = admit(source)
    assert result['envelope']['sender'] == '+15550100001'
    assert result['envelope']['chat'] == 'any;-;+15550100001'
    assert result['envelope']['scope'] == scope(source[0])
    assert result['native_cursor'] == '1'
    assert result['attachment_bytes'] == 0


@pytest.mark.parametrize('change', ['sender', 'missing-sender', 'chat', 'ambiguous-chat', 'outer-chat', 'phone', 'service',
    'self', 'automatic', 'system', 'event', 'cursor', 'bool-sequence', 'missing-time', 'before-grant', 'future', 'thread',
    'unknown-reply', 'display-alias'])
def test_unapproved_source_is_refused_before_native_mapping(source, change):
    data = source[2]; event = data['event']; msg = event['message']
    if change == 'sender': msg['sender']['address'] = '+15550100002'
    elif change == 'missing-sender': msg.pop('sender')
    elif change == 'chat': msg['chatGuids'] = ['any;-;+15550100002']; event['chatGuid'] = msg['chatGuids'][0]
    elif change == 'ambiguous-chat': msg['chatGuids'].append('any;-;+15550100002')
    elif change == 'outer-chat': event['chatGuid'] = 'any;-;+15550100002'
    elif change == 'phone': data['phone'] = '+15550100003'
    elif change == 'service': msg['sender']['service'] = 'SMS'
    elif change == 'self': msg['isFromMe'] = True
    elif change == 'automatic': msg['isAutoReply'] = True
    elif change == 'system': msg['isSystemMessage'] = True
    elif change == 'event': event['type'] = 'message.reactionAdded'
    elif change == 'cursor': data['cursor'] = '2'
    elif change == 'bool-sequence': event['sequence'] = True
    elif change == 'missing-time': msg.pop('dateCreated')
    elif change == 'before-grant': msg['dateCreated'] = '2020-01-01T00:00:00Z'
    elif change == 'future': event['occurredAt'] = '2099-01-01T00:00:00Z'
    elif change == 'thread': msg['threadOriginatorGuid'] = str(uuid.uuid4())
    elif change == 'unknown-reply': msg['replyTargetGuid'] = str(uuid.uuid4())
    elif change == 'display-alias': msg['sender']['address'] = 'Owner'
    with pytest.raises(Refused): admit(source)


def attachment(source):
    part = {'guid': str(uuid.uuid4()), 'fileName': 'fixture.png', 'mimeType': 'image/png', 'totalBytes': 3}
    source[2]['event']['message']['content']['attachments'] = [part]
    source[1]['bindings'][0]['allow_media'] = True
    return part


@pytest.mark.parametrize('change', ['unapproved', 'voice', 'video', 'oversize', 'unknown-size', 'bool-size', 'negative',
    'duplicate', 'path', 'control', 'vcard', 'vcard-application', 'vcard-x-application', 'vcard-extension', 'total', 'too-many'])
def test_media_refusals_precede_download(source, change):
    part = attachment(source); binding = source[1]['bindings'][0]
    if change == 'unapproved': binding.pop('allow_media')
    elif change == 'voice': part['mimeType'] = 'audio/mp4'
    elif change == 'video': part['mimeType'] = 'video/mp4'
    elif change == 'oversize': part['totalBytes'] = 8 * 1024 * 1024 + 1
    elif change == 'unknown-size': part.pop('totalBytes')
    elif change == 'bool-size': part['totalBytes'] = True
    elif change == 'negative': part['totalBytes'] = -1
    elif change == 'duplicate': source[2]['event']['message']['content']['attachments'].append(dict(part))
    elif change == 'path': part['fileName'] = '../../private'
    elif change == 'control': part['fileName'] = 'hidden\nprivate'
    elif change == 'vcard': part['mimeType'] = 'text/vcard'
    elif change == 'vcard-application': part['mimeType'] = 'application/vcard'
    elif change == 'vcard-x-application': part['mimeType'] = 'application/x-vcard'
    elif change == 'vcard-extension': part['fileName'] = 'private.vcf'
    elif change == 'total':
        part['totalBytes'] = 8 * 1024 * 1024
        source[2]['event']['message']['content']['attachments'] += [{**part, 'guid': str(uuid.uuid4())} for _ in range(2)]
    elif change == 'too-many': source[2]['event']['message']['content']['attachments'] = [{**part, 'guid': str(uuid.uuid4())} for _ in range(17)]
    with pytest.raises(Refused): admit(source)


def test_separate_voice_and_video_consents(source):
    part = attachment(source); binding = source[1]['bindings'][0]
    assert admit(source)['attachment_bytes'] == 3
    part['mimeType'] = 'audio/mp4'; binding['allow_voice'] = True
    # The pinned SDK supports audio files as well as native voice-note bubbles.
    # Both need the explicit voice grant; the flag controls the wire type only.
    assert admit(source)['attachment_bytes'] == 3
    source[2]['event']['message']['isAudioMessage'] = True
    assert admit(source)['attachment_bytes'] == 3
    part['mimeType'] = 'video/mp4'; binding['allow_video'] = True
    assert admit(source)['attachment_bytes'] == 3


def test_exact_thread_and_explicit_whole_chat(source):
    thread = str(uuid.uuid4()); source[2]['event']['message']['threadOriginatorGuid'] = thread
    source[1]['bindings'][0]['thread'] = thread
    assert admit(source)['envelope']['thread'] == thread
    source[1]['bindings'][0].update(thread='', all_threads=True)
    assert admit(source)['envelope']['thread'] == thread
    overlapping = copy.deepcopy(source[1]['bindings'][0]); overlapping.update(id='other', thread=thread, all_threads=False)
    source[1]['bindings'].append(overlapping)
    with pytest.raises(ValueError, match='overlapping'): admit(source)


def test_changed_or_relabelled_policy_does_not_gain_authority(source):
    policy = PreparedPhotonPolicy(source[1]); policy.bindings['phone-owner']['sender'] = '+15550100002'
    with pytest.raises(PermissionError, match='unchanged'):
        approve(policy, 'phone', source[0], json.dumps(source[2]).encode())
    assert 'photon' not in SUPPORTED
    with pytest.raises(ValueError): GatewayPolicy(source[1])


@pytest.mark.parametrize('change', ['host', 'node', 'token', 'empty-services', 'unknown-service', 'duplicate-services', 'line'])
def test_private_config_has_no_arbitrary_hosts_programs_or_management_token(source, change):
    account = source[0]
    if change == 'host': account['host'] = 'https://fixture.invalid'
    elif change == 'node': account['node'] = '/tmp/unreviewed'
    elif change == 'token': account['dashboard_token'] = secrets.token_urlsafe()
    elif change == 'empty-services': account['services'] = []
    elif change == 'unknown-service': account['services'] = ['unknown']
    elif change == 'duplicate-services': account['services'] = ['iMessage', 'iMessage']
    elif change == 'line': account['phone'] = 'Owner'
    with pytest.raises(ValueError): credentials(account)


@pytest.fixture
def custody(source, tmp_path):
    from haos.gateway_photon_custody import Originals
    from haos.redaction import Redactor
    tmp_path.chmod(0o700)
    policy = PreparedPhotonPolicy(source[1])
    def current():
        from haos.gateway_photon import checked_policy
        return checked_policy(policy)
    store = Originals(tmp_path / 'photon.db', Redactor([source[0]['project_secret']]), current)
    yield store, policy, current
    store.close()


def decoded(source):
    data = source[2]; binding = source[1]['bindings'][0]
    return {'messageId': data['event']['message']['guid'], 'platform': 'iMessage',
        'space': {'id': binding['chat'], 'type': 'dm', 'phone': source[0]['phone']},
        'sender': {'id': binding['sender']}, 'content': {'type': 'text', 'text': 'fixture command'},
        'timestamp': data['event']['occurredAt']}


def retain(source, custody):
    store, policy, _ = custody
    return store.retain(policy, 'phone', source[0], json.dumps(source[2]).encode())


def test_actual_full_sqlite_two_stage_custody_and_single_parent_receipt(source, custody):
    from haos.gateway import Conflict
    store, policy, _ = custody; key = retain(source, custody)
    assert store.db.execute('PRAGMA synchronous').fetchone()[0] == 2
    row, proof = store.load(key, policy, 'phone', source[0])
    assert json.loads(row['raw']) == source[2]
    assert row['normalized'] == b''
    with pytest.raises(Conflict, match='decoded'):
        store.admitted(key, 'a' * 64, policy, 'phone', source[0])
    raw = json.dumps(decoded(source)).encode()
    store.decode(key, policy, 'phone', source[0], raw)
    store.admitted(key, 'a' * 64, policy, 'phone', source[0])
    store.admitted(key, 'a' * 64, policy, 'phone', source[0])
    with pytest.raises(Conflict, match='another'):
        store.admitted(key, 'b' * 64, policy, 'phone', source[0])
    assert store.load(key, policy, 'phone', source[0])[0]['admitted_receipt'] == 'a' * 64
    assert retain(source, custody) == key


@pytest.mark.parametrize('change', ['sender', 'space', 'mode', 'time', 'id', 'platform', 'text', 'marker', 'extra', 'missing', 'unrequested-file'])
def test_changed_native_projection_has_no_decoded_receipt(source, custody, change):
    from haos.gateway import Conflict
    store, policy, _ = custody; key = retain(source, custody); data = decoded(source)
    if change == 'sender': data['sender']['id'] = '+15550100002'
    elif change == 'space': data['space']['id'] = 'any;-;+15550100002'
    elif change == 'mode': data['space']['phone'] = '+15550100003'
    elif change == 'time': data['timestamp'] = '2020-01-01T00:00:00Z'
    elif change == 'id': data['messageId'] = str(uuid.uuid4())
    elif change == 'platform': data['platform'] = 'another-plugin'
    elif change == 'text': data['content']['text'] = 'substituted command'
    elif change == 'marker': data['content'] = {'type': 'unknown'}
    elif change == 'extra': data['credential'] = 'unexpected field'
    elif change == 'missing': data.pop('sender')
    elif change == 'unrequested-file': data['content'] = {'type': 'attachment'}
    with pytest.raises(Conflict): store.decode(key, policy, 'phone', source[0], json.dumps(data).encode())
    assert store.load(key, policy, 'phone', source[0])[0]['normalized'] == b''


def test_native_bytes_are_exact_bounded_canonical_and_retained_once(source, custody):
    import base64
    from haos.gateway import Conflict
    # Add the grant before constructing this policy; changes to a live object
    # are a withdrawal rather than a way to grant an existing source more rights.
    account, config, data = source; part = attachment(source)
    policy = PreparedPhotonPolicy(config); store = custody[0]
    store.current = lambda: policy
    raw = json.dumps(data).encode(); key = store.retain(policy, 'phone', account, raw)
    projected = decoded(source)
    binary = {'type': 'attachment', 'id': part['guid'], 'name': part['fileName'], 'mimeType': part['mimeType'],
        'size': part['totalBytes'], 'data': base64.b64encode(b'abc').decode(), 'encoding': 'base64'}
    mid = data['event']['message']['guid']
    projected['content'] = {'type': 'group', 'items': [{'id': 'p:0/' + mid, 'content': binary}, {'id': 'p:1/' + mid, 'content': projected['content']}]}
    encoded = json.dumps(projected).encode(); store.decode(key, policy, 'phone', account, encoded)
    row, _ = store.load(key, policy, 'phone', account)
    assert json.loads(row['parts'])[part['guid']]['size'] == 3
    assert row['normalized'] == encoded
    binary['data'] = base64.b64encode(b'xyz').decode()
    with pytest.raises(Conflict, match='replay changed'): store.decode(key, policy, 'phone', account, json.dumps(projected).encode())


@pytest.mark.parametrize('change', ['missing-bytes', 'truncated', 'size', 'foreign-id', 'mime', 'duplicate'])
def test_native_binary_failure_never_becomes_successful_metadata_marker(source, custody, change):
    import base64
    from haos.gateway import Conflict
    part = attachment(source); policy = PreparedPhotonPolicy(source[1]); store = custody[0]; store.current = lambda: policy
    key = store.retain(policy, 'phone', source[0], json.dumps(source[2]).encode())
    data = decoded(source)
    binary = {'type': 'attachment', 'id': part['guid'], 'name': part['fileName'], 'mimeType': part['mimeType'],
        'size': 3, 'data': base64.b64encode(b'abc').decode(), 'encoding': 'base64'}
    if change == 'missing-bytes': binary.pop('data')
    elif change == 'truncated': binary['data'] = base64.b64encode(b'ab').decode()
    elif change == 'size': binary['size'] = True
    elif change == 'foreign-id': binary['id'] = str(uuid.uuid4())
    elif change == 'mime': binary['mimeType'] = 'video/mp4'
    mid = source[2]['event']['message']['guid']
    data['content'] = {'type': 'group', 'items': [{'id': 'p:0/' + mid, 'content': binary}, {'id': 'p:1/' + mid, 'content': data['content']}]}
    if change == 'duplicate': data['content']['items'].append({'id': 'duplicate', 'content': dict(binary)})
    with pytest.raises(Conflict): store.decode(key, policy, 'phone', source[0], json.dumps(data).encode())
    assert store.load(key, policy, 'phone', source[0])[0]['normalized'] == b''


def test_real_sql_failure_rolls_back_normalized_custody(source, custody):
    import sqlite3
    store, policy, _ = custody; key = retain(source, custody)
    store.db.execute("CREATE TRIGGER refuse_fixture_decode BEFORE UPDATE OF normalized ON photon_originals BEGIN SELECT RAISE(ABORT,'fixture durable write refusal'); END")
    with pytest.raises(sqlite3.IntegrityError, match='durable write refusal'):
        store.decode(key, policy, 'phone', source[0], json.dumps(decoded(source)).encode())
    assert not store.db.in_transaction
    row, _ = store.load(key, policy, 'phone', source[0])
    assert row['normalized'] == b'' and row['admitted_receipt'] == ''


def test_sqlite_reopen_preserves_original_and_native_projection(source, custody, tmp_path):
    from haos.gateway_photon_custody import Originals
    store, policy, current = custody; key = retain(source, custody)
    raw = json.dumps(decoded(source)).encode(); store.decode(key, policy, 'phone', source[0], raw)
    reopened = Originals(tmp_path / 'photon.db', store.store.redactor, current)
    try:
        assert reopened.load(key, policy, 'phone', source[0])[0]['normalized'] == raw
        assert reopened.retain(policy, 'phone', source[0], json.dumps(source[2]).encode()) == key
    finally: reopened.close()


@pytest.mark.parametrize('change', ['account', 'credential', 'grant', 'original', 'normalized'])
def test_retained_source_cannot_move_to_changed_identity_epoch_grant_or_body(source, custody, change):
    from haos.gateway import Conflict
    store, policy, _ = custody; key = retain(source, custody)
    store.decode(key, policy, 'phone', source[0], json.dumps(decoded(source)).encode())
    account = copy.deepcopy(source[0])
    if change == 'account': account['project_id'] = 'another-project'
    elif change == 'credential': account['project_secret'] = secrets.token_urlsafe(32)
    elif change == 'grant': policy.bindings['phone-owner']['capabilities'] = ['create']
    elif change == 'original': store.db.execute('UPDATE photon_originals SET raw=? WHERE id=?', (b'{}', key))
    elif change == 'normalized': store.db.execute('UPDATE photon_originals SET normalized=? WHERE id=?', (b'{}', key))
    with pytest.raises((PermissionError, Conflict)):
        store.load(key, policy, 'phone', account)


@pytest.mark.parametrize('change', ['none', 'order', 'child-id', 'text', 'trim-0085', 'nested-group', 'extra-reply'])
def test_native_mixed_order_and_javascript_whitespace_are_exact(source, custody, change):
    import base64
    from haos.gateway import Conflict
    part = attachment(source); source[2]['event']['message']['content']['text'] = '\ufeff\u0085first \ufffc second\ufeff'
    policy = PreparedPhotonPolicy(source[1]); store = custody[0]; store.current = lambda: policy
    key = store.retain(policy, 'phone', source[0], json.dumps(source[2]).encode()); mid = source[2]['event']['message']['guid']
    data = decoded(source)
    contents = [{'type': 'text', 'text': '\u0085first'}, {'type': 'attachment', 'id': part['guid'], 'name': part['fileName'],
        'mimeType': part['mimeType'], 'size': 3, 'data': base64.b64encode(b'abc').decode(), 'encoding': 'base64'}, {'type': 'text', 'text': 'second'}]
    data['content'] = {'type': 'group', 'items': [{'id': 'p:' + str(i) + '/' + mid, 'content': c} for i, c in enumerate(contents)]}
    items = data['content']['items']
    if change == 'order': items[0]['content'], items[1]['content'] = items[1]['content'], items[0]['content']
    elif change == 'child-id': items[0]['id'] = 'foreign-part'
    elif change == 'text': items[0]['content']['text'] = '\u0085first modified'
    elif change == 'trim-0085': items[0]['content']['text'] = 'first'
    elif change == 'nested-group': items[0]['content'] = {'type': 'group', 'items': []}
    elif change == 'extra-reply': data['content'] = {'type': 'reply', 'targetMessageId': str(uuid.uuid4()), 'content': data['content']}
    raw = json.dumps(data).encode()
    if change == 'none':
        store.decode(key, policy, 'phone', source[0], raw)
        assert store.load(key, policy, 'phone', source[0])[0]['normalized'] == raw
    else:
        with pytest.raises(Conflict): store.decode(key, policy, 'phone', source[0], raw)
        assert store.load(key, policy, 'phone', source[0])[0]['normalized'] == b''
