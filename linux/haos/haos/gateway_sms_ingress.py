"""Signed durable SMS admission before the actual pinned webhook decoder."""
import asyncio
import base64
import hmac
import hashlib
from contextvars import ContextVar
from datetime import datetime,timezone
import re
from types import MethodType
from urllib.parse import urlencode

from .gateway import Conflict,digest
from .gateway_sms import envelope,form,snapshot,validate_binding

_CURRENT=ContextVar('haos_retained_sms',default=None)


async def capture(adapter,raw,signature):
    return await _capture(adapter,raw,signature,origin='signed-webhook')


async def _capture(adapter,raw,signature,*,origin):
    value=adapter._haos_sms_value;native=adapter._haos_native;policy=native.policy()
    adapter._haos_sms_check()
    if not isinstance(signature,str) or not re.fullmatch(r'[A-Za-z0-9+/]{27}=',signature):
        raise PermissionError('bounded Twilio signature required')
    values=form(raw)
    if not adapter._validate_twilio_signature(value['tls']['public_url'],values,signature):
        raise PermissionError('invalid Twilio signature')
    source=envelope(values,value)
    try:binding=policy.authorize(native.connector,source)
    except PermissionError:return None  # Signed unknown callers get no lookup, reply or mission.
    validate_binding(binding,require_epoch=True)
    from .gateway_media import approved
    count=int(values.get('NumMedia','0'))
    if count and (not approved(binding) or 'create' not in binding['capabilities']):return None
    if any(native.inbox.redactor.text(text)!=text for text in values.values()):
        raise PermissionError('private SMS credential reflection refused')
    identity=native.inbox.key(native.connector,source)
    prior=native.inbox.db.execute('SELECT binding_digest,fingerprint FROM native_inbox WHERE id=?',(identity,)).fetchone()
    if prior is not None:
        if prior['binding_digest']!=digest(binding) or prior['fingerprint']!=digest(source):
            raise Conflict('retained SMS replay changed grant or body')
        return identity
    def current():
        adapter._haos_sms_check();current_policy=native.policy()
        current_policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        return current_policy
    stamp=await adapter._haos_sms_rest.message(values,binding,current)
    items=await adapter._haos_sms_rest.media(values,current) if count else []
    if any(not approved(binding,item['kind']) for item in items):return None
    identity=native.inbox.admit(current(),native.connector,source,{'form':values,'signature':signature,'media':items,'origin':origin},received_at=stamp)
    native.inbox.db.execute('CREATE TABLE IF NOT EXISTS sms_input_origins (identity TEXT PRIMARY KEY, origin TEXT NOT NULL, binding_digest TEXT NOT NULL)')
    native.inbox.db.execute('INSERT OR IGNORE INTO sms_input_origins VALUES (?,?,?)',(identity,origin,digest(binding)))
    return identity


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_sms_decode_lock:
        row=native.inbox.claim(key,native.policy())
        if row is None:return False
        state={'adapter':adapter,'row':row,'accepted':False,'media':[],'codec_text':row['payload']['form']['Body'].strip()};token=_CURRENT.set(state)
        spawned=[]
        try:
            adapter._haos_sms_check()
            payload=row['payload']
            if set(payload)=={'form','signature'} and payload['form'].get('NumMedia','0')=='0':payload={**payload,'media':[]}
            if 'origin' not in payload:payload={**payload,'origin':'signed-webhook'}
            if payload.get('origin') not in {'signed-webhook','authenticated-api-recovery'}:raise PermissionError('unknown SMS admission origin')
            if set(payload)!={'form','signature','media','origin'} or envelope(payload['form'],adapter._haos_sms_value)!=row['envelope']:
                raise PermissionError('retained SMS source changed')
            if not adapter._validate_twilio_signature(adapter._haos_sms_value['tls']['public_url'],payload['form'],payload['signature']):
                raise PermissionError('retained original SMS signature changed')
            codec_form=dict(payload['form']);codec_signature=payload['signature']
            if payload['media']:
                from .gateway_sms_media import download
                state['media']=await asyncio.wait_for(download(adapter,row),30)
                if not codec_form['Body'].strip():
                    # The pinned text decoder ignores empty bodies. After real
                    # original signature/resource/grant verification, feed it a
                    # local placeholder under this unforgeable retained context.
                    codec_form['Body']='[approved MMS attachment]';state['codec_text']=codec_form['Body']
                    signed=adapter._haos_sms_value['tls']['public_url']+''.join(key+codec_form[key] for key in sorted(codec_form))
                    codec_signature=base64.b64encode(hmac.new(adapter._auth_token.encode(),signed.encode(),hashlib.sha1).digest()).decode()
            class Request:
                content_length=len(urlencode(codec_form).encode())
                headers={'X-Twilio-Signature':codec_signature}
                async def read(self):return urlencode(codec_form).encode()
            before=set(adapter._background_tasks)
            response=await adapter._haos_sms_decode(adapter,Request())
            spawned=list(set(adapter._background_tasks)-before)
            if response.status!=200:raise PermissionError('actual native SMS decoder refused retained message')
            if spawned:await asyncio.wait_for(asyncio.gather(*spawned),10)
            native.policy().current_binding(row);native.inbox.complete(key,state['accepted'])
            return state['accepted']
        except BaseException:
            for task in spawned:
                if not task.done():task.cancel()
            if spawned:await asyncio.gather(*spawned,return_exceptions=True)
            native.inbox.retry(key);raise
        finally:_CURRENT.reset(token)


