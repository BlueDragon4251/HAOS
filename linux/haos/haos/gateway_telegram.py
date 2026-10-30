"""Hold the pinned PTB polling offset until native HAOS admission finishes."""
import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

_CURRENT = ContextVar('haos_telegram_admission', default=None)
_APPLICATIONS = {}


def failed():
    state = _CURRENT.get()
    if state is not None:
        state.failed = True


def admitted():
    state = _CURRENT.get()
    if state is not None:
        state.resolved = True


def accept_native(adapter, original):
    state = _CURRENT.get()
    # Hermes's native text dispatcher marks handoff BEFORE calling its agent
    # dispatcher. HAOS's actual handoff is the synchronous durable inbox write.
    if state is None or state.resolved:
        return original(adapter)


def install(application):
    from telegram import Update
    from telegram.error import NetworkError
    original = type(application)
    if isinstance(application.update_queue, AdmissionQueue):
        return
    if original not in _APPLICATIONS:
        class DurableApplication(original):
            __slots__ = ()
            async def process_error(self, *args, **kwargs):
                failed()
                return await super().process_error(*args, **kwargs)
        _APPLICATIONS[original] = DurableApplication
    application.__class__ = _APPLICATIONS[original]
    queue = AdmissionQueue(application, Update, NetworkError)
    application.update_queue = queue
    application.updater.update_queue = queue


class AdmissionQueue(asyncio.Queue):
    """Actual Updater awaits put before it confirms getUpdates' next offset.

    Dispatch directly through Application.process_update, serially and using its
    native handlers. The ordinary queue remains for PTB's own shutdown sentinel.
    No process-wide SDK patch, alternate Bot client or transport receipt mock.
    """
    def __init__(self, application, update_type, network_error):
        super().__init__()
        self.application, self.update_type, self.network_error = application, update_type, network_error
        self.lock = asyncio.Lock()

    async def put(self, update):
        if not isinstance(update, self.update_type):
            return await super().put(update)
        async with self.lock:
            state = SimpleNamespace(failed=False, resolved=False)
            token = _CURRENT.set(state)
            try:
                await self.application.process_update(update)
                if state.failed:
                    raise self.network_error('HAOS local durable admission unavailable; update remains unconfirmed')
            finally:
                _CURRENT.reset(token)


_SENDING = ContextVar('haos_telegram_delivery', default=None)


async def send_native(adapter, original, chat_id, content, reply_to=None, metadata=None):
    from gateway.platforms.base import SendResult
    from .gateway_delivery_authority import current_delivery
    metadata=metadata or {}
    state = _SENDING.get()
    try:current=current_delivery(adapter,'telegram',chat_id,metadata)
    except PermissionError:
        if state is not None:state.refused=True
        return SendResult(success=False,error='current exact owner Telegram grant required',error_kind='unknown'
            if state is not None and state.successful else 'forbidden',
            raw_response={} if state is not None and state.successful else {'haos_delivery':'refused'})
    owner=(str(chat_id),metadata['haos_binding']['binding_id'],metadata['haos_binding']['binding_digest'],
        metadata['haos_scope'],metadata.get('thread_id',''))
    token = None
    if state is None:
        state = SimpleNamespace(started=False,successful=0,refused=False,current=current,adapter=adapter,owner=owner)
        token = _SENDING.set(state)
    elif state.adapter is not adapter or state.owner!=owner:
        state.refused=True
        return SendResult(success=False,error='nested Telegram delivery changed owner authority',
            error_kind='unknown' if state.successful else 'forbidden',
            raw_response={} if state.successful else {'haos_delivery':'refused'})
    try:
        result = await original(adapter,chat_id,content,reply_to,metadata)
        if state.refused:
            return SendResult(success=False,error='Telegram owner authority changed before a native write',
                error_kind='unknown' if state.successful else 'forbidden',
                raw_response={} if state.successful else {'haos_delivery':'refused'})
        if result.success:
            ids = result.raw_response.get('message_ids') if isinstance(result.raw_response, dict) else None
            ids = ids or [result.message_id]
            if any(not isinstance(value, (str, int)) or isinstance(value, bool)
                    or not str(value).isascii() or not str(value).isdigit() or len(str(value)) > 19
                    or not 0 < int(value) < 2**63 for value in ids):
                from gateway.platforms.base import SendResult
                return SendResult(success=False, error='Telegram returned no valid delivery identity', error_kind='unknown')
        if not state.started and not result.success:
            raw = dict(result.raw_response) if isinstance(result.raw_response, dict) else {}
            if 'haos_delivery' not in raw:
                result.raw_response = {**raw, 'haos_delivery': 'not-dispatched'}
        return result
    finally:
        if token is not None: _SENDING.reset(token)


