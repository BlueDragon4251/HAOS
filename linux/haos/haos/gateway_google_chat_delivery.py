"""Prepared exact-source controller text replies; no public profile activation."""
import asyncio
from contextvars import ContextVar
import hashlib
import re
from types import MethodType

from .gateway import Conflict,digest
from .gateway_google_chat import resource,scope
from .gateway_google_chat_text import TextLedger
from .gateway_event_context import validate

_SENDING=ContextVar('haos_google_chat_outbox',default=None)


class Publisher:
    def __init__(self,adapter):
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter
        if not isinstance(adapter,GoogleChatAdapter):raise TypeError('actual pinned native Google Chat adapter required')
        self.adapter=adapter;self.native=adapter._haos_native;self.value=adapter._haos_google_value;self.lock=asyncio.Lock()
        self.db=self.native.inbox.db;self.ledger=TextLedger(self.native.inbox,self.native.connector,self.value,self.native.policy,adapter._haos_google_check)
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_delivery_groups(
            id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            source_id TEXT NOT NULL,source_sha256 TEXT NOT NULL,context_sha256 TEXT NOT NULL,content_sha256 TEXT NOT NULL,
            parts INTEGER NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,connector TEXT NOT NULL)''')
        if 'connector' not in {row[1] for row in self.db.execute('PRAGMA table_info(google_chat_delivery_groups)')}:
            self.db.execute("ALTER TABLE google_chat_delivery_groups ADD COLUMN connector TEXT NOT NULL DEFAULT ''")
        from .gateway_google_chat_output import Output
        from .gateway_google_chat_files import FileLedger
        self.output=Output(adapter);self.file_ledger=FileLedger(self.native.inbox);self.files=None;self.user_inbox=None
        adapter._haos_google_output=self.output
        receiver=getattr(adapter,'_haos_google_receiver',None)
        if receiver is not None:receiver.own_message=lambda raw:self.file_ledger.own_message(self.native.connector,self.value,raw)
        self.install()

    def file_sender(self):
        if self.files is None:
            from .gateway_raw import NativeInbox
            from .gateway_google_chat_oauth import OAuthStore
            from .gateway_google_chat_files import Files
            self.user_inbox=NativeInbox(self.adapter._haos_google_home.parent/'user-oauth.sqlite',self.native.inbox.redactor)
            self.files=Files(self.adapter,OAuthStore(self.user_inbox))
        return self.files

    async def close(self):
        async with self.lock:
            if self.user_inbox is not None:self.user_inbox.close();self.user_inbox=None;self.files=None

    def source(self,binding,message_id,thread):
        resource(message_id,'message',space=binding['chat']);self.adapter._haos_google_check()
        rows=self.db.execute('''SELECT p.*,n.state AS native_state,n.fingerprint,n.binding_id,n.binding_digest AS native_binding
            FROM google_chat_native_projection p JOIN native_inbox n ON p.source_key=n.id
            WHERE n.connector=? AND n.message_id=?''',(self.native.connector,message_id)).fetchall()
        if len(rows)!=1:raise PermissionError('one committed independently retained Google Chat source required')
        row=rows[0]
        if (row['native_state']!='committed' or row['binding_id']!=binding['id'] or row['native_binding']!=digest(binding)
                or row['binding_digest']!=digest(binding) or row['envelope_sha256']!=row['fingerprint']):
            raise PermissionError('Google Chat reply source lacks matching completed native admission')
        raw,proof=self.adapter._haos_google_originals.load(row['raw_id'],self.native.policy(),self.native.connector,self.value,self.adapter._haos_google_check)
        envelope=proof['envelope']
        if (row['raw_sha256']!=proof['raw_sha256'] or row['credential_scope']!=proof['credential_scope']
                or envelope['sender']!=binding['sender'] or envelope['chat']!=binding['chat']
                or envelope['scope']!=scope(self.value) or envelope['thread']!=thread or envelope['message_id']!=message_id):
            raise PermissionError('Google Chat source differs from exact outbox recipient/thread/account')
        expected=digest([self.native.connector,*(envelope[k] for k in ['scope','chat','thread','message_id'])])
        stored=self.adapter._haos_google_originals.db.execute('SELECT admitted_receipt FROM google_chat_originals WHERE id=?',(row['raw_id'],)).fetchone()
        if stored is None or stored[0]!=expected:raise PermissionError('Google Chat source has no completed parent relay receipt')
        return row,raw

    def install(self):
        publisher=self;adapter=self.adapter
        def context(self):
            value=_SENDING.get()
            if value is None or value['publisher'] is not publisher or value['task'] is not asyncio.current_task():
                raise PermissionError('no current exact-source Google Chat outbox capability')
            value['current']();return value
        async def create(self,parent,body):
            value=context(self);part=value['part']
            if part>=len(value['bodies']) or parent!=value['chat'] or body!=value['bodies'][part]:
                raise PermissionError('native Google Chat write differs from pinned controller projection')
            operation=digest([value['delivery_id'],value['source_key'],part])
            try:result=await publisher.ledger.create(self,operation,value['route'],parent,body)
            except Exception as error:
                handler=getattr(self,'_haos_google_delivery_error',None)
                if callable(handler):handler(error)
                raise
            if result.success is not True:raise Conflict('Google Chat chunk has no acceptance receipt')
            value['part']+=1;return result
        def thread(self,*_args,**_kwargs):return context(self)['thread'] or None
        async def deny(self,*_args,**_kwargs):raise PermissionError('Google Chat operation has no reviewed private outbox capability')
        adapter._create_message=MethodType(create,adapter);adapter._resolve_thread_id=MethodType(thread,adapter)
        for name in ['send_card','send_typing','stop_typing','edit_message','delete_message','_patch_message','send_clarify',
                '_send_file','_post_attachment_fallback','send_image','send_image_file','send_document','send_voice','send_video','send_animation',
                '_handle_setup_files_command','_dispatch_message','dispatch_http_event','connect']:
            setattr(adapter,name,MethodType(deny,adapter))

    async def send(self,chat,content,reply_to,metadata):
        from gateway.platforms.base import SendResult
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter,_thread_body
        from .gateway_delivery_authority import current_delivery
        authority=current_delivery(self.adapter,'google_chat',chat,metadata)
        if (not isinstance(content,str) or not content.strip() or len(content.encode())>32000
                or self.native.inbox.redactor.text(content)!=content):raise PermissionError('bounded private controller text required')
        delivery_id=metadata.get('haos_delivery_id');attempt=metadata.get('haos_delivery_attempt')
        if not isinstance(delivery_id,str) or not re.fullmatch('[0-9a-f]{64}',delivery_id) or type(attempt) is not int or not 1<=attempt<=5:
            raise PermissionError('exact bounded root outbox identity and attempt required')
        context=validate(metadata.get('haos_event_context'))
        if context['content_sha256']!=hashlib.sha256(content.encode()).hexdigest():raise Conflict('controller Google Chat content changed')
        binding=self.native.policy().current_binding(metadata['haos_binding']);thread=metadata.get('thread_id','')
        delivery={'id':delivery_id,'attempt':attempt,**metadata['haos_binding'],'chat':chat,'scope':binding['scope'],
            'thread':thread,'event_context':context,'content':content}
        projected=metadata.get('haos_output');artifacts=[];rendered=content
        if projected is not None:
            artifacts=self.output.resolve(delivery,projected);rendered=projected['text']
            if self.native.inbox.redactor.text(rendered)!=rendered:raise PermissionError('Google output text reflects private credentials')
        # Do not render an agent filesystem path as a fallback chat message.
        from gateway.platforms.base import BasePlatformAdapter
        files,_=BasePlatformAdapter.extract_media(content)
        if files and projected is None:raise PermissionError('Google Chat file directives require separately approved sealed output')
        def current():
            self.adapter._haos_google_check();authority()
            self.source(self.native.policy().current_binding(metadata['haos_binding']),reply_to,thread)
        async with self.lock:
            current();source,raw=self.source(binding,reply_to,thread)
            last_file=None
            if artifacts:
                evidence={'delivery_id':delivery_id,'source_key':source['source_key'],'source_id':reply_to,
                    'source_sha256':hashlib.sha256(raw).hexdigest(),'context_sha256':digest(context),'content_sha256':context['content_sha256']}
                def file_current():
                    current();self.output.resolve(delivery,projected)
                try:
                    for index,artifact in enumerate(artifacts):
                        file_current();manager=self.file_sender()
                        from .gateway_matrix_profile import scope as private_scope
                        with private_scope(self.adapter._haos_google_home,self.adapter._haos_google_environment):
                            last_file=await manager.send(digest([delivery_id,source['source_key'],'file',index]),dict(metadata['haos_binding']),
                                evidence,artifact,'',thread,file_current)
                        file_current()
                        if last_file.success is not True:raise Conflict('Google file part has no durable acceptance receipt')
                except asyncio.CancelledError:raise
                except Exception:
                    return SendResult(success=False,error='Google file user authorization or write needs inspected recovery',raw_response={'haos_delivery':'uncertain'})
            if not rendered.strip():
                if last_file is not None:return last_file
                raise PermissionError('Google output has no approved file or text')
            chunks=GoogleChatAdapter._chunk_text(self.adapter,GoogleChatAdapter.format_message(rendered))
            if not chunks or len(chunks)>64:raise ValueError('bounded native Google Chat text projection required')
            bodies=[_thread_body(chunk,thread or None) for chunk in chunks]
            values=(delivery_id,binding['id'],digest(binding),digest(self.value),reply_to,hashlib.sha256(raw).hexdigest(),
                digest(context),hashlib.sha256(content.encode()).hexdigest(),len(bodies))
            previous=self.db.execute('SELECT * FROM google_chat_delivery_groups WHERE id=?',(delivery_id,)).fetchone()
            if previous is not None:
                if tuple(previous)[:9]!=values or previous['connector']!=self.native.connector:raise Conflict('Google Chat root delivery changed source, account, text or event context')
                if previous['state']=='confirmed':return SendResult(success=True,message_id=resource(previous['receipt'],'message',space=chat))
                if previous['state']!='writing':raise Conflict('damaged Google Chat root delivery state')
            else:
                if self.db.execute('SELECT COUNT(*) FROM google_chat_delivery_groups').fetchone()[0]>=65536:raise Conflict('Google Chat outbox history full')
                self.db.execute('INSERT INTO google_chat_delivery_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(*values,'writing','',self.native.connector))
            state={'publisher':self,'task':asyncio.current_task(),'current':current,'chat':chat,'thread':thread,
                'route':dict(metadata['haos_binding']),'source_key':source['source_key'],'delivery_id':delivery_id,'part':0,'bodies':bodies}
            token=_SENDING.set(state)
            try:
                from .gateway_matrix_profile import scope as private_scope
                with private_scope(self.adapter._haos_google_home,self.adapter._haos_google_environment):
                    result=await GoogleChatAdapter.send(self.adapter,chat,rendered,reply_to=reply_to,metadata=metadata)
                current()
                if result.success is not True or state['part']!=len(bodies):
                    return SendResult(success=False,error='Google Chat text acceptance requires inspected recovery',raw_response={'haos_delivery':'uncertain'})
                receipt=resource(result.message_id,'message',space=chat)
                changed=self.db.execute("UPDATE google_chat_delivery_groups SET state='confirmed',receipt=? WHERE id=? AND state='writing'",(receipt,delivery_id)).rowcount
                if changed!=1:raise Conflict('Google Chat controller acceptance journal changed')
                return SendResult(success=True,message_id=receipt,raw_response={'upstream_acceptance_only':True,'recipient_read_verified':False})
            except asyncio.CancelledError:raise
            except PermissionError:raise
            except Exception:
                return SendResult(success=False,error='Google Chat write requires read-only reconciliation',raw_response={'haos_delivery':'uncertain'})
            finally:_SENDING.reset(token)
