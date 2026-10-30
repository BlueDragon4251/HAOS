"""Offline inspected upload decisions; never upload, publish or erase proofs."""
import hashlib
import re
import time

from .gateway import Conflict,digest,GatewayPolicy
from .gateway_buzz import HEX,credentials,scope


def _events(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='buzz_upload_owner_events'").fetchone())


def projection(db,record,policy):
    row=dict(record)
    fields={'id','delivery_id','proof','binding_digest','credential_scope','name','source_sha256','state','descriptor',
        'source_bytes','stored_bytes','created_at'}
    if (set(row)!=fields or any(not isinstance(row[key],str) or not HEX.fullmatch(row[key])
            for key in ['id','delivery_id','proof','binding_digest','credential_scope','source_sha256'])
            or not isinstance(row['name'],str) or not re.fullmatch('result-[0-9]{1,6}(?:\\.[a-z0-9]{1,11})?',row['name'])
            or row['state'] not in {'uploading','retry-approved','ready','purged'}
            or any(type(row[key]) is not int or not 0<=row[key]<=8388608 for key in ['source_bytes','stored_bytes'])
            or not isinstance(row['descriptor'],str) or len(row['descriptor'].encode())>65536
            or type(row['created_at']) not in {int,float} or not 0<row['created_at']<=253402300799):
        raise Conflict('damaged Buzz upload recovery metadata')
    # The retained binding digest is exact; find no recipient by approximation.
    matching=[binding for binding in policy.bindings.values() if digest(binding)==row['binding_digest']]
    current=bool(len(matching)==1 and policy.connectors[matching[0]['connector']]['platform']=='buzz')
    approvals=db.execute('SELECT COUNT(*) FROM buzz_upload_owner_events WHERE id=? AND action=?',
        (row['id'],'retry-upload')).fetchone()[0] if _events(db) else 0
    public={key:row[key] for key in ['id','delivery_id','name','source_sha256','state','source_bytes','stored_bytes','created_at']}
    public.update(current_grant=current,purge_allowed=not current,retry_approvals=approvals,
        metadata_sha256=digest(row),private_bytes_returned=False)
    return {**public,'snapshot_sha256':digest(public)}


SELECT='SELECT id,delivery_id,proof,binding_digest,credential_scope,name,source_sha256,state,descriptor,length(source) AS source_bytes,length(stored) AS stored_bytes,created_at FROM buzz_output_uploads'


def inventory(inbox,policy):
    if not isinstance(policy,GatewayPolicy):raise PermissionError('current independent Buzz owner policy required')
    db=inbox.db
    rows=db.execute(SELECT+' ORDER BY created_at DESC LIMIT 129').fetchall() if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='buzz_output_uploads'").fetchone() else []
    return {'outputs':[projection(db,row,policy) for row in rows[:128]],'history_truncated':len(rows)>128,
        'network_requested':False,'private_bytes_returned':False}


def decide(inbox,policy,value,request):
    fields={'id','action','snapshot_sha256','owner_uid','note_sha256','confirmed'}
    if (not isinstance(policy,GatewayPolicy) or not isinstance(request,dict) or set(request)!=fields
            or not isinstance(request['action'],str) or request['action'] not in {'retry-upload','purge-upload'} or request['confirmed'] is not True
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or any(not isinstance(request[key],str) or not HEX.fullmatch(request[key]) for key in ['id','snapshot_sha256','note_sha256'])):
        raise PermissionError('exact inspected Buzz upload decision and owner identity required')
    value=credentials(value);db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS buzz_upload_owner_events(
            id TEXT NOT NULL,action TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL,
            PRIMARY KEY(id,action,snapshot_sha256))''')
        previous=db.execute('SELECT * FROM buzz_upload_owner_events WHERE id=? AND action=? AND snapshot_sha256=?',
            (request['id'],request['action'],request['snapshot_sha256'])).fetchone()
        record=db.execute(SELECT+' WHERE id=?',(request['id'],)).fetchone()
        if record is None:raise KeyError('unknown Buzz upload custody')
        view=projection(db,record,policy)
        if previous is not None:
            if any(previous[key]!=request[key] for key in ['owner_uid','note_sha256']):raise Conflict('Buzz upload decision belongs to another inspection')
            receipt=previous['receipt']
        else:
            if view['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('Buzz upload changed after owner inspection')
            if request['action']=='purge-upload':
                if not view['purge_allowed']:raise PermissionError('withdraw or change original grant before Buzz upload disposal')
                db.execute("UPDATE buzz_output_uploads SET state='purged',source=x'',stored=x'' WHERE id=?",(request['id'],))
            else:
                matches=[binding for binding in policy.bindings.values() if digest(binding)==record['binding_digest']]
                if (not view['current_grant'] or len(matches)!=1 or matches[0]['scope']!=scope(value)
                        or 'read' not in matches[0]['capabilities'] or matches[0].get('allow_outbound_media') is not True
                        or record['credential_scope']!=digest(value)):
                    raise PermissionError('same current Buzz account, exact grant and outbound-media/read approval required')
                if (record['state']!='uploading' or record['descriptor'] or record['stored_bytes'] or view['retry_approvals']>=2):
                    raise PermissionError('only a bounded unresolved unsigned Buzz upload may be retried')
                source=db.execute('SELECT source FROM buzz_output_uploads WHERE id=?',(request['id'],)).fetchone()[0]
                if not isinstance(source,bytes) or not 1<=len(source)<=8388608 or hashlib.sha256(source).hexdigest()!=record['source_sha256']:
                    raise Conflict('Buzz upload source damaged; automatic restoration refused')
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='buzz_delivery_intents'").fetchone():
                    if db.execute('SELECT 1 FROM buzz_delivery_intents WHERE delivery_id=? AND length(signed_raw)>0',
                            (record['delivery_id'],)).fetchone():raise PermissionError('signed Buzz reply requires exact-event recovery, never a replacement upload')
                db.execute("UPDATE buzz_output_uploads SET state='retry-approved' WHERE id=?",(request['id'],))
            receipt=digest([request,record['proof'],policy.publication,policy.connectors,policy.bindings])
            db.execute('INSERT INTO buzz_upload_owner_events VALUES(?,?,?,?,?,?,?)',
                (request['id'],request['action'],request['snapshot_sha256'],request['owner_uid'],request['note_sha256'],receipt,time.time()))
        db.execute('COMMIT')
        return {'id':request['id'],'action':request['action'],'receipt':receipt,'network_requested':False,
            'message_sent':False,'tombstones_retained':True,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
