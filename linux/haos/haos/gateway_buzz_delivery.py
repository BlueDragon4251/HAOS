"""Durable exact-source replies; uncertain attempts never silently sign a new ID."""
import asyncio
from copy import deepcopy
import hashlib
import json
import math
import time
from types import MethodType

from .gateway import Conflict,digest
from .gateway_buzz import HEX
from .gateway_buzz_crypto import wire
from .gateway_buzz_send_process import send as private_send


class Publisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.native=adapter._haos_native;self.value=deepcopy(adapter._haos_buzz_value)
        self.db=self.native.inbox.db;self.lock=asyncio.Lock();self.closed=False
        self.scope=digest([self.native.connector,self.value])
        self.db.execute('PRAGMA max_page_count='+str(64*1024*1024//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS buzz_delivery_intents(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,source_id TEXT NOT NULL,source_sha256 TEXT NOT NULL,
            fingerprint TEXT NOT NULL,target TEXT NOT NULL,state TEXT NOT NULL,signed_raw BLOB NOT NULL,
            signed_sha256 TEXT NOT NULL,event_id TEXT NOT NULL,receipt TEXT NOT NULL,error TEXT NOT NULL,
            created_at REAL NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(delivery_id,attempt))''')
        self.db.execute("UPDATE buzz_delivery_intents SET state='uncertain',error='delivery-unknown' WHERE connector=? AND credential_scope=? AND state='writing'",
            (self.native.connector,self.scope))

    def current(self,binding,authority):
        authority();self.adapter._haos_buzz_check()
        if (self.closed or self.adapter._haos_buzz_reader.authentication_refused
                or self.adapter.native_health()['status'] in {'created','connecting','closed','revoked','disconnected',
                    'authentication-refused','identity-refused'}):raise PermissionError('live private Buzz reply authority required')
        self.native.policy().current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if 'read' not in binding['capabilities']:raise PermissionError('independent Buzz reply/read grant required')

    async def source(self,binding,source_id):
        if not isinstance(source_id,str) or not HEX.fullmatch(source_id):raise PermissionError('exact committed Buzz reply source required')
        records=self.adapter._haos_buzz_raw.db.execute('SELECT id FROM buzz_raw_events WHERE connector=? AND event_id=?',
            (self.native.connector,source_id)).fetchall()
        if len(records)!=1:raise PermissionError('one retained signed Buzz reply original required')
        item=await self.adapter._haos_buzz_raw.get(self.native.policy(),self.native.connector,self.value,records[0]['id'])
        envelope=item['envelope']
        if any(envelope[key]!=binding[key] for key in ['sender','chat','scope','thread']):raise Conflict('Buzz reply source changed its approved recipient route')
        row=self.db.execute('SELECT * FROM native_inbox WHERE id=?',(item['source_key'],)).fetchone()
        if (row is None or row['state']!='committed' or row['connector']!=self.native.connector or row['platform']!='buzz'
                or row['message_id']!=source_id or row['binding_id']!=binding['id'] or row['binding_digest']!=digest(binding)
                or row['fingerprint']!=digest(envelope)):
            raise PermissionError('Buzz reply original has no matching committed independent input')
        return item

    async def send(self,binding,delivery_id,attempt,content,source_id,authority,*,prepared=None):
        from gateway.platforms.base import SendResult
        if (not isinstance(delivery_id,str) or not HEX.fullmatch(delivery_id) or type(attempt) is not int or not 1<=attempt<=5
                or not isinstance(content,str) or not content.strip() or len(content.encode())>32000):
            raise ValueError('one bounded exact Buzz outbox attempt and text required')
        binding=deepcopy(binding)
        def current():self.current(binding,authority)
        current();source=await self.source(binding,source_id);original=wire(source['raw'])
        attachments=[]
        if prepared is not None:
            if (not isinstance(prepared,dict) or set(prepared)!={'items','text'} or not isinstance(prepared['text'],str)
                    or len(prepared['text'].encode())>32000):raise PermissionError('closed private Buzz output projection required')
            if prepared['items']:
                attachments=self.adapter._haos_buzz_output.resolve({'id':delivery_id,'binding_id':binding['id'],
                    'binding_digest':digest(binding)},prepared['items'])
            elif not isinstance(prepared['items'],list):raise PermissionError('retained Buzz output identities required')
            content=prepared['text'] or ('Result files' if attachments else 'Mission completed.')
        if self.native.inbox.redactor.text(content)!=content:raise PermissionError('private Buzz credential reflection refused')
        target={'channel':binding['chat'],'anchor':binding['thread'] or source_id,'thread':binding['thread'] or source_id,
            'content':content,'kind':45003 if original['kind'] in {45001,45003} else 9,
            'allowed_mentions':sorted({binding['sender'],self.value['public_key']}),'explicit_mentions':[]}
        if attachments:target['attachments']=attachments
        encoded=json.dumps(target,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        source_sha=hashlib.sha256(source['raw']).hexdigest()
        fingerprint=digest([self.scope,digest(binding),source['id'],source_sha,target])
        async with self.lock:
            current();await self.source(binding,source_id)
            prior=self.db.execute('SELECT * FROM buzz_delivery_intents WHERE delivery_id=? ORDER BY attempt',(delivery_id,)).fetchall()
            replay=None
            for record in prior:
                row=validate(record)
                if (row['connector']!=self.native.connector or row['credential_scope']!=self.scope or row['fingerprint']!=fingerprint
                        or row['target']!=encoded or row['source_id']!=source_id or row['binding_id']!=binding['id']
                        or row['binding_digest']!=digest(binding) or row['source_sha256']!=source_sha):
                    raise Conflict('Buzz outbox replay changed source body target account or owner grant')
                if row['state']=='confirmed':return SendResult(success=True,message_id=row['receipt'],raw_response={'upstream_acceptance_only':True,'recipient_read_verified':False})
                if row['state'] in {'writing','uncertain'}:return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
                if row['state'] not in {'rejected','owner-retry-approved'}:raise Conflict('damaged Buzz delivery state')
                if row['attempt']==attempt:return SendResult(success=False,error='Buzz reply requires inspected recovery',raw_response={'haos_delivery':'refused'})
                if row['signed_raw']:
                    if replay is not None and replay!=bytes(row['signed_raw']):raise Conflict('Buzz attempts changed retained signed original')
                    replay=bytes(row['signed_raw'])
            if prior and (prior[-1]['attempt']+1!=attempt or prior[-1]['state']!='owner-retry-approved') or not prior and attempt!=1:
                raise Conflict('sequential inspected Buzz retry required')
            if self.db.execute('SELECT COUNT(*) FROM buzz_delivery_intents').fetchone()[0]>=65536:raise Conflict('private Buzz delivery journal full; inspected maintenance required')
            now=time.time()
            self.db.execute('INSERT INTO buzz_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (delivery_id,attempt,self.native.connector,self.scope,binding['id'],digest(binding),source_id,
                    hashlib.sha256(source['raw']).hexdigest(),fingerprint,encoded,'writing',b'','','','','',now,now))
            async def retained(raw,event):
                current();await self.source(binding,source_id)
                if replay is not None and raw!=replay:raise Conflict('Buzz recovery attempted to change original signed event')
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    previous=self.db.execute('SELECT * FROM buzz_delivery_intents WHERE delivery_id=? AND attempt=?',(delivery_id,attempt)).fetchone()
                    if previous is None:raise Conflict('Buzz signed intent was removed before publication')
                    previous=validate(previous)
                    if (previous['state']!='writing' or previous['fingerprint']!=fingerprint
                            or previous['signed_raw'] and bytes(previous['signed_raw'])!=raw):
                        raise Conflict('Buzz signed original was replaced during publication')
                    changed=self.db.execute("UPDATE buzz_delivery_intents SET signed_raw=?,signed_sha256=?,event_id=?,updated_at=? WHERE delivery_id=? AND attempt=? AND state='writing'",
                        (raw,hashlib.sha256(raw).hexdigest(),event['id'],time.time(),delivery_id,attempt)).rowcount
                    if changed!=1:raise Conflict('Buzz signed custody was not committed')
                    current();self.db.execute('COMMIT')
                except BaseException:
                    if self.db.in_transaction:self.db.execute('ROLLBACK')
                    raise
                return True
            outcome=None;used=False;owner=asyncio.current_task();reader=self.adapter._run_cli
            async def bridge(_adapter,args,*,input_text=None):
                nonlocal outcome,used
                if args[:2]!=['messages','send']:return await reader(args,input_text=input_text)
                if asyncio.current_task() is not owner or used or input_text!=content:
                    raise PermissionError('one sealed native Buzz write per approved outbox attempt required')
                from .gateway_buzz_send_process import target as arguments
                expected=arguments(self.value,target)
                native_args=expected[:]
                if target['kind']!=9:
                    index=native_args.index('--kind');del native_args[index:index+2]
                # The actual pinned native codec may add only approved explicit
                # mention identities. Its target/body remain immutable.
                prefix=native_args
                if args[:len(prefix)]!=prefix or len(args[len(prefix):])%2:raise Conflict('native Buzz reply codec changed its exact target')
                mentions=[]
                for flag,public in zip(args[len(prefix):][::2],args[len(prefix):][1::2]):
                    if flag!='--mention' or public not in target['allowed_mentions'] or public in mentions:raise PermissionError('native Buzz notification recipient is not independently approved')
                    mentions.append(public)
                actual={**target,'explicit_mentions':mentions};used=True
                outcome=await private_send(self.value,actual,home=self.adapter._haos_buzz_home,current=current,retain=retained,
                    redactor=self.native.inbox.redactor,replay=replay)
                if outcome['state']=='confirmed':return 0,json.dumps({'event_id':outcome['receipt'],'accepted':True}),''
                return 4,'',json.dumps({'error':'private_reply_refused','message':'private reply has no confirmed acceptance','retryable':False})
            self.adapter._run_cli=MethodType(bridge,self.adapter)
            try:
                from plugins.platforms.buzz.adapter import BuzzAdapter
                receipt=await BuzzAdapter.send(self.adapter,binding['chat'],content,reply_to=source_id,metadata={'thread_id':binding['thread']})
                current()
                if outcome is not None and outcome['state']=='confirmed' and receipt.success and receipt.message_id==outcome['receipt']:
                    self.db.execute("UPDATE buzz_delivery_intents SET state='confirmed',receipt=?,error='',updated_at=? WHERE delivery_id=? AND attempt=?",
                        (receipt.message_id,time.time(),delivery_id,attempt))
                    return SendResult(success=True,message_id=receipt.message_id,raw_response={'upstream_acceptance_only':True,'recipient_read_verified':False})
                state='rejected' if outcome is None or outcome['state']=='not-dispatched' else 'uncertain'
                self.db.execute('UPDATE buzz_delivery_intents SET state=?,error=?,updated_at=? WHERE delivery_id=? AND attempt=?',
                    (state,'prepublication-refused' if state=='rejected' else 'delivery-unknown',time.time(),delivery_id,attempt))
                return SendResult(success=False,raw_response={'haos_delivery':'refused' if state=='rejected' else 'uncertain'})
            except BaseException as error:
                self.db.execute("UPDATE buzz_delivery_intents SET state='uncertain',error='delivery-unknown',updated_at=? WHERE delivery_id=? AND attempt=?",
                    (time.time(),delivery_id,attempt))
                if isinstance(error,(asyncio.CancelledError,PermissionError)):raise
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            finally:self.adapter._run_cli=reader

    async def close(self):
        self.closed=True
        async with self.lock:pass


def validate(record):
    row=dict(record)
    fields={'delivery_id','attempt','connector','credential_scope','binding_id','binding_digest','source_id','source_sha256',
        'fingerprint','target','state','signed_raw','signed_sha256','event_id','receipt','error','created_at','updated_at'}
    if (set(row)!=fields or any(not isinstance(row[key],str) or not HEX.fullmatch(row[key])
            for key in ['delivery_id','credential_scope','binding_digest','source_id','source_sha256','fingerprint'])
            or type(row['attempt']) is not int or not 1<=row['attempt']<=5
            or row['state'] not in {'writing','confirmed','uncertain','rejected','owner-retry-approved'}
            or any(not isinstance(row[key],str) or not 1<=len(row[key])<=128 for key in ['connector','binding_id'])
            or not isinstance(row['target'],str) or len(row['target'].encode())>65536 or not isinstance(row['signed_raw'],bytes)
            or len(row['signed_raw'])>1048576 or any(not isinstance(row[key],str) for key in ['signed_sha256','event_id','receipt','error'])
            or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<=0 for key in ['created_at','updated_at'])
            or row['error']!=('delivery-unknown' if row['state']=='uncertain' else 'prepublication-refused' if row['state']=='rejected' else '')):
        raise Conflict('damaged Buzz delivery metadata')
    if row['signed_raw']:
        event=wire(bytes(row['signed_raw']))
        if hashlib.sha256(row['signed_raw']).hexdigest()!=row['signed_sha256'] or event['id']!=row['event_id']:
            raise Conflict('damaged retained signed Buzz reply')
    elif row['signed_sha256'] or row['event_id']:raise Conflict('Buzz signed original was removed; automatic restoration refused')
    if row['state']=='confirmed':
        if not row['signed_raw'] or row['receipt']!=row['event_id']:raise Conflict('damaged Buzz acceptance receipt')
    elif row['receipt']:raise Conflict('unconfirmed Buzz reply contains an acceptance receipt')
    return row
