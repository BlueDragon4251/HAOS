"""Private metadata snapshots and audited auth/source recovery; no dispatch."""
import hashlib
import json
import math
import re
import time

from .gateway import Conflict,digest
from .gateway_google_chat import credentials,scope,resource,thread_allowed

HEX=re.compile('[0-9a-f]{64}\\Z')


def profile_name(value):
    if not isinstance(value,str) or not re.fullmatch('google-chat-[0-9a-f]{64}',value):raise ValueError('exact opaque Google Chat profile required')
    return value


def decision(value,fields):
    if (not isinstance(value,dict) or set(value)!=fields|{'owner_uid','note_sha256','confirmed'} or value['confirmed'] is not True
            or type(value['owner_uid']) is not int or not 0<=value['owner_uid']<2**32-1
            or not isinstance(value.get('note_sha256'),str) or not HEX.fullmatch(value['note_sha256'])
            or 'snapshot_sha256' in fields and (not isinstance(value.get('snapshot_sha256'),str) or not HEX.fullmatch(value['snapshot_sha256']))):
        raise PermissionError('closed inspected Google Chat owner decision required')


def source_view(record,policy,profile):
    profile_name(profile);row=dict(record);raw=row['raw']
    if (any(not isinstance(row[key],str) or not HEX.fullmatch(row[key]) for key in ['id','credential_scope','binding_digest','semantic_sha256','raw_sha256'])
            or not isinstance(raw,bytes) or len(raw)>1048576 or not isinstance(row['proof'],str) or len(row['proof'].encode())>65536
            or row['admitted_receipt'] and (not isinstance(row['admitted_receipt'],str) or not HEX.fullmatch(row['admitted_receipt']))
            or type(row['created_at']) not in {int,float} or not math.isfinite(row['created_at'])):
        raise Conflict('damaged Google Chat source custody')
    resource(row['message_id'],'message')
    try:binding=policy.current_binding(row);current=binding['connector']==row['connector']
    except PermissionError:current=False
    actual=hashlib.sha256(raw).hexdigest() if raw else None
    public={key:row[key] for key in ['id','connector','message_id','binding_id','binding_digest','created_at','admitted_receipt']}
    public.update(profile=profile,source_sha256=row['raw_sha256'],actual_sha256=actual,stored_bytes=len(raw),
        proof_sha256=digest(row['proof']),current_grant=current,purge_allowed=not current,
        state='purged' if not raw else 'retained' if actual==row['raw_sha256'] else 'damaged',
        authentication_reverified=False,private_bytes_returned=False)
    return {**public,'snapshot_sha256':digest(public)}


def sources(store,policy,profile):
    rows=store.db.execute('SELECT * FROM google_chat_originals ORDER BY (length(raw)>0) DESC,created_at DESC LIMIT 129').fetchall()
    return {'profile':profile_name(profile),'sources':[source_view(row,policy,profile) for row in rows[:128]],
        'history_truncated':len(rows)>128,'network_requested':False,'private_bytes_returned':False}


