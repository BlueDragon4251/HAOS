"""A2A server identity and exact independently approved peer/context grants."""
import json
import re

from .gateway import GatewayPolicy,SUPPORTED,CAPABILITIES,digest

PEER=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
OPAQUE=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
TOKEN=re.compile(r'[A-Za-z0-9_-]{32,128}\Z')


def opaque(value):
    if not isinstance(value,str) or not OPAQUE.fullmatch(value) or value.lower() in {'all','system','default','anonymous'}:
        raise ValueError('exact A2A message/context identifier required; no URL, wildcard or anonymous alias')
    return value


def credentials(value,*,verify_tls=True):
    if not isinstance(value,dict) or not {'peer_tokens','port','tls','agent_name'}<=set(value)<={'peer_tokens','port','tls','agent_name','download_origins','callbacks'}:
        raise ValueError('exact private A2A peer tokens, HTTPS listener and public name required')
    peers=value['peer_tokens']
    if (not isinstance(peers,dict) or not 1<=len(peers)<=16
            or any(not isinstance(name,str) or not PEER.fullmatch(name) or name.lower() in {'all','system','anonymous','localhost'}
                or not isinstance(token,str) or not TOKEN.fullmatch(token) for name,token in peers.items())
            or len(set(peers.values()))!=len(peers)):
        raise ValueError('unique private token for each exact A2A peer required; no shared or IP-derived identity')
    if type(value['port']) is not int or not 1024<=value['port']<=65535:
        raise ValueError('unprivileged exact A2A HTTPS listener port required')
    name=value['agent_name']
    if not isinstance(name,str) or not 1<=len(name)<=64 or name!=name.strip() or any(ord(c)<32 for c in name):
        raise ValueError('bounded public A2A agent display name required')
    if any(token in public for token in peers.values() for public in [name,*peers]):
        raise ValueError('public A2A names must not contain private peer tokens')
    from .gateway_line_tls import material
    try:tls=material(value['tls'],verify=verify_tls,webhook_path='/a2a')
    except ValueError:raise ValueError('A2A HTTPS needs the exact trusted current hostname/certificate/key and explicit listener approval') from None
    result={**value,'peer_tokens':dict(sorted(peers.items())),'tls':tls}
    if 'callbacks' in value:
        from .gateway_a2a_callback_config import callbacks
        selected=callbacks(value['callbacks'],peers)
        if any(item['secret'] in public for item in selected.values() for public in [name,*peers]):
            raise ValueError('callback keys cannot appear in public A2A names')
        if selected:result['callbacks']=selected
        else:result.pop('callbacks',None)
    if 'download_origins' in value:
        from .gateway_a2a_media import origins
        selected=origins(value['download_origins'],peers)
        if selected:result['download_origins']=selected
        else:result.pop('download_origins',None)
    if len(json.dumps(result).encode())>32768:raise ValueError('private A2A account exceeds service bound')
    return result


def scope(value,peer):
    if not isinstance(peer,str) or not PEER.fullmatch(peer):raise ValueError('exact A2A peer required for server scope')
    return 'a2a:'+digest([value['tls']['public_url'],'default-agent',peer])


def validate_binding(binding):
    if (not isinstance(binding.get('sender'),str) or not PEER.fullmatch(binding['sender'])
            or binding['sender'].lower() in {'all','system','anonymous','localhost'}):
        raise ValueError('exact credential-bound A2A peer required')
    context=binding.get('chat')
    if not isinstance(context,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}',context):
        raise ValueError('exact A2A context must use letters, numbers, underscore or dash; native conversation paths must not alias')
    opaque(context)
    if not isinstance(binding.get('scope'),str) or not re.fullmatch('a2a:[0-9a-f]{64}',binding['scope']) or binding.get('thread')!='':
        raise ValueError('exact A2A server scope and context required; separate topic threads do not apply')
    caps=binding.get('capabilities')
    if (not isinstance(caps,list) or not caps or any(not isinstance(c,str) or c not in {'create','read','cancel','answer'} for c in caps)
            or len(set(caps))!=len(caps) or any(c in caps for c in ['cancel','answer']) and 'read' not in caps):
        raise ValueError('explicit A2A mission permissions required')
    if (not isinstance(binding.get('generation'),str) or not re.fullmatch('[0-9a-f]{64}',binding['generation'])
            or type(binding.get('since')) is not int or not 0<binding['since']<2**53):
        raise ValueError('fresh timed A2A owner grant required')
    flags=['allow_media','allow_voice','allow_video','allow_outbound_media','allow_callback']
    if any(key in binding and type(binding[key]) is not bool for key in flags):
        raise ValueError('explicit boolean A2A media permissions required')
    if (any(binding.get(key) is True for key in flags[:3]) and 'create' not in caps
            or any(binding.get(key) is True for key in ['allow_outbound_media','allow_callback']) and 'read' not in caps):
        raise ValueError('separate A2A media/create or outbound-file/read permissions required')


class PreparedA2APolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'a2a'})

    def __init__(self,value):
        super().__init__(value)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']=='a2a':validate_binding(binding)


def authority(connector,value,expected=None):
    from pathlib import Path
    from .gateway_publication import pending
    from .sandbox import trusted_json
    config=Path('/etc/haos')
    if pending(config):raise PermissionError('A2A owner publication requires recovery')
    raw=trusted_json(config/'gateways.json');policy=PreparedA2APolicy(raw)
    if policy.connectors.get(connector,{}).get('platform')!='a2a':raise PermissionError('saved private A2A connector required')
    for binding in policy.bindings.values():
        if binding['connector']==connector and (binding['scope']!=scope(value,binding['sender']) or binding['sender'] not in value['peer_tokens']):
            raise PermissionError('A2A peer/context grant differs from saved server identity')
    publication=digest(raw)
    if pending(config) or expected is not None and expected!=publication:raise PermissionError('A2A owner publication changed')
    return publication
