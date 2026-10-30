"""Prepared immutable original -> actual native codec -> durable HAOS relay."""
import asyncio
from contextvars import ContextVar
from datetime import datetime,timezone
from types import MethodType

from .gateway import Conflict,digest
from .gateway_google_chat_codec import decode_text

_CURRENT=ContextVar('haos_google_chat_original',default=None)


def install(adapter):
    from plugins.platforms.google_chat.adapter import GoogleChatAdapter
    if not isinstance(adapter,GoogleChatAdapter):raise TypeError('actual pinned Google Chat adapter required')
    if not callable(getattr(adapter,'_haos_admit',None)) or hasattr(adapter,'_haos_google_admit'):
        raise TypeError('one actual durable native Google Chat adapter required')
    original=adapter._haos_admit
    def admit(self,event):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self or state['event'] is not event:
            raise PermissionError('no independently retained Google Chat source context')
        self._haos_google_check();self._haos_native.policy().current_binding(state['row'])
        from .gateway_runtime import adapter_envelope
        if adapter_envelope(event,'google_chat')!=state['row']['envelope']:raise Conflict('Google Chat native source changed before parent admission')
        original(event)
    adapter._haos_google_admit=original;adapter._haos_admit=MethodType(admit,adapter)
    adapter._haos_google_decode_lock=asyncio.Lock()
    return adapter


async def capture_stored(adapter,identity):
    adapter._haos_google_check();native=adapter._haos_native;policy=native.policy()
    raw,proof=adapter._haos_google_originals.load(identity,policy,native.connector,adapter._haos_google_value,adapter._haos_google_check)
    from .gateway_matrix_profile import scope
    with scope(adapter._haos_google_home,adapter._haos_google_environment):
        event=await decode_text(adapter,policy,native.connector,adapter._haos_google_value,raw,proof)
    # Native text is the command projection, but credentials remain private.
    event.text=native.inbox.redactor.text(event.text);event.channel_prompt=None
    from .gateway_runtime import adapter_envelope
    envelope=adapter_envelope(event,'google_chat')
    if {**envelope,'text':''}!=proof['envelope']:raise Conflict('Google Chat codec changed approved immutable route')
    if not 1<=len(event.text.strip())<=32000:raise PermissionError('Google Chat source has no bounded actionable text')
    source_key=native.inbox.key(native.connector,envelope);db=native.inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_native_projection(
        source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,raw_sha256 TEXT NOT NULL,binding_digest TEXT NOT NULL,
        credential_scope TEXT NOT NULL,envelope_sha256 TEXT NOT NULL)''')
    values=(source_key,identity,proof['raw_sha256'],proof['binding_digest'],proof['credential_scope'],digest(envelope))
    previous=db.execute('SELECT * FROM google_chat_native_projection WHERE source_key=?',(source_key,)).fetchone()
    if previous is None:db.execute('INSERT INTO google_chat_native_projection VALUES(?,?,?,?,?,?)',values)
    elif tuple(previous)!=values:raise Conflict('Google Chat original or native command projection changed after first custody')
    adapter._haos_google_check();policy=native.policy();policy.current_binding(proof)
    key=native.inbox.admit(policy,native.connector,envelope,{'raw_id':identity},received_at=proof['received_at'])
    if key!=source_key:raise Conflict('Google Chat native source key changed')
    return key


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_google_decode_lock:
        adapter._haos_google_check();row=native.inbox.claim(key,native.policy())
        if row is None:return False
        try:
            if not isinstance(row['payload'],dict) or set(row['payload'])!={'raw_id'}:raise Conflict('exact retained Google Chat original required')
            identity=row['payload']['raw_id'];policy=native.policy()
            raw,proof=adapter._haos_google_originals.load(identity,policy,native.connector,adapter._haos_google_value,adapter._haos_google_check)
            from .gateway_matrix_profile import scope
            with scope(adapter._haos_google_home,adapter._haos_google_environment):
                event=await decode_text(adapter,policy,native.connector,adapter._haos_google_value,raw,proof)
            event.text=native.inbox.redactor.text(event.text);event.channel_prompt=None
            event.timestamp=datetime.fromtimestamp(proof['received_at'],timezone.utc)
            from .gateway_runtime import adapter_envelope
            envelope=adapter_envelope(event,'google_chat')
            projection=native.inbox.db.execute('SELECT * FROM google_chat_native_projection WHERE source_key=?',(key,)).fetchone()
            if (projection is None or projection['raw_id']!=identity or projection['raw_sha256']!=proof['raw_sha256']
                    or projection['binding_digest']!=row['binding_digest'] or projection['credential_scope']!=proof['credential_scope']
                    or projection['envelope_sha256']!=digest(envelope) or envelope!=row['envelope']):
                raise Conflict('retained Google Chat source differs from first native projection')
            token=_CURRENT.set({'adapter':adapter,'event':event,'row':row})
            try:adapter._haos_admit(event)
            finally:_CURRENT.reset(token)
            adapter._haos_google_check();native.policy().current_binding(row)
            if event._gateway_accepted is not True:raise Conflict('Google Chat parent admission has no committed receipt')
            parent_key=digest([native.connector,*(envelope[k] for k in ['scope','chat','thread','message_id'])])
            adapter._haos_google_originals.admitted(identity,parent_key,native.policy(),native.connector,adapter._haos_google_value,adapter._haos_google_check)
            native.inbox.complete(key,True);return True
        except BaseException:native.inbox.retry(key);raise
