"""Prepared IRCv3 account admission; not a public transport or a TLS implementation."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import re
import time
from types import MethodType

from .gateway import GatewayPolicy, SUPPORTED, digest

_ACCOUNT=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
_CHANNEL=re.compile(r'[&#][a-z0-9][a-z0-9_-]{0,63}\Z')
_SERVER=re.compile(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?:[1-9][0-9]{0,4}\Z')
_CURRENT=ContextVar('haos_retained_irc_account',default=None)
REQUIRED_CAPS=frozenset({'account-tag','server-time','message-tags'})


class PreparedIRCPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'irc'})

    def __init__(self,config):
        super().__init__(config)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']!='irc':continue
            if (not _ACCOUNT.fullmatch(binding['sender']) or not _CHANNEL.fullmatch(binding['chat'])
                    or not _SERVER.fullmatch(binding['scope']) or binding['thread']
                    or not binding.get('generation') or type(binding.get('since')) is not int):
                raise ValueError('IRC requires an exact account/channel/server and timed owner grant')


def snapshot(policy,connector,server):
    if (not isinstance(policy,PreparedIRCPolicy)
            or policy.connectors.get(connector,{}).get('platform')!='irc'
            or not isinstance(server,str) or not _SERVER.fullmatch(server)):
        raise PermissionError('prepared IRC server authority required')
    return {'connector':connector,'server':server,
        'bindings':[digest(b) for b in policy.bindings.values() if b['connector']==connector and b['scope']==server]}


def envelope(adapter,raw,server,capabilities):
    # Only a future TLS/capability-negotiated transport may supply these caps.
    # Client-only (+account) tags, nicknames and hostmasks are never identities.
    if not REQUIRED_CAPS<=frozenset(capabilities):raise PermissionError('authenticated IRCv3 account/time/message capabilities required')
    if (not isinstance(raw,str) or not 1<=len(raw.encode())<=4096 or any(c in raw for c in '\r\n\0')
            or not raw.startswith('@') or not _SERVER.fullmatch(server)):
        return None
    try:
        tags,line=raw[1:].split(' ',1);values={}
        for item in tags.split(';'):
            name,sep,value=item.partition('=')
            if not name or name in values or not sep or '\\' in value:return None
            values[name]=value
        if not {'account','time','msgid'}<=values.keys():return None
        if not _ACCOUNT.fullmatch(values['account']):return None
        identity=values['msgid']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',identity):return None
        original=datetime.fromisoformat(values['time'])
        if original.tzinfo is None or original.utcoffset() is None:return None
        if not line.startswith(':'):return None
        prefix,command,chat,body=line[1:].split(' ',3)
        if (command!='PRIVMSG' or not re.fullmatch(r'[^\s!@:]+![^\s!@:]+@[^\s!@:]+',prefix)
                or not _CHANNEL.fullmatch(chat.lower()) or not body.startswith(':')):return None
        text=body[1:]
        if '\x01' in text or prefix.split('!',1)[0].lower()==adapter._current_nick.lower():return None
        for mention in (adapter._current_nick+':',adapter._current_nick+',',adapter._current_nick+' '):
            if text.lower().startswith(mention.lower()):text=text[len(mention):].strip();break
        else:return None
        if not text or len(text.encode())>32000:return None
        source={'platform':'irc','sender':values['account'],'chat':chat.lower(),'scope':server,'thread':'',
            'message_id':digest([server,identity]),'is_bot':False,'text':text}
        return source,original.timestamp(),line
    except (ValueError,TypeError,OverflowError):return None


def capture(adapter,raw,authority,capabilities):
    native=adapter._haos_native
    if not isinstance(authority,dict) or set(authority)!={'connector','server','bindings'}:
        raise PermissionError('captured IRC owner authority required')
    decoded=envelope(adapter,raw,authority['server'],capabilities)
    if decoded is None:return None
    source,original,_=decoded
    policy=native.policy();binding=policy.authorize(native.connector,source)
    if (authority['connector']!=native.connector or digest(binding) not in authority['bindings']
            or original*1000<=binding['since'] or original>time.time()+300):
        raise PermissionError('IRC original is outside its captured owner grant')
    return native.inbox.admit(policy,native.connector,source,{'raw':raw},received_at=original)


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_irc_decode_lock:
        row=native.inbox.claim(key,native.policy())
        if row is None:return False
        token=None
        try:
            native.policy().current_binding(row)
            decoded=envelope(adapter,row['payload']['raw'],row['envelope']['scope'],REQUIRED_CAPS)
            if decoded is None or decoded[0]!=row['envelope']:raise PermissionError('retained IRC source changed')
            state={'adapter':adapter,'row':row,'accepted':False};token=_CURRENT.set(state)
            await adapter._haos_irc_decode(adapter,decoded[2])
            native.policy().current_binding(row)
            native.inbox.complete(key,state['accepted'])
            return state['accepted']
        except BaseException:native.inbox.retry(key);raise
        finally:
            if token is not None:_CURRENT.reset(token)


def install(adapter):
    from .gateway_runtime import adapter_envelope
    adapter._haos_irc_decode=type(adapter)._handle_line
    adapter._haos_irc_decode_lock=asyncio.Lock()
    original_build=adapter.build_source;original_handle=adapter.handle_message
    async def deny(_self,*_args,**_kwargs):raise PermissionError('IRC callbacks require retained account authority')
    def source(self,**kwargs):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained IRC account')
        value=state['row']['envelope']
        kwargs.update(chat_id=value['chat'],user_id=value['sender'],scope_id=value['scope'],thread_id=None,
            message_id=value['message_id'],is_bot=False)
        return original_build(**kwargs)
    async def handle(self,event):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained IRC event')
        self._haos_native.policy().current_binding(state['row'])
        event.message_id=state['row']['envelope']['message_id']
        event.timestamp=datetime.fromtimestamp(state['row']['created_at'],timezone.utc)
        if adapter_envelope(event,'irc')!=state['row']['envelope']:raise PermissionError('IRC native codec changed approved event')
        await original_handle(event)
        state['accepted']=event._gateway_accepted is True
    # The pinned codec checks this sentinel before constructing an event.
    # Actual delivery still goes exclusively through the durable override.
    adapter._message_handler=MethodType(deny,adapter)
    adapter._handle_line=MethodType(deny,adapter)
    adapter.build_source=MethodType(source,adapter)
    adapter.handle_message=MethodType(handle,adapter)
    return adapter
