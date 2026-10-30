"""Exact-source Photon replies through the actual native Python send codec."""
import asyncio
from contextvars import ContextVar
import hashlib
from types import MethodType

from .gateway import Conflict, digest
from .gateway_event_context import validate
from .gateway_photon_outbox import Journal

_SENDING = ContextVar('haos_photon_outbox', default=None)


class Publisher:
    def __init__(self, adapter):
        from plugins.platforms.photon.adapter import PhotonAdapter
        if not isinstance(adapter, PhotonAdapter): raise TypeError('actual pinned Photon adapter required')
        self.adapter = adapter; self.native = adapter._haos_native; self.lock = asyncio.Lock()
        def current():
            adapter._haos_photon_check()
            if not adapter._haos_photon_health.permitted(): raise PermissionError('Photon native transport or retry budget refused')
        self.current = current
        self.journal = Journal(self.native.inbox, adapter._haos_photon_originals, self.native.connector,
            adapter._haos_photon_value, self.native.policy, adapter._haos_photon_check)
        publisher = self
        async def send(self, chat, content, reply_to=None, metadata=None):
            return await publisher.send(chat, content, reply_to, metadata)
        async def native_text(self, chat, text, **kwargs):
            state = publisher.context()
            if kwargs or chat != state['wire']['spaceId'] or text != state['formatted']:
                raise PermissionError('exact current Photon native text invocation required')
            return await PhotonAdapter._sidecar_send(self, chat, text, richlink=False, markdown=False)
        async def deny_unreviewed(self, *args, **kwargs):
            raise PermissionError('Photon operation requires its own independently approved native capability')
        adapter.send = MethodType(send, adapter); adapter._sidecar_send = MethodType(native_text, adapter)
        # Refuse at the public method boundary, before inherited helpers can
        # fetch an arbitrary URL or open an agent-supplied filesystem path.
        for name in ['send_image', 'send_animation', 'send_video', 'send_voice', 'send_document', 'send_file',
                'send_media_group', 'send_poll', 'edit_message', 'delete_message', 'send_typing', 'react_to_message', 'set_reaction']:
            if hasattr(adapter, name): setattr(adapter, name, MethodType(deny_unreviewed, adapter))

    def context(self):
        state = _SENDING.get()
        if state is None or state['publisher'] is not self or state['task'] is not asyncio.current_task():
            raise PermissionError('current exact Photon output task capability required')
        state['current'](); return state

    def packet(self, path, body):
        state = self.context()
        if path != '/send' or body != {key: state['wire'][key] for key in ['spaceId', 'text']} or state['used']:
            raise PermissionError('one unchanged native Photon text packet required')
        state['used'] = True
        return dict(state['wire'])

    async def send(self, chat, content, reply_to, metadata):
        from gateway.platforms.base import BasePlatformAdapter, SendResult
        from plugins.platforms.photon.adapter import PhotonAdapter, _sidecar_payload_text
        from .gateway_delivery_authority import current_delivery
        authority = current_delivery(self.adapter, 'photon', chat, metadata)
        context = validate(metadata.get('haos_event_context'))
        if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != context['content_sha256']:
            raise Conflict('Photon controller content differs from its event context')
        files, _ = BasePlatformAdapter.extract_media(content)
        if files or metadata.get('haos_output') is not None:
            raise PermissionError('Photon files require a separately approved sealed native output path')
        formatted = self.adapter.format_message(content)
        wire_text = _sidecar_payload_text(formatted, False)
        binding = self.native.policy().current_binding(metadata['haos_binding']); thread = metadata.get('thread_id', '')
        delivery_id = metadata.get('haos_delivery_id'); attempt = metadata.get('haos_delivery_attempt')
        def current():
            self.current(); authority()
            if not self.adapter.is_connected: raise PermissionError('live private Photon transport required')
            self.journal.source(binding, reply_to, thread)
        async with self.lock:
            current()
            intent = self.journal.prepare(binding, delivery_id, attempt, reply_to, thread, content, wire_text, digest(context))
            if intent['state'] == 'confirmed':
                return SendResult(success=True, message_id=intent['receipt'], raw_response={'upstream_acceptance_only': True, 'recipient_read_verified': False})
            if intent['state'] == 'uncertain':
                return SendResult(success=False, error='Photon write requires inspected recovery', raw_response={'haos_delivery': 'uncertain'})
            state = {'publisher': self, 'task': asyncio.current_task(), 'current': current, 'wire': intent['wire'], 'used': False, 'formatted': formatted}
            token = _SENDING.set(state)
            try:
                result = await PhotonAdapter.send(self.adapter, chat, content, reply_to=reply_to, metadata=metadata)
                current()
                if result.success is not True or not state['used']:
                    outcome = self.journal.result(delivery_id, attempt)
                    return SendResult(success=False, error='Photon native write has no acceptance receipt',
                        retryable=outcome == 'not-dispatched', retry_after=2,
                        raw_response={'haos_delivery': outcome if outcome == 'not-dispatched' else 'uncertain'})
                self.journal.result(delivery_id, attempt, result.message_id)
                return SendResult(success=True, message_id=result.message_id,
                    raw_response={'upstream_acceptance_only': True, 'recipient_read_verified': False})
            except asyncio.CancelledError:
                self.journal.result(delivery_id, attempt); raise
            except Exception:
                outcome = self.journal.result(delivery_id, attempt)
                return SendResult(success=False, error='Photon output requires inspected recovery', retryable=outcome == 'not-dispatched', retry_after=2,
                    raw_response={'haos_delivery': outcome if outcome == 'not-dispatched' else 'uncertain'})
            finally: _SENDING.reset(token)
