"""Durable single-reply intents bound to committed native input and current owner grants."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import math
import re
import time

from .gateway import digest,Conflict
from .gateway_feishu import MESSAGE_ID
from .gateway_feishu_send import specification,wire_target
from . import gateway_feishu_process as process


class Publisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.native=adapter._haos_native;self.value=deepcopy(adapter._haos_feishu_value)
        self.db=self.native.inbox.db;self.lock=asyncio.Lock();self.closed=False
        self.db.execute('''CREATE TABLE IF NOT EXISTS feishu_delivery_intents(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,fingerprint TEXT NOT NULL,
            state TEXT NOT NULL,receipt TEXT NOT NULL,error TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,attempt))''')
        self.account_scope=digest([self.value[key] for key in ['domain','app_id','app_secret','tenant_key','bot_open_id']])
        self.db.execute('''CREATE TABLE IF NOT EXISTS feishu_delivery_backoff(
            account_scope TEXT PRIMARY KEY,status TEXT NOT NULL,next_attempt REAL NOT NULL,updated_at REAL NOT NULL)''')
        self.db.execute('INSERT OR IGNORE INTO feishu_delivery_backoff VALUES(?,?,?,?)',(self.account_scope,'ready',0,time.time()))
        self.credential_scope=digest([self.native.connector,self.value])
        self.db.execute("UPDATE feishu_delivery_intents SET state='uncertain' WHERE state='writing' AND connector=? AND credential_scope=?",
            (self.native.connector,self.credential_scope))

    def current(self,binding,authority):
        authority();self.adapter._haos_feishu_check()
        if self.closed or not self.adapter.is_connected or self.adapter._haos_feishu_value!=self.value:
            raise PermissionError('connected unchanged private Feishu publisher required')
        latest=self.native.policy();latest.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if binding['connector']!=self.native.connector or 'read' not in binding['capabilities']:
            raise PermissionError('current exact Feishu read/reply grant required')

    def source(self,binding,source_id):
        if not isinstance(source_id,str) or not MESSAGE_ID.fullmatch(source_id):
            raise PermissionError('exact retained native Feishu source message required')
        rows=self.db.execute('''SELECT c.* FROM feishu_source_context c JOIN native_inbox n ON n.id=c.source_key
            WHERE n.connector=? AND n.message_id=? AND n.binding_digest=? AND n.state='committed' ''',
            (self.native.connector,source_id,digest(binding))).fetchall()
        if len(rows)!=1:raise PermissionError('one durably admitted native Feishu reply source required')
        row=dict(rows[0])
        if any(row[key]!=binding[field] for key,field in [('connector','connector'),('scope','scope'),('chat','chat'),
                ('thread','thread'),('sender','sender')]) or row['message_id']!=source_id:
            raise PermissionError('Feishu retained reply context changed')
        item=self.adapter._haos_feishu_raw.get(self.native.policy(),self.native.connector,self.value,row['raw_id'])
        if item['source_key']!=row['source_key'] or item['envelope']['message_id']!=source_id:
            raise Conflict('Feishu original reply source differs from committed input')
        return item

    def health(self):
        row=self.db.execute('SELECT status,next_attempt FROM feishu_delivery_backoff WHERE account_scope=?',(self.account_scope,)).fetchone()
        if (row is None or row['status'] not in {'ready','rate-limited','authentication-refused'}
                or type(row['next_attempt']) not in {int,float} or not math.isfinite(row['next_attempt']) or row['next_attempt']<0):
            raise Conflict('damaged private Feishu delivery backoff')
        return dict(row)

    @staticmethod
    def refusal(error,delay=60):
        from gateway.platforms.base import SendResult
        if error=='rate-limited':return SendResult(success=False,error_kind='rate_limited',retry_after=delay,raw_response={'haos_delivery':'refused'})
        if error=='transport-unavailable':
            return SendResult(success=False,retryable=True,retry_after=5,raw_response={'haos_delivery':'not-dispatched'})
        return SendResult(success=False,error_kind='forbidden' if error in {'authentication-refused','identity-refused','tls-refused'} else 'bad_format',
            raw_response={'haos_delivery':'refused'})

    async def send(self,binding,delivery_id,attempt,content,source_id,authority):
        from gateway.platforms.base import SendResult
        if (not isinstance(delivery_id,str) or not re.fullmatch('[0-9a-f]{64}',delivery_id)
                or type(attempt) is not int or not 1<=attempt<=5):raise ValueError('exact bounded Feishu outbox attempt required')
        binding=deepcopy(binding)
        def current():self.current(binding,authority)
        current();source=self.source(binding,source_id);raw=source['raw']
        blueprint={'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':delivery_id,'attempt':attempt,
            'source_id':source_id,'source_sha256':hashlib.sha256(raw).hexdigest(),'source_base64':base64.b64encode(raw).decode(),'body':content}
        item=specification(self.value,self.native.policy(),self.native.connector,blueprint,self.native.inbox.redactor)
        target=wire_target(self.adapter,item)
        fingerprint=digest([self.value,digest(binding),source['id'],item['source_sha256'],content,target])
        async with self.lock:
            current();self.source(binding,source_id)
            previous=self.db.execute('SELECT * FROM feishu_delivery_intents WHERE delivery_id=? ORDER BY attempt',(delivery_id,)).fetchall()
            for row in previous:
                if row['connector']!=self.native.connector or row['credential_scope']!=self.credential_scope or row['fingerprint']!=fingerprint:raise Conflict('Feishu delivery changed source, body, native wire codec or authority')
                if row['state']=='confirmed':
                    if not isinstance(row['receipt'],str) or not MESSAGE_ID.fullmatch(row['receipt']):raise Conflict('damaged native Feishu acceptance receipt')
                    return SendResult(success=True,message_id=row['receipt'],raw_response={'recipient_read_verified':False})
                if row['state'] in {'writing','uncertain'}:return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
                if row['state'] not in {'rejected','owner-retry-approved'} or row['receipt']:
                    raise Conflict('damaged Feishu delivery decision')
                if row['state']=='rejected' and row['error'] not in process.ERRORS|{'native-refused'}:
                    raise Conflict('damaged Feishu rejection diagnostic')
                if row['attempt']==attempt:return self.refusal(row['error'])
            if (previous and (previous[-1]['attempt']+1!=attempt or previous[-1]['state'] not in {'rejected','owner-retry-approved'})
                    or not previous and attempt!=1):raise Conflict('sequential approved Feishu outbox attempt required')
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if (len(previous)>=5 or self.db.execute('SELECT COUNT(*) FROM feishu_delivery_intents').fetchone()[0]>=65536
                    or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
                raise Conflict('private Feishu delivery journal full; owner recovery required')
            current();now=time.time();backoff=self.health()
            blocked=backoff['status']=='authentication-refused' or backoff['next_attempt']>now
            if blocked:
                error='authentication-refused' if backoff['status']=='authentication-refused' else 'rate-limited'
                self.db.execute('INSERT INTO feishu_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (delivery_id,attempt,self.native.connector,self.credential_scope,fingerprint,'rejected','',error,now,now))
                return self.refusal(error,max(1,math.ceil(backoff['next_attempt']-now)))
            if backoff['status']=='rate-limited':
                self.db.execute("UPDATE feishu_delivery_backoff SET status='ready',next_attempt=0,updated_at=? WHERE account_scope=?",(now,self.account_scope))
            self.db.execute('INSERT INTO feishu_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
                (delivery_id,attempt,self.native.connector,self.credential_scope,fingerprint,'writing','','',now,now))
            try:
                result=await process.reply(self.value,self.native.connector,current,blueprint)
                current()
                if result['state']=='confirmed':
                    self.db.execute("UPDATE feishu_delivery_intents SET state='confirmed',receipt=?,updated_at=? WHERE delivery_id=? AND attempt=?",
                        (result['message_id'],time.time(),delivery_id,attempt))
                    return SendResult(success=True,message_id=result['message_id'],raw_response={'recipient_read_verified':False})
                if result['state']=='rejected':
                    if result['error'] in {'authentication-refused','rate-limited'}:
                        latest=self.health()
                        state='authentication-refused' if latest['status']=='authentication-refused' else result['error']
                        deadline=max(latest['next_attempt'],time.time()+60) if state=='rate-limited' else 0
                        self.db.execute('UPDATE feishu_delivery_backoff SET status=?,next_attempt=?,updated_at=? WHERE account_scope=?',
                            (state,deadline,time.time(),self.account_scope))
                    self.db.execute("UPDATE feishu_delivery_intents SET state='rejected',error=?,updated_at=? WHERE delivery_id=? AND attempt=?",
                        (result['error'],time.time(),delivery_id,attempt))
                    return self.refusal(result['error'])
                self.db.execute("UPDATE feishu_delivery_intents SET state='uncertain',updated_at=? WHERE delivery_id=? AND attempt=?",
                    (time.time(),delivery_id,attempt))
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            except BaseException as error:
                self.db.execute("UPDATE feishu_delivery_intents SET state='uncertain',updated_at=? WHERE delivery_id=? AND attempt=?",
                    (time.time(),delivery_id,attempt))
                if isinstance(error,(asyncio.CancelledError,PermissionError)):raise
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})

    async def close(self):
        self.closed=True
        async with self.lock:pass
