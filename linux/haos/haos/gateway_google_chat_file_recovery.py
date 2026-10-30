"""Offline Owner file decisions; never contact Google or expose payload/capabilities."""
import hashlib
import json
import time

from .gateway import Conflict,digest
from .gateway_google_chat import scope,resource,thread_allowed
from .gateway_google_chat_files import FileLedger,HEX


def current_grant(policy,connector,account,proof):
    try:
        binding=policy.current_binding({'binding_id':proof['binding_id'],'binding_digest':proof['binding_digest']})
        return (binding['connector']==connector and binding['scope']==scope(account)==proof['account_scope']
            and binding['sender']==proof['subject'] and binding['chat']==proof['chat'] and thread_allowed(binding,proof['thread'])
            and 'read' in binding['capabilities'] and binding.get('allow_outbound_media') is True)
    except (PermissionError,ValueError):return False


def retained_output(inbox,proof):
    db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():return False
    row=db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(proof['file_id'],)).fetchone()
    return bool(row is not None and row['state']=='retained' and isinstance(row['data'],bytes) and len(row['data'])==row['size']
        and row['delivery_id']==proof['source']['delivery_id'] and row['binding_digest']==proof['binding_digest']
        and row['binding_id']==proof['binding_id'] and row['credential_scope']==proof['credential_scope']
        and row['sha256']==proof['file_sha256']==hashlib.sha256(row['data']).hexdigest()
        and row['filename']==proof['filename'] and row['mime']==proof['mime']
        and row['offer_sha256']==digest({'id':row['offer_id'],'size':row['size'],'sha256':row['sha256']}))


def retained_source(inbox,originals,connector,account,proof,current):
    if originals is None:return False
    db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_native_projection'").fetchone():return False
    row=db.execute('''SELECT p.*,n.state,n.connector,n.message_id,n.fingerprint,n.binding_id,n.binding_digest AS native_binding
        FROM google_chat_native_projection p JOIN native_inbox n ON n.id=p.source_key WHERE p.source_key=?''',(proof['source']['source_key'],)).fetchone()
    if (row is None or row['state']!='committed' or row['connector']!=connector or row['message_id']!=proof['source']['source_id']
            or row['raw_sha256']!=proof['source']['source_sha256'] or row['binding_id']!=proof['binding_id']
            or row['binding_digest']!=proof['binding_digest'] or row['native_binding']!=proof['binding_digest']
            or row['envelope_sha256']!=row['fingerprint'] or row['credential_scope']!=digest([connector,account])):return False
    # Validate byte identity/proof directly, without reading private material
    # into the Owner response or rebuilding native events under a stale grant.
    stored=originals.db.execute('SELECT * FROM google_chat_originals WHERE id=?',(row['raw_id'],)).fetchone()
    if stored is None:return False
    try:originals._verify(stored);original=json.loads(stored['proof']);envelope=original['envelope']
    except (ValueError,KeyError,TypeError,Conflict):return False
    current()
    return (stored['raw_sha256']==row['raw_sha256'] and original['credential_scope']==row['credential_scope']
        and original['binding_digest']==proof['binding_digest'] and original['binding_id']==proof['binding_id']
        and all(envelope[k]==proof[v] for k,v in [('sender','subject'),('chat','chat'),('thread','thread')])
        and envelope['scope']==scope(account) and envelope['message_id']==proof['source']['source_id']
        and stored['admitted_receipt']==digest([connector,*(envelope[k] for k in ['scope','chat','thread','message_id'])]))


