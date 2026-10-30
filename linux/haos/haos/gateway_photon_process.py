"""Fixed verified Node command and private process lifetime; no runtime installer."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat

ROOT = Path('/usr/lib/haos/photon')
SIDECAR = Path('/usr/lib/haos/hermes/plugins/platforms/photon/sidecar')
PROGRAMS = {'node': ROOT / 'node', 'launcher': ROOT / 'photon_sidecar.mjs', 'bounded-stream': ROOT / 'photon_bounded_stream.mjs',
    'cloud': ROOT / 'photon_cloud.mjs',
    'sidecar': SIDECAR / 'index.mjs', 'format': SIDECAR / 'send-format.mjs', 'staleness': SIDECAR / 'stream-staleness.mjs',
    'compatibility': SIDECAR / 'patch-spectrum-mixed-attachments.mjs',
    'imessage': SIDECAR / 'node_modules/@spectrum-ts/imessage/dist/index.js',
    'stream': SIDECAR / 'node_modules/@spectrum-ts/core/dist/authoring.js', 'adapter': SIDECAR.parent / 'adapter.py',
    'manifest': SIDECAR / 'package.json', 'lockfile': SIDECAR / 'package-lock.json'}


def regular(path, maximum):
    if path.resolve() != path: raise PermissionError('canonical installed Photon program required')
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('immutable root-owned Photon program directories required')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
            or info.st_mode & 0o022 or not 0 < info.st_size <= maximum):
        raise PermissionError('bounded immutable root-owned Photon program required')


def command():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity(); metadata = ROOT / 'source.json'; regular(metadata, 65536)
    try: value = json.loads(metadata.read_text())
    except (ValueError, UnicodeError, RecursionError): raise PermissionError('valid bounded installed Photon provenance required') from None
    if (not isinstance(value, dict) or value.get('schema') != 1 or value.get('hermes_commit') != 'f97608f178d1ffeca59860195ab7da295f7c8e5f'
            or value.get('spectrum_version') != '12.7.0' or not isinstance(value.get('node'), dict)
            or value['node'].get('version') != '24.19.0'
            or value['node'].get('sha256') != '14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647'
            or not isinstance(value.get('programs'), list) or len(value['programs']) != len(PROGRAMS)):
        raise PermissionError('exact installed Photon/Node source provenance required')
    observed = set()
    for entry in value['programs']:
        if (not isinstance(entry, dict) or set(entry) != {'name', 'sha256'} or not isinstance(entry['name'], str)
                or entry['name'] not in PROGRAMS or entry['name'] in observed
                or not isinstance(entry['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', entry['sha256'])):
            raise PermissionError('one exact installed digest per Photon program required')
        name = entry['name']; observed.add(name); path = PROGRAMS[name]
        regular(path, 400000000 if name == 'node' else 16000000)
        checksum = hashlib.sha256()
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024): checksum.update(block)
        if checksum.hexdigest() != entry['sha256']:
            raise PermissionError('Photon program differs from reviewed installed build')
    return [str(PROGRAMS['node']), '--no-addons', '--disable-proto=throw', '--use-system-ca', '--max-old-space-size=192', str(PROGRAMS['launcher'])]


class Child:
    def __init__(self, value, home, policy_socket, control_socket, token, current):
        from .gateway_photon import credentials
        from .gateway_line_profile import _directory
        self.value = credentials(value); self.home = Path(home); _directory(self.home)
        if not callable(current) or not isinstance(token, str) or not re.fullmatch('[a-f0-9]{64}', token):
            raise PermissionError('private Photon launch authority required')
        self.policy_socket = Path(policy_socket); self.control_socket = Path(control_socket); self.token = token; self.current = current
        self.process = None; self.drains = []; self.socket_identity = None

    @property
    def pid(self):
        return self.process.pid if self.process is not None and self.process.returncode is None else None

    async def _discard(self, stream):
        # Issued SDK bearer tokens are not available to Python's Redactor.
        # Never forward raw SDK stdout/stderr to journald, UI or agent output.
        while await stream.read(8192):
            await asyncio.sleep(0)  # Diagnostics cannot starve current-authority checks.

    async def start(self):
        from .gateway_runtime import require_runtime_identity
        require_runtime_identity(); self.current()
        if not re.search(r'^NoNewPrivs:\s+1$', Path('/proc/self/status').read_text(), re.M):
            raise PermissionError('Photon child requires inherited NoNewPrivileges')
        if self.process is not None: raise PermissionError('Photon child already started')
        if os.path.lexists(self.control_socket): raise PermissionError('Photon control entry already exists')
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(self.home), 'HERMES_HOME': str(self.home), 'LANG': 'C.UTF-8',
            'HAOS_PHOTON_PHONE': self.value['phone'],
            'PHOTON_PROJECT_ID': self.value['project_id'], 'PHOTON_PROJECT_SECRET': self.value['project_secret'],
            'PHOTON_SIDECAR_TOKEN': self.token, 'HAOS_PHOTON_POLICY_SOCKET': str(self.policy_socket),
            'HAOS_PHOTON_CONTROL_SOCKET': str(self.control_socket), 'NODE_OPTIONS': '', 'NODE_PATH': '',
            'PHOTON_READ_RECEIPTS': 'false', 'PHOTON_TELEMETRY': 'false', 'PHOTON_STREAM_SILENCE_PROBE_MS': '0',
            'PHOTON_MAX_INLINE_ATTACHMENT_BYTES': str(8 * 1024 * 1024), 'PHOTON_SIDECAR_WATCH_STDIN': '1'}
        self.process = await asyncio.create_subprocess_exec(*command(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=16384,
            env=environment, cwd=str(self.home), start_new_session=True, close_fds=True)
        self.drains = [asyncio.create_task(self._discard(self.process.stdout)), asyncio.create_task(self._discard(self.process.stderr))]
        try:
            async with asyncio.timeout(45):
                while True:
                    self.current()
                    if self.process.returncode is not None: raise ConnectionError('private Photon SDK initialization failed')
                    try: info = self.control_socket.lstat()
                    except FileNotFoundError: pass
                    else:
                        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                                or info.st_nlink != 1 or self.control_socket.resolve() != self.control_socket):
                            raise PermissionError('private Photon control socket required')
                        self.socket_identity = (info.st_dev, info.st_ino); break
                    await asyncio.sleep(0.025)
            self.current()
        except BaseException:
            await self.stop(); raise

    async def stop(self, *, immediate=False):
        process = self.process
        if process is not None:
            # The main Node process can exit while one of its descendants is
            # still alive. Its private POSIX session remains ours to terminate.
            try: os.killpg(process.pid, signal.SIGKILL if immediate else signal.SIGTERM)
            except ProcessLookupError: pass
            if process.returncode is None and not immediate:
                try:
                    async with asyncio.timeout(2): await process.wait()
                except TimeoutError:
                    pass
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            await process.wait()
            if process.stdin: process.stdin.close()
            if self.drains:
                try:
                    async with asyncio.timeout(2): await asyncio.gather(*self.drains, return_exceptions=True)
                except TimeoutError:
                    for task in self.drains: task.cancel()
                    await asyncio.gather(*self.drains, return_exceptions=True)
            self.process = None; self.drains = []
        if self.socket_identity is not None:
            try: info = self.control_socket.lstat()
            except FileNotFoundError: pass
            else:
                if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self.socket_identity:
                    self.control_socket.unlink()
            self.socket_identity = None
