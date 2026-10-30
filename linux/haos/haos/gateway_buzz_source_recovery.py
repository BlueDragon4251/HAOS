"""Opaque source/history inspection and audited disposal or new-grant catch-up."""
import hashlib
import json
import math
import re
import time

from .gateway import Conflict,digest
from .gateway_buzz import HEX,channel
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object


def profile_name(value):
    if not isinstance(value,str) or not re.fullmatch('buzz-[0-9a-f]{64}',value):raise ValueError('opaque exact Buzz profile required')
    return value


def source_view(record,policy,profile):
    profile_name(profile)
    row=dict(record);data=row['data']
    if (any(not isinstance(row[key],str) or not HEX.fullmatch(row[key]) for key in ['id','source_key','event_id','binding_digest','credential_scope','sha256'])
            or not isinstance(row['binding_id'],str) or not 1<=len(row['binding_id'])<=128
            or not isinstance(row['connector'],str) or not 1<=len(row['connector'])<=128
            or not isinstance(data,bytes) or len(data)>1048576
            or not isinstance(row['metadata'],str) or len(row['metadata'].encode())>65536
            or row['admitted_receipt'] not in {'',row['source_key']}
            or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<=0 for key in ['received_at','created_at'])):
        raise Conflict('damaged Buzz original recovery mapping')
    try:binding=policy.current_binding(row);current=binding['connector']==row['connector']
    except PermissionError:current=False
    actual=hashlib.sha256(data).hexdigest() if data else None
    public={key:row[key] for key in ['id','connector','event_id','binding_id','binding_digest','received_at','admitted_receipt']}
    public.update(profile=profile,source_sha256=row['sha256'],stored_bytes=len(data),purged=not bool(data),current_grant=current,
        purge_allowed=not current,original_bytes_match_receipt=bool(data) and actual==row['sha256'],
        signature_reverified=False,metadata_sha256=digest(row['metadata']),actual_sha256=actual,
        state='purged' if not data else 'retained' if actual==row['sha256'] else 'damaged')
    return {**public,'snapshot_sha256':digest(public)}


def sources(store,policy,profile):
    records=store.db.execute('SELECT * FROM buzz_raw_events ORDER BY (length(data)>0) DESC,created_at DESC LIMIT 129').fetchall()
    return {'profile':profile,'sources':[source_view(row,policy,profile) for row in records[:128]],'history_truncated':len(records)>128,
        'network_requested':False,'private_bytes_returned':False}


def decision(request,fields):
    if (not isinstance(request,dict) or set(request)!=fields|{'owner_uid','note_sha256','confirmed'}
            or request['confirmed'] is not True or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or any(not isinstance(request.get(key),str) or not HEX.fullmatch(request[key]) for key in ['snapshot_sha256','note_sha256'])):
        raise PermissionError('exact inspected Buzz source/history decision required')


