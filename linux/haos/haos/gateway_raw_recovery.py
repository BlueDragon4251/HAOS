"""Offline owner decisions, executed only as the private gateway ledger UID."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import resource
import sys
import time

from .gateway import Conflict, GatewayPolicy
from .gateway_raw import NativeInbox
from .redaction import Redactor

DATABASE = Path('/var/lib/haos-gateway/native-inbox.db')
UNRESOLVED = {'pending','processing','failed','expired','revoked'}


def unresolved(inbox, after=0):
    if type(after) is not int or after < 0:
        raise ValueError('invalid ingress cursor')
    rows = inbox.db.execute("""SELECT rowid AS cursor,* FROM native_inbox
        WHERE state IN ('pending','processing','failed','expired','revoked') AND rowid>?
        ORDER BY rowid LIMIT 100""",(after,)).fetchall()
    result = []
    for row in rows:
        if not re.fullmatch('[0-9a-f]{64}',row['id']) or type(row['attempt']) is not int or not 0 <= row['attempt'] <= 8:
            raise ValueError('invalid native receipt metadata')
        pattern=(r'[1-9][0-9]{0,15}\.[0-9]{6}' if row['platform']=='slack' else
            r'[1-9][0-9]{0,19}' if row['platform']=='discord' else
            r'[a-z0-9]{26}' if row['platform']=='mattermost' else
            r'[0-9a-f]{64}' if row['platform'] in {'homeassistant','irc','line'} else
            r'(?:SM|MM)[0-9a-fA-F]{32}' if row['platform']=='sms' else
            r'[A-Za-z0-9_-]{1,64}' if row['platform']=='ntfy' else None)
        from .gateway_matrix_policy import opaque
        valid=opaque(row['message_id'],'$') if row['platform']=='matrix' else pattern is not None and re.fullmatch(pattern,row['message_id'])
        if not valid:
            raise ValueError('invalid native source metadata')
        result.append({'cursor':row['cursor'],'ingress_id':row['id'],'state':row['state'],'platform':row['platform'],
            'message_id':row['message_id'],
            'attempt':row['attempt'],'created_at':row['created_at'],
            'payload_sha256':hashlib.sha256(row['payload'].encode()).hexdigest()})
    history=[]
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='discord_history_status'").fetchone():
        for row in inbox.db.execute('SELECT binding_digest,status,updated_at FROM discord_history_status ORDER BY updated_at DESC LIMIT 512'):
            if (not re.fullmatch('[0-9a-f]{64}',row['binding_digest']) or row['status'] not in
                    {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}):
                raise ValueError('invalid history status metadata')
            history.append(dict(row))
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='slack_history'").fetchone():
        for row in inbox.db.execute('SELECT binding_digest,status,updated_at FROM slack_history ORDER BY updated_at DESC LIMIT 512'):
            if (not re.fullmatch('[0-9a-f]{64}',row['binding_digest']) or row['status'] not in
                    {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}):
                raise ValueError('invalid Slack history status metadata')
            history.append({**dict(row),'platform':'slack'})
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mattermost_history'").fetchone():
        for row in inbox.db.execute('SELECT binding_digest,status,updated_at FROM mattermost_history ORDER BY updated_at DESC LIMIT 512'):
            if (not re.fullmatch('[0-9a-f]{64}',row['binding_digest']) or row['status'] not in
                    {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}):
                raise ValueError('invalid Mattermost history status metadata')
            history.append({**dict(row),'platform':'mattermost'})
    transport=[]
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mattermost_transport'").fetchone():
        from .gateway_mattermost import TRANSPORT_KINDS
        import math
        for row in inbox.db.execute('SELECT connector,status,updated_at FROM mattermost_transport ORDER BY updated_at DESC LIMIT 64'):
            if (not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector']) or row['status'] not in TRANSPORT_KINDS
                    or type(row['updated_at']) not in {int,float} or not math.isfinite(row['updated_at']) or row['updated_at']<=0):
                raise ValueError('invalid Mattermost transport status metadata')
            transport.append({**dict(row),'platform':'mattermost'})
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matrix_transport'").fetchone():
        import math
        from .gateway_matrix_profile import PROFILE_STATES
        for row in inbox.db.execute('SELECT connector,status,last_error,updated_at,next_sync,pending_pages,history_gaps,history_error FROM matrix_transport ORDER BY updated_at DESC LIMIT 64'):
            if (not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector']) or row['status'] not in PROFILE_STATES
                    or row['last_error'] not in PROFILE_STATES|{''}
                    or any(type(row[name]) not in {int,float} or not math.isfinite(row[name]) or row[name]<0 for name in ('updated_at','next_sync'))
                    or type(row['pending_pages']) is not int or not 0<=row['pending_pages']<=65536
                    or type(row['history_gaps']) is not int or not 0<=row['history_gaps']<=4096
                    or row['history_error'] not in {'','rate-limited','source-unavailable','transport-unavailable','invalid-page'}):
                raise ValueError('invalid Matrix transport status metadata')
            transport.append({**dict(row),'platform':'matrix'})
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ntfy_profile_status'").fetchone():
        import math
        from .gateway_ntfy_profile import STATES
        for row in inbox.db.execute('SELECT * FROM ntfy_profile_status ORDER BY updated_at DESC LIMIT 64'):
            if (not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                    or row['status'] not in STATES or row['last_error'] not in STATES|{''}
                    or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<0 for key in ('updated_at','next_attempt'))):
                raise ValueError('invalid ntfy transport metadata')
            transport.append({**dict(row),'platform':'ntfy'})
    for platform,table in [('homeassistant','homeassistant_profile_status'),('irc','irc_profile_status')]:
        if not inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        import math
        if platform=='homeassistant':
            from .gateway_homeassistant_profile import PROFILE_STATES as states
        else:
            from .gateway_irc_profile import STATES as states
        fields='connector,status,updated_at,next_attempt,gap_since'
        detailed=platform=='irc' and 'last_error' in {row[1] for row in inbox.db.execute(f'PRAGMA table_info({table})')}
        if detailed:fields+=',last_error'
        for row in inbox.db.execute(f'SELECT {fields} FROM {table} ORDER BY updated_at DESC LIMIT 64'):
            if (not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                    or row['status'] not in states
                    or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<0
                        for key in ('updated_at','next_attempt','gap_since'))):
                raise ValueError('invalid private gateway transport metadata')
            if detailed:
                from .gateway_irc_transport import DIAGNOSTICS
                if not isinstance(row['last_error'],str) or row['last_error'] and row['last_error'] not in DIAGNOSTICS:
                    raise ValueError('invalid private IRC diagnostic')
            transport.append({**dict(row),'platform':platform,'unseen_remote_history_recovered':False})
    from .gateway_irc_recovery import outgoing
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='line_profile_status'").fetchone():
        from .gateway_line_profile import STATES as line_states
        import math
        for row in inbox.db.execute('SELECT connector,status,updated_at,next_attempt FROM line_profile_status ORDER BY updated_at DESC LIMIT 64'):
            if (not isinstance(row['connector'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                    or row['status'] not in line_states or any(type(row[key]) not in {int,float}
                        or not math.isfinite(row[key]) or row[key]<0 for key in ('updated_at','next_attempt'))):
                raise ValueError('invalid private LINE profile inspection metadata')
            transport.append({**dict(row),'platform':'line','external_tls_ingress_verified':False})
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sms_profile_status'").fetchone():
        from .gateway_sms_profile import STATES as sms_states
        import math
        for row in inbox.db.execute('SELECT connector,status,updated_at,next_attempt FROM sms_profile_status ORDER BY updated_at DESC LIMIT 64'):
            if (not isinstance(row['connector'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                    or row['status'] not in sms_states or any(type(row[key]) not in {int,float}
                        or not math.isfinite(row[key]) or row[key]<0 for key in ('updated_at','next_attempt'))):
                raise ValueError('invalid private SMS profile inspection metadata')
            transport.append({**dict(row),'platform':'sms','external_tls_ingress_verified':False})
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sms_recovery_status'").fetchone():
        import math
        for row in inbox.db.execute('SELECT connector,status,updated_at,next_attempt FROM sms_recovery_status ORDER BY updated_at DESC LIMIT 64'):
            if (not isinstance(row['connector'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                    or row['status'] not in {'backfill-ready','backfill-unavailable'} or any(type(row[key]) not in {int,float}
                        or not math.isfinite(row[key]) or row[key]<0 for key in ('updated_at','next_attempt'))):
                raise ValueError('invalid private SMS API recovery metadata')
            transport.append({**dict(row),'platform':'sms','external_tls_ingress_verified':False})
    rejected=[]
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sms_recovery_rejections'").fetchone():
        import math
        for row in inbox.db.execute('SELECT message_sid,reason,created_at FROM sms_recovery_rejections ORDER BY created_at DESC LIMIT 64'):
            if (not isinstance(row['message_sid'],str) or not re.fullmatch(r'(?:SM|MM)[0-9a-fA-F]{32}',row['message_sid'])
                    or row['reason']!='unsupported-content' or type(row['created_at']) not in {int,float}
                    or not math.isfinite(row['created_at']) or row['created_at']<0):
                raise ValueError('invalid private SMS recovery refusal receipt')
            rejected.append({'platform':'sms',**dict(row)})
    from .gateway_line_recovery import outgoing as line_outgoing
    return {'ingress':result,'history':history,'transport':transport,'recovery_rejections':rejected,'native_outgoing':outgoing(inbox)+line_outgoing(inbox)+line_outgoing(inbox,'sms'),
        'next_cursor':rows[-1]['cursor'] if rows else after}


def reconcile(inbox, policy, request):
    if set(request) != {'ingress_id','attempt','state','decision','owner_uid','note_sha256'}:
        raise ValueError('invalid owner ingress decision')
    key, attempt, state, decision = (request[name] for name in ('ingress_id','attempt','state','decision'))
    if (not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key)
            or type(attempt) is not int or not 0 <= attempt <= 8 or state not in UNRESOLVED
            or decision not in {'retry','discard'} or type(request['owner_uid']) is not int
            or not 0 <= request['owner_uid'] < 2**32-1 or not isinstance(request['note_sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}',request['note_sha256'])):
        raise ValueError('invalid owner ingress evidence')
    inbox.db.execute('BEGIN IMMEDIATE')
    try:
        row = inbox.db.execute('SELECT * FROM native_inbox WHERE id=?',(key,)).fetchone()
        if row is None: raise KeyError('unknown native ingress')
        if row['state'] != state or row['attempt'] != attempt or state not in UNRESOLVED:
            raise Conflict('stale native ingress decision')
        if decision == 'retry':
            if state != 'failed':
                raise Conflict('only failed native decoding may be retried by owner')
            policy.current_binding(dict(row))
            if time.time() >= row['created_at']+86400:
                raise Conflict('expired native input must not execute as a new request')
            target = 'pending'
            inbox.db.execute("UPDATE native_inbox SET state='pending',attempt=0,next_attempt=0 WHERE id=?",(key,))
        else:
            target = 'discarded'
            # Preserve original payload, timestamps and receipt for owner review.
            inbox.db.execute("UPDATE native_inbox SET state='discarded' WHERE id=?",(key,))
        inbox.db.execute('''CREATE TABLE IF NOT EXISTS native_owner_events (
            id INTEGER PRIMARY KEY, ingress_id TEXT NOT NULL, created_at REAL NOT NULL,
            owner_uid INTEGER NOT NULL, decision TEXT NOT NULL, previous_state TEXT NOT NULL,
            previous_attempt INTEGER NOT NULL, note_sha256 TEXT NOT NULL)''')
        inbox.db.execute('INSERT INTO native_owner_events(ingress_id,created_at,owner_uid,decision,previous_state,previous_attempt,note_sha256) VALUES(?,?,?,?,?,?,?)',
            (key,time.time(),request['owner_uid'],decision,state,attempt,request['note_sha256']))
        inbox.db.execute('COMMIT')
    except BaseException:
        inbox.db.execute('ROLLBACK'); raise
    return {'ingress_id':key,'attempt':attempt,'decision':decision,'state':target}


def _recheck_connector(policy,request,platform):
    if (not isinstance(policy,GatewayPolicy) or not isinstance(request,dict)
            or set(request)!={'connector','owner_uid','note_sha256'}
            or not isinstance(request['connector'],str)
            or policy.connectors.get(request['connector'],{}).get('platform')!=platform
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or not isinstance(request['note_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',request['note_sha256'])):
        raise ValueError('exact gateway connector and authenticated owner audit context required')
    return request['connector']


def retry_ntfy_auth(inbox,policy,request):
    # Explicit owner recheck permission; never an authentication or send bypass.
    from .gateway import digest
    connector=_recheck_connector(policy,request,'ntfy')
    changed=0
    inbox.db.execute('BEGIN IMMEDIATE')
    try:
        if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ntfy_subscription'").fetchone():
            changed=inbox.db.execute("UPDATE ntfy_subscription SET status='ready',next_attempt=0 WHERE connector=? AND status='authentication-denied'",(connector,)).rowcount
        if changed:
            inbox.db.execute('CREATE TABLE IF NOT EXISTS ntfy_owner_events ('
                'connector TEXT NOT NULL, created_at REAL NOT NULL, owner_uid INTEGER NOT NULL,'
                'decision TEXT NOT NULL, changed INTEGER NOT NULL, policy_sha256 TEXT NOT NULL, note_sha256 TEXT NOT NULL)')
            authority=digest([policy.publication,sorted(digest(b) for b in policy.bindings.values() if b['connector']==connector)])
            inbox.db.execute('INSERT INTO ntfy_owner_events VALUES(?,?,?,?,?,?,?)',
                (connector,time.time(),request['owner_uid'],'retry-auth',changed,authority,request['note_sha256']))
        inbox.db.execute('COMMIT')
    except BaseException:
        inbox.db.execute('ROLLBACK');raise
    return {'connector':connector,'authentication_blocks_cleared':changed,'network_requested':False}


def _retry_private_auth(inbox,policy,request,platform):
    from .gateway import digest
    if platform not in {'homeassistant','irc','line','sms'}:raise ValueError('unsupported private authentication recheck')
    connector=_recheck_connector(policy,request,platform);changed=0
    table=platform+'_profile_status';events=platform+'_owner_events'
    inbox.db.execute('BEGIN IMMEDIATE')
    try:
        if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            now=time.time()
            refused=('authentication-refused','identity-refused') if platform in {'line','sms'} else ('authentication-refused',)
            placeholders=','.join('?' for _ in refused)
            changed=inbox.db.execute(f"UPDATE {table} SET status='created',updated_at=?,"
                "next_attempt=CASE WHEN next_attempt>? THEN next_attempt ELSE 0 END "
                f"WHERE connector=? AND status IN ({placeholders})",(now,now,connector,*refused)).rowcount
        if changed:
            inbox.db.execute(f'CREATE TABLE IF NOT EXISTS {events} ('
                'connector TEXT NOT NULL, created_at REAL NOT NULL, owner_uid INTEGER NOT NULL,'
                'decision TEXT NOT NULL, changed INTEGER NOT NULL, policy_sha256 TEXT NOT NULL, note_sha256 TEXT NOT NULL)')
            authority=digest([policy.publication,sorted(digest(b) for b in policy.bindings.values() if b['connector']==connector)])
            inbox.db.execute(f'INSERT INTO {events} VALUES(?,?,?,?,?,?,?)',
                (connector,time.time(),request['owner_uid'],'retry-auth',changed,authority,request['note_sha256']))
        inbox.db.execute('COMMIT')
    except BaseException:
        inbox.db.execute('ROLLBACK');raise
    return {'connector':connector,'authentication_blocks_cleared':changed,'network_requested':False}


def retry_homeassistant_auth(inbox,policy,request):
    """Permit a fresh server check; never clear revocation, gaps or rate limits."""
    return _retry_private_auth(inbox,policy,request,'homeassistant')


def retry_irc_auth(inbox,policy,request):
    """Offline owner decision; retain revocation, gaps and rate limits."""
    return _retry_private_auth(inbox,policy,request,'irc')


def retry_line_auth(inbox,policy,request):
    """Offline owner recheck; preserve rate limits, retained input and revocation."""
    return _retry_private_auth(inbox,policy,request,'line')


def retry_sms_auth(inbox,policy,request):
    return _retry_private_auth(inbox,policy,request,'sms')


def main():
    account = pwd.getpwnam('haos-gateway')
    if os.geteuid() == 0 or os.geteuid() != account.pw_uid:
        raise PermissionError('native ingress recovery requires the unprivileged gateway UID')
    resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(5,5)); resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    raw = sys.stdin.buffer.read(1024*1024+1)
    if len(raw) > 1024*1024: raise ValueError('owner request exceeds bound')
    data = json.loads(raw)
    if not isinstance(data,dict) or set(data) != {'action','policy','params'} or not isinstance(data['params'],dict):
        raise ValueError('invalid ingress recovery request')
    policy = GatewayPolicy(data['policy'])
    try:DATABASE.lstat()
    except FileNotFoundError:
        if data['action']=='media-cache' and data['params']=={}:
            print(json.dumps({'uploads':[],'stored_bytes':0,'reserved_bytes':0,'limit_bytes':64*1024*1024,'limit_records':128,'native_journal_created':False}))
            return
        if data['action']=='ingress' and set(data['params'])=={'after'}:
            after=data['params']['after']
            if type(after) is not int or after<0:raise ValueError('invalid ingress cursor')
            print(json.dumps({'ingress':[],'history':[],'next_cursor':after,'native_journal_created':False}))
            return
        if data['action'] in {'retry-ntfy-auth','retry-homeassistant-auth','retry-irc-auth','retry-line-auth','retry-sms-auth'}:
            platform={'retry-ntfy-auth':'ntfy','retry-homeassistant-auth':'homeassistant','retry-irc-auth':'irc','retry-line-auth':'line','retry-sms-auth':'sms'}[data['action']]
            connector=_recheck_connector(policy,data['params'],platform)
            print(json.dumps({'connector':connector,'authentication_blocks_cleared':0,
                'network_requested':False,'native_journal_created':False}))
            return
        raise
    inbox = NativeInbox(DATABASE,Redactor())
    try:
        if data['action'] == 'ingress' and set(data['params']) == {'after'}:
            result = unresolved(inbox,data['params']['after'])
        elif data['action'] in {'media-cache','purge-media-cache'}:
            from .gateway_media_relay import MediaCache
            cache=MediaCache(inbox)
            if data['action']=='media-cache':
                if data['params']!={}:raise ValueError('cache inventory takes no selectors')
                result=cache.owner_inventory(policy)
            else:result=cache.owner_purge(policy,data['params'])
        elif data['action'] == 'retry-ntfy-auth':
            result=retry_ntfy_auth(inbox,policy,data['params'])
        elif data['action'] == 'retry-irc-auth':
            result=retry_irc_auth(inbox,policy,data['params'])
        elif data['action'] == 'retry-sms-auth':
            result=retry_sms_auth(inbox,policy,data['params'])
        elif data['action'] == 'retry-line-auth':
            result=retry_line_auth(inbox,policy,data['params'])
        elif data['action'] == 'retry-homeassistant-auth':
            result=retry_homeassistant_auth(inbox,policy,data['params'])
        elif data['action'] == 'reconcile-ingress':
            result = reconcile(inbox,policy,data['params'])
        else: raise ValueError('unknown ingress recovery action')
        print(json.dumps(result))
    finally: inbox.close()


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(type(error).__name__,file=sys.stderr); raise SystemExit(1)