def purge_source(store,policy,request):
    decision(request,{'profile','id','snapshot_sha256'});profile_name(request['profile'])
    if not isinstance(request['id'],str) or not HEX.fullmatch(request['id']):raise ValueError('exact retained Google Chat original ID required')
    db=store.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS google_chat_source_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')
        row=db.execute('SELECT * FROM google_chat_originals WHERE id=?',(request['id'],)).fetchone()
        if row is None:raise KeyError('unknown Google Chat original')
        view=source_view(row,policy,request['profile'])
        if not view['purge_allowed']:raise PermissionError('withdraw or change the original Google Chat grant before disposal')
        old=db.execute('SELECT * FROM google_chat_source_owner_events WHERE id=?',(request['id'],)).fetchone()
        if old is not None:
            if any(old[k]!=request[k] for k in ['owner_uid','note_sha256','snapshot_sha256']):raise Conflict('Google Chat source disposal belongs to another inspection')
            receipt=old['receipt']
        else:
            if view['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('Google Chat source changed after inspection')
            receipt=digest([request,view,policy.publication]);proof=json.dumps({'purged':True,'proof_sha256':digest(row['proof'])},separators=(',',':'))
            db.execute("UPDATE google_chat_originals SET raw=x'',proof=? WHERE id=?",(proof,request['id']))
            db.execute('INSERT INTO google_chat_source_owner_events VALUES(?,?,?,?,?,?)',
                (request['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],receipt,time.time()))
        db.execute('COMMIT');return {'id':request['id'],'receipt':receipt,'network_requested':False,'message_sent':False,
            'tombstones_retained':True,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise


def retry_auth(inbox,policy,connector,value,request):
    decision(request,{'connector'})
    value=credentials(value)
    if (request['connector']!=connector or policy.connectors.get(connector,{}).get('platform')!='google_chat'):
        raise PermissionError('exact current Google Chat connector required')
    identity=digest([connector,value]);db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS google_chat_auth_owner_events(receipt TEXT PRIMARY KEY,connector TEXT NOT NULL,
            credential_scope TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,cleared INTEGER NOT NULL,created_at REAL NOT NULL)''')
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='google_chat_profile_status'").fetchone()
        count=0
        if exists:
            rows=db.execute('SELECT * FROM google_chat_profile_status WHERE connector=? AND credential_scope=?',(connector,identity)).fetchall()
            if len(rows)>65536:raise Conflict('Google Chat auth status history exceeds bound')
            count=db.execute("UPDATE google_chat_profile_status SET status='created',updated_at=? WHERE connector=? AND credential_scope=? AND status IN ('authentication-refused','identity-refused')",
                (time.time(),connector,identity)).rowcount
        receipt=digest([request,identity,count,time.time()])
        db.execute('INSERT INTO google_chat_auth_owner_events VALUES(?,?,?,?,?,?,?)',
            (receipt,connector,identity,request['owner_uid'],request['note_sha256'],count,time.time()))
        # Never alter next_attempt or the account budget table here.
        db.execute('COMMIT');return {'connector':connector,'authentication_blocks_cleared':count,'receipt':receipt,
            'network_requested':False,'message_sent':False}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise


def group_view(inbox,policy,connector,value,record):
    row=dict(record);value=credentials(value)
    hashes=['id','binding_digest','credential_scope','source_sha256','context_sha256','content_sha256']
    if (any(not isinstance(row[k],str) or not HEX.fullmatch(row[k]) for k in hashes)
            or not isinstance(row.get('connector'),str) or row['connector']!=connector
            or type(row['parts']) is not int or not 1<=row['parts']<=64 or row['state'] not in {'writing','confirmed'}):
        raise Conflict('damaged Google Chat controller write group')
    resource(row['source_id'],'message');chat=row['source_id'].split('/messages/')[0]
    try:binding=policy.current_binding(row);active=binding['connector']==connector and binding['scope']==scope(value) and 'read' in binding['capabilities']
    except PermissionError:active=False
    same_account=row['credential_scope']==digest(value)
    projection=inbox.db.execute('''SELECT p.source_key FROM google_chat_native_projection p JOIN native_inbox n ON n.id=p.source_key
        WHERE n.connector=? AND n.message_id=? AND n.binding_id=? AND n.binding_digest=? AND n.state='committed'
        AND p.raw_sha256=? AND p.binding_digest=? AND p.credential_scope=? AND p.envelope_sha256=n.fingerprint''',
        (connector,row['source_id'],row['binding_id'],row['binding_digest'],row['source_sha256'],row['binding_digest'],digest([connector,value]))).fetchall()
    if len(projection)>1:raise Conflict('ambiguous Google Chat original projection')
    parts=[]
    if projection:
        import uuid
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        for index in range(row['parts']):
            identity=digest([row['id'],projection[0]['source_key'],index])
            part=inbox.db.execute('SELECT * FROM google_chat_text_writes WHERE id=?',(identity,)).fetchone()
            if part is None:
                parts.append({'id':identity,'part':index,'state':'not-started','receipt':None,'body_sha256':None,'body_bytes':0,'retry_generation':0});continue
            if (part['binding_id']!=row['binding_id'] or part['binding_digest']!=row['binding_digest']
                    or part['credential_scope']!=row['credential_scope'] or part['parent']!=chat
                    or part['client_id']!='client-'+identity[:56]
                    or part['request_id']!=str(uuid.uuid5(uuid.NAMESPACE_URL,'haos-google-chat:'+identity))
                    or part['state'] not in {'writing','confirmed','owner-retry-approved'}
                    or type(part['owner_retry_generation']) is not int or not 0<=part['owner_retry_generation']<=4
                    or not isinstance(part['body'],str) or not 1<=len(part['body'].encode())<=65536):
                raise Conflict('Google Chat native part differs from root write group')
            body=json.loads(part['body'],object_pairs_hook=_object,parse_constant=finite)
            if (not isinstance(body,dict) or not {'text'}<=set(body)<={'text','thread'} or not isinstance(body['text'],str)
                    or not 1<=len(body['text'].encode())<=16384 or json.dumps(body,sort_keys=True,separators=(',',':'))!=part['body']):
                raise Conflict('damaged retained Google Chat native text bytes')
            if body.get('thread'):
                if not isinstance(body['thread'],dict) or set(body['thread'])!={'name'}:raise Conflict('damaged Google Chat part thread')
                resource(body['thread']['name'],'thread',space=chat)
            if active and not thread_allowed(binding,body.get('thread',{}).get('name','')):raise Conflict('Google Chat retained part differs from exact source reply grant')
            if part['state']=='confirmed':resource(part['receipt'],'message',space=chat)
            elif part['receipt']:raise Conflict('unconfirmed Google Chat part has a fabricated receipt')
            parts.append({'id':identity,'part':index,'state':part['state'],'receipt':part['receipt'] or None,
                'body_sha256':hashlib.sha256(part['body'].encode()).hexdigest(),'body_bytes':len(part['body'].encode()),'retry_generation':part['owner_retry_generation']})
    confirmed=sum(p['state']=='confirmed' for p in parts)
    if row['state']=='confirmed' and (confirmed!=row['parts'] or row['receipt']!=parts[-1]['receipt']):
        raise Conflict('Google Chat root acceptance lacks all exact native part receipts')
    if row['state']!='confirmed' and row['receipt']:raise Conflict('unconfirmed Google Chat root group has a fabricated receipt')
    public={k:row[k] for k in ['id','connector','binding_id','binding_digest','source_id','source_sha256','context_sha256','content_sha256','state']}
    public.update(expected_parts=row['parts'],confirmed_parts=confirmed,receipt=row['receipt'] or None,
        current_account=same_account,current_grant=active and same_account,source_projection_available=bool(projection),
        parts=parts,private_bytes_returned=False,recipient_read_verified=False)
    return {**public,'snapshot_sha256':digest(public)}


def outgoing(inbox,policy,connector,value):
    if policy.connectors.get(connector,{}).get('platform')!='google_chat':raise PermissionError('selected Google Chat connector required')
    exists=inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='google_chat_delivery_groups'").fetchone()
    rows=inbox.db.execute('SELECT * FROM google_chat_delivery_groups WHERE connector=? ORDER BY rowid DESC LIMIT 65',(connector,)).fetchall() if exists else []
    return {'outgoing':[group_view(inbox,policy,connector,value,row) for row in rows[:64]],'history_truncated':len(rows)>64,
        'network_requested':False,'private_bytes_returned':False}


def approve_retry(inbox,policy,connector,value,request):
    """Release one exact uncertain native part, never send or reset other parts."""
    decision(request,{'connector','id','part_id','snapshot_sha256','confirmed_not_delivered'})
    if (request['connector']!=connector or policy.connectors.get(connector,{}).get('platform')!='google_chat'
            or request['confirmed_not_delivered'] is not True
            or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','part_id'])):
        raise PermissionError('independent non-delivery confirmation for one exact Google Chat part required')
    db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS google_chat_reply_owner_events(
            receipt TEXT PRIMARY KEY,group_id TEXT NOT NULL,part_id TEXT NOT NULL,generation INTEGER NOT NULL,
            snapshot_sha256 TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
            created_at REAL NOT NULL,consumed_at REAL,UNIQUE(part_id,generation),UNIQUE(part_id,snapshot_sha256))""")
        row=db.execute('SELECT * FROM google_chat_delivery_groups WHERE id=?',(request['id'],)).fetchone()
        if row is None:raise KeyError('unknown Google Chat controller write group')
        view=group_view(inbox,policy,connector,value,row)
        if not view['current_grant'] or not view['source_projection_available']:
            raise PermissionError('current exact account, source and reply/read grant required')
        old=db.execute('SELECT * FROM google_chat_reply_owner_events WHERE part_id=? AND snapshot_sha256=?',
            (request['part_id'],request['snapshot_sha256'])).fetchone()
        if old is not None:
            if old['group_id']!=request['id'] or any(old[k]!=request[k] for k in ['owner_uid','note_sha256']):
                raise Conflict('Google Chat retry already belongs to another Owner inspection')
            receipt=old['receipt'];generation=old['generation']
        else:
            if view['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('Google Chat reply changed after inspection')
            part=next((p for p in view['parts'] if p['id']==request['part_id']),None)
            if view['state']!='writing' or part is None or part['state']!='writing' or part['receipt'] or part['retry_generation']>=4:
                raise PermissionError('only a begun unconfirmed Google Chat part can receive a bounded retry decision')
            generation=part['retry_generation']+1;receipt=digest([request,generation,policy.publication])
            changed=db.execute("UPDATE google_chat_text_writes SET state='owner-retry-approved',owner_retry_generation=? WHERE id=? AND state='writing' AND owner_retry_generation=?",
                (generation,request['part_id'],part['retry_generation'])).rowcount
            if changed!=1:raise Conflict('Google Chat part changed during Owner decision')
            db.execute('INSERT INTO google_chat_reply_owner_events VALUES(?,?,?,?,?,?,?,?,NULL)',
                (receipt,request['id'],request['part_id'],generation,request['snapshot_sha256'],request['owner_uid'],request['note_sha256'],time.time()))
        db.execute('COMMIT')
        return {'id':request['id'],'part_id':request['part_id'],'receipt':receipt,'retry_generation':generation,
            'private_retry_approved':True,'stable_client_and_request_id_reuse_required':True,'network_requested':False,'message_sent':False}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
