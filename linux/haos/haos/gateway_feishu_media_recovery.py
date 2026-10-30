"""Inspected offline per-part decisions; upload keys never leave the private ledger."""
import json
import math
import re
import time

from .gateway import GatewayPolicy,Conflict,digest
from .gateway_feishu import MESSAGE_ID
from .gateway_feishu_process import ERRORS

TABLES={'upload':'feishu_upload_intents','reply':'feishu_media_reply_intents'}
HASH=re.compile('[0-9a-f]{64}\\Z')


def row(record,operation):
    value=dict(record)
    if (set(value)!={'delivery_id','part','attempt','connector','credential_scope','fingerprint','state','receipt',
            'receipt_sha256','error','created_at','updated_at'}
            or any(not isinstance(value[k],str) or not HASH.fullmatch(value[k]) for k in ['delivery_id','credential_scope','fingerprint'])
            or not isinstance(value['connector'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',value['connector'])
            or type(value['part']) is not int or not 0<=value['part']<4
            or type(value['attempt']) is not int or not 1<=value['attempt']<=5
            or value['state'] not in {'writing','confirmed','uncertain','rejected','owner-retry-approved'}
            or not isinstance(value['receipt'],str) or not isinstance(value['receipt_sha256'],str) or not isinstance(value['error'],str)
            or value['state']=='rejected' and value['error'] not in ERRORS|{'native-refused'}
            or value['state']!='rejected' and value['error']
            or any(type(value[k]) not in {int,float} or not math.isfinite(value[k]) or value[k]<=0 for k in ['created_at','updated_at'])):
        raise Conflict('damaged private Feishu media decision')
    if value['state']=='confirmed':
        if (not 1<=len(value['receipt'])<=512 or not HASH.fullmatch(value['receipt_sha256'])
                or digest([value['fingerprint'],value['receipt']])!=value['receipt_sha256']):
            raise Conflict('damaged private Feishu media acceptance proof')
        try:receipt=json.loads(value['receipt'])
        except ValueError:raise Conflict('invalid private Feishu media acceptance') from None
        if not isinstance(receipt,dict) or json.dumps(receipt,sort_keys=True,separators=(',',':'))!=value['receipt']:
            raise Conflict('noncanonical private Feishu media acceptance')
        if operation=='upload':
            if (set(receipt)!={'state','kind','key'} or receipt['state']!='confirmed' or not isinstance(receipt['kind'],str) or receipt['kind'] not in {'image','file'}
                    or not isinstance(receipt['key'],str)
                    or not re.fullmatch(('img_' if receipt['kind']=='image' else 'file_')+'[A-Za-z0-9_-]{8,251}',receipt['key'])):
                raise Conflict('invalid private Feishu upload acceptance')
        elif (set(receipt)!={'state','message_id'} or receipt['state']!='confirmed'
                or not isinstance(receipt['message_id'],str) or not MESSAGE_ID.fullmatch(receipt['message_id'])):
            raise Conflict('invalid private Feishu media reply acceptance')
    elif value['receipt'] or value['receipt_sha256']:raise Conflict('unconfirmed Feishu media decision has a receipt')
    return value


def outgoing(inbox):
    result=[]
    for operation,table in TABLES.items():
        if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        for record in inbox.db.execute(f'SELECT * FROM {table} ORDER BY updated_at DESC LIMIT 64'):
            value=row(record,operation)
            result.append({'platform':'feishu','operation':operation,'part':value['part'],'connector':value['connector'],
                'delivery_id':value['delivery_id'],'attempt':value['attempt'],'state':value['state'],
                'native_acceptance_receipt_sha256':value['receipt_sha256'] or None,'error':value['error'] or None,
                'updated_at':value['updated_at'],'snapshot_sha256':digest(value),'recipient_read_verified':False})
    return result


def approve_retry(inbox,policy,request):
    required={'connector','delivery_id','part','operation','attempt','snapshot_sha256','owner_uid','note_sha256','confirmed','confirmed_not_accepted'}
    if (not isinstance(request,dict) or set(request)!=required or request['confirmed'] is not True
            or request['confirmed_not_accepted'] is not True or type(request['owner_uid']) is not int
            or not 0<=request['owner_uid']<2**32-1 or type(request['attempt']) is not int or not 1<=request['attempt']<5
            or type(request['part']) is not int or not 0<=request['part']<4
            or not isinstance(request['operation'],str) or request['operation'] not in TABLES
            or any(not isinstance(request[k],str) or not HASH.fullmatch(request[k]) for k in ['delivery_id','snapshot_sha256','note_sha256'])
            or not isinstance(request['connector'],str) or not isinstance(policy,GatewayPolicy)
            or policy.connectors.get(request['connector'],{}).get('platform')!='feishu'
            or not any(b['connector']==request['connector'] and 'read' in b['capabilities'] and b.get('allow_outbound_media') is True for b in policy.bindings.values())):
        raise PermissionError('exact inspected per-part Feishu decision and independent non-acceptance confirmation required')
    db=inbox.db;table=TABLES[request['operation']];db.execute('BEGIN IMMEDIATE')
    key=(request['delivery_id'],request['part'],request['attempt'],request['operation'])
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS feishu_media_owner_events(
            delivery_id TEXT NOT NULL,part INTEGER NOT NULL,attempt INTEGER NOT NULL,operation TEXT NOT NULL,
            connector TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
            previous_state TEXT NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,part,attempt,operation))''')
        previous=db.execute('SELECT * FROM feishu_media_owner_events WHERE delivery_id=? AND part=? AND attempt=? AND operation=?',key).fetchone()
        if previous is not None:
            if any(previous[k]!=request[k] for k in ['connector','owner_uid','note_sha256','snapshot_sha256']):
                raise Conflict('Feishu per-part decision already recorded under another inspection')
        else:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():raise KeyError('unknown private Feishu media ledger')
            record=db.execute(f'SELECT * FROM {table} WHERE delivery_id=? AND part=? AND attempt=?',key[:3]).fetchone()
            if record is None:raise KeyError('unknown private Feishu media intent')
            value=row(record,request['operation'])
            if value['connector']!=request['connector'] or digest(value)!=request['snapshot_sha256']:
                raise Conflict('Feishu per-part decision changed after inspection')
            if value['state'] not in {'writing','uncertain','rejected'} or value['receipt']:
                raise PermissionError('confirmed Feishu media acceptance cannot be released')
            db.execute(f"UPDATE {table} SET state='owner-retry-approved',error='',updated_at=? WHERE delivery_id=? AND part=? AND attempt=?",(time.time(),*key[:3]))
            db.execute('INSERT INTO feishu_media_owner_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (*key,request['connector'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],value['state'],
                    digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return {'delivery_id':request['delivery_id'],'part':request['part'],'operation':request['operation'],'attempt':request['attempt'],
        'private_retry_approved':True,'controller_reconciliation_still_required':True,'network_requested':False,'recipient_read_verified':False}
