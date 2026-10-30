"""FULL first-original custody for signed Buzz events before native dispatch."""
import hashlib
import json
import math
from pathlib import Path
import time

from .gateway import Conflict,digest
from .gateway_raw import NativeInbox
from .gateway_buzz_crypto import wire
from .gateway_buzz import HEX
from .gateway_buzz_admission import approve
from .redaction import Redactor

LIMIT=64*1024*1024


class RawEvents:
    def __init__(self,path,redactor,current):
        if not isinstance(redactor,Redactor) or not callable(current):raise PermissionError('private Buzz redaction and current owner publication required')
        current();self.current=current;self.redactor=redactor;self.store=NativeInbox(Path(path),redactor);self.db=self.store.db
        self.db.execute('PRAGMA max_page_count='+str(LIMIT//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS buzz_raw_events(
            id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,connector TEXT NOT NULL,event_id TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            metadata TEXT NOT NULL,sha256 TEXT NOT NULL,data BLOB NOT NULL,received_at REAL NOT NULL,
            admitted_receipt TEXT NOT NULL,created_at REAL NOT NULL)''')

    def close(self):self.store.close()

    async def validate(self,row,policy,connector,value,own_reply=None):
        record=dict(row)
        if (set(record)!={'id','source_key','connector','event_id','binding_id','binding_digest','credential_scope','metadata','sha256','data','received_at','admitted_receipt','created_at'}
                or record['connector']!=connector or record['admitted_receipt'] not in {'',record['source_key']}
                or any(type(record[key]) not in {int,float} or not math.isfinite(record[key]) or record[key]<=0 for key in ['received_at','created_at'])
                or not isinstance(record['metadata'],str) or len(record['metadata'].encode())>65536):raise Conflict('damaged retained Buzz source mapping')
        policy.current_binding(record);raw=bytes(record['data'])
        if not raw:raise PermissionError('Buzz original was removed; automatic restoration refused')
        if not 1<=len(raw)<=1048576 or hashlib.sha256(raw).hexdigest()!=record['sha256']:raise Conflict('damaged retained Buzz original bytes')
        event=wire(raw);proof=await approve(policy,connector,value,raw,self.redactor,received_at=record['received_at'],own_reply=own_reply)
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        try:metadata=json.loads(record['metadata'],object_pairs_hook=_object,parse_constant=finite)
        except (ValueError,RecursionError):raise Conflict('damaged retained Buzz source proof') from None
        if (metadata!=proof or proof['credential_scope']!=record['credential_scope'] or event['id']!=record['event_id']
                or NativeInbox.key(connector,proof['envelope'])!=record['source_key']
                or digest([record['source_key'],record['event_id'],proof['binding_digest'],proof['credential_scope']])!=record['id']):
            raise Conflict('Buzz source changed its signed body account route or timed grant')
        return {'id':record['id'],'source_key':record['source_key'],'raw':raw,**proof}

    async def get(self,policy,connector,value,identity,*,own_reply=None):
        self.current()
        if not isinstance(identity,str) or not HEX.fullmatch(identity):raise ValueError('exact retained Buzz original ID required')
        row=self.db.execute('SELECT * FROM buzz_raw_events WHERE id=?',(identity,)).fetchone()
        if row is None:raise PermissionError('unknown retained Buzz original')
        result=await self.validate(row,policy,connector,value,own_reply);self.current();return result

    async def capture(self,policy,connector,value,raw,*,own_reply=None):
        self.current();event=wire(raw)
        canonical=json.dumps(event,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        proof=await approve(policy,connector,value,canonical,self.redactor,own_reply=own_reply)
        source=NativeInbox.key(connector,proof['envelope']);identity=digest([source,event['id'],proof['binding_digest'],proof['credential_scope']])
        encoded=json.dumps(proof,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>65536:raise ValueError('bounded private Buzz original proof required')
        previous=self.db.execute('SELECT * FROM buzz_raw_events WHERE source_key=?',(source,)).fetchone()
        if previous is not None:
            prior=await self.validate(previous,policy,connector,value,own_reply)
            # Nostr's ID commits every signed semantic field but not signature
            # randomness. Preserve the FIRST valid signature/original on replay.
            old_event=wire(prior['raw'])
            if identity!=previous['id'] or {key:item for key,item in old_event.items() if key!='sig'}!={key:item for key,item in event.items() if key!='sig'}:
                raise Conflict('Buzz replay changed immutable signed source or owner epoch')
            self.current();return prior
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT 1 FROM buzz_raw_events WHERE source_key=?',(source,)).fetchone() is not None:
                raise Conflict('concurrent Buzz capture requires replay of its retained first original')
            count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)+length(metadata)),0) FROM buzz_raw_events WHERE length(data)>0').fetchone()
            if count>=128 or size+len(canonical)+len(encoded.encode())>LIMIT or self.db.execute('SELECT COUNT(*) FROM buzz_raw_events').fetchone()[0]>=65536:
                raise Conflict('private Buzz original capacity reached; inspected owner maintenance required')
            self.db.execute('INSERT INTO buzz_raw_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,source,connector,event['id'],proof['binding_id'],proof['binding_digest'],proof['credential_scope'],encoded,
                    hashlib.sha256(canonical).hexdigest(),canonical,proof['received_at'],'',time.time()))
            self.current();self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return {'id':identity,'source_key':source,'raw':canonical,**proof}

    def admitted(self,identity,receipt):
        self.current();row=self.db.execute('SELECT source_key,admitted_receipt FROM buzz_raw_events WHERE id=?',(identity,)).fetchone()
        if row is None or receipt!=row['source_key'] or row['admitted_receipt'] not in {'',receipt}:
            raise PermissionError('exact durable local Buzz parent inbox receipt required')
        self.db.execute("UPDATE buzz_raw_events SET admitted_receipt=? WHERE id=?",(receipt,identity));self.current()
