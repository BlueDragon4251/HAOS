"""Prepared private HA native WebSocket handshake and bounded retained reader."""
import asyncio
import hashlib
import json
import math
from types import MethodType

from .gateway_homeassistant_ingress import snapshot,capture,dispatch_stored


class Rejected(ConnectionError):
    pass


def _object(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise Rejected('Home Assistant duplicate protocol field')
        value[key]=item
    return value


class Boundary:
    def __init__(self,adapter):
        from .gateway_mattermost import server_url
        try:self.server=server_url(adapter._hass_url)
        except ValueError:raise ValueError('Home Assistant requires an exact system-trusted HTTPS server') from None
        token=adapter._hass_token
        if not isinstance(token,str) or not 1<=len(token)<=8192 or any(ord(c)<33 or ord(c)>126 for c in token):
            raise ValueError('bounded private Home Assistant access token required')
        self.adapter=adapter
        self.token_digest=hashlib.sha256(token.encode()).digest()
        self.authority=snapshot(adapter._haos_native.policy(),adapter._haos_native.connector)
        if not self.authority['bindings']:raise PermissionError('explicit Home Assistant user/entity grants required before transport')
        adapter._hass_url=self.server
        self.endpoint=self.server.replace('https:','wss:',1)+'/api/websocket'
        self._target=self.endpoint
        self.sessions=set();self.sockets=set();self.socket=None;self.confirmed=False;self.subscription_id=None
        self.status='created';self.closed=False;self._handshake_seconds=30;self.retry_after=0

    def current(self):
        if (self.closed or self.adapter._hass_url!=self.server or not isinstance(self.adapter._hass_token,str)
                or hashlib.sha256(self.adapter._hass_token.encode()).digest()!=self.token_digest
                or snapshot(self.adapter._haos_native.policy(),self.adapter._haos_native.connector)!=self.authority):
            self.revoke('revoked')
            raise PermissionError('Home Assistant private identity or owner grant changed')

    def require_ready(self):
        self.current()
        if (not self.confirmed or self.socket is None or self.socket.closed or self.adapter._ws is not self.socket):
            raise PermissionError('Home Assistant has no current authenticated subscription')

    def revoke(self,status='disconnected'):
        self.confirmed=False;self.status=status;self.adapter._running=False

    def session(self):
        import aiohttp
        self.current()
        client=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=30))
        client._retry_connection=False
        original_request=client._request;original_ws=client.ws_connect
        async def request(method,url,**kwargs):
            self.current()
            if (method!='GET' or str(url)!=self.endpoint or kwargs.get('auth') is not None
                    or kwargs.get('proxy') is not None or kwargs.get('params')
                    or kwargs.get('ssl',True) is not True):
                raise PermissionError('Home Assistant request has no exact private WebSocket authority')
            kwargs['allow_redirects']=False
            return await original_request(method,self._target,**kwargs)
        async def websocket(url,**kwargs):
            self.current()
            if (str(url)!=self.endpoint or set(kwargs)-{'heartbeat','timeout'}
                    or kwargs.get('heartbeat')!=30 or kwargs.get('timeout')!=30):
                raise PermissionError('Home Assistant WebSocket target or TLS policy changed')
            kwargs.update(max_msg_size=65536,compress=0)
            raw=await original_ws(url,**kwargs)
            try:self.current()
            except BaseException:
                await raw.close();raise
            self.confirmed=False;self.subscription_id=None;self.status='authenticating'
            self.socket=_Socket(self,raw)
            self.sockets={socket for socket in self.sockets if not socket.closed}
            self.sockets.add(self.socket)
            return self.socket
        client._request=request;client.ws_connect=websocket
        self.sessions={session for session in self.sessions if not session.closed}
        self.sessions.add(client)
        return client

    async def close(self):
        self.closed=True;self.revoke('closed')
        sockets,self.sockets=self.sockets,set()
        for socket in sockets:await socket.close()
        sessions,self.sessions=self.sessions,set()
        for client in sessions:await client.close()


