#!/usr/bin/env python3
"""Actual private profile, Node SDK and TLS/protobuf loopback peers.

Run only as PID 1 of a fresh network-disabled container. Public installed code
is copied into that namespace; SDK endpoint literals are replaced only there.
No cloud account, external delivery, controller or installed OS is claimed.
"""
import asyncio
import base64
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def private_identity():
    os.setgroups([]); os.setresgid(65534, 65534, 65534); os.setresuid(65534, 65534, 65534)
    assert ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) == 0


async def worker(directory):
    sys.path[:0] = ['/usr/lib/haos', '/usr/lib/haos/hermes', '/opt/fixture-deps']
    from haos.gateway_photon import PreparedPhotonPolicy, scope
    from haos.gateway_photon_profile import build
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    root = Path(directory); config = json.loads((root / 'worker.json').read_text()); value = config['account']
    binding = {'id': 'phone-owner', 'connector': 'phone', 'identity': 'owner', 'sender': '+15550100001',
        'chat': 'any;-;+15550100001', 'thread': '', 'scope': scope(value), 'capabilities': ['create', 'read'],
        'generation': secrets.token_hex(32), 'since': config['since']}
    policy = PreparedPhotonPolicy({'version': 1, 'connectors': [{'id': 'phone', 'platform': 'photon'}], 'bindings': [binding]})
    active = [True]
    def current():
        if not active[0]: raise PermissionError('fixture independent owner withdrew authority')
        return policy
    redactor = Redactor([value['project_secret']]); inbox = NativeInbox(root / 'inbox.db', redactor)
    relay = RelayInbox(root / 'relay.db', redactor); parent = root / 'profiles'; parent.mkdir(mode=0o700)
    if config['scenario'].startswith('media-') and config['scenario'] != 'media-unapproved':
        binding.update(allow_media=True, allow_voice=True)
        policy = PreparedPhotonPolicy({'version': 1, 'connectors': [{'id': 'phone', 'platform': 'photon'}], 'bindings': [binding]})
    adapter = build(value, parent=parent, connector='phone', policy=current, inbox=inbox)
    observed = []; observed_media = []
    def accept(event):
        from haos.gateway_media_relay import event_media
        envelope = adapter_envelope(event, 'photon'); media = event_media(event, 'photon') if event.media_urls else []
        relay.admit(current(), 'phone', envelope, media=media); observed_media.append(media)
        observed.append(envelope); return True
    adapter.set_durable_message_handler(accept)
    try:
        connected = await adapter.connect()
        scenario = config['scenario']
        if scenario not in {'normal', 'dedicated', 'health-withdraw'} and not scenario.startswith(('reply-', 'media-')):
            if connected: (root / 'emit').write_text('emit fixture native refusal')
            expected = 'identity-refused' if scenario == 'wrong-line' else 'rate-limited' if scenario.endswith('429') else 'authentication-refused'
            deadline = time.monotonic() + 10
            while adapter.is_connected or adapter._haos_photon_health.recorded()['status'] != expected:
                assert time.monotonic() < deadline, (scenario, adapter._haos_photon_health.recorded())
                await asyncio.sleep(.01)
            health = adapter._haos_photon_health.recorded()
            assert health['status'] == expected
            if expected == 'rate-limited': assert health['next_attempt'] > time.time() + 50
            counts = json.loads((root / 'counts.json').read_text())
            token_calls = counts['http'].get('POST /projects/fixture-project/imessage/tokens', 0)
            assert token_calls >= (2 if scenario.startswith('refresh') else 1)
            assert not observed and relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
            assert not any(Path('/tmp').glob('hp-*/control.sock'))
            assert await adapter.connect() is False
            await adapter.close()
            reopened = build(value, parent=parent, connector='phone', policy=current, inbox=inbox)
            try: assert await reopened.connect() is False
            finally: await reopened.close()
            await asyncio.sleep(.1)
            assert json.loads((root / 'counts.json').read_text())['http'] == counts['http']
            return {'passed': 5, 'scenario': scenario, 'cases': ['actual_native_SDK_refusal_recorded_finitely',
                'actual_Node_stopped_after_refusal', 'no_source_or_parent_delivery',
                'same_instance_cannot_retry_around_budget_or_terminal_state', 'reopened_profile_cannot_retry_around_persisted_refusal'],
                'counts': counts, 'live_Photon_verified': False, 'controller_IPC_verified': False, 'OS_release_artifact': False}
        assert connected, adapter._haos_photon_health.recorded()
        assert adapter.is_connected
        if scenario == 'media-storage-refusal':
            adapter._haos_photon_originals.db.execute("CREATE TRIGGER refuse_decoded_custody BEFORE UPDATE OF normalized ON photon_originals BEGIN SELECT RAISE(ABORT,'fixture durable source write refusal'); END")
        (root / 'emit').write_text('emit fixture frames')
        if scenario in {'media-unapproved', 'media-truncated', 'media-withdraw', 'media-storage-refusal'}:
            deadline = time.monotonic() + 6
            if scenario == 'media-withdraw':
                while not (root / 'download-observed').exists():
                    assert time.monotonic() < deadline, 'actual attachment RPC did not open'
                    await asyncio.sleep(.01)
                active[0] = False
            elif scenario == 'media-unapproved':
                while adapter._haos_photon_cursor.resume() != '2':
                    assert time.monotonic() < deadline, 'refused native media did not finish durable cursor processing'
                    await asyncio.sleep(.01)
            else:
                while adapter.is_connected:
                    assert time.monotonic() < deadline, 'truncated native attachment did not stop the failed transport'
                    await asyncio.sleep(.01)
            if scenario == 'media-unapproved': active[0] = False
            while adapter.is_connected:
                assert time.monotonic() < deadline, 'actual media withdrawal did not stop Node'
                await asyncio.sleep(.01)
            counts = json.loads((root / 'counts.json').read_text())
            if scenario == 'media-storage-refusal': assert adapter._haos_photon_health.recorded()['status'] == 'storage-unavailable'
            assert not observed and relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 0
            originals = adapter._haos_photon_originals.db
            rows = originals.execute('SELECT length(normalized) AS normalized_bytes FROM photon_originals').fetchall()
            if scenario == 'media-unapproved':
                assert counts['grpc'].get('DownloadAttachment', 0) == 0 and not rows
            else:
                assert counts['grpc']['DownloadAttachment'] == 1 and len(rows) == 1 and rows[0]['normalized_bytes'] == 0
                assert originals.execute('SELECT safe FROM photon_resume').fetchone()[0] == 1
            return {'passed': 5, 'scenario': scenario, 'cases': ['actual_native_attachment_TLS_gRPC_source_and_policy',
                'unknown_sender_or_missing_media_consent_cannot_fetch', 'failed_or_withdrawn_media_has_no_native_or_parent_receipt',
                'durable_cursor_does_not_skip_unfinished_original', 'actual_Node_stops_on_failed_or_revoked_media'],
                'counts': counts, 'live_Photon_verified': False, 'controller_IPC_verified': False, 'OS_release_artifact': False}
        deadline = time.monotonic() + 12
        while not observed:
            if time.monotonic() >= deadline:
                raise AssertionError({'status': adapter._haos_photon_health.recorded(),
                    'counts': json.loads((root / 'counts.json').read_text()),
                    'originals': [dict(row) for row in adapter._haos_photon_originals.db.execute('SELECT id,length(normalized) AS bytes FROM photon_originals')]})
            await asyncio.sleep(.025)
        await asyncio.sleep(.3)
        assert len(observed) == 1
        if scenario.startswith('media-'): assert 'approved actual protobuf message' in observed[0]['text']
        else: assert observed[0]['text'] == 'approved actual protobuf message'
        assert observed[0]['message_id'] == config['message_id']
        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 1
        originals = adapter._haos_photon_originals.db
        assert originals.execute('SELECT COUNT(*) FROM photon_originals').fetchone()[0] == 1
        assert originals.execute('SELECT COUNT(*) FROM photon_refusals').fetchone()[0] == 1
        assert len(originals.execute('SELECT admitted_receipt FROM photon_originals').fetchone()[0]) == 64
        assert adapter._haos_photon_cursor.resume() == '2'
        if scenario == 'dedicated':
            counts = json.loads((root / 'counts.json').read_text())
            assert counts['grpc']['SubscribeMessageEvents'] == 1
            assert counts['grpc']['SubscribeGroupEvents'] == 1
            assert counts['grpc']['SubscribePollEvents'] == 1
        reply_checks = []
        if scenario.startswith('media-'):
            from haos.gateway_media_relay import MediaCache
            assert len(observed_media) == 1 and len(observed_media[0]) == 1
            media = MediaCache(inbox).get(current(), observed_media[0][0])
            assert media['descriptor']['sha256'] == config['media_sha256'] and hashlib.sha256(media['data']).hexdigest() == config['media_sha256']
            assert json.loads(relay.db.execute('SELECT media FROM inbox').fetchone()[0]) == observed_media[0]
            counts = json.loads((root / 'counts.json').read_text())
            assert counts['grpc']['DownloadAttachment'] == 1
            reply_checks += ['actual_native_attachment_stream_and_codec_preserve_exact_private_bytes',
                'durable_parent_receipt_includes_only_source_bound_opaque_media_identity', 'unknown_sender_and_replay_do_not_repeat_attachment_RPC']
        if scenario == 'health-withdraw':
            # Stop the actual Node process and observe the real Python health
            # coroutine waiting for its response. No mock, artificial health
            # method or weakened revocation deadline is used.
            nodes = []
            for entry in Path('/proc').iterdir():
                if not entry.name.isdecimal(): continue
                try:
                    status = (entry / 'status').read_text()
                    if '\nUid:\t65534\t65534\t65534\t65534\n' not in status: continue
                    args = (entry / 'cmdline').read_bytes().split(b'\0')
                except (FileNotFoundError, PermissionError, ProcessLookupError): continue
                if args[0] == b'/usr/lib/haos/photon/node' and b'/usr/lib/haos/photon/photon_sidecar.mjs' in args:
                    nodes.append(int(entry.name))
            assert len(nodes) == 1
            os.kill(nodes[0], signal.SIGSTOP)
            deadline = time.monotonic() + 5
            while True:
                waiting = False
                for task in asyncio.all_tasks():
                    names = []; awaited = task.get_coro()
                    while awaited is not None:
                        code = getattr(awaited, 'cr_code', None)
                        if code is not None: names.append(code.co_name)
                        awaited = getattr(awaited, 'cr_await', None)
                    if 'monitor' in names and 'local_call' in names: waiting = True
                if waiting: break
                assert time.monotonic() < deadline, 'real network health coroutine did not enter its blocked call'
                await asyncio.sleep(.01)
            reply_checks.append('actual_SIGSTOP_Node_health_wait_cannot_delay_independent_owner_withdrawal')
        if scenario.startswith('reply-'):
            from haos.gateway import digest
            text = 'approved native reply'
            event_context = {'version': 1, 'mission_id': 'fixture-mission', 'kind': 'mission.completed',
                'source_event': config['message_id'], 'state': 'completed', 'phase': 'finished',
                'request_id': None, 'request_method': None, 'part': 0, 'parts': 1, 'total_bytes': len(text.encode()),
                'content_sha256': hashlib.sha256(text.encode()).hexdigest(), 'group_sha256': hashlib.sha256(text.encode()).hexdigest()}
            metadata = {'notify': True, 'haos_scope': binding['scope'],
                'haos_binding': {'binding_id': binding['id'], 'binding_digest': digest(binding)},
                'haos_delivery_id': secrets.token_hex(32), 'haos_delivery_attempt': 1, 'haos_event_context': event_context}
            for method, args in [('send_image', (binding['chat'], 'https://unapproved.invalid/image.png')),
                    ('send_document', (binding['chat'], '/unapproved-host-path/fixture.txt')),
                    ('_sidecar_call', ('/send', {'spaceId': binding['chat'], 'text': text}))]:
                try: await getattr(adapter, method)(*args)
                except PermissionError: pass
                else: raise AssertionError('unreviewed native output escaped its early capability boundary')
            reply_checks.append('implicit_URL_file_and_direct_transport_writes_refused_before_IO')
            for changed_chat, changed_source in [(binding['chat'], 'spc-foreign-source'), ('any;-;+15550100009', config['message_id'])]:
                try: await adapter.send(changed_chat, text, reply_to=changed_source, metadata=metadata)
                except PermissionError: pass
                else: raise AssertionError('changed native output recipient/source admitted')
            reply_checks.append('changed_recipient_and_unretained_source_refused_before_native_write')
            if scenario == 'reply-sql-refusal':
                inbox.db.execute("CREATE TRIGGER refuse_output_consumption BEFORE UPDATE ON photon_output_intents WHEN NEW.state='writing' BEGIN SELECT RAISE(ABORT,'fixture write gate failure'); END")
            pending = asyncio.create_task(adapter.send(binding['chat'], text, reply_to=config['message_id'], metadata=metadata))
            if scenario == 'reply-withdraw':
                deadline = time.monotonic() + 5
                while not (root / 'write-observed').exists():
                    assert time.monotonic() < deadline, 'actual native write did not reach peer'
                    await asyncio.sleep(.01)
                active[0] = False
            result = await asyncio.wait_for(pending, 6)
            counts = json.loads((root / 'counts.json').read_text())
            state = inbox.db.execute('SELECT state FROM photon_output_intents').fetchone()[0]
            if scenario in {'reply-confirmed', 'reply-restart'}:
                assert result.success is True and result.message_id == config['reply_receipt'] and state == 'confirmed'
                again = await adapter.send(binding['chat'], text, reply_to=config['message_id'], metadata=metadata)
                assert again.success is True and again.message_id == result.message_id
                assert len(json.loads((root / 'counts.json').read_text())['writes']) == 1
                assert counts['grpc']['SendTextMessage'] == 1 and len(counts['writes']) == 1
                reply_checks += ['actual_native_Python_sidecar_SDK_reply_builder_and_protobuf_wire', 'confirmed_receipt_replay_does_not_issue_second_RPC']
                if scenario == 'reply-restart':
                    await adapter.close()
                    adapter = build(value, parent=parent, connector='phone', policy=current, inbox=inbox)
                    adapter.set_durable_message_handler(accept)
                    assert await adapter.connect(), adapter._haos_photon_health.recorded()
                    after_restart = await adapter.send(binding['chat'], text, reply_to=config['message_id'], metadata=metadata)
                    assert after_restart.success is True and after_restart.message_id == config['reply_receipt']
                    counts = json.loads((root / 'counts.json').read_text())
                    assert counts['grpc']['SendTextMessage'] == 1 and len(counts['writes']) == 1
                    assert counts['http']['POST /projects/fixture-project/imessage/tokens'] == 2
                    reply_checks += ['actual_Node_profile_database_reopen_preserves_confirmed_receipt', 'confirmed_reply_after_process_restart_has_no_new_native_write']
            elif scenario == 'reply-sql-refusal':
                assert result.success is False and result.raw_response['haos_delivery'] == 'not-dispatched' and state == 'not-dispatched'
                assert not counts['writes'] and counts['grpc'].get('SendTextMessage', 0) == 0
                reply_checks += ['actual_SQL_gate_failure_prevents_any_native_RPC', 'unconsumed_write_permission_atomically_cancelled']
            else:
                assert result.success is False and result.raw_response['haos_delivery'] == 'uncertain' and state == 'uncertain'
                assert counts['grpc']['SendTextMessage'] == 1 and len(counts['writes']) == 1
                if scenario in {'reply-disconnect', 'reply-reset'}:
                    deadline = time.monotonic() + 3
                    while adapter.is_connected:
                        assert time.monotonic() < deadline, 'native write error ignored by supervisor'
                        await asyncio.sleep(.01)
                    for attempt in [1, 2]:
                        assert adapter._haos_photon_publisher.journal.prepare(binding, metadata['haos_delivery_id'], attempt,
                            config['message_id'], '', text, text, digest(event_context)) == {'state': 'uncertain'}
                if scenario == 'reply-reset':
                    assert counts['transport_resets'] == 1
                    reply_checks.append('actual_TLS_connection_loss_after_write_does_not_replay_RPC_to_live_peer')
                reply_checks += ['actual_peer_write_without_receipt_remains_uncertain', 'no_automatic_native_RPC_retry_or_resend']
        active[0] = False
        if not adapter.is_connected: await adapter.disconnect()
        deadline = time.monotonic() + 2
        while adapter.is_connected:
            assert time.monotonic() < deadline, 'actual profile ignored owner withdrawal'
            await asyncio.sleep(.01)
        assert adapter._haos_photon_health.recorded()['status'] == 'revoked'
        assert not any(Path('/tmp').glob('hp-*/control.sock'))
        return {'passed': 7 + len(reply_checks), 'scenario': scenario, 'cases': ['actual_private_UID_Node_TLS_HTTP_auth_and_protobuf_gRPC',
            'unknown_sender_hash_only_refusal_before_native_mapping', 'approved_native_SDK_sidecar_Python_codec_durable_relay',
            'duplicate_native_message_exactly_one_parent_row', 'original_and_native_custody_have_parent_receipt',
            'actual_native_stream_advances_durable_cursor',
            'owner_withdrawal_keeps_failed_transport_revoked' if scenario in {'reply-disconnect', 'reply-reset'} else 'owner_withdrawal_stops_actual_Node_and_Unix_control', *reply_checks],
            'counts': json.loads((root / 'counts.json').read_text()), 'live_Photon_verified': False,
            'controller_IPC_verified': False, 'OS_release_artifact': False}
    finally:
        await adapter.close(); inbox.close(); relay.close()


