"""Explicit owner recovery under the private UID; no transport or mission calls."""
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .gateway import digest

ACTIONS=frozenset({'retry-source-auth','purge-source-inputs','purge-task-outputs'})
TERMINAL=frozenset({'TASK_STATE_COMPLETED','TASK_STATE_FAILED','TASK_STATE_CANCELED','TASK_STATE_REJECTED'})


def parameters(value):
    patterns={'profile':'a2a-[0-9a-f]{64}','peer_journal':'peer-[0-9a-f]{64}',
        'task_id':'task-[0-9a-f]{16}','snapshot_sha256':'[0-9a-f]{64}','note_sha256':'[0-9a-f]{64}'}
    if not isinstance(value,dict) or set(value)!=set(patterns) or any(not isinstance(value[key],str) or not re.fullmatch(pattern,value[key]) for key,pattern in patterns.items()):
        raise ValueError('exact inspected A2A source and owner review receipt required')
    return value


def recover(action,params,current,connector,value,publication,policy,redactor):
    if action not in ACTIONS:raise ValueError('closed A2A owner recovery action required')
    parameters(params);current()
    from .a2a_owner_records import readonly,task_summary
    from .gateway_matrix_profile import acquire_lease
    profile=Path('/var/lib/haos-gateway/profiles')/params['profile'];peer=profile/params['peer_journal']
    # Validate all ancestry before creating/acquiring even a profile lock.
    checked=readonly(peer/'tasks.db');checked.close()
    lease=acquire_lease(profile);db=None;taskdb=None
    try:
        taskdb=readonly(peer/'tasks.db')
        row=taskdb.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(params['task_id'],)).fetchone()
        if row is None:raise PermissionError('unknown inspected A2A task')
        path=profile/'originals.db' if action!='purge-task-outputs' else peer/'tasks.db'
        checked=readonly(path);checked.close()
        db=sqlite3.connect('file:'+str(path)+'?mode=rw',uri=True,isolation_level=None);db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        db.execute('''CREATE TABLE IF NOT EXISTS a2a_owner_recovery(
            id TEXT PRIMARY KEY,request TEXT NOT NULL,result TEXT NOT NULL,created_at REAL NOT NULL)''')
        request=json.dumps([action,params,publication],sort_keys=True,separators=(',',':'));identity=digest(request)
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT request,result FROM a2a_owner_recovery WHERE id=?',(identity,)).fetchone()
        if prior is not None:
            if prior['request']!=request:raise ValueError('A2A recovery identity changed')
            result=json.loads(prior['result'])
            from .a2a_owner_process import response
            response(result,action);current();db.execute('COMMIT');return result
        summary=task_summary(profile,peer,taskdb,row,digest([connector,value]),policy)
        if summary['snapshot_sha256']!=params['snapshot_sha256']:raise PermissionError('A2A task changed since owner inspection; inspect again')
        if summary['uncertain_transitions'] or summary['uncertain_controls'] or summary['uncertain_results']:
            raise PermissionError('uncertain A2A operation requires source reconciliation before maintenance')
        affected=0;removed=0
        if action=='retry-source-auth':
            if (not summary['current_account'] or not summary['current_grant'] or summary['parent_admitted']
                    or summary['native_state']!='TASK_STATE_WORKING' or not summary['original_retained']):
                raise PermissionError('only a current unadmitted working A2A source can retry refused resource authentication')
            from .gateway_a2a_cache import RawEvents
            from .gateway_a2a_resources import Resources
            # Use the actual immutable source validator, without constructing a
            # transport/cache or creating any new ingress receipt.
            originals=object.__new__(RawEvents);originals.redactor=redactor
            raw=db.execute('SELECT * FROM a2a_raw_events WHERE id=?',(row['raw_id'],)).fetchone()
            if raw is None:raise PermissionError('retained original required for authentication retry')
            proof=originals.validate(raw,policy,connector,value,row['peer'])
            resource=object.__new__(Resources);resource.inbox=type('PrivateRedactor',(),{'redactor':redactor})()
            specs={item['index']:item for item in proof.get('resources',[])}
            for entry in db.execute("SELECT * FROM a2a_input_resources WHERE raw_id=? AND state='authentication-refused'",(row['raw_id'],)).fetchall():
                spec=specs.get(entry['part_index'])
                if spec is None or spec['mode']!='https':raise PermissionError('exact retained HTTPS resource required')
                resource.check(proof,spec,entry)
                db.execute("UPDATE a2a_input_resources SET state='prepared',attempt=0,next_attempt=0,updated_at=? WHERE raw_id=? AND part_index=?",(time.time(),row['raw_id'],entry['part_index']));affected+=1
            if not affected:raise PermissionError('no authentication-refused A2A resource remains')
        else:
            if summary['current_grant'] or summary['native_state'] not in TERMINAL:
                raise PermissionError('withdraw the exact grant and reconcile a terminal task before removing retained bytes')
            if action=='purge-source-inputs':
                original=db.execute('SELECT length(data) FROM a2a_raw_events WHERE id=?',(row['raw_id'],)).fetchone()
                removed=original[0];affected=int(removed>0)
                db.execute("UPDATE a2a_raw_events SET data=X'' WHERE id=?",(row['raw_id'],))
                tables={item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'a2a_input_resources' in tables:
                    count,size=db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM a2a_input_resources WHERE raw_id=? AND length(data)>0',(row['raw_id'],)).fetchone()
                    removed+=size;affected+=count
                    db.execute("UPDATE a2a_input_resources SET data=NULL WHERE raw_id=? AND length(data)>0",(row['raw_id'],))
            else:
                tables={item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'a2a_output_artifacts' in tables:
                    affected,removed=db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM a2a_output_artifacts WHERE task_id=? AND length(data)>0',(row['task_id'],)).fetchone()
                    db.execute("UPDATE a2a_output_artifacts SET data=X'' WHERE task_id=? AND length(data)>0",(row['task_id'],))
        result={'action':action,'receipt':identity,'affected':affected,'removed_bytes':removed,'message_sent':False,'mission_created':False}
        from .a2a_owner_process import response
        response(result,action)
        if db.execute('SELECT COUNT(*) FROM a2a_owner_recovery').fetchone()[0]>=65536:raise PermissionError('bounded A2A maintenance history full')
        db.execute('INSERT INTO a2a_owner_recovery VALUES(?,?,?,?)',(identity,request,json.dumps(result,sort_keys=True,separators=(',',':')),time.time()))
        current();db.execute('COMMIT');return result
    finally:
        if db is not None:db.close()
        if taskdb is not None:taskdb.close()
        os.close(lease)
