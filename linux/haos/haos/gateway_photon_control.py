"""Private authenticated Node-to-Python Photon custody transport over Unix.

Both a per-launch secret and the exact supervised child PID/UID/GID are required.
This is a component, not a public listener or a credential-loading entrypoint.
"""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct

from .gateway import Conflict, digest
from .gateway_dingtalk_admission import parse, finite
from .gateway_line_ingress import _object
from .gateway_photon_admission import Refused
from .gateway_photon_custody import MAX_NORMALIZED, re_full_hash


class PolicyServer:
    def __init__(self, path, token, *, child_pid, connector, value, policy, originals, current):
        self.path = Path(path)
        parent = self.path.parent.lstat()
        if (not self.path.is_absolute() or str(self.path.parent.resolve()) != str(self.path.parent)
                or len(os.fsencode(self.path)) > 100 or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.geteuid() or parent.st_mode & 0o077):
            raise PermissionError('short canonical private Photon Unix listener path required')
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{64}', token) or not all(callable(v) for v in [child_pid, policy, current]):
            raise PermissionError('private Photon launch token, child PID and current publication required')
        self.token = token; self.child_pid = child_pid; self.connector = connector
        self.value = value; self.policy = policy; self.originals = originals; self.current = current
        self.server = None; self.identity = None; self.connections = set(); self.lock = asyncio.Lock()
        self.originals.db.execute('''CREATE TABLE IF NOT EXISTS photon_refusals(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,reason TEXT NOT NULL,raw_sha256 TEXT NOT NULL)''')

    async def start(self):
        self.current()
        if self.server is not None: raise Conflict('Photon policy listener already started')
        # Never remove a retained socket/entry from an earlier process blindly.
        if os.path.lexists(self.path): raise PermissionError('Photon policy socket path already exists')
        # Bind explicitly: asyncio's path= convenience may unlink an existing
        # socket between its own checks and bind. Kernel bind never replaces it.
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.setblocking(False); listener.bind(str(self.path))
            info = self.path.lstat(); self.identity = (info.st_dev, info.st_ino)
            self.path.chmod(0o600)
            self.server = await asyncio.start_unix_server(self.handle, sock=listener, limit=8192, backlog=4)
        except BaseException:
            listener.close(); await self.close(); raise

    async def close(self):
        if self.server:
            self.server.close(); await self.server.wait_closed(); self.server = None
        current = asyncio.current_task()
        pending = [task for task in self.connections if task is not current]
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
        if self.identity is not None:
            try: info = self.path.lstat()
            except FileNotFoundError: pass
            else:
                if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self.identity:
                    self.path.unlink()
            self.identity = None

    def peer(self, writer):
        transport = writer.get_extra_info('socket')
        if transport is None: raise PermissionError('actual Photon Unix peer required')
        pid, uid, gid = struct.unpack('3i', transport.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        expected = self.child_pid()
        if type(expected) is not int or expected <= 1 or expected == os.getpid() or (pid, uid, gid) != (expected, os.geteuid(), os.getegid()):
            raise PermissionError('only the exact supervised Photon child may submit custody')

    async def handle(self, reader, writer):
        task = asyncio.current_task(); self.connections.add(task)
        status = 403; response = {'approved': False}
        try:
            if len(self.connections) > 4: raise PermissionError('Photon control capacity reached')
            self.peer(writer); self.current()
            async with asyncio.timeout(10):
                head = await reader.readuntil(b'\r\n\r\n')
                if len(head) > 4096: raise ValueError('bounded Photon control header required')
                lines = head[:-4].decode('ascii').split('\r\n')
                pieces = lines[0].split(' ')
                if len(pieces) != 3 or pieces[0] != 'POST' or pieces[2] != 'HTTP/1.1': raise ValueError('fixed Photon control method required')
                route = pieces[1]
                if route not in {'/admit', '/current', '/custody', '/lease'}: raise PermissionError('unknown Photon control operation')
                headers = {}
                for line in lines[1:]:
                    name, sep, content = line.partition(':')
                    name = name.lower()
                    if not sep or not re.fullmatch('[a-z0-9-]+', name) or name in headers: raise ValueError('unique Photon control headers required')
                    headers[name] = content.strip()
                if ('transfer-encoding' in headers or headers.get('content-type') != 'application/json'
                        or not hmac.compare_digest(headers.get('x-hermes-sidecar-token', ''), self.token)):
                    raise PermissionError('authenticated bounded Photon control JSON required')
                size = headers.get('content-length', '')
                if not re.fullmatch('[1-9][0-9]{0,8}', size): raise ValueError('exact Photon control content length required')
                maximum = MAX_NORMALIZED + 4096 if route == '/custody' else 1048576 if route == '/admit' else 4096
                if int(size) > maximum: raise ValueError('Photon control body exceeds bound')
                raw = await reader.readexactly(int(size))
                self.peer(writer); self.current()
                async with self.lock:
                    response = self.dispatch(route, raw)
                status = 200
        except Refused as exc:
            # Denial is committed before the SDK may advance its cursor. Do not
            # retain unknown senders' body/address or credential-shaped text.
            try:
                if 'raw' not in locals(): raise PermissionError('no authenticated original')
                self.current(); sha = hashlib.sha256(raw).hexdigest()
                count = self.originals.db.execute('SELECT COUNT(*) FROM photon_refusals').fetchone()[0]
                if count >= 65536: raise Conflict('Photon refusal journal capacity reached')
                identity = digest([self.connector, exc.reason, sha])
                self.originals.db.execute('INSERT OR IGNORE INTO photon_refusals VALUES(?,?,?,?)', (identity, self.connector, exc.reason, sha))
                response = {'approved': False}; status = 200
            except Exception: status = 503
        except (PermissionError, ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            status = 403
        except (Conflict, TimeoutError, OSError):
            status = 503
        except asyncio.CancelledError:
            raise
        except Exception:
            # No SDK/credential/body exceptions cross this private boundary.
            status = 503
        finally:
            try:
                body = json.dumps(response, separators=(',', ':')).encode()
                writer.write(f'HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
                async with asyncio.timeout(1): await writer.drain()
            except (ConnectionError, OSError, TimeoutError): pass
            writer.close()
            try:
                async with asyncio.timeout(1): await writer.wait_closed()
            except (ConnectionError, OSError, TimeoutError): pass
            self.connections.discard(task)

    def dispatch(self, route, raw):
        self.current(); policy = self.policy()
        if route == '/admit':
            # Preserve the authenticated SDK event bytes before any native
            # contact/reply/poll conversion can fetch additional content.
            key = self.originals.retain(policy, self.connector, self.value, raw)
            return {'approved': True, 'source': key}
        if route == '/lease':
            if parse(raw) != {}: raise ValueError('empty Photon lease request required')
            self.current(); return {'approved': True}
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=finite)
        if (not isinstance(data, dict) or set(data) != ({'source', 'event'} if route == '/custody' else {'source'})
                or not isinstance(data.get('source'), str) or not re_full_hash(data['source'])):
            raise ValueError('exact retained Photon source required')
        key = data['source']
        row, proof = self.originals.load(key, policy, self.connector, self.value)
        if route == '/custody':
            projected = json.dumps(data['event'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            self.originals.decode(key, policy, self.connector, self.value, projected)
        self.current(); policy.current_binding(proof)
        return {'approved': True, 'source': key, 'envelope': proof['envelope']}
