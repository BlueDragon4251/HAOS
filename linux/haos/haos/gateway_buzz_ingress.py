"""Native Buzz decoding from verified originals with persistent independent claims."""
import asyncio
import copy
from contextvars import ContextVar
from datetime import datetime,timezone
import json
from types import MethodType,SimpleNamespace

from .gateway import Conflict,digest
from .gateway_buzz import scope
from .gateway_buzz_admission import Refused,thread

_CURRENT=ContextVar('haos_retained_buzz',default=None)


async def capture(adapter,channel,event):
    native=adapter._haos_native;adapter._haos_buzz_check()
    try:item=await adapter._haos_buzz_raw.capture(native.policy(),native.connector,adapter._haos_buzz_value,
        json.dumps(event,separators=(',',':'),ensure_ascii=False).encode())
    except Refused:return False
    if item['envelope']['chat']!=channel:raise Conflict('Buzz original differs from subscribed channel')
    prior=adapter._haos_buzz_raw.db.execute('SELECT admitted_receipt FROM buzz_raw_events WHERE id=?',(item['id'],)).fetchone()
    if prior['admitted_receipt'] and not native.inbox.db.execute('SELECT 1 FROM native_inbox WHERE id=?',(item['source_key'],)).fetchone():
        raise Conflict('settled Buzz original lost native receipt; automatic restoration refused')
    key=native.inbox.admit(native.policy(),native.connector,item['envelope'],{'raw_id':item['id']},received_at=item['received_at'])
    if key!=item['source_key']:raise Conflict('Buzz original and native ingress identities differ')
    state=native.inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()
    if state['state']=='committed':adapter._haos_buzz_raw.admitted(item['id'],key)
    adapter._haos_buzz_check();return True


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_buzz_decode_lock:
        adapter._haos_buzz_check();row=native.inbox.claim(key,native.policy())
        if row is None:
            settled=native.inbox.db.execute('SELECT * FROM native_inbox WHERE id=?',(key,)).fetchone()
            if settled is None or settled['state']!='committed':return False
            original=adapter._haos_buzz_raw.db.execute('SELECT id FROM buzz_raw_events WHERE source_key=?',(key,)).fetchone()
            if original is None:raise Conflict('committed Buzz ingress lost retained source mapping')
            item=await adapter._haos_buzz_raw.get(native.policy(),native.connector,adapter._haos_buzz_value,original['id'])
            if (settled['connector']!=native.connector or settled['platform']!='buzz' or settled['message_id']!=item['envelope']['message_id']
                    or settled['binding_id']!=item['binding_id'] or settled['binding_digest']!=item['binding_digest']
                    or settled['fingerprint']!=digest(item['envelope'])):raise Conflict('Buzz committed receipt changed its retained source')
            adapter._haos_buzz_raw.admitted(item['id'],key);return True
        context={'adapter':adapter,'row':row,'accepted':False};token=_CURRENT.set(context);channel_state=None;before=None
        try:
            if not isinstance(row['payload'],dict) or set(row['payload'])!={'raw_id'}:raise Conflict('exact retained Buzz source required')
            item=await adapter._haos_buzz_raw.get(native.policy(),native.connector,adapter._haos_buzz_value,row['payload']['raw_id'])
            if item['source_key']!=key or item['envelope']!=row['envelope']:raise Conflict('Buzz retained ingress projection changed')
            context['item']=item
            if item['resources']:raise PermissionError('private Buzz media decoding is not installed yet')
            event=json.loads(item['raw']);channel=row['envelope']['chat']
            channel_state=adapter._channel_state.setdefault(channel,adapter._new_channel_state('group'))
            before=copy.deepcopy(channel_state)
            # NativeInbox, not its bounded volatile seen set, owns this pending
            # retry. Failed decoding must roll back native pre-dispatch mutation.
            channel_state['seen'].pop(event['id'],None)
            from .gateway_matrix_profile import scope
            with scope(adapter._haos_buzz_home,adapter._haos_buzz_environment):
                await adapter._haos_buzz_decode(adapter,channel,channel_state,event)
            adapter._haos_buzz_check();native.policy().current_binding(row)
            if not context['accepted']:raise Conflict('native Buzz decoder did not produce durable HAOS admission')
            native.inbox.complete(key,True)
            adapter._haos_buzz_raw.admitted(item['id'],key)
            return True
        except BaseException as error:
            if channel_state is not None and before is not None:
                channel_state.clear();channel_state.update(before)
            native.inbox.retry(key)
            if isinstance(error,Conflict):native.inbox.db.execute("UPDATE native_inbox SET state='failed' WHERE id=? AND state='pending'",(key,))
            raise
        finally:_CURRENT.reset(token)


