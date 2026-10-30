"""Actual pinned DingTalk message dispatch from independently retained originals."""
import asyncio
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from types import MethodType

from .gateway import Conflict, digest
from .gateway_dingtalk_admission import parse, native_data,Refused

_CURRENT = ContextVar('haos_retained_dingtalk', default=None)


def capture(adapter, raw):
    native = adapter._haos_native; adapter._haos_dingtalk_check()
    item = adapter._haos_dingtalk_raw.capture(native.policy(), native.connector, adapter._haos_dingtalk_value, raw)
    policy = native.policy(); binding = policy.authorize(native.connector, item['envelope'])
    policy.current_binding({'binding_id': binding['id'], 'binding_digest': digest(binding)})
    native.inbox.db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_source_context(
        source_key TEXT PRIMARY KEY, connector TEXT NOT NULL, raw_id TEXT NOT NULL,
        binding_digest TEXT NOT NULL, scope TEXT NOT NULL, chat TEXT NOT NULL,
        thread TEXT NOT NULL, message_id TEXT NOT NULL, sender TEXT NOT NULL)''')
    envelope = item['envelope']
    values = (item['source_key'], native.connector, item['id'], digest(binding), envelope['scope'],
              envelope['chat'], envelope['thread'], envelope['message_id'], envelope['sender'])
    old = native.inbox.db.execute('SELECT * FROM dingtalk_source_context WHERE source_key=?', (item['source_key'],)).fetchone()
    if old is None:
        native.inbox.db.execute('INSERT INTO dingtalk_source_context VALUES(?,?,?,?,?,?,?,?,?)', values)
    elif tuple(old) != values:
        raise Conflict('DingTalk replay changed retained source or reply context')
    adapter._haos_dingtalk_check(); policy = native.policy()
    policy.current_binding({'binding_id': binding['id'], 'binding_digest': digest(binding)})
    key = native.inbox.admit(policy, native.connector, envelope, {'raw_id': item['id']}, received_at=item['received_at'])
    if key != item['source_key']:
        raise Conflict('DingTalk original and native input identities differ')
    return key


async def dispatch_stored(adapter, key):
    native = adapter._haos_native
    async with adapter._haos_dingtalk_decode_lock:
        row = native.inbox.claim(key, native.policy())
        if row is None:
            return False
        state = {'adapter': adapter, 'row': row, 'accepted': False}; token = _CURRENT.set(state)
        try:
            adapter._haos_dingtalk_check(); native.policy().current_binding(row)
            if not isinstance(row['payload'], dict) or set(row['payload']) != {'raw_id'}:
                raise ValueError('exact retained DingTalk original required')
            item = adapter._haos_dingtalk_raw.get(native.policy(), native.connector,
                adapter._haos_dingtalk_value, row['payload']['raw_id'])
            if item['envelope'] != row['envelope'] or item['source_key'] != key:
                raise Conflict('retained DingTalk projection changed')
            state['item'] = item
            from .gateway_dingtalk_media import retained
            state['resources']=await retained(adapter,row,item) if item['resources'] else []
            from dingtalk_stream import ChatbotMessage
            from plugins.platforms.dingtalk.inbound import extract_text
            message=ChatbotMessage.from_dict(native_data(parse(item['raw'])))
            state['native_text']=extract_text(message)
            from .gateway_matrix_profile import scope
            with scope(adapter._haos_dingtalk_home, adapter._haos_dingtalk_environment):
                await adapter._haos_dingtalk_decode(adapter,message)
            adapter._haos_dingtalk_check(); native.policy().current_binding(row)
            native.inbox.complete(key, state['accepted'])
            return state['accepted']
        except BaseException as error:
            native.inbox.retry(key)
            if isinstance(error,Conflict):
                # Immutable source/hash conflicts need an explicit owner
                # decision; automatic retries must not keep reading changed
                # content or attempt another mission admission.
                native.inbox.db.execute("UPDATE native_inbox SET state='failed' WHERE id=? AND state='pending'",(key,))
            if isinstance(error,Refused) and error.retry_after:
                native.inbox.db.execute("UPDATE native_inbox SET next_attempt=MAX(next_attempt,?) WHERE id=? AND state='pending'",
                    (time.time()+error.retry_after,key))
            raise
        finally:
            # The private per-source journal owns replies. Never retain a last
            # chat's session bearer as authority for some later mission's reply.
            adapter._message_contexts.clear(); adapter._session_webhooks.clear()
            _CURRENT.reset(token)


def install(adapter):
    if (not callable(getattr(adapter, 'set_durable_message_handler', None))
            or not callable(getattr(adapter, '_haos_admit', None)) or hasattr(adapter, '_haos_dingtalk_decode')):
        raise TypeError('one actual native DingTalk adapter with durable ingress MRO required')
    from plugins.platforms.dingtalk.adapter import DingTalkAdapter
    if not isinstance(adapter, DingTalkAdapter):
        raise TypeError('actual pinned DingTalk adapter required')
    adapter._haos_dingtalk_decode = DingTalkAdapter._on_message
    adapter._haos_dingtalk_decode_lock = asyncio.Lock()
    original_source = adapter.build_source; original_handle = adapter.handle_message;original_media=adapter._extract_media
    def current(self):
        state = _CURRENT.get()
        if state is None or state['adapter'] is not self:
            raise PermissionError('no independently retained native DingTalk context')
        self._haos_dingtalk_check(); self._haos_native.policy().current_binding(state['row'])
        return state
    class DurableDedup:
        def is_duplicate(self, message_id):
            state = current(adapter)
            if message_id != state['row']['envelope']['message_id']:
                raise PermissionError('native DingTalk message differs from durable input')
            return False  # NativeInbox owns the persistent claim and retry.
    def user_allowed(self, sender_id, sender_staff_id):
        return sender_id == current(self)['row']['envelope']['sender']
    def should_process(self, message, text, is_group, chat_id):
        state = current(self); raw = parse(state['item']['raw']); envelope = state['row']['envelope']
        if (message.message_id != envelope['message_id'] or chat_id != envelope['chat']
                or is_group != (str(raw['conversationType']) == '2') or text != state['native_text']):
            raise PermissionError('native DingTalk trigger differs from independently approved source')
        return True
    def source(self, **kwargs):
        row = current(self)['row']['envelope']
        if kwargs.get('chat_id') != row['chat'] or kwargs.get('user_id') != row['sender'] or kwargs.get('message_id') != row['message_id']:
            raise PermissionError('native DingTalk source changed before durable admission')
        kwargs.update(scope_id=row['scope'], thread_id='', user_id_alt=None,
                      user_name=row['sender'], chat_name=row['chat'], is_bot=False)
        return original_source(**kwargs)
    async def media(self, message):
        state = current(self)
        if (message.message_id != state['row']['envelope']['message_id']
                or len(state['item']['resources'])!=len(state['resources'])):
            raise PermissionError('DingTalk native resource lacks private retained broker capability')
        # The pinned pure codec still sees its original download codes. Only
        # extract_media below projects the independently retained local copies.
    def extract(self,message):
        state=current(self);result=original_media(message)
        if not state['resources']:return result
        _kind,codes,mimes=result;expected=state['item']['resources']
        if codes!=[part['code'] for part in expected] or mimes!=[part['mime'] for part in expected]:
            raise PermissionError('native DingTalk media codec differs from original approval')
        if any(part['resource']!=expected[index] or part['index']!=index for index,part in enumerate(state['resources'])):
            raise PermissionError('DingTalk retained resource indexes changed')
        from gateway.platforms.base import MessageType
        kinds={part['item']['descriptor']['kind'] for part in state['resources']}
        kind=MessageType.PHOTO if kinds=={'image'} else MessageType.VOICE if kinds=={'voice'} else MessageType.VIDEO if kinds=={'video'} else MessageType.DOCUMENT
        return kind,['haos-dingtalk-resource:'+str(part['index']) for part in state['resources']],[part['mime'] for part in state['resources']]
    async def handle(self, event):
        state = current(self); row = state['row']; envelope = row['envelope']
        expected=['haos-dingtalk-resource:'+str(part['index']) for part in state['resources']]
        if (event.media_urls!=expected or event.media_types!=[part['mime'] for part in state['resources']]
                or event.text!=state['native_text']):
            raise PermissionError('DingTalk native text or media differs from retained source')
        # Vendor-recognized voice text is approved as voice at original capture;
        # its textual goal does not imply a local ASR result or resource access.
        if state['item']['native_kind'] == 'voice' and not state['resources']:
            from gateway.platforms.base import MessageType
            event.message_type = MessageType.TEXT
        event.timestamp = datetime.fromtimestamp(row['created_at'], timezone.utc)
        event.raw_message = None; event.channel_prompt = None
        event.text=envelope['text']
        from .gateway_runtime import adapter_envelope
        if state['resources']:
            unique={part['item']['id']:part for part in state['resources']};ids=list(unique)
            types=[part['mime'] for part in unique.values()]
            event.media_urls=['haos-media:'+identity for identity in ids];event.media_types=types;event.media_text_inlined=[False]*len(ids)
            from .gateway_media_relay import event_scope
            with event_scope(event,ids,types,platform='dingtalk'):
                if adapter_envelope(event,'dingtalk')!=envelope:raise Conflict('native media source differs from independent approval')
                await original_handle(event)
        else:
            if adapter_envelope(event, 'dingtalk') != envelope:
                raise Conflict('native DingTalk input differs from independently approved original')
            await original_handle(event)
        state['accepted'] = event._gateway_accepted is True
    async def deny(_self, *_args, **_kwargs):
        raise PermissionError('DingTalk operation has no reviewed private capability')
    adapter._dedup = DurableDedup()
    for name, method in {'_is_user_allowed': user_allowed, '_should_process_message': should_process,
                         'build_source': source, '_resolve_media_codes': media, '_extract_media':extract,'handle_message': handle}.items():
        setattr(adapter, name, MethodType(method, adapter))
    for name in ('connect', 'send', 'send_typing', 'send_image', 'send_image_file', 'send_document',
                 'edit_message', '_get_access_token', '_send_emotion', '_create_and_stream_card',
                 '_stream_card_content', '_fetch_download_url', '_on_message'):
        setattr(adapter, name, MethodType(deny, adapter))
    return adapter
