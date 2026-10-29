"""One bounded private native DingTalk connection; parent commits before SDK ACK."""
import asyncio
import base64
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import resource
import signal
import ssl
import sys
import threading
from urllib.parse import quote_plus


def main():
    from .gateway_runtime import require_runtime_identity, SafeFormatter
    require_runtime_identity()
    if sys.version_info[:2] != (3, 11):
        raise PermissionError('pinned private CPython 3.11 required')
    parent = os.getppid(); libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
        raise PermissionError('private socket parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    signal.signal(signal.SIGALRM, lambda *_: os._exit(124)); signal.alarm(40)
    from .gateway_dingtalk_admission import finite, MAX_EVENT, approve, normalize, Refused
    from .gateway_line_ingress import _object
    raw = sys.stdin.buffer.readline(32769)
    if len(raw) > 32768 or not raw.endswith(b'\n'):
        raise ValueError('bounded private socket startup required')
    request = json.loads(raw, object_pairs_hook=_object, parse_constant=finite)
    if (not isinstance(request, dict) or set(request) != {'connector', 'credentials', 'policy_sha256', 'parent_pid'}
            or type(request['parent_pid']) is not int or request['parent_pid'] != parent or os.getppid() != parent
            or not isinstance(request['connector'], str) or not isinstance(request['policy_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', request['policy_sha256'])):
        raise ValueError('exact private socket startup required')
    from .gateway_dingtalk import credentials, authority, PreparedDingTalkPolicy
    from .gateway_dingtalk_http import Boundary, sdk_scope, endpoint, Failure
    from .gateway_dingtalk_process import ERRORS
    from .gateway_dingtalk_frames import install
    from .redaction import Redactor
    from .sandbox import trusted_json
    from importlib.metadata import version
    if ({name: version(name) for name in ('dingtalk-stream', 'alibabacloud-dingtalk', 'alibabacloud-tea-openapi', 'websockets')}
            != {'dingtalk-stream': '0.24.3', 'alibabacloud-dingtalk': '2.2.42',
                'alibabacloud-tea-openapi': '0.4.6', 'websockets': '15.0.1'}):
        raise PermissionError('reviewed private SDK versions required')
    value = credentials(request['credentials']); stopped = threading.Event()
    output = sys.stdout.buffer; sys.stdout = sys.stderr
    os.set_blocking(output.fileno(), False)
    def current():
        if stopped.is_set():
            raise PermissionError('private socket stopping')
        authority(request['connector'], value, request['policy_sha256'])
    current()
    redactor = Redactor([value['client_secret']]); handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(redactor))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    boundary = Boundary(value, current, redactor)

    class SocketLogger(logging.LoggerAdapter):
        def log(self, level, _message, *_args, **_kwargs):
            if self.isEnabledFor(level):
                self.logger.log(level, 'private DingTalk socket diagnostic')

    async def run():
        loop = asyncio.get_running_loop(); pending = {}; sequence = 0
        stop_event = asyncio.Event(); output_lock = asyncio.Lock()
        def stop():
            stopped.set(); loop.call_soon_threadsafe(stop_event.set)
        signal.signal(signal.SIGTERM, lambda *_: stop())
        async def emit(data):
            encoded = (json.dumps(data, separators=(',', ':')) + '\n').encode()
            async with output_lock:
                offset = 0
                async with asyncio.timeout(5):
                    while offset < len(encoded):
                        current()
                        try:
                            offset += os.write(output.fileno(), encoded[offset:])
                        except BlockingIOError:
                            writable = loop.create_future()
                            def ready():
                                if not writable.done():
                                    writable.set_result(True)
                            loop.add_writer(output.fileno(), ready)
                            try:
                                await writable
                            finally:
                                loop.remove_writer(output.fileno())
        def reply(data):
            try:
                if (not isinstance(data, dict) or set(data) not in ({'seq', 'receipt'}, {'seq', 'refused'})
                        or type(data['seq']) is not int or data['seq'] not in pending):
                    raise ValueError
                if ('receipt' in data and (not isinstance(data['receipt'], str)
                        or not re.fullmatch('[0-9a-f]{64}', data['receipt']))
                        or 'refused' in data and data['refused'] is not True):
                    raise ValueError
                future = pending[data['seq']]
                if future.done():
                    raise ValueError
                future.set_result(data)
            except Exception:
                stop()
        def read_parent():
            try:
                while not stopped.is_set():
                    line = sys.stdin.buffer.readline(4097)
                    if not line or len(line) > 4096 or not line.endswith(b'\n'):
                        break
                    data = json.loads(line, object_pairs_hook=_object, parse_constant=finite)
                    if data == {'stop': True}:
                        break
                    loop.call_soon_threadsafe(reply, data)
            except Exception:
                pass
            finally:
                stop()
        async def capture(raw):
            nonlocal sequence
            current()
            policy = PreparedDingTalkPolicy(trusted_json(Path('/etc/haos/gateways.json')))
            proof = approve(policy, request['connector'], value, raw)
            projection = normalize(policy, request['connector'], value, raw, proof, redactor)
            if redactor.clean(projection) != projection:
                raise Refused('private-reflection')
            if pending:
                raise PermissionError('one retained event at a time')
            sequence += 1; seq = sequence; future = loop.create_future(); pending[seq] = future
            try:
                await emit({'kind': 'event', 'seq': seq, 'payload_base64': base64.b64encode(raw).decode(),
                            'sha256': hashlib.sha256(raw).hexdigest()})
                result = await asyncio.wait_for(future, 5); current()
                if 'receipt' not in result:
                    raise PermissionError('parent refused durable input')
                return result['receipt']
            finally:
                pending.pop(seq, None)
        client = boundary.client(); install(client, capture, current); client.pre_start()
        # Retain the actual pinned SDK subscription/discovery and callback/ACK
        # codecs. The private owner supplies the socket loop because SDK.start
        # swallows cancellation, reconnects internally and spawns unbounded tasks.
        def discover():
            with sdk_scope(), boundary.operation('connection', client):
                result = client.open_connection()
            if not result:
                raise Failure(boundary.failure or 'transport-unavailable')
            return result
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosedOK
        class ClosedConnect(connect):
            def process_redirect(self, exception):
                return exception
        async def session():
            connection = await asyncio.to_thread(discover); current()
            address = endpoint(connection['endpoint']) + '?ticket=' + quote_plus(connection['ticket'])
            boundary.register(quote_plus(connection['ticket'])); boundary.register(address)
            async with ClosedConnect(address, ssl=ssl.create_default_context(), proxy=None, compression=None,
                    max_size=MAX_EVENT, max_queue=1, open_timeout=10, close_timeout=3,
                    ping_interval=20, ping_timeout=20,
                    logger=SocketLogger(logging.getLogger('haos.dingtalk.socket'), {})) as socket:
                client.websocket = socket; current(); signal.alarm(0)
                await emit({'kind': 'ready'})
                keepalive = asyncio.create_task(client.keepalive(socket))
                try:
                    while True:
                        current()
                        raw = await socket.recv()
                        if not isinstance(raw, str):
                            raise Refused('unsupported-frame')
                        result = await client._haos_route_frame(raw.encode('utf-8'))
                        if result == client.TAG_DISCONNECT:
                            return
                except ConnectionClosedOK:
                    return
                finally:
                    keepalive.cancel(); await asyncio.gather(keepalive, return_exceptions=True)
        async def watch():
            while not stop_event.is_set():
                current(); await asyncio.sleep(.1)
        threading.Thread(target=read_parent, name='private-dingtalk-parent', daemon=True).start()
        tasks = [asyncio.create_task(session()), asyncio.create_task(watch()), asyncio.create_task(stop_event.wait())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    try:
        asyncio.run(run())
    except Exception as error:
        from websockets.exceptions import InvalidStatus
        if isinstance(error, Failure): kind = error.kind
        elif isinstance(error, ssl.SSLError): kind = 'tls-refused'
        elif isinstance(error, InvalidStatus):
            code = error.response.status_code
            kind = 'authentication-refused' if code in {401, 403} else 'rate-limited' if code == 429 else 'redirect-refused' if 300 <= code < 400 else 'transport-unavailable'
        elif isinstance(error, PermissionError): kind = 'authority-or-protocol-refused'
        else: kind = 'transport-unavailable'
    else:
        kind = 'transport-unavailable'
    finally:
        stopped.set(); signal.alarm(5); boundary.close()
    # No exception string, endpoint ticket or callback body crosses diagnostics.
    os.write(output.fileno(), (json.dumps({'kind': 'stopped', 'error': kind if kind in ERRORS else 'authority-or-protocol-refused'}) + '\n').encode())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('private DingTalk socket worker refused\n'); raise SystemExit(1)
