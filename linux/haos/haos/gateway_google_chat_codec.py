"""Actual pinned native text codec, after independent immutable-source admission.

This is a prepared primitive; no public receive/profile lifecycle is enabled.
"""
from copy import deepcopy

from .gateway_google_chat_admission import approve,message,space_type,Refused
from .gateway_dingtalk_admission import parse


async def decode_text(adapter,policy,connector,value,raw,approval):
    from plugins.platforms.google_chat.adapter import GoogleChatAdapter
    if not isinstance(adapter,GoogleChatAdapter):raise TypeError('actual pinned Google Chat adapter required')
    current=approve(policy,connector,value,raw)
    if current!=approval:raise PermissionError('Google Chat original or independent grant changed before decoding')
    data=parse(raw);expected,space=message(data)
    if expected.get('attachment'):raise Refused('text-codec-requires-separate-private-media')
    extracted=GoogleChatAdapter._extract_message_payload(deepcopy(data))
    if extracted is None or extracted[0]!=expected or extracted[1]!=space:raise Refused('native-projection-differs')
    event=await adapter._build_message_event(extracted[0],{**deepcopy(data),'space':{**space,'spaceType':space_type(expected,space)}})
    if event is None or event.source is None or event.media_urls or event.media_types:raise Refused('native-projection-differs')
    envelope=approval['envelope']
    if event.message_id!=envelope['message_id'] or event.source.chat_id!=envelope['chat']:raise Refused('native-projection-differs')
    # Native email identity and DM thread-count heuristics do not change an
    # independently approved immutable sender resource or exact thread route.
    event.source.user_id=envelope['sender'];event.user_id=envelope['sender']
    event.source.thread_id=envelope['thread'] or None;event.source.scope_id=envelope['scope']
    event.raw_message=None
    policy.current_binding(approval)
    return event


async def decode_event(adapter,policy,connector,value,raw,approval,raw_id):
    """Actual native builder with independently retained private media copies."""
    data=parse(raw);msg,space=message(data)
    if not msg.get('attachment'):return await decode_text(adapter,policy,connector,value,raw,approval)
    from plugins.platforms.google_chat.adapter import GoogleChatAdapter
    from .gateway_google_chat_resources import specifications,retained
    from .gateway_runtime import adapter_envelope
    from .gateway import Conflict
    from types import MethodType
    import asyncio
    if not isinstance(adapter,GoogleChatAdapter) or approve(policy,connector,value,raw)!=approval:
        raise PermissionError('actual native Google Chat adapter and matching original approval required')
    extracted=GoogleChatAdapter._extract_message_payload(deepcopy(data))
    if extracted is None or extracted[0]!=msg or extracted[1]!=space:raise Refused('native-projection-differs')
    # Do not rewrite the retained raw/proof representation. Only the native
    # builder receives the independently checked canonical Space kind.
    space={**space,'spaceType':space_type(msg,space)}
    def normalize(event):
        if event is None or event.source is None or event.message_id!=approval['envelope']['message_id'] or event.source.chat_id!=approval['envelope']['chat']:
            raise Refused('native-projection-differs')
        event.source.user_id=approval['envelope']['sender'];event.user_id=event.source.user_id
        event.source.thread_id=approval['envelope']['thread'] or None;event.source.scope_id=approval['envelope']['scope']
        event.text=adapter._haos_native.inbox.redactor.text(event.text or 'Process the attached Google Chat media')
        event.channel_prompt=None;event.raw_message=None
        return event
    from .redaction import Redactor
    redactor=adapter._haos_native.inbox.redactor
    uploads=[item.get('attachmentDataRef',{}).get('attachmentUploadToken') for item in msg['attachment'] if isinstance(item.get('attachmentDataRef'),dict)]
    secrets=Redactor([*redactor.secrets,*[token for token in uploads if isinstance(token,str) and 1<=len(token)<=16384]]).secrets
    if len(secrets)>4096 or sum(len(s) for s in secrets)>8*1024*1024:raise Refused('private-redaction-capacity')
    redactor.secrets=secrets
    text=normalize(await GoogleChatAdapter._build_message_event(adapter,{**deepcopy(msg),'attachment':[]},{**deepcopy(data),'space':space}))
    if text.media_urls or text.media_types:raise Refused('native-projection-differs')
    envelope=adapter_envelope(text,'google_chat')
    specs=specifications(policy,connector,value,raw,approval,envelope)
    copies=await retained(adapter,raw_id,raw,approval,envelope,specs)
    # Only the actual current native builder task can resolve these already
    # retained copies. No bearer-bearing URL or host path enters the event.
    from contextvars import ContextVar
    if not hasattr(adapter,'_haos_google_media_context'):
        adapter._haos_google_media_context=ContextVar('haos_google_chat_retained_media',default=None)
        async def local(self,item):
            state=self._haos_google_media_context.get()
            if state is None or state['task'] is not asyncio.current_task():raise PermissionError('no retained Google media codec context')
            self._haos_google_check();self._haos_native.policy().current_binding(state['approval'])
            index=state['index']
            if index>=len(state['attachments']) or item!=state['attachments'][index]:raise PermissionError('native Google attachment changed after byte custody')
            copy=state['copies'][index];state['index']+=1
            return 'haos-media:'+copy['item']['id'],copy['spec']['mime']
        adapter._download_attachment=MethodType(local,adapter)
    state={'task':asyncio.current_task(),'approval':approval,'attachments':deepcopy(msg['attachment']),'copies':copies,'index':0}
    token=adapter._haos_google_media_context.set(state)
    try:event=normalize(await GoogleChatAdapter._build_message_event(adapter,deepcopy(msg),{**deepcopy(data),'space':space}))
    finally:adapter._haos_google_media_context.reset(token)
    if (state['index']!=len(copies) or event.text!=text.text
            or event.media_urls!=['haos-media:'+p['item']['id'] for p in copies] or event.media_types!=[p['spec']['mime'] for p in copies]):
        raise Conflict('Google native media/text projection differs from exact retained source')
    unique={copy['item']['id']:copy for copy in copies};event.media_urls=['haos-media:'+identity for identity in unique]
    event.media_types=[copy['spec']['mime'] for copy in unique.values()];event.media_text_inlined=[False]*len(unique)
    from gateway.platforms.base import MessageType
    kinds={copy['item']['descriptor']['kind'] for copy in copies}
    event.message_type=MessageType.PHOTO if kinds=={'image'} else MessageType.VOICE if kinds=={'voice'} else MessageType.VIDEO if kinds=={'video'} else MessageType.DOCUMENT
    adapter._haos_google_check();policy=adapter._haos_native.policy();policy.current_binding(approval)
    return event
