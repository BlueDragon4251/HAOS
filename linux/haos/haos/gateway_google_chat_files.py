"""Prepared exact-source native file calls with upload/write uncertainty fences."""
import asyncio
from contextvars import ContextVar
import hashlib
import json
import re
import threading
import time
from types import MethodType
import uuid

from .gateway import Conflict,digest
from .gateway_google_chat import resource,scope
from .gateway_google_chat_output import sealed

_CURRENT=ContextVar('haos_google_file_operation',default=None)
HEX=re.compile('[a-f0-9]{64}\\Z')


def attachment(value):
    if (not isinstance(value,dict) or not value or not set(value)<={'resourceName','attachmentUploadToken'}
            or any(not isinstance(v,str) or not 1<=len(v)<=8192 or any(not 33<=ord(c)<=126 for c in v) for v in value.values())):
        raise Conflict('bounded private Google upload reference required')
    return dict(value)


class FileLedger:
    def __init__(self,inbox):
        self.db=inbox.db;self.redactor=inbox.redactor
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_file_writes(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,account_scope TEXT NOT NULL,
            proof TEXT NOT NULL,proof_sha256 TEXT NOT NULL,client_id TEXT NOT NULL UNIQUE,
            request_id TEXT NOT NULL,upload_state TEXT NOT NULL,attachment_ref TEXT NOT NULL,
            state TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL,owner_retry_generation INTEGER NOT NULL DEFAULT 0)''')

    def get(self,identity,proof):
        fields={'connector','credential_scope','account_scope','binding_id','binding_digest','chat','thread','subject','token_id','client_sha256','source','file_id','file_sha256','filename','mime','caption'}
        if (not isinstance(identity,str) or not HEX.fullmatch(identity) or not isinstance(proof,dict) or set(proof)!=fields
                or any(not isinstance(proof[k],str) or not HEX.fullmatch(proof[k]) for k in ['credential_scope','binding_digest','token_id','client_sha256','file_id','file_sha256'])
                or any(not isinstance(proof[k],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',proof[k]) for k in ['connector','binding_id'])
                or not isinstance(proof['account_scope'],str) or not re.fullmatch('google-chat:[a-f0-9]{64}',proof['account_scope'])
                or not isinstance(proof['caption'],str) or len(proof['caption'].encode())>16384
                or not isinstance(proof['filename'],str) or not re.fullmatch('result-[0-9]{1,6}\\.[a-z0-9]{1,10}',proof['filename'])
                or not isinstance(proof['mime'],str) or not re.fullmatch('[a-z0-9.+-]+/[a-z0-9.+-]+',proof['mime'])):
            raise PermissionError('closed exact-source Google file proof required')
        resource(proof['chat'],'space');resource(proof['subject'],'user')
        if proof['thread']:resource(proof['thread'],'thread',space=proof['chat'])
        source=proof['source']
        if (not isinstance(source,dict) or set(source)!={'delivery_id','source_key','source_id','source_sha256','context_sha256','content_sha256'}
                or any(not isinstance(source[k],str) or not HEX.fullmatch(source[k]) for k in source if k!='source_id')):
            raise PermissionError('closed Root outbox/source context required for Google file')
        resource(source['source_id'],'message',space=proof['chat'])
        encoded=json.dumps(proof,sort_keys=True,separators=(',',':'));row=self.db.execute('SELECT * FROM google_chat_file_writes WHERE id=?',(identity,)).fetchone()
        client='client-'+identity[:56];request=str(uuid.uuid5(uuid.NAMESPACE_URL,'haos-google-file:'+identity))
        if row is not None:
            if (row['proof']!=encoded or row['proof_sha256']!=digest(proof) or row['connector']!=proof['connector']
                    or row['credential_scope']!=proof['credential_scope'] or row['account_scope']!=proof['account_scope'] or row['client_id']!=client or row['request_id']!=request
                    or row['upload_state'] not in {'not-started','uploading','uploaded'} or row['state'] not in {'prepared','writing','confirmed','owner-retry-approved'}
                    or type(row['owner_retry_generation']) is not int or not 0<=row['owner_retry_generation']<=4
                    or (row['upload_state']=='uploaded')!=bool(row['attachment_ref']) or (row['state']=='confirmed')!=bool(row['receipt'])
                    or row['state']!='prepared' and row['upload_state']!='uploaded'):
                raise Conflict('Google file write identity, source or journal changed')
            if row['attachment_ref']:
                ref=attachment(json.loads(row['attachment_ref']))
                if json.dumps(ref,sort_keys=True,separators=(',',':'))!=row['attachment_ref']:raise Conflict('Google upload reference changed')
            if row['receipt']:resource(row['receipt'],'message',space=proof['chat'])
            return dict(row)
        count,used=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(proof)+length(attachment_ref)),0) FROM google_chat_file_writes').fetchone()
        if count>=65536 or used+len(encoded.encode())>16*1024*1024:raise Conflict('Google file journal full; Owner recovery required')
        self.db.execute('INSERT INTO google_chat_file_writes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,proof['connector'],proof['credential_scope'],proof['account_scope'],encoded,digest(proof),client,request,'not-started','','prepared','',time.time(),0))
        return self.get(identity,proof)

    def uploading(self,identity,proof):
        row=self.get(identity,proof)
        if row['upload_state']=='uploaded':return attachment(json.loads(row['attachment_ref']))
        if row['state']!='prepared' or row['upload_state']!='not-started':raise Conflict('Google upload was already begun; no automatic repetition')
        if self.db.execute("UPDATE google_chat_file_writes SET upload_state='uploading' WHERE id=? AND state='prepared' AND upload_state='not-started'",(identity,)).rowcount!=1:
            raise Conflict('Google upload intent changed')
        return None

    def uploaded(self,identity,proof,ref):
        row=self.get(identity,proof);ref=attachment(ref)
        if row['state']!='prepared' or row['upload_state']!='uploading':raise Conflict('current durable Google upload intent required')
        from .redaction import Redactor
        self.redactor.secrets=Redactor([*self.redactor.secrets,*ref.values()]).secrets
        encoded=json.dumps(ref,sort_keys=True,separators=(',',':'))
        used=self.db.execute('SELECT COALESCE(SUM(length(proof)+length(attachment_ref)),0) FROM google_chat_file_writes').fetchone()[0]
        if used+len(encoded.encode())>16*1024*1024:raise Conflict('Google file reference custody full')
        if self.db.execute("UPDATE google_chat_file_writes SET upload_state='uploaded',attachment_ref=? WHERE id=? AND state='prepared' AND upload_state='uploading'",(encoded,identity)).rowcount!=1:
            raise Conflict('Google upload acceptance changed')
        return ref

    def writing(self,identity,proof):
        row=self.get(identity,proof)
        if row['state']!='prepared' or row['upload_state']!='uploaded':raise Conflict('one current uploaded Google file intent required')
        if self.db.execute("UPDATE google_chat_file_writes SET state='writing' WHERE id=? AND state='prepared' AND upload_state='uploaded'",(identity,)).rowcount!=1:
            raise Conflict('Google file publication intent changed')
        return self.get(identity,proof)

    def confirm(self,identity,proof,response):
        row=self.get(identity,proof);name=receipt(response,proof,row['client_id'])
        if row['state'] not in {'writing','owner-retry-approved'}:raise Conflict('begun Google file publication required')
        if self.db.execute("UPDATE google_chat_file_writes SET state='confirmed',receipt=? WHERE id=? AND state IN ('writing','owner-retry-approved')",(name,identity)).rowcount!=1:
            raise Conflict('Google file acceptance changed')
        return name

    def own_message(self,connector,account,raw):
        """Authenticated callbacks cannot turn our user-authored file into a mission."""
        from .gateway_dingtalk_admission import parse,Refused as JSONRefused
        from .gateway_google_chat_admission import message,timestamp,Refused
        try:data=parse(raw);msg,space=message(data)
        except JSONRefused:raise Refused('unsupported-content') from None
        sender=msg.get('sender',{})
        if not isinstance(sender,dict) or sender.get('type')!='HUMAN':return False
        chat=space.get('name');subject=sender.get('name');mid=msg.get('name');client=msg.get('clientAssignedMessageId')
        try:resource(chat,'space');resource(subject,'user');resource(mid,'message',space=chat)
        except ValueError:raise Refused('unsupported-content') from None
        if msg.get('thread') is not None and not isinstance(msg['thread'],dict):raise Refused('unsupported-thread')
        pin=scope(account)
        rows=self.db.execute("SELECT * FROM google_chat_file_writes WHERE connector=? AND account_scope=? AND (client_id=? OR receipt=?) LIMIT 2",
            (connector,pin,client if isinstance(client,str) else '',mid)).fetchall()
        for row in rows:
            proof=json.loads(row['proof']);self.get(row['id'],proof)
            if proof['chat']==chat and proof['subject']==subject:return True
        # Some callback projections omit clientAssignedMessageId. While a
        # matching create is unresolved, refuse this exact file/caption/user
        # shape as ambiguous rather than execute a possible echo as a mission.
        rows=self.db.execute("""SELECT * FROM google_chat_file_writes WHERE connector=? AND account_scope=? AND state='writing'
            AND json_extract(proof,'$.chat')=? AND json_extract(proof,'$.subject')=? LIMIT 129""",(connector,pin,chat,subject)).fetchall()
        if len(rows)>128:raise Conflict('Google ambiguous own-write history needs Owner recovery')
        for row in rows:
            proof=json.loads(row['proof']);self.get(row['id'],proof);items=msg.get('attachment',[])
            if (isinstance(items,list) and len(items)==1 and isinstance(items[0],dict)
                    and items[0].get('contentName')==proof['filename'] and items[0].get('contentType')==proof['mime']
                    and msg.get('text','')==proof['caption'] and (msg.get('thread') or {}).get('name','')==proof['thread']
                    and timestamp(msg.get('createTime'))/1000>=row['created_at']-60):return True
        return False


def receipt(response,proof,client):
    if not isinstance(response,dict):raise Conflict('Google file acceptance object required')
    name=resource(response.get('name'),'message',space=proof['chat']);sender=response.get('sender');files=response.get('attachment')
    if (response.get('clientAssignedMessageId')!=client or response.get('text','')!=proof['caption']
            or not isinstance(sender,dict) or sender.get('name')!=proof['subject'] or sender.get('type')!='HUMAN'
            or proof['thread'] and (response.get('thread') or {}).get('name')!=proof['thread']
            or not isinstance(files,list) or len(files)!=1 or any(response.get(k) for k in ['cards','cardsV2','privateMessageViewer'])):
        raise Conflict('Google user file acceptance differs from exact principal, text, thread or write ID')
    item=files[0]
    if (not isinstance(item,dict) or not isinstance(item.get('name'),str)
            or not re.fullmatch(re.escape(name)+'/attachments/[A-Za-z0-9_-]{1,256}',item['name'])
            or item.get('contentName')!=proof['filename'] or item.get('contentType')!=proof['mime'] or item.get('source')!='UPLOADED_CONTENT'
            or item.get('driveDataRef')):raise Conflict('Google file acceptance differs from the uploaded filename/type/source')
    return name


class Files:
    def __init__(self,adapter,store):
        from .gateway_runtime import require_runtime_identity
        require_runtime_identity()
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter
        if not isinstance(adapter,GoogleChatAdapter):raise TypeError('actual pinned Google Chat file adapter required')
        self.adapter=adapter;self.store=store;self.ledger=FileLedger(adapter._haos_native.inbox)
        self.lock=asyncio.Lock();self.install()

    def context(self):
        state=_CURRENT.get()
        if state is None or state['files'] is not self or state['ended'].is_set():raise PermissionError('no current native Google file capability')
        state['api'].guard.call(state['check']);return state

    def install(self):
        manager=self
        async def acquire(_self,_display_email):
            state=manager.context()
            if asyncio.current_task() is not state['task']:raise PermissionError('exact native Google file task required')
            return state['facade'],state['proof']['subject']
        async def no_typing(_self,chat,text):
            # Native text sends also call this helper. Typing cards are
            # disabled for every path; outside a file capability this no-op
            # grants no operation (the text create has its separate guard).
            if _CURRENT.get() is None:return None
            state=manager.context()
            if chat!=state['proof']['chat'] or text!=(state['proof']['caption'] or ' '):raise PermissionError('no independent typing mutation allowed')
            return None
        def invalidate(_self,identity):
            if identity!=manager.context()['proof']['subject']:raise PermissionError('Google file principal changed')
        self.adapter._acquire_user_chat_api=MethodType(acquire,self.adapter)
        self.adapter._consume_typing_card_with_text=MethodType(no_typing,self.adapter)
        self.adapter._invalidate_user_creds=MethodType(invalidate,self.adapter)
        async def deny(_self,*_args,**_kwargs):raise PermissionError('Google file has no independent fallback, setup or legacy-account authority')
        for name in ['_send_file','_post_attachment_fallback','_load_per_user_chat_api','_load_user_oauth','_handle_setup_files_command']:
            setattr(self.adapter,name,MethodType(deny,self.adapter))

    async def send(self,operation,route,source,artifact,caption,thread,check,*,http=None,certificate_request=None):
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter
        from gateway.platforms.base import SendResult
        if not isinstance(operation,str) or not HEX.fullmatch(operation) or not isinstance(caption,str) or len(caption.encode())>16384:
            raise ValueError('bounded exact Google file operation required')
        from .gateway_media import MAX_BYTES
        if (not isinstance(artifact,dict) or not isinstance(artifact.get('data'),bytes) or not 1<=len(artifact['data'])<=MAX_BYTES
                or artifact.get('sha256')!=hashlib.sha256(artifact['data']).hexdigest() or artifact.get('size')!=len(artifact['data'])):
            raise PermissionError('exact bounded retained Root file bytes required')
        async with self.lock:
            check();native=self.adapter._haos_native;binding=native.policy().current_binding(route)
            base={'connector':native.connector,'credential_scope':digest(self.adapter._haos_google_value),'account_scope':scope(self.adapter._haos_google_value),'binding_id':binding['id'],'binding_digest':digest(binding),
                'chat':binding['chat'],'thread':thread,'subject':binding['sender'],'source':source,'file_id':artifact['id'],
                'file_sha256':artifact['sha256'],'filename':artifact['filename'],'mime':artifact['mime'],'caption':caption}
            previous=self.ledger.db.execute('SELECT proof FROM google_chat_file_writes WHERE id=?',(operation,)).fetchone()
            if previous is not None:
                retained=json.loads(previous['proof'])
                expected={**base,'token_id':retained['token_id'],'client_sha256':retained['client_sha256']}
                row=self.ledger.get(operation,expected)
                if row['state']=='confirmed':
                    # A verified historical receipt needs no token refresh or
                    # new API access, including after explicit user logout.
                    return SendResult(success=True,message_id=row['receipt'],raw_response={'upstream_acceptance_only':True,'recipient_read_verified':False})
            from .gateway_google_chat_file_http import FileAPI
            api=await FileAPI.open(self.store,native.policy,native.connector,self.adapter._haos_google_value,route,check,http=http,certificate_request=certificate_request)
            state=None;token=None
            try:
                redactor=self.store.inbox.redactor
                if redactor.text(caption)!=caption or any(secret.encode() in artifact['data'] for secret in redactor.secrets if secret):
                    raise PermissionError('private Google credentials cannot become file output or caption')
                snapshot=api.snapshot;subject=snapshot['row']['subject']
                proof={**base,'subject':subject,'token_id':snapshot['row']['id'],'client_sha256':snapshot['row']['client_sha256']}
                if subject!=binding['sender']:raise PermissionError('Google native file cannot borrow another user or legacy identity')
                row=self.ledger.get(operation,proof)
                if row['state']=='confirmed':return SendResult(success=True,message_id=row['receipt'])
                if row['state'] in {'writing','owner-retry-approved'}:
                    # An interrupted native create can only look up its own
                    # retained client ID. A 404 alone never permits another POST.
                    response=await asyncio.to_thread(lambda:api.execute(api.service.spaces().messages().get(name=proof['chat']+'/messages/'+row['client_id'])))
                    check();name=self.ledger.confirm(operation,proof,response)
                    return SendResult(success=True,message_id=name,raw_response={'upstream_acceptance_only':True,'recipient_read_verified':False})
                state={'files':self,'api':api,'proof':proof,'operation':operation,'artifact':artifact,'check':check,'ended':threading.Event(),
                    'task':asyncio.current_task(),'path':None,'facade':_Facade(self)}
                token=_CURRENT.set(state)
                with sealed(artifact['data']) as path:
                    state['path']=path
                    result=await GoogleChatAdapter._send_file(self.adapter,proof['chat'],path,caption or None,mime_hint=artifact['mime'],thread_id=thread or None,override_filename=artifact['filename'])
                check();row=self.ledger.get(operation,proof)
                if not result.success or row['state']!='confirmed' or result.message_id!=row['receipt']:raise Conflict('native Google file has no durable exact acceptance receipt')
                return SendResult(success=True,message_id=row['receipt'],raw_response={'upstream_acceptance_only':True,'recipient_read_verified':False})
            finally:
                if state is not None:state['ended'].set()
                if token is not None:_CURRENT.reset(token)
                api.close()


class _Once:
    def __init__(self,execute):self.operation=execute;self.begun=False
    def execute(self,*args,**kwargs):
        if args or kwargs or self.begun:raise PermissionError('one exact native Google file SDK operation required')
        self.begun=True;return self.operation()


class _Facade:
    """Only the actual pinned native _send_file projection reaches this facade."""
    def __init__(self,manager):self.manager=manager
    def media(self):self.manager.context();return self
    def spaces(self):self.manager.context();return self
    def messages(self):self.manager.context();return self
    def upload(self,**kwargs):
        state=self.manager.context();artifact=state['artifact'];media=kwargs.get('media_body')
        from googleapiclient.http import MediaFileUpload
        if (set(kwargs)!={'parent','body','media_body'} or kwargs['parent']!=state['proof']['chat'] or kwargs['body']!={'filename':artifact['filename']}
                or type(media) is not MediaFileUpload or media._filename!=state['path'] or media.size()!=len(artifact['data'])
                or media.mimetype()!=artifact['mime'] or media.resumable() or media.getbytes(0,media.size())!=artifact['data']):
            raise PermissionError('native Google upload differs from sealed Root output bytes or recipient')
        def execute():
            state=self.manager.context();api=state['api'];proof=state['proof'];identity=state['operation']
            try:
                cached=api.guard.call(lambda:self.manager.ledger.uploading(identity,proof))
                if cached is not None:return {'attachmentDataRef':cached}
                response=api.execute(api.service.media().upload(**kwargs))
                if not isinstance(response,dict) or set(response)!={'attachmentDataRef'}:raise Conflict('bounded native Google upload acceptance required')
                ref=api.guard.call(lambda:self.manager.ledger.uploaded(identity,proof,response['attachmentDataRef']))
                return {'attachmentDataRef':ref}
            finally:media._fd.close()
        return _Once(execute)

    def create(self,**kwargs):
        state=self.manager.context();proof=state['proof'];api=state['api'];identity=state['operation']
        row=api.guard.call(lambda:self.manager.ledger.get(identity,proof));ref=attachment(json.loads(row['attachment_ref']))
        body={'attachment':[{'attachmentDataRef':ref}]}
        if proof['caption']:body['text']=proof['caption']
        if proof['thread']:body['thread']={'name':proof['thread']}
        from plugins.platforms.google_chat.adapter import _create_kwargs
        if kwargs!=_create_kwargs(proof['chat'],body):raise PermissionError('actual native Google file projection changed')
        def execute():
            self.manager.context();row=api.guard.call(lambda:self.manager.ledger.writing(identity,proof))
            exact={'parent':proof['chat'],'body':body,'messageId':row['client_id'],'requestId':row['request_id']}
            if proof['thread']:exact['messageReplyOption']='REPLY_MESSAGE_OR_FAIL'
            response=api.execute(api.service.spaces().messages().create(**exact))
            api.guard.call(lambda:self.manager.ledger.confirm(identity,proof,response));return response
        return _Once(execute)