class _Socket:
    def __init__(self,boundary,raw):
        self.boundary=boundary;self.raw=raw;self.phase=0

    @property
    def closed(self):return self.raw.closed

    async def close(self):
        if self.boundary.socket is self:self.boundary.revoke('closed' if self.boundary.closed else 'disconnected')
        try:await asyncio.wait_for(self.raw.close(),5)
        except TimeoutError:self.raw._response.close()

    async def receive_json(self):
        boundary=self.boundary;boundary.current()
        if boundary.socket is not self:raise PermissionError('superseded Home Assistant private socket')
        try:value=await self.raw.receive_json(loads=lambda text:json.loads(text,object_pairs_hook=_object))
        except Exception:raise Rejected('Home Assistant private handshake is not valid bounded JSON') from None
        boundary.current()
        if boundary.socket is not self:raise PermissionError('superseded Home Assistant private socket')
        if not isinstance(value,dict):raise Rejected('Home Assistant private handshake has invalid shape')
        if self.phase==0 and value.get('type')=='auth_required':self.phase=1
        elif self.phase==2 and value.get('type')=='auth_ok':self.phase=3
        elif self.phase==2 and value.get('type')=='auth_invalid':
            boundary.status='authentication-refused'
            raise Rejected('Home Assistant private authentication refused')
        elif (self.phase==4 and value.get('type')=='result' and type(value.get('id')) is int
                and value['id']==boundary.subscription_id and value.get('success') is True):
            self.phase=5;boundary.confirmed=True;boundary.status='subscribed'
        else:raise Rejected('Home Assistant private handshake type or subscription acknowledgement does not match')
        return value

    async def send_json(self,value):
        boundary=self.boundary;boundary.current()
        if boundary.socket is not self:raise PermissionError('superseded Home Assistant private socket')
        if (self.phase==1 and isinstance(value,dict) and set(value)=={'type','access_token'}
                and value['type']=='auth' and value['access_token']==boundary.adapter._hass_token):self.phase=2
        elif (self.phase==3 and isinstance(value,dict) and set(value)=={'id','type','event_type'}
                and type(value['id']) is int and value['id']>0 and value['type']=='subscribe_events'
                and value['event_type']=='state_changed'):
            boundary.subscription_id=value['id'];self.phase=4
        else:raise PermissionError('Home Assistant WebSocket send is outside native auth/subscription capability')
        try:await self.raw.send_json(value)
        except Exception:raise Rejected('Home Assistant private handshake write interrupted') from None


def install(adapter):
    boundary=Boundary(adapter)
    native_connect=adapter._ws_connect
    adapter._haos_ha_transport=boundary
    adapter._new_session=boundary.session
    async def handshake_failed(self,*_args):
        boundary.revoke('handshake-refused');await self._cleanup_ws();return False
    async def connect(self,*args,**kwargs):
        try:
            boundary.retry_after=0
            boundary.current()
            async with asyncio.timeout(boundary._handshake_seconds):
                return await native_connect(*args,**kwargs)
        except asyncio.CancelledError:
            await self._cleanup_ws();boundary.revoke('cancelled');raise
        except Exception as error:
            limited=getattr(error,'status',None)==429
            if limited:
                try:delay=float((getattr(error,'headers',None) or {}).get('Retry-After','60'))
                except (ValueError,TypeError):delay=60
                boundary.retry_after=min(86400,max(1,delay)) if math.isfinite(delay) else 60
            reason=('handshake-timeout' if isinstance(error,TimeoutError) else 'revoked' if isinstance(error,PermissionError) else 'authentication-refused' if boundary.status=='authentication-refused' or getattr(error,'status',None) in {401,403}
                else 'rate-limited' if limited else 'handshake-refused')
            await self._cleanup_ws();boundary.revoke(reason);return False
    async def read(self):
        import aiohttp
        boundary.require_ready()
        socket=boundary.socket
        try:
            async for message in socket.raw:
                if message.type in {aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR}:break
                if boundary.socket is not socket:raise PermissionError('superseded Home Assistant reader has no current socket proof')
                boundary.require_ready()
                if message.type!=aiohttp.WSMsgType.TEXT:raise Rejected('Home Assistant private stream requires text JSON')
                try:value=json.loads(message.data,object_pairs_hook=_object)
                except (ValueError,TypeError):raise Rejected('Home Assistant private stream JSON invalid') from None
                if (not isinstance(value,dict) or value.get('type')!='event' or type(value.get('id')) is not int
                        or value['id']!=boundary.subscription_id or not isinstance(value.get('event'),dict)):
                    raise Rejected('Home Assistant private stream subscription source invalid')
                try:key=capture(self,value['event'],boundary.authority)
                except PermissionError:
                    boundary.current();continue
                if key is not None:await dispatch_stored(self,key)
        finally:
            if boundary.socket is socket:boundary.revoke()
    async def no_send(_self,*_args,**_kwargs):
        raise PermissionError('Home Assistant notifications require a separate explicit bounded delivery capability')
    adapter._handshake_failed=MethodType(handshake_failed,adapter)
    adapter._ws_connect=MethodType(connect,adapter)
    adapter._read_events=MethodType(read,adapter)
    adapter.send=MethodType(no_send,adapter)
    return adapter