def view(inbox,ledger,record,policy,connector,account,originals,current):
    proof=json.loads(record['proof']);row=ledger.get(record['id'],proof)
    if proof['connector']!=connector or proof['account_scope']!=scope(account):raise PermissionError('selected Google file account required')
    grant=current_grant(policy,connector,account,proof);same=proof['credential_scope']==digest(account)
    source=retained_source(inbox,originals,connector,account,proof,current) if same else False
    output=retained_output(inbox,proof);eligible=grant and same and source and output
    result={k:row[k] for k in ['id','client_id','request_id','upload_state','state','receipt','created_at','owner_retry_generation','upload_retry_generation']}
    result.update(connector=connector,account_scope=proof['account_scope'],binding_id=proof['binding_id'],binding_digest=proof['binding_digest'],
        subject=proof['subject'],chat=proof['chat'],thread=proof['thread'],delivery_id=proof['source']['delivery_id'],source_id=proof['source']['source_id'],
        file_id=proof['file_id'],file_sha256=proof['file_sha256'],filename=proof['filename'],mime=proof['mime'],proof_sha256=row['proof_sha256'],
        caption_sha256=hashlib.sha256(proof['caption'].encode()).hexdigest(),caption_bytes=len(proof['caption'].encode()),
        upload_ref_sha256=digest(row['attachment_ref']),current_grant=grant,current_account=same,source_projection_available=source,output_available=output,
        upload_retry_allowed=eligible and row['state']=='prepared' and row['upload_state']=='uploading' and row['upload_retry_generation']<2,
        file_retry_allowed=eligible and row['state']=='writing' and row['owner_retry_generation']<4,
        private_bytes_returned=False,recipient_read_verified=False)
    return {**result,'snapshot_sha256':digest(result)}


def inventory(inbox,policy,connector,account,current,*,originals=None):
    current();ledger=FileLedger(inbox)
    rows=ledger.db.execute('SELECT * FROM google_chat_file_writes WHERE connector=? AND account_scope=? ORDER BY created_at DESC LIMIT 65',(connector,scope(account))).fetchall()
    values=[view(inbox,ledger,row,policy,connector,account,originals,current) for row in rows[:64]];current()
    return {'files':values,'history_truncated':len(rows)>64,'network_requested':False,'private_bytes_returned':False}


def decide(inbox,policy,connector,account,request,current,*,originals=None):
    fields={'id','action','snapshot_sha256','owner_uid','note_sha256','confirmed','confirmed_not_delivered'}
    if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True
            or not isinstance(request['action'],str) or request['action'] not in {'retry-upload','retry-file'} or type(request['confirmed_not_delivered']) is not bool
            or request['confirmed_not_delivered']!=(request['action']=='retry-file')
            or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','snapshot_sha256','note_sha256'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1):raise PermissionError('closed inspected explicitly confirmed Google file decision required')
    current();ledger=FileLedger(inbox);db=ledger.db;action=request['action'];operation=digest([connector,scope(account),request])
    def result(generation,receipt):return {'id':request['id'],'action':action,'generation':generation,'receipt':receipt,'approval_recorded':True,
        'network_requested':False,'message_sent':False,'same_source_user_file_and_stable_ids_required':True,'late_acceptance_check_before_create_required':action=='retry-file'}
    old=db.execute('SELECT * FROM google_chat_file_owner_events WHERE id=?',(operation,)).fetchone()
    if old is not None:return result(old['generation'],old['receipt'])
    record=db.execute('SELECT * FROM google_chat_file_writes WHERE id=?',(request['id'],)).fetchone()
    if record is None:raise PermissionError('retained Google file write required')
    snapshot=view(inbox,ledger,record,policy,connector,account,originals,current)
    if snapshot['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('Google file state changed after Owner inspection')
    if not snapshot['upload_retry_allowed' if action=='retry-upload' else 'file_retry_allowed']:raise PermissionError('Google file decision lacks source output or current grant / bounded retry budget')
    field='upload_retry_generation' if action=='retry-upload' else 'owner_retry_generation';generation=record[field]+1
    receipt=digest([operation,record['proof_sha256'],generation,time.time()])
    def approve():
        current()
        if db.execute('SELECT COUNT(*) FROM google_chat_file_owner_events').fetchone()[0]>=65536:raise Conflict('Google file Owner decision history full')
        db.execute('INSERT INTO google_chat_file_owner_events VALUES(?,?,?,?,?,?,?,?,?,?)',
            (operation,request['id'],action,generation,'approved',request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],receipt,time.time()))
        changed=(db.execute("UPDATE google_chat_file_writes SET upload_state='retry-approved',upload_retry_generation=? WHERE id=? AND upload_state='uploading' AND state='prepared' AND upload_retry_generation=?",
            (generation,request['id'],record[field])).rowcount if action=='retry-upload' else
            db.execute("UPDATE google_chat_file_writes SET state='owner-retry-approved',owner_retry_generation=? WHERE id=? AND state='writing' AND owner_retry_generation=?",
            (generation,request['id'],record[field])).rowcount)
        if changed!=1:raise Conflict('Google file Owner approval changed before commit')
    ledger._transaction(approve);current();return result(generation,receipt)


