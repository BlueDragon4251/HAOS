"""Private vendor-returned media URLs: public pinned DNS, TLS, no credentials."""
import asyncio
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit, parse_qsl

from .gateway_dingtalk_http import Failure
from .gateway_media import MAX_BYTES, MAX_IMAGE_BYTES


class ContentFailure(PermissionError):
    def __init__(self, kind, retry_after=0):
        if (kind not in {'content-refused','content-rate-limited'} or type(retry_after) is not int
                or not 0 <= retry_after <= 86400 or kind != 'content-rate-limited' and retry_after):
            raise ValueError('finite private content diagnostic required')
        super().__init__('private DingTalk content server refused the resource')
        self.kind=kind;self.retry_after=retry_after


def validate_url(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 16384 or any(not 33 <= ord(char) <= 126 for char in url):
        raise Failure('invalid-response')
    try:
        parsed = urlsplit(url); host = parsed.hostname
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in {None, 443}
                or parsed.fragment or not host or len(host) > 253 or parsed.path and not parsed.path.startswith('/')
                or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.'))
                or len(host.split('.')) < 2):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
    except (ValueError, UnicodeError):
        raise Failure('invalid-response') from None
    return url


def public_address(value):
    try:
        ip = ipaddress.ip_address(value)
        return (ip.is_global and not ip.is_multicast and not ip.is_reserved
                and (not isinstance(ip, ipaddress.IPv6Address)
                     or ip in ipaddress.ip_network('2000::/3') and ip.sixtofour is None and ip.teredo is None))
    except ValueError:
        return False


class PublicResolver:
    async def resolve(self, host, port=443, family=socket.AF_INET):
        # aiohttp connects to these reviewed numeric answers, rather than doing
        # another hostname resolution between policy check and TLS connection.
        answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM), 5)
        if not 1 <= len(answers) <= 32 or any(not public_address(answer[4][0]) for answer in answers):
            raise Failure('invalid-response')
        unique = {}
        for af, proto_type, proto, _canonical, address in answers:
            if af not in {socket.AF_INET, socket.AF_INET6} or proto_type != socket.SOCK_STREAM or address[1] != port:
                raise Failure('invalid-response')
            unique[(af, address[0])] = {'hostname': host, 'host': address[0], 'port': port,
                'family': af, 'proto': proto, 'flags': socket.AI_NUMERICHOST}
        return list(unique.values())
    async def close(self):
        pass


async def fetch(url, kind, current, redactor):
    """Only a separately authenticated native lookup may supply this private URL."""
    import aiohttp
    from yarl import URL
    limit = MAX_IMAGE_BYTES if kind == 'image' else MAX_BYTES
    context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=context, resolver=PublicResolver(), use_dns_cache=False,
                                    limit=1, limit_per_host=1)
    async with aiohttp.ClientSession(connector=connector, trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False,
            timeout=aiohttp.ClientTimeout(total=20, sock_connect=5, sock_read=10)) as client:
        client._retry_connection = False
        for attempt in range(3):
            current(); url = validate_url(url)
            secrets = [url, *(value for _key, value in parse_qsl(urlsplit(url).query) if len(value) >= 8)]
            redactor.secrets = sorted(set([*redactor.secrets, *secrets]), key=len, reverse=True)
            try:
                async with client.get(URL(url, encoded=True), headers={'Accept-Encoding': 'identity'}, allow_redirects=False) as response:
                    current(); status = response.status
                    if status in {401, 403}: raise ContentFailure('content-refused')
                    if status == 429:
                        from .gateway_retry import retry_after
                        raise ContentFailure('content-rate-limited',retry_after(response.headers.get('Retry-After'),
                            default=60,private_values=redactor.secrets))
                    if 300 <= status < 400:
                        if attempt == 2: raise Failure('redirect-refused')
                        location = response.headers.get('Location', '')
                        if not location or len(location) > 16384: raise Failure('redirect-refused')
                        url = validate_url(urljoin(url, location)); continue
                    if status != 200 or response.headers.get('Content-Range') is not None:
                        raise Failure('server-refused')
                    if response.headers.get('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                        raise Failure('invalid-response')
                    if response.content_length is not None and not 0 < response.content_length <= limit:
                        raise Failure('response-too-large')
                    mime = response.headers.get('Content-Type', 'application/octet-stream').split(';', 1)[0].strip().lower()
                    if not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}', mime):
                        raise Failure('invalid-response')
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        current(); data.extend(chunk)
                        if len(data) > limit: raise Failure('response-too-large')
                    current()
                    if not data or response.content_length is not None and len(data) != response.content_length:
                        raise Failure('truncated-response')
                    raw = bytes(data)
                    if any(secret.encode() in raw for secret in redactor.secrets):
                        raise Failure('invalid-response')
                    return raw, mime
            except (Failure,ContentFailure):
                raise
            except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientConnectorSSLError):
                raise Failure('tls-refused') from None
            except aiohttp.ClientPayloadError:
                raise Failure('truncated-response') from None
            except aiohttp.ClientConnectorDNSError as error:
                if isinstance(error.__cause__, Failure):
                    raise error.__cause__ from None
                raise Failure('transport-unavailable') from None
            except Exception:
                raise Failure('transport-unavailable') from None
    raise Failure('redirect-refused')
