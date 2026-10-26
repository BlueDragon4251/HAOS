"""Prepared native LINE push with independent grants and persistent write intent."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
import re
import time
from types import MethodType
import uuid

from .gateway import digest
from .gateway_retry import retry_after

_ACTIVE=ContextVar('haos_line_push',default=None)
_URL='https://api.line.me/v2/bot/message/push'
_HASH=re.compile(r'[0-9a-f]{64}\Z')


class Publisher:
    def __init__(self,adapter):
        from plugins.platforms.line.adapter import _LineClient
        self.adapter=adapter;self.token=adapter.channel_access_token
        if not isinstance(self.token,str) or not 16<=len(self.token)<=8192 or any(ord(c)<33 or ord(c)>126 for c in self.token):
            raise ValueError('bounded private LINE access token required')
        self.original=type(adapter).send;self.native=_LineClient(self.token);self.native._session=self.session
        self._target=_URL;self.client=None;self.lock=asyncio.Lock();self.closed=False
        self.db=adapter._haos_native.inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS line_delivery_intents(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,fingerprint TEXT NOT NULL,
            state TEXT NOT NULL,receipt TEXT NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,attempt))''')
        self.db.execute("UPDATE line_delivery_intents SET state='uncertain' WHERE state='writing'")
        async def deny(_self,*_args,**_kwargs):raise PermissionError('native LINE send requires current outbox capability')
        adapter.send=MethodType(deny,adapter)

    def current(self,binding):
        native=self.adapter._haos_native;policy=native.policy()
        if self.closed or self.adapter.channel_access_token!=self.token:raise PermissionError('LINE publisher closed or identity changed')
        policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if (binding['connector']!=native.connector or policy.connectors.get(native.connector,{}).get('platform')!='line'
                or 'read' not in binding['capabilities']):raise PermissionError('current LINE read grant required')

    @asynccontextmanager
    async def session(self,timeout):
        route=_ACTIVE.get()
        if route is None or route['publisher'] is not self or timeout!=15.0:raise PermissionError('no native LINE request capability')
        yield self

    @asynccontextmanager
    async def post(self,url,*,headers,json):
        import aiohttp
        route=_ACTIVE.get()
        if route is None or route['publisher'] is not self:raise PermissionError('no native LINE push capability')
        self.current(route['binding'])
        if (url!=_URL or headers!={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}
                or json!={'to':route['binding']['chat'],'messages':route['messages']} or route['dispatched']):
            raise PermissionError('native LINE endpoint, credentials or payload changed')
        if self.client is None:
            self.client=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=15))
            self.client._retry_connection=False
        class SafeResponse:
            status=502
            async def text(self):return 'private LINE request outcome unknown'
        safe=SafeResponse();route['dispatched']=True
        try:
            async with self.client.post(self._target,headers=headers,json=json,allow_redirects=False) as response:
                route['status']=response.status
                route['retry_after']=retry_after(response.headers.get('Retry-After'),private_values=[self.token])
                body=bytearray()
                async for part in response.content.iter_chunked(4096):
                    body.extend(part)
                    if len(body)>65536:raise ValueError('bounded LINE response exceeded')
                if response.status==200:
                    from .gateway_line_ingress import _object
                    import json as codec
                    proof=codec.loads(body,object_pairs_hook=_object)
                    request_id=response.headers.get('X-Line-Request-Id','')
                    if str(uuid.UUID(request_id))!=request_id:raise ValueError('exact LINE request ID required')
                    messages=proof.get('sentMessages') if isinstance(proof,dict) else None
                    if (not isinstance(messages,list) or len(messages)!=len(route['messages'])
                            or any(not isinstance(m,dict) or not isinstance(m.get('id'),str)
                                or not re.fullmatch(r'[1-9][0-9]{0,31}',m['id']) for m in messages)
                            or len({m['id'] for m in messages})!=len(messages)):
                        raise ValueError('complete distinct LINE message receipts required')
                    from .redaction import Redactor
                    private=Redactor([self.token,self.adapter.channel_secret])
                    ids=[m['id'] for m in messages]
                    if any(private.text(value)!=value for value in ids+[request_id]):raise ValueError('private LINE receipt refused')
                    route['receipt']='line_push_'+digest([request_id,ids])
                safe.status=response.status
        except asyncio.CancelledError:raise
        except Exception:pass
        yield safe

    async def send(self,binding,delivery_id,attempt,content):
        from gateway.platforms.base import SendResult
        from plugins.platforms.line.adapter import _text_messages,strip_markdown_preserving_urls
        if (not isinstance(delivery_id,str) or not _HASH.fullmatch(delivery_id)
                or type(attempt) is not int or not 1<=attempt<=5):raise ValueError('actual LINE outbox ID and bounded attempt required')
        binding=deepcopy(binding);self.current(binding)
        if not isinstance(content,str) or not content.strip() or len(content.encode())>65536:
            return SendResult(success=False,error_kind='too_long',raw_response={'haos_delivery':'refused'})
        messages=_text_messages(content)
        # One native push only. A later batch may not consume an unjournaled side effect.
        if (not 1<=len(messages)<=5
                or any(len(m['text'].encode('utf-16-le'))//2>5000 for m in messages)
                or ''.join(strip_markdown_preserving_urls(content).split())!=''.join(''.join(m['text'].split()) for m in messages)):
            return SendResult(success=False,error_kind='too_long',raw_response={'haos_delivery':'refused'})
        fingerprint=digest([digest(binding),self.token,content,messages])
        async with self.lock:
            self.current(binding)
            old=self.db.execute('SELECT * FROM line_delivery_intents WHERE delivery_id=? AND attempt=?',(delivery_id,attempt)).fetchone()
            if old is not None:
                if old['fingerprint']!=fingerprint:raise PermissionError('LINE outbox attempt changed content or authority')
                if (old['state'] not in {'writing','uncertain','confirmed'}
                        or not isinstance(old['receipt'],str)
                        or old['state']=='confirmed' and not re.fullmatch(r'line_push_[0-9a-f]{64}',old['receipt'])
                        or old['state']!='confirmed' and old['receipt']):raise ValueError('invalid private LINE delivery journal')
                if old['state']=='confirmed':return SendResult(success=True,message_id=old['receipt'],raw_response={'recipient_receipt_verified':False})
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if (self.db.execute('SELECT COUNT(*) FROM line_delivery_intents').fetchone()[0]>=65536
                    or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
                raise PermissionError('private LINE delivery journal capacity reached')
            self.db.execute('INSERT INTO line_delivery_intents VALUES(?,?,?,?,?,?)',
                (delivery_id,attempt,fingerprint,'writing','',time.time()))
            route={'publisher':self,'binding':binding,'messages':messages,'dispatched':False,'status':None,'receipt':None,'retry_after':5}
            token=_ACTIVE.set(route);previous=self.adapter._client
            try:
                self.adapter._client=self.native
                if self.adapter._reply_tokens or self.adapter._pending_buttons:raise PermissionError('unapproved LINE reply/postback capability')
                native=await self.original(self.adapter,binding['chat'],content)
                confirmed=native.success is True and route['receipt'] is not None
                state='confirmed' if confirmed else 'uncertain'
                self.db.execute('UPDATE line_delivery_intents SET state=?,receipt=?,updated_at=? WHERE delivery_id=? AND attempt=?',
                    (state,route['receipt'] if confirmed else '',time.time(),delivery_id,attempt))
                if confirmed:return SendResult(success=True,message_id=route['receipt'],raw_response={'recipient_receipt_verified':False})
                status=route['status']
                if status in {400,401,403,404,413,429}:
                    kind={400:'bad_format',401:'forbidden',403:'forbidden',404:'not_found',413:'too_long',429:'rate_limited'}[status]
                    return SendResult(success=False,error_kind=kind,retry_after=route['retry_after'],raw_response={'haos_delivery':'refused'})
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            except asyncio.CancelledError:raise
            except Exception:return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            finally:self.adapter._client=previous;_ACTIVE.reset(token)

    async def close(self):
        self.closed=True
        async with self.lock:
            if self.client is not None:await self.client.close();self.client=None
