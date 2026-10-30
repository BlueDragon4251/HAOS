#!/usr/bin/env python3
"""Actual private profile, Node SDK and TLS/protobuf loopback peers.

Run only as PID 1 of a fresh network-disabled container. Public installed code
is copied into that namespace; SDK endpoint literals are replaced only there.
No cloud account, external delivery, controller or installed OS is claimed.
"""
import asyncio
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
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
    adapter = build(value, parent=parent, connector='phone', policy=current, inbox=inbox)
    observed = []
    def accept(event):
        envelope = adapter_envelope(event, 'photon'); relay.admit(current(), 'phone', envelope)
        observed.append(envelope); return True
    adapter.set_durable_message_handler(accept)
    try:
        assert await adapter.connect(), adapter._haos_photon_health.recorded()
        assert adapter.is_connected
        (root / 'emit').write_text('emit fixture frames')
        deadline = time.monotonic() + 12
        while not observed:
            if time.monotonic() >= deadline:
                raise AssertionError({'status': adapter._haos_photon_health.recorded(),
                    'counts': json.loads((root / 'counts.json').read_text()),
                    'originals': [dict(row) for row in adapter._haos_photon_originals.db.execute('SELECT id,length(normalized) AS bytes FROM photon_originals')]})
            await asyncio.sleep(.025)
        await asyncio.sleep(.3)
        assert len(observed) == 1 and observed[0]['text'] == 'approved actual protobuf message'
        assert observed[0]['message_id'] == config['message_id']
        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 1
        originals = adapter._haos_photon_originals.db
        assert originals.execute('SELECT COUNT(*) FROM photon_originals').fetchone()[0] == 1
        assert originals.execute('SELECT COUNT(*) FROM photon_refusals').fetchone()[0] == 1
        assert len(originals.execute('SELECT admitted_receipt FROM photon_originals').fetchone()[0]) == 64
        assert adapter._haos_photon_cursor.resume() == '2'
        active[0] = False
        deadline = time.monotonic() + 2
        while adapter.is_connected:
            assert time.monotonic() < deadline, 'actual profile ignored owner withdrawal'
            await asyncio.sleep(.01)
        assert adapter._haos_photon_health.recorded()['status'] == 'revoked'
        assert not any(Path('/tmp').glob('hp-*/control.sock'))
        return {'passed': 7, 'cases': ['actual_private_UID_Node_TLS_HTTP_auth_and_protobuf_gRPC',
            'unknown_sender_hash_only_refusal_before_native_mapping', 'approved_native_SDK_sidecar_Python_codec_durable_relay',
            'duplicate_native_message_exactly_one_parent_row', 'original_and_native_custody_have_parent_receipt',
            'actual_native_stream_advances_durable_cursor', 'owner_withdrawal_stops_actual_Node_and_Unix_control'],
            'counts': json.loads((root / 'counts.json').read_text()), 'live_Photon_verified': False,
            'controller_IPC_verified': False, 'OS_release_artifact': False}
    finally:
        await adapter.close(); inbox.close(); relay.close()


def main():
    if os.geteuid() != 0 or os.getpid() != 1 or os.environ.get('HAOS_DISPOSABLE_PHOTON_PROFILE') != '1':
        raise PermissionError('fresh disposable PID-1 network-disabled profile fixture required')
    root = Path('/usr/lib/haos'); root.mkdir(mode=0o755)
    # Public package sources only. Never broaden permissions on the checkout,
    # provider identity, owner home or mounted frozen dependency environment.
    shutil.copytree('/deps', '/opt/fixture-deps', ignore=shutil.ignore_patterns('__pycache__'), copy_function=shutil.copyfile)
    shutil.copytree('/repo/upstream/hermes-agent', root / 'hermes', ignore=shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__'), copy_function=shutil.copyfile)
    shutil.copytree('/input/hermes', root / 'hermes', dirs_exist_ok=True, copy_function=shutil.copyfile)
    shutil.copytree('/repo/linux/haos/haos', root / 'haos', ignore=shutil.ignore_patterns('__pycache__'), copy_function=shutil.copyfile)
    shutil.copytree('/input/photon', root / 'photon', copy_function=shutil.copyfile)
    # Exercise the CURRENT fixed launcher, not yesterday's installed fixture.
    for name in ['photon_sidecar.mjs', 'photon_bounded_stream.mjs']:
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
    native_token = secrets.token_urlsafe(32); mid = 'spc-' + str(uuid.uuid4()); stamp = {'seconds': int(time.time()), 'nanos': 0}
    def message(sequence, sender, guid):
        chat = 'any;-;' + sender
        body = {'guid': guid, 'content': {'text': 'approved actual protobuf message'}, 'dateCreated': stamp,
            'sender': {'address': sender, 'service': 'CHAT_SERVICE_TYPE_IMESSAGE'}, 'chatGuids': [chat], 'isFromMe': False}
        return {'sequence': sequence, 'messageChanged': {'chatGuid': chat, 'occurredAt': stamp, 'isFromMe': False, 'messageReceived': {'message': body}}}
    approved = message(2, '+15550100001', mid)
    config = {'sidecar': str(root / 'hermes/plugins/platforms/photon/sidecar'), 'key': str(directory / 'server.key'),
        'cert': str(directory / 'server.crt'), 'project_id': account['project_id'], 'project_secret': account['project_secret'],
        'native_token': native_token, 'counts': str(directory / 'counts.json'), 'emit': str(directory / 'emit'),
        'ready': str(directory / 'ready.json'), 'frames': [message(1, '+15550100009', str(uuid.uuid4())), approved, approved]}
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
        sys.path.insert(0, str(root))
        from haos.gateway_photon_process import PROGRAMS
        provenance = root / 'photon/source.json'; value = json.loads(provenance.read_text())
        value['programs'] = [{'name': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in PROGRAMS.items()]
        provenance.write_text(json.dumps(value))
        (directory / 'worker.json').write_text(json.dumps({'account': account, 'since': int(time.time() * 1000) - 10000, 'message_id': mid}))
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
