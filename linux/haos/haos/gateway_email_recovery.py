"""Offline inspected email recovery; no messages, credentials or network requests."""
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time

from .gateway import GatewayPolicy,Conflict,digest
from .gateway_email_imap import uid_number

HASH=re.compile('[0-9a-f]{64}\\Z')
PROFILES=Path('/var/lib/haos-gateway/profiles')


def private_directory(path):
    own=path.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077:
        raise PermissionError('private gateway-owned email profile directory required')


def source_cache(profile,*,parent=PROFILES):
    from .gateway_email_cache import RawCache
    from .redaction import Redactor
    if not isinstance(profile,str) or not re.fullmatch('email-[0-9a-f]{64}',profile):
        raise ValueError('exact opaque email profile required; no caller path')
    parent=Path(parent);private_directory(parent);directory=parent/profile;private_directory(directory)
    path=directory/'raw.db';own=path.lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_nlink!=1 or own.st_mode&0o077:
        raise PermissionError('existing private email raw ledger required')
    return RawCache(path,Redactor())


def sources(inbox,policy,profile=None,*,parent=PROFILES):
    if profile is not None:
        cache=source_cache(profile,parent=parent)
        try:return {'profile':profile,**cache.owner_inventory(inbox,policy),'network_requested':False}
        finally:cache.close()
    parent=Path(parent)
    try:private_directory(parent)
    except FileNotFoundError:return {'profiles':[],'network_requested':False,'history_truncated':False}
    result=[];truncated=False
    with os.scandir(parent) as entries:
        for count,entry in enumerate(entries):
            if count>=1024:truncated=True;break
            if not re.fullmatch('email-[0-9a-f]{64}',entry.name):continue
            if len(result)>=128:truncated=True;break
            try:cache=source_cache(entry.name,parent=parent)
            except FileNotFoundError:
                result.append({'profile':entry.name,'connector':None,'records':0,'active':0,'stored_bytes':0,'status':'incomplete-profile'})
                continue
            try:
                values=cache.db.execute('SELECT connector,COUNT(*) AS total,SUM(length(data)>0) AS active,COALESCE(SUM(length(data)),0) AS stored_bytes FROM email_raw_messages GROUP BY connector LIMIT 16').fetchall()
                if not values:result.append({'profile':entry.name,'connector':None,'records':0,'active':0,'stored_bytes':0})
                else:
                    if len(values)!=1:raise Conflict('private email source profile spans multiple connectors')
                    row=values[0]
                    result.append({'profile':entry.name,'connector':row['connector'],'records':row['total'],
                        'active':row['active'],'stored_bytes':row['stored_bytes']})
            finally:cache.close()
    return {'profiles':sorted(result,key=lambda row:row['profile']),'network_requested':False,'history_truncated':truncated}


def purge_source(inbox,policy,request,*,parent=PROFILES):
    if not isinstance(request,dict) or 'profile' not in request:raise ValueError('exact inspected email source profile required')
    cache=source_cache(request['profile'],parent=parent)
    try:return {'profile':request['profile'],**cache.owner_purge(inbox,policy,{key:value for key,value in request.items() if key!='profile'})}
    finally:cache.close()


def decision(request,fields):
    if (not isinstance(request,dict) or set(request)!=set(fields)|{'owner_uid','note_sha256','confirmed'}
            or request['confirmed'] is not True or type(request['owner_uid']) is not int
            or not 0<=request['owner_uid']<2**32-1 or not isinstance(request['note_sha256'],str)
            or not HASH.fullmatch(request['note_sha256'])):
        raise PermissionError('exact inspected owner email decision required')


