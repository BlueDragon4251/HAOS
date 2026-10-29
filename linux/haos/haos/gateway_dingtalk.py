"""Prepared DingTalk app identity and exact grants; public activation is separate."""
import re

from .gateway import GatewayPolicy,SUPPORTED,CAPABILITIES,digest

OPAQUE=re.compile(r'[A-Za-z0-9_$:+=/.-]{1,256}\Z')
APP=re.compile(r'[A-Za-z0-9_-]{8,128}\Z')
API='https://api.dingtalk.com'


def identity(value):
    if not isinstance(value,str) or not OPAQUE.fullmatch(value) or '://' in value or value in {'all','system','.' ,'..'}:
        raise ValueError('exact opaque DingTalk platform ID required; no aliases, URLs or wildcard')
    return value


def credentials(value):
    if not isinstance(value,dict) or set(value)!={'client_id','client_secret','corp_id','robot_code'}:
        raise ValueError('exact DingTalk app/secret/corporation/robot identity required')
    for key in ['client_id','corp_id','robot_code']:
        if not isinstance(value[key],str) or not APP.fullmatch(value[key]):raise ValueError('exact DingTalk '+key+' required')
    secret=value['client_secret']
    if not isinstance(secret,str) or not 16<=len(secret)<=4096 or any(not 33<=ord(char)<=126 for char in secret):
        raise ValueError('bounded private DingTalk app secret required')
    return dict(value)


def scope(value):return 'dingtalk:'+digest([value[key] for key in ['client_id','corp_id','robot_code']])


def validate_binding(binding):
    identity(binding.get('sender'));identity(binding.get('chat'))
    caps=binding.get('capabilities')
    if (not isinstance(caps,list) or not caps or any(not isinstance(cap,str) or cap not in CAPABILITIES for cap in caps)
            or len(set(caps))!=len(caps)):raise ValueError('explicit supported DingTalk mission permissions required')
    if (not isinstance(binding.get('scope'),str) or not re.fullmatch('dingtalk:[0-9a-f]{64}',binding['scope'])
            or binding.get('thread')!=''):
        raise ValueError('exact DingTalk account scope required; pinned native callback has no topic-thread route')
    if (not isinstance(binding.get('generation'),str) or not re.fullmatch('[0-9a-f]{64}',binding['generation'])
            or type(binding.get('since')) is not int or not 0<binding['since']<2**53):
        raise ValueError('explicit timed DingTalk owner grant required')
    if type(binding.get('require_mention',True)) is not bool:raise ValueError('explicit boolean DingTalk mention policy required')
    for key in ['allow_media','allow_voice','allow_video','allow_outbound_media']:
        if key in binding and (type(binding[key]) is not bool
                or binding[key] and ('read' if key=='allow_outbound_media' else 'create') not in caps):
            raise ValueError('separate DingTalk media approval and matching mission rights required')


class PreparedDingTalkPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'dingtalk'})

    def __init__(self,value):
        super().__init__(value)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']=='dingtalk':validate_binding(binding)


def authority(connector,value,expected=None):
    from pathlib import Path
    from .gateway_publication import pending
    from .sandbox import trusted_json
    value=credentials(value);config=Path('/etc/haos')
    if pending(config):raise PermissionError('DingTalk owner publication requires recovery')
    raw=trusted_json(config/'gateways.json');policy=PreparedDingTalkPolicy(raw)
    if policy.connectors.get(connector,{}).get('platform')!='dingtalk':raise PermissionError('configured private DingTalk connector required')
    for binding in policy.bindings.values():
        if binding['connector']==connector and (binding['scope']!=scope(value) or binding['sender']==value['robot_code']):
            raise PermissionError('DingTalk grant differs from configured app identity or approves its robot')
    result=digest(raw)
    if pending(config) or expected is not None and expected!=result:raise PermissionError('DingTalk owner publication changed')
    return result
