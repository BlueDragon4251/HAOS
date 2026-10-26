"""Prepared bounded TLS/IRCv3 subscription; public setup and delivery stay disabled."""
import asyncio
import re
import ssl
import time
from types import MethodType

from .gateway import digest
from .gateway_irc_ingress import REQUIRED_CAPS,snapshot,capture,dispatch_stored


class Rejected(ConnectionError):
    pass


def credentials(value):
    required={'server','port','nickname','channel'}
    if not isinstance(value,dict) or not required<=set(value)<=required|{'server_password','nickserv_password'}:
        raise ValueError('exact private IRC connection fields required')
    host=value['server'];port=value['port'];nick=value['nickname'];channel=value['channel']
    if (not isinstance(host,str) or len(host)>253 or host!=host.lower()
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in host.split('.'))
            or type(port) is not int or not 1<=port<=65535
            or not isinstance(nick,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,29}',nick)
            or not isinstance(channel,str) or not re.fullmatch(r'#[a-z0-9][a-z0-9_-]{0,63}',channel)):
        raise ValueError('bounded canonical IRC hostname, port, nickname and exact channel required')
    for field in ('server_password','nickserv_password'):
        secret=value.get(field,'')
        if not isinstance(secret,str) or len(secret)>4096 or any(ord(c)<33 or ord(c)>126 for c in secret):
            raise ValueError('bounded private IRC credential without protocol controls required')
    # Do not send a password to a potentially unregistered NickServ nickname.
    # Server-authenticated SASL must be implemented before accepting this option.
    if value.get('nickserv_password'):raise ValueError('IRC NickServ credential requires a reviewed authenticated service path')
    return dict(value)


