"""FULL original custody keyed by authenticated peer/context/message, before native dispatch."""
import hashlib
import json
import math
from pathlib import Path
import re
import time

from .gateway import Conflict,digest
from .gateway_raw import NativeInbox
from .gateway_a2a_admission import approve,parse
from .gateway_line_ingress import _object
from .gateway_dingtalk_admission import finite
from .redaction import Redactor

LIMIT=64*1024*1024
HASH=re.compile('[0-9a-f]{64}\\Z')


def semantic(raw,approval):
    # JSON-RPC correlation IDs and send-vs-stream wrappers may change on retry.
    # They cannot change the retained original payload or create a second mission.
    return digest([parse(raw)['params'],approval['envelope'],approval['binding_digest'],approval['credential_scope']])


class RawEvents:
    def __init__(self,path,redactor,current):
        if not isinstance(redactor,Redactor) or not callable(current):raise PermissionError('private A2A redaction and current publication required')
        current();self.current=current;self.redactor=redactor;self.store=NativeInbox(Path(path),redactor);self.db=self.store.db
        self.db.execute('PRAGMA max_page_count='+str(LIMIT//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_raw_events(
            id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,connector TEXT NOT NULL,peer TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            sha256 TEXT NOT NULL,semantic_sha256 TEXT NOT NULL,metadata TEXT NOT NULL,data BLOB NOT NULL,
            received_at REAL NOT NULL,created_at REAL NOT NULL)''')

    def close(self):self.store.close()

    def validate(self,row,policy,connector,value,peer):
        record=dict(row)
        if (set(record)!={'id','source_key','connector','peer','binding_id','binding_digest','credential_scope','sha256',
                'semantic_sha256','metadata','data','received_at','created_at'}
                or any(not isinstance(record[k],str) or not HASH.fullmatch(record[k]) for k in ['id','source_key','binding_digest','credential_scope','sha256','semantic_sha256'])
                or record['connector']!=connector or record['peer']!=peer
                or any(type(record[k]) not in {int,float} or not math.isfinite(record[k]) or record[k]<=0 for k in ['received_at','created_at'])
                or not isinstance(record['metadata'],str) or len(record['metadata'].encode())>65536):
            raise Conflict('damaged private A2A source metadata')
        policy.current_binding(record)
        raw=bytes(record['data'])
        if not raw:raise PermissionError('A2A original removed; automatic restoration refused')
        if not 1<=len(raw)<=1024*1024 or hashlib.sha256(raw).hexdigest()!=record['sha256']:
            raise Conflict('damaged private A2A original bytes')
        try:metadata=json.loads(record['metadata'],object_pairs_hook=_object,parse_constant=finite)
        except (ValueError,RecursionError):raise Conflict('damaged private A2A source proof') from None
        proof=approve(policy,connector,value,peer,raw,self.redactor,received_at=record['received_at'])
        if (metadata!=proof or digest([record['source_key'],record['semantic_sha256']])!=record['id']
                or NativeInbox.key(connector,proof['envelope'])!=record['source_key']
                or semantic(raw,proof)!=record['semantic_sha256'] or proof['credential_scope']!=record['credential_scope']):
            raise Conflict('A2A source changed its codec, account, message or grant')
        return {'id':record['id'],'source_key':record['source_key'],'raw':raw,**proof}

    def capture(self,policy,connector,value,peer,raw):
        self.current();proof=approve(policy,connector,value,peer,raw,self.redactor)
        source=NativeInbox.key(connector,proof['envelope']);fingerprint=semantic(raw,proof);identity=digest([source,fingerprint])
        encoded=json.dumps(proof,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>65536:raise ValueError('bounded private A2A original proof required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT * FROM a2a_raw_events WHERE source_key=?',(source,)).fetchone()
            if old is not None:
                previous=self.validate(old,policy,connector,value,peer)
                if old['id']!=identity or old['semantic_sha256']!=fingerprint:
                    raise Conflict('A2A replay changed immutable source body, account or grant')
                result=previous
            else:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)+length(metadata)),0) FROM a2a_raw_events WHERE length(data)>0').fetchone()
                if (count>=128 or size+len(raw)+len(encoded.encode())>LIMIT
                        or self.db.execute('SELECT COUNT(*) FROM a2a_raw_events').fetchone()[0]>=65536):
                    raise Conflict('private A2A original capacity reached; owner maintenance required')
                self.db.execute('INSERT INTO a2a_raw_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,source,connector,peer,proof['binding_id'],proof['binding_digest'],proof['credential_scope'],
                        hashlib.sha256(raw).hexdigest(),fingerprint,encoded,raw,proof['received_at'],time.time()))
                result={'id':identity,'source_key':source,'raw':raw,**proof}
            self.current();self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return result

    def get(self,policy,connector,value,peer,identity):
        self.current()
        if not isinstance(identity,str) or not HASH.fullmatch(identity):raise ValueError('exact private A2A original receipt required')
        row=self.db.execute('SELECT * FROM a2a_raw_events WHERE id=?',(identity,)).fetchone()
        if row is None:raise PermissionError('unknown private A2A original')
        result=self.validate(row,policy,connector,value,peer);self.current();return result
