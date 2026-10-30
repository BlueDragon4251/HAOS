"""Actual pinned native text codec, after independent immutable-source admission.

This is a prepared primitive; no public receive/profile lifecycle is enabled.
"""
from copy import deepcopy

from .gateway_google_chat_admission import approve,message,Refused
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
    event=await adapter._build_message_event(extracted[0],{**deepcopy(data),'space':extracted[1]})
    if event is None or event.source is None or event.media_urls or event.media_types:raise Refused('native-projection-differs')
    envelope=approval['envelope']
    if event.message_id!=envelope['message_id'] or event.source.chat_id!=envelope['chat']:raise Refused('native-projection-differs')
    # Native email identity and DM thread-count heuristics do not change an
    # independently approved immutable sender resource or exact thread route.
    event.source.user_id=envelope['sender'];event.user_id=envelope['sender']
    event.source.thread_id=envelope['thread'] or None;event.source.scope_id=envelope['scope']
    policy.current_binding(approval)
    return event
