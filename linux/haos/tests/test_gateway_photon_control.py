"""Real AF_UNIX/SO_PEERCRED and SQLite component checks; no SDK or external network."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile

import pytest

from test_gateway_photon_admission import source, custody, decoded
from haos.gateway_photon_control import PolicyServer


CLIENT = '''import json,socket,sys
value=json.loads(sys.stdin.buffer.read())
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
s.settimeout(5);s.connect(sys.argv[1])
try:s.sendall(bytes.fromhex(value['wire']))
except (BrokenPipeError,ConnectionResetError):pass
parts=[]
while True:
 try:part=s.recv(65536)
 except ConnectionResetError:break
 if not part:break
 parts.append(part)
s.close();sys.stdout.buffer.write(b''.join(parts))
'''


async def request(server, allowed, wire, *, own=True):
    process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-c', CLIENT, str(server.path),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    allowed[0] = process.pid if own else os.getpid()
    stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps({'wire': wire.hex()}).encode()), 8)
    assert process.returncode == 0, stderr.decode()
    if not stdout:
        # Refusal before reading a byte may reset a Unix connection that still
        # has an unread request. It must not be presented as an HTTP receipt.
        return None, {'transport_refused': True}
    head, body = stdout.split(b'\r\n\r\n', 1)
    return int(head.split(b' ')[1]), json.loads(body)


def frame(token, route, data, *, headers=None):
    raw = json.dumps(data).encode()
    fields = {'Content-Type': 'application/json', 'Content-Length': str(len(raw)), 'X-Hermes-Sidecar-Token': token}
    if headers: fields.update(headers)
    return ('POST ' + route + ' HTTP/1.1\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in fields.items()) + '\r\n').encode() + raw


async def fixture(source, custody, operation):
    store, policy, current = custody
    with tempfile.TemporaryDirectory(prefix='haos-photon-uds-') as directory:
        path = Path(directory) / 'policy.sock'; token = secrets.token_hex(32); allowed = [None]
        server = PolicyServer(path, token, child_pid=lambda: allowed[0], connector='phone', value=source[0],
            policy=lambda: policy, originals=store, current=current)
        await server.start()
        try:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            await operation(server, allowed, token)
        finally: await server.close()
        assert not path.exists()


def test_exact_real_child_pid_controls_original_and_normalized_custody(source, custody):
    async def run(server, allowed, token):
        code, result = await request(server, allowed, frame(token, '/admit', source[2]))
        assert code == 200 and result['approved'] is True
        key = result['source']; store, policy, _ = custody
        assert store.load(key, policy, 'phone', source[0])[0]['normalized'] == b''
        code, result = await request(server, allowed, frame(token, '/current', {'source': key}))
        assert code == 200 and result['envelope']['sender'] == '+15550100001'
        code, result = await request(server, allowed, frame(token, '/custody', {'source': key, 'event': decoded(source)}))
        assert code == 200 and result['approved'] is True
        assert json.loads(store.load(key, policy, 'phone', source[0])[0]['normalized']) == decoded(source)
        assert await request(server, allowed, frame(token, '/lease', {})) == (200, {'approved': True})
    asyncio.run(fixture(source, custody, run))


@pytest.mark.parametrize('change', ['wrong-pid', 'wrong-token', 'unknown-route', 'duplicate-header', 'chunked', 'oversize', 'non-json', 'absolute-route'])
def test_private_unix_transport_refuses_before_original_storage(source, custody, change):
    async def run(server, allowed, token):
        route = '/admit'; headers = {}; own = True
        if change == 'wrong-pid': own = False
        elif change == 'wrong-token': token = secrets.token_hex(32)
        elif change == 'unknown-route': route = '/send'
        elif change == 'chunked': headers['Transfer-Encoding'] = 'chunked'
        elif change == 'oversize': headers['Content-Length'] = '1048577'
        elif change == 'non-json': headers['Content-Type'] = 'text/plain'
        elif change == 'absolute-route': route = 'http://localhost/admit'
        wire = frame(token, route, source[2], headers=headers)
        if change == 'duplicate-header': wire = wire.replace(b'Content-Type: application/json\r\n', b'Content-Type: application/json\r\ncontent-type: application/json\r\n')
        code, result = await request(server, allowed, wire, own=own)
        if change == 'wrong-pid' and code is None:
            assert result == {'transport_refused': True}
        else:
            assert code == 403 and result == {'approved': False}
        assert custody[0].db.execute('SELECT COUNT(*) FROM photon_originals').fetchone()[0] == 0
    asyncio.run(fixture(source, custody, run))


def test_authenticated_unknown_sender_denial_has_only_durable_hash_and_reason(source, custody):
    async def run(server, allowed, token):
        source[2]['event']['message']['sender']['address'] = '+15550100009'
        code, result = await request(server, allowed, frame(token, '/admit', source[2]))
        assert code == 200 and result == {'approved': False}
        row = custody[0].db.execute('SELECT * FROM photon_refusals').fetchone()
        assert row['reason'] == 'ambiguous-sender'
        assert '+15550100009' not in json.dumps(dict(row))
        assert custody[0].db.execute('SELECT COUNT(*) FROM photon_originals').fetchone()[0] == 0
    asyncio.run(fixture(source, custody, run))


def test_policy_withdrawal_denies_real_child_and_does_not_acknowledge_a_new_source(source, custody):
    async def run(server, allowed, token):
        def withdrawn(): raise PermissionError('fixture owner withdrew authority')
        server.current = withdrawn
        code, result = await request(server, allowed, frame(token, '/admit', source[2]))
        if code is None:
            assert result == {'transport_refused': True}
        else:
            assert code == 403 and result == {'approved': False}
        assert custody[0].db.execute('SELECT COUNT(*) FROM photon_originals').fetchone()[0] == 0
    asyncio.run(fixture(source, custody, run))


def test_actual_sql_refusal_is_unavailable_not_successful_ack(source, custody):
    async def run(server, allowed, token):
        custody[0].db.execute("CREATE TRIGGER refuse_source BEFORE INSERT ON photon_originals BEGIN SELECT RAISE(ABORT,'fixture write refusal'); END")
        code, result = await request(server, allowed, frame(token, '/admit', source[2]))
        assert code == 503 and result == {'approved': False}
        assert not custody[0].db.in_transaction
    asyncio.run(fixture(source, custody, run))


def test_stale_socket_entry_is_preserved_and_never_unlinked_blindly(source, custody):
    async def run():
        store, policy, current = custody
        with tempfile.TemporaryDirectory(prefix='haos-photon-uds-') as directory:
            path = Path(directory) / 'policy.sock'; path.write_bytes(b'existing fixture recovery data')
            server = PolicyServer(path, secrets.token_hex(32), child_pid=lambda: None, connector='phone', value=source[0],
                policy=lambda: policy, originals=store, current=current)
            with pytest.raises(PermissionError, match='already exists'): await server.start()
            await server.close()
            assert path.read_bytes() == b'existing fixture recovery data'
    asyncio.run(run())


def test_existing_actual_unix_socket_is_preserved(source, custody):
    import socket
    async def run():
        store, policy, current = custody
        with tempfile.TemporaryDirectory(prefix='haos-photon-uds-') as directory:
            path = Path(directory) / 'policy.sock'; listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(path)); info = path.lstat()
            try:
                server = PolicyServer(path, secrets.token_hex(32), child_pid=lambda: None, connector='phone', value=source[0],
                    policy=lambda: policy, originals=store, current=current)
                with pytest.raises(PermissionError, match='already exists'): await server.start()
                await server.close()
                assert path.lstat().st_ino == info.st_ino and stat.S_ISSOCK(path.lstat().st_mode)
            finally: listener.close()
    asyncio.run(run())


def test_cleanup_does_not_unlink_replacement_recovery_data(source, custody):
    async def run(server, allowed, token):
        previous = server.path.with_name('retained.sock')
        server.path.rename(previous)
        server.path.write_bytes(b'fixture recovery data')
        await server.close()
        assert server.path.read_bytes() == b'fixture recovery data'
        assert previous.exists()
        # Remove only the test's own generated replacement for fixture cleanup;
        # production close above has demonstrably preserved it.
        server.path.unlink()
    asyncio.run(fixture(source, custody, run))
