"""Inspected private codec-cache disposal; retained proofs prevent automatic restoration."""
import hashlib
import json
import math
import re
import time

from .gateway import Conflict,digest,GatewayPolicy
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object

HASH=re.compile('[0-9a-f]{64}\\Z')


def projection(record,policy):
    value=dict(record)
    if (set(value)!={'id','proof','binding_id','binding_digest','source_sha256','sha256','metadata','stored_bytes','created_at'}
            or any(not isinstance(value[key],str) or not HASH.fullmatch(value[key]) for key in ['id','proof','binding_digest','source_sha256','sha256'])
            or not isinstance(value['binding_id'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',value['binding_id'])
            or type(value['stored_bytes']) is not int or not 0<=value['stored_bytes']<=8*1024*1024
            or type(value['created_at']) not in {int,float} or not math.isfinite(value['created_at']) or value['created_at']<=0
            or not isinstance(value['metadata'],str) or len(value['metadata'].encode())>32768):
        raise Conflict('damaged private DingTalk output-cache metadata')
    try:metadata=json.loads(value['metadata'],object_pairs_hook=_object,parse_constant=finite)
    except (ValueError,RecursionError):raise Conflict('damaged private output conversion descriptor') from None
    if (not isinstance(metadata,dict) or json.dumps(metadata,sort_keys=True,separators=(',',':'))!=value['metadata']
            or metadata.get('kind') not in {'image','file','voice'} or metadata.get('sha256')!=value['sha256']
            or type(metadata.get('size')) is not int or not 1<=metadata['size']<=8*1024*1024
            or value['stored_bytes'] not in {0,metadata['size']} or not isinstance(metadata.get('name'),str)
            or not re.fullmatch(r'(result|cover)-[0-3]\.[a-z0-9]{1,4}',metadata['name'])):
        raise Conflict('private output conversion descriptor changed')
    try:
        binding=policy.current_binding(value)
        if policy.connectors[binding['connector']]['platform']!='dingtalk':raise Conflict('cache binding changed platform')
        purge_allowed=False
    except PermissionError:purge_allowed=True
    public={'id':value['id'],'binding_id':value['binding_id'],'binding_digest':value['binding_digest'],
        'kind':metadata['kind'],'name':metadata['name'],'stored_bytes':value['stored_bytes'],'sha256':value['sha256'],
        'source_sha256':value['source_sha256'],'purged':value['stored_bytes']==0,'purge_allowed':purge_allowed,
        'created_at':value['created_at'],'proof_sha256':digest(value)}
    return {**public,'snapshot_sha256':digest(public)}


def inventory(inbox,policy):
    if not isinstance(policy,GatewayPolicy):raise PermissionError('current independent gateway policy required')
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dingtalk_output_transforms'").fetchone():
        return {'outputs':[],'stored_bytes':0,'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
    records=inbox.db.execute('SELECT id,proof,binding_id,binding_digest,source_sha256,sha256,metadata,length(data) AS stored_bytes,created_at '
        'FROM dingtalk_output_transforms ORDER BY (length(data)>0) DESC,created_at DESC LIMIT 129').fetchall()
    total=inbox.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM dingtalk_output_transforms').fetchone()[0]
    return {'outputs':[projection(record,policy) for record in records[:128]],'stored_bytes':total,
        'history_truncated':len(records)>128,'network_requested':False,'private_bytes_returned':False}


def purge(inbox,policy,request):
    if (not isinstance(policy,GatewayPolicy) or not isinstance(request,dict)
            or set(request)!={'id','snapshot_sha256','owner_uid','note_sha256','confirmed'} or request['confirmed'] is not True
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or any(not isinstance(request[key],str) or not HASH.fullmatch(request[key]) for key in ['id','snapshot_sha256','note_sha256'])):
        raise PermissionError('exact inspected output-cache disposal decision required')
    db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_transform_owner_events(
            id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
            snapshot_sha256 TEXT NOT NULL,removed_bytes INTEGER NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')
        record=db.execute('SELECT id,proof,binding_id,binding_digest,source_sha256,sha256,metadata,length(data) AS stored_bytes,created_at '
            'FROM dingtalk_output_transforms WHERE id=?',(request['id'],)).fetchone()
        if record is None:raise KeyError('unknown retained output conversion')
        current=projection(record,policy)
        if not current['purge_allowed']:raise PermissionError('withdraw or change the original grant before disposal')
        previous=db.execute('SELECT * FROM dingtalk_transform_owner_events WHERE id=?',(request['id'],)).fetchone()
        if previous is not None:
            if any(previous[key]!=request[key] for key in ['owner_uid','note_sha256','snapshot_sha256']):
                raise Conflict('output cache disposal already recorded under another inspection')
            removed=0
        else:
            if current['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('output cache changed after owner inspection')
            removed=current['stored_bytes']
            db.execute("UPDATE dingtalk_output_transforms SET data=X'' WHERE id=?",(request['id'],))
            db.execute('INSERT INTO dingtalk_transform_owner_events VALUES(?,?,?,?,?,?,?)',
                (request['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],removed,
                    digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
        return {'id':request['id'],'removed_payload_bytes':removed,'tombstones_retained':True,'network_requested':False,
            'other_copies_backups_and_WAL_erasure_not_claimed':True}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
