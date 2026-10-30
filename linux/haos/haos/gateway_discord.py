"""Exact owner-scoped Discord admission, independent of native env/role grants."""
from contextvars import ContextVar
from types import SimpleNamespace
import logging

_CURRENT = ContextVar('haos_discord_owner_source', default=None)
_SENDING = ContextVar('haos_discord_delivery', default=None)


def source_envelope(adapter, message):
    thread, chat = adapter._thread_id_and_chat_for_channel(message.channel)
    guild = getattr(message, 'guild', None)
    source = adapter.build_source(chat_id=chat, chat_type='thread' if thread else 'group' if guild else 'dm',
        user_id=str(message.author.id), thread_id=thread, guild_id=str(guild.id) if guild else None,
        is_bot=bool(message.author.bot), message_id=str(message.id))
    return {'platform': 'discord', 'sender': str(source.user_id), 'chat': str(source.chat_id),
        'scope': str(source.scope_id or ''), 'thread': str(source.thread_id or ''),
        'message_id': str(message.id), 'is_bot': source.is_bot, 'text': message.content}


async def _dispatch_owner(adapter, original, message, *args, **kwargs):
    handler = getattr(adapter, '_haos_source_authorizer', None)
    if handler is None:
        return False, False
    envelope = source_envelope(adapter, message)
    if handler(envelope) is not True:
        logging.warning('Discord source refused by HAOS owner policy')
        return False, False
    reference = getattr(message, 'reference', None)
    referenced = getattr(reference, 'resolved', None)
    snapshots = getattr(message, 'message_snapshots', ()) or ()
    if (message.attachments or getattr(referenced, 'attachments', None)
            or any(getattr(item, 'attachments', None) for item in snapshots)):
        logging.warning('Discord media refused: no approved HAOS media broker configured')
        return False, False
    state = SimpleNamespace(adapter=adapter, envelope=envelope, accepted=False)
    token = _CURRENT.set(state)
    try:
        result = await original(adapter, message, *args, **kwargs)
        if state.accepted:
            # Native claim=True records before dispatch. Only HAOS's committed
            # admission may consume this cache key; a failed write can retry.
            adapter._dedup.is_duplicate(str(message.id))
        return result, state.accepted
    finally:
        _CURRENT.reset(token)


async def dispatch(adapter, original, message, *args, **kwargs):
    if getattr(adapter,'_haos_stopping',False):return False
    import asyncio
    tasks = getattr(adapter, '_haos_receive_tasks', None)
    if tasks is None:
        tasks = adapter._haos_receive_tasks = set()
    task = asyncio.current_task(); tasks.add(task)
    try:
        native = getattr(adapter, '_haos_native', None)
        if native is not None:
            key = native.inbox.find_discord(native.connector, message.id)
            if key is None: return False
            return await dispatch_stored(adapter, original, key, message)
        result, _ = await _dispatch_owner(adapter, original, message, *args, **kwargs)
        return result
    finally:
        tasks.discard(task)


async def dispatch_stored(adapter, original, key, live_message=None):
    if getattr(adapter,'_haos_stopping',False):return False
    import asyncio
    import discord
    native = adapter._haos_native
    row = native.inbox.claim(key, native.policy())
    if row is None: return False
    task = asyncio.current_task()
    tasks = getattr(adapter, '_haos_receive_tasks', None)
    if tasks is None: tasks = adapter._haos_receive_tasks = set()
    tasks.add(task)
    try:
        if adapter._dedup.contains(row['message_id']):
            # This HAOS-scoped in-memory cache is written only after the relay
            # commits. It never imports the old native response ledger.
            native.inbox.complete(key, True)
            return True
        await asyncio.wait_for(adapter._ready_event.wait(), 30)
        channel = live_message.channel if live_message is not None else await adapter._resolve_channel(row['envelope']['chat'])
        message = discord.Message(state=adapter._client._connection, channel=channel, data=row['payload'])
        source = source_envelope(adapter, message)
        fields = ('platform','sender','chat','scope','thread','message_id','is_bot')
        if any(source[name] != row['envelope'][name] for name in fields):
            raise ValueError('native replay changed its owner source context')
        result, accepted = await _dispatch_owner(adapter, original, message)
        native.policy().current_binding(row)
        native.inbox.complete(key, accepted)
        return result
    except BaseException:
        native.inbox.retry(key)
        raise
    finally:
        tasks.discard(task)


