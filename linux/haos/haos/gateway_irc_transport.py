"""Bounded TLS/IRCv3 subscription behind independent exact owner authority."""
import asyncio
import base64
import re
import socket
import ssl
import time
from types import MethodType

from .gateway import digest
from .gateway_irc_ingress import REQUIRED_CAPS,snapshot,capture,dispatch_stored


DIAGNOSTICS=frozenset({'protocol-refused','required-capabilities','unsupported-case-mapping','nickname-in-use',
    'channel-full','channel-invite-required','channel-banned','channel-key-required','channel-not-found',
    'account-required','channel-forwarding-refused','authentication-refused','rate-limited','permission-revoked',
    'tls-certificate','tls-protocol','dns','connection-refused','timeout','connection-lost'})


class Rejected(ConnectionError):
    def __init__(self,message,*,code='protocol-refused'):
        super().__init__(message)
        self.code=code if code in DIAGNOSTICS else 'protocol-refused'


def diagnostic(error):
    if isinstance(error,ssl.SSLCertVerificationError):return 'tls-certificate'
    if isinstance(error,ssl.SSLError):return 'tls-protocol'
    if isinstance(error,socket.gaierror):return 'dns'
    if isinstance(error,ConnectionRefusedError):return 'connection-refused'
    if isinstance(error,TimeoutError):return 'timeout'
    if isinstance(error,AuthenticationRejected):return 'authentication-refused'
    if isinstance(error,RateLimited):return 'rate-limited'
    if isinstance(error,PermissionError):return 'permission-revoked'
    return error.code if isinstance(error,Rejected) else 'connection-lost'


class AuthenticationRejected(Rejected):
    pass


class RateLimited(Rejected):
    retry_after=60


def credentials(value):
    required={'server','port','nickname','channel'}
    if not isinstance(value,dict) or not required<=set(value)<=required|{'server_password','nickserv_password','sasl_username','sasl_password','channel_password'}:
        raise ValueError('exact private IRC connection fields required')
    host=value['server'];port=value['port'];nick=value['nickname'];channel=value['channel']
    if (not isinstance(host,str) or len(host)>253 or host!=host.lower()
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in host.split('.'))
            or type(port) is not int or not 1<=port<=65535
            or not isinstance(nick,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,29}',nick)
            or not isinstance(channel,str) or not re.fullmatch(r'[&#][a-z0-9][a-z0-9_-]{0,63}',channel)):
        raise ValueError('bounded canonical IRC hostname, port, nickname and exact channel required')
    for field in ('server_password','nickserv_password'):
        secret=value.get(field,'')
        if not isinstance(secret,str) or len(secret)>4096 or any(ord(c)<33 or ord(c)>126 for c in secret):
            raise ValueError('bounded private IRC credential without protocol controls required')
    username=value.get('sasl_username','');password=value.get('sasl_password','')
    if (not isinstance(username,str) or not isinstance(password,str)
            or bool(username)!=bool(password)
            or username and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',username)
            or len(password.encode())>4096 or any(ord(c)<32 or ord(c)==127 for c in password)):
        raise ValueError('paired bounded IRC SASL account and private password required')
    # Do not send a password to a potentially unregistered NickServ nickname.
    # SASL authenticates to the TLS server; this option instead addresses a nick.
    if value.get('nickserv_password'):raise ValueError('IRC NickServ credential requires a reviewed authenticated service path')
    channel_key=value.get('channel_password','')
    if (not isinstance(channel_key,str) or len(channel_key)>128
            or any(ord(c)<33 or ord(c)>126 or c==',' for c in channel_key)):
        raise ValueError('bounded private IRC channel key without protocol separators required')
    return dict(value)


