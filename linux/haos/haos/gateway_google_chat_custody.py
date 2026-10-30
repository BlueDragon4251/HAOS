"""Private FULL original receipt, committed before HTTP/PubSub acknowledgment.

The caller must establish transport identity and kernel isolation. This prepared
store does not authenticate callers or create missions by itself.
"""
import hashlib
import json
import time

from .gateway import Conflict,digest
from .gateway_raw import NativeInbox
from .gateway_google_chat_admission import approve,message
from .gateway_dingtalk_admission import parse


class Originals:
    def __init__(self,path,redactor):
        self.store=NativeInbox(path,redactor);self.db=self.store.db
        self.db.execute('PRAGMA max_page_count='+str(64*1024*1024//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_originals(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,message_id TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,semantic_sha256 TEXT NOT NULL,
            raw BLOB NOT NULL,raw_sha256 TEXT NOT NULL,proof TEXT NOT NULL,created_at REAL NOT NULL,
            admitted_receipt TEXT NOT NULL DEFAULT '')''')

    def close(self):self.store.close()

    def retain(self,policy,connector,value,raw,current):
        current();proof=approve(policy,connector,value,raw);msg,space=message(parse(raw));semantic=digest([msg,space])
        envelope=proof['envelope'];key=digest([connector,envelope['scope'],envelope['message_id']]);encoded=json.dumps(proof,sort_keys=True,separators=(',',':'))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM google_chat_originals WHERE id=?',(key,)).fetchone()
            if row is None:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(raw)+length(proof)),0) FROM google_chat_originals WHERE length(raw)>0').fetchone()
                total=self.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]
                if count>=128 or size+len(raw)+len(encoded.encode())>64*1024*1024 or total>=65536:
                    raise Conflict('private Google Chat source capacity reached; owner recovery required')
                self.db.execute('INSERT INTO google_chat_originals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key,connector,proof['credential_scope'],envelope['message_id'],proof['binding_id'],proof['binding_digest'],semantic,
                        raw,proof['raw_sha256'],encoded,time.time(),''))
            else:
                if (row['connector']!=connector or row['credential_scope']!=proof['credential_scope']
                        or row['message_id']!=envelope['message_id'] or row['binding_id']!=proof['binding_id']
                        or row['binding_digest']!=proof['binding_digest'] or row['semantic_sha256']!=semantic):
                    raise Conflict('Google Chat original identity or independent authority changed')
                self._verify(row)
            policy.current_binding(proof);current();self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return key

    def _verify(self,row):
        if not row['raw'] or hashlib.sha256(row['raw']).hexdigest()!=row['raw_sha256']:
            raise Conflict('Google Chat original unavailable or damaged; never restore automatically')
        msg,space=message(parse(bytes(row['raw'])))
        proof=json.loads(row['proof'])
        if (digest([msg,space])!=row['semantic_sha256'] or proof['raw_sha256']!=row['raw_sha256']
                or any(proof[k]!=row[k] for k in ['credential_scope','binding_id','binding_digest'])):
            raise Conflict('Google Chat original proof differs from retained source')

    def load(self,key,policy,connector,value,current):
        current();row=self.db.execute('SELECT * FROM google_chat_originals WHERE id=?',(key,)).fetchone()
        if row is None:raise KeyError('unknown retained Google Chat source')
        self._verify(row);raw=bytes(row['raw']);proof=approve(policy,connector,value,raw)
        if json.loads(row['proof'])!=proof:raise Conflict('Google Chat retained source authority changed')
        policy.current_binding(proof);current();return raw,proof

    def admitted(self,key,receipt,policy,connector,value,current):
        # A source receipt records only completed parent custody, not a model
        # run, external message delivery or a new authorization.
        if not isinstance(receipt,str) or len(receipt)!=64 or any(c not in '0123456789abcdef' for c in receipt):
            raise ValueError('exact parent custody receipt required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.load(key,policy,connector,value,current)
            prior=self.db.execute('SELECT admitted_receipt FROM google_chat_originals WHERE id=?',(key,)).fetchone()[0]
            if prior and prior!=receipt:raise Conflict('Google Chat source already belongs to another parent receipt')
            self.db.execute('UPDATE google_chat_originals SET admitted_receipt=? WHERE id=?',(receipt,key))
            current();self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
