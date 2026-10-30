"""Prepared exact-route native text writes and read-only uncertain reconciliation.

Caller must independently validate a controller outbox operation. This private
primitive neither creates missions nor grants an agent arbitrary send authority.
"""
import asyncio
import json
import re
import time
import uuid

from .gateway import Conflict,digest
from .gateway_google_chat import credentials,scope,resource,validate_binding,thread_allowed


class TextLedger:
    def __init__(self,inbox,connector,value,policy,current):
        self.db=inbox.db;self.redactor=inbox.redactor;self.connector=connector;self.value=credentials(value)
        self.policy=policy;self.check=current;current()
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_text_writes(
            id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            parent TEXT NOT NULL,body TEXT NOT NULL,client_id TEXT NOT NULL,request_id TEXT NOT NULL,
            state TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')

    def current(self,route):
        self.check();policy=self.policy();binding=policy.current_binding(route);validate_binding(binding)
        if (binding['connector']!=self.connector or policy.connectors.get(self.connector,{}).get('platform')!='google_chat'
                or binding['scope']!=scope(self.value) or binding['sender']==self.value['bot_user'] or 'read' not in binding['capabilities']):
            raise PermissionError('exact current Google Chat reply/read grant required')
        return binding

    def _response(self,response,parent,body,client_id):
        if not isinstance(response,dict):raise Conflict('invalid Google Chat acceptance response')
        name=resource(response.get('name'),'message',space=parent)
        reply_thread=(response.get('thread') or {}).get('name','')
        if reply_thread:resource(reply_thread,'thread',space=parent)
        if (response.get('clientAssignedMessageId')!=client_id or response.get('text')!=body['text']
                or body.get('thread') and reply_thread!=body['thread']['name']
                or any(response.get(key) for key in ['attachment','cards','cardsV2','privateMessageViewer'])):
            raise Conflict('Google Chat acceptance differs from exact reply operation')
        return name

    async def create(self,adapter,operation,route,parent,body):
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter,_create_kwargs
        if not isinstance(adapter,GoogleChatAdapter):raise TypeError('actual pinned Google Chat adapter required')
        if not isinstance(operation,str) or not re.fullmatch('[0-9a-f]{64}',operation):raise ValueError('exact controller operation digest required')
        binding=self.current(route);resource(parent,'space')
        if (parent!=binding['chat'] or not isinstance(body,dict) or not {'text'}<=set(body)<={'text','thread'}
                or not isinstance(body['text'],str) or not 1<=len(body['text'].encode())<=16384
                or any(secret in body['text'] for secret in self.redactor.secrets if secret)):
            raise PermissionError('bounded exact-route private Google Chat text reply required')
        thread=body.get('thread',{})
        if not isinstance(thread,dict) or set(thread) not in (set(),{'name'}) or not thread_allowed(binding,thread.get('name','')):
            raise PermissionError('reply cannot cross or fall back from approved Google Chat thread')
        encoded=json.dumps(body,sort_keys=True,separators=(',',':'));pin=digest(self.value)
        client_id='client-'+operation[:56];request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'haos-google-chat:'+operation))
        row=self.db.execute('SELECT * FROM google_chat_text_writes WHERE id=?',(operation,)).fetchone()
        if row is not None:
            if any(row[k]!=v for k,v in {'binding_id':binding['id'],'binding_digest':digest(binding),'credential_scope':pin,
                    'parent':parent,'body':encoded,'client_id':client_id,'request_id':request_id}.items()):
                raise Conflict('Google Chat write operation changed source grant, account or body')
            if row['state']=='confirmed':
                name=resource(row['receipt'],'message',space=parent)
                from gateway.platforms.base import SendResult
                return SendResult(success=True,message_id=name)
            # GET is safe after a begun or interrupted create. Not-found does
            # not prove non-delivery and never authorizes another create.
            self.current(route)
            response=await asyncio.to_thread(lambda:adapter._chat_api.spaces().messages().get(
                name=parent+'/messages/'+client_id).execute(http=adapter._new_authed_http(),num_retries=0))
        else:
            count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(body)),0) FROM google_chat_text_writes').fetchone()
            if count>=65536 or size+len(encoded.encode())>8*1024*1024:raise Conflict('Google Chat reply custody full; owner recovery required')
            # Autocommit on a FULL journal precedes the first actual HTTP byte.
            self.current(route)
            self.db.execute('INSERT INTO google_chat_text_writes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (operation,binding['id'],digest(binding),pin,parent,encoded,client_id,request_id,'writing','',time.time()))
            kwargs=_create_kwargs(parent,body);kwargs.update(messageId=client_id,requestId=request_id)
            if thread:kwargs['messageReplyOption']='REPLY_MESSAGE_OR_FAIL'
            response=await asyncio.to_thread(lambda:adapter._chat_api.spaces().messages().create(**kwargs).execute(
                http=adapter._new_authed_http(),num_retries=0))
        self.current(route);name=self._response(response,parent,body,client_id)
        changed=self.db.execute("UPDATE google_chat_text_writes SET state='confirmed',receipt=? WHERE id=? AND state='writing'",
            (name,operation)).rowcount
        if changed!=1:raise Conflict('Google Chat reply acceptance journal changed')
        from gateway.platforms.base import SendResult
        return SendResult(success=True,message_id=name)
