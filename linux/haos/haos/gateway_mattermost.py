"""Private Mattermost transport boundaries; not a public gateway enablement."""
from contextvars import ContextVar
import ipaddress
import json
import re
from types import MethodType
from urllib.parse import urlsplit

_ID = re.compile(r'[a-z0-9]{26}\Z')
_SENDING = ContextVar('haos_mattermost_send', default=None)
_LIMIT = 1024 * 1024


def server_url(value):
    """Owner-selected HTTPS origin, optionally with a literal deployment prefix."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError('provide a bounded Mattermost HTTPS server URL')
    if any(ord(c) < 33 or ord(c) > 126 for c in value) or '\\' in value or '%' in value:
        raise ValueError('Mattermost URL contains ambiguous characters')
    try:
        url = urlsplit(value)
        host, port = url.hostname, url.port
    except ValueError:
        raise ValueError('invalid Mattermost server URL') from None
    if (url.scheme != 'https' or not host or url.username is not None or url.password is not None
            or url.query or url.fragment or '?' in value or '#' in value
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Mattermost requires an explicit HTTPS server without credentials, query or fragment')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', host) or any(
                not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in host.split('.')):
            raise ValueError('invalid Mattermost server hostname') from None
    prefix = url.path.rstrip('/')
    if prefix and (not re.fullmatch(r'(?:/[A-Za-z0-9._~-]+)+', prefix)
                   or any(part in {'.', '..'} for part in prefix.split('/'))):
        raise ValueError('invalid Mattermost deployment prefix')
    authority = '[' + host + ']' if ':' in host else host.lower()
    if port is not None and port != 443:
        authority += ':' + str(port)
    return 'https://' + authority + prefix


def validate_credentials(token, url):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,4096}', token):
        raise ValueError('provide one private Mattermost access token')
    return server_url(url)


def install_api(adapter, allow_read):
    """Constrain the actual native adapter's REST seam, without global patches.

    The caller supplies current owner read authority. Outgoing context is private
    to send_native; arbitrary native media, typing, edits and flat fallback have
    no POST authority. Public runtime integration remains deliberately disabled.
    """
    if not callable(allow_read):
        raise TypeError('current owner read authority required')

    async def api(self, method, path, payload=None):
        import asyncio
        import aiohttp
        route = _SENDING.get()
        read_path = (path == 'users/me' or re.fullmatch(r'channels/[a-z0-9]{26}(?:/posts)?', path)
                     or re.fullmatch(r'posts/[a-z0-9]{26}(?:/thread)?', path))
        if method == 'GET':
            if payload is not None or not read_path or allow_read(path) is not True:
                raise PermissionError('Mattermost read is outside current owner authority')
        elif method == 'POST':
            if (path != 'posts' or route is None or not isinstance(payload, dict)
                    or set(payload) - {'channel_id', 'message', 'root_id', 'props'}
                    or payload.get('channel_id') != route['chat']
                    or payload.get('root_id', '') != route['thread']
                    or payload.get('props') != {'disable_mentions': True}
                    or not isinstance(payload.get('message'), str) or not payload['message']):
                raise PermissionError('Mattermost write is outside the exact approved route')
            self._last_post_status, self._last_post_error = None, ''
        else:
            raise PermissionError('Mattermost media, edits and other writes are not authorized')
        try:
            async with self._session.request(method, self._base_url + '/api/v4/' + path,
                    headers=self._headers(), json=payload if method == 'POST' else None,
                    allow_redirects=False, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if method == 'POST':
                    self._last_post_status = response.status
                    route['statuses'].append(response.status)
                    if response.status >= 500:
                        route['ambiguous'] = True
                # Never log vendor bodies, tokens or untrusted exception text.
                if not 200 <= response.status < 300:
                    return {}
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > _LIMIT:
                        raise ValueError('Mattermost API response exceeds private bound')
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError('Mattermost API response must be an object')
                if method == 'POST':
                    if (not isinstance(value.get('id'), str) or not _ID.fullmatch(value['id'])
                            or value.get('channel_id') != route['chat']
                            or value.get('root_id', '') != route['thread']):
                        raise ValueError('Mattermost receipt does not match the approved route')
                    route['receipts'].append(value['id'])
                return value
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            if method == 'POST':
                route['ambiguous'] = True
            return {}

    async def preserving(self, chat_id, payload, metadata):
        # Native notify fallback must never move an approved thread to a channel.
        return await self._api_post('posts', payload)

    adapter._api = MethodType(api, adapter)
    adapter._post_preserving_thread = MethodType(preserving, adapter)
    return adapter


async def send_native(adapter, original_send, chat, content, thread=''):
    """Run actual native formatting/chunking with exact thread identity preserved."""
    if not isinstance(chat, str) or not _ID.fullmatch(chat) or (thread and (
            not isinstance(thread, str) or not _ID.fullmatch(thread))):
        raise ValueError('invalid Mattermost destination identity')
    route = {'chat': chat, 'thread': thread, 'statuses': [], 'receipts': [], 'ambiguous': False}
    token = _SENDING.set(route)
    # Native root resolution performs a GET and can silently substitute a root.
    # Use the already approved thread verbatim at the private post-builder seam.
    try:
        result = await original_send(adapter, chat, content, reply_to=None,
            metadata={'thread_id': thread, 'notify': True})
        return result, route
    finally:
        _SENDING.reset(token)


def install_post_builder(adapter):
    async def post(self, chat, message, reply_to, metadata, file_ids=None):
        route = _SENDING.get()
        if route is None or chat != route['chat'] or reply_to is not None or file_ids is not None:
            raise PermissionError('Mattermost post has no exact private route')
        payload = {'channel_id': chat, 'message': message, 'props': {'disable_mentions': True}}
        if route['thread']:
            payload['root_id'] = route['thread']
        return await self._post_preserving_thread(chat, payload, metadata)
    adapter._post_message = MethodType(post, adapter)
    return adapter