def install(adapter):
    from plugins.platforms.buzz.adapter import BuzzAdapter
    if (not isinstance(adapter,BuzzAdapter) or not callable(getattr(adapter,'set_durable_message_handler',None))
            or hasattr(adapter,'_haos_buzz_decode')):raise TypeError('one actual durable native Buzz adapter required')
    adapter._haos_buzz_decode=BuzzAdapter._handle_event;adapter._haos_buzz_decode_lock=asyncio.Lock()
    original_source=adapter.build_source;original_handle=adapter.handle_message
    def current(self):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('independently retained Buzz decode context required')
        self._haos_buzz_check();self._haos_native.policy().current_binding(state['row']);return state
    def source(self,**kwargs):
        state=current(self);row=state['row']['envelope']
        if any(kwargs.get(name)!=row[key] for name,key in [('chat_id','chat'),('user_id','sender'),('message_id','message_id')]):
            raise Conflict('native Buzz source changed independently verified identity')
        kwargs.update(scope_id=row['scope'],thread_id=row['thread'],is_bot=False,user_id_alt=None)
        return original_source(**kwargs)
    async def handle(self,event):
        state=current(self);envelope=state['row']['envelope'];raw=json.loads(state['item']['raw'])
        if event.raw_message!=raw or event.media_urls or event.media_types or event.text!=self._strip_mention(raw['content']):
            raise Conflict('native Buzz text or resource projection changed')
        # Retain the first actual native command projection and the exact codec
        # inputs. Display-name changes must not change an already admitted goal.
        from plugins.platforms.buzz.adapter import BuzzAdapter,hex_to_npub
        db=self._haos_native.inbox.db
        db.execute('''CREATE TABLE IF NOT EXISTS buzz_native_projection(
            source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            credential_scope TEXT NOT NULL,normalizer TEXT NOT NULL,text TEXT NOT NULL)''')
        prior=db.execute('SELECT * FROM buzz_native_projection WHERE source_key=?',(state['item']['source_key'],)).fetchone()
        inputs={'_display_name':self._display_name,'_self_pubkey':self._self_pubkey,'_self_npub':self._self_npub}
        if prior is not None:
            if (prior['raw_id']!=state['item']['id'] or prior['binding_digest']!=state['item']['binding_digest']
                    or prior['credential_scope']!=state['item']['credential_scope'] or len(prior['normalizer'].encode())>4096):
                raise Conflict('retained Buzz native projection changed its original or grant')
            try:inputs=json.loads(prior['normalizer'])
            except (ValueError,RecursionError):raise Conflict('invalid retained Buzz normalizer') from None
        if (not isinstance(inputs,dict) or set(inputs)!={'_display_name','_self_pubkey','_self_npub'}
                or not isinstance(inputs['_display_name'],str) or len(inputs['_display_name'].encode())>1024
                or inputs['_self_pubkey']!=self._haos_buzz_value['public_key'] or inputs['_self_npub']!=hex_to_npub(inputs['_self_pubkey'])):
            raise Conflict('native Buzz command normalizer differs from exact private account')
        text=BuzzAdapter._strip_mention(SimpleNamespace(**inputs),raw['content'])
        if not text:raise PermissionError('Buzz source has no actionable text after native mention decoding')
        if prior is None:
            db.execute('INSERT INTO buzz_native_projection VALUES(?,?,?,?,?,?)',(state['item']['source_key'],state['item']['id'],
                state['item']['binding_digest'],state['item']['credential_scope'],json.dumps(inputs,separators=(',',':')),text))
        elif prior['text']!=text:raise Conflict('retained Buzz native command projection differs from its actual codec')
        event.text=text;event.raw_message=None;event.channel_prompt=None
        event.timestamp=datetime.fromtimestamp(state['item']['received_at'],timezone.utc)
        from .gateway_runtime import adapter_envelope
        projected={**envelope,'text':text}
        self._haos_native.policy().authorize(self._haos_native.connector,projected)
        if adapter_envelope(event,'buzz')!=projected:raise Conflict('native Buzz envelope differs from retained approval')
        await original_handle(event);state['accepted']=event._gateway_accepted is True
    async def receive(self,channel,state,event):
        if not await capture(self,channel,event):return
        from .gateway_raw import NativeInbox
        key=NativeInbox.key(self._haos_native.connector,{'platform':'buzz','scope':scope(self._haos_buzz_value),
            'chat':channel,'thread':thread(event),'message_id':event['id']})
        await dispatch_stored(self,key)
    async def deny(_self,*_args,**_kwargs):raise PermissionError('Buzz operation has no reviewed private capability')
    async def no_reaction(_self,*_args,**_kwargs):return False
    for name,method in {'build_source':source,'handle_message':handle,'_handle_event':receive,'send_reaction':no_reaction}.items():
        setattr(adapter,name,MethodType(method,adapter))
    for name in ['connect','send','send_image','send_image_file','send_document','edit_message','delete_message',
            '_download_attachment','_localize_inbound_media']:
        setattr(adapter,name,MethodType(deny,adapter))
    # The native dispatcher calls this even for text. Admit an unchanged text
    # projection only inside the verified no-resource context above.
    async def text_only(self,text,message_id,**kwargs):
        state=current(self);row=state['row']['envelope']
        if (state['item']['resources'] or message_id!=row['message_id'] or kwargs.get('user_id')!=row['sender']
                or kwargs.get('chat_id')!=row['chat']):raise PermissionError('retained Buzz media capability required')
        from gateway.platforms.base import MessageType
        return text,[],[],MessageType.TEXT
    adapter._localize_inbound_media=MethodType(text_only,adapter)
    return adapter
