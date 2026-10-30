"""Bounded recorded native status; no SDK, network, lease or authority changes."""
import math
import os
from pathlib import Path
import re
import sqlite3
import stat

from .gateway_google_chat_recovery import HEX

STATES=frozenset({'created','connecting','connected-pull','listening-tls','disconnected','closed','revoked',
    'authentication-refused','identity-refused','rate-limited','transport-unavailable','source-unavailable','storage-unavailable'})


def selector(params):
    if (not isinstance(params,dict) or set(params)!={'connector','credential_scope','account_scope'}
            or not isinstance(params['connector'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',params['connector'])
            or not isinstance(params['credential_scope'],str) or not HEX.fullmatch(params['credential_scope'])
            or not isinstance(params['account_scope'],str) or not re.fullmatch('google-chat:[a-f0-9]{64}',params['account_scope'])):
        raise ValueError('exact saved Google connector and credential/app fingerprints required')
    return params


def checked(value,request=None):
    keys={'connector','credential_scope','account_scope','status','updated_at','next_attempt','observed_only','live_transport_verified',
        'network_requested','private_credentials_returned'}
    if (not isinstance(value,dict) or set(value)!=keys or not isinstance(value['status'],str) or value['status'] not in STATES|{'not-started'}
            or value['observed_only'] is not True or any(value[k] is not False for k in ['live_transport_verified','network_requested','private_credentials_returned'])):
        raise ValueError('closed recorded Google status without live verification or credentials required')
    chosen=selector({key:value[key] for key in ['connector','credential_scope','account_scope']})
    for key in ['updated_at','next_attempt']:
        number=value[key]
        if key=='updated_at' and number is None and value['status']=='not-started':continue
        if (type(number) not in {int,float} or not math.isfinite(number) or not 0<=number<=253402300799):raise ValueError('finite recorded Google status time required')
    if request is not None and chosen!=selector(request):raise ValueError('recorded Google status belongs to another selected account')
    return value


def read(path,params,current):
    from .gateway_runtime import require_runtime_identity
    from .gateway_line_profile import _directory
    require_runtime_identity();params=selector(params);current();path=Path(path);_directory(path.parent)
    result={**params,'status':'not-started','updated_at':None,'next_attempt':0,'observed_only':True,
        'live_transport_verified':False,'network_requested':False,'private_credentials_returned':False}
    try:descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    except FileNotFoundError:current();return checked(result,params)
    try:
        def private(own):
            if (not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_gid!=os.getegid()
                    or own.st_nlink!=1 or own.st_mode&0o077):raise PermissionError('private native status journal required')
        before=os.fstat(descriptor);private(before)
        if path.resolve()!=path:raise PermissionError('canonical fixed native status journal required')
        for suffix in ['-wal','-shm']:
            try:private(path.with_name(path.name+suffix).lstat())
            except FileNotFoundError:pass
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2,isolation_level=None)
        try:
            after=path.lstat();private(after)
            if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):raise PermissionError('native status journal replaced while opening')
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('google_chat_profile_status','google_chat_profile_budget')")}
            if 'google_chat_profile_status' in tables:
                row=db.execute('SELECT status,updated_at,next_attempt FROM google_chat_profile_status WHERE connector=? AND credential_scope=? ORDER BY updated_at DESC LIMIT 1',
                    (params['connector'],params['credential_scope'])).fetchone()
                if row is not None:result.update(status=row[0],updated_at=row[1],next_attempt=row[2])
            if 'google_chat_profile_budget' in tables:
                row=db.execute('SELECT not_before FROM google_chat_profile_budget WHERE scope=?',(params['account_scope'],)).fetchone()
                if row is not None:
                    number=row[0]
                    if type(number) not in {int,float} or not math.isfinite(number) or not 0<=number<=253402300799:raise ValueError('finite original account retry budget required')
                    result['next_attempt']=max(result['next_attempt'],number)
            db.execute('COMMIT')
        finally:db.close()
    finally:os.close(descriptor)
    current();return checked(result,params)
