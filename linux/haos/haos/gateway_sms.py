"""Independent exact Twilio SMS identities and strict signed form decoding."""
import re
from urllib.parse import parse_qs,urlencode

from .gateway import GatewayPolicy,SUPPORTED,digest

PHONE=re.compile(r'\+[1-9][0-9]{7,14}\Z')
ACCOUNT=re.compile(r'AC[0-9a-fA-F]{32}\Z')
MESSAGE=re.compile(r'(?:SM|MM)[0-9a-fA-F]{32}\Z')


class PreparedSMSPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'sms'})

    def __init__(self,value):
        super().__init__(value)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']=='sms':validate_binding(binding,require_epoch=True)


def credentials(value,*,verify_tls=True):
    if not isinstance(value,dict) or set(value)!={'account_sid','auth_token','from_number','port','tls'}:
        raise ValueError('exact private Twilio account, auth token, number, HTTPS port and TLS material required')
    if (not isinstance(value['account_sid'],str) or not ACCOUNT.fullmatch(value['account_sid'])
            or not isinstance(value['auth_token'],str) or not re.fullmatch(r'[0-9a-fA-F]{32}',value['auth_token'])
            or not isinstance(value['from_number'],str) or not PHONE.fullmatch(value['from_number'])
            or type(value['port']) is not int or not 1024<=value['port']<=65535):
        raise ValueError('canonical Twilio Account SID, private auth token, E.164 number and unprivileged port required')
    from .gateway_line_tls import material
    try:tls=material(value['tls'],verify=verify_tls,webhook_path='/webhooks/twilio')
    except (ValueError,PermissionError):raise ValueError('SMS requires current trusted HTTPS certificate/key and exact public /webhooks/twilio URL') from None
    return {**value,'tls':tls}


def scope(value):return value['account_sid']+':'+value['from_number']


def validate_binding(binding,*,require_epoch=False):
    if (not isinstance(binding['sender'],str) or not PHONE.fullmatch(binding['sender'])
            or binding['chat']!=binding['sender'] or binding['thread']
            or not re.fullmatch(r'AC[0-9a-fA-F]{32}:\+[1-9][0-9]{7,14}',binding['scope'])
            or binding['scope'].split(':',1)[1]==binding['sender']):
        raise ValueError('SMS requires exact distinct sender/receiver E.164 numbers, account scope and no thread')
    if require_epoch and (not binding.get('generation') or type(binding.get('since')) is not int):
        raise ValueError('SMS requires an explicit timed owner grant')


def snapshot(policy,connector,value):
    if not isinstance(policy,GatewayPolicy) or policy.connectors.get(connector,{}).get('platform')!='sms':
        raise PermissionError('configured SMS connector required')
    return digest([connector,scope(value),sorted(digest(b) for b in policy.bindings.values() if b['connector']==connector)])


def form(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=65536:raise ValueError('bounded SMS form required')
    text=raw.decode('utf-8',errors='strict')
    # parse_qs otherwise accepts malformed percent escapes and silently repairs
    # invalid encoded UTF-8. Duplicate values are never flattened for signatures.
    if re.search(r'%(?![0-9a-fA-F]{2})',text):raise ValueError('canonical percent-encoded SMS form required')
    values=parse_qs(text,keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=128)
    if (not values or any(len(v)!=1 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',key)
            or len(v[0].encode())>32000 for key,v in values.items())):
        raise ValueError('bounded distinct SMS form fields required')
    result={key:value[0] for key,value in values.items()}
    if len(urlencode(result).encode())>65536:raise ValueError('canonical SMS form exceeds native decoder bound')
    return result


def envelope(values,value):
    mandatory={'AccountSid','MessageSid','From','To','Body'}
    if not isinstance(values,dict) or not mandatory<=set(values) or any(not isinstance(v,str) for v in values.values()):
        raise ValueError('complete Twilio message identity required')
    if (values['AccountSid']!=value['account_sid'] or not MESSAGE.fullmatch(values['MessageSid'])
            or values['To']!=value['from_number'] or not PHONE.fullmatch(values['From'])
            or values['From']==values['To'] or not 1<=len(values['Body'].strip())<=1600):
        raise ValueError('exact Twilio account, sender, receiver and bounded text required')
    if values.get('NumMedia','0')!='0' or any(key.startswith('MediaUrl') for key in values):
        raise ValueError('SMS media requires its separate reviewed transport')
    return {'platform':'sms','sender':values['From'],'chat':values['From'],'scope':scope(value),'thread':'',
        'message_id':values['MessageSid'],'is_bot':False,'text':values['Body'].strip()}
