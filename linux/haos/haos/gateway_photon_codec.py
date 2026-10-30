"""Retained Photon bytes through the actual native adapter without agent/plugins."""
import asyncio
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
from types import MethodType

from .gateway import Conflict, digest
from .gateway_dingtalk_admission import parse
from .gateway_photon_custody import normalized

_CURRENT = ContextVar('haos_photon_native_source', default=None)


@contextmanager
def media_scope(event):
    if event.media_urls:
        from .gateway_media_relay import event_scope
        with event_scope(event, [url.removeprefix('haos-media:') for url in event.media_urls], event.media_types, platform='photon'):
            yield
    else:
        yield


def install(adapter):
    from plugins.platforms.photon.adapter import PhotonAdapter
    if not isinstance(adapter, PhotonAdapter) or not callable(getattr(adapter, '_haos_admit', None)) or hasattr(adapter, '_haos_photon_admit'):
        raise TypeError('one actual durable native Photon adapter required')
    original = adapter._haos_admit

    def admit(self, event):
        state = _CURRENT.get()
        if state is None or state['adapter'] is not self or state['task'] is not asyncio.current_task():
            raise PermissionError('no independently retained Photon codec context')
        self._haos_photon_check(); self._haos_native.policy().current_binding(state['proof'])
        if state['mode'] == 'decode':
            if state['event'] is not None or event.source is None:
                raise Conflict('Photon native codec emitted more than one source')
            expected = state['proof']['envelope']; source = event.source
            if (getattr(source.platform, 'value', None) != 'photon' or source.user_id != expected['sender']
                    or source.chat_id != expected['chat'] or event.message_id != expected['message_id']
                    or source.is_bot is not False):
                raise Conflict('Photon native codec changed source identity')
            source.scope_id = expected['scope']; source.thread_id = expected['thread'] or None
            event.user_id = source.user_id; event.channel_prompt = None; event.raw_message = None
            event.text = self._haos_native.inbox.redactor.text(event.text)
            state['event'] = event
        elif state['mode'] == 'dispatch' and state['event'] is event:
            from .gateway_runtime import adapter_envelope
            with media_scope(event):
                if adapter_envelope(event, 'photon') != state['row']['envelope']:
                    raise Conflict('Photon source differs from durable parent projection')
                original(event)
        else:
            raise PermissionError('no exact Photon parent dispatch context')

    adapter._haos_photon_admit = original; adapter._haos_admit = MethodType(admit, adapter)
    adapter._haos_photon_decode_lock = asyncio.Lock()
    return adapter


def _parts(content):
    if content['type'] == 'reply':
        return _parts(content['content'])
    if content['type'] == 'group':
        return [part for item in content['items'] for part in _parts(item['content'])]
    return [content] if content['type'] in {'attachment', 'voice'} else []


