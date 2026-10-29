"""Inline native DingTalk routing: durable independent custody precedes ACK.

This guard requires a separately authenticated, bounded private socket owner.
It does not open connections, authorize senders or install native plugins.
"""
import asyncio
from contextvars import ContextVar
import inspect
import re
from types import MethodType

from .gateway_dingtalk import identity
from .gateway_dingtalk_admission import MAX_EVENT, Refused, parse, milliseconds

_FRAME = ContextVar('haos_retained_dingtalk_frame', default=None)


def install(client, capture, current):
    from dingtalk_stream import ChatbotMessage
    from dingtalk_stream.stream import DingTalkStreamClient
    from dingtalk_stream.handlers import CallbackHandler, SystemHandler
    from dingtalk_stream.frames import AckMessage, SystemMessage
    if (type(client) is not DingTalkStreamClient or not callable(capture) or not callable(current)
            or hasattr(client, '_haos_frame_guard') or client._is_event_required
            or client.callback_handler_map):
        raise PermissionError('one unconfigured private native DingTalk client required')
    lock = asyncio.Lock()
    client._haos_frame_guard = True

    class Retained(CallbackHandler):
        async def process(self, message):
            state = _FRAME.get()
            if (state is None or state['client'] is not client or message.data != state['data']
                    or message.headers.message_id != state['message_id']
                    or message.headers.topic != ChatbotMessage.TOPIC):
                raise Refused('changed-native-source')
            current()
            result = capture(state['raw'])
            receipt = await result if inspect.isawaitable(result) else result
            current()
            if not isinstance(receipt, str) or not re.fullmatch('[0-9a-f]{64}', receipt):
                raise PermissionError('explicit durable DingTalk input receipt required before ACK')
            # No native incoming handler: it ACKs early and starts a reaction
            # before independent sender approval. Keep the SDK ACK codec itself.
            return AckMessage.STATUS_OK, 'OK'

    handler = Retained()
    client.register_callback_handler(ChatbotMessage.TOPIC, handler)
    original = DingTalkStreamClient.route_message

    async def route(self, raw):
        if lock.locked():
            raise Refused('concurrent-frame')
        async with lock:
            current()
            if (self._is_event_required or self.callback_handler_map != {ChatbotMessage.TOPIC: handler}
                    or type(self.system_handler) is not SystemHandler):
                raise Refused('unreviewed-handler')
            if not isinstance(raw, bytes) or len(raw) > MAX_EVENT:
                raise Refused('unsupported-frame')
            frame = parse(raw)
            if set(frame) != {'specVersion', 'type', 'headers', 'data'} or frame['specVersion'] != '1.0':
                raise Refused('unsupported-frame')
            headers = frame['headers']
            if not isinstance(headers, dict) or len(headers) > 32:
                raise Refused('unsupported-frame')
            try:
                message_id = identity(headers['messageId'])
                if headers['contentType'] != 'application/json':
                    raise ValueError
                if 'appId' in headers and headers['appId'] != self.credential.client_id:
                    raise ValueError
                milliseconds(headers['time'])
                if not isinstance(frame['data'], str):
                    raise ValueError
                data_raw = frame['data'].encode('utf-8')
                data = parse(data_raw)
            except (KeyError, ValueError, TypeError, UnicodeError):
                raise Refused('unsupported-frame') from None
            if frame['type'] == 'CALLBACK' and headers.get('topic') == ChatbotMessage.TOPIC:
                state = {'client': self, 'data': data, 'raw': data_raw, 'message_id': message_id}
            elif frame['type'] == 'SYSTEM' and headers.get('topic') == SystemMessage.TOPIC_DISCONNECT:
                # SDK sends this control ACK and the socket owner closes it.
                # It cannot admit a message, trigger a reaction or call a plugin.
                state = None
            else:
                raise Refused('unsupported-frame')
            token = _FRAME.set(state)
            try:
                result = await original(self, frame)
                current()
                return result
            finally:
                _FRAME.reset(token)

    client._haos_route_frame = MethodType(route, client)
    client.route_message = client._haos_route_frame
    return client
