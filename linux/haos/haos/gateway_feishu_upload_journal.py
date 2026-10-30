"""FULL-synchronous per-artifact upload intents; uncertain writes never auto-repeat."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import re
import time

from .gateway import digest,Conflict
from .gateway_feishu_upload import specification,response
from .gateway_feishu_process import ERRORS
from . import gateway_feishu_upload_process as process


class Uploads:
    def __init__(self,adapter):
        self.adapter=adapter;self.native=adapter._haos_native;self.db=self.native.inbox.db
        self.value=deepcopy(adapter._haos_feishu_value);self.scope=digest([self.native.connector,self.value]);self.lock=asyncio.Lock()
        self.db.execute('''CREATE TABLE IF NOT EXISTS feishu_upload_intents(
            delivery_id TEXT NOT NULL,part INTEGER NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,
            credential_scope TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL,error TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,part,attempt))''')
        self.db.execute("UPDATE feishu_upload_intents SET state='uncertain' WHERE state='writing' AND connector=? AND credential_scope=?",
            (self.native.connector,self.scope))

    def current(self,binding,authority):
        authority();self.adapter._haos_feishu_check()
        if not self.adapter.is_connected or self.adapter._haos_feishu_value!=self.value:raise PermissionError('connected unchanged private uploader required')
        latest=self.native.policy().current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if latest!=binding or binding['connector']!=self.native.connector or binding.get('allow_outbound_media') is not True or 'read' not in binding['capabilities']:
            raise PermissionError('current separate exact output/read grant required')

    async def upload(self,binding,delivery_id,attempt,part,source_id,output,authority):
        if (not isinstance(delivery_id,str) or not re.fullmatch('[0-9a-f]{64}',delivery_id)
                or type(attempt) is not int or not 1<=attempt<=5 or type(part) is not int or not 0<=part<4):
            raise ValueError('exact bounded upload delivery attempt and part required')
        if not isinstance(output,dict) or set(output)!={'id','kind','name','size','sha256','file_type','duration_ms','data'}:
            raise ValueError('exact sealed controller artifact required')
        binding=deepcopy(binding);data=output['data']
        def current():self.current(binding,authority)
        current();source=self.adapter._haos_feishu_publisher.source(binding,source_id);raw=source['raw']
        item={'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':delivery_id,'attempt':attempt,
            'source_id':source_id,'source_base64':base64.b64encode(raw).decode(),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'output':{key:value for key,value in output.items() if key!='data'}}
        exact=specification(self.value,self.native.policy(),self.native.connector,item,self.native.inbox.redactor)['target']
        if not isinstance(data,bytes) or len(data)!=exact['size'] or hashlib.sha256(data).hexdigest()!=exact['sha256']:
            raise ValueError('sealed output offer no longer matches original bytes')
        fingerprint=digest([self.value,digest(binding),source['id'],source_id,item['source_sha256'],item['output'],part])
        async with self.lock:
            current();self.adapter._haos_feishu_publisher.source(binding,source_id)
            previous=self.db.execute('SELECT * FROM feishu_upload_intents WHERE delivery_id=? AND part=? ORDER BY attempt',(delivery_id,part)).fetchall()
            for row in previous:
                if row['connector']!=self.native.connector or row['credential_scope']!=self.scope or row['fingerprint']!=fingerprint:
                    raise Conflict('upload changed exact source, owner grant, artifact or account')
                if row['state']=='confirmed':
                    if digest([fingerprint,row['receipt']])!=row['receipt_sha256']:raise Conflict('damaged private upload receipt')
                    return response(json.loads(row['receipt']),exact)
                if row['state'] in {'writing','uncertain'}:return {'state':'uncertain'}
                if row['state'] not in {'rejected','owner-retry-approved'} or row['receipt'] or row['receipt_sha256']:
                    raise Conflict('damaged private upload decision')
                if row['state']=='rejected' and row['error'] not in ERRORS|{'native-refused'}:raise Conflict('damaged upload refusal')
                if row['attempt']==attempt:return {'state':'rejected','error':row['error']}
            if previous and (previous[-1]['attempt']+1!=attempt or previous[-1]['state'] not in {'rejected','owner-retry-approved'}):raise Conflict('sequential approved upload attempt required')
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if (len(previous)>=5 or self.db.execute('SELECT COUNT(*) FROM feishu_upload_intents').fetchone()[0]>=65536
                    or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
                raise Conflict('private upload journal capacity reached; owner recovery required')
            account=self.adapter._haos_feishu_publisher.health();now=time.time()
            blocked=account['status']=='authentication-refused' or account['next_attempt']>now
            error='authentication-refused' if account['status']=='authentication-refused' else 'rate-limited'
            self.db.execute('INSERT INTO feishu_upload_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (delivery_id,part,attempt,self.native.connector,self.scope,fingerprint,'rejected' if blocked else 'writing','',
                    '',error if blocked else '',now,now))
            if blocked:return {'state':'rejected','error':error}
            # Autocommit + synchronous FULL precedes every credential-bearing process.
            try:result=await process.upload(self.value,self.native.connector,current,item,data);current();result=response(result,exact)
            except BaseException:
                self.db.execute("UPDATE feishu_upload_intents SET state='uncertain',updated_at=? WHERE delivery_id=? AND part=? AND attempt=?",
                    (time.time(),delivery_id,part,attempt));raise
            receipt=json.dumps(result,sort_keys=True,separators=(',',':')) if result['state']=='confirmed' else ''
            self.db.execute('UPDATE feishu_upload_intents SET state=?,receipt=?,receipt_sha256=?,error=?,updated_at=? WHERE delivery_id=? AND part=? AND attempt=?',
                (result['state'],receipt,digest([fingerprint,receipt]) if receipt else '',result.get('error',''),time.time(),delivery_id,part,attempt))
            if result.get('error') in {'authentication-refused','rate-limited'}:
                error=result['error'];now=time.time()
                self.db.execute('UPDATE feishu_delivery_backoff SET status=?,next_attempt=?,updated_at=? WHERE account_scope=?',
                    (error,now+60 if error=='rate-limited' else 0,now,self.adapter._haos_feishu_publisher.account_scope))
            return result
