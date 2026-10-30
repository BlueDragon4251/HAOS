"""Inspected offline per-part decisions; upload keys never leave the private ledger."""
import json
import math
import re
import time

from .gateway import GatewayPolicy,Conflict,digest
from .gateway_dingtalk_delivery import MESSAGE_ID
from .gateway_dingtalk_reply_process import ERRORS,response as reply_response
from .gateway_dingtalk_upload import response as upload_response

TABLES={'upload':'dingtalk_upload_intents','reply':'dingtalk_media_reply_intents'}
HASH=re.compile('[0-9a-f]{64}\\Z')


def row(record,operation):
    value=dict(record)
    if (set(value)!={'delivery_id','part','attempt','connector','credential_scope','fingerprint','state','receipt',
            'receipt_sha256','error','created_at','updated_at'}
            or any(not isinstance(value[k],str) or not HASH.fullmatch(value[k]) for k in ['delivery_id','credential_scope','fingerprint'])
            or not isinstance(value['connector'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',value['connector'])
            or type(value['part']) is not int or not 0<=value['part']<(8 if operation=='upload' else 4)
            or type(value['attempt']) is not int or not 1<=value['attempt']<=5
            or value['state'] not in {'writing','confirmed','uncertain','rejected','owner-retry-approved'}
            or not isinstance(value['receipt'],str) or not isinstance(value['receipt_sha256'],str) or not isinstance(value['error'],str)
            or value['state']=='rejected' and value['error'] not in ERRORS|{'native-refused'}
            or value['state']!='rejected' and value['error']
            or any(type(value[k]) not in {int,float} or not math.isfinite(value[k]) or value[k]<=0 for k in ['created_at','updated_at'])):
        raise Conflict('damaged private DingTalk media decision')
    if value['state']=='confirmed':
        if (not 1<=len(value['receipt'])<=32768 or not HASH.fullmatch(value['receipt_sha256'])
                or digest([value['fingerprint'],value['receipt']])!=value['receipt_sha256']):
            raise Conflict('damaged private DingTalk media acceptance proof')
        try:receipt=json.loads(value['receipt'])
        except ValueError:raise Conflict('invalid private DingTalk media acceptance') from None
        if not isinstance(receipt,dict) or json.dumps(receipt,sort_keys=True,separators=(',',':'))!=value['receipt']:
            raise Conflict('noncanonical private DingTalk media acceptance')
        try:
            if operation=='upload':
                if receipt.get('kind') not in {'image','file','voice','video'}:raise ValueError('reviewed native upload kind required')
                checked=upload_response(receipt,{'kind':receipt['kind']})
            else:checked=reply_response(receipt)
            if checked['state']!='confirmed':raise ValueError('confirmed native part acceptance required')
        except (ValueError,TypeError,KeyError):raise Conflict('invalid private DingTalk part acceptance') from None
    elif value['receipt'] or value['receipt_sha256']:raise Conflict('unconfirmed DingTalk media decision has a receipt')
    return value


def outgoing(inbox):
    result=[]
    for operation,table in TABLES.items():
        if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        for record in inbox.db.execute(f'SELECT * FROM {table} ORDER BY updated_at DESC LIMIT 64'):
            value=row(record,operation)
            result.append({'platform':'dingtalk','operation':operation,'part':value['part'],'connector':value['connector'],
                'delivery_id':value['delivery_id'],'attempt':value['attempt'],'state':value['state'],
                'native_acceptance_receipt_sha256':value['receipt_sha256'] or None,'error':value['error'] or None,
                'updated_at':value['updated_at'],'snapshot_sha256':digest(value),'recipient_read_verified':False})
    return result


def approve_retry(inbox,policy,request):
    required={'connector','delivery_id','part','operation','attempt','snapshot_sha256','owner_uid','note_sha256','confirmed','confirmed_not_accepted'}
    if (not isinstance(request,dict) or set(request)!=required or request['confirmed'] is not True
            or request['confirmed_not_accepted'] is not True or type(request['owner_uid']) is not int
            or not 0<=request['owner_uid']<2**32-1 or type(request['attempt']) is not int or not 1<=request['attempt']<5
            or type(request['part']) is not int or not 0<=request['part']<(8 if request.get('operation')=='upload' else 4)
            or not isinstance(request['operation'],str) or request['operation'] not in TABLES
            or any(not isinstance(request[k],str) or not HASH.fullmatch(request[k]) for k in ['delivery_id','snapshot_sha256','note_sha256'])
            or not isinstance(request['connector'],str) or not isinstance(policy,GatewayPolicy)
            or policy.connectors.get(request['connector'],{}).get('platform')!='dingtalk'
            or not any(b['connector']==request['connector'] and 'read' in b['capabilities'] and b.get('allow_outbound_media') is True for b in policy.bindings.values())):
        raise PermissionError('exact inspected per-part DingTalk decision and independent non-acceptance confirmation required')
    db=inbox.db;table=TABLES[request['operation']];db.execute('BEGIN IMMEDIATE')
    key=(request['delivery_id'],request['part'],request['attempt'],request['operation'])
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_media_owner_events(
            delivery_id TEXT NOT NULL,part INTEGER NOT NULL,attempt INTEGER NOT NULL,operation TEXT NOT NULL,
            connector TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
            previous_state TEXT NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,part,attempt,operation))''')
        previous=db.execute('SELECT * FROM dingtalk_media_owner_events WHERE delivery_id=? AND part=? AND attempt=? AND operation=?',key).fetchone()
        if previous is not None:
            if any(previous[k]!=request[k] for k in ['connector','owner_uid','note_sha256','snapshot_sha256']):
                raise Conflict('DingTalk per-part decision already recorded under another inspection')
        else:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():raise KeyError('unknown private DingTalk media ledger')
            record=db.execute(f'SELECT * FROM {table} WHERE delivery_id=? AND part=? AND attempt=?',key[:3]).fetchone()
            if record is None:raise KeyError('unknown private DingTalk media intent')
            value=row(record,request['operation'])
            if value['connector']!=request['connector'] or digest(value)!=request['snapshot_sha256']:
                raise Conflict('DingTalk per-part decision changed after inspection')
            if value['state'] not in {'writing','uncertain','rejected'} or value['receipt']:
                raise PermissionError('confirmed DingTalk media acceptance cannot be released')
            db.execute(f"UPDATE {table} SET state='owner-retry-approved',error='',updated_at=? WHERE delivery_id=? AND part=? AND attempt=?",(time.time(),*key[:3]))
            db.execute('INSERT INTO dingtalk_media_owner_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (*key,request['connector'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],value['state'],
                    digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return {'delivery_id':request['delivery_id'],'part':request['part'],'operation':request['operation'],'attempt':request['attempt'],
        'private_retry_approved':True,'controller_reconciliation_still_required':True,'network_requested':False,'recipient_read_verified':False}


def batches(inbox):
    """Recover a whole-batch local proof only from every committed part receipt."""
    db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dingtalk_output_manifests'").fetchone():return []
    from .gateway_dingtalk_recovery import row as text_row
    result=[]
    for record in db.execute('SELECT * FROM dingtalk_output_manifests ORDER BY created_at DESC LIMIT 64'):
        value=dict(record)
        if (set(value)!={'delivery_id','connector','credential_scope','binding_id','binding_digest','source_sha256','fingerprint','manifest','created_at'}
                or any(not isinstance(value[k],str) or not HASH.fullmatch(value[k]) for k in ['delivery_id','credential_scope','binding_digest','source_sha256','fingerprint'])
                or any(not isinstance(value[k],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',value[k]) for k in ['connector','binding_id'])
                or not isinstance(value['manifest'],str) or len(value['manifest'].encode())>32768
                or type(value['created_at']) not in {int,float} or not math.isfinite(value['created_at']) or value['created_at']<=0):
            raise Conflict('damaged private DingTalk batch manifest')
        try:manifest=json.loads(value['manifest'])
        except (ValueError,RecursionError):raise Conflict('invalid private DingTalk batch manifest') from None
        if (not isinstance(manifest,dict) or set(manifest)!={'items','text'} or not isinstance(manifest['items'],list)
                or not 1<=len(manifest['items'])<=4 or not isinstance(manifest['text'],str)
                or len(manifest['text'])>4000 or len(manifest['text'].encode())>16000
                or json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False)!=value['manifest']):
            raise Conflict('noncanonical private DingTalk batch manifest')
        caption=None;complete=True;accepted=[];confirmed_parts=0
        if manifest['text'].strip():
            texts=[text_row(record) for record in db.execute('SELECT * FROM dingtalk_delivery_intents WHERE delivery_id=?',(value['delivery_id'],))]
            good=[r for r in texts if r['state']=='confirmed' and r['connector']==value['connector'] and r['credential_scope']==value['credential_scope']]
            if len(good)>1:raise Conflict('ambiguous private DingTalk caption acceptance')
            if not good:complete=False
            else:caption=good[0]['receipt']
        for part,item in enumerate(manifest['items']):
            if not isinstance(item,dict) or item.get('kind') not in {'image','file','voice','video'} or 'cover' not in item:
                raise Conflict('invalid private DingTalk batch part')
            required=[('upload',part),('reply',part)]
            if item['cover'] is not None:
                if item['kind']!='video' or not isinstance(item['cover'],dict):raise Conflict('invalid private batch cover')
                required.append(('upload',part+4))
            elif item['kind']=='video':raise Conflict('private batch video has no retained cover')
            part_complete=True
            for operation,index in required:
                records=[row(record,operation) for record in db.execute(f'SELECT * FROM {TABLES[operation]} WHERE delivery_id=? AND part=?',(value['delivery_id'],index))]
                good=[r for r in records if r['state']=='confirmed' and r['connector']==value['connector'] and r['credential_scope']==value['credential_scope']]
                if len(good)>1:raise Conflict('ambiguous private DingTalk part acceptance')
                if not good:part_complete=False
                elif operation=='reply':accepted.append(json.loads(good[0]['receipt'])['acceptance_id'])
            if part_complete:confirmed_parts+=1
            else:complete=False
        acceptance='haos-dingtalk-'+digest([value['delivery_id'],value['fingerprint'],caption,accepted]) if complete else None
        result.append({'platform':'dingtalk','connector':value['connector'],'delivery_id':value['delivery_id'],
            'state':'confirmed' if complete else 'incomplete','parts':len(manifest['items']),'confirmed_parts':confirmed_parts,
            'native_acceptance_receipt':acceptance,'recipient_read_verified':False,'remote_message_id':None})
    return result