def output_view(policy,connector,row):
    if (any(not isinstance(row[k],str) or not HEX.fullmatch(row[k]) for k in ['id','delivery_id','binding_digest','credential_scope','offer_id','offer_sha256','sha256'])
            or row['id']!=digest([row['delivery_id'],row['offer_id']]) or type(row['size']) is not int or not 1<=row['size']<=8*1024*1024
            or row['offer_sha256']!=digest({'id':row['offer_id'],'size':row['size'],'sha256':row['sha256']})
            or not isinstance(row['data'],bytes) or row['state'] not in {'fetching','retained','purged'}):raise Conflict('damaged Google output identity; preserve and inspect journal')
    import re
    if (not isinstance(row['filename'],str) or not re.fullmatch('result-[0-9]{1,6}\\.[a-z0-9]{1,10}',row['filename'])
            or not isinstance(row['mime'],str) or not re.fullmatch('[a-z0-9.+-]+/[a-z0-9.+-]+',row['mime'])):raise Conflict('Google output metadata is not public bounded descriptor data')
    try:
        if policy is None:raise PermissionError('no active Root policy')
        binding=policy.current_binding({'binding_id':row['binding_id'],'binding_digest':row['binding_digest']})
        grant=(policy.connectors.get(binding['connector'],{}).get('platform')=='google_chat'
            and 'read' in binding['capabilities'] and binding.get('allow_outbound_media') is True)
    except PermissionError:grant=False
    actual=hashlib.sha256(row['data']).hexdigest() if row['data'] else None
    healthy=(row['state']=='retained' and len(row['data'])==row['size'] and actual==row['sha256']
        or row['state'] in {'fetching','purged'} and row['data']==b'')
    state=row['state'] if healthy else 'damaged'
    result={k:row[k] for k in ['id','delivery_id','binding_id','binding_digest','filename','mime','size','created_at']}
    result.update(expected_sha256=row['sha256'],actual_sha256=actual,stored_bytes=len(row['data']),state=state,
        current_grant=grant,purge_allowed=not grant and state!='purged',private_bytes_returned=False,
        remote_deletion_verified=False,other_copies_backups_and_WAL_erasure_not_claimed=True)
    return {**result,'snapshot_sha256':digest(result)}


def outputs(inbox,policy,connector,account,current):
    current();db=inbox.db
    from .gateway_google_chat_output_identity import backfill
    backfill(inbox,policy,connector,account)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():rows=[]
    else:rows=db.execute('''SELECT f.* FROM google_chat_output_files f JOIN google_chat_output_owners o ON o.file_id=f.id
        WHERE o.connector=? AND o.account_scope=? ORDER BY (f.state!='purged') DESC,f.created_at DESC LIMIT 65''',(connector,scope(account))).fetchall()
    from .gateway_google_chat_output_identity import owner
    for row in rows:owner(inbox,row)
    values=[output_view(policy,connector,row) for row in rows[:64]];current()
    return {'outputs':values,'history_truncated':len(rows)>64,'network_requested':False,'private_bytes_returned':False}


