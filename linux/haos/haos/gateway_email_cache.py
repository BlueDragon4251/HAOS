"""Private bounded durable raw-mail custody, never an agent-readable pathname."""
import hashlib
import json
import math
import re
import time

from .gateway import digest,Conflict
from .gateway_email_codec import MAX_RAW,MAX_HEADERS
from .gateway_email_imap import uid_number
from .gateway_raw import NativeInbox

LIMIT=64*1024*1024


class RawCache:
    def __init__(self,path,redactor):
        self.store=NativeInbox(path,redactor);self.db=self.store.db;self.redactor=redactor
        self.db.execute('PRAGMA max_page_count='+str(LIMIT//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS email_raw_messages(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            source_id TEXT NOT NULL,uid_validity INTEGER NOT NULL,uid INTEGER NOT NULL,
            sha256 TEXT NOT NULL,metadata TEXT NOT NULL,data BLOB NOT NULL,created_at REAL NOT NULL)''')

    def close(self):self.store.close()

    @staticmethod
    def current(policy,row):
        binding=policy.current_binding({'binding_id':row['binding_id'],'binding_digest':row['binding_digest']})
        if policy.connectors[binding['connector']]['platform']!='email' or binding['connector']!=row['connector']:
            raise PermissionError('exact current email raw-custody grant required')
        return binding

    def put(self,policy,connector,resource):
        if not isinstance(resource,dict) or 'content' not in resource or 'approval' not in resource:
            raise ValueError('complete independently approved raw email required')
        data=resource['content'];approval=resource['approval']
        if not isinstance(data,bytes) or not 1<=len(data)<=MAX_RAW or resource.get('size')!=len(data):
            raise ValueError('bounded complete raw email bytes required')
        uid_number(resource['uid']);uid_number(resource['uid_validity'])
        checksum=hashlib.sha256(data).hexdigest()
        boundary=data.find(b'\r\n\r\n')
        if (checksum!=resource['sha256'] or not 0<boundary<=MAX_HEADERS
                or hashlib.sha256(data[:boundary+4]).hexdigest()!=approval['header_sha256']):
            raise Conflict('raw mail resource changed after independent approval')
        binding=self.current(policy,{'connector':connector,**approval})
        routed=policy.authorize(connector,approval['envelope'])
        if routed['id']!=binding['id'] or digest(routed)!=digest(binding):raise PermissionError('raw email source differs from the captured recipient grant')
        stamp=resource.get('internal_at')
        if (type(stamp) not in {int,float} or not math.isfinite(stamp) or not binding['since']<stamp*1000
                or not 0<stamp<=time.time()+300 or approval.get('received_at')!=stamp):
            raise PermissionError('raw email was not received under this exact timed owner grant')
        if any(secret.encode() in data for secret in self.redactor.secrets):raise PermissionError('private email credential reflection refused')
        metadata=json.dumps({key:value for key,value in resource.items() if key!='content'},ensure_ascii=False,allow_nan=False)
        if len(metadata.encode())>16384:raise ValueError('bounded private mail source metadata required')
        identity=digest([connector,digest(binding),resource['uid_validity'],resource['uid'],checksum])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT sha256 FROM email_raw_messages WHERE id=?',(identity,)).fetchone()
            if old is None:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)+length(metadata)),0) FROM email_raw_messages').fetchone()
                if count>=128 or size+len(data)+len(metadata.encode())>LIMIT:raise Conflict('private raw email custody capacity reached')
                self.db.execute('INSERT INTO email_raw_messages VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,connector,binding['id'],digest(binding),approval['envelope']['message_id'],resource['uid_validity'],resource['uid'],
                     checksum,metadata,data,time.time()))
            elif old['sha256']!=checksum:raise Conflict('raw email replay changed bytes')
            self.current(policy,{'connector':connector,**approval});self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return identity

    def get(self,policy,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{64}',identity):raise ValueError('exact opaque raw email receipt required')
        row=self.db.execute('SELECT * FROM email_raw_messages WHERE id=?',(identity,)).fetchone()
        if row is None:raise PermissionError('private raw email resource unavailable')
        self.current(policy,row);data=bytes(row['data'])
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Conflict('private raw email bytes are damaged')
        return {**json.loads(row['metadata']),'content':data}