def install(adapter):
    from .gateway_runtime import adapter_envelope
    original_build=adapter.build_source;original_handle=adapter.handle_message
    adapter._haos_sms_decode=type(adapter)._handle_webhook;adapter._haos_sms_decode_lock=asyncio.Lock()
    async def deny(_self,*_args,**_kwargs):raise PermissionError('SMS requires retained independent owner admission')
    def source(self,**kwargs):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained SMS source')
        row=state['row']['envelope'];self._haos_native.policy().current_binding(state['row'])
        kwargs.update(chat_id=row['chat'],user_id=row['sender'],scope_id=row['scope'],thread_id=None,message_id=row['message_id'],is_bot=False)
        return original_build(**kwargs)
    async def handle(self,event):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained SMS decoder context')
        self._haos_sms_check();self._haos_native.policy().current_binding(state['row'])
        event.timestamp=datetime.fromtimestamp(state['row']['created_at'],timezone.utc)
        if event.text!=state['codec_text']:raise PermissionError('native SMS codec changed retained text')
        if state['media']:
            from .gateway_media_relay import event_scope
            from gateway.platforms.event import MessageType
            kinds={item['descriptor']['kind'] for item in state['media']}
            kind=next(iter(kinds)) if len(kinds)==1 else 'document'
            event.message_type={'image':MessageType.PHOTO,'voice':MessageType.VOICE,'video':MessageType.VIDEO,'document':MessageType.DOCUMENT}[kind]
            event.text=state['row']['envelope']['text']
            ids=[item['id'] for item in state['media']]
            types=['image/'+item['descriptor']['format'] if item['descriptor']['kind']=='image' else 'application/octet-stream' for item in state['media']]
            event.media_urls=['haos-media:'+identity for identity in ids];event.media_types=types
            with event_scope(event,ids,types,platform='sms'):
                if adapter_envelope(event,'sms')!=state['row']['envelope']:raise PermissionError('native MMS source changed')
                await original_handle(event)
        else:
            if adapter_envelope(event,'sms')!=state['row']['envelope']:raise PermissionError('native SMS codec changed approved source')
            await original_handle(event)
        state['accepted']=event._gateway_accepted is True
    for name in ['connect','_handle_webhook','send','send_typing','send_image','send_image_file','send_document','send_voice','send_video']:
        setattr(adapter,name,MethodType(deny,adapter))
    adapter.build_source=MethodType(source,adapter);adapter.handle_message=MethodType(handle,adapter)
    return adapter
