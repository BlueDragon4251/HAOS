"""Authenticated native Feishu webhook bytes and durable pre-ACK custody.

This is the private receive core, not a public listener. Listener framing, HTTPS,
rate limits and independent kernel identity must be established by its caller.
"""
import base64
import hashlib
import hmac
import json
from itertools import islice
from pathlib import Path
import re
import time
from types import SimpleNamespace

from .gateway import Conflict,digest
from .gateway_feishu import credentials
from .gateway_feishu_admission import parse,bounded,finite,approve,normalize,MAX_EVENT,Refused
from .gateway_line_ingress import _object
from .gateway_raw import NativeInbox

MAX_WIRE=4*((MAX_EVENT+34)//3)+128
_HEADER_NAMES={'x-lark-request-timestamp','x-lark-request-nonce','x-lark-signature'}


def headers(value):
    try:items=list(islice(value.items() if hasattr(value,'items') else value,65))
    except (TypeError,ValueError):raise Refused('invalid-authentication') from None
    if len(items)>64:raise Refused('invalid-authentication')
    result={}
    for entry in items:
        if not isinstance(entry,(tuple,list)) or len(entry)!=2:raise Refused('invalid-authentication')
        name,item=entry
        if (not isinstance(name,str) or not isinstance(item,str) or len(name)>128 or len(item)>16384
                or any(char in name+item for char in ['\r','\n','\0'])):raise Refused('invalid-authentication')
        name=name.lower()
        if name in _HEADER_NAMES:
            if name in result:raise Refused('invalid-authentication')
            result[name]=item
    if set(result)!=_HEADER_NAMES:raise Refused('invalid-authentication')
    stamp=result['x-lark-request-timestamp'];nonce=result['x-lark-request-nonce'];signature=result['x-lark-signature']
    if (not re.fullmatch('[1-9][0-9]{0,10}',stamp) or not re.fullmatch('[A-Za-z0-9_-]{8,256}',nonce)
            or not re.fullmatch('[0-9a-f]{64}',signature)):raise Refused('invalid-authentication')
    return result


def _authenticate(value,head,wire,current,*,fresh):
    current();value=credentials(value,verify_tls=False)
    if value['connection_mode']!='webhook':raise Refused('invalid-authentication')
    head=headers(head)
    if not isinstance(wire,bytes) or not 1<=len(wire)<=MAX_WIRE:raise Refused('unsupported-content')
    if fresh and abs(time.time()-int(head['x-lark-request-timestamp']))>300:raise Refused('stale-authentication')
    try:wire.decode('utf-8')
    except UnicodeError:raise Refused('invalid-authentication') from None
    signature=hashlib.sha256((head['x-lark-request-timestamp']+head['x-lark-request-nonce']+value['encrypt_key']).encode()+wire).hexdigest()
    if not hmac.compare_digest(signature,head['x-lark-signature']):raise Refused('invalid-authentication')
    # The actual pinned Hermes signature validator must agree on the original bytes.
    from plugins.platforms.feishu import adapter as native
    if not native.FeishuAdapter._is_webhook_signature_valid(SimpleNamespace(_encrypt_key=value['encrypt_key']),head,wire):
        raise Refused('invalid-authentication')
    try:outer=json.loads(wire.decode(),object_pairs_hook=_object,parse_constant=finite);bounded(outer)
    except (ValueError,UnicodeError,RecursionError):raise Refused('unsupported-content') from None
    if not isinstance(outer,dict):raise Refused('unsupported-content')
    if 'encrypt' in outer:
        if set(outer)!={'encrypt'} or not isinstance(outer['encrypt'],str):raise Refused('unsupported-content')
        try:
            encrypted=base64.b64decode(outer['encrypt'],validate=True)
            if base64.b64encode(encrypted).decode()!=outer['encrypt'] or not 32<=len(encrypted)<=MAX_EVENT+32:
                raise ValueError('bounded canonical ciphertext required')
            from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
            decoder=EventDispatcherHandler.builder(value['encrypt_key'],value['verification_token']).build()
            plaintext=decoder._decrypt(wire).encode('utf-8')
        except Exception:raise Refused('invalid-authentication') from None
    else:plaintext=wire
    body=parse(plaintext)
    challenge=body.get('type')=='url_verification'
    token=body.get('token') if challenge else body.get('header',{}).get('token') if isinstance(body.get('header'),dict) else None
    if not isinstance(token,str) or not hmac.compare_digest(token.encode(),value['verification_token'].encode()):
        raise Refused('invalid-authentication')
    if challenge:
        item=body.get('challenge')
        if (set(body)!={'type','token','challenge'} or not isinstance(item,str) or not 1<=len(item.encode())<=1024
                or any(ord(char)<32 for char in item)):raise Refused('unsupported-content')
    current()
    return {'plaintext':plaintext,'headers':head,'challenge':body['challenge'] if challenge else None}


class Receiver:
    def __init__(self,adapter,path):
        self.adapter=adapter;self.value=credentials(adapter._haos_feishu_value,verify_tls=False)
        if self.value['connection_mode']!='webhook':raise ValueError('private webhook account required')
        self.current=adapter._haos_feishu_check;self.current()
        redactor=adapter._haos_feishu_raw.redactor
        redactor.secrets=sorted(set([*redactor.secrets,self.value['app_secret'],self.value['verification_token'],
            self.value['encrypt_key'],self.value['tls']['private_key']]),key=len,reverse=True)
        self.store=NativeInbox(Path(path),adapter._haos_feishu_raw.redactor);self.db=self.store.db
        self.db.execute('PRAGMA max_page_count='+str(64*1024*1024//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS feishu_webhook_receipts(
            id TEXT PRIMARY KEY,credential_scope TEXT NOT NULL,headers TEXT NOT NULL,wire BLOB NOT NULL,
            wire_sha256 TEXT NOT NULL,proof TEXT NOT NULL,state TEXT NOT NULL,source_key TEXT,created_at REAL NOT NULL)''')
        self.credential_scope=digest([adapter._haos_native.connector,self.value])

    def close(self):self.store.close()

    def project(self,head,wire,*,fresh):
        self.current();result=_authenticate(self.value,head,wire,self.current,fresh=fresh)
        if result['challenge'] is not None:return result,None
        native=self.adapter._haos_native;policy=native.policy()
        proof=approve(policy,native.connector,self.value,result['plaintext'])
        normalize(policy,native.connector,self.value,result['plaintext'],proof,self.adapter._haos_feishu_raw.redactor)
        self.current();return result,proof

    def receive(self,head,wire):
        result,proof=self.project(head,wire,fresh=True)
        if proof is None:return {'challenge':result['challenge']}
        head=result['headers'];identity=digest([self.credential_scope,head['x-lark-request-timestamp'],head['x-lark-request-nonce']])
        metadata=json.dumps(proof,sort_keys=True,separators=(',',':'));encoded_headers=json.dumps(head,sort_keys=True)
        checksum=hashlib.sha256(wire).hexdigest();self.current();self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT * FROM feishu_webhook_receipts WHERE id=?',(identity,)).fetchone()
            if old is None:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(wire)+length(proof)),0) FROM feishu_webhook_receipts WHERE length(wire)>0').fetchone()
                if (count>=128 or size+len(wire)+len(metadata.encode())>64*1024*1024
                        or self.db.execute('SELECT COUNT(*) FROM feishu_webhook_receipts').fetchone()[0]>=65536):
                    raise Conflict('private Feishu webhook receipt capacity reached; owner recovery required')
                self.db.execute('INSERT INTO feishu_webhook_receipts VALUES(?,?,?,?,?,?,?,?,?)',
                    (identity,self.credential_scope,encoded_headers,wire,checksum,metadata,'retained',None,time.time()))
            elif (old['credential_scope']!=self.credential_scope or old['headers']!=encoded_headers
                    or bytes(old['wire'])!=wire or old['wire_sha256']!=checksum or old['proof']!=metadata):
                raise Conflict('Feishu webhook nonce reused with a different event or proof')
            self.current();self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        self._capture(identity,result,proof)
        return {'code':0,'msg':'ok'}

    def _capture(self,identity,result,proof):
        from .gateway_feishu_ingress import capture
        self.current();native=self.adapter._haos_native
        latest=approve(native.policy(),native.connector,self.value,result['plaintext'])
        if latest!=proof:raise Conflict('Feishu webhook approval changed before input capture')
        key=capture(self.adapter,result['plaintext']);self.current()
        old=self.db.execute('SELECT * FROM feishu_webhook_receipts WHERE id=?',(identity,)).fetchone()
        if old is None or old['state'] not in {'retained','captured'} or old['source_key'] not in {None,key}:
            raise Conflict('Feishu webhook receipt or captured source changed')
        self.db.execute("UPDATE feishu_webhook_receipts SET state='captured',source_key=? WHERE id=?",(key,identity))
        self.current();return key

    def recover(self):
        """Only retained authenticated originals may cross the live freshness window."""
        self.current();keys=[]
        for row in self.db.execute("SELECT * FROM feishu_webhook_receipts WHERE state='retained' ORDER BY created_at").fetchall():
            self.current();wire=bytes(row['wire'])
            if row['credential_scope']!=self.credential_scope or hashlib.sha256(wire).hexdigest()!=row['wire_sha256']:
                raise Conflict('private Feishu webhook original or credential epoch changed')
            try:head=json.loads(row['headers'],object_pairs_hook=_object,parse_constant=finite)
            except (ValueError,UnicodeError,RecursionError):raise Conflict('private Feishu webhook headers damaged') from None
            result,proof=self.project(head,wire,fresh=False)
            identity=digest([self.credential_scope,result['headers']['x-lark-request-timestamp'],result['headers']['x-lark-request-nonce']])
            if (identity!=row['id'] or proof is None or json.dumps(proof,sort_keys=True,separators=(',',':'))!=row['proof']):
                raise Conflict('private Feishu retained webhook proof changed')
            keys.append(self._capture(identity,result,proof))
        return keys