def allowed(adapter, user_id, author=None, *, guild=None, is_dm=False, channel_ids=None):
    state = _CURRENT.get()
    if state is None or state.adapter is not adapter:
        return False
    source = state.envelope
    return (source['sender'] == str(user_id) and source['is_bot'] is False
        and source['scope'] == (str(guild.id) if guild else '')
        and (is_dm and source['scope'] == '' or channel_ids is not None and source['chat'] in channel_ids))


def admitted(adapter, accepted):
    state = _CURRENT.get()
    if state is not None and state.adapter is adapter:
        state.accepted = accepted is True


def install_capture(adapter, client):
    """Private-instance SDK debug seam runs before received_message sets sequence."""
    capture = getattr(adapter, '_haos_native_capture', None)
    if capture is None or getattr(client, '_haos_capture_installed', False):
        return
    import asyncio
    import errno
    import inspect
    import json
    import sqlite3
    from .gateway import Conflict
    original = client.dispatch
    def dispatch(event, *args, **kwargs):
        if event == 'socket_raw_receive' and args:
            raw = args[0]
            if not isinstance(raw, str) or len(raw.encode()) > 1024*1024:
                raise OSError(errno.EMSGSIZE, 'native Discord frame exceeds its limit')
            data = json.loads(raw)
            if isinstance(data, dict) and data.get('op') == 0 and data.get('t') == 'MESSAGE_CREATE':
                try:
                    result = capture(client, data.get('d'))
                    if inspect.isawaitable(result):
                        if callable(getattr(result, 'close', None)): result.close()
                        raise TypeError('native capture cannot defer its durable commit')
                    if type(result) is not bool:
                        raise TypeError('explicit native capture outcome required')
                except (sqlite3.Error, Conflict, OSError, TypeError) as error:
                    # Close this exact socket. KeepAlive must stop while the SDK
                    # reconnects with the last sequence whose input was durable.
                    websocket = client.ws
                    if websocket is not None:
                        asyncio.get_running_loop().create_task(websocket.close(code=4000))
                    raise OSError(errno.ENOSPC, 'HAOS native ingress durability unavailable') from error
        return original(event, *args, **kwargs)
    client.dispatch = dispatch
    client._connection.dispatch = dispatch
    client._enable_debug_events = True
    client._haos_capture_installed = True


def install_delivery(client):
    """Observe the private client's real SDK HTTP attempts, preserving SDK nonce retries."""
    if getattr(client, '_haos_delivery_installed', False): return
    import aiohttp
    http = client.http
    trace = http.http_trace or aiohttp.TraceConfig()
    async def request_start(session,context,params):
        state=_SENDING.get()
        if state is not None:
            try:state.current()
            except PermissionError:
                state.refused=True;raise
    async def response_end(session, context, params):
        state = _SENDING.get()
        if state is not None and params.method == 'POST':
            state.statuses.append(params.response.status)
            if params.response.status >= 500: state.ambiguous = True
    async def response_error(session, context, params):
        state = _SENDING.get()
        if state is not None and params.method == 'POST':
            if isinstance(params.exception, aiohttp.ClientConnectorError):
                state.connect_failed = True
            else: state.ambiguous = True
    trace.on_request_start.append(request_start)
    trace.on_request_end.append(response_end)
    trace.on_request_exception.append(response_error)
    http.http_trace = trace
    original = http.request
    async def request(route, **kwargs):
        state = _SENDING.get()
        if state is not None:
            try:state.current()
            except PermissionError:
                state.refused=True;raise
        if state is not None and route.method not in {'GET','HEAD'}:
            payload = kwargs.get('json')
            if (route.method != 'POST' or route.path != '/channels/{channel_id}/messages'
                    or str(route.channel_id) != state.target or not isinstance(payload, dict)
                    or payload.get('enforce_nonce') is not True or not payload.get('nonce')):
                state.refused = True
                raise PermissionError('Discord delivery cannot change its approved target or idempotency contract')
            state.started = True
        kwargs['allow_redirects']=False
        try: return await original(route, **kwargs)
        except Exception as error:
            if state is not None: state.error = error
            raise
    http.request = request
    client._haos_delivery_installed = True