def mailbox(row):
    value=dict(row)
    fields={'identity','connector','scope','uid_validity','uid_next','cursor','observed_validity','observed_next','status','updated_at'}
    if (set(value)!=fields or not isinstance(value['identity'],str) or not HASH.fullmatch(value['identity'])
            or not isinstance(value['connector'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',value['connector'])
            or not isinstance(value['scope'],str) or not re.fullmatch('mailbox:[0-9a-f]{64}',value['scope'])
            or type(value['cursor']) is not int or not 0<=value['cursor']<2**32
            or value['status'] not in {'ready','uid-validity-changed','uid-next-regressed'}
            or type(value['updated_at']) not in {int,float} or not math.isfinite(value['updated_at']) or value['updated_at']<=0):
        raise ValueError('exact bounded mailbox inventory required')
    for key in ['uid_validity','uid_next','observed_validity','observed_next']:uid_number(value[key])
    return value


def mailboxes(inbox):
    db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='email_mailboxes'").fetchone():return []
    result=[]
    for row in db.execute('SELECT * FROM email_mailboxes ORDER BY updated_at DESC LIMIT 128'):
        value=mailbox(row)
        active=db.execute('SELECT identity FROM email_mailbox_current WHERE connector=? AND scope=?',
            (value['connector'],value['scope'])).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='email_mailbox_current'").fetchone() else None
        result.append({**value,'snapshot_sha256':digest(value),'active':active is None or active['identity']==value['identity']})
    return result


def outgoing(inbox):
    db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='email_delivery_intents'").fetchone():return []
    result=[]
    for row in db.execute('SELECT delivery_id,attempt,fingerprint,state,receipt,updated_at FROM email_delivery_intents ORDER BY updated_at DESC LIMIT 64'):
        if (any(not isinstance(row[key],str) or not HASH.fullmatch(row[key]) for key in ('delivery_id','fingerprint'))
                or type(row['attempt']) is not int or not 1<=row['attempt']<=5
                or row['state'] not in {'writing','confirmed','uncertain','rejected','owner-retry-approved'}
                or not isinstance(row['receipt'],str)
                or row['state']=='confirmed' and not re.fullmatch('smtp_accept_[0-9a-f]{64}',row['receipt'])
                or row['state']!='confirmed' and row['receipt']
                or type(row['updated_at']) not in {int,float} or not math.isfinite(row['updated_at']) or row['updated_at']<0):
            raise ValueError('bounded private SMTP acceptance metadata required')
        result.append({'platform':'email','delivery_id':row['delivery_id'],'attempt':row['attempt'],'state':row['state'],
            'server_acceptance_receipt':row['receipt'] or None,'updated_at':row['updated_at'],
            'recipient_receipt_verified':False,'snapshot_sha256':digest(dict(row))})
    return result


def approve_retry(inbox,policy,request):
    decision(request,{'connector','delivery_id','attempt','snapshot_sha256','confirmed_not_delivered'})
    if (not isinstance(policy,GatewayPolicy) or not isinstance(request['connector'],str)
            or policy.connectors.get(request['connector'],{}).get('platform')!='email'
            or request['confirmed_not_delivered'] is not True
            or type(request['attempt']) is not int or not 1<=request['attempt']<5
            or any(not isinstance(request[key],str) or not HASH.fullmatch(request[key]) for key in ('delivery_id','snapshot_sha256'))):
        raise PermissionError('current inspected email attempt and explicit non-delivery confirmation required')
    db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS email_delivery_owner_events(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,previous_state TEXT NOT NULL,
            policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(delivery_id,attempt))''')
        old=db.execute('SELECT * FROM email_delivery_owner_events WHERE delivery_id=? AND attempt=?',
            (request['delivery_id'],request['attempt'])).fetchone()
        if old is not None:
            if any(old[key]!=request[key] for key in ('connector','owner_uid','note_sha256','snapshot_sha256')):
                raise Conflict('email retry decision was already recorded under another inspection')
        else:
            row=db.execute('SELECT delivery_id,attempt,fingerprint,state,receipt,updated_at FROM email_delivery_intents WHERE delivery_id=? AND attempt=?',
                (request['delivery_id'],request['attempt'])).fetchone()
            if row is None:raise KeyError('unknown private SMTP write intent')
            if digest(dict(row))!=request['snapshot_sha256']:raise Conflict('SMTP write state changed after owner inspection')
            if row['state'] not in {'writing','uncertain','rejected'} or row['receipt']:
                raise PermissionError('confirmed SMTP acceptance cannot be released for another write')
            db.execute("UPDATE email_delivery_intents SET state='owner-retry-approved',updated_at=? WHERE delivery_id=? AND attempt=?",
                (time.time(),request['delivery_id'],request['attempt']))
            db.execute('INSERT INTO email_delivery_owner_events VALUES(?,?,?,?,?,?,?,?,?)',
                (request['delivery_id'],request['attempt'],request['connector'],request['owner_uid'],request['note_sha256'],
                 request['snapshot_sha256'],row['state'],digest([policy.publication,policy.connectors,policy.bindings]),time.time()))
        db.execute('COMMIT')
    except BaseException:db.execute('ROLLBACK');raise
    return {'delivery_id':request['delivery_id'],'attempt':request['attempt'],'private_retry_approved':True,
        'controller_reconciliation_still_required':True,'network_requested':False,'recipient_receipt_verified':False}


def transport(inbox):
    db=inbox.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='email_profile_status'").fetchone():return []
    from .gateway_email_profile import STATES
    result=[]
    for row in db.execute('SELECT connector,status,updated_at,next_attempt FROM email_profile_status ORDER BY updated_at DESC LIMIT 64'):
        if (not isinstance(row['connector'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])
                or row['status'] not in STATES or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<0
                    for key in ('updated_at','next_attempt'))):raise ValueError('bounded private email transport metadata required')
        result.append({**dict(row),'platform':'email','live_account_or_external_delivery_verified':False})
    return result


def recover_mailbox(inbox,policy,request):
    """Append a fresh local scan epoch, preserving every old cursor and receipt."""
    decision(request,{'identity','snapshot_sha256'})
    if (not isinstance(policy,GatewayPolicy) or any(not isinstance(request[key],str) or not HASH.fullmatch(request[key])
            for key in ('identity','snapshot_sha256'))):raise ValueError('exact inspected mailbox snapshot required')
    db=inbox.db;db.execute('BEGIN IMMEDIATE')
    try:
        found=db.execute('SELECT * FROM email_mailboxes WHERE identity=?',(request['identity'],)).fetchone()
        if found is None:raise KeyError('unknown private mailbox scan')
        row=mailbox(found)
        if digest(row)!=request['snapshot_sha256']:raise Conflict('mailbox observations changed after owner inspection')
        if row['status']=='ready':raise Conflict('only a fenced mailbox scan needs owner recovery')
        db.execute('''CREATE TABLE IF NOT EXISTS email_mailbox_current(
            connector TEXT NOT NULL,scope TEXT NOT NULL,identity TEXT NOT NULL UNIQUE,PRIMARY KEY(connector,scope))''')
        if row['identity']==digest([row['connector'],row['scope']]):
            # Known preceding schema had exactly this one deterministic epoch.
            # Bootstrap its pointer without rewriting an old cursor or receipt.
            db.execute('INSERT OR IGNORE INTO email_mailbox_current VALUES(?,?,?)',(row['connector'],row['scope'],row['identity']))
        pointer=db.execute('SELECT identity FROM email_mailbox_current WHERE connector=? AND scope=?',(row['connector'],row['scope'])).fetchone()
        if pointer is None or pointer['identity']!=row['identity']:raise Conflict('mailbox scan has already been replaced')
        if (policy.connectors.get(row['connector'],{}).get('platform')!='email'
                or not any(binding['connector']==row['connector'] and binding['scope']==row['scope'] for binding in policy.bindings.values())):
            raise PermissionError('current explicit email mailbox grants required; old scopes cannot move')
        if db.execute('SELECT COUNT(*) FROM email_mailboxes').fetchone()[0]>=128:raise Conflict('mailbox scan history capacity reached')
        identity=digest([row['connector'],row['scope'],row['identity'],secrets.token_hex(32)])
        now=time.time()
        db.execute('INSERT INTO email_mailboxes VALUES(?,?,?,?,?,?,?,?,?,?)',
            (identity,row['connector'],row['scope'],row['observed_validity'],row['observed_next'],0,
             row['observed_validity'],row['observed_next'],'ready',now))
        db.execute('UPDATE email_mailbox_current SET identity=? WHERE connector=? AND scope=?',
            (identity,row['connector'],row['scope']))
        db.execute('''CREATE TABLE IF NOT EXISTS email_mailbox_owner_events(
            previous_identity TEXT PRIMARY KEY,identity TEXT NOT NULL UNIQUE,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,previous_sha256 TEXT NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')
        db.execute('INSERT INTO email_mailbox_owner_events VALUES(?,?,?,?,?,?,?)',
            (row['identity'],identity,request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],
             digest([policy.publication,policy.connectors,policy.bindings]),now))
        db.execute('COMMIT')
    except BaseException:db.execute('ROLLBACK');raise
    return {'previous_identity':row['identity'],'identity':identity,'cursor':0,'old_receipts_preserved':True,
        'grants_changed':False,'network_requested':False,'next_connection_must_verify_observed_state':True}
