"""Bounded private native Lark WS frames; transport authentication is separate."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from copy import copy
import json
import re
import threading
import time
from types import MethodType

from .gateway_feishu_admission import MAX_EVENT,bounded,finite,Refused
from .gateway_line_ingress import _object


class Bridge:
    """SDK thread waits for the real owning event loop's durable capture, never a volatile queue."""
    def __init__(self,loop,capture,current):
        if not callable(capture) or not callable(current) or loop.is_closed():raise PermissionError('live private capture loop required')
        self.loop=loop;self.capture=capture;self.current=current;self.thread=threading.get_ident()
    def commit(self,raw):
        self.current();receipt=self.capture(raw);self.current()
        if not isinstance(receipt,str) or not re.fullmatch('[0-9a-f]{64}',receipt):
            raise PermissionError('explicit durable private Feishu input receipt required')
    def _do_without_validation(self,raw):
        # The official SDK expects this seam; HAOS authenticates the socket and
        # independently validates source/account/policy inside capture().
        self.current()
        if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_EVENT:raise Refused('unsupported-content')
        if threading.get_ident()==self.thread:
            self.commit(raw);return None
        async def commit():
            self.commit(raw)
        if self.loop.is_closed():raise PermissionError('private Feishu capture loop closed')
        future=asyncio.run_coroutine_threadsafe(commit(),self.loop)
        try:future.result(timeout=5)
        except FutureTimeout:
            future.cancel();raise ConnectionError('durable Feishu capture deadline exceeded') from None
        self.current();return None


class FragmentCache:
    def __init__(self):self.records={};self.proofs={}
    def sweep(self):
        now=time.monotonic()
        for key,value in list(self.proofs.items()):
            if value['deadline']<now:self.records.pop(key,None);self.proofs.pop(key,None)
    def get(self,key):
        self.sweep();value=self.records.get(key)
        return None if value is None else copy(value)
    def set(self,key,value,ttl):
        self.sweep();proof=self.proofs.get(key)
        if (proof is None or type(ttl) is not int or ttl!=5 or not isinstance(value,list)
                or len(value)!=proof['sum'] or any(not isinstance(part,bytes) for part in value)
                or sum(map(len,value))>MAX_EVENT):raise Refused('unsupported-fragments')
        self.records[key]=copy(value)
    def remove(self,key):self.records.pop(key,None);self.proofs.pop(key,None)


