"""Private mailbox cursor fences and atomic durable capture/refusal receipts."""
import json
import math
import re
import time

from .gateway import Conflict,digest
from .gateway_email_imap import uid_number

_HASH=re.compile(r'[0-9a-f]{64}\Z')
_REASONS=frozenset({'unapproved-sender','unapproved-thread','pre-grant','self-or-automated','unsupported-content','authentication-refused','source-unavailable','media-not-approved'})


class Journal:
    def __init__(self,inbox,connector,scope,current):
        if (not isinstance(connector,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',connector)
                or not isinstance(scope,str) or not re.fullmatch(r'mailbox:[0-9a-f]{64}',scope) or not callable(current)):
            raise ValueError('exact private mailbox journal authority required')
        self.db=inbox.db;self.connector=connector;self.scope=scope;self.current=current;self.identity=digest([connector,scope])
        current()
        self.db.execute('''CREATE TABLE IF NOT EXISTS email_mailboxes(
            identity TEXT PRIMARY KEY,connector TEXT NOT NULL,scope TEXT NOT NULL,
            uid_validity INTEGER NOT NULL,uid_next INTEGER NOT NULL,cursor INTEGER NOT NULL,
            observed_validity INTEGER NOT NULL,observed_next INTEGER NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS email_receipts(
            identity TEXT NOT NULL,uid_validity INTEGER NOT NULL,uid INTEGER NOT NULL,
            header_sha256 TEXT,internal_at REAL,status TEXT NOT NULL,
            reason TEXT NOT NULL,native_id TEXT,PRIMARY KEY(identity,uid_validity,uid))''')

        self.db.execute('CREATE TABLE IF NOT EXISTS email_native_scopes (native_id TEXT PRIMARY KEY,connector TEXT NOT NULL,scope TEXT NOT NULL)')

    def remember_capture(self,native_id):
        self.current()
        if not isinstance(native_id,str) or not _HASH.fullmatch(native_id):raise ValueError('exact durable native email receipt required')
        old=self.db.execute('SELECT connector,scope FROM email_native_scopes WHERE native_id=?',(native_id,)).fetchone()
        if old is not None:
            if tuple(old)!=(self.connector,self.scope):raise PermissionError('native email receipt cannot move between mailboxes')
            return
        native=self.db.execute('SELECT connector,platform,envelope FROM native_inbox WHERE id=?',(native_id,)).fetchone()
        if native is None or native['connector']!=self.connector or native['platform']!='email':
            raise PermissionError('mail cursor requires a durable native input')
        envelope=json.loads(native['envelope'])
        if envelope.get('scope')!=self.scope:raise PermissionError('native email source mailbox is unavailable or different')
        self.db.execute('INSERT INTO email_native_scopes VALUES(?,?,?)',(native_id,self.connector,self.scope))

    def state(self):
        self.current();row=self.db.execute('SELECT * FROM email_mailboxes WHERE identity=?',(self.identity,)).fetchone()
        if row is None:raise Conflict('mailbox state has not been privately verified')
        return dict(row)

    def observe(self,validity,next_uid):
        uid_number(validity);uid_number(next_uid);self.current();self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM email_mailboxes WHERE identity=?',(self.identity,)).fetchone()
            if row is None:
                if self.db.execute('SELECT COUNT(*) FROM email_mailboxes').fetchone()[0]>=128:raise Conflict('private mailbox identity inventory full')
                self.db.execute('INSERT INTO email_mailboxes VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (self.identity,self.connector,self.scope,validity,next_uid,0,validity,next_uid,'ready',time.time()))
            else:
                status=row['status']
                if status=='ready':
                    if row['uid_validity']!=validity:status='uid-validity-changed'
                    elif next_uid<row['uid_next']:status='uid-next-regressed'
                self.db.execute('UPDATE email_mailboxes SET observed_validity=?,observed_next=?,uid_next=?,status=?,updated_at=? WHERE identity=?',
                    (validity,next_uid,max(next_uid,row['uid_next']) if validity==row['uid_validity'] else row['uid_next'],status,time.time(),self.identity))
            self.current();self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return self.state()

    def page(self,span=1000):
        if type(span) is not int or not 1<=span<=100000:raise ValueError('bounded private UID span required')
        row=self.state()
        if row['status']!='ready':raise PermissionError('mailbox UID state changed; explicit owner recovery required')
        if row['cursor']>=row['uid_next']-1:return None
        return {'uid_validity':row['uid_validity'],'after':row['cursor'],'through':min(row['cursor']+span,row['uid_next']-1)}

    def commit(self,page,receipts,*,uids):
        self.current()
        if (not isinstance(page,dict) or set(page)!={'uid_validity','after','through'}
                or type(page['after']) is not int or not 0<=page['after']<2**32
                or type(page['through']) is not int or not page['after']<page['through']<2**32
                or page['through']-page['after']>100000 or not isinstance(receipts,list) or len(receipts)>1000 or not isinstance(uids,list) or len(uids)>1000 or any(type(uid) is not int for uid in uids)):
            raise ValueError('bounded exact mailbox page and durable outcomes required')
        uid_number(page['uid_validity']);last=page['after']
        for item in receipts:
            if (not isinstance(item,dict) or set(item)!={'uid','header_sha256','internal_at','status','reason','native_id'}
                    or type(item['uid']) is not int or not last<item['uid']<=page['through']
                    or item['status'] not in {'captured','ignored','refused'}):
                raise ValueError('ordered bounded private email outcome required')
            unavailable=item['status']=='refused' and item['reason']=='source-unavailable'
            if unavailable:
                if item['header_sha256'] is not None or item['internal_at'] is not None:raise ValueError('unavailable mail has no claimed header digest or received time')
            elif (not isinstance(item['header_sha256'],str) or not _HASH.fullmatch(item['header_sha256'])
                    or type(item['internal_at']) not in {int,float} or not math.isfinite(item['internal_at']) or not 0<item['internal_at']<=time.time()+300):
                raise ValueError('verified email header digest and received time required')
            if item['status']=='captured':
                if item['reason']!='' or not isinstance(item['native_id'],str) or not _HASH.fullmatch(item['native_id']):
                    raise ValueError('captured email needs its exact durable native inbox receipt')
            elif item['native_id'] is not None or item['reason'] not in _REASONS:
                raise ValueError('closed private email refusal reason required')
            last=item['uid']
        if [item['uid'] for item in receipts]!=uids:raise ValueError('every searched UID needs exactly one durable disposition')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.state()
            if row['status']!='ready' or row['uid_validity']!=page['uid_validity'] or row['cursor']!=page['after'] or page['through']>=row['uid_next']:
                raise Conflict('stale mailbox cursor, validity or resource range')
            for item in receipts:
                if item['status']=='captured':
                    native=self.db.execute('SELECT connector,platform,envelope FROM native_inbox WHERE id=?',(item['native_id'],)).fetchone()
                    if native is None or native['connector']!=self.connector or native['platform']!='email':
                        raise PermissionError('mail cursor cannot advance before its native input is durable')
                    self.remember_capture(item['native_id'])
                old=self.db.execute('SELECT * FROM email_receipts WHERE identity=? AND uid_validity=? AND uid=?',
                    (self.identity,page['uid_validity'],item['uid'])).fetchone()
                expected=(item['header_sha256'],item['internal_at'],item['status'],item['reason'],item['native_id'])
                if old is not None:
                    if tuple(old[key] for key in ('header_sha256','internal_at','status','reason','native_id'))!=expected:
                        raise Conflict('email UID replay changed its durable resource or disposition')
                else:
                    if self.db.execute('SELECT COUNT(*) FROM email_receipts').fetchone()[0]>=65536:raise Conflict('private email receipt inventory full')
                    self.db.execute('INSERT INTO email_receipts VALUES(?,?,?,?,?,?,?,?)',(self.identity,page['uid_validity'],item['uid'],*expected))
            self.db.execute('UPDATE email_mailboxes SET cursor=?,updated_at=? WHERE identity=?',(page['through'],time.time(),self.identity))
            self.current();self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return self.state()