def sasl_chunks(value):
    if not value.get('sasl_username'):return ()
    user=value['sasl_username']
    encoded=base64.b64encode((user+'\0'+user+'\0'+value['sasl_password']).encode()).decode()
    chunks=[encoded[i:i+400] for i in range(0,len(encoded),400)]
    if len(encoded)%400==0:chunks.append('+')
    return tuple(chunks)


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
        self.required=REQUIRED_CAPS|({'sasl'} if self.value.get('sasl_username') else set())
        self._sasl_stage='none';self._sasl_logged_in=False
        self._sasl_chunks=sasl_chunks(self.value)

    def join_command(self):
        return 'JOIN '+self.value['channel']+(' :'+self.value['channel_password'] if self.value.get('channel_password') else '')

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
        allowed={'CAP LS 302','CAP REQ :'+ ' '.join(sorted(self.required)),'CAP END',
            'NICK '+self.value['nickname'],'USER '+self.value['nickname']+' 0 * :HAOS private gateway',
            self.join_command()}
        if self.value.get('server_password'):allowed.add('PASS '+self.value['server_password'])
        if self._sasl_stage=='mechanism':allowed.add('AUTHENTICATE PLAIN')
        if self._sasl_stage=='payload':allowed.update('AUTHENTICATE '+chunk for chunk in self._sasl_chunks)
        if line not in allowed and not line.startswith('PONG :'):
            raise PermissionError('IRC application writes require separate reviewed outbox authority')
        self.writer.write((line+'\r\n').encode());await asyncio.wait_for(self.writer.drain(),10)

    async def read(self,timeout):
        self.current()
        if self.reader is None:raise Rejected('IRC connection unavailable')
        try:raw=await asyncio.wait_for(self.reader.readuntil(b'\r\n'),timeout)
        except (asyncio.IncompleteReadError,asyncio.LimitOverrunError):raise Rejected('IRC framing interrupted or oversized',code='connection-lost') from None
        self.current()
        if len(raw)>4098:raise Rejected('IRC frame exceeds bound')
        try:return raw[:-2].decode('utf-8',errors='strict')
        except UnicodeError:raise Rejected('IRC frame is not UTF-8') from None

    @staticmethod
    def parse(raw):
        from plugins.platforms.irc.adapter import _parse_irc_message
        if not isinstance(raw,str) or len(raw.encode())>4096 or any(c in raw for c in '\r\n\0'):
            raise Rejected('invalid IRC frame')
        if raw.startswith('@'):
            tags,separator,raw=raw[1:].partition(' ')
            if not separator:raise Rejected('IRC tag envelope has no frame')
            values={}
            for tag in tags.split(';'):
                name,separator,value=tag.partition('=')
                if not name or name in values:raise Rejected('IRC duplicate or empty tag')
                values[name]=value if separator else None
        else:values={}
        return {**_parse_irc_message(raw),'tags':values}

    async def control(self,raw):
        msg=self.parse(raw)
        if msg['command']=='PING':
            if len(msg['params'])!=1:raise Rejected('invalid IRC keepalive')
            await self.write('PONG :'+msg['params'][0]);return True
        if msg['command']=='005' and any(part.startswith('CASEMAPPING=') and part.split('=',1)[1] not in {'ascii','rfc1459','strict-rfc1459'} for part in msg['params']):
            raise Rejected('IRC server case mapping is unsupported',code='unsupported-case-mapping')
        if msg['command'] in {'263','439'}:raise RateLimited('IRC server deferred account traffic')
        if msg['command'] in {'464','465'}:
            raise AuthenticationRejected('IRC account or server access refused')
        errors={'433':'nickname-in-use','471':'channel-full','473':'channel-invite-required','474':'channel-banned',
            '475':'channel-key-required','477':'account-required','403':'channel-not-found','470':'channel-forwarding-refused'}
        if msg['command'] in errors:
            raise Rejected('IRC server refused requested nickname or channel',code=errors[msg['command']])
        if msg['command']=='ERROR' or re.fullmatch(r'[45][0-9]{2}',msg['command']):
            raise Rejected('IRC server refused registration or subscription')
        return False

    async def connect(self):
        self.current()
        if self.status=='authentication-refused':raise AuthenticationRejected('explicit owner account recheck required')
        if self.writer is not None:raise Rejected('IRC connection already active')
        self.status='connecting';self.confirmed=False;self.capabilities=frozenset()
        self._sasl_stage='none';self._sasl_logged_in=False
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
            deadline=time.monotonic()+self._handshake_seconds;offered=set();mechanisms=None;requested=False;registered=False
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise Rejected('IRC handshake timed out')
                raw=await self.read(remaining)
                if await self.control(raw):continue
                msg=self.parse(raw);params=msg['params'];command=msg['command']
                if command=='CAP':
                    if len(params)<3:raise Rejected('invalid IRC capability response')
                    operation=params[1]
                    if operation=='LS' and not requested:
                        for part in params[-1].split():
                            name,sep,values=part.partition('=');offered.add(name)
                            if name=='sasl' and sep:mechanisms=values.split(',')
                        if len(params)==4 and params[2]=='*':continue
                        if not self.required<=offered:raise Rejected('IRC server lacks required account capabilities',code='required-capabilities')
                        if 'sasl' in self.required and mechanisms is not None and 'PLAIN' not in mechanisms:
                            raise AuthenticationRejected('IRC server does not offer reviewed TLS SASL mechanism')
                        await self.write('CAP REQ :'+ ' '.join(sorted(self.required)));requested=True
                    elif operation=='ACK' and requested and not self.capabilities:
                        acknowledged=frozenset(params[-1].split())
                        if acknowledged!=self.required:raise Rejected('IRC account capabilities were not confirmed',code='required-capabilities')
                        self.capabilities=acknowledged
                        if 'sasl' in self.required:
                            self._sasl_stage='mechanism';await self.write('AUTHENTICATE PLAIN');self._sasl_stage='challenge'
                        else:await self.write('CAP END')
                    else:raise Rejected('IRC capability negotiation refused or changed',code='required-capabilities')
                elif command=='AUTHENTICATE':
                    if self._sasl_stage!='challenge' or params!=['+']:
                        raise AuthenticationRejected('IRC SASL challenge was not expected')
                    self._sasl_stage='payload'
                    for chunk in self._sasl_chunks:await self.write('AUTHENTICATE '+chunk)
                    self._sasl_stage='result'
                elif command=='900':
                    if (self._sasl_stage!='result' or len(params)<3
                            or params[0].lower()!=self.value['nickname'].lower() or params[2]!=self.value.get('sasl_username')):
                        raise AuthenticationRejected('IRC server authenticated a different account')
                    self._sasl_logged_in=True
                elif command=='903':
                    if self._sasl_stage!='result' or not self._sasl_logged_in:
                        raise AuthenticationRejected('IRC SASL completion has no account confirmation')
                    self._sasl_stage='complete';await self.write('CAP END')
                elif command in {'901','902','904','905','906','907','908'}:
                    raise AuthenticationRejected('IRC SASL authentication refused or interrupted')
                elif command=='001':
                    if ('sasl' in self.required and self._sasl_stage!='complete'
                            or not self.capabilities or registered or not params or params[0].lower()!=self.value['nickname'].lower()):
                        raise Rejected('IRC registration preceded verified capabilities or changed nickname')
                    registered=True;await self.write(self.join_command())
                elif command=='JOIN':
                    if (not registered or msg['prefix'].split('!',1)[0].lower()!=self.value['nickname'].lower()
                            or len(params)!=1 or params[0].lower()!=self.value['channel']):raise Rejected('IRC subscription target changed')
                    self.confirmed=True;self.status='streaming';self.adapter._mark_connected();return True
                elif command=='PRIVMSG':raise Rejected('IRC message arrived before authenticated subscription')
        except BaseException as error:
            if isinstance(error,RateLimited):self.status='rate-limited'
            elif isinstance(error,AuthenticationRejected):self.status='authentication-refused'
            elif self.status!='revoked':self.status='transport-unavailable'
            await self.disconnect();raise

    async def receive(self):
        try:
            while True:
                self.current()
                if not self.confirmed:raise Rejected('IRC has no current authenticated subscription')
                try:raw=await self.read(.5)
                except asyncio.TimeoutError:continue
                witness=getattr(self,'_witness',None)
                if witness is not None:
                    consumed=witness.observe(raw)
                    if type(consumed) is not bool:raise PermissionError('explicit IRC witness routing required')
                    if consumed:continue
                if await self.control(raw):continue
                msg=self.parse(raw)
                if msg['command'] in {'900','901','902','904','905','906','907'}:
                    raise AuthenticationRejected('IRC authenticated account changed during subscription')
                if msg['command']=='CAP':raise Rejected('IRC account capability changed during subscription')
                if (msg['command']=='KICK' and len(msg['params'])>=2
                        and msg['params'][0]==self.value['channel'] and msg['params'][1].lower()==self.value['nickname'].lower()
                        or msg['command'] in {'PART','QUIT','NICK'}
                        and msg['prefix'].split('!',1)[0].lower()==self.value['nickname'].lower()):
                    raise Rejected('IRC subscription or local identity was withdrawn')
                # Tagged application frames are admitted independently of the
                # native nickname allowlist; unpaired accounts are never sent on.
                if raw.startswith('@'):
                    try:key=capture(self.adapter,raw,self.authority,self.capabilities)
                    except PermissionError:self.current();continue
                    if key is not None:await dispatch_stored(self.adapter,key)
        except RateLimited:
            self.status='rate-limited';raise
        except AuthenticationRejected:
            self.status='authentication-refused';raise
        finally:
            self.confirmed=False;self.adapter._mark_disconnected();await self.disconnect()

    async def disconnect(self):
        witness=getattr(self,'_witness',None)
        if witness is not None:witness.disconnected()
        self.confirmed=False;self.adapter._mark_disconnected()
        writer,self.writer=self.writer,None;self.reader=None
        if writer is not None:
            writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),5)
            except (OSError,asyncio.TimeoutError):pass
        if self.status not in {'revoked','authentication-refused','rate-limited'}:self.status='disconnected'


def install(adapter,value):
    boundary=Boundary(adapter,value)
    async def deny(_self,*_args,**_kwargs):raise PermissionError('prepared IRC has no reviewed outbox authority')
    adapter._haos_irc_transport=boundary
    # Native raw/standalone sends cannot bypass the later reviewed outbox path.
    adapter._send_raw=MethodType(deny,adapter)
    adapter.send=MethodType(deny,adapter)
    return boundary
