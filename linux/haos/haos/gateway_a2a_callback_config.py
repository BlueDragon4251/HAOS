"""Owner-approved callback destinations, separate from named-peer bearer tokens."""
import ipaddress
import re
from urllib.parse import urlsplit,urlunsplit


def destination(url):
    if not isinstance(url,str) or not 1<=len(url)<=2048 or any(ord(c)<33 or ord(c)>126 for c in url) or '\\' in url:
        raise ValueError('bounded exact HTTPS callback destination required')
    try:parts=urlsplit(url);host=parts.hostname;port=parts.port
    except ValueError:raise ValueError('invalid A2A callback destination') from None
    if (parts.scheme!='https' or not host or parts.username is not None or parts.password is not None or parts.query or parts.fragment
            or '?' in url or '#' in url or port is not None and not 1<=port<=65535 or not parts.path.startswith('/')
            or host.lower() in {'localhost','localhost.localdomain'} or host.lower().endswith(('.localhost','.local'))):
        raise ValueError('exact HTTPS callback requires a hostname/path without credentials, query, fragment or local aliases')
    try:
        address=ipaddress.ip_address(host)
        if not address.is_global:raise ValueError('private or reserved callback literal forbidden')
    except ValueError as error:
        if not re.fullmatch(r'(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}',host):
            raise ValueError('public callback hostname or global address required') from None
    authority='['+host+']' if ':' in host else host
    if port is not None and port!=443:authority+=':'+str(port)
    canonical=urlunsplit(('https',authority,parts.path,'',''))
    if canonical!=url:raise ValueError('canonical exact HTTPS callback destination required')
    return url


def callbacks(value,peers):
    if not isinstance(value,dict) or not set(value)<=set(peers):raise ValueError('callbacks require exact configured named peers')
    result={};secrets=set()
    for peer,item in value.items():
        if not isinstance(item,dict) or set(item)!={'url','secret'}:raise ValueError('exact owner callback destination and separate signing secret required')
        url=destination(item['url']);secret=item['secret']
        if (not isinstance(secret,str) or not re.fullmatch('[A-Za-z0-9_-]{32,128}',secret) or secret in secrets
                or any(token in secret or secret in token for token in peers.values())
                or any(token in url for token in [secret,*peers.values()])):
            raise ValueError('unique callback signing key must be separate from all peer bearer credentials')
        secrets.add(secret);result[peer]={'url':url,'secret':secret}
    if any(secret in item['url'] for secret in secrets for item in result.values()):
        raise ValueError('callback signing keys cannot appear in callback destinations')
    return dict(sorted(result.items()))
