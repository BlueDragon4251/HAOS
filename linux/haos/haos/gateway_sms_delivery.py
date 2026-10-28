"""Actual pinned SMS formatter/HTTP sender with durable single-write authority."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import re
import time

from .gateway import digest
from .gateway_retry import retry_after
from .gateway_sms import MESSAGE
from .gateway_sms_rest import BASE

_ACTIVE=ContextVar('haos_sms_send',default=None)


class Publisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.value=deepcopy(adapter._haos_sms_value);self.db=adapter._haos_native.inbox.db
        self.original=type(adapter).send;self.client=None;self._target=None;self.lock=asyncio.Lock();self.closed=False
        self.db.execute('''CREATE TABLE IF NOT EXISTS sms_delivery_intents(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,fingerprint TEXT NOT NULL,
            state TEXT NOT NULL,receipt TEXT NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,attempt))''')
        self.db.execute("UPDATE sms_delivery_intents SET state='uncertain' WHERE state='writing'")

    def current(self,binding):
        self.adapter._haos_sms_check()
        if self.closed or not self.adapter.is_connected:raise PermissionError('connected private SMS identity required')
        policy=self.adapter._haos_native.policy();policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if binding['connector']!=self.adapter._haos_native.connector or 'read' not in binding['capabilities']:
            raise PermissionError('exact current SMS reply/read grant required')

    @asynccontextmanager
    async def post(self,url,*,data,headers):
        import aiohttp
        from plugins.platforms.sms.adapter import _basic_auth
        route=_ACTIVE.get()
        if route is None or route['publisher'] is not self:raise PermissionError('no native SMS write capability')
        self.current(route['binding'])
        if (url!=BASE+self.value['account_sid']+'/Messages.json' or route['dispatched']
                or headers!={'Authorization':_basic_auth(self.value['account_sid'],self.value['auth_token'])}
                or not isinstance(data,aiohttp.FormData) or data.is_multipart):
            raise PermissionError('native SMS endpoint, credentials or payload changed')
        fields={}
        for options,extra,value in data._fields:
            key=options.get('name')
            if key in fields or extra or type(value) is not str:raise PermissionError('plain exact native SMS form required')
            fields[key]=value
        if fields!={'From':self.value['from_number'],'To':route['binding']['chat'],'Body':route['body']}:
            raise PermissionError('SMS sender, recipient or body changed')
        if self.client is None:
            self.client=aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),timeout=aiohttp.ClientTimeout(total=30));self.client._retry_connection=False
        class Safe:
            status=502
            async def json(self):return {'message':'private SMS request outcome unknown'}
        safe=Safe();route['dispatched']=True
        try:
            async with self.client.post(self._target or url,data=data,headers=headers,allow_redirects=False) as response:
                route['status']=response.status;route['delay']=retry_after(response.headers.get('Retry-After'),private_values=[self.value['auth_token']])
                raw=bytearray()
                async for block in response.content.iter_chunked(4096):
                    raw.extend(block)
                    if len(raw)>65536:raise ValueError('bounded SMS response exceeded')
                if response.status==201:
                    from .gateway_line_ingress import _object
                    proof=json.loads(raw,object_pairs_hook=_object);sid=proof.get('sid') if isinstance(proof,dict) else None
                    if (not isinstance(sid,str) or not MESSAGE.fullmatch(sid) or proof.get('account_sid')!=self.value['account_sid']
                            or proof.get('from')!=self.value['from_number'] or proof.get('to')!=route['binding']['chat']
                            or proof.get('body')!=route['body'] or proof.get('status') not in {'accepted','queued','sending','sent','delivered'}
                            or self.adapter._haos_native.inbox.redactor.text(sid)!=sid):
                        raise ValueError('exact SMS server receipt required')
                    route['receipt']='sms_push_'+digest([sid,self.value['account_sid']])
                    async def receipt():return {'sid':sid}
                    safe.json=receipt
                safe.status=response.status
        except asyncio.CancelledError:raise
        except Exception:pass
        yield safe

    async def send(self,binding,identity,attempt,content):
        from gateway.platforms.base import SendResult
        if (not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity)
                or type(attempt) is not int or not 1<=attempt<=5):raise ValueError('exact bounded SMS outbox attempt required')
        binding=deepcopy(binding);self.current(binding)
        if not isinstance(content,str) or not content.strip() or len(content)>1800:
            return SendResult(success=False,error_kind='too_long',raw_response={'haos_delivery':'refused'})
        chunks=self.adapter.truncate_message(self.adapter.format_message(content))
        if not isinstance(chunks,list) or len(chunks)!=1 or not 1<=len(chunks[0])<=1600:
            return SendResult(success=False,error_kind='too_long',raw_response={'haos_delivery':'refused'})
        fingerprint=digest([digest(binding),self.value['account_sid'],self.value['auth_token'],content,chunks])
        async with self.lock:
            self.current(binding)
            old=self.db.execute('SELECT * FROM sms_delivery_intents WHERE delivery_id=? AND attempt=?',(identity,attempt)).fetchone()
            if old is not None:
                if old['fingerprint']!=fingerprint:raise PermissionError('SMS attempt changed authority or body')
                if old['state']=='confirmed' and re.fullmatch('sms_push_[0-9a-f]{64}',old['receipt']):
                    return SendResult(success=True,message_id=old['receipt'],raw_response={'recipient_receipt_verified':False})
                if old['state'] not in {'writing','uncertain'} or old['receipt']:raise ValueError('damaged SMS write journal')
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if self.db.execute('SELECT COUNT(*) FROM sms_delivery_intents').fetchone()[0]>=65536 or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024:
                raise PermissionError('private SMS delivery capacity reached')
            self.db.execute('INSERT INTO sms_delivery_intents VALUES(?,?,?,?,?,?)',(identity,attempt,fingerprint,'writing','',time.time()))
            route={'publisher':self,'binding':binding,'body':chunks[0],'dispatched':False,'status':None,'receipt':None,'delay':5}
            active=_ACTIVE.set(route);previous=self.adapter._http_session;self.adapter._http_session=self
            try:
                result=await self.original(self.adapter,binding['chat'],content)
                confirmed=result.success is True and route['receipt'] is not None
                self.db.execute('UPDATE sms_delivery_intents SET state=?,receipt=?,updated_at=? WHERE delivery_id=? AND attempt=?',
                    ('confirmed' if confirmed else 'uncertain',route['receipt'] if confirmed else '',time.time(),identity,attempt))
                if confirmed:return SendResult(success=True,message_id=route['receipt'],raw_response={'recipient_receipt_verified':False})
                if route['status'] in {400,401,403,404,413,429}:
                    kind={400:'bad_format',401:'forbidden',403:'forbidden',404:'not_found',413:'too_long',429:'rate_limited'}[route['status']]
                    return SendResult(success=False,error_kind=kind,retry_after=route['delay'],raw_response={'haos_delivery':'refused'})
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            except asyncio.CancelledError:raise
            except Exception:return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            finally:self.adapter._http_session=previous;_ACTIVE.reset(active)

    async def close(self):
        self.closed=True
        async with self.lock:
            if self.client is not None:await self.client.close();self.client=None
