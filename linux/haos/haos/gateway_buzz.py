"""Prepared Buzz account and exact Nostr/channel grants; no public activation."""
import json
import re
from urllib.parse import urlsplit,urlunsplit
from uuid import UUID

from .gateway import GatewayPolicy,SUPPORTED,CAPABILITIES,digest

HEX=re.compile('[0-9a-f]{64}\\Z')
ORDER=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def relay(value):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 or ord(c)>126 for c in value) or '\\' in value:
        raise ValueError('exact canonical HTTPS Buzz relay required')
    try:parts=urlsplit(value);host=parts.hostname;port=parts.port
    except ValueError:raise ValueError('invalid Buzz relay authority') from None
    if (parts.scheme!='https' or not host or parts.username is not None or parts.password is not None
            or parts.path or parts.query or parts.fragment or '?' in value or '#' in value
            or port is not None and not 1<=port<=65535 or host.endswith('.')):
        raise ValueError('Buzz relay must be one exact HTTPS origin without path, credentials, query or fragment')
    authority='['+host+']' if ':' in host else host
    if port is not None and port!=443:authority+=':'+str(port)
    if value!=urlunsplit(('https',authority,'','','')):raise ValueError('canonical Buzz relay origin required')
    return value


def channel(value):
    if not isinstance(value,str) or len(value)!=36:raise ValueError('exact canonical Buzz channel UUID required')
    try:parsed=UUID(value)
    except ValueError:raise ValueError('exact canonical Buzz channel UUID required') from None
    if str(parsed)!=value or not parsed.int:raise ValueError('nonempty canonical Buzz channel UUID required')
    return value


def credentials(value):
    fields={'private_key','public_key','relay_url','channels'}
    if not isinstance(value,dict) or not fields<=set(value)<=fields|{'auth_tag','attachment_origins'}:
        raise ValueError('dedicated private Nostr key, expected public key, exact relay and explicit channels required')
    key=value['private_key'];public=value['public_key']
    if (not isinstance(public,str) or not HEX.fullmatch(public) or not isinstance(key,str)
            or not (HEX.fullmatch(key) and 0<int(key,16)<ORDER or re.fullmatch('nsec1[023456789acdefghjklmnpqrstuvwxyz]{58}',key))):
        raise ValueError('bounded canonical Nostr private key and exact expected hexadecimal public identity required')
    endpoint=relay(value['relay_url']);channels=value['channels']
    if (not isinstance(channels,list) or not 1<=len(channels)<=32 or any(not isinstance(item,str) for item in channels)
            or len(set(channels))!=len(channels)):
        raise ValueError('one to thirty-two explicit distinct Buzz channel UUIDs required')
    for item in channels:channel(item)
    result={**value,'channels':sorted(channels)}
    if 'attachment_origins' in value:
        origins=value['attachment_origins']
        if (not isinstance(origins,list) or len(origins)>8 or any(not isinstance(item,str) for item in origins)
                or len(set(origins))!=len(origins)):
            raise ValueError('at most eight explicit distinct HTTPS attachment origins required')
        for item in origins:relay(item)
        result['attachment_origins']=sorted(origins)
    if 'auth_tag' in value:
        raw=value['auth_tag']
        if not isinstance(raw,str) or len(raw.encode())>4096:raise ValueError('bounded private NIP-OA auth tag JSON required')
        try:tag=json.loads(raw)
        except (ValueError,RecursionError):raise ValueError('valid NIP-OA auth tag JSON required') from None
        if (not isinstance(tag,list) or len(tag)!=4 or tag[0]!='auth' or any(not isinstance(part,str) or not part or len(part)>2048
                or any(ord(c)<32 for c in part) for part in tag)):
            raise ValueError('exact four-string NIP-OA owner attestation required')
        result['auth_tag']=json.dumps(tag,separators=(',',':'),ensure_ascii=False)
    if key in endpoint or key==public:raise ValueError('private Nostr material cannot become public relay/account metadata')
    return result


def scope(value):return 'buzz:'+digest([value['relay_url'],value['public_key']])


def resource_origin(value,url):
    """No credential-bearing GET beyond the native relay's media namespace."""
    if (not isinstance(url,str) or not 1<=len(url)<=4096 or any(ord(c)<33 or ord(c)>126 for c in url) or '\\' in url):
        raise ValueError('one bounded explicit HTTPS resource URL required')
    try:parts=urlsplit(url);host=parts.hostname;port=parts.port
    except ValueError:raise ValueError('invalid Buzz resource URL') from None
    if parts.scheme!='https' or not host or parts.username is not None or parts.password is not None or parts.fragment or '#' in url:
        raise ValueError('Buzz resource cannot contain ambient credentials or a fragment')
    authority='['+host+']' if ':' in host else host
    if port is not None and port!=443:authority+=':'+str(port)
    origin=relay(urlunsplit(('https',authority,'','','')))
    if origin==value['relay_url']:
        if not re.fullmatch('/media/[0-9a-f]{64}(?:\\.[a-z0-9]{1,8}|\\.thumb\\.jpg)?',parts.path):
            raise PermissionError('private relay credentials are restricted to native content-addressed media GETs')
        return 'relay'
    if origin not in value.get('attachment_origins',[]):raise PermissionError('foreign media origin lacks explicit independent owner approval')
    return 'public'


def validate_binding(binding):
    if (not isinstance(binding.get('sender'),str) or not HEX.fullmatch(binding['sender'])
            or not isinstance(binding.get('scope'),str) or not re.fullmatch('buzz:[0-9a-f]{64}',binding['scope'])
            or not isinstance(binding.get('thread'),str) or binding['thread'] and not HEX.fullmatch(binding['thread'])):
        raise ValueError('exact signed Nostr sender, relay/account scope and optional thread root required')
    channel(binding.get('chat'))
    caps=binding.get('capabilities')
    if (not isinstance(caps,list) or not caps or any(not isinstance(cap,str) or cap not in CAPABILITIES for cap in caps)
            or len(set(caps))!=len(caps)):
        raise ValueError('explicit independent Buzz mission capabilities required')
    if (not isinstance(binding.get('generation'),str) or not HEX.fullmatch(binding['generation'])
            or type(binding.get('since')) is not int or not 0<binding['since']<2**53):
        raise ValueError('fresh timed independent Buzz grant required')
    flags=['allow_media','allow_voice','allow_video','allow_outbound_media','require_mention']
    if any(key in binding and type(binding[key]) is not bool for key in flags):raise ValueError('explicit boolean Buzz permission flags required')
    if (any(binding.get(key) is True for key in flags[:3]) and 'create' not in caps
            or binding.get('allow_outbound_media') is True and 'read' not in caps):
        raise ValueError('independent Buzz media/create and file-output/read grants required')


class PreparedBuzzPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'buzz'})

    def __init__(self,value):
        if (not isinstance(value,dict) or not isinstance(value.get('bindings'),list) or len(value['bindings'])>512
                or any(not isinstance(row,dict) for row in value['bindings'])):
            raise ValueError('bounded prepared Buzz identity bindings required')
        super().__init__(value)
        for row in self.bindings.values():
            if self.connectors[row['connector']]['platform']=='buzz':validate_binding(row)
