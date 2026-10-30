"""Read-only private A2A records shared by inspection and reviewed recovery."""
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat

def readonly(path):
    base=Path('/var/lib/haos-gateway');path=Path(path)
    if base not in path.parents:raise PermissionError('fixed private A2A journal namespace required')
    directory=path.parent
    while True:
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise PermissionError('private A2A journal ancestry required')
        if directory==base:break
        directory=directory.parent
    for candidate in [path,path.with_name(path.name+'-wal'),path.with_name(path.name+'-shm')]:
        try:info=candidate.lstat()
        except FileNotFoundError:
            if candidate==path:raise
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_nlink!=1:
            raise PermissionError('private single-link A2A journal required')
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');return db


def resources(profile,row):
    db=readonly(profile/'originals.db')
    try:
        original=db.execute('SELECT source_key,binding_digest,credential_scope,length(data) AS bytes FROM a2a_raw_events WHERE id=?',(row['raw_id'],)).fetchone()
        if original is None or any(original[key]!=row[key] for key in ['source_key','binding_digest','credential_scope']):raise ValueError('native A2A original source mapping changed')
        tables={item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        entries=db.execute('SELECT state,attempt,next_attempt FROM a2a_input_resources WHERE raw_id=?',(row['raw_id'],)).fetchall() if 'a2a_input_resources' in tables else []
        states={};attempt=0;retry_at=0
        if len(entries)>4:raise ValueError('bounded A2A resource inventory required')
        for item in entries:
            if (item['state'] not in {'prepared','retained','authentication-refused','rate-limited','transport-unavailable','source-unavailable','private-reflection'}
                    or type(item['attempt']) is not int or not 0<=item['attempt']<=8 or type(item['next_attempt']) not in {int,float}
                    or not math.isfinite(item['next_attempt']) or item['next_attempt']<0):raise ValueError('finite retained A2A resource status required')
            states[item['state']]=states.get(item['state'],0)+1;attempt=max(attempt,item['attempt']);retry_at=max(retry_at,item['next_attempt'])
        return {'original_retained':original['bytes']>0,'resources':states,'resource_attempts':attempt,'resource_retry_at':retry_at}
    finally:db.close()


def task_summary(profile,peer,db,row,credential_scope,policy):
    from .gateway import digest
    if (not isinstance(row['record'],str) or len(row['record'].encode())>65536
            or row['record_sha256']!=digest([row['source_key'],row['raw_id'],row['binding_digest'],row['credential_scope'],row['record']])):
        raise ValueError('damaged retained native A2A source proof')
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    record=json.loads(row['record'],object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(record,dict) or record.get('task_id')!=row['task_id'] or record.get('peer')!=row['peer'] or record.get('context_id')!=row['context_id']
            or json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)!=row['record']
            or row['admitted_receipt'] not in {'',row['source_key']}
            or not re.fullmatch('task-[0-9a-f]{16}',row['task_id'])
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',row['peer'])
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}',row['context_id'])):
        raise ValueError('damaged retained native A2A task identity')
    states={'TASK_STATE_SUBMITTED','TASK_STATE_WORKING','TASK_STATE_INPUT_REQUIRED','TASK_STATE_COMPLETED','TASK_STATE_FAILED','TASK_STATE_CANCELED','TASK_STATE_REJECTED'}
    if record.get('state') not in states:raise ValueError('finite retained A2A task state required')
    tables={item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    callbacks=dict(db.execute('SELECT state,COUNT(*) FROM a2a_callback_deliveries WHERE task_id=? GROUP BY state',(row['task_id'],)).fetchall()) if 'a2a_callback_deliveries' in tables else {}
    uncertain=db.execute("SELECT COUNT(*) FROM a2a_task_transitions WHERE task_id=? AND state!='committed'",(row['task_id'],)).fetchone()[0]
    controls=db.execute("SELECT COUNT(*) FROM a2a_control_intents WHERE task_id=? AND state!='committed'",(row['task_id'],)).fetchone()[0] if 'a2a_control_intents' in tables else 0
    results=db.execute("SELECT COUNT(*) FROM a2a_result_epochs WHERE task_id=? AND state!='committed'",(row['task_id'],)).fetchone()[0] if 'a2a_result_epochs' in tables else 0
    active=False
    if policy is not None and credential_scope==row['credential_scope']:
        try:policy.current_binding(dict(row));active=True
        except PermissionError:pass
    summary={'profile':profile.name,'peer_journal':peer.name,'task_id':row['task_id'],'peer':row['peer'],'context':row['context_id'],
        'native_state':record['state'],'parent_admitted':row['admitted_receipt']==row['source_key'],'original_id':row['raw_id'],
        'source_key':row['source_key'],'binding_id':row['binding_id'],'binding_digest':row['binding_digest'],
        'credential_scope':row['credential_scope'],'current_account':credential_scope==row['credential_scope'],'current_grant':active,
        'uncertain_transitions':uncertain,'uncertain_controls':controls,'uncertain_results':results,'callbacks':callbacks,**resources(profile,row)}
    summary['snapshot_sha256']=digest(summary)
    return summary
