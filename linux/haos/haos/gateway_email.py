"""Prepared exact email identities and TLS account settings; not a public transport."""
import re

from .gateway import GatewayPolicy,SUPPORTED,digest

_ADDRESS=re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
_MESSAGE=re.compile(r'<[^<>@\s\x00-\x1f\x7f]{1,250}@[^<>@\s\x00-\x1f\x7f]{1,250}>\Z')


def hostname(value):
    if (not isinstance(value,str) or not 1<=len(value)<=253 or value!=value.lower()
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in value.split('.'))):
        raise ValueError('exact lowercase ASCII mail hostname required; no URL, credentials or wildcard')
    return value


def address(value):
    if not isinstance(value,str) or not 3<=len(value)<=254 or not value.isascii() or not _ADDRESS.fullmatch(value):
        raise ValueError('exact canonical lowercase mailbox address required')
    local,domain=value.rsplit('@',1)
    if len(local)>64:raise ValueError('bounded mailbox local part required')
    hostname(domain)
    return value


def credentials(value):
    fields={'address','password','imap_host','imap_port','imap_security','smtp_host','smtp_port','smtp_security','authserv_id'}
    if not isinstance(value,dict) or set(value)!=fields:raise ValueError('exact private email account, TLS endpoints and receiving authentication service required')
    address(value['address'])
    for key in ('imap_host','smtp_host','authserv_id'):hostname(value[key])
    for key in ('imap_port','smtp_port'):
        if type(value[key]) is not int or not 1<=value[key]<=65535:raise ValueError('bounded exact mail endpoint port required')
    if any(value[key] not in {'tls','starttls'} for key in ('imap_security','smtp_security')):
        raise ValueError('verified implicit TLS or STARTTLS required for both mail protocols')
    password=value['password']
    if (not isinstance(password,str) or not 8<=len(password)<=4096 or password!=password.strip()
            or any(not 32<=ord(c)<=126 for c in password)):
        raise ValueError('bounded private account/app password required; no control characters')
    return dict(value)


def scope(value):
    return 'mailbox:'+digest([value['address'],value['imap_host'],value['imap_port'],'INBOX'])


def message_id(value):
    return isinstance(value,str) and len(value)<=256 and value.isascii() and _MESSAGE.fullmatch(value) is not None


def validate_binding(binding):
    address(binding['sender'])
    if binding['chat']!=binding['sender'] or not re.fullmatch(r'mailbox:[0-9a-f]{64}',binding['scope']):
        raise ValueError('email requires the same exact sender/chat address and configured mailbox scope')
    if binding['thread'] and not message_id(binding['thread']):raise ValueError('exact bounded email root Message-ID required; no wildcard thread')
    if not binding.get('generation') or type(binding.get('since')) is not int:
        raise ValueError('email requires an explicit timed owner grant')


class PreparedEmailPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'email'})

    def __init__(self,value):
        super().__init__(value)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']=='email':validate_binding(binding)


def authority(connector,value,expected=None):
    """Read the root publication on every worker boundary; no cached owner grant."""
    from pathlib import Path
    from .gateway_publication import pending
    from .sandbox import trusted_json
    config=Path('/etc/haos')
    if pending(config):raise PermissionError('email owner publication requires recovery')
    raw=trusted_json(config/'gateways.json');policy=PreparedEmailPolicy(raw)
    if policy.connectors.get(connector,{}).get('platform')!='email':raise PermissionError('configured email connector required')
    for binding in policy.bindings.values():
        if binding['connector']==connector and (binding['scope']!=scope(value) or binding['sender']==value['address']):
            raise PermissionError('email owner route differs from configured receiving mailbox')
    identity=digest(raw)
    if pending(config) or expected is not None and identity!=expected:raise PermissionError('email owner publication changed')
    return identity
