"""Owner-approved executable identities, with no execution or privilege endpoint.

An approval is necessary, never sufficient to expose the host desktop. The native
launcher must independently supply an isolated mission context before execution.
"""
import hashlib
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat

from .enrollment import protected_directory
from .policy import atomic_json

POLICY = Path('/etc/haos/applications.json')
CLASSES = {'browser', 'editor', 'terminal', 'utility'}
FIELDS = {'id', 'class', 'executable', 'sha256', 'argv', 'memory_mib', 'runtime_seconds'}


def validate_application(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('unsupported application manifest')
    key, executable, arguments = value['id'], value['executable'], value['argv']
    if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', key) or not isinstance(value['class'], str) or value['class'] not in CLASSES:
        raise ValueError('invalid application identity or class')
    if (not isinstance(executable, str) or not executable.startswith('/usr/')
            or len(executable.encode()) > 512 or str(Path(executable)) != executable
            or any(part in {'.', '..'} for part in executable.split('/'))
            or any(ord(c) < 32 or ord(c) == 127 for c in executable)):
        raise PermissionError('only canonical installed /usr executables may be approved')
    if not isinstance(value['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['sha256']):
        raise ValueError('exact executable digest required')
    if (not isinstance(arguments, list) or len(arguments) > 32
            or any(not isinstance(a, str) or len(a.encode()) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in a) for a in arguments)
            or sum(len(a.encode()) for a in arguments) > 8192):
        raise ValueError('application arguments must be bounded fixed strings')
    if (type(value['memory_mib']) is not int or not 128 <= value['memory_mib'] <= 4096
            or type(value['runtime_seconds']) is not int or not 1 <= value['runtime_seconds'] <= 3600):
        raise ValueError('bounded application memory and runtime required')
    return dict(value, argv=list(arguments))


def executable_digest(path):
    """Do not trust PATH, symlinks, writable directories or set-ID binaries."""
    path = Path(path)
    if not str(path).startswith('/usr/') or '..' in path.parts:
        raise PermissionError('installed executable required')
    protected_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1
                or metadata.st_mode & 0o6022 or not metadata.st_mode & 0o111
                or not 4 <= metadata.st_size <= 256 * 1024 * 1024):
            raise PermissionError('untrusted installed executable')
        if os.read(fd, 4) != b'\x7fELF':
            raise PermissionError('interpreter scripts are not executable identities')
        digest = hashlib.sha256(b'\x7fELF')
        while block := os.read(fd, 1024 * 1024):
            digest.update(block)
        after = os.fstat(fd)
        if (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise PermissionError('executable changed during verification')
        return digest.hexdigest()
    finally:
        os.close(fd)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('ambiguous application policy')
        result[key] = value
    return result


class ApplicationRegistry:
    def __init__(self, path=POLICY):
        if os.geteuid() != 0:
            raise PermissionError('application grants require authenticated owner authority')
        self.path = Path(path)
        protected_directory(self.path.parent)

    def read(self):
        if not self.path.exists() and not self.path.is_symlink():
            return {'version': 1, 'applications': []}
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1
                    or metadata.st_mode & 0o077 or metadata.st_size > 65536):
                raise PermissionError('untrusted owner application policy')
            with os.fdopen(fd, 'r') as stream:
                fd = -1
                value = json.load(stream, object_pairs_hook=unique_object)
        finally:
            if fd >= 0:
                os.close(fd)
        if (not isinstance(value, dict) or set(value) != {'version', 'applications'}
                or type(value['version']) is not int or value['version'] != 1
                or not isinstance(value['applications'], list) or len(value['applications']) > 32):
            raise ValueError('unsupported application registry')
        applications = [validate_application(a) for a in value['applications']]
        if len({a['id'] for a in applications}) != len(applications):
            raise ValueError('duplicate application identity')
        return {'version': 1, 'applications': applications}

    def register(self, value):
        application = validate_application(value)
        if executable_digest(application['executable']) != application['sha256']:
            raise PermissionError('executable differs from owner-approved bytes')
        with self.lock():
            policy = self.read()
            # Replacement is explicit revoke then register; never silently widen a grant.
            if any(a['id'] == application['id'] for a in policy['applications']):
                raise PermissionError('application identity already registered; revoke it first')
            if len(policy['applications']) >= 32:
                raise ValueError('application registry budget exhausted')
            policy['applications'].append(application)
            if len(json.dumps(policy, indent=2).encode()) + 1 > 65536:
                raise ValueError('application policy byte budget exhausted')
            atomic_json(self.path, policy)
        return application

    def resolve(self, key):
        matches = [a for a in self.read()['applications'] if a['id'] == key]
        if len(matches) != 1 or executable_digest(matches[0]['executable']) != matches[0]['sha256']:
            raise PermissionError('application absent, revoked or changed by an update')
        return matches[0]

    def revoke(self, key):
        with self.lock():
            policy = self.read()
            if not any(a['id'] == key for a in policy['applications']):
                raise KeyError('application is not registered')
            policy['applications'] = [a for a in policy['applications'] if a['id'] != key]
            atomic_json(self.path, policy)

    @contextmanager
    def lock(self):
        protected_directory(self.path.parent)
        fd = os.open(self.path.with_suffix('.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
                raise PermissionError('untrusted application policy lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)


def owner_application(args):
    from .owner import audit, stopped
    registry = ApplicationRegistry()
    if args.application_action == 'status':
        return {**registry.read(), 'host_application_launch_available': False,
                'requires': 'isolated native mission process and Wayland context'}
    stopped()
    if args.application_action == 'register':
        value = registry.register({'id': args.id, 'class': args.application_class, 'executable': args.executable,
            'sha256': executable_digest(args.executable), 'argv': args.arg, 'memory_mib': args.memory_mib,
            'runtime_seconds': args.runtime_seconds})
        audit('application.registered', {'id': value['id'], 'class': value['class'], 'sha256': value['sha256']})
        return {'registered': value['id'], 'sha256': value['sha256'], 'host_application_launch_available': False}
    if args.application_action == 'revoke':
        registry.revoke(args.id)
        audit('application.revoked', {'id': args.id})
        return {'revoked': args.id}
    raise ValueError('unsupported owner application action')
