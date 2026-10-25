"""Prepared HA context/entity admission; public setup and transport remain disabled."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import re
import time
from types import MethodType

from .gateway import GatewayPolicy, SUPPORTED, digest

_USER=re.compile(r'[0-9a-f]{32}\Z')
_ENTITY=re.compile(r'[a-z0-9_]{1,64}\.[a-z0-9_]{1,128}\Z')
_CONTEXT=re.compile(r'(?:[0-9a-f]{32}|[0-9A-HJKMNP-TV-Z]{26})\Z')
_CURRENT=ContextVar('haos_homeassistant_retained_context',default=None)


class PreparedHomeAssistantPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'homeassistant'})

    def __init__(self,config):
        super().__init__(config)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']!='homeassistant':continue
            if ('homeassistant_shared_notifications' in binding and type(binding['homeassistant_shared_notifications']) is not bool):
                raise ValueError('explicit boolean approval of shared Home Assistant notifications required')
            if (not _USER.fullmatch(binding['sender']) or not _ENTITY.fullmatch(binding['chat'])
                    or binding['scope'] or binding['thread'] or type(binding.get('since')) is not int
                    or not binding.get('generation')):
                raise ValueError('prepared Home Assistant requires exact authenticated user, entity and explicit timed owner grant')


def snapshot(policy,connector):
    if policy.connectors.get(connector,{}).get('platform')!='homeassistant':
        raise PermissionError('exact prepared Home Assistant connector required')
    return {'connector':connector,'bindings':[digest(b) for b in policy.bindings.values() if b['connector']==connector]}


def _timestamp(value):
    if not isinstance(value,str) or not 1<=len(value)<=64:raise ValueError('bounded original Home Assistant timestamp required')
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError('timezone-aware original timestamp required')
    return parsed.timestamp()


def envelope(adapter,event):
    try:
        if not isinstance(event,dict) or event.get('event_type')!='state_changed':return None
        if len(json.dumps(event,ensure_ascii=False).encode())>65536:return None
        data=event.get('data');context=event.get('context')
        if not isinstance(data,dict) or not isinstance(context,dict):return None
        entity=data.get('entity_id');user=context.get('user_id');identity=context.get('id')
        if (not isinstance(entity,str) or not _ENTITY.fullmatch(entity)
                or not isinstance(user,str) or not _USER.fullmatch(user)
                or not isinstance(identity,str) or not _CONTEXT.fullmatch(identity)):return None
        new=data.get('new_state');old=data.get('old_state')
        if (not isinstance(new,dict) or old is not None and not isinstance(old,dict)
                or new.get('entity_id')!=entity or not isinstance(new.get('context'),dict)
                or new['context'].get('id')!=identity or new['context'].get('user_id')!=user
                or not isinstance(new.get('state'),str) or not isinstance(new.get('attributes',{}),dict)
                or old is not None and 'state' in old and not isinstance(old['state'],str)):return None
        updated=_timestamp(new.get('last_updated'));fired=_timestamp(event.get('time_fired'))
        if not 0<=fired-updated<=300:return None
        text=adapter._format_state_change(entity,old,new)
        if not isinstance(text,str) or not 1<=len(text.encode())<=32000:return None
        source={'platform':'homeassistant','sender':user,'chat':entity,'scope':'','thread':'',
            'message_id':digest([entity,identity,new['last_updated'],event['time_fired']]),'is_bot':False,'text':text}
        return source,fired
    except (ValueError,TypeError,KeyError,OverflowError):return None


def capture(adapter,event,authority):
    decoded=envelope(adapter,event)
    if decoded is None:return None
    source,original=decoded
    native=adapter._haos_native;policy=native.policy();binding=policy.authorize(native.connector,source)
    if (not isinstance(authority,dict) or authority.get('connector')!=native.connector
            or digest(binding) not in authority.get('bindings',[])
            or original*1000<=binding['since'] or original>time.time()+300):
        raise PermissionError('Home Assistant original is outside its captured owner grant')
    return native.inbox.admit(policy,native.connector,source,{'event':event},received_at=original)


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_ha_decode_lock:
        row=native.inbox.claim(key,native.policy())
        if row is None:return False
        token=None;before=adapter._last_event_time
        try:
            native.policy().current_binding(row)
            event=row['payload']['event'];decoded=envelope(adapter,event)
            if decoded is None or decoded[0]!=row['envelope']:raise PermissionError('retained HA source changed')
            state={'adapter':adapter,'row':row,'accepted':False}
            token=_CURRENT.set(state)
            # Native wall-clock cooldown cannot consume a durable failed attempt.
            adapter._last_event_time={}
            await adapter._haos_ha_decode(adapter,event)
            native.policy().current_binding(row)
            native.inbox.complete(key,state['accepted'])
            return state['accepted']
        except BaseException:native.inbox.retry(key);raise
        finally:
            adapter._last_event_time=before
            if token is not None:_CURRENT.reset(token)


def install(adapter):
    from .gateway_runtime import adapter_envelope
    adapter._haos_ha_decode=type(adapter)._handle_ha_event
    adapter._haos_ha_decode_lock=asyncio.Lock()
    original_build=adapter.build_source;original_handle=adapter.handle_message
    async def deny(_self,*_args,**_kwargs):
        raise PermissionError('Home Assistant native callback requires retained owner admission')
    def source(self,**kwargs):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained Home Assistant context')
        original=state['row']['envelope']
        kwargs.update(chat_id=original['chat'],user_id=original['sender'],scope_id=None,thread_id=None,
            message_id=original['message_id'],is_bot=False)
        return original_build(**kwargs)
    async def handle(self,event):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained Home Assistant native event')
        self._haos_native.policy().current_binding(state['row'])
        event.message_id=state['row']['envelope']['message_id']
        event.timestamp=datetime.fromtimestamp(state['row']['created_at'],timezone.utc)
        if adapter_envelope(event,'homeassistant')!=state['row']['envelope']:
            raise PermissionError('native Home Assistant codec changed approved source')
        await original_handle(event)
        state['accepted']=event._gateway_accepted is True
    adapter._handle_ha_event=MethodType(deny,adapter)
    adapter.build_source=MethodType(source,adapter)
    adapter.handle_message=MethodType(handle,adapter)
    return adapter
