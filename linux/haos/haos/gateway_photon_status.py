"""Read recorded Photon state without credentials, SDK, network or profile lease."""
import math
import os
from pathlib import Path
import re
import sqlite3
import stat

from .gateway_photon_health import STATES


def selector(value):
    if (not isinstance(value, dict) or set(value) != {'connector', 'credential_scope', 'account_scope'}
            or not isinstance(value['connector'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value['connector'])
            or not isinstance(value['credential_scope'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['credential_scope'])
            or not isinstance(value['account_scope'], str) or not re.fullmatch(r'photon:[a-f0-9]{64}', value['account_scope'])):
        raise ValueError('exact saved Photon connector and credential/account fingerprints required')
    return dict(value)


def _time(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 253402300799:
        raise ValueError('finite recorded Photon status time required')
    return value


def checked(value, request=None):
    fields = {'connector', 'credential_scope', 'account_scope', 'status', 'updated_at', 'next_attempt',
        'observed_only', 'live_transport_verified', 'network_requested', 'private_credentials_returned'}
    if (not isinstance(value, dict) or set(value) != fields or not isinstance(value['status'], str)
            or value['status'] not in STATES | {'not-started'} or value['observed_only'] is not True
            or any(value[key] is not False for key in ['live_transport_verified', 'network_requested', 'private_credentials_returned'])):
        raise ValueError('closed recorded Photon status without live verification or credentials required')
    chosen = selector({key: value[key] for key in ['connector', 'credential_scope', 'account_scope']})
    if value['updated_at'] is not None or value['status'] != 'not-started': _time(value['updated_at'])
    _time(value['next_attempt'])
    if request is not None and chosen != selector(request):
        raise ValueError('recorded Photon status belongs to another selected account')
    return dict(value)


def read(path, params, current):
    from .gateway_runtime import require_runtime_identity
    from .gateway_line_profile import _directory
    require_runtime_identity(); params = selector(params); current()
    path = Path(path); _directory(path.parent)
    result = {**params, 'status': 'not-started', 'updated_at': None, 'next_attempt': 0,
        'observed_only': True, 'live_transport_verified': False, 'network_requested': False, 'private_credentials_returned': False}
    try: descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        current(); return checked(result, params)
    try:
        def private(item):
            if (not stat.S_ISREG(item.st_mode) or item.st_uid != os.geteuid() or item.st_gid != os.getegid()
                    or item.st_nlink != 1 or item.st_mode & 0o077):
                raise PermissionError('private Photon status journal required')
        before = os.fstat(descriptor); private(before)
        if path.resolve() != path: raise PermissionError('canonical fixed Photon status journal required')
        for suffix in ['-wal', '-shm']:
            try: private(path.with_name(path.name + suffix).lstat())
            except FileNotFoundError: pass
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2, isolation_level=None)
        try:
            after = path.lstat(); private(after)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise PermissionError('Photon status journal replaced while opening')
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            expected = {'photon_profile_status', 'photon_account_budget'}
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('photon_profile_status','photon_account_budget')")}
            if tables and tables != expected: raise ValueError('incomplete Photon status journal requires owner inspection')
            if tables:
                row = db.execute('SELECT status,updated_at FROM photon_profile_status WHERE connector=? AND credential_scope=? AND account_scope=? ORDER BY updated_at DESC LIMIT 1',
                    (params['connector'], params['credential_scope'], params['account_scope'])).fetchone()
                if row is not None: result.update(status=row[0], updated_at=row[1])
                budget = db.execute('SELECT next_attempt FROM photon_account_budget WHERE account_scope=?', (params['account_scope'],)).fetchone()
                if budget is not None: result['next_attempt'] = _time(budget[0])
                elif row is not None: raise ValueError('Photon account retry budget is missing; owner inspection required')
            db.execute('COMMIT')
        finally: db.close()
    finally: os.close(descriptor)
    current(); return checked(result, params)
