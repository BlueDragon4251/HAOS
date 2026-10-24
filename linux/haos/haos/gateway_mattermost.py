"""Private native Mattermost transport, exact owner admission and retained replay."""
from contextvars import ContextVar
import ipaddress
import json
import re
from types import MethodType
from urllib.parse import urlsplit

_ID = re.compile(r'[a-z0-9]{26}\Z')
_SENDING = ContextVar('haos_mattermost_send', default=None)
_LIMIT = 1024 * 1024
_READ_ERROR = ContextVar('haos_mattermost_read_error',default=(None,5))


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
    no POST authority. Native decoding and framing remain upstream-owned.
    """
    if not callable(allow_read):
        raise TypeError('current owner read authority required')

    async def api(self, method, path, payload=None):
        import asyncio
        import aiohttp
        route = _SENDING.get()
        read_path = (path == 'users/me' or re.fullmatch(r'channels/[a-z0-9]{26}(?:/posts(?:\?per_page=100(?:&before=[a-z0-9]{26})?)?)?', path)
                     or re.fullmatch(r'posts/[a-z0-9]{26}(?:/thread)?', path)
                     or re.fullmatch(r'users/[a-z0-9]{26}', path))
        if method == 'GET':
            _READ_ERROR.set((None,5))
            if payload is not None or not read_path or allow_read(path) is not True:
                raise PermissionError('Mattermost read is outside current owner authority')
        elif method == 'POST':
            if (path != 'posts' or route is None or route.get('adapter') is not self or not isinstance(payload, dict)
                    or set(payload) - {'channel_id', 'message', 'root_id', 'props'}
                    or payload.get('channel_id') != route['chat']
                    or payload.get('root_id', '') != route['thread']
                    or payload.get('props') != {'disable_mentions': True}
                    or not isinstance(payload.get('message'), str) or not payload['message']):
                raise PermissionError('Mattermost write is outside the exact approved route')
            if route.get('binding') is not None:
                self._haos_native.policy().current_binding(route['binding_route'])
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
                    try: route['retry_after'] = min(86400,max(1,float(response.headers.get('Retry-After','5'))))
                    except ValueError: route['retry_after'] = 5
                    if response.status >= 500:
                        route['ambiguous'] = True
                # Never log vendor bodies, tokens or untrusted exception text.
                if not 200 <= response.status < 300:
                    if method == 'GET':
                        try: delay = min(86400,max(1,float(response.headers.get('Retry-After','5'))))
                        except ValueError: delay = 5
                        _READ_ERROR.set((response.status,delay))
                    return {}
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    limit=8*_LIMIT if method=='GET' and '/posts?' in path else _LIMIT
                    if len(data) > limit:
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
        except aiohttp.ClientConnectorError:
            if method == 'POST': route['connect_failed'] = True
            else: _READ_ERROR.set((None,5))
            return {}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            if method == 'POST':
                route['ambiguous'] = True
            else:
                _READ_ERROR.set((None,5))
            return {}

    async def preserving(self, chat_id, payload, metadata):
        # Native notify fallback must never move an approved thread to a channel.
        return await self._api_post('posts', payload)

    adapter._api = MethodType(api, adapter)
    adapter._post_preserving_thread = MethodType(preserving, adapter)
    return adapter


async def send_native(adapter, original_send, chat, content, thread='', *, binding=None):
    """Run actual native formatting/chunking with exact thread identity preserved."""
    if not isinstance(chat, str) or not _ID.fullmatch(chat) or (thread and (
            not isinstance(thread, str) or not _ID.fullmatch(thread))):
        raise ValueError('invalid Mattermost destination identity')
    route = {'adapter': adapter, 'chat': chat, 'thread': thread, 'statuses': [], 'receipts': [], 'ambiguous': False, 'binding': binding, 'retry_after': 5, 'connect_failed': False}
    if binding is not None:
        from .gateway import digest
        route['binding_route']={'binding_id':binding['id'],'binding_digest':digest(binding)}
    token = _SENDING.set(route)
    # Native root resolution performs a GET and can silently substitute a root.
    # Use the already approved thread verbatim at the private post-builder seam.
    try:
        result = await original_send(adapter, chat, content, reply_to=None,
            metadata={'thread_id': thread, 'notify': True})
        if not result.success and route['receipts']:
            route['ambiguous'] = True
        return result, route
    finally:
        _SENDING.reset(token)


def install_post_builder(adapter):
    async def post(self, chat, message, reply_to, metadata, file_ids=None):
        route = _SENDING.get()
        if route is None or route.get('adapter') is not self or chat != route['chat'] or reply_to is not None or file_ids is not None:
            raise PermissionError('Mattermost post has no exact private route')
        payload = {'channel_id': chat, 'message': message, 'props': {'disable_mentions': True}}
        if route['thread']:
            payload['root_id'] = route['thread']
        return await self._post_preserving_thread(chat, payload, metadata)
    adapter._post_message = MethodType(post, adapter)
    return adapter


class APIError(ConnectionError):
    def __init__(self, status=None, retry_after=5):
        super().__init__('Mattermost request unavailable; inspect safe transport status')
        self.status, self.retry_after = status, retry_after


_READING = ContextVar('haos_mattermost_read', default=None)
_CURRENT = ContextVar('haos_mattermost_source', default=None)


def allowed_read(adapter, path):
    if path == 'users/me':
        return True
    state = _READING.get()
    if state is None or state['adapter'] is not adapter or path not in state['paths']:
        return False
    adapter._haos_native.policy().current_binding(state['route'])
    return True


async def read(adapter, binding, path):
    from .gateway import digest
    route = {'binding_id': binding['id'], 'binding_digest': digest(binding)}
    adapter._haos_native.policy().current_binding(route)
    token = _READING.set({'adapter': adapter, 'paths': {path}, 'route': route})
    try:
        result = await adapter._api_get(path)
        adapter._haos_native.policy().current_binding(route)
        if not result:
            raise APIError(*_READ_ERROR.get())
        return result
    finally:
        _READING.reset(token)


def post_event(event):
    """Only original plain user posts; no system, bot, media or plugin events."""
    if not isinstance(event, dict) or event.get('event') != 'posted':
        return None
    data = event.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('post'), str) or len(data['post'].encode()) > 262144:
        return None
    try:
        post = json.loads(data['post'])
    except (ValueError, TypeError):
        return None
    if (not isinstance(post, dict) or post.get('type') or post.get('file_ids')
            or post.get('delete_at') or post.get('edit_at') or not isinstance(post.get('props',{}),dict)
            or post.get('props', {}).get('from_bot')
            or not isinstance(post.get('message'), str) or not 1 <= len(post['message'].strip()) <= 32000
            or any(not isinstance(post.get(key), str) or not _ID.fullmatch(post[key])
                   for key in ('id', 'user_id', 'channel_id'))
            or post.get('root_id') and (not isinstance(post['root_id'], str) or not _ID.fullmatch(post['root_id']))
            or type(post.get('create_at')) is not int or post['create_at'] <= 0):
        return None
    import time
    if post['create_at'] > time.time()*1000+300000:
        return None
    return post


def candidates(adapter, post):
    native = adapter._haos_native
    policy = native.policy()
    return [binding for binding in policy.bindings.values() if binding['connector'] == native.connector
        and binding['sender'] == post['user_id'] and binding['chat'] == post['channel_id']
        and binding['thread'] == (post.get('root_id') or '')
        and (not binding.get('since') or post['create_at'] > binding['since'])]


async def channel(adapter, binding):
    value = await read(adapter, binding, 'channels/' + binding['chat'])
    if (value.get('id') != binding['chat'] or value.get('type') not in {'D', 'G', 'O', 'P'}
            or value.get('team_id', '') != binding['scope'] or value.get('delete_at')
            or (value['type'] in {'D', 'G'}) != (binding['scope'] == '')):
        raise PermissionError('Mattermost channel differs from the exact owner team grant')
    if binding['thread']:
        root=await read(adapter,binding,'posts/'+binding['thread'])
        if (root.get('id')!=binding['thread'] or root.get('channel_id')!=binding['chat']
                or root.get('root_id') or root.get('delete_at')):
            raise PermissionError('Mattermost thread is not the approved channel root post')
    return value


async def capture(adapter, event):
    if getattr(adapter, '_haos_stopping', False):
        raise ConnectionError('private Mattermost ingress is stopping')
    post = post_event(event)
    if post is None or post['user_id'] == adapter._bot_user_id:
        return None
    matches = candidates(adapter, post)
    if len(matches) != 1:
        return None
    binding = matches[0]
    info = await channel(adapter, binding)
    user = await read(adapter, binding, 'users/' + post['user_id'])
    if user.get('id') != post['user_id'] or user.get('is_bot', False) is not False or user.get('delete_at'):
        return None
    if info['type'] != 'D' and adapter._apply_channel_gating(binding['chat'], post['message']) is None:
        return None
    envelope = {'platform': 'mattermost', 'sender': post['user_id'], 'chat': post['channel_id'],
        'scope': binding['scope'], 'thread': post.get('root_id') or '', 'message_id': post['id'],
        'is_bot': False, 'text': post['message']}
    native = adapter._haos_native
    policy = native.policy()
    policy.authorize(native.connector, envelope)
    retained = {'event': 'posted', 'data': {'post': json.dumps(post,ensure_ascii=False), 'channel_type': info['type']}}
    return native.inbox.admit(policy, native.connector, envelope, retained, received_at=post['create_at']/1000)


async def dispatch_stored(adapter, original, key):
    import asyncio
    if getattr(adapter, '_haos_stopping', False):
        return False
    native = adapter._haos_native
    row = native.inbox.claim(key, native.policy())
    if row is None:
        return False
    tasks = getattr(adapter, '_haos_receive_tasks', None)
    if tasks is None:
        tasks = adapter._haos_receive_tasks = set()
    task = asyncio.current_task(); tasks.add(task)
    token = _CURRENT.set({'adapter': adapter, 'source': row['envelope'], 'accepted': False})
    try:
        post = post_event(row['payload'])
        if post is None or any(row['envelope'][key] != value for key, value in {
                'sender': post['user_id'], 'chat': post['channel_id'], 'thread': post.get('root_id') or '',
                'message_id': post['id']}.items()):
            raise ValueError('retained Mattermost input differs from its approved source')
        with secret_scope(adapter):
            await original(adapter, row['payload'])
        native.policy().current_binding(row)
        accepted = _CURRENT.get()['accepted']
        native.inbox.complete(key, accepted)
        return accepted
    except BaseException:
        native.inbox.retry(key)
        raise
    finally:
        _CURRENT.reset(token); tasks.discard(task)


def admitted(adapter, accepted):
    state = _CURRENT.get()
    if state is not None and state['adapter'] is adapter:
        state['accepted'] = accepted is True


def secret_scope(adapter):
    from .gateway_slack import secret_scope as scoped
    return scoped(adapter._haos_secrets, adapter._haos_secret_home)



TRANSPORT_KINDS = {'connecting','connected','disconnected','authentication-refused','transport-unavailable'}


def transport_status(adapter, kind):
    import time
    if kind not in TRANSPORT_KINDS:raise ValueError('invalid Mattermost transport status')
    native=getattr(adapter,'_haos_native',None)
    if native is None:return
    db=native.inbox.db
    db.execute('CREATE TABLE IF NOT EXISTS mattermost_transport (connector TEXT PRIMARY KEY,status TEXT NOT NULL,updated_at REAL NOT NULL)')
    db.execute('INSERT INTO mattermost_transport(connector,status,updated_at) VALUES(?,?,?) '
        'ON CONFLICT(connector) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at',
        (native.connector,kind,time.time()))


def install(adapter):
    """Private instance hooks preserve native decoding/formatting and WS client."""
    import asyncio
    original = type(adapter)
    adapter._haos_native_dispatch = original._handle_ws_event
    original_build = adapter.build_source
    original_listen = adapter._ws_connect_and_listen
    original_mark = adapter._mark_connected
    original_connect = adapter.connect
    original_send = original.send
    class NoVolatileDedup:
        def is_duplicate(self, _identity): return False
    adapter._dedup = NoVolatileDedup()
    install_post_builder(install_api(adapter, lambda path: allowed_read(adapter, path)))

    def build(self, **kwargs):
        state = _CURRENT.get()
        if state is None or state['adapter'] is not self:
            raise PermissionError('Mattermost decoder has no retained owner source')
        kwargs['scope_id'] = state['source']['scope'] or None
        return original_build(**kwargs)

    async def dispatch(self, event):
        if isinstance(event, dict) and type(event.get('seq_reply')) is int and event['seq_reply'] == 1:
            if event.get('status') == 'OK':
                self._haos_authenticated = True
                transport_status(self,'connected')
                original_mark()
            else:
                self._closing = True
                transport_status(self,'authentication-refused')
                self._set_fatal_error('mattermost_auth_error', 'Mattermost WebSocket authentication rejected; check the private owner token.', retryable=False)
                if self._ws: await self._ws.close()
                await self._notify_fatal_error()
            self._haos_auth_ready.set()
            return
        if not getattr(self, '_haos_authenticated', False):
            return
        key = await capture(self, event)
        if key is not None:
            await dispatch_stored(self, self._haos_native_dispatch, key)

    async def listen(self):
        self._haos_authenticated = False
        self._mark_disconnected()
        try:
            await original_listen()
        finally:
            self._haos_authenticated = False
            if not self.has_fatal_error:transport_status(self,'disconnected')
            self._mark_disconnected()

    async def connect(self):
        if self.has_fatal_error and not self._fatal_error_retryable:
            return False
        self._haos_auth_ready = asyncio.Event()
        transport_status(self,'connecting')
        with secret_scope(self):
            if not await original_connect():
                code=_READ_ERROR.get()[0]
                transport_status(self,'authentication-refused' if code in {401,403} else 'transport-unavailable')
                return False
            try:await asyncio.wait_for(self._haos_auth_ready.wait(), 15)
            except TimeoutError:
                transport_status(self,'transport-unavailable')
                raise
        return self.is_connected

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        from gateway.platforms.base import SendResult
        metadata = metadata or {}
        native = self._haos_native
        try:
            binding = native.policy().current_binding(metadata['haos_binding'])
            if (binding['connector'] != native.connector or binding['chat'] != chat_id
                    or binding['scope'] != metadata.get('haos_scope')
                    or binding['thread'] != (metadata.get('thread_id') or '') or 'read' not in binding['capabilities']):
                raise PermissionError('Mattermost outgoing route differs from its current owner grant')
            await channel(self, binding)
        except (PermissionError, KeyError, ValueError):
            return SendResult(success=False,error='Mattermost owner route refused',error_kind='forbidden',raw_response={'haos_delivery':'refused'})
        except APIError as error:
            return SendResult(success=False,error='Mattermost destination verification unavailable',
                error_kind='forbidden' if error.status in {401,403,404} else 'rate_limited' if error.status==429 else 'unknown',
                retryable=error.status not in {401,403,404},retry_after=error.retry_after,
                raw_response={'haos_delivery':'refused' if error.status in {401,403,404,429} else 'not-dispatched'})
        result, route = await send_native(self,original_send,chat_id,content,binding['thread'],binding=binding)
        if result.success:
            return result
        if route['ambiguous'] or route['receipts']:
            return SendResult(success=False,error='Mattermost delivery outcome uncertain',error_kind='unknown')
        statuses = route['statuses']
        if statuses == [429]:
            return SendResult(success=False,error='Mattermost rate limit',error_kind='rate_limited',
                retry_after=route['retry_after'],raw_response={'haos_delivery':'refused'})
        if len(statuses)==1 and statuses[0] in {400,401,403,404,413}:
            return SendResult(success=False,error='Mattermost post refused',
                error_kind='too_long' if statuses[0]==413 else 'not_found' if statuses[0]==404 else 'forbidden',
                raw_response={'haos_delivery':'refused'})
        if route['connect_failed'] and not statuses:
            return SendResult(success=False,error='Mattermost connection unavailable',retryable=True,
                raw_response={'haos_delivery':'not-dispatched'})
        return SendResult(success=False,error='Mattermost delivery outcome uncertain',error_kind='unknown')

    def session_get(self): return self.__dict__.get('_haos_mm_session')
    def session_set(self, value):
        if value is not None:
            import aiohttp
            trace = aiohttp.TraceConfig()
            async def no_redirect(*_args):
                raise PermissionError('Mattermost redirects cannot receive private gateway authority')
            trace.on_request_redirect.append(no_redirect)
            trace.freeze()
            value.trace_configs.append(trace)
        self.__dict__['_haos_mm_session'] = value

    adapter.__class__ = type('PrivateMattermost', (original,), {'__module__': __name__,
        '_session': property(session_get, session_set), 'connect': connect, 'send': send,
        '_handle_ws_event': dispatch, '_ws_connect_and_listen': listen,
        '_mark_connected': lambda self, **kwargs: None, 'build_source': build})
    return adapter
