"""Offline source-byte disposal after grant withdrawal; immutable proofs survive."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from .gateway import Conflict,digest
from .gateway_dingtalk_cache import metadata
from .gateway_raw import NativeInbox
from .redaction import Redactor

PROFILES=Path('/var/lib/haos-gateway/profiles')
STORES={'original':('originals.db','dingtalk_raw_events','data')}
HASH=re.compile('[0-9a-f]{64}\\Z')


def directory(path):
    own=path.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077:
        raise PermissionError('existing private gateway-owned source directory required')


def open_store(profile,kind,*,parent=PROFILES):
    if (not isinstance(profile,str) or not re.fullmatch('dingtalk-[0-9a-f]{64}',profile)
            or not isinstance(kind,str) or kind not in STORES):raise ValueError('exact opaque DingTalk profile and source kind required')
    parent=Path(parent);directory(parent);folder=parent/profile;directory(folder)
    path=folder/STORES[kind][0];own=path.lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_nlink!=1 or own.st_mode&0o077:
        raise PermissionError('existing private source ledger required')
    result=NativeInbox(path,Redactor())
    if not result.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(STORES[kind][1],)).fetchone():
        result.close();raise Conflict('private DingTalk source table unavailable')
    return result


def projection(record,kind,policy):
    value=dict(record);payload=bytes(value[STORES[kind][2]])
    approval=metadata(value['metadata'])['approval'];connector=value['connector'];checksum=value['sha256']
    if (not isinstance(connector,str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',connector)
            or any(not isinstance(value.get(k),str) or not HASH.fullmatch(value[k]) for k in ['source_key','credential_scope','semantic_sha256'])):
        raise Conflict('damaged private DingTalk source identity')
    if any(value[k]!=approval.get(k) for k in ['binding_id','binding_digest','credential_scope']):raise Conflict('original source approval changed')
    proof=digest([value[k] for k in ['source_key','connector','binding_id','binding_digest','credential_scope','semantic_sha256','metadata']])
    if (not isinstance(approval,dict) or any(not isinstance(approval.get(k),str) for k in ['binding_id','binding_digest'])
            or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',approval['binding_id'])
            or not HASH.fullmatch(approval['binding_digest']) or not HASH.fullmatch(value['id']) or not HASH.fullmatch(checksum)):
        raise Conflict('exact private DingTalk source proof required')
    try:
        binding=policy.current_binding(approval);revoked=False
        if connector!=binding['connector']:raise Conflict('retained source connector differs from current grant')
    except PermissionError:
        revoked=True
    result={'id':value['id'],'kind':kind,'connector':connector,'binding_id':approval['binding_id'],
        'binding_digest':approval['binding_digest'],'stored_bytes':len(payload),'sha256':checksum,
        'integrity_verified':not payload or hashlib.sha256(payload).hexdigest()==checksum,'purge_allowed':revoked,
        'purged':not payload,'proof_sha256':proof}
    return {**result,'snapshot_sha256':digest(result)}


def sources(policy,profile=None,kind=None,*,parent=PROFILES):
    if profile is None:
        if kind is not None:raise ValueError('source kind requires an exact profile')
        parent=Path(parent)
        try:directory(parent)
        except FileNotFoundError:return {'profiles':[],'history_truncated':False,'network_requested':False}
        result=[];truncated=False
        with os.scandir(parent) as entries:
            for count,entry in enumerate(entries):
                if count>=1024:truncated=True;break
                if not re.fullmatch('dingtalk-[0-9a-f]{64}',entry.name):continue
                if len(result)>=128:truncated=True;break
                directory(parent/entry.name);kinds={}
                for selected,(_,table,column) in STORES.items():
                    try:store=open_store(entry.name,selected,parent=parent)
                    except FileNotFoundError:continue
                    try:
                        total,active,size=store.db.execute(f'SELECT COUNT(*),COALESCE(SUM(length({column})>0),0),COALESCE(SUM(length({column})),0) FROM {table}').fetchone()
                        kinds[selected]={'records':total,'active':active,'stored_bytes':size}
                    finally:store.close()
                result.append({'profile':entry.name,'kinds':kinds})
        return {'profiles':sorted(result,key=lambda row:row['profile']),'history_truncated':truncated,'network_requested':False}
    store=open_store(profile,kind,parent=parent)
    try:
        table,column=STORES[kind][1:]
        rows=store.db.execute(f'SELECT * FROM {table} ORDER BY (length({column})>0) DESC,created_at DESC LIMIT 129').fetchall()
        return {'profile':profile,'kind':kind,'sources':[projection(row,kind,policy) for row in rows[:128]],
            'history_truncated':len(rows)>128,'network_requested':False,'private_bytes_returned':False}
    finally:store.close()


def purge(policy,request,*,parent=PROFILES):
    if (not isinstance(request,dict) or set(request)!={'profile','kind','id','snapshot_sha256','owner_uid','note_sha256','confirmed'}
            or request['confirmed'] is not True or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or any(not isinstance(request[k],str) or not HASH.fullmatch(request[k]) for k in ['id','snapshot_sha256','note_sha256'])):
        raise PermissionError('exact inspected DingTalk source disposal decision required')
    store=open_store(request['profile'],request['kind'],parent=parent);db=store.db
    table,column=STORES[request['kind']][1:]
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_source_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,removed_bytes INTEGER NOT NULL,purged_at REAL NOT NULL)''')
        record=db.execute(f'SELECT * FROM {table} WHERE id=?',(request['id'],)).fetchone()
        if record is None:raise KeyError('unknown retained DingTalk source')
        current=projection(record,request['kind'],policy)
        if not current['purge_allowed']:raise PermissionError('withdraw or change the source grant before disposal')
        previous=db.execute('SELECT * FROM dingtalk_source_owner_events WHERE id=?',(request['id'],)).fetchone()
        if previous is not None:
            if any(previous[k]!=request[k] for k in ['owner_uid','note_sha256','snapshot_sha256']):raise Conflict('DingTalk source disposal already recorded under another inspection')
            size=0
        else:
            if current['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('DingTalk source changed after inspection')
            size=current['stored_bytes']
            db.execute(f"UPDATE {table} SET {column}=X'' WHERE id=?",(request['id'],))
            db.execute('INSERT INTO dingtalk_source_owner_events VALUES(?,?,?,?,?,?)',
                (request['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],size,time.time()))
        db.execute('COMMIT')
        return {'id':request['id'],'kind':request['kind'],'removed_payload_bytes':size,'tombstones_retained':True,
            'network_requested':False,'other_source_stores_controller_agent_copies_and_backups_unchanged':True}
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    finally:store.close()
