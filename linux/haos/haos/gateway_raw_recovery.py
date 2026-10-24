"""Offline owner decisions, executed only as the private gateway ledger UID."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import resource
import sys
import time

from .gateway import Conflict, GatewayPolicy
from .gateway_raw import NativeInbox
from .redaction import Redactor

DATABASE = Path('/var/lib/haos-gateway/native-inbox.db')
UNRESOLVED = {'pending','processing','failed','expired','revoked'}


def unresolved(inbox, after=0):
    if type(after) is not int or after < 0:
        raise ValueError('invalid ingress cursor')
    rows = inbox.db.execute("""SELECT rowid AS cursor,* FROM native_inbox
        WHERE state IN ('pending','processing','failed','expired','revoked') AND rowid>?
        ORDER BY rowid LIMIT 100""",(after,)).fetchall()
    result = []
    for row in rows:
        if not re.fullmatch('[0-9a-f]{64}',row['id']) or type(row['attempt']) is not int or not 0 <= row['attempt'] <= 8:
            raise ValueError('invalid native receipt metadata')
        pattern=(r'[1-9][0-9]{0,15}\.[0-9]{6}' if row['platform']=='slack' else
            r'[1-9][0-9]{0,19}' if row['platform']=='discord' else None)
        if pattern is None or not re.fullmatch(pattern,row['message_id']):
            raise ValueError('invalid native source metadata')
        result.append({'cursor':row['cursor'],'ingress_id':row['id'],'state':row['state'],'platform':row['platform'],
            'message_id':row['message_id'],
            'attempt':row['attempt'],'created_at':row['created_at'],
            'payload_sha256':hashlib.sha256(row['payload'].encode()).hexdigest()})
    history=[]
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='discord_history_status'").fetchone():
        for row in inbox.db.execute('SELECT binding_digest,status,updated_at FROM discord_history_status ORDER BY updated_at DESC LIMIT 512'):
            if (not re.fullmatch('[0-9a-f]{64}',row['binding_digest']) or row['status'] not in
                    {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}):
                raise ValueError('invalid history status metadata')
            history.append(dict(row))
    if inbox.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='slack_history'").fetchone():
        for row in inbox.db.execute('SELECT binding_digest,status,updated_at FROM slack_history ORDER BY updated_at DESC LIMIT 512'):
            if (not re.fullmatch('[0-9a-f]{64}',row['binding_digest']) or row['status'] not in
                    {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}):
                raise ValueError('invalid Slack history status metadata')
            history.append({**dict(row),'platform':'slack'})
    return {'ingress':result,'history':history,'next_cursor':rows[-1]['cursor'] if rows else after}


def reconcile(inbox, policy, request):
    if set(request) != {'ingress_id','attempt','state','decision','owner_uid','note_sha256'}:
        raise ValueError('invalid owner ingress decision')
    key, attempt, state, decision = (request[name] for name in ('ingress_id','attempt','state','decision'))
    if (not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key)
            or type(attempt) is not int or not 0 <= attempt <= 8 or state not in UNRESOLVED
            or decision not in {'retry','discard'} or type(request['owner_uid']) is not int
            or not 0 <= request['owner_uid'] < 2**32-1 or not isinstance(request['note_sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}',request['note_sha256'])):
        raise ValueError('invalid owner ingress evidence')
    inbox.db.execute('BEGIN IMMEDIATE')
    try:
        row = inbox.db.execute('SELECT * FROM native_inbox WHERE id=?',(key,)).fetchone()
        if row is None: raise KeyError('unknown native ingress')
        if row['state'] != state or row['attempt'] != attempt or state not in UNRESOLVED:
            raise Conflict('stale native ingress decision')
        if decision == 'retry':
            if state != 'failed':
                raise Conflict('only failed native decoding may be retried by owner')
            policy.current_binding(dict(row))
            if time.time() >= row['created_at']+86400:
                raise Conflict('expired native input must not execute as a new request')
            target = 'pending'
            inbox.db.execute("UPDATE native_inbox SET state='pending',attempt=0,next_attempt=0 WHERE id=?",(key,))
        else:
            target = 'discarded'
            # Preserve original payload, timestamps and receipt for owner review.
            inbox.db.execute("UPDATE native_inbox SET state='discarded' WHERE id=?",(key,))
        inbox.db.execute('''CREATE TABLE IF NOT EXISTS native_owner_events (
            id INTEGER PRIMARY KEY, ingress_id TEXT NOT NULL, created_at REAL NOT NULL,
            owner_uid INTEGER NOT NULL, decision TEXT NOT NULL, previous_state TEXT NOT NULL,
            previous_attempt INTEGER NOT NULL, note_sha256 TEXT NOT NULL)''')
        inbox.db.execute('INSERT INTO native_owner_events(ingress_id,created_at,owner_uid,decision,previous_state,previous_attempt,note_sha256) VALUES(?,?,?,?,?,?,?)',
            (key,time.time(),request['owner_uid'],decision,state,attempt,request['note_sha256']))
        inbox.db.execute('COMMIT')
    except BaseException:
        inbox.db.execute('ROLLBACK'); raise
    return {'ingress_id':key,'attempt':attempt,'decision':decision,'state':target}


def main():
    account = pwd.getpwnam('haos-gateway')
    if os.geteuid() == 0 or os.geteuid() != account.pw_uid:
        raise PermissionError('native ingress recovery requires the unprivileged gateway UID')
    resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(5,5)); resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    raw = sys.stdin.buffer.read(1024*1024+1)
    if len(raw) > 1024*1024: raise ValueError('owner request exceeds bound')
    data = json.loads(raw)
    if not isinstance(data,dict) or set(data) != {'action','policy','params'} or not isinstance(data['params'],dict):
        raise ValueError('invalid ingress recovery request')
    policy = GatewayPolicy(data['policy'])
    try:DATABASE.lstat()
    except FileNotFoundError:
        if data['action']=='ingress' and set(data['params'])=={'after'}:
            after=data['params']['after']
            if type(after) is not int or after<0:raise ValueError('invalid ingress cursor')
            print(json.dumps({'ingress':[],'history':[],'next_cursor':after,'native_journal_created':False}))
            return
        raise
    inbox = NativeInbox(DATABASE,Redactor())
    try:
        if data['action'] == 'ingress' and set(data['params']) == {'after'}:
            result = unresolved(inbox,data['params']['after'])
        elif data['action'] == 'reconcile-ingress':
            result = reconcile(inbox,policy,data['params'])
        else: raise ValueError('unknown ingress recovery action')
        print(json.dumps(result))
    finally: inbox.close()


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(type(error).__name__,file=sys.stderr); raise SystemExit(1)