async def resolve_delivery(adapter, original, channel_id):
    channel = await original(adapter, channel_id)
    state = _SENDING.get()
    if state is None: return channel
    import discord
    guild = getattr(channel, 'guild', None)
    thread = isinstance(channel, discord.Thread)
    if (str(getattr(channel,'id','')) != state.target
            or not isinstance(channel,(discord.TextChannel,discord.Thread,discord.DMChannel))
            or (str(guild.id) if guild else '') != state.scope
            or thread != bool(state.thread)):
        state.refused = True
        raise PermissionError('Discord resolved target differs from owner guild/channel/thread')
    return channel


def reply_rejected(original, error):
    import discord
    return (isinstance(error,discord.HTTPException) and error.status in {400,404}
        and original(error))


async def send_native(adapter, original, chat_id, content, reply_to=None, metadata=None):
    from gateway.platforms.base import SendResult
    from .gateway_delivery_authority import current_delivery
    import discord
    metadata = metadata or {}
    try:current=current_delivery(adapter,'discord',chat_id,metadata)
    except PermissionError:
        return SendResult(success=False,error='current exact owner Discord grant required',error_kind='forbidden',
            raw_response={'haos_delivery':'refused'})
    scope, thread = metadata.get('haos_scope'), metadata.get('thread_id','')
    if not isinstance(scope,str) or thread and str(thread) != str(chat_id):
        return SendResult(success=False,error='exact owner Discord scope and thread required',error_kind='forbidden',
            raw_response={'haos_delivery':'refused'})
    state = SimpleNamespace(target=str(thread or chat_id),scope=scope,thread=thread,started=False,
        refused=False,ambiguous=False,connect_failed=False,statuses=[],error=None,current=current)
    token = _SENDING.set(state)
    try:
        result = await original(adapter,chat_id,content,reply_to,metadata)
        if result.success is True:
            ids = result.raw_response.get('message_ids') if isinstance(result.raw_response,dict) else None
            ids = ids or [result.message_id]
            if any(isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value).isascii()
                    or not str(value).isdigit() or len(str(value)) > 20 or not 0 < int(value) < 2**64 for value in ids):
                return SendResult(success=False,error='Discord returned no valid delivery identity',error_kind='unknown')
            return result
        raw = dict(result.raw_response) if isinstance(result.raw_response,dict) else {}
        error = state.error
        if state.ambiguous or any(200 <= status < 300 for status in state.statuses):
            return SendResult(success=False,error='Discord delivery outcome uncertain',error_kind='unknown')
        if state.refused:
            result.error_kind='forbidden';raw['haos_delivery']='refused'
        elif isinstance(error,discord.RateLimited):
            result.error_kind='rate_limited'; result.retry_after=error.retry_after
            raw['haos_delivery']='refused'
        elif isinstance(error,discord.HTTPException) and error.status in {400,401,403,404}:
            result.error_kind='not_found' if error.status==404 else 'bad_format' if error.status==400 else 'forbidden'
            raw['haos_delivery']='refused'
        elif not state.started or state.connect_failed and not state.statuses:
            result.retryable=True;raw['haos_delivery']='not-dispatched'
        result.raw_response=raw
        return result
    finally: _SENDING.reset(token)


def capture_envelope(adapter, client, payload, policy, connector):
    """Decode a real SDK message before the transport can acknowledge its frame."""
    import discord
    if (not isinstance(payload, dict) or payload.get('type', 0) not in {0, 19}
            or not isinstance(payload.get('content'), str) or not payload['content'].strip()
            or payload.get('attachments') or payload.get('message_snapshots')):
        logging.warning('Discord native input refused: unsupported content')
        return None
    channel, guild = client._connection._get_guild_channel(payload)
    message = discord.Message(state=client._connection, channel=channel, data=payload)
    envelope = source_envelope(adapter, message)
    if guild is None and payload.get('guild_id'):
        envelope['scope'] = str(payload['guild_id'])
    candidates = [envelope]
    if isinstance(channel, discord.PartialMessageable):
        candidates = [{**envelope, 'thread': value} for value in ('', envelope['chat'])]
    admitted = []
    for candidate in candidates:
        try: policy.authorize(connector, candidate)
        except (PermissionError, ValueError): continue
        admitted.append(candidate)
    if len(admitted) > 1:
        raise ValueError('native Discord channel context is ambiguous')
    if not admitted:
        logging.warning('Discord source refused by HAOS owner policy')
        return None
    return admitted[0]
