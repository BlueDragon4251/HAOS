"""Offline inspected private DingTalk delivery decisions; no network or send capability.

Only the owner-authorized stopped-service handoff may call these functions with
an actual private gateway ledger. Public CLI/GUI wiring remains separate.
"""
import math
import re
import time

from .gateway import GatewayPolicy,Conflict,digest
from .gateway_dingtalk_delivery import MESSAGE_ID
from .gateway_dingtalk_reply_process import ERRORS

HASH=re.compile('[0-9a-f]{64}\\Z')


def row(value):
    value=dict(value)
    if (set(value)!={'delivery_id','attempt','connector','credential_scope','fingerprint','state','receipt','error','created_at','updated_at'}
            or any(not isinstance(value[key],str) or not HASH.fullmatch(value[key]) for key in ['delivery_id','credential_scope','fingerprint'])
            or not isinstance(value['connector'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',value['connector'])
            or type(value['attempt']) is not int or not 1<=value['attempt']<=5
            or value['state'] not in {'writing','confirmed','uncertain','rejected','owner-retry-approved'}
            or not isinstance(value['receipt'],str) or not isinstance(value['error'],str)
            or value['state']=='confirmed' and not MESSAGE_ID.fullmatch(value['receipt'])
            or value['state']!='confirmed' and value['receipt']
            or value['state']=='rejected' and value['error'] not in ERRORS|{'native-refused'}
            or value['state']!='rejected' and value['error']
            or any(type(value[key]) not in {int,float} or not math.isfinite(value[key]) or value[key]<=0 for key in ['created_at','updated_at'])):
        raise Conflict('damaged private DingTalk delivery metadata')
    return value


def outgoing(inbox):
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dingtalk_delivery_intents'").fetchone():return []
    result=[]
    for record in inbox.db.execute('SELECT * FROM dingtalk_delivery_intents ORDER BY updated_at DESC LIMIT 64'):
        value=row(record)
        result.append({'platform':'dingtalk','connector':value['connector'],'delivery_id':value['delivery_id'],
            'attempt':value['attempt'],'state':value['state'],'native_acceptance_receipt':value['receipt'] or None,
            'error':value['error'] or None,'updated_at':value['updated_at'],'recipient_read_verified':False,
            'snapshot_sha256':digest(value)})
    return result


def approve_retry(inbox,policy,request):
    required={'connector','delivery_id','attempt','snapshot_sha256','owner_uid','note_sha256','confirmed','confirmed_not_delivered'}
    if (not isinstance(request,dict) or set(request)!=required or request['confirmed'] is not True
            or request['confirmed_not_delivered'] is not True or type(request['owner_uid']) is not int
            or not 0<=request['owner_uid']<2**32-1 or type(request['attempt']) is not int or not 1<=request['attempt']<5
            or any(not isinstance(request[key],str) or not HASH.fullmatch(request[key]) for key in ['delivery_id','snapshot_sha256','note_sha256'])
            or not isinstance(request['connector'],str) or not isinstance(policy,GatewayPolicy)
            or policy.connectors.get(request['connector'],{}).get('platform')!='dingtalk'
            or not any(binding['connector']==request['connector'] and 'read' in binding['capabilities'] for binding in policy.bindings.values())):
        raise PermissionError('exact inspected current DingTalk owner decision and independent non-delivery confirmation required')
    db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_delivery_owner_events(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,previous_state TEXT NOT NULL,
            policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(delivery_id,attempt))''')
        previous=db.execute('SELECT * FROM dingtalk_delivery_owner_events WHERE delivery_id=? AND attempt=?',
            (request['delivery_id'],request['attempt'])).fetchone()
        if previous is not None:
            if any(previous[key]!=request[key] for key in ['connector','owner_uid','note_sha256','snapshot_sha256']):
                raise Conflict('DingTalk retry decision already recorded under another inspection')
        else:
            record=db.execute('SELECT * FROM dingtalk_delivery_intents WHERE delivery_id=? AND attempt=?',
                (request['delivery_id'],request['attempt'])).fetchone()
            if record is None:raise KeyError('unknown private DingTalk write intent')
            value=row(record)
            if value['connector']!=request['connector'] or digest(value)!=request['snapshot_sha256']:
                raise Conflict('DingTalk delivery state or connector changed after owner inspection')
            if value['state'] not in {'writing','uncertain','rejected'} or value['receipt']:
                raise PermissionError('confirmed DingTalk acceptance cannot be released for another write')
            db.execute("UPDATE dingtalk_delivery_intents SET state='owner-retry-approved',error='',updated_at=? WHERE delivery_id=? AND attempt=?",
                (time.time(),request['delivery_id'],request['attempt']))
            db.execute('INSERT INTO dingtalk_delivery_owner_events VALUES(?,?,?,?,?,?,?,?,?)',
                (request['delivery_id'],request['attempt'],request['connector'],request['owner_uid'],request['note_sha256'],
                    request['snapshot_sha256'],value['state'],digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return {'delivery_id':request['delivery_id'],'attempt':request['attempt'],'private_retry_approved':True,
        'controller_reconciliation_still_required':True,'network_requested':False,'recipient_read_verified':False}


def accounts(inbox):
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dingtalk_delivery_backoff'").fetchone():return []
    result=[]
    for record in inbox.db.execute('SELECT * FROM dingtalk_delivery_backoff ORDER BY updated_at DESC LIMIT 64'):
        value=dict(record)
        if (set(value)!={'account_scope','status','next_attempt','updated_at'} or not isinstance(value['account_scope'],str)
                or not HASH.fullmatch(value['account_scope']) or value['status'] not in {'ready','rate-limited','authentication-refused'}
                or any(type(value[key]) not in {int,float} or not math.isfinite(value[key]) or value[key]<0 for key in ['next_attempt','updated_at'])):
            raise Conflict('damaged private DingTalk account metadata')
        result.append({**value,'platform':'dingtalk','snapshot_sha256':digest(value),'network_requested':False})
    return result


def retry_auth(inbox,policy,request):
    required={'connector','credential_scope','account_scope','owner_uid','note_sha256'}
    if (not isinstance(request,dict) or set(request)!=required or not isinstance(request['connector'],str)
            or not isinstance(policy,GatewayPolicy) or policy.connectors.get(request['connector'],{}).get('platform')!='dingtalk'
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or any(not isinstance(request[k],str) or not HASH.fullmatch(request[k]) for k in ['credential_scope','account_scope','note_sha256'])):
        raise PermissionError('exact current DingTalk account and owner authentication-recheck decision required')
    db=inbox.db;changed=0;now=time.time();db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dingtalk_profile_status'").fetchone():
            changed+=db.execute("UPDATE dingtalk_profile_status SET status='created',updated_at=?,next_attempt=MAX(next_attempt,0) "
                "WHERE connector=? AND credential_scope=? AND status='authentication-refused'",
                (now,request['connector'],request['credential_scope'])).rowcount
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dingtalk_delivery_backoff'").fetchone():
            changed+=db.execute("UPDATE dingtalk_delivery_backoff SET status='ready',updated_at=? WHERE account_scope=? AND status='authentication-refused'",
                (now,request['account_scope'])).rowcount
        if changed:
            db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_auth_owner_events(connector TEXT NOT NULL,credential_scope TEXT NOT NULL,
                account_scope TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,policy_sha256 TEXT NOT NULL,
                changed INTEGER NOT NULL,created_at REAL NOT NULL)''')
            db.execute('INSERT INTO dingtalk_auth_owner_events VALUES(?,?,?,?,?,?,?,?)',
                (request['connector'],request['credential_scope'],request['account_scope'],request['owner_uid'],request['note_sha256'],
                    digest([policy.publication,policy.connectors,policy.bindings]),changed,now))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return {'connector':request['connector'],'authentication_blocks_cleared':changed,'network_requested':False}