class Boundary:
    def __init__(self,adapter,value):
        self.value=credentials(value)
        self.adapter=adapter
        self.server=f"{self.value['server']}:{self.value['port']}"
        self.authority=snapshot(adapter._haos_native.policy(),adapter._haos_native.connector,self.server)
        if not self.authority['bindings']:raise PermissionError('exact IRC account grants required')
        if any(b['chat']!=self.value['channel'] for b in adapter._haos_native.policy().bindings.values()
                if b['connector']==adapter._haos_native.connector):
            raise PermissionError('IRC channel differs from exact owner grant')
        self.identity=digest(self.value)
        self.reader=None;self.writer=None;self.confirmed=False;self.closed=False
        self.status='created';self.capabilities=frozenset();self._handshake_seconds=30
        self._open=asyncio.open_connection

    def current(self):
        if (self.closed or digest(self.value)!=self.identity
                or self.adapter.server!=self.value['server'] or self.adapter.port!=self.value['port']
                or self.adapter.nickname!=self.value['nickname'] or self.adapter.channel!=self.value['channel']
                or self.adapter.use_tls is not True
                or self.adapter.server_password!=self.value.get('server_password','')
                or self.adapter.nickserv_password
                or snapshot(self.adapter._haos_native.policy(),self.adapter._haos_native.connector,self.server)!=self.authority):
            self.confirmed=False;self.status='revoked'
            if self.writer is not None:self.writer.close()
            raise PermissionError('IRC private connection or owner authority changed')

    async def write(self,line):
        self.current()
        if self.writer is None or self.writer.is_closing():raise Rejected('IRC connection unavailable')
        if not isinstance(line,str) or len(line.encode())>4096 or any(c in line for c in '\r\n\0'):
            raise Rejected('invalid IRC control frame')
        allowed={'CAP LS 302','CAP REQ :'+ ' '.join(sorted(REQUIRED_CAPS)),'CAP END',
            'NICK '+self.value['nickname'],'USER '+self.value['nickname']+' 0 * :HAOS private gateway',
            'JOIN '+self.value['channel']}
        if self.value.get('server_password'):allowed.add('PASS '+self.value['server_password'])
        if line not in allowed and not line.startswith('PONG :'):
            raise PermissionError('IRC application writes require separate reviewed outbox authority')
        self.writer.write((line+'\r\n').encode());await asyncio.wait_for(self.writer.drain(),10)

    async def read(self,timeout):
        self.current()
        if self.reader is None:raise Rejected('IRC connection unavailable')
        try:raw=await asyncio.wait_for(self.reader.readuntil(b'\r\n'),timeout)
        except (asyncio.IncompleteReadError,asyncio.LimitOverrunError):raise Rejected('IRC framing interrupted or oversized') from None
        self.current()
        if len(raw)>4098:raise Rejected('IRC frame exceeds bound')
        try:return raw[:-2].decode('utf-8',errors='strict')
        except UnicodeError:raise Rejected('IRC frame is not UTF-8') from None

    async def control(self,raw):
        from plugins.platforms.irc.adapter import _parse_irc_message
        msg=_parse_irc_message(raw)
        if msg['command']=='PING':
            if len(msg['params'])!=1:raise Rejected('invalid IRC keepalive')
            await self.write('PONG :'+msg['params'][0]);return True
        if msg['command']=='ERROR' or re.fullmatch(r'[45][0-9]{2}',msg['command']):
            raise Rejected('IRC server refused registration or subscription')
        return False

    async def connect(self):
        self.current()
        if self.writer is not None:raise Rejected('IRC connection already active')
        self.status='connecting';self.confirmed=False;self.capabilities=frozenset()
        context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
        if context.check_hostname is not True or context.verify_mode!=ssl.CERT_REQUIRED:
            raise PermissionError('system-trusted IRC TLS and hostname verification required')
        try:
            self.reader,self.writer=await asyncio.wait_for(self._open(self.value['server'],self.value['port'],
                ssl=context,server_hostname=self.value['server'],limit=4098),self._handshake_seconds)
            self.current()
            if self.writer.get_extra_info('ssl_object') is None:raise Rejected('IRC TLS missing')
            await self.write('CAP LS 302')
            if self.value.get('server_password'):await self.write('PASS '+self.value['server_password'])
            await self.write('NICK '+self.value['nickname'])
            await self.write('USER '+self.value['nickname']+' 0 * :HAOS private gateway')
            from plugins.platforms.irc.adapter import _parse_irc_message
            deadline=time.monotonic()+self._handshake_seconds;offered=set();requested=False;registered=False
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise Rejected('IRC handshake timed out')
                raw=await self.read(remaining)
                if await self.control(raw):continue
                msg=_parse_irc_message(raw);params=msg['params'];command=msg['command']
                if command=='CAP':
                    if len(params)<3:raise Rejected('invalid IRC capability response')
                    operation=params[1]
                    if operation=='LS' and not requested:
                        offered.update(part.split('=',1)[0] for part in params[-1].split())
                        if len(params)==4 and params[2]=='*':continue
                        if not REQUIRED_CAPS<=offered:raise Rejected('IRC server lacks required account capabilities')
                        await self.write('CAP REQ :'+ ' '.join(sorted(REQUIRED_CAPS)));requested=True
                    elif operation=='ACK' and requested and not self.capabilities:
                        acknowledged=frozenset(params[-1].split())
                        if acknowledged!=REQUIRED_CAPS:raise Rejected('IRC account capabilities were not confirmed')
                        self.capabilities=acknowledged;await self.write('CAP END')
                    else:raise Rejected('IRC capability negotiation refused or changed')
                elif command=='001':
                    if not self.capabilities or registered or not params or params[0]!=self.value['nickname']:
                        raise Rejected('IRC registration preceded verified capabilities or changed nickname')
                    registered=True;await self.write('JOIN '+self.value['channel'])
                elif command=='JOIN':
                    if (not registered or msg['prefix'].split('!',1)[0]!=self.value['nickname']
                            or params!=[self.value['channel']]):raise Rejected('IRC subscription target changed')
                    self.confirmed=True;self.status='streaming';self.adapter._mark_connected();return True
                elif command=='PRIVMSG':raise Rejected('IRC message arrived before authenticated subscription')
        except BaseException:
            if self.status!='revoked':self.status='transport-unavailable'
            await self.disconnect();raise

    async def receive(self):
        try:
            while True:
                self.current()
                if not self.confirmed:raise Rejected('IRC has no current authenticated subscription')
                try:raw=await self.read(.5)
                except asyncio.TimeoutError:continue
                if await self.control(raw):continue
                from plugins.platforms.irc.adapter import _parse_irc_message
                msg=_parse_irc_message(raw)
                if msg['command']=='CAP':raise Rejected('IRC account capability changed during subscription')
                if (msg['command']=='KICK' and len(msg['params'])>=2
                        and msg['params'][0]==self.value['channel'] and msg['params'][1]==self.value['nickname']
                        or msg['command'] in {'PART','QUIT','NICK'}
                        and msg['prefix'].split('!',1)[0]==self.value['nickname']):
                    raise Rejected('IRC subscription or local identity was withdrawn')
                # Tagged application frames are admitted independently of the
                # native nickname allowlist; unpaired accounts are never sent on.
                if raw.startswith('@'):
                    try:key=capture(self.adapter,raw,self.authority,self.capabilities)
                    except PermissionError:self.current();continue
                    if key is not None:await dispatch_stored(self.adapter,key)
        finally:
            self.confirmed=False;self.adapter._mark_disconnected();await self.disconnect()

    async def disconnect(self):
        self.confirmed=False;self.adapter._mark_disconnected()
        writer,self.writer=self.writer,None;self.reader=None
        if writer is not None:
            writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),5)
            except (OSError,asyncio.TimeoutError):pass
        if self.status!='revoked':self.status='disconnected'


def install(adapter,value):
    boundary=Boundary(adapter,value)
    async def deny(_self,*_args,**_kwargs):raise PermissionError('prepared IRC has no reviewed outbox authority')
    adapter._haos_irc_transport=boundary
    # Native raw/standalone sends cannot bypass the later reviewed outbox path.
    adapter._send_raw=MethodType(deny,adapter)
    adapter.send=MethodType(deny,adapter)
    return boundary