async def decode(adapter, identity):
    from plugins.platforms.photon import adapter as native
    from .gateway_media import describe, authorize, MAX_IMAGE_BYTES
    from .gateway_media_relay import MediaCache
    adapter._haos_photon_check(); context = adapter._haos_native; policy = context.policy()
    row, proof = adapter._haos_photon_originals.load(identity, policy, context.connector, adapter._haos_photon_value)
    if not row['normalized']:
        raise Conflict('Photon original has no durable native conversion')
    value = adapter._haos_photon_value
    projected, checksums = normalized(bytes(row['normalized']), parse(bytes(row['raw'])), proof, value)
    body = projected['content']['content'] if projected['content']['type'] == 'reply' else projected['content']
    copies = {}
    for payload in _parts(body):
        aid = payload['id']; data = base64.b64decode(payload['data'], validate=True)
        kind = 'voice' if payload['type'] == 'voice' or payload['mimeType'].startswith('audio/') else 'image' if payload['mimeType'].startswith('image/') else 'video' if payload['mimeType'].startswith('video/') else 'document'
        descriptor = describe(data, kind)
        if descriptor['sha256'] != checksums[aid]['sha256']:
            raise Conflict('Photon attachment differs from durable native checksum')
        if kind == 'image' and payload['mimeType'] != {'png': 'image/png', 'jpeg': 'image/jpeg'}[descriptor['format']]:
            raise Conflict('Photon image MIME differs from retained magic')
        if kind == 'video' and payload['mimeType'] != {'mp4': 'video/mp4', '3gp': 'video/3gpp', '3g2': 'video/3gpp2'}[descriptor['format']]:
            raise Conflict('Photon video MIME differs from retained magic')
        copies[aid] = {'payload': payload, 'data': data, 'descriptor': descriptor, 'url': 'haos-media:' + digest([identity, aid])}
    if sum(copy['descriptor']['size'] for copy in copies.values() if copy['descriptor']['kind'] == 'image') > MAX_IMAGE_BYTES:
        raise Conflict('Photon aggregate image budget exceeded')

    def cached(payload, name, mime, *, force_audio=False):
        copy = copies.get(payload.get('id'))
        if (copy is None or payload != copy['payload'] or name != payload['name'] or mime != payload['mimeType']
                or hashlib.sha256(base64.b64decode(payload['data'], validate=True)).hexdigest() != copy['descriptor']['sha256']):
            raise PermissionError('no exact independently retained Photon attachment capability')
        return copy['url']

    with native.attachment_cache(cached):
        text, _, _, _ = native._normalize_content(deepcopy(body))
    text = context.inbox.redactor.text(text)
    envelope = {**proof['envelope'], 'text': text}
    cache = MediaCache(context.inbox)
    for copy in copies.values():
        adapter._haos_photon_check(); policy = context.policy(); policy.current_binding(proof)
        kind = copy['descriptor']['kind']; authorize(policy, context.connector, envelope, kind)
        media_id = digest([context.connector, digest(policy.current_binding(proof)), digest(envelope), copy['descriptor']])
        existing = cache.db.execute('SELECT id FROM native_media_cache WHERE id=?', (media_id,)).fetchone()
        if existing:
            retained = cache.replay(policy, media_id)
            if retained['descriptor'] != copy['descriptor'] or retained['data'] is not None and retained['data'] != copy['data']:
                raise Conflict('Photon retained media differs from first source')
        else:
            cache.capacity(); retained = cache.put(policy, context.connector, envelope, copy['data'], kind)
        copy['url'] = 'haos-media:' + retained['id']

    state = {'adapter': adapter, 'task': asyncio.current_task(), 'mode': 'decode', 'proof': proof, 'event': None}
    token = _CURRENT.set(state)
    # Replay must not depend on native volatile URL-preview/placeholder caches.
    adapter._recent_richlinks_by_chat.clear()
    try:
        with native.attachment_cache(cached):
            await native.PhotonAdapter._dispatch_inbound(adapter, {**deepcopy(projected), 'content': deepcopy(body)})
    finally:
        _CURRENT.reset(token); adapter._recent_richlinks_by_chat.clear()
    event = state['event']
    if event is None or event.text != text:
        raise Conflict('Photon native codec produced no exact actionable projection')
    expected_urls = [copies[p['id']]['url'] for p in _parts(body)]
    expected_types = [p['mimeType'] for p in _parts(body)]
    if event.media_urls != expected_urls or event.media_types != expected_types:
        raise Conflict('Photon native media differs from exact retained capabilities')
    unique = dict(zip(expected_urls, expected_types)); event.media_urls = list(unique); event.media_types = list(unique.values())
    event.media_text_inlined = [False] * len(unique)
    if copies:
        from gateway.platforms.event import MessageType
        kinds = {copy['descriptor']['kind'] for copy in copies.values()}
        event.message_type = MessageType.PHOTO if kinds == {'image'} else MessageType.VOICE if kinds == {'voice'} else MessageType.VIDEO if kinds == {'video'} else MessageType.DOCUMENT
    adapter._haos_photon_check(); context.policy().current_binding(proof)
    return event, row, proof


@contextmanager
def dispatch(adapter, event, row, proof):
    state = {'adapter': adapter, 'task': asyncio.current_task(), 'mode': 'dispatch', 'proof': proof, 'event': event, 'row': row}
    token = _CURRENT.set(state)
    try:
        yield
    finally:
        _CURRENT.reset(token)
