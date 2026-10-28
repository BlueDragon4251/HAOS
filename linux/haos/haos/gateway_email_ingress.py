"""Retained native email dispatch into independent durable HAOS admission."""
import asyncio
from contextvars import ContextVar
from datetime import datetime,timezone
from types import MethodType

from .gateway import digest,Conflict
from .gateway_email_admission import approve,Refused
from .gateway_email_codec import decode

_CURRENT=ContextVar('haos_retained_email',default=None)


def text(decoded):
    body=decoded['body'].strip();subject=decoded['subject']
    native=(f'[Subject: {subject}]\n\n{body}' if subject and not subject.startswith('Re:') else body) or '(empty email)'
    # Exact HAOS control syntax comes from the authenticated body, never from
    # language-model output or an unsigned display-name/subject interpretation.
    goal=body if body.startswith('/') else native
    if not 1<=len(goal.strip())<=32000:raise Refused('unsupported-content')
    return native,goal


def capture(adapter,resource):
    native=adapter._haos_native;adapter._haos_email_check();policy=native.policy()
    approval=approve(policy,native.connector,adapter._haos_email_value,resource)
    if approval!=resource['approval']:raise Conflict('email body differs from current independent source approval')
    try:parsed=decode(adapter,resource['content'],adapter._haos_email_value,str(resource['uid']).encode())
    except ValueError:raise Refused('unsupported-content') from None
    if parsed is None:raise Refused('self-or-automated')
    codec_text,goal=text(parsed)
    if any(native.inbox.redactor.text(value)!=value for value in [goal,codec_text,parsed['sender_name']]):
        raise Refused('unsupported-content')
    envelope={**approval['envelope'],'text':goal}
    latest=native.policy();latest.current_binding({'binding_id':approval['binding_id'],'binding_digest':approval['binding_digest']})
    identity=adapter._haos_email_raw.put(latest,native.connector,resource)
    latest=native.policy();latest.current_binding({'binding_id':approval['binding_id'],'binding_digest':approval['binding_digest']})
    native.inbox.db.execute('''CREATE TABLE IF NOT EXISTS email_source_context(
        source_id TEXT PRIMARY KEY,binding_digest TEXT NOT NULL,rfc_message_id TEXT NOT NULL,subject TEXT NOT NULL)''')
    old=native.inbox.db.execute('SELECT * FROM email_source_context WHERE source_id=?',(envelope['message_id'],)).fetchone()
    values=(envelope['message_id'],approval['binding_digest'],parsed['message_id'],parsed['subject'])
    if old is None:native.inbox.db.execute('INSERT INTO email_source_context VALUES(?,?,?,?)',values)
    elif tuple(old)!=values:raise Conflict('email source replay changed reply context or recipient authority')
    key=native.inbox.admit(latest,native.connector,envelope,{'raw_id':identity},received_at=approval['received_at'])
    from .gateway_email_journal import Journal
    Journal(native.inbox,native.connector,envelope['scope'],adapter._haos_email_check).remember_capture(key)
    return key


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_email_decode_lock:
        row=native.inbox.claim(key,native.policy())
        if row is None:return False
        state={'adapter':adapter,'row':row,'accepted':False};token=_CURRENT.set(state)
        try:
            adapter._haos_email_check();native.policy().current_binding(row)
            if set(row['payload'])!={'raw_id'}:raise ValueError('exact retained email resource required')
            resource=adapter._haos_email_raw.get(native.policy(),row['payload']['raw_id'])
            approval=approve(native.policy(),native.connector,adapter._haos_email_value,resource)
            parsed=decode(adapter,resource['content'],adapter._haos_email_value,str(resource['uid']).encode())
            if parsed is None:raise PermissionError('retained native email codec no longer accepts source')
            codec_text,goal=text(parsed);state.update(codec_text=codec_text,rfc_message_id=parsed['message_id'])
            if {**approval['envelope'],'text':goal}!=row['envelope']:raise Conflict('retained native email source changed')
            from .gateway_matrix_profile import scope
            with scope(adapter._haos_email_home,adapter._haos_email_environment):
                await adapter._haos_email_decode(adapter,parsed)
            native.policy().current_binding(row);native.inbox.complete(key,state['accepted']);return state['accepted']
        except BaseException:native.inbox.retry(key);raise
        finally:_CURRENT.reset(token)


def install(adapter):
    if not callable(getattr(adapter,'set_durable_message_handler',None)) or not callable(getattr(adapter,'_haos_admit',None)):
        raise TypeError('native email must use the independent durable ingress MRO')
    original_build=adapter.build_source;original_handle=adapter.handle_message
    adapter._haos_email_decode=type(adapter)._dispatch_message;adapter._haos_email_decode_lock=asyncio.Lock()
    def current(self):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained independently approved email context')
        self._haos_email_check();self._haos_native.policy().current_binding(state['row']);return state
    def sender(self,user_id,chat_type='dm',chat_id=None,**_kwargs):
        try:state=current(self)
        except PermissionError:return False
        source=state['row']['envelope']
        return user_id==source['sender'] and chat_id==source['chat'] and chat_type=='dm'
    def source(self,**kwargs):
        state=current(self);row=state['row']['envelope']
        kwargs.update(chat_id=row['chat'],user_id=row['sender'],scope_id=row['scope'],thread_id=row['thread'] or None,
            message_id=row['message_id'],is_bot=False)
        return original_build(**kwargs)
    async def handle(self,event):
        state=current(self);row=state['row']
        if event.text!=state['codec_text'] or event.message_id!=state['rfc_message_id'] or event.media_urls:
            raise PermissionError('native email codec changed retained text, identity or media')
        event.text=row['envelope']['text'];event.message_id=row['envelope']['message_id']
        event.timestamp=datetime.fromtimestamp(row['created_at'],timezone.utc)
        from .gateway_runtime import adapter_envelope
        if adapter_envelope(event,'email')!=row['envelope']:raise PermissionError('native email source differs from approved route')
        await original_handle(event);state['accepted']=event._gateway_accepted is True
    async def deny(_self,*_args,**_kwargs):raise PermissionError('email requires retained independent admission and supervised native transport')
    for name in ['connect','_check_inbox','_dispatch_message','send','send_image','send_multiple_images','send_document','send_voice','send_video','send_typing']:
        setattr(adapter,name,MethodType(deny,adapter))
    adapter._is_sender_authorized=MethodType(sender,adapter);adapter.build_source=MethodType(source,adapter)
    adapter.handle_message=MethodType(handle,adapter)
    return adapter