def main():
    if os.geteuid() != 0 or os.getpid() != 1 or os.environ.get('HAOS_DISPOSABLE_PHOTON_PROFILE') != '1':
        raise PermissionError('fresh disposable PID-1 network-disabled profile fixture required')
    scenario = sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == '--case' else 'normal'
    if scenario not in {'normal', 'dedicated', 'health-withdraw', 'http401', 'http403', 'http429', 'grpc401', 'grpc429', 'wrong-line', 'refresh401', 'refresh429',
            'reply-confirmed', 'reply-restart', 'reply-disconnect', 'reply-reset', 'reply-sql-refusal', 'reply-withdraw'}:
        if scenario not in {'media-image', 'media-document', 'media-voice-caf', 'media-truncated', 'media-withdraw', 'media-unapproved', 'media-storage-refusal'}:
            raise ValueError('finite fixture case required')
    root = Path('/usr/lib/haos'); root.mkdir(mode=0o755)
    # Public package sources only. Never broaden permissions on the checkout,
    # provider identity, owner home or mounted frozen dependency environment.
    shutil.copytree('/deps', '/opt/fixture-deps', ignore=shutil.ignore_patterns('__pycache__'), copy_function=shutil.copyfile)
    shutil.copytree('/repo/upstream/hermes-agent', root / 'hermes', ignore=shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__'), copy_function=shutil.copyfile)
    shutil.copytree('/input/hermes', root / 'hermes', dirs_exist_ok=True, copy_function=shutil.copyfile)
    shutil.copytree('/repo/linux/haos/haos', root / 'haos', ignore=shutil.ignore_patterns('__pycache__'), copy_function=shutil.copyfile)
    baseline = Path('/baseline/profile.py')
    if baseline.exists():
        # Regression comparison only: a read-only public prior source module
        # inside this disposable namespace, never a production loading hook.
        shutil.copyfile(baseline, root / 'haos/gateway_photon_profile.py')
    shutil.copytree('/input/photon', root / 'photon', copy_function=shutil.copyfile)
    # Exercise the CURRENT fixed launcher, not yesterday's installed fixture.
    for name in ['photon_sidecar.mjs', 'photon_bounded_stream.mjs', 'photon_cloud.mjs']:
        shutil.copyfile('/repo/linux/haos/runtime/' + name, root / 'photon' / name)
    fixtures = root / 'fixtures'; fixtures.mkdir()
    shutil.copyfile(__file__, fixtures / 'profile.py')
    shutil.copyfile('/repo/linux/haos/runtime/photon_protocol_fixture.mjs', fixtures / 'protocol.mjs')
    for base in [root, Path('/opt/fixture-deps')]:
        base.chmod(0o755)
        for entry in base.rglob('*'):
            if not entry.is_symlink(): entry.chmod(0o755 if entry.is_dir() else 0o644)
    (root / 'photon/node').chmod(0o755)
    sys.path.insert(0, '/opt/fixture-deps')
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    directory = Path(tempfile.mkdtemp(prefix='photon-profile-', dir='/tmp')); directory.chmod(0o700)
    now = datetime.now(timezone.utc); name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Photon loopback fixture')])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256()))
    serverkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    servername = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Photon loopback server')])
    cert = (x509.CertificateBuilder().subject_name(servername).issuer_name(name).public_key(serverkey.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True).sign(key, hashes.SHA256()))
    (directory / 'server.key').write_bytes(serverkey.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (directory / 'server.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    anchor = Path('/usr/local/share/ca-certificates/haos-photon-fixture.crt')
    anchor.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    subprocess.run(['/usr/sbin/update-ca-certificates'], check=True, capture_output=True)
    account = {'project_id': 'fixture-project', 'project_secret': secrets.token_urlsafe(32), 'phone': 'shared', 'services': ['iMessage']}
    if scenario in {'dedicated', 'wrong-line'}: account['phone'] = '+15550100002'
    native_token = secrets.token_urlsafe(32); mid = 'spc-' + str(uuid.uuid4()); stamp = {'seconds': int(time.time()), 'nanos': 0}
    media = None
    if scenario.startswith('media-'):
        if scenario == 'media-voice-caf':
            source = Path('/public-input/reference.flac').read_bytes()
            assert hashlib.sha256(source).hexdigest() == '63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
            sys.path[:0] = [str(root), '/repo/linux/haos/runtime']
            from haos.speech import decode
            from caf_fixture import encode
            data = encode(decode(source)[0]); name = 'fixture.caf'; mime = 'application/octet-stream'; uti = 'com.apple.coreaudio-format'
        elif scenario == 'media-document':
            data = b'approved fixture document'; name = 'fixture.bin'; mime = 'application/octet-stream'; uti = 'public.data'
        else:
            from PIL import Image
            from io import BytesIO
            buffer = BytesIO(); Image.new('RGB', (2, 2), 'blue').save(buffer, format='PNG')
            data = buffer.getvalue(); name = 'fixture.png'; mime = 'image/png'; uti = 'public.png'
        media = {'attachment': {'guid': str(uuid.uuid4()), 'fileName': name, 'mimeType': mime, 'uti': uti, 'totalBytes': len(data)},
            'data': base64.b64encode(data).decode()}
    def message(sequence, sender, guid):
        chat = 'any;-;' + sender
        body = {'guid': guid, 'content': {'text': 'approved actual protobuf message'}, 'dateCreated': stamp,
            'sender': {'address': sender, 'service': 'CHAT_SERVICE_TYPE_IMESSAGE'}, 'chatGuids': [chat], 'isFromMe': False}
        if media:
            body['content']['attachments'] = [media['attachment']]
            if scenario == 'media-voice-caf': body['isAudioMessage'] = True
        return {'sequence': sequence, 'messageChanged': {'chatGuid': chat, 'occurredAt': stamp, 'isFromMe': False, 'messageReceived': {'message': body}}}
    approved = message(2, '+15550100001', mid)
    config = {'sidecar': str(root / 'hermes/plugins/platforms/photon/sidecar'), 'key': str(directory / 'server.key'),
        'cert': str(directory / 'server.crt'), 'project_id': account['project_id'], 'project_secret': account['project_secret'],
        'native_token': native_token, 'counts': str(directory / 'counts.json'), 'emit': str(directory / 'emit'),
        'ready': str(directory / 'ready.json'), 'scenario': scenario,
        'reply_source': mid, 'reply_chat': 'any;-;+15550100001', 'reply_receipt': str(uuid.uuid4()), 'write_observed': str(directory / 'write-observed'),
        'media': media, 'download_observed': str(directory / 'download-observed'),
        'frames': [message(1, '+15550100009', str(uuid.uuid4())), approved, approved] if scenario in {'normal', 'dedicated', 'health-withdraw'} or scenario.startswith(('reply-', 'media-')) else []}
    (directory / 'server.json').write_text(json.dumps(config))
    peer = subprocess.Popen([str(root / 'photon/node'), str(fixtures / 'protocol.mjs'), str(directory / 'server.json')],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 8
        while not (directory / 'ready.json').exists():
            if peer.poll() is not None: raise AssertionError(peer.stderr.read().decode())
            assert time.monotonic() < deadline, 'fixture TLS peer did not start'
            time.sleep(.02)
        ready = json.loads((directory / 'ready.json').read_text())
        sidecar = root / 'hermes/plugins/platforms/photon/sidecar'
        substitutions = [(sidecar / 'node_modules/@spectrum-ts/core/dist/index.js', 'https://spectrum.photon.codes', ready['cloud']),
            (sidecar / 'node_modules/@spectrum-ts/imessage/dist/index.js', 'imessage.spectrum.photon.codes:443', ready['grpc'])]
        for path, original, replacement in substitutions:
            code = path.read_text(); assert code.count('"' + original + '"') == 1
            path.write_text(code.replace('"' + original + '"', '"' + replacement + '"'))
        if scenario in {'dedicated', 'wrong-line'}:
            sdkfile = sidecar / 'node_modules/@spectrum-ts/imessage/dist/index.js'
            code = sdkfile.read_text(); assert code.count('`${instanceId}.imsg.photon.codes:443`') == 1
            sdkfile.write_text(code.replace('`${instanceId}.imsg.photon.codes:443`', '"' + ready['grpc'] + '"'))
        launcher = root / 'photon/photon_sidecar.mjs'
        code = launcher.read_text(); assert code.count('"https://spectrum.photon.codes"') == 1
        launcher.write_text(code.replace('"https://spectrum.photon.codes"', '"' + ready['cloud'] + '"'))
        sys.path.insert(0, str(root))
        from haos.gateway_photon_process import PROGRAMS
        provenance = root / 'photon/source.json'; value = json.loads(provenance.read_text())
        value['programs'] = [{'name': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in PROGRAMS.items()]
        provenance.write_text(json.dumps(value))
        (directory / 'worker.json').write_text(json.dumps({'account': account, 'since': int(time.time() * 1000) - 10000, 'message_id': mid,
            'scenario': scenario, 'reply_receipt': config['reply_receipt']}))
        worker = directory / 'worker.json'; setup = json.loads(worker.read_text())
        if media: setup['media_sha256'] = hashlib.sha256(base64.b64decode(media['data'])).hexdigest()
        worker.write_text(json.dumps(setup))
        for entry in directory.rglob('*'): os.chown(entry, 65534, 65534)
        os.chown(directory, 65534, 65534)
        with Path('/etc/passwd').open('a') as output: output.write('haos-gateway:x:65534:65534:fixture:/nonexistent:/usr/sbin/nologin\n')
        completed = subprocess.run(['/usr/local/bin/python3', '-I', str(fixtures / 'profile.py'), '--worker', str(directory)],
            preexec_fn=private_identity, env={'PATH': '/usr/bin:/bin', 'HOME': str(directory), 'PYTHONDONTWRITEBYTECODE': '1', 'HERMES_SAFE_MODE': '1'},
            capture_output=True, text=True, timeout=50)
        if completed.returncode: raise AssertionError(completed.stderr + completed.stdout)
        result = json.loads(completed.stdout); assert result['counts']['refused_auth'] == 0
        result['substitution'] = 'Root fixture-only SDK HTTP/gRPC endpoint literals and fresh trusted loopback TLS CA; actual SDK, native codec, private process and custody'
        print(json.dumps(result), flush=True)
    finally:
        peer.terminate()
        try: peer.communicate(timeout=4)
        except subprocess.TimeoutExpired: peer.kill(); peer.communicate()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker': print(json.dumps(asyncio.run(worker(sys.argv[2]))), flush=True)
    else: main()
