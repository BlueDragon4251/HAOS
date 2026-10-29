"""Per-artifact native upload/reply receipts for one durable HAOS delivery."""
import asyncio
from copy import deepcopy
import json
import time

from .gateway import digest,Conflict
from .gateway_feishu_upload_journal import Uploads
from .gateway_feishu_upload import specification as upload_specification
from .gateway_feishu_media_reply import specification,wire_target
from .gateway_feishu_process import media_reply,reply_response,ERRORS


class MediaPublisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.native=adapter._haos_native;self.db=self.native.inbox.db
        self.uploads=Uploads(adapter);self.scope=self.uploads.scope;self.lock=asyncio.Lock();self.closed=False
        self.db.execute('''CREATE TABLE IF NOT EXISTS feishu_media_reply_intents(
            delivery_id TEXT NOT NULL,part INTEGER NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,
            credential_scope TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL,error TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,part,attempt))''')
        self.db.execute("UPDATE feishu_media_reply_intents SET state='uncertain' WHERE state='writing' AND connector=? AND credential_scope=?",
            (self.native.connector,self.scope))

    def current(self,binding,authority):
        if self.closed:raise PermissionError('private media publisher closed')
        self.uploads.current(binding,authority)

    async def reply(self,binding,delivery_id,attempt,part,upload,receipt,caption,authority):
        def current():self.current(binding,authority)
        current();item={'upload':upload,'receipt':receipt,'caption':caption}
        blueprint=specification(self.uploads.value,self.native.policy(),self.native.connector,item,self.native.inbox.redactor)
        from .gateway_matrix_profile import scope
        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter
        with scope(self.adapter._haos_feishu_home,self.adapter._haos_feishu_environment):
            codec=FeishuAdapter(PlatformConfig(enabled=True));codec._haos_media_binding=binding;exact,_=wire_target(codec,blueprint)
        stable=deepcopy(blueprint);stable['upload']['intent'].pop('attempt')
        fingerprint=digest([self.uploads.value,stable,exact,part])
        previous=self.db.execute('SELECT * FROM feishu_media_reply_intents WHERE delivery_id=? AND part=? ORDER BY attempt',(delivery_id,part)).fetchall()
        for row in previous:
            if row['connector']!=self.native.connector or row['credential_scope']!=self.scope or row['fingerprint']!=fingerprint:
                raise Conflict('media reply changed account, source, artifact, caption or wire UUID')
            if row['state']=='confirmed':
                if digest([fingerprint,row['receipt']])!=row['receipt_sha256']:raise Conflict('damaged media reply receipt')
                return reply_response(json.loads(row['receipt']))
            if row['state'] in {'writing','uncertain'}:return {'state':'uncertain'}
            if row['state'] not in {'rejected','owner-retry-approved'} or row['receipt'] or row['receipt_sha256']:
                raise Conflict('damaged private media reply decision')
            if row['state']=='rejected' and row['error'] not in ERRORS|{'native-refused'}:raise Conflict('damaged media reply refusal')
            if row['attempt']==attempt:return {'state':'rejected','error':row['error']}
        if previous and (previous[-1]['attempt']+1!=attempt or previous[-1]['state'] not in {'rejected','owner-retry-approved'}):raise Conflict('sequential approved media reply attempt required')
        pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
        if (len(previous)>=5 or self.db.execute('SELECT COUNT(*) FROM feishu_media_reply_intents').fetchone()[0]>=65536
                or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
            raise Conflict('private media reply journal full; owner recovery required')
        account=self.adapter._haos_feishu_publisher.health();now=time.time()
        blocked=account['status']=='authentication-refused' or account['next_attempt']>now
        error='authentication-refused' if account['status']=='authentication-refused' else 'rate-limited'
        self.db.execute('INSERT INTO feishu_media_reply_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (delivery_id,part,attempt,self.native.connector,self.scope,fingerprint,'rejected' if blocked else 'writing','',
                '',error if blocked else '',now,now))
        if blocked:return {'state':'rejected','error':error}
        try:result=await media_reply(self.uploads.value,self.native.connector,current,item);current();result=reply_response(result)
        except BaseException:
            self.db.execute("UPDATE feishu_media_reply_intents SET state='uncertain',updated_at=? WHERE delivery_id=? AND part=? AND attempt=?",
                (time.time(),delivery_id,part,attempt));raise
        stored=json.dumps(result,sort_keys=True,separators=(',',':')) if result['state']=='confirmed' else ''
        self.db.execute('UPDATE feishu_media_reply_intents SET state=?,receipt=?,receipt_sha256=?,error=?,updated_at=? WHERE delivery_id=? AND part=? AND attempt=?',
            (result['state'],stored,digest([fingerprint,stored]) if stored else '',result.get('error',''),time.time(),delivery_id,part,attempt))
        if result.get('error') in {'authentication-refused','rate-limited'}:
            now=time.time();error=result['error']
            self.db.execute('UPDATE feishu_delivery_backoff SET status=?,next_attempt=?,updated_at=? WHERE account_scope=?',
                (error,now+60 if error=='rate-limited' else 0,now,self.adapter._haos_feishu_publisher.account_scope))
        return result

    async def send(self,binding,delivery_id,attempt,source_id,prepared,authority):
        from gateway.platforms.base import SendResult
        if (not isinstance(prepared,dict) or set(prepared)!={'items','text'} or not isinstance(prepared['items'],list)
                or not 1<=len(prepared['items'])<=4 or not isinstance(prepared['text'],str)):
            raise ValueError('bounded sealed media output batch required')
        binding=deepcopy(binding)
        def current():self.current(binding,authority)
        async with self.lock:
            current();last=None
            if len(prepared['text'])>4000 or len(prepared['text'].encode())>16000 or self.native.inbox.redactor.text(prepared['text'])!=prepared['text']:
                raise ValueError('bounded credential-free media caption required before upload')
            # Validate the complete sealed batch before its first side effect.
            source=self.adapter._haos_feishu_publisher.source(binding,source_id);raw=source['raw']
            import base64,hashlib
            for output in prepared['items']:
                if not isinstance(output,dict) or set(output)!={'id','kind','name','size','sha256','file_type','duration_ms','data'}:
                    raise ValueError('exact sealed media artifact required')
                intent={'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':delivery_id,'attempt':attempt,
                    'source_id':source_id,'source_base64':base64.b64encode(raw).decode(),'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'output':{key:value for key,value in output.items() if key!='data'}}
                target=upload_specification(self.uploads.value,self.native.policy(),self.native.connector,intent,self.native.inbox.redactor)['target']
                if not isinstance(output['data'],bytes) or len(output['data'])!=target['size'] or hashlib.sha256(output['data']).hexdigest()!=target['sha256']:
                    raise ValueError('sealed artifact bytes changed before upload')
            for part,output in enumerate(prepared['items']):
                receipt=await self.uploads.upload(binding,delivery_id,attempt,part,source_id,output,current);current()
                if receipt['state']!='confirmed':
                    return self.adapter._haos_feishu_publisher.refusal(receipt['error']) if receipt['state']=='rejected' else SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
                source=self.adapter._haos_feishu_publisher.source(binding,source_id);raw=source['raw']
                import base64,hashlib
                upload={'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':delivery_id,'attempt':attempt,
                    'source_id':source_id,'source_base64':base64.b64encode(raw).decode(),'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'output':{key:value for key,value in output.items() if key!='data'}}
                upload_specification(self.uploads.value,self.native.policy(),self.native.connector,upload,self.native.inbox.redactor)
                last=await self.reply(binding,delivery_id,attempt,part,upload,receipt,prepared['text'] if part==0 else '',current)
                if last['state']!='confirmed':
                    return self.adapter._haos_feishu_publisher.refusal(last['error']) if last['state']=='rejected' else SendResult(success=False,raw_response={'haos_delivery':'uncertain'})
            current();return SendResult(success=True,message_id=last['message_id'],raw_response={'recipient_read_verified':False,'confirmed_parts':len(prepared['items'])})

    async def close(self):
        self.closed=True
        async with self.lock:pass
