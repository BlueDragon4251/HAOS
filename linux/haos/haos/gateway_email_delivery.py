"""Durable single-write SMTP intents with retained per-source reply context."""
import asyncio
from copy import deepcopy
import re
import time

from .gateway import digest,Conflict
from . import gateway_email_process as process


class Publisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.native=adapter._haos_native;self.db=self.native.inbox.db
        self.value=deepcopy(adapter._haos_email_value);self.lock=asyncio.Lock();self.closed=False
        self.db.execute('''CREATE TABLE IF NOT EXISTS email_delivery_intents(
            delivery_id TEXT NOT NULL,attempt INTEGER NOT NULL,fingerprint TEXT NOT NULL,
            state TEXT NOT NULL,receipt TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,attempt))''')
        self.db.execute("UPDATE email_delivery_intents SET state='uncertain' WHERE state='writing'")

    def current(self,binding,authority):
        authority();self.adapter._haos_email_check()
        if self.closed or not self.adapter.is_connected:raise PermissionError('connected private email publisher required')
        latest=self.native.policy();latest.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if binding['connector']!=self.native.connector or 'read' not in binding['capabilities']:
            raise PermissionError('current exact email read/reply grant required')

    def source(self,binding,source_id):
        if not isinstance(source_id,str) or not re.fullmatch('[0-9a-f]{64}',source_id):
            raise PermissionError('exact retained email reply source required')
        rows=self.db.execute('''SELECT c.rfc_message_id,c.subject FROM native_inbox n
            JOIN email_source_context c ON n.message_id=c.source_id AND n.binding_digest=c.binding_digest
            WHERE n.connector=? AND n.message_id=? AND n.binding_digest=? AND n.state='committed' ''',
            (self.native.connector,source_id,digest(binding))).fetchall()
        if len(rows)!=1:raise PermissionError('one durably admitted email reply context required')
        return dict(rows[0])

    async def send(self,binding,delivery_id,attempt,content,source_id,authority,*,prepared=None):
        from gateway.platforms.base import SendResult
        if (not isinstance(delivery_id,str) or not re.fullmatch('[0-9a-f]{64}',delivery_id)
                or type(attempt) is not int or not 1<=attempt<=5):raise ValueError('exact bounded email outbox attempt required')
        binding=deepcopy(binding)
        def current():self.current(binding,authority)
        current();source=self.source(binding,source_id)
        if (not isinstance(content,str) or not 1<=len(content.strip())<=32000 or len(content.encode())>128000
                or '\0' in content):return SendResult(success=False,error_kind='too_long',raw_response={'haos_delivery':'refused'})
        if self.native.inbox.redactor.text(content)!=content:raise PermissionError('private email credential reflection refused')
        files=[];body=content;parts=[]
        if prepared is not None:
            if (not isinstance(prepared,dict) or set(prepared)!={'items','text'} or not isinstance(prepared['items'],list)
                    or not isinstance(prepared['text'],str)):raise ValueError('exact private email output preparation required')
            body=prepared['text']
            for entry in prepared['items']:
                if not isinstance(entry,dict) or set(entry)!={'id','sha256','size','name','data'}:raise ValueError('exact SMTP snapshot bytes required')
                files.append({key:value for key,value in entry.items() if key!='data'});parts.append(entry['data'])
        from .gateway_email_frame import validate
        validate(files,parts)
        if any(secret.encode() in part for secret in self.native.inbox.redactor.secrets for part in parts):
            raise PermissionError('private email credential reflection refused')
        from .gateway_email_smtp import specification
        blueprint={'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':delivery_id,'attempt':attempt,
            'source_id':source_id,'rfc_message_id':source['rfc_message_id'],'root_message_id':binding['thread'],
            'subject':source['subject'],'body':body,'created_at':int(time.time()),'recipient':binding['chat'],'files':files}
        specification(self.value,self.native.policy(),self.native.connector,blueprint)
        material=[self.value,digest(binding),source_id,source['rfc_message_id'],source['subject'],content]
        # Preserve secured text-only receipts from the preceding private schema.
        fingerprint=digest(material if prepared is None else material+[body,files])
        async with self.lock:
            current();self.source(binding,source_id)
            previous=self.db.execute('SELECT * FROM email_delivery_intents WHERE delivery_id=? ORDER BY attempt',(delivery_id,)).fetchall()
            for row in previous:
                if row['fingerprint']!=fingerprint:raise Conflict('email delivery changed body, source or authority')
                if row['state']=='confirmed':
                    if not re.fullmatch('smtp_accept_[0-9a-f]{64}',row['receipt']):raise Conflict('damaged SMTP acceptance receipt')
                    return SendResult(success=True,message_id=row['receipt'],raw_response={'recipient_receipt_verified':False})
                if row['state'] in {'writing','uncertain'}:return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
                if row['state']!='rejected' or row['receipt']:raise Conflict('damaged email delivery intent')
                if row['attempt']==attempt:return SendResult(success=False,raw_response={'haos_delivery':'refused'})
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if len(previous)>=5 or self.db.execute('SELECT COUNT(*) FROM email_delivery_intents').fetchone()[0]>=65536 or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024:
                raise Conflict('private email delivery capacity reached')
            now=int(time.time())
            self.db.execute('INSERT INTO email_delivery_intents VALUES(?,?,?,?,?,?,?)',(delivery_id,attempt,fingerprint,'writing','',now,time.time()))
            item={**blueprint,'created_at':now}
            try:
                result=await process.smtp(self.value,self.native.connector,current,item,files=parts);current()
                accepted=result.get('accepted') is True;error=result.get('error')
                rejected=error in {'smtp-authentication-refused','smtp-temporary-refusal','smtp-permanent-refusal','tls-refused'}
                self.db.execute('UPDATE email_delivery_intents SET state=?,receipt=?,updated_at=? WHERE delivery_id=? AND attempt=?',
                    ('confirmed' if accepted else 'rejected' if rejected else 'uncertain',result['receipt'] if accepted else '',time.time(),delivery_id,attempt))
                if accepted:return SendResult(success=True,message_id=result['receipt'],raw_response={'recipient_receipt_verified':False})
                if rejected:
                    kind='rate_limited' if error=='smtp-temporary-refusal' else 'forbidden' if error in {'smtp-authentication-refused','tls-refused'} else 'bad_format'
                    return SendResult(success=False,error_kind=kind,retry_after=30,raw_response={'haos_delivery':'refused','email_error':error})
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            except asyncio.CancelledError:raise
            except PermissionError:raise
            except Exception:
                self.db.execute("UPDATE email_delivery_intents SET state='uncertain',updated_at=? WHERE delivery_id=? AND attempt=?",(time.time(),delivery_id,attempt))
                return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})

    async def close(self):
        self.closed=True
        async with self.lock:pass