def purge(inbox,policy,connector,account,request,current):
    fields={'id','snapshot_sha256','owner_uid','note_sha256','confirmed'}
    if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True
            or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','snapshot_sha256','note_sha256'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1):raise PermissionError('explicit inspected Google output disposal required')
    current();db=inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_output_owner_events(
        id TEXT PRIMARY KEY,output_id TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
        snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')
    operation=digest([connector,scope(account),request]);old=db.execute('SELECT receipt FROM google_chat_output_owner_events WHERE id=?',(operation,)).fetchone()
    def result(receipt):return {'id':request['id'],'receipt':receipt,'network_requested':False,'message_sent':False,
        'tombstones_retained':True,'remote_deletion_verified':False,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    if old is not None:return result(old['receipt'])
    from .gateway_google_chat_output_identity import backfill,owner
    backfill(inbox,policy,connector,account)
    row=db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(request['id'],)).fetchone()
    associated=owner(inbox,row) if row is not None else None
    if associated is None or associated['connector']!=connector or associated['account_scope']!=scope(account):
        raise PermissionError('selected retained Google output app/connector ownership required')
    view=output_view(policy,connector,row)
    if view['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('Google output changed after Owner inspection')
    if not view['purge_allowed']:raise PermissionError('withdraw original output grant before local file disposal')
    receipt=digest([operation,row['sha256'],time.time()]);db.execute('BEGIN IMMEDIATE')
    try:
        current()
        if db.execute('SELECT COUNT(*) FROM google_chat_output_owner_events').fetchone()[0]>=65536:raise Conflict('Google output Owner history full')
        db.execute('INSERT INTO google_chat_output_owner_events VALUES(?,?,?,?,?,?,?)',
            (operation,row['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],receipt,time.time()))
        if db.execute("UPDATE google_chat_output_files SET data=x'',state='purged' WHERE id=? AND state=?",(row['id'],row['state'])).rowcount!=1:
            raise Conflict('Google output disposal changed before commit')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    current();return result(receipt)


def output_owned_view(inbox,policy,row,association):
    value=output_view(policy,association['connector'],row)
    value.pop('snapshot_sha256')
    value.update(connector=association['connector'],account_scope=association['account_scope'],ownership_sha256=digest(association))
    return {**value,'snapshot_sha256':digest(value)}


def outputs_identity(inbox,policy,identity,current):
    from .gateway_google_chat_identity import account_scope
    from .gateway_google_chat_output_identity import backfill_identity,owner
    current();expected=account_scope(identity);backfill_identity(inbox,expected);db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():rows=[]
    else:rows=db.execute('''SELECT f.* FROM google_chat_output_files f JOIN google_chat_output_owners o ON o.file_id=f.id
        WHERE o.account_scope=? ORDER BY (f.state!='purged') DESC,f.created_at DESC LIMIT 65''',(expected,)).fetchall()
    values=[output_owned_view(inbox,policy,row,owner(inbox,row)) for row in rows[:64]];current()
    return {'outputs':values,'history_truncated':len(rows)>64,'network_requested':False,'private_bytes_returned':False}


def purge_identity(inbox,policy,identity,request,current):
    fields={'id','snapshot_sha256','connector','ownership_sha256','owner_uid','note_sha256','confirmed'}
    from .gateway_google_chat_identity import account_scope
    from .gateway_google_chat_output_identity import owner,NAME
    if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True
            or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','snapshot_sha256','ownership_sha256','note_sha256'])
            or not isinstance(request['connector'],str) or not NAME.fullmatch(request['connector'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1):
        raise PermissionError('exact inspected historical output app/connector decision required')
    current();db=inbox.db;expected=account_scope(identity)
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_output_owner_events(
        id TEXT PRIMARY KEY,output_id TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
        snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')
    operation=digest(['historical-output-purge',expected,request])
    def result(receipt):return {'id':request['id'],'receipt':receipt,'network_requested':False,'message_sent':False,
        'tombstones_retained':True,'remote_deletion_verified':False,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    old=db.execute('SELECT receipt FROM google_chat_output_owner_events WHERE id=?',(operation,)).fetchone()
    if old is not None:return result(old['receipt'])
    row=db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(request['id'],)).fetchone()
    associated=owner(inbox,row) if row is not None else None
    if (associated is None or associated['account_scope']!=expected or associated['connector']!=request['connector']
            or digest(associated)!=request['ownership_sha256']):raise PermissionError('historical output ownership changed after inspection')
    view=output_owned_view(inbox,policy,row,associated)
    if view['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('historical output bytes/state changed after inspection')
    if not view['purge_allowed']:raise PermissionError('withdraw original output grant before historical byte disposal')
    receipt=digest([operation,row['sha256'],time.time()]);db.execute('BEGIN IMMEDIATE')
    try:
        current()
        if db.execute('SELECT COUNT(*) FROM google_chat_output_owner_events').fetchone()[0]>=65536:raise Conflict('Google output Owner history full')
        db.execute('INSERT INTO google_chat_output_owner_events VALUES(?,?,?,?,?,?,?)',
            (operation,row['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],receipt,time.time()))
        if db.execute("UPDATE google_chat_output_files SET data=x'',state='purged' WHERE id=? AND state=?",(row['id'],row['state'])).rowcount!=1:
            raise Conflict('historical output state changed before disposal commit')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    current();return result(receipt)


def unassociated_outputs(inbox,policy,current):
    from .gateway_google_chat_output_identity import prepare
    current();prepare(inbox);db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_output_files'").fetchone():rows=[]
    else:rows=db.execute('''SELECT f.* FROM google_chat_output_files f LEFT JOIN google_chat_output_owners o ON o.file_id=f.id
        WHERE o.file_id IS NULL ORDER BY (f.state!='purged') DESC,f.created_at DESC LIMIT 65''').fetchall()
    values=[output_view(policy,'',row) for row in rows[:64]];current()
    return {'outputs':values,'history_truncated':len(rows)>64,'network_requested':False,'private_bytes_returned':False}


def purge_unassociated(inbox,policy,request,current):
    from .gateway_google_chat_output_identity import owner
    fields={'id','snapshot_sha256','owner_uid','note_sha256','confirmed'}
    if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True
            or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','snapshot_sha256','note_sha256'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1):
        raise PermissionError('exact inspected unassociated output and explicit global Owner decision required')
    current();db=inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_output_owner_events(
        id TEXT PRIMARY KEY,output_id TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
        snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')
    operation=digest(['unassociated-output-purge',request])
    def result(receipt):return {'id':request['id'],'receipt':receipt,'network_requested':False,'message_sent':False,
        'tombstones_retained':True,'remote_deletion_verified':False,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    old=db.execute('SELECT receipt FROM google_chat_output_owner_events WHERE id=?',(operation,)).fetchone()
    if old is not None:return result(old['receipt'])
    row=db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(request['id'],)).fetchone()
    if row is None or owner(inbox,row) is not None:raise PermissionError('output is absent or now has app ownership; refresh the proper account view')
    value=output_view(policy,'',row)
    if value['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('unassociated output changed after inspection')
    if not value['purge_allowed']:raise PermissionError('any active original output grant blocks unassociated byte disposal')
    receipt=digest([operation,row['sha256'],time.time()]);db.execute('BEGIN IMMEDIATE')
    try:
        current()
        if db.execute('SELECT COUNT(*) FROM google_chat_output_owner_events').fetchone()[0]>=65536:raise Conflict('Google output Owner history full')
        if owner(inbox,row) is not None:raise Conflict('output acquired proven ownership before disposal')
        db.execute('INSERT INTO google_chat_output_owner_events VALUES(?,?,?,?,?,?,?)',
            (operation,row['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],receipt,time.time()))
        if db.execute("UPDATE google_chat_output_files SET data=x'',state='purged' WHERE id=? AND state=?",(row['id'],row['state'])).rowcount!=1:
            raise Conflict('unassociated output changed during disposal')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    current();return result(receipt)
