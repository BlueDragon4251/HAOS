"""Recoverable owner publication of a matched gateway policy/credential snapshot."""
from contextlib import contextmanager
import fcntl
import json
import os
import secrets
import stat

from .gateway import GatewayPolicy
from .policy import atomic_json
from .sandbox import trusted_json

PENDING = 'gateway-publication.json'


def validate_snapshot(policy, credentials):
    GatewayPolicy(policy)
    if (not isinstance(credentials, dict) or set(credentials) not in ({'connectors'}, {'connectors', 'publication'})
            or not isinstance(credentials['connectors'], dict)
            or set(credentials['connectors']) != {row['id'] for row in policy['connectors']}):
        raise ValueError('gateway credentials and policy disagree')
    if policy.get('publication') != credentials.get('publication'):
        raise PermissionError('gateway policy and credentials are from different owner publications')
    platforms={item['id']:item['platform'] for item in policy['connectors']}
    for name,row in credentials['connectors'].items():
        required=({'token','app_token'} if platforms[name]=='slack' else
            {'token','server_url'} if platforms[name]=='mattermost' else {'token'})
        if (not isinstance(row, dict) or set(row) not in (required,required|{'extra'})
                or not isinstance(row.get('token'), str) or not 16 <= len(row['token']) <= 4096
                or any(char.isspace() or ord(char) < 32 for char in row['token'])
                or ('extra' in row and not isinstance(row['extra'], dict))):
            raise ValueError('invalid protected gateway credential')
        if platforms[name]=='slack':
            from .gateway_slack import validate_credentials
            validate_credentials(row['token'],row['app_token'])
        if platforms[name]=='mattermost':
            from .gateway_mattermost import validate_credentials
            if validate_credentials(row['token'],row['server_url']) != row['server_url']:
                raise ValueError('Mattermost server URL must use its canonical owner representation')
    if len(json.dumps(credentials).encode()) > 32768:
        raise ValueError('gateway credentials exceed service bound')


def pending(config):
    path = config/PENDING
    return path.exists() or path.is_symlink()


def directory(config):
    info = config.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError('untrusted gateway configuration directory')


@contextmanager
def writer(config):
    if os.geteuid() != 0:
        raise PermissionError('gateway publication requires authenticated owner authority')
    directory(config)
    fd = os.open(config/'.gateway-publication.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise PermissionError('untrusted gateway publication lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def finish(config, journal, gid):
    if (set(journal) != {'version', 'policy', 'credentials', 'previous_policy'}
            or type(journal['version']) is not int or journal['version'] != 1):
        raise ValueError('invalid gateway publication journal')
    validate_snapshot(journal['policy'], journal['credentials'])
    GatewayPolicy(journal['previous_policy'])
    if not journal['policy'].get('publication'):
        raise ValueError('gateway publication has no snapshot identity')
    for name in ('gateways.json', 'gateway-credentials'):
        path = config/name
        if path.exists() or path.is_symlink():
            trusted_json(path)
            if name == 'gateway-credentials' and path.lstat().st_mode & 0o077:
                raise PermissionError('gateway credential store must remain root-private')
    # Repeating any stage after a crash is safe. Withdraw all old authority
    # durably before credentials can be assigned to another account.
    atomic_json(config/'gateways.json', {'version': 1, 'connectors': [], 'bindings': [],
        'publication': journal['policy']['publication']}, mode=0o640, gid=gid)
    atomic_json(config/'gateway-credentials', journal['credentials'])
    atomic_json(config/'gateways.json', journal['policy'], mode=0o640, gid=gid)
    (config/PENDING).unlink()
    fd = os.open(config, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def publish(config, policy, credentials, previous, gid):
    publication = secrets.token_hex(32)
    policy = {**policy, 'publication': publication}
    credentials = {**credentials, 'publication': publication}
    validate_snapshot(policy, credentials)
    journal = {'version': 1, 'policy': policy, 'credentials': credentials, 'previous_policy': previous}
    atomic_json(config/PENDING, journal)
    finish(config, journal, gid)


def recover(config, gid):
    with writer(config):
        path = config/PENDING
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 2*1024*1024:
            raise PermissionError('untrusted gateway publication journal')
        journal = trusted_json(path)
        finish(config, journal, gid)
    return {'recovered': True, 'restart_required': True}