def install(client,current,bridge,*,on_exit=None):
    """Keep actual SDK protobuf parsing, assembly, event dispatch and response encoding."""
    if not callable(current) or not isinstance(bridge,Bridge) or on_exit is not None and not callable(on_exit) or hasattr(client,'_haos_ws_frame_guard'):
        raise PermissionError('one private native WS frame guard required')
    from lark_oapi.ws.client import Client,Frame,FrameType,MessageType
    from lark_oapi.ws.model import ClientConfig
    original_message=Client._handle_message;original_combine=Client._combine;original_configure=Client._configure
    old_cache=client._cache
    if hasattr(old_cache,'_cron'):old_cache._cron.cancel()
    cache=FragmentCache();client._cache=cache;client._event_handler=bridge;client._auto_reconnect=False
    client._haos_ws_frame_guard=True;client._haos_ws_tokens=64.;client._haos_ws_last=time.monotonic()
    def configure(self,conf):
        current();values={}
        for name,field,default,low,high in [('ReconnectCount','_reconnect_count',-1,-1,100),
                ('ReconnectInterval','_reconnect_interval',120,1,3600),('ReconnectNonce','_reconnect_nonce',30,0,120),
                ('PingInterval','_ping_interval',120,1,3600)]:
            value=getattr(conf,name,None)
            if value is None:value=getattr(self,field,default)
            if type(value) is not int or not low<=value<=high:raise Refused('unsupported-ws-configuration')
            values[name]=value
        original_configure(self,ClientConfig(values));current()
    def combine(self,key,total,sequence,payload):
        current();proof=cache.proofs.get(key)
        if proof is None or proof['sum']!=total:raise Refused('unsupported-fragments')
        result=original_combine(self,key,total,sequence,payload)
        if result is not None:
            expected=b''.join(proof['parts'][index] for index in range(total))
            if result!=expected:raise Refused('unsupported-fragments')
            cache.remove(key)
        current();return result
    async def message(self,raw):
        current();cache.sweep()
        if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_EVENT+16384:raise Refused('unsupported-frame')
        now=time.monotonic();self._haos_ws_tokens=min(64.,self._haos_ws_tokens+(now-self._haos_ws_last)*16)
        self._haos_ws_last=now;cost=max(1,(len(raw)+65535)//65536)
        if self._haos_ws_tokens<cost:raise Refused('ws-rate-limited')
        self._haos_ws_tokens-=cost
        frame=Frame()
        try:frame.ParseFromString(raw)
        except Exception:raise Refused('unsupported-frame') from None
        if not frame.IsInitialized():raise Refused('unsupported-frame')
        headers={}
        if len(frame.headers)>32 or len(frame.payload)>MAX_EVENT:raise Refused('unsupported-frame')
        for header in frame.headers:
            if (header.key in headers or not re.fullmatch('[a-z_]{1,64}',header.key)
                    or len(header.value)>1024 or any(ord(char)<32 for char in header.value)):
                raise Refused('unsupported-frame')
            headers[header.key]=header.value
        if frame.method==FrameType.CONTROL.value:
            if headers.get('type') not in {MessageType.PING.value,MessageType.PONG.value}:raise Refused('unsupported-frame')
            if frame.payload:
                if headers['type']!=MessageType.PONG.value or len(frame.payload)>4096:raise Refused('unsupported-frame')
                try:conf=json.loads(frame.payload.decode(),object_pairs_hook=_object,parse_constant=finite);bounded(conf)
                except (ValueError,UnicodeError,RecursionError):raise Refused('unsupported-frame') from None
                if not isinstance(conf,dict) or set(conf)-{'ReconnectCount','ReconnectInterval','ReconnectNonce','PingInterval'}:
                    raise Refused('unsupported-ws-configuration')
                # Validate before actual SDK JSON decode/configuration.
                for key,value in conf.items():
                    limits={'ReconnectCount':(-1,100),'ReconnectInterval':(1,3600),'ReconnectNonce':(0,120),'PingInterval':(1,3600)}
                    if type(value) is not int or not limits[key][0]<=value<=limits[key][1]:raise Refused('unsupported-ws-configuration')
        elif frame.method==FrameType.DATA.value:
            required={'message_id','trace_id','sum','seq','type'}
            if not required<=set(headers) or headers['type']!=MessageType.EVENT.value:raise Refused('unsupported-frame')
            if (not re.fullmatch('[A-Za-z0-9_.:-]{1,256}',headers['message_id'])
                    or not re.fullmatch('[A-Za-z0-9_.:-]{1,256}',headers['trace_id'])
                    or not re.fullmatch('[1-9][0-9]?',headers['sum']) or not re.fullmatch('0|[1-9][0-9]?',headers['seq'])):
                raise Refused('unsupported-fragments')
            total=int(headers['sum']);sequence=int(headers['seq'])
            if not 1<=total<=16 or not 0<=sequence<total or not frame.payload:raise Refused('unsupported-fragments')
            if total>1:
                key=headers['message_id'];proof=cache.proofs.get(key)
                if proof is None:
                    if len(cache.proofs)>=32:raise Refused('fragment-capacity')
                    proof={'sum':total,'trace':headers['trace_id'],'parts':{},'deadline':time.monotonic()+5};cache.proofs[key]=proof
                if proof['sum']!=total or proof['trace']!=headers['trace_id']:raise Refused('fragment-conflict')
                if sequence in proof['parts'] and proof['parts'][sequence]!=frame.payload:raise Refused('fragment-conflict')
                size=sum(len(part) for index,part in proof['parts'].items() if index!=sequence)+len(frame.payload)
                if size>MAX_EVENT:raise Refused('unsupported-fragments')
                proof['parts'][sequence]=bytes(frame.payload)
            elif headers['message_id'] in cache.proofs:raise Refused('fragment-conflict')
        else:raise Refused('unsupported-frame')
        await original_message(self,raw);current()
    async def receive(self):
        try:
            while True:
                current()
                if self._conn is None:raise ConnectionError('private socket closed')
                # Inline dispatch provides backpressure; the SDK default starts
                # one unbounded task per received frame before admission.
                raw=await self._conn.recv();await self._handle_message(raw)
        except asyncio.CancelledError:raise
        except Exception as error:
            self._haos_ws_failure=error.reason if isinstance(error,Refused) else 'transport-unavailable'
            try:await self._disconnect()
            finally:
                if on_exit is not None:on_exit(self._haos_ws_failure)
    client._receive_message_loop=MethodType(receive,client)
    client._configure=MethodType(configure,client);client._combine=MethodType(combine,client)
    client._handle_message=MethodType(message,client)
    return client