async def send_chunk(adapter, chat_id, chunk, index, reply_to, metadata, thread_id, used_thread_fallback, error_types):
    from gateway.platforms.base import SendResult
    from plugins.platforms.telegram.adapter import normalize_telegram_chat_id
    private_topic, reply_off, reply_id = adapter._chunk_reply_routing(chat_id, reply_to, metadata, thread_id, index)
    if private_topic and reply_id is None and not reply_off:
        return SendResult(success=False, error='owner thread requires an existing anchor', error_kind='not_found',
            raw_response={'haos_delivery': 'refused'})
    route = adapter._thread_kwargs_for_send(chat_id, thread_id, metadata,
        reply_to_message_id=reply_id, reply_to_mode=adapter._reply_to_mode)
    if thread_id is not None:
        expected = adapter._message_thread_id_for_send(thread_id)
        if expected is None or route.get('message_thread_id') != expected or used_thread_fallback:
            return SendResult(success=False, error='owner thread cannot be changed', error_kind='not_found',
                raw_response={'haos_delivery': 'refused'})
    kwargs = {'chat_id': normalize_telegram_chat_id(chat_id), 'reply_to_message_id': reply_id,
        **route, **adapter._link_preview_kwargs(), **adapter._notification_kwargs(metadata)}
    return await send_formatted(adapter, chunk, kwargs), False


async def send_formatted(adapter, chunk, kwargs):
    from telegram.constants import ParseMode
    from telegram.error import BadRequest
    from plugins.platforms.telegram.adapter import _await_with_thread_deadline, _TEXT_SEND_DEADLINE, _strip_mdv2
    state = _SENDING.get()
    async def dispatch(text, parse_mode):
        if state is not None:
            try:state.current()
            except PermissionError:
                state.refused=True;raise
            state.started=True
        result=await _await_with_thread_deadline(adapter._bot.send_message(text=text, parse_mode=parse_mode, **kwargs),
            timeout=_TEXT_SEND_DEADLINE, label='haos-telegram-send', dump_on_blocked_loop=False)
        if state is not None:state.successful+=1
        return result
    try:
        return await dispatch(chunk, ParseMode.MARKDOWN_V2)
    except BadRequest as error:
        # Only an explicit Bot API formatting refusal permits this native codec
        # fallback. A parser/network exception is not evidence of non-delivery.
        if not any(value in str(error).lower() for value in ('parse', 'markdown')):
            raise
        return await dispatch(_strip_mdv2(chunk), None)


def classify_send(error):
    from gateway.platforms.base import SendResult, classify_send_error
    from telegram.error import BadRequest, Forbidden, RetryAfter
    import httpx
    if isinstance(error, (BadRequest, Forbidden, RetryAfter)):
        retry = error.retry_after if isinstance(error, RetryAfter) else None
        if hasattr(retry, 'total_seconds'): retry = retry.total_seconds()
        return SendResult(success=False, error='Telegram refused the request', error_kind=classify_send_error(error),
            retryable=isinstance(error, RetryAfter), retry_after=retry, raw_response={'haos_delivery': 'refused'})
    cause = error
    for _ in range(8):
        if isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
            return SendResult(success=False, error='Telegram connection was not established', error_kind='transient',
                retryable=True, raw_response={'haos_delivery': 'not-dispatched'})
        cause = getattr(cause, '__cause__', None)
        if cause is None: break
    return SendResult(success=False, error='Telegram delivery requires owner inspection', error_kind='unknown',
        raw_response={'haos_delivery': 'ambiguous'})
