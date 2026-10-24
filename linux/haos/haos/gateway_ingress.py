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
                elif getattr(self.platform, 'value', None) == 'discord':
                    from .gateway_discord import admitted
                    admitted(self, accepted)
                elif getattr(self.platform, 'value', None) == 'slack':
                    from .gateway_slack import admitted
                    admitted(self, accepted)

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
        if getattr(adapter.platform,'value',None)=='slack':
            from . import gateway_slack
            async def slack_connect(self,*args,**kwargs):
                with gateway_slack.secret_scope(self._haos_secrets,self._haos_secret_home):
                    return await original.connect(self,*args,**kwargs)
            async def slack_dispatch(self,event,payload=None):
                return await gateway_slack.dispatch(self,original._handle_slack_message,event,payload)
            async def slack_disconnect(self):
                with gateway_slack.secret_scope(self._haos_secrets,self._haos_secret_home):
                    return await original.disconnect(self)
            async def slack_send(self,chat_id,content,reply_to=None,metadata=None):
                return await gateway_slack.send_native(self,original.send,chat_id,content,reply_to,metadata)
            def register_slack(self):
                async def receive(event,body):await self._handle_slack_message(event,body)
                self._app.event('message')(receive)
                self._app.event('app_mention')(receive)
            def handler_get(self):return self.__dict__.get('_handler')
            def handler_set(self,value):
                if value is not None:gateway_slack.install_socket(self,value)
                self.__dict__['_handler']=value
            async def no_history(self,**kwargs):return None,[],[]
            async def no_title(self,*args,**kwargs):return None
            async def user_name(self,user_id,**kwargs):return user_id
            async def channel_name(self,channel_id,**kwargs):return channel_id
            async def human_mentions(self,text,**kwargs):return text
            def new_slack_client(self,*args,**kwargs):
                client=original._new_web_client(*args,**kwargs)
                return gateway_slack.install_web_client(client)
            attributes.update(connect=slack_connect,disconnect=slack_disconnect,send=slack_send,_handle_slack_message=slack_dispatch,
                _haos_native_dispatch=staticmethod(original._handle_slack_message),
                _handler=property(handler_get,handler_set),_register_bolt_handlers=register_slack,
                _early_reject_unauthorized=lambda self,user,channel,is_dm:not gateway_slack.allowed(self,user,channel),
                _channel_gate_allows=gateway_slack.channel_allowed,
                _hydrate_thread_context=no_history,_set_assistant_thread_title=no_title,
                _resolve_user_name=user_name,_resolve_channel_name=channel_name,_humanize_user_mentions=human_mentions,
                _reactions_enabled=lambda self:False,_slack_allow_bots=lambda self:'none',
                _is_block_payload_rejection=staticmethod(lambda error:gateway_slack.block_rejected(original._is_block_payload_rejection,error)),
                _clear_thread_status_quietly=no_title,stop_typing=no_title,
                _remember_processed_message_ts=no_plugins,_new_web_client=new_slack_client)
        if getattr(adapter.platform, 'value', None) == 'discord':
            from . import gateway_discord
            async def dispatch_discord(self, message):
                return await gateway_discord.dispatch(self, original._dispatch_discord_message, message)
            async def dispatch_recovered(self, message):
                return await gateway_discord.dispatch(self, original._dispatch_recovered_message, message)
            def discord_allowed(self, *args, **kwargs):
                return gateway_discord.allowed(self, *args, **kwargs)
            def discord_admission(self, message, *, claim):
                return original._discord_message_admission(self, message, claim=False)
            async def record_response(self, reply_to, result, content, final, metadata=None):
                # HAOS owns the sole persistent reply/recovery obligation.
                return result
            def client_get(self):
                return self.__dict__.get('_client')
            def client_set(self, value):
                if value is not None:
                    gateway_discord.install_capture(self, value)
                    gateway_discord.install_delivery(value)
                self.__dict__['_client'] = value
            async def send_discord(self, chat_id, content, reply_to=None, metadata=None):
                return await gateway_discord.send_native(self, original.send, chat_id, content, reply_to, metadata)
            async def resolve_discord(self, channel_id):
                return await gateway_discord.resolve_delivery(self, original._resolve_channel, channel_id)
            def rejected_reply(error):
                return gateway_discord.reply_rejected(original._is_reply_reference_rejected, error)
            attributes.update(_dispatch_discord_message=dispatch_discord, _dispatch_recovered_message=dispatch_recovered,
                _is_allowed_user=discord_allowed, _discord_message_admission=discord_admission,
                _record_response_async=record_response, _client=property(client_get, client_set),
                send=send_discord, _resolve_channel=resolve_discord, _is_reply_reference_rejected=staticmethod(rejected_reply),
                _haos_native_dispatch=staticmethod(original._dispatch_discord_message))
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
            async def send(self, chat_id, content, reply_to=None, metadata=None):
                return await gateway_telegram.send_native(self, original.send, chat_id, content, reply_to, metadata)
            async def send_chunk(self, *args, **kwargs):
                return await gateway_telegram.send_chunk(self, *args, **kwargs)
            def classify_send(self, error, error_types):
                return gateway_telegram.classify_send(error)
            def telegram_authorized(self, message):
                source = self._source_from_message_for_auth(message)
                return self._is_sender_authorized(source.user_id, chat_type=source.chat_type,
                    chat_id=source.chat_id, thread_id=source.thread_id, is_bot=source.is_bot) is True
            # Native pairing/env fallback is not HAOS owner authorization.
            attributes['_is_user_authorized_from_message'] = telegram_authorized
            attributes.update(_register_handlers=register_handlers, _accept_update=accept_update,
                _fail_update_preparation=fail_preparation, _hold_inbound_event=hold_event,
                _start_polling_once=start_polling, send=send, _send_chunk_with_retries=send_chunk,
                _classify_send_exception=classify_send, _should_attempt_rich=lambda *args, **kwargs: False)
        _CLASSES[original] = type('HAOS' + original.__name__, (original, DurableIngress), attributes)
    adapter.__class__ = _CLASSES[original]
    if getattr(adapter.platform,'value',None)=='slack':
        from . import gateway_slack
        adapter._dedup=gateway_slack.NativeDedup()
    if getattr(adapter.platform, 'value', None) == 'telegram':
        # Apply to every fresh adapter, including a same-process reconnect.
        # Earlier native receipts can precede HAOS's durable commit. Keep those
        # files intact and use a separate post-admission namespace.
        adapter._update_receipt_dir = adapter._update_receipt_dir / 'haos-durable-v1'
    return adapter
