"""Stopped-service owner inspection; no network or message-send capability."""
import time
import math

from .gateway import GatewayPolicy,Conflict,digest
from .gateway_buzz import HEX
from .gateway_buzz_delivery import validate


def transport(inbox):
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='buzz_profile_status'").fetchone():return []
    states={'created','connecting','connected-ws','connected-poll','disconnected','closed','revoked',
        'authentication-refused','identity-refused','rate-limited','transport-unavailable','source-unavailable','storage-unavailable'}
    result=[]
    for record in inbox.db.execute('SELECT connector,status,updated_at,next_attempt FROM buzz_profile_status ORDER BY updated_at DESC LIMIT 64'):
        row=dict(record)
        if (not isinstance(row['connector'],str) or not 1<=len(row['connector'])<=128 or row['status'] not in states
                or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<0 for key in ['updated_at','next_attempt'])):
            raise Conflict('damaged private Buzz transport status')
        result.append({'platform':'buzz',**row})
    return result


def retry_auth(inbox,policy,value,request):
    from .gateway_buzz import credentials
    if (not isinstance(policy,GatewayPolicy) or not isinstance(request,dict)
            or set(request)!={'connector','owner_uid','note_sha256','confirmed'} or request['confirmed'] is not True
            or not isinstance(request['connector'],str) or policy.connectors.get(request['connector'],{}).get('platform')!='buzz'
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or not isinstance(request['note_sha256'],str) or not HEX.fullmatch(request['note_sha256'])):
        raise PermissionError('explicit current Buzz account authentication recheck required')
    account=digest([request['connector'],credentials(value)]);db=inbox.db;changed=0
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='buzz_profile_status'").fetchone():
            changed=db.execute("UPDATE buzz_profile_status SET status='created',updated_at=? WHERE connector=? AND credential_scope=? AND status IN ('authentication-refused','identity-refused')",
                (time.time(),request['connector'],account)).rowcount
        db.execute('''CREATE TABLE IF NOT EXISTS buzz_auth_owner_events(
            connector TEXT NOT NULL,credential_scope TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
            changed INTEGER NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')
        db.execute('INSERT INTO buzz_auth_owner_events VALUES(?,?,?,?,?,?,?)',(request['connector'],account,
            request['owner_uid'],request['note_sha256'],changed,digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return {'connector':request['connector'],'authentication_blocks_cleared':changed,'network_requested':False,'message_sent':False}


def snapshot(row):
    value=validate(row)
    return digest({key:part for key,part in value.items() if key!='signed_raw'})


def outgoing(inbox):
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='buzz_delivery_intents'").fetchone():return []
    result=[]
    for record in inbox.db.execute('SELECT * FROM buzz_delivery_intents ORDER BY updated_at DESC LIMIT 64'):
        row=validate(record)
        result.append({'platform':'buzz','connector':row['connector'],'delivery_id':row['delivery_id'],'attempt':row['attempt'],
            'state':row['state'],'native_acceptance_receipt':row['receipt'] or None,'signed_event_id':row['event_id'] or None,
            'error':row['error'] or None,'updated_at':row['updated_at'],'recipient_read_verified':False,
            'snapshot_sha256':snapshot(row)})
    return result


def approve_retry(inbox,policy,request):
    fields={'connector','delivery_id','attempt','snapshot_sha256','owner_uid','note_sha256','confirmed','confirmed_not_delivered'}
    if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True or request['confirmed_not_delivered'] is not True
            or not isinstance(request['connector'],str) or not isinstance(policy,GatewayPolicy) or policy.connectors.get(request['connector'],{}).get('platform')!='buzz'
            or type(request['attempt']) is not int or not 1<=request['attempt']<5 or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or any(not isinstance(request[key],str) or not HEX.fullmatch(request[key]) for key in ['delivery_id','snapshot_sha256','note_sha256'])):
        raise PermissionError('exact inspected current Buzz owner decision and independent non-delivery confirmation required')
    db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS buzz_delivery_owner_events(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,previous_state TEXT NOT NULL,
            policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(delivery_id,attempt))''')
        previous=db.execute('SELECT * FROM buzz_delivery_owner_events WHERE delivery_id=? AND attempt=?',
            (request['delivery_id'],request['attempt'])).fetchone()
        record=db.execute('SELECT * FROM buzz_delivery_intents WHERE delivery_id=? AND attempt=?',(request['delivery_id'],request['attempt'])).fetchone()
        if record is None:raise KeyError('unknown private Buzz write intent')
        row=validate(record)
        if row['connector']!=request['connector']:raise Conflict('Buzz delivery connector changed after owner inspection')
        binding=policy.current_binding({'binding_id':row['binding_id'],'binding_digest':row['binding_digest']})
        if binding['connector']!=request['connector'] or 'read' not in binding['capabilities']:
            raise PermissionError('current exact Buzz source reply/read grant required')
        if previous is not None:
            if any(previous[key]!=request[key] for key in ['connector','owner_uid','note_sha256','snapshot_sha256']):
                raise Conflict('Buzz retry decision already recorded under another owner inspection')
        else:
            if snapshot(row)!=request['snapshot_sha256']:
                raise Conflict('Buzz delivery changed after owner inspection')
            if row['state'] not in {'writing','uncertain','rejected'} or row['receipt']:
                raise PermissionError('confirmed Buzz acceptance cannot be released for another write')
            db.execute("UPDATE buzz_delivery_intents SET state='owner-retry-approved',error='',updated_at=? WHERE delivery_id=? AND attempt=?",
                (time.time(),request['delivery_id'],request['attempt']))
            db.execute('INSERT INTO buzz_delivery_owner_events VALUES(?,?,?,?,?,?,?,?,?)',
                (request['delivery_id'],request['attempt'],request['connector'],request['owner_uid'],request['note_sha256'],
                    request['snapshot_sha256'],row['state'],digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return {'delivery_id':request['delivery_id'],'attempt':request['attempt'],'private_retry_approved':True,
        'signed_event_reuse_required':bool(row['signed_raw'])}
