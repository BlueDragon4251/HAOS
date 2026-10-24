"""Use pinned transport adapters without their separate agent/plugin dispatcher."""
import inspect

_CLASSES = {}


def durable_adapter(adapter):
    """Cooperative MRO preserves native transport overrides around HAOS admission.

    In particular Telegram keeps its update tracking; its call to the shared
    dispatcher reaches our synchronous durable boundary instead of a debounce
    timer or background agent task. No process-wide upstream monkey patch.
    """
    from gateway.platforms.base import BasePlatformAdapter
    original = type(adapter)
    if original in _CLASSES.values():
        return adapter
    if not isinstance(adapter, BasePlatformAdapter):
        raise TypeError('pinned platform adapter required')
    if original not in _CLASSES:
        class DurableIngress(BasePlatformAdapter):
            def set_durable_message_handler(self, handler):
                if not callable(handler) or inspect.iscoroutinefunction(handler):
                    raise TypeError('durable gateway admission must be synchronous')
                self._haos_ingress = handler

            def _haos_admit(self, event):
                event._gateway_accepted = False
                handler = getattr(self, '_haos_ingress', None)
                if handler is None:
                    raise PermissionError('HAOS durable admission is not installed')
                accepted = handler(event)
                if inspect.isawaitable(accepted):
                    if callable(getattr(accepted, 'close', None)):
                        accepted.close()
                    raise TypeError('gateway admission cannot defer its durable commit')
                if type(accepted) is not bool:
                    raise TypeError('explicit durable admission receipt required')
                event._gateway_accepted = accepted
                if getattr(self.platform, 'value', None) == 'telegram':
                    from .gateway_telegram import admitted
                    admitted()
                    self._accept_update()

            async def handle_message(self, event):
                self._haos_admit(event)

            def _enqueue_text_event(self, event):
                self._haos_admit(event)

            async def _process_message_background(self, event, session_key):
                self._haos_admit(event)

        def no_plugins(self, *args, **kwargs):
            return None
        attributes = {'__module__': __name__, '_wire_plugin_handlers': no_plugins,
            '_register_plugin_action_handlers': no_plugins, 'rewire_plugin_handlers': no_plugins}
        if getattr(adapter.platform, 'value', None) == 'telegram':
            from . import gateway_telegram
            def register_handlers(self, app):
                gateway_telegram.install(app)
                return original._register_handlers(self, app)
            def accept_update(self):
                return gateway_telegram.accept_native(self, original._accept_update)
            def fail_preparation(self):
                gateway_telegram.failed()
                return original._fail_update_preparation(self)
            def hold_event(self, *args, **kwargs):
                gateway_telegram.failed()
                original._fail_update_preparation(self)
                return original._hold_inbound_event(self, *args, **kwargs)
            async def start_polling(self, app, *, drop_pending_updates, **kwargs):
                # A native conflict-recovery branch otherwise drops pending
                # updates. Another active consumer requires owner intervention.
                return await original._start_polling_once(self, app, drop_pending_updates=False, **kwargs)
            def telegram_authorized(self, message):
                source = self._source_from_message_for_auth(message)
                return self._is_sender_authorized(source.user_id, chat_type=source.chat_type,
                    chat_id=source.chat_id, thread_id=source.thread_id, is_bot=source.is_bot) is True
            # Native pairing/env fallback is not HAOS owner authorization.
            attributes['_is_user_authorized_from_message'] = telegram_authorized
            attributes.update(_register_handlers=register_handlers, _accept_update=accept_update,
                _fail_update_preparation=fail_preparation, _hold_inbound_event=hold_event,
                _start_polling_once=start_polling)
        _CLASSES[original] = type('HAOS' + original.__name__, (original, DurableIngress), attributes)
    adapter.__class__ = _CLASSES[original]
    if getattr(adapter.platform, 'value', None) == 'telegram':
        # Apply to every fresh adapter, including a same-process reconnect.
        # Earlier native receipts can precede HAOS's durable commit. Keep those
        # files intact and use a separate post-admission namespace.
        adapter._update_receipt_dir = adapter._update_receipt_dir / 'haos-durable-v1'
    return adapter
