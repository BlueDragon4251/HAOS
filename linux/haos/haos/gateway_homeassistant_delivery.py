"""Prepared native HA notifications with explicit shared audience and remote proof."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import math
import re
from types import MethodType

from .gateway import digest

_ACTIVE=ContextVar('haos_homeassistant_notification',default=None)
_ID=re.compile(r'[0-9a-f]{64}\Z')


class Publisher:
    def __init__(self,adapter):
        from .gateway_mattermost import server_url
        self.adapter=adapter;self.server=server_url(adapter._hass_url);self._target=self.server
        adapter._hass_url=self.server
        token=adapter._hass_token
        if not isinstance(token,str) or not 1<=len(token)<=8192 or any(ord(c)<33 or ord(c)>126 for c in token):
            raise ValueError('private bounded Home Assistant token required')
        self.token_digest=hashlib.sha256(token.encode()).digest()
        self.original=type(adapter).send;self.client=None;self.closed=False
        self.witness=NotificationWitness(self)
        adapter._rest_session=self
        async def deny(_self,*_args,**_kwargs):
            raise PermissionError('Home Assistant native send requires explicit shared-audience outbox capability')
        adapter.send=MethodType(deny,adapter)

    def current(self,binding):
        if (self.closed or self.adapter._hass_url!=self.server or not isinstance(self.adapter._hass_token,str)
                or hashlib.sha256(self.adapter._hass_token.encode()).digest()!=self.token_digest):
            raise PermissionError('Home Assistant publisher identity changed or closed')
        native=self.adapter._haos_native;policy=native.policy()
        policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if (policy.connectors.get(binding['connector'],{}).get('platform')!='homeassistant'
                or binding['connector']!=native.connector or binding.get('homeassistant_shared_notifications') is not True
                or 'read' not in binding['capabilities'] or binding['scope'] or binding['thread']):
            raise PermissionError('explicit owner approval of notifications visible to all instance users required')

    @asynccontextmanager
    async def post(self,url,*,headers,json,timeout):
        import aiohttp
        route=_ACTIVE.get()
        if route is None or route['publisher'] is not self:raise PermissionError('no private notification capability')
        self.current(route['binding'])
        if (url!=self.server+'/api/services/persistent_notification/create'
                or headers!={'Authorization':'Bearer '+self.adapter._hass_token,'Content-Type':'application/json'}
                or json!={'title':'Hermes Agent','message':route['message']} or getattr(timeout,'total',None)!=10):
            raise PermissionError('native notification changed endpoint, payload or authentication')
        if self.client is None:
            self.client=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=10))
            self.client._retry_connection=False
        route['dispatched']=True
        class SafeResponse:
            status=502
            async def text(self):return 'private Home Assistant delivery outcome unknown'
        safe=SafeResponse()
        try:
            async with self.client.post(self._target+'/api/services/persistent_notification/create',
                    headers=headers,json={**json,'notification_id':route['notification_id']},allow_redirects=False,timeout=timeout) as response:
                route['status']=response.status
                try:delay=float(response.headers.get('Retry-After','5'))
                except ValueError:delay=5
                route['retry_after']=min(86400,max(1,delay)) if math.isfinite(delay) else 5
                length=0
                async for chunk in response.content.iter_chunked(4096):
                    length+=len(chunk)
                    if length>65536:raise ValueError('bounded native notification response exceeded')
                safe.status=response.status
        except asyncio.CancelledError:raise
        except Exception:pass
        yield safe

    async def send(self,binding,delivery_id,content):
        from gateway.platforms.base import SendResult
        binding=deepcopy(binding);self.current(binding)
        if not isinstance(delivery_id,str) or not _ID.fullmatch(delivery_id):
            raise ValueError('stable actual outbox delivery ID required')
        if not isinstance(content,str) or not content or len(content)>65536 or len(content.encode())>65536:
            return SendResult(success=False,error_kind='too_long',raw_response={'haos_delivery':'refused'})
        receipts=[]
        for offset in range(0,len(content),4096):
            part=content[offset:offset+4096]
            marker='haos_'+digest([digest(binding),delivery_id,offset])[:32]
            route={'publisher':self,'binding':binding,'notification_id':marker,'message':part,
                'dispatched':False,'status':None,'retry_after':5}
            token=_ACTIVE.set(route)
            try:
                self.current(binding)
                result=await self.original(self.adapter,binding['chat'],part)
                # Native's random UUID is never a remote notification receipt.
                verified=(result.success is True and route['status'] in {200,201,202,204}
                    and await self.witness.verify(binding,marker,part))
            except asyncio.CancelledError:raise
            except Exception:verified=False
            finally:_ACTIVE.reset(token)
            if verified:receipts.append(marker);continue
            if receipts:return SendResult(success=False,raw_response={'partial_overflow':True,'haos_chunk_receipts':receipts})
            code=route['status']
            if code in {400,401,403,404,413,429}:
                kind={400:'bad_format',401:'forbidden',403:'forbidden',404:'not_found',413:'too_long',429:'rate_limited'}[code]
                return SendResult(success=False,error_kind=kind,retry_after=route['retry_after'],raw_response={'haos_delivery':'refused'})
            return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
        return SendResult(success=True,message_id=receipts[-1],raw_response={'haos_chunk_receipts':receipts})

    async def close(self):
        self.closed=True
        try:await self.witness.close()
        finally:
            client,self.client=self.client,None
            if client is not None:await client.close()


class NotificationWitness:
    def __init__(self,publisher):
        from gateway.config import PlatformConfig
        from plugins.platforms.homeassistant.adapter import HomeAssistantAdapter
        from .gateway_homeassistant_transport import install
        self.publisher=publisher
        adapter=HomeAssistantAdapter(PlatformConfig(enabled=True,token=publisher.adapter._hass_token,
            extra={'url':publisher.server,'watch_entities':[],'watch_all':False}))
        adapter._haos_native=publisher.adapter._haos_native
        self.adapter=install(adapter);self.boundary=adapter._haos_ha_transport
        self.lock=asyncio.Lock()

    async def verify(self,binding,notification_id,message):
        from .gateway_homeassistant_transport import _object
        import json
        async with self.lock:
            self.publisher.current(binding)
            async with asyncio.timeout(15):
                if not self.boundary.confirmed:
                    if not await self.adapter._ws_connect():return False
                self.boundary.require_ready()
                request_id=self.adapter._next_id()
                # Only this fixed read is available to the private witness;
                # no result list or unrelated notification escapes the broker.
                await self.boundary.socket.raw.send_json({'id':request_id,'type':'persistent_notification/get'})
                for _ in range(128):
                    value=await self.boundary.socket.raw.receive_json(loads=lambda text:json.loads(text,object_pairs_hook=_object))
                    self.publisher.current(binding);self.boundary.require_ready()
                    if not isinstance(value,dict):return False
                    if value.get('type')=='event' and value.get('id')==self.boundary.subscription_id:continue
                    if (value.get('type')!='result' or type(value.get('id')) is not int or value['id']!=request_id
                            or value.get('success') is not True or not isinstance(value.get('result'),list)
                            or len(value['result'])>4096):return False
                    matches=[row for row in value['result'] if isinstance(row,dict) and row.get('notification_id')==notification_id]
                    return (len(matches)==1 and matches[0].get('message')==message and matches[0].get('title')=='Hermes Agent')
            return False

    async def close(self):await self.boundary.close()
