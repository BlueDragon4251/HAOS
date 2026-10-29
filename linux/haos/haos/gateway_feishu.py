"""Prepared exact Feishu/Lark account identities; public activation is separate."""
import re

from .gateway import GatewayPolicy,SUPPORTED,digest

APP=re.compile(r'cli_[A-Za-z0-9]{8,64}\Z')
OPEN_ID=re.compile(r'ou_[A-Za-z0-9]{16,64}\Z')
CHAT_ID=re.compile(r'oc_[A-Za-z0-9]{16,64}\Z')
MESSAGE_ID=re.compile(r'om_[A-Za-z0-9]{16,64}\Z')
THREAD_ID=re.compile(r'omt_[A-Za-z0-9]{16,64}\Z')
TENANT=re.compile(r'[A-Za-z0-9_-]{8,128}\Z')
DOMAINS={'feishu':'https://open.feishu.cn','lark':'https://open.larksuite.com'}


def secret(value,*,limit=4096):
    if (not isinstance(value,str) or not 16<=len(value)<=limit or value!=value.strip()
            or any(not 33<=ord(char)<=126 for char in value)):
        raise ValueError('bounded exact private Feishu secret required; no whitespace or controls')
    return value


def credentials(value,*,verify_tls=True):
    base={'app_id','app_secret','domain','tenant_key','bot_open_id','connection_mode'}
    if (not isinstance(value,dict) or not isinstance(value.get('connection_mode'),str) or value.get('connection_mode') not in {'websocket','webhook'}
            or set(value)!=(base|{'verification_token','encrypt_key','port','tls'} if value.get('connection_mode')=='webhook' else base)):
        raise ValueError('exact Feishu app/tenant/bot identity and reviewed connection settings required')
    for key,pattern in [('app_id',APP),('tenant_key',TENANT),('bot_open_id',OPEN_ID)]:
        if not isinstance(value[key],str) or not pattern.fullmatch(value[key]):raise ValueError('exact Feishu '+key+' required')
    secret(value['app_secret'])
    if not isinstance(value['domain'],str) or value['domain'] not in DOMAINS:
        raise ValueError('select fixed feishu or lark API domain; no caller URL')
    result=dict(value)
    if value['connection_mode']=='webhook':
        secret(value['verification_token'],limit=256);secret(value['encrypt_key'],limit=256)
        if type(value['port']) is not int or not 1024<=value['port']<=65535:raise ValueError('bounded private Feishu HTTPS port required')
        from .gateway_line_tls import material
        try:result['tls']=material(value['tls'],verify=verify_tls,webhook_path='/feishu/webhook')
        except ValueError:raise ValueError('Feishu HTTPS requires exact reviewed URL, trusted certificate/private key and explicit listener consent') from None
    return result


def scope(value):return 'feishu:'+digest([value['domain'],value['app_id'],value['tenant_key'],value['bot_open_id']])


def validate_binding(binding):
    for key,pattern in [('sender',OPEN_ID),('chat',CHAT_ID)]:
        if not isinstance(binding.get(key),str) or not pattern.fullmatch(binding[key]):raise ValueError('exact Feishu open sender/chat ID required')
    if (not isinstance(binding.get('scope'),str) or not re.fullmatch('feishu:[0-9a-f]{64}',binding['scope'])
            or not isinstance(binding.get('thread'),str) or binding['thread'] and not THREAD_ID.fullmatch(binding['thread'])):
        raise ValueError('exact Feishu account scope and optional native topic thread required')
    if type(binding.get('require_mention',True)) is not bool:raise ValueError('explicit boolean Feishu mention policy required')
    if (not isinstance(binding.get('generation'),str) or not re.fullmatch('[0-9a-f]{64}',binding['generation'])
            or type(binding.get('since')) is not int or not 0<binding['since']<2**53):
        raise ValueError('explicit timed Feishu owner grant required')
    for key in ['allow_media','allow_voice','allow_video','allow_outbound_media']:
        if key in binding and (type(binding[key]) is not bool
                or binding[key] and ('read' if key=='allow_outbound_media' else 'create') not in binding['capabilities']):
            raise ValueError('separate boolean Feishu media approval and matching mission rights required')


class PreparedFeishuPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'feishu'})

    def __init__(self,value):
        super().__init__(value)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']=='feishu':validate_binding(binding)


def authority(connector,value,expected=None):
    """Fresh root-owned publication, including exact account scope and own-bot denial."""
    from pathlib import Path
    from .gateway_publication import pending
    from .sandbox import trusted_json
    value=credentials(value,verify_tls=False);config=Path('/etc/haos')
    if pending(config):raise PermissionError('Feishu owner publication requires recovery')
    raw=trusted_json(config/'gateways.json');policy=PreparedFeishuPolicy(raw)
    if policy.connectors.get(connector,{}).get('platform')!='feishu':
        raise PermissionError('configured private Feishu connector required')
    for binding in policy.bindings.values():
        if binding['connector']==connector and (binding['scope']!=scope(value) or binding['sender']==value['bot_open_id']):
            raise PermissionError('Feishu grant differs from configured account or approves the bot itself')
    identity=digest(raw)
    if pending(config) or expected is not None and identity!=expected:
        raise PermissionError('Feishu owner publication changed')
    return identity
