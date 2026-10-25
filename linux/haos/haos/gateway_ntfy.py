"""Prepared ntfy admission: exact trusted topic, never publisher-supplied identity.

Not enabled by public GatewayPolicy or the owner GUI until transport, delivery
and recovery are integrated. No platform/plugin discovery or network startup.
"""
import asyncio
from contextvars import ContextVar
import re
import time
from types import MethodType

from .gateway import GatewayPolicy, SUPPORTED, digest

_CURRENT = ContextVar('haos_ntfy_source', default=None)
_TOPIC = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_EVENT = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


class PreparedNtfyPolicy(GatewayPolicy):
    platforms = frozenset(SUPPORTED | {'ntfy'})

    def __init__(self, config):
        super().__init__(config)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform'] != 'ntfy':
                continue
            if (not _TOPIC.fullmatch(binding['chat']) or binding['sender'] != binding['chat']
                    or binding['scope'] or binding['thread']
                    or binding.get('trust_topic_publishers') is not True
                    or type(binding.get('since')) is not int or not binding.get('generation')):
                raise ValueError('ntfy requires explicit trust of all publishers to one exact private topic; no individual sender identity')


def snapshot(policy, connector):
    if policy.connectors.get(connector, {}).get('platform') != 'ntfy':
        raise PermissionError('exact prepared ntfy connector required')
    return {'connector': connector, 'bindings': [digest(b) for b in policy.bindings.values() if b['connector'] == connector]}


def envelope(event, topic):
    if (not isinstance(topic, str) or not _TOPIC.fullmatch(topic) or not isinstance(event, dict)
            or event.get('event') != 'message' or event.get('topic') != topic
            or not isinstance(event.get('id'), str) or not _EVENT.fullmatch(event['id'])
            or type(event.get('time')) is not int or event['time'] <= 0
            or not isinstance(event.get('message'), str) or not 1 <= len(event['message'].strip().encode()) <= 4096
            or any(name in event for name in ('attachment', 'actions', 'click', 'encoding'))
            or not isinstance(event.get('tags', []), list)
            or any(not isinstance(tag, str) for tag in event.get('tags', []))
            or 'hermes-agent' in event.get('tags', [])):
        return None
    # title, sender, user and display names carry no identity authority on ntfy.
    return {'platform': 'ntfy', 'sender': topic, 'chat': topic, 'scope': '', 'thread': '',
            'message_id': event['id'], 'is_bot': False, 'text': event['message'].strip()}


def capture(adapter, event, authority):
    source = envelope(event, adapter._topic)
    if source is None:
        return None
    native = adapter._haos_native
    policy = native.policy()
    binding = policy.authorize(native.connector, source)
    original = event['time'] * 1000
    if (not isinstance(authority, dict) or authority.get('connector') != native.connector
            or digest(binding) not in authority.get('bindings', [])
            or original <= binding['since'] or original > time.time() * 1000 + 300000):
        raise PermissionError('ntfy original is outside the captured owner grant')
    return native.inbox.admit(policy, native.connector, source, {'event': event}, received_at=event['time'])


async def dispatch_stored(adapter, key):
    from gateway.platforms.helpers import MessageDeduplicator
    native = adapter._haos_native
    async with adapter._haos_ntfy_lock:
        row = native.inbox.claim(key, native.policy())
        if row is None:
            return False
        try:
            native.policy().current_binding(row)
            event = row['payload']['event']
            if envelope(event, adapter._topic) != row['envelope']:
                raise PermissionError('retained ntfy source differs from the captured topic')
            state = {'adapter': adapter, 'row': row, 'accepted': False}
            token = _CURRENT.set(state)
            before = adapter._dedup
            try:
                # HAOS owns durable replay. Native TTL dedup cannot erase a
                # retry after an interrupted/failed durable admission.
                adapter._dedup = MessageDeduplicator(max_size=1, ttl_seconds=300)
                await adapter._haos_ntfy_decode(adapter, event)
                native.policy().current_binding(row)
                native.inbox.complete(key, state['accepted'])
                return state['accepted']
            finally:
                adapter._dedup = before
                _CURRENT.reset(token)
        except BaseException:
            native.inbox.retry(key)
            raise


def install(adapter):
    """Wrap only one actual bundled adapter; no public enablement or receive loop."""
    from .gateway_runtime import adapter_envelope
    adapter._haos_ntfy_decode = type(adapter)._on_message
    adapter._haos_ntfy_lock = asyncio.Lock()
    original_handle = adapter.handle_message

    async def retained(self, event):
        state = _CURRENT.get()
        if state is None or state['adapter'] is not self:
            raise PermissionError('ntfy native decoder has no retained owner source')
        self._haos_native.policy().current_binding(state['row'])
        if adapter_envelope(event, 'ntfy') != state['row']['envelope']:
            raise PermissionError('native ntfy decoder changed source identity')
        await original_handle(event)
        state['accepted'] = event._gateway_accepted is True

    async def receive(self, event):
        raise PermissionError('ntfy transport requires durable capture before native decoding')

    adapter.handle_message = MethodType(retained, adapter)
    adapter._on_message = MethodType(receive, adapter)
    return adapter
