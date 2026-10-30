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
            state TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL,owner_retry_generation INTEGER NOT NULL DEFAULT 0)''')
        if 'owner_retry_generation' not in {row[1] for row in self.db.execute('PRAGMA table_info(google_chat_text_writes)')}:
            self.db.execute('ALTER TABLE google_chat_text_writes ADD COLUMN owner_retry_generation INTEGER NOT NULL DEFAULT 0')

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
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter
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
            if row['state'] not in {'writing','owner-retry-approved'}:raise Conflict('damaged Google Chat text write state')
            # Always look for late acceptance first, including after an Owner
            # decision. A 404 alone still never authorizes another create.
            self.current(route)
            try:
                response=await asyncio.to_thread(lambda:adapter._chat_api.spaces().messages().get(
                    name=parent+'/messages/'+client_id).execute(http=adapter._new_authed_http(),num_retries=0))
            except Exception as error:
                from googleapiclient.errors import HttpError
                if not isinstance(error,HttpError) or error.resp.status!=404 or row['state']!='owner-retry-approved':raise
                self.current(route)
                self._consume_retry(row)
                response=await self._post(adapter,parent,body,client_id,request_id)
        else:
            count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(body)),0) FROM google_chat_text_writes').fetchone()
            if count>=65536 or size+len(encoded.encode())>8*1024*1024:raise Conflict('Google Chat reply custody full; owner recovery required')
            # Autocommit on a FULL journal precedes the first actual HTTP byte.
            self.current(route)
            self.db.execute('INSERT INTO google_chat_text_writes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (operation,binding['id'],digest(binding),pin,parent,encoded,client_id,request_id,'writing','',time.time(),0))
            response=await self._post(adapter,parent,body,client_id,request_id)
        self.current(route);name=self._response(response,parent,body,client_id)
        self._confirm(operation,name)
        from gateway.platforms.base import SendResult
        return SendResult(success=True,message_id=name)

    def _confirm(self,operation,name):
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            row=db.execute('SELECT * FROM google_chat_text_writes WHERE id=?',(operation,)).fetchone()
            if row is None or row['state'] not in {'writing','owner-retry-approved'}:raise Conflict('Google Chat reply acceptance journal changed')
            if row['state']=='owner-retry-approved':
                changed=db.execute("UPDATE google_chat_reply_owner_events SET consumed_at=? WHERE part_id=? AND generation=? AND consumed_at IS NULL",
                    (time.time(),operation,row['owner_retry_generation'])).rowcount
                if changed!=1:raise Conflict('Google Chat reconciliation has no durable Owner decision')
            db.execute("UPDATE google_chat_text_writes SET state='confirmed',receipt=? WHERE id=?",(name,operation))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def _consume_retry(self,row):
        # Both consumption and its audit become durable before a new HTTP byte.
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            changed=db.execute("UPDATE google_chat_text_writes SET state='writing' WHERE id=? AND state='owner-retry-approved' AND owner_retry_generation=?",
                (row['id'],row['owner_retry_generation'])).rowcount
            audited=db.execute("UPDATE google_chat_reply_owner_events SET consumed_at=? WHERE part_id=? AND generation=? AND consumed_at IS NULL",
                (time.time(),row['id'],row['owner_retry_generation'])).rowcount
            if changed!=1 or audited!=1:raise Conflict('Google Chat retry approval changed or has no durable Owner audit')
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    async def _post(self,adapter,parent,body,client_id,request_id):
        from plugins.platforms.google_chat.adapter import _create_kwargs
        kwargs=_create_kwargs(parent,body);kwargs.update(messageId=client_id,requestId=request_id)
        if body.get('thread'):kwargs['messageReplyOption']='REPLY_MESSAGE_OR_FAIL'
        return await asyncio.to_thread(lambda:adapter._chat_api.spaces().messages().create(**kwargs).execute(
            http=adapter._new_authed_http(),num_retries=0))
