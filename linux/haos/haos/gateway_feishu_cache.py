"""Private bounded original-event custody before Feishu transport acknowledgement."""
import hashlib
import json
from pathlib import Path
import re
import time

from .gateway import Conflict,digest
from .gateway_raw import NativeInbox
from .gateway_feishu import credentials
from .gateway_feishu_admission import approve,normalize,parse,milliseconds,MAX_EVENT,finite
from .gateway_line_ingress import _object
from .redaction import Redactor

LIMIT=64*1024*1024


def semantic(raw,approval):
    message=parse(raw)['event']['message']
    content=json.loads(message['content'],object_pairs_hook=_object)
    return digest([approval['envelope'],approval['binding_digest'],approval['credential_scope'],
        milliseconds(message['create_time']),message['message_type'],message['chat_type'],content,
        message.get('mentions') or [],message.get('root_id') or '',message.get('parent_id') or '',message.get('update_time')])


def metadata(text):
    if not isinstance(text,str) or len(text.encode())>16384:raise Conflict('original Feishu proof is damaged')
    try:value=json.loads(text,object_pairs_hook=_object,parse_constant=finite)
    except (ValueError,UnicodeError,RecursionError):raise Conflict('original Feishu proof is damaged') from None
    if (not isinstance(value,dict) or set(value)!={'approval','resources','envelope_sha256'}
            or not isinstance(value['approval'],dict) or not isinstance(value['resources'],list)
            or not isinstance(value['envelope_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['envelope_sha256'])):
        raise Conflict('original Feishu proof shape is damaged')
    return value


class RawEvents:
    def __init__(self,path,redactor,current):
        if not isinstance(redactor,Redactor) or not callable(current):raise PermissionError('private redaction and current publication callback required')
        current();self.current=current;self.redactor=redactor;self.store=NativeInbox(Path(path),redactor);self.db=self.store.db
        self.db.execute('PRAGMA max_page_count='+str(LIMIT//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS feishu_raw_events(
            id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,connector TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            sha256 TEXT NOT NULL,semantic_sha256 TEXT NOT NULL,metadata TEXT NOT NULL,
            data BLOB NOT NULL,created_at REAL NOT NULL)''')

    def close(self):self.store.close()

    def capture(self,policy,connector,value,raw):
        self.current();approval=approve(policy,connector,value,raw)
        result=normalize(policy,connector,value,raw,approval,self.redactor)
        source_key=NativeInbox.key(connector,result['envelope']);fingerprint=semantic(raw,approval)
        identity=digest([source_key,fingerprint]);checksum=hashlib.sha256(raw).hexdigest()
        encoded_metadata=json.dumps({'approval':approval,'resources':result['resources'],'envelope_sha256':digest(result['envelope'])},
            sort_keys=True,ensure_ascii=False,allow_nan=False)
        if len(encoded_metadata.encode())>16384:raise ValueError('bounded original Feishu event proof required')
        self.current();self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT * FROM feishu_raw_events WHERE source_key=?',(source_key,)).fetchone()
            if old is None:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)+length(metadata)),0) FROM feishu_raw_events WHERE length(data)>0').fetchone()
                if (count>=128 or size+len(raw)+len(encoded_metadata.encode())>LIMIT
                        or self.db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]>=65536):
                    raise Conflict('private Feishu original-event capacity reached')
                self.db.execute('INSERT INTO feishu_raw_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,source_key,connector,approval['binding_id'],approval['binding_digest'],approval['credential_scope'],
                     checksum,fingerprint,encoded_metadata,raw,time.time()))
            else:
                expected={'id':identity,'connector':connector,'binding_id':approval['binding_id'],
                    'binding_digest':approval['binding_digest'],'credential_scope':approval['credential_scope'],'semantic_sha256':fingerprint}
                if any(old[key]!=part for key,part in expected.items()):
                    raise Conflict('Feishu source changed its immutable body, route, grant or credential identity')
                data=bytes(old['data'])
                if not data:raise PermissionError('original Feishu bytes unavailable; automatic restoration refused')
                if not 1<=len(data)<=MAX_EVENT or hashlib.sha256(data).hexdigest()!=old['sha256']:
                    raise Conflict('retained Feishu original-event bytes are damaged')
                before=metadata(old['metadata'])
                old_approval=approve(policy,connector,value,data)
                if before['approval']!=old_approval or semantic(data,old_approval)!=old['semantic_sha256']:
                    raise Conflict('retained Feishu source proof changed')
                if before['resources']!=result['resources'] or before['envelope_sha256']!=digest(result['envelope']):
                    raise Conflict('Feishu source changed its native codec projection or resources')
            self.current();self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return {'id':identity,'source_key':source_key,'envelope':result['envelope'],
            'resources':result['resources'],'received_at':approval['received_at']}

    def get(self,policy,connector,value,identity):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('exact opaque original Feishu receipt required')
        self.current();row=self.db.execute('SELECT * FROM feishu_raw_events WHERE id=?',(identity,)).fetchone()
        if row is None:raise PermissionError('private original Feishu event unavailable')
        policy.current_binding({'binding_id':row['binding_id'],'binding_digest':row['binding_digest']})
        if connector!=row['connector'] or digest([connector,credentials(value,verify_tls=False)])!=row['credential_scope']:
            raise PermissionError('Feishu original cannot move between accounts or credential epochs')
        raw=bytes(row['data'])
        if not raw:raise PermissionError('original Feishu bytes unavailable')
        if not 1<=len(raw)<=MAX_EVENT or hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise Conflict('private original Feishu bytes are damaged')
        before=metadata(row['metadata']);approval=approve(policy,connector,value,raw)
        if before['approval']!=approval or semantic(raw,approval)!=row['semantic_sha256']:
            raise Conflict('private original Feishu source proof is damaged or changed')
        result=normalize(policy,connector,value,raw,approval,self.redactor)
        if (before['resources']!=result['resources'] or before['envelope_sha256']!=digest(result['envelope'])
                or NativeInbox.key(connector,result['envelope'])!=row['source_key']):
            raise Conflict('private original Feishu codec projection changed')
        self.current()
        return {'id':identity,'source_key':row['source_key'],'raw':raw,**result,'received_at':approval['received_at']}
