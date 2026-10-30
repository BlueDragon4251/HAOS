"""Immutable batch manifests and FULL per-part native upload/message receipts."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import re
import time

from .gateway import Conflict,digest
from .gateway_dingtalk_parts import Journal
from .gateway_dingtalk_upload import specification as upload_specification,response as upload_response
from .gateway_dingtalk_upload_http import verify_bytes
from .gateway_dingtalk_media_reply import specification as reply_specification,wire_target
from .gateway_dingtalk_reply_process import response as reply_response
from . import gateway_dingtalk_upload_process as upload_process
from . import gateway_dingtalk_media_reply_process as reply_process

UPLOAD_FIELDS={'id','kind','name','size','sha256','mime'}
OUTPUT_FIELDS=UPLOAD_FIELDS|{'data','duration_ms','width','height','cover'}


class MediaPublisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.native=adapter._haos_native;self.db=self.native.inbox.db
        self.publisher=adapter._haos_dingtalk_publisher;self.value=deepcopy(adapter._haos_dingtalk_value)
        self.uploads=Journal(adapter,'upload');self.replies=Journal(adapter,'reply');self.scope=self.uploads.scope
        self.lock=asyncio.Lock();self.closed=False
        self.db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_output_manifests(
            delivery_id TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,source_sha256 TEXT NOT NULL,
            fingerprint TEXT NOT NULL,manifest TEXT NOT NULL,created_at REAL NOT NULL)''')

    def current(self,binding,authority):
        if self.closed or self.adapter._haos_dingtalk_value!=self.value:
            raise PermissionError('active unchanged private media publisher required')
        self.publisher.current(binding,authority)
        if binding.get('allow_outbound_media') is not True:
            raise PermissionError('separate current media output/read approval required')

    def intent(self,binding,delivery_id,attempt,source_id,output):
        source=self.publisher.source(binding,source_id);raw=source['raw']
        return {'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':delivery_id,'attempt':attempt,
            'source_id':source_id,'source_sha256':hashlib.sha256(raw).hexdigest(),'source_base64':base64.b64encode(raw).decode(),
            'output':{key:output[key] for key in UPLOAD_FIELDS}}

    def preflight(self,binding,delivery_id,attempt,source_id,prepared):
        if (not isinstance(prepared,dict) or set(prepared)!={'items','text'} or not isinstance(prepared['items'],list)
                or not 1<=len(prepared['items'])<=4 or not isinstance(prepared['text'],str)
                or len(prepared['text'])>4000 or len(prepared['text'].encode())>16000
                or self.native.inbox.redactor.text(prepared['text'])!=prepared['text']):
            raise ValueError('one bounded private sealed-output batch and credential-free caption required')
        manifest=[]
        for part,output in enumerate(prepared['items']):
            if not isinstance(output,dict) or set(output)!=OUTPUT_FIELDS:
                raise ValueError('exact sealed Robot output metadata required')
            intent=self.intent(binding,delivery_id,attempt,source_id,output)
            checked=upload_specification(self.value,self.native.policy(),self.native.connector,intent,self.native.inbox.redactor)
            verify_bytes(checked['target'],output['data'],self.native.inbox.redactor)
            if not re.fullmatch(r'result-'+str(part)+r'\.[a-z0-9]{1,4}',output['name']):
                raise PermissionError('immutable original part position and path-free name required')
            if any(type(output[key]) is not int for key in ['duration_ms','width','height']):
                raise ValueError('exact integer media duration and display dimensions required')
            cover=output['cover']
            if output['kind'] in {'image','file'}:
                if cover is not None or any(output[key] for key in ['duration_ms','width','height']):
                    raise ValueError('image/document cannot acquire unrelated audio/video metadata')
            elif output['kind']=='voice':
                from .audio_amr import duration_samples
                expected=(duration_samples(output['data'])*1000+15999)//16000
                if output['duration_ms']!=expected or output['width'] or output['height'] or cover is not None:
                    raise ValueError('voice duration must match exact sealed AMR frames')
            else:
                if (not 1<=output['duration_ms']<=120020 or not 1<=output['width']<=4096 or not 1<=output['height']<=4096
                        or not isinstance(cover,dict) or set(cover)!=UPLOAD_FIELDS|{'data','source_sha256'}
                        or cover['source_sha256']!=output['sha256'] or cover['kind']!='image' or cover['name']!='cover-'+str(part)+'.png'):
                    raise PermissionError('bounded video and exact source-bound private thumbnail required')
                thumbnail=self.intent(binding,delivery_id,attempt,source_id,cover)
                reviewed=upload_specification(self.value,self.native.policy(),self.native.connector,thumbnail,self.native.inbox.redactor)
                verify_bytes(reviewed['target'],cover['data'],self.native.inbox.redactor)
            entry={key:value for key,value in output.items() if key not in {'data','cover'}}
            entry['cover']={key:value for key,value in cover.items() if key!='data'} if cover is not None else None
            manifest.append(entry)
        return {'items':manifest,'text':prepared['text']}

    def manifest(self,binding,delivery_id,source_id,body):
        source=self.publisher.source(binding,source_id);checksum=hashlib.sha256(source['raw']).hexdigest()
        fingerprint=digest([self.value,digest(binding),source['id'],source_id,checksum,body])
        encoded=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        if len(encoded.encode())>32768:raise ValueError('bounded sealed batch manifest required')
        prior=self.db.execute('SELECT * FROM dingtalk_output_manifests WHERE delivery_id=?',(delivery_id,)).fetchone()
        if prior is not None:
            expected={'connector':self.native.connector,'credential_scope':self.scope,'binding_id':binding['id'],
                'binding_digest':digest(binding),'source_sha256':checksum,'fingerprint':fingerprint,'manifest':encoded}
            if any(prior[key]!=value for key,value in expected.items()):
                raise Conflict('media delivery changed its full original batch, caption, source, codec or approval')
            return fingerprint
        if self.db.execute('SELECT 1 FROM dingtalk_delivery_intents WHERE delivery_id=?',(delivery_id,)).fetchone():
            raise Conflict('ordinary text delivery cannot become a new media batch')
        pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
        if (self.db.execute('SELECT COUNT(*) FROM dingtalk_output_manifests').fetchone()[0]>=65536
                or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
            raise Conflict('private output manifest journal full; owner recovery required')
        self.db.execute('INSERT INTO dingtalk_output_manifests VALUES(?,?,?,?,?,?,?,?,?)',
            (delivery_id,self.native.connector,self.scope,binding['id'],digest(binding),checksum,fingerprint,encoded,time.time()))
        return fingerprint

    async def upload(self,binding,delivery_id,attempt,part,source_id,output,manifest,current):
        current();item=self.intent(binding,delivery_id,attempt,source_id,output)
        target=upload_specification(self.value,self.native.policy(),self.native.connector,item,self.native.inbox.redactor)['target']
        stable=deepcopy(item);stable.pop('attempt')
        fingerprint=digest([self.value,stable,part,manifest])
        async def invoke(checked):return await upload_process.upload(self.value,self.native.connector,checked,item,output['data'])
        receipt=await self.uploads.perform(binding,delivery_id,attempt,part,fingerprint,lambda value:upload_response(value,target),invoke,current)
        return item,receipt

    async def reply(self,binding,delivery_id,attempt,part,item,manifest,current):
        current();checked=reply_specification(self.value,self.native.policy(),self.native.connector,item,self.native.inbox.redactor)
        target=wire_target(self.adapter,checked['blueprint'],checked['media'])
        stable=deepcopy(item);stable['upload'].pop('attempt')
        if stable['cover'] is not None:stable['cover']['upload'].pop('attempt')
        fingerprint=digest([self.value,stable,manifest,part,target['url'],target['payload']])
        async def invoke(approved):return await reply_process.media_reply(self.value,self.native.connector,approved,item)
        return await self.replies.perform(binding,delivery_id,attempt,part,fingerprint,reply_response,invoke,current)

    def refused(self,result):
        from gateway.platforms.base import SendResult
        if result['state']=='rejected':return self.publisher.refusal(result['error'],max(1,result['retry_after']))
        return SendResult(success=False,raw_response={'haos_delivery':'uncertain'})

    async def send(self,binding,delivery_id,attempt,source_id,prepared,authority):
        from gateway.platforms.base import SendResult
        if (not isinstance(delivery_id,str) or not re.fullmatch('[0-9a-f]{64}',delivery_id)
                or type(attempt) is not int or not 1<=attempt<=5):raise ValueError('exact bounded media delivery attempt required')
        binding=deepcopy(binding)
        def current():
            self.current(binding,authority);self.publisher.source(binding,source_id)
        async with self.lock:
            current();body=self.preflight(binding,delivery_id,attempt,source_id,prepared)
            manifest=self.manifest(binding,delivery_id,source_id,body)
            # The complete immutable batch precedes the first caption or upload.
            caption=None
            if prepared['text'].strip():
                text=await self.publisher.send(binding,delivery_id,attempt,prepared['text'],source_id,current)
                if text.success is not True:return text
                caption=text.message_id
            accepted=[]
            for part,output in enumerate(prepared['items']):
                current();upload,receipt=await self.upload(binding,delivery_id,attempt,part,source_id,output,manifest,current)
                if receipt['state']!='confirmed':return self.refused(receipt)
                cover=None
                if output['cover'] is not None:
                    cover_upload,cover_receipt=await self.upload(binding,delivery_id,attempt,part+4,source_id,output['cover'],manifest,current)
                    if cover_receipt['state']!='confirmed':return self.refused(cover_receipt)
                    cover={'upload':cover_upload,'receipt':cover_receipt}
                item={'upload':upload,'receipt':receipt,'duration_ms':output['duration_ms'],
                    'width':output['width'],'height':output['height'],'cover':cover}
                result=await self.reply(binding,delivery_id,attempt,part,item,manifest,current)
                if result['state']!='confirmed':return self.refused(result)
                accepted.append(result['acceptance_id'])
            current()
            local='haos-dingtalk-'+digest([delivery_id,manifest,caption,accepted])
            return SendResult(success=True,message_id=local,raw_response={'remote_message_id':None,
                'recipient_read_verified':False,'local_vendor_acceptance_only':True,'confirmed_parts':len(accepted)})

    async def close(self):
        self.closed=True
        async with self.lock:pass
