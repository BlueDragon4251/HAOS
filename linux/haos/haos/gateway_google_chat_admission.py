"""Independent route admission before native Google Chat parsing or attachments.

Only authenticated transport code may submit bytes. This does not authenticate
HTTP tokens or Pub/Sub callers and is not a public profile factory.
"""
from datetime import datetime
import hashlib
import re
import time

from .gateway import GatewayPolicy,digest
from .gateway_google_chat import credentials,resource,scope,validate_binding
from .gateway_dingtalk_admission import parse,Refused as JSONRefused


class Refused(PermissionError):
    def __init__(self,reason):
        self.reason=reason;super().__init__('Google Chat source is not approved')


def timestamp(value):
    if (not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z',value)):
        raise ValueError('exact UTC Google Chat source timestamp required')
    return datetime.fromisoformat(value[:-1]+'+00:00').timestamp()*1000


def message(data):
    # Use the actual pinned extractor later, after authority. Relay aliases lack
    # a verified Google resource sender and cannot establish independent grants.
    if data.get('type')=='MESSAGE' and isinstance(data.get('message'),dict):
        msg=data['message'];space=data['space'] if 'space' in data else msg.get('space')
    elif isinstance(data.get('chat'),dict) and isinstance(data['chat'].get('messagePayload'),dict):
        payload=data['chat']['messagePayload'];msg=payload.get('message');space=payload.get('space')
    else:raise Refused('unsupported-event')
    if not isinstance(msg,dict) or not isinstance(space,dict):raise Refused('unsupported-event')
    space_type(msg,space);return msg,space


def space_type(msg,space):
    # Google can project a full outer Space alongside a nested name-only or
    # differently descriptive Space. Bind authority to the resource and a
    # consistent type, rather than requiring incidental metadata equality.
    descriptors=[space]
    if msg.get('space') is not None:descriptors.append(msg['space'])
    kinds={'DIRECT_MESSAGE','SPACE','GROUP_CHAT'};typed=False
    for descriptor in descriptors:
        if not isinstance(descriptor,dict) or descriptor.get('name')!=space.get('name'):raise Refused('ambiguous-space')
        for field in ['spaceType','type']:
            if field not in descriptor:continue
            value=descriptor[field];typed=True
            if not isinstance(value,str):raise Refused('unsupported-space')
            allowed=({'DIRECT_MESSAGE'} if value=='DM' else {'SPACE','GROUP_CHAT'} if value=='ROOM' else
                {value} if value in {'DIRECT_MESSAGE','SPACE','GROUP_CHAT'} else set())
            if not allowed:raise Refused('unsupported-space')
            kinds&=allowed
            if not kinds:raise Refused('ambiguous-space')
    if not typed:raise Refused('unsupported-space')
    return 'SPACE' if kinds=={'SPACE','GROUP_CHAT'} else next(iter(kinds))


def approve(policy,connector,value,raw):
    if not isinstance(policy,GatewayPolicy) or policy.connectors.get(connector,{}).get('platform')!='google_chat':raise Refused('unapproved-route')
    value=credentials(value)
    try:
        data=parse(raw);msg,space=message(data);sender=msg.get('sender')
        if not isinstance(sender,dict) or sender.get('type')!='HUMAN':raise Refused('self-or-automated')
        peer=resource(sender.get('name'),'user');chat=resource(space.get('name'),'space')
        if peer==value['bot_user']:raise Refused('self-or-automated')
        mid=resource(msg.get('name'),'message',space=chat);thread=msg.get('thread')
        if thread is not None and not isinstance(thread,dict):raise Refused('unsupported-thread')
        thread=resource(thread['name'],'thread',space=chat) if thread else ''
        envelope={'platform':'google_chat','sender':peer,'chat':chat,'scope':scope(value),'thread':thread,
            'message_id':mid,'is_bot':False,'text':''}
        try:binding=policy.authorize(connector,envelope)
        except PermissionError:raise Refused('unapproved-route') from None
        validate_binding(binding);created=timestamp(msg.get('createTime'))
        if not binding['since']<created<=time.time()*1000+300000:raise Refused('pre-grant')
        kind=space_type(msg,space)
        annotations=msg.get('annotations',[])
        if not isinstance(annotations,list) or len(annotations)>128:raise Refused('unsupported-content')
        mentioned=any(isinstance(a,dict) and a.get('type')=='USER_MENTION' and isinstance(a.get('userMention'),dict)
            and isinstance(a['userMention'].get('user'),dict) and a['userMention']['user'].get('name')==value['bot_user'] for a in annotations)
        if kind!='DIRECT_MESSAGE' and binding.get('require_mention',True) and not mentioned:
            raise Refused('mention-required')
        for key in ['text','argumentText']:
            if key in msg and (not isinstance(msg[key],str) or len(msg[key].encode())>32768):raise Refused('unsupported-content')
        attachments=msg.get('attachment',[])
        if not isinstance(attachments,list) or len(attachments)>4:raise Refused('unsupported-content')
        for item in attachments:
            if not isinstance(item,dict) or not isinstance(item.get('contentType'),str):raise Refused('unsupported-content')
            mime=item['contentType']
            needed='allow_voice' if mime.startswith('audio/') else 'allow_video' if mime.startswith('video/') else 'allow_media'
            if binding.get(needed) is not True:raise Refused('unapproved-media')
    except Refused:raise
    except JSONRefused:raise Refused('unsupported-content') from None
    except (ValueError,KeyError,TypeError,OverflowError):raise Refused('unsupported-content') from None
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    return {'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),'received_at':created/1000,
        'raw_sha256':hashlib.sha256(raw).hexdigest(),'credential_scope':digest([connector,value])}
