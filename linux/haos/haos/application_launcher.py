"""Root-authorized application launch, never an arbitrary command endpoint.

The registered ELF is run as a distinct dynamic UID in a private rootfs/network
with a bounded cgroup. Admission is durable before systemd receives the start.
An ambiguous start is inspected or stopped, never dispatched again.
"""
import json
import hashlib
import os
from pathlib import Path
import pwd
import re
import select
import signal
import socket
import sqlite3
import stat
import struct
import subprocess
import time
import uuid

from .applications import ApplicationRegistry, unique_object
from .enrollment import protected_directory
from .policy import atomic_json
from .application_session import session_action

SOURCE = Path('/usr/lib/haos/haos/application_session.py')


def grant_digest(grant):
    return hashlib.sha256(json.dumps(grant,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def canonical_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('canonical application mission/action UUID required')
    return value


def launch_command(application, mission, request, root, source=SOURCE):
    """Only RootDirectory/runtime names and owner-registered fixed argv vary."""
    canonical_id(mission); canonical_id(request)
    from .applications import validate_application
    application = validate_application(application)
    unit = 'haos-app-' + request.replace('-', '')
    properties = {
        'Type': 'exec', 'DynamicUser': 'yes', 'User': 'haos-a-' + request.replace('-', '')[:24],
        'RootDirectory': str(root), 'BindReadOnlyPaths': f'/usr:/usr /etc/fonts:/etc/fonts {source}:/session.py',
        'MountAPIVFS': 'yes', 'PrivateDevices': 'yes', 'PrivateNetwork': 'yes',
        'TemporaryFileSystem': '/tmp:rw,size=64M,mode=1777 /var/tmp:rw,size=64M,mode=1777',
        'NoNewPrivileges': 'yes', 'CapabilityBoundingSet': '',
        'AmbientCapabilities': '', 'ProtectSystem': 'strict', 'ProtectHome': 'tmpfs',
        'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes', 'ProtectControlGroups': 'yes',
        'ProtectProc': 'invisible', 'ProcSubset': 'pid', 'RestrictSUIDSGID': 'yes',
        'RestrictAddressFamilies': 'AF_UNIX', 'RestrictNamespaces': 'yes', 'LockPersonality': 'yes',
        'RuntimeDirectory': unit, 'RuntimeDirectoryMode': '0700',
        'LoadCredential': 'launch:' + str(root / 'launch.json'),
        'BindPaths': f'/run/{unit}:/home/mission', 'WorkingDirectory': '/home/mission',
        'MemoryMax': str(application['memory_mib']) + 'M', 'MemorySwapMax': '0',
        'TasksMax': '64', 'CPUQuota': '100%', 'RuntimeMaxSec': str(application['runtime_seconds']),
        'KillMode': 'control-group', 'ExitType': 'cgroup', 'Delegate': 'no', 'TimeoutStopSec': '5', 'Restart': 'no',
        'UMask': '0077', 'LimitNOFILE': '128', 'LimitFSIZE': '64M',
        'StandardOutput': 'journal', 'StandardError': 'null',
    }
    command = ['/usr/bin/systemd-run', '--quiet', '--no-block', '--unit=' + unit]
    command += ['--property=' + key + '=' + value for key, value in properties.items()]
    command += ['/usr/bin/python3', '-I', '/session.py']
    return command


def _read_mission(path, mission, ledger_uid, proof=None):
    info = path.lstat()
    parent = path.parent.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != ledger_uid or info.st_nlink != 1
            or info.st_mode & 0o077 or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != ledger_uid or parent.st_mode & 0o077 or path.resolve() != path):
        raise PermissionError('untrusted mission ledger authority')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        deadline = time.monotonic() + 1
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.execute('BEGIN')
        row = db.execute('SELECT state,phase,session_id,cancel_requested,deadline FROM missions WHERE id=?', (mission,)).fetchone()
        if not row or row[0] != 'running' or row[1] != 'dispatching' or not row[2] or row[3] or row[4] <= time.time():
            raise PermissionError('application requires an active dispatched mission')
        if proof is not None:
            request,digest,operation=proof
            admitted=db.execute('SELECT mission_id,request_hash,operation,state,created_at FROM gui_actions WHERE id=?',(request,)).fetchone()
            if (not admitted or admitted[:4]!=(mission,digest,operation,'dispatched')
                    or type(admitted[4]) not in {int,float} or not 0<=time.time()-admitted[4]<20):
                raise PermissionError('application action lacks a fresh matching durable GUI dispatch')
    finally:
        db.close()
    after = path.lstat()
    if (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
        raise PermissionError('mission ledger changed identity')


def running_mission(path, mission, ledger_uid, *, request=None, action=None):
    """Read the mutable WAL ledger as its UID, never with root filesystem rights.

    A substituted SQLite path cannot expose owner/credential data to the broker.
    Only a one-byte allow/deny decision crosses the privilege boundary.
    """
    canonical_id(mission)
    proof=None
    if request is not None or action is not None:
        from .application_protocol import action as validate_action,action_digest
        canonical_id(request); action=validate_action(action)
        proof=(request,action_digest(action),action['operation'])
    if type(ledger_uid) is not int or ledger_uid <= 0:
        raise PermissionError('separate controller UID required')
    if os.geteuid() == ledger_uid:
        return _read_mission(path, mission, ledger_uid, proof)
    if os.geteuid() != 0:
        raise PermissionError('mission ledger access is not authorized')
    account = pwd.getpwuid(ledger_uid)
    reader, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(reader)
            # The worker cannot retain a privileged socket, credential or file
            # descriptor from the authorizing process.
            os.closerange(0, writer)
            os.closerange(writer + 1, 1048576)
            os.setgroups([]); os.setgid(account.pw_gid); os.setuid(ledger_uid)
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(38, 1, 0, 0, 0) != 0:
                os._exit(1)
            _read_mission(path, mission, ledger_uid, proof)
            os.write(writer, b'1')
        except BaseException:
            pass
        os._exit(0)
    os.close(writer)
    try:
        ready, _, _ = select.select([reader], [], [], 3)
        allowed = bool(ready) and os.read(reader, 2) == b'1'
    finally:
        os.close(reader)
        if os.waitpid(pid, os.WNOHANG) == (0, 0):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
    if not allowed:
        raise PermissionError('application requires a verified active mission')


class ApplicationLauncher:
    def __init__(self, registry=None, state=Path('/var/lib/haos-applications'), runtime=Path('/run/haos-applications'), source=SOURCE):
        if os.geteuid() != 0:
            raise PermissionError('the independent application authority is required')
        self.registry = registry or ApplicationRegistry()
        self.state, self.runtime, self.source = map(Path, (state, runtime, source))
        for path in (self.state, self.runtime):
            protected_directory(path.parent)
            path.mkdir(mode=0o700, exist_ok=True)
            protected_directory(path)
            if stat.S_IMODE(path.stat().st_mode) != 0o700:
                raise PermissionError('application broker directories must be private')
        protected_directory(self.source.parent)
        info = self.source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > 65536:
            raise PermissionError('untrusted application session program')

    def start(self, application, mission, request, *, ledger=Path('/var/lib/haos-control/missions.db'), ledger_uid):
        if os.geteuid() != 0:
            raise PermissionError('application launch requires the independent authority')
        canonical_id(request)
        running_mission(Path(ledger), mission, ledger_uid)
        grant = self.registry.resolve(application)
        receipt = self.state / (request + '.json')
        if receipt.exists() or receipt.is_symlink():
            raise PermissionError('application action already admitted; inspect before another start')
        records = list(self.state.iterdir())
        if len(records) >= 128:
            raise PermissionError('application admission retention budget exhausted')
        active = []
        for file in records:
            if file.suffix != '.json':
                raise PermissionError('unknown application authority state')
            previous = self.record(file.stem)
            if previous['state'] != 'stopped':
                active.append(previous)
                if previous['request'].replace('-', '')[:24] == request.replace('-', '')[:24]:
                    raise PermissionError('dynamic application identity already reserved')
        if sum(p['mission'] == mission for p in active) >= 4:
            raise PermissionError('mission application budget exhausted')
        # Exclusive, durable admission is never removed after an ambiguous result.
        descriptor = {'version': 1, 'request': request, 'mission': mission, 'application': grant['id'],
                      'sha256': grant['sha256'], 'grant_sha256':grant_digest(grant),
                      'unit': 'haos-app-' + request.replace('-', ''), 'state': 'admitted'}
        fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(descriptor) + '\n').encode()); os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(self.state, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        root = self.runtime / request
        root.mkdir(mode=0o755)
        for path in ('usr','run','tmp','var','var/tmp','home','home/mission','etc','dev','proc'):
            (root / path).mkdir(mode=0o755, exist_ok=True)
        (root / 'etc/fonts').mkdir(mode=0o755)
        for name in ('bin','sbin','lib','lib64'):
            (root / name).symlink_to('usr/' + name)
        (root / 'session.py').touch(mode=0o444)
        # Do not put fixed owner arguments (which may contain private URLs or
        # paths) in world-readable transient-unit metadata or the process argv.
        atomic_json(root / 'launch.json',{'executable':grant['executable'],'argv':grant['argv']})
        # Revalidate the policy immediately before submitting a fixed unit. The
        # immutable /usr bind pins the running image's executable/library view.
        if self.registry.resolve(application) != grant:
            raise PermissionError('owner application authority changed before launch')
        subprocess.run(launch_command(grant, mission, request, root, self.source), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                       env={'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8'})
        descriptor['state'] = 'submitted'
        atomic_json(receipt, descriptor)
        return {'request': request, 'mission': mission, 'application': application, 'state': 'submitted'}

    def record(self, request):
        if os.geteuid() != 0:
            raise PermissionError('application inspection requires the independent authority')
        canonical_id(request)
        path = self.state / (request + '.json')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 4096:
                raise PermissionError('untrusted application admission record')
            with os.fdopen(fd) as stream:
                fd = -1; record = json.load(stream, object_pairs_hook=unique_object)
        finally:
            if fd >= 0: os.close(fd)
        if (not isinstance(record, dict)
                or set(record) != {'version','request','mission','application','sha256','grant_sha256','unit','state'}
                or record['request'] != request or record['unit'] != 'haos-app-' + request.replace('-', '')
                or type(record['version']) is not int or record['version'] != 1
                or record['state'] not in {'admitted','submitted','stopped'}
                or not isinstance(record['application'],str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',record['application'])
                or any(not isinstance(record[k],str) or not re.fullmatch(r'[a-f0-9]{64}',record[k]) for k in ('sha256','grant_sha256'))):
            raise PermissionError('application record identity mismatch')
        canonical_id(record['mission'])
        return record

    def stop(self, request):
        if os.geteuid() != 0:
            raise PermissionError('application termination requires the independent authority')
        record = self.record(request)
        # An exited transient unit may already have been unloaded. A failed
        # stop command never counts as success by itself: confirm empty kernel
        # process/cgroup state below before changing the durable receipt.
        subprocess.run(['/usr/bin/systemctl','stop',record['unit'] + '.service'], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                       env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        process = subprocess.run(['/usr/bin/systemctl','show',record['unit'] + '.service','--property=ActiveState','--property=MainPID'],
                                 capture_output=True, text=True, check=True, timeout=5)
        properties = dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line)
        if properties.get('ActiveState') not in {'inactive','failed'} or properties.get('MainPID') != '0':
            raise RuntimeError('application cgroup termination is not confirmed')
        group=Path('/sys/fs/cgroup/system.slice')/(record['unit']+'.service')
        if group.exists() and 'populated 0' not in (group/'cgroup.events').read_text().splitlines():
            raise RuntimeError('application cgroup still contains descendants')
        record['state'] = 'stopped'
        atomic_json(self.state / (request + '.json'), record)
        (self.runtime / request / 'launch.json').unlink(missing_ok=True)
        return {'request':request,'state':'stopped'}

    def unit_state(self, request):
        record=self.record(request)
        process=subprocess.run(['/usr/bin/systemctl','show',record['unit']+'.service',
            '--property=ActiveState','--property=MainPID','--property=ControlGroup','--property=ExecMainStatus'],
            capture_output=True,text=True,check=True,timeout=3,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        if len(process.stdout.encode())>8192:
            raise PermissionError('invalid application unit response')
        properties=dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line)
        if (set(properties)!={'ActiveState','MainPID','ControlGroup','ExecMainStatus'}
                or not properties['MainPID'].isdecimal() or not properties['ExecMainStatus'].isdecimal()
                or properties['ActiveState'] not in {'active','activating','inactive','failed','deactivating'}):
            raise PermissionError('invalid application unit identity')
        return properties

    def execute(self, request, mission, action, *, ledger=Path('/var/lib/haos-control/missions.db'), ledger_uid):
        if os.geteuid()!=0:
            raise PermissionError('application controls require the independent authority')
        action=session_action(action)
        record=self.record(request)
        if record['mission']!=canonical_id(mission) or record['state']!='submitted':
            raise PermissionError('application belongs to another mission or is not running')
        running_mission(Path(ledger),mission,ledger_uid)
        if grant_digest(self.registry.resolve(record['application']))!=record['grant_sha256']:
            raise PermissionError('application authority changed')
        unit=self.unit_state(request)
        pid=int(unit['MainPID'])
        if unit['ActiveState']!='active' or pid<=1:
            raise RuntimeError('application unit is not ready or has stopped')
        status=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        identities=[int(value) for value in status['Uid'].split()]
        if len(identities)!=4 or len(set(identities))!=1 or not 61184<=identities[0]<=65519:
            raise PermissionError('a separate systemd dynamic application identity is required')
        path=Path('/run')/record['unit']/'control.sock'
        info=path.lstat();parent=path.parent.lstat()
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid!=identities[0] or stat.S_IMODE(info.st_mode)!=0o600
                or not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=identities[0]
                or stat.S_IMODE(parent.st_mode)!=0o700 or path.resolve()!=path):
            raise PermissionError('untrusted application control socket')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
            peer.settimeout(4);peer.connect(str(path))
            actual_pid,actual_uid,_=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if actual_pid!=pid or actual_uid!=identities[0]:
                raise PermissionError('application server kernel identity changed')
            running_mission(Path(ledger),mission,ledger_uid)
            if grant_digest(self.registry.resolve(record['application']))!=record['grant_sha256']:
                raise PermissionError('application authority changed before input')
            peer.sendall(json.dumps(action).encode()+b'\n');data=bytearray()
            while b'\n' not in data:
                block=peer.recv(65536)
                if not block or len(data)+len(block)>1500000:
                    raise ValueError('invalid application control response')
                data.extend(block)
        frame,rest=data.split(b'\n',1)
        if rest: raise ValueError('multiple application responses denied')
        result=json.loads(frame,object_pairs_hook=unique_object)
        if not isinstance(result,dict) or set(result)!={'result'}:
            if (isinstance(result,dict) and set(result)=={'error','reason'}
                    and result['reason'] in {'ValueError','PermissionError','RuntimeError','TimeoutError','OSError'}):
                raise PermissionError('application action denied or unavailable ('+result['reason']+')')
            raise PermissionError('application action denied or unavailable')
        return result['result']