def purge(store,policy,request):
    decision(request,{'profile','id','snapshot_sha256'});profile_name(request['profile'])
    if not isinstance(request['id'],str) or not HEX.fullmatch(request['id']):raise ValueError('exact Buzz original receipt required')
    db=store.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS buzz_source_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')
        row=db.execute('SELECT * FROM buzz_raw_events WHERE id=?',(request['id'],)).fetchone()
        if row is None:raise KeyError('unknown retained Buzz original')
        view=source_view(row,policy,request['profile'])
        if not view['purge_allowed']:raise PermissionError('withdraw or change the original Buzz grant before disposal')
        previous=db.execute('SELECT * FROM buzz_source_owner_events WHERE id=?',(request['id'],)).fetchone()
        if previous is not None:
            if any(previous[key]!=request[key] for key in ['owner_uid','note_sha256','snapshot_sha256']):raise Conflict('Buzz original disposal belongs to another inspection')
            receipt=previous['receipt']
        else:
            if view['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('Buzz original changed after inspection')
            receipt=digest([request,view,policy.publication])
            # The admission proof contains message text and resource URLs too.
            # Compact it to its hash; keeping the original JSON would retain
            # the very source payload the owner explicitly disposed of.
            compact=json.dumps({'purged':True,'proof_sha256':digest(row['metadata'])},separators=(',',':'))
            db.execute("UPDATE buzz_raw_events SET data=x'',metadata=? WHERE id=?",(compact,request['id']))
            db.execute('INSERT INTO buzz_source_owner_events VALUES(?,?,?,?,?,?)',
                (request['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],receipt,time.time()))
        db.execute('COMMIT')
        return {'id':request['id'],'receipt':receipt,'network_requested':False,'message_sent':False,'tombstones_retained':True,
            'other_copies_backups_and_WAL_erasure_not_claimed':True}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise


def history_view(record,reader,profile):
    profile_name(profile)
    row=dict(record);channel(row['channel'])
    if (not isinstance(row['pin'],str) or not HEX.fullmatch(row['pin'])
            or any(type(row[key]) is not int or not 0<row[key]<2**53 for key in ['floor_ts','ceiling_ts','before_ts'])
            or not row['floor_ts']<=row['before_ts']<=row['ceiling_ts'] or type(row['revision']) is not int or row['revision']<0
            or row['complete'] not in {0,1} or not isinstance(row['before_id'],str) or row['before_id'] and not HEX.fullmatch(row['before_id'])
            or not isinstance(row['page'],str) or len(row['page'].encode())>16384):raise Conflict('damaged Buzz history checkpoint')
    page=json.loads(row['page'],object_pairs_hook=_object,parse_constant=finite)
    if not isinstance(page,list) or len(page)>50 or any(not isinstance(part,list) or len(part)!=2
            or not isinstance(part[0],str) or not HEX.fullmatch(part[0]) or type(part[1]) is not bool for part in page):
        raise Conflict('damaged Buzz history custody receipt')
    from .gateway_buzz_history import History
    # The grant method requires no network and does not construct a CLI client.
    from types import SimpleNamespace
    try:
        if profile!='buzz-'+digest([reader.value['relay_url'],reader.value['public_key']]):raise PermissionError('historical account')
        current_pin,earliest=History.grant(SimpleNamespace(reader=reader),row['channel'])
    except PermissionError:current_pin=None;earliest=None
    public={key:row[key] for key in ['channel','pin','floor_ts','ceiling_ts','before_ts','before_id','revision','complete']}
    public.update(profile=profile,current_pin=current_pin,current_earliest=earliest,page_sha256=digest(page),
        reset_allowed=current_pin is not None and row['pin']!=current_pin,
        state='current' if row['pin']==current_pin else 'grant-changed' if current_pin is not None else 'unpaired')
    return {**public,'snapshot_sha256':digest(public)}


def history(store,reader,profile):
    chosen=reader.value['channels'];placeholders=','.join('?' for _ in chosen)
    current=store.db.execute('SELECT * FROM buzz_history WHERE channel IN ('+placeholders+') ORDER BY channel',chosen).fetchall()
    older=store.db.execute('SELECT * FROM buzz_history WHERE channel NOT IN ('+placeholders+') ORDER BY channel LIMIT ?',
        (*chosen,129-len(current))).fetchall();rows=[*current,*older]
    return {'profile':profile,'history':[history_view(row,reader,profile) for row in rows[:128]],'history_truncated':len(rows)>128,
        'network_requested':False,'private_bytes_returned':False}


def reset_history(store,reader,request):
    decision(request,{'profile','channel','snapshot_sha256'});channel(request['channel']);profile_name(request['profile']);db=store.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS buzz_history_owner_events(channel TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
            owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,previous_checkpoint TEXT NOT NULL,created_at REAL NOT NULL,
            PRIMARY KEY(channel,snapshot_sha256))''')
        previous=db.execute('SELECT * FROM buzz_history_owner_events WHERE channel=? AND snapshot_sha256=?',
            (request['channel'],request['snapshot_sha256'])).fetchone()
        row=db.execute('SELECT * FROM buzz_history WHERE channel=?',(request['channel'],)).fetchone()
        if row is None:raise KeyError('unknown retained Buzz channel checkpoint')
        view=history_view(row,reader,request['profile'])
        if previous is not None:
            if any(previous[key]!=request[key] for key in ['owner_uid','note_sha256']):raise Conflict('Buzz history decision belongs to another inspection')
            receipt=previous['receipt']
        else:
            if view['snapshot_sha256']!=request['snapshot_sha256'] or not view['reset_allowed']:
                raise PermissionError('only an inspected checkpoint for a changed exact Buzz grant may restart')
            earliest=view['current_earliest'];ceiling=max(earliest,int(time.time()))
            db.execute("UPDATE buzz_history SET pin=?,floor_ts=?,ceiling_ts=?,before_ts=?,before_id='',revision=revision+1,complete=0,page='[]' WHERE channel=?",
                (view['current_pin'],earliest,ceiling,ceiling,request['channel']))
            receipt=digest([request,view]);db.execute('INSERT INTO buzz_history_owner_events VALUES(?,?,?,?,?,?,?)',
                (request['channel'],request['snapshot_sha256'],request['owner_uid'],request['note_sha256'],receipt,
                    json.dumps(dict(row),sort_keys=True,separators=(',',':')),time.time()))
        db.execute('COMMIT');return {'channel':request['channel'],'receipt':receipt,'network_requested':False,'message_sent':False,
            'originals_and_previous_checkpoint_receipt_retained':True}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
