"""Read sealed controller snapshots and retain local codec results; never open agent paths."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import PurePosixPath
import re
import time
import zipfile

from .gateway import Conflict,digest
from .gateway_media import MAX_BYTES,CHUNK_BYTES
from .gateway_outbound import approved,marked
from .gateway_dingtalk_upload_http import FORMATS
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object


class Output:
    def __init__(self,adapter):
        self.adapter=adapter;self.db=adapter._haos_native.inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_output_transforms(
            id TEXT PRIMARY KEY,proof TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,sha256 TEXT NOT NULL,metadata TEXT NOT NULL,data BLOB NOT NULL,created_at REAL NOT NULL)''')

    def current(self,delivery):
        adapter=self.adapter;policy=adapter._haos_native.policy();binding=approved(policy,delivery)
        adapter._haos_dingtalk_publisher.current(binding,adapter._haos_dingtalk_check)
        if (policy.connectors[binding['connector']]['platform']!='dingtalk' or binding['connector']!=adapter._haos_native.connector):
            raise PermissionError('exact current native DingTalk output route required')
        return binding

    def scan(self,data):
        if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise ValueError('bounded sealed output bytes required')
        values=set(self.adapter._haos_native.inbox.redactor.secrets)
        # Scan before compression/encoding too: transport scanning cannot inspect
        # a plaintext credential once an otherwise valid codec has transformed it.
        values.add(self.adapter._haos_dingtalk_value['client_secret'])
        for _ in range(2):
            values|={json.dumps(value,ensure_ascii=ascii)[1:-1] for value in tuple(values) for ascii in (True,False)}
            values|={repr(value)[1:-1] for value in tuple(values)}
        if any(value.encode() in data for value in values):raise PermissionError('private DingTalk credential reflection refused')

    async def transform(self,delivery,offer,operation,build):
        binding=self.current(delivery);identity=digest([delivery['id'],offer['id'],operation])
        proof=digest([delivery['id'],offer,binding,operation])
        def retained():
            row=self.db.execute('SELECT * FROM dingtalk_output_transforms WHERE id=?',(identity,)).fetchone()
            if row is None:return None
            data=bytes(row['data'])
            if (row['proof']!=proof or row['binding_id']!=binding['id'] or row['binding_digest']!=digest(binding)
                    or row['source_sha256']!=offer['sha256'] or not 1<=len(data)<=MAX_BYTES
                    or hashlib.sha256(data).hexdigest()!=row['sha256'] or len(row['metadata'].encode())>32768):
                raise Conflict('retained output conversion changed, was purged or lost its approval')
            try:metadata=json.loads(row['metadata'],object_pairs_hook=_object,parse_constant=finite)
            except (ValueError,RecursionError):raise Conflict('retained output conversion metadata damaged') from None
            if (not isinstance(metadata,dict) or metadata.get('sha256')!=row['sha256'] or metadata.get('size')!=len(data)
                    or 'data' in metadata or json.dumps(metadata,sort_keys=True,separators=(',',':'))!=row['metadata']):
                raise Conflict('retained output conversion descriptor damaged')
            self.scan(data);return {**metadata,'data':data}
        previous=retained()
        if previous is not None:return previous
        def capacity(extra=0):
            count=self.db.execute('SELECT COUNT(*) FROM dingtalk_output_transforms WHERE length(data)>0').fetchone()[0]
            total=self.db.execute('SELECT COUNT(*) FROM dingtalk_output_transforms').fetchone()[0]
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if count>=128 or total>=65536 or pages*self.db.execute('PRAGMA page_size').fetchone()[0]+extra>=64*1024*1024:
                raise Conflict('private output conversion storage full; owner recovery required')
        capacity();converted=await build();self.current(delivery)
        if not isinstance(converted,dict) or not isinstance(converted.get('data'),bytes):raise ValueError('closed local media conversion required')
        data=converted['data'];self.scan(data);metadata={key:value for key,value in converted.items() if key!='data'}
        metadata.update(size=len(data),sha256=hashlib.sha256(data).hexdigest())
        encoded=json.dumps(metadata,sort_keys=True,separators=(',',':'))
        if len(encoded.encode())>32768:raise ValueError('bounded local conversion descriptor required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous=retained()
            if previous is None:
                capacity(len(data)+len(encoded.encode()))
                self.db.execute('INSERT INTO dingtalk_output_transforms VALUES(?,?,?,?,?,?,?,?,?)',
                    (identity,proof,binding['id'],digest(binding),offer['sha256'],metadata['sha256'],encoded,data,time.time()))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return previous if previous is not None else {**metadata,'data':data}

    async def voice(self,delivery,offer,data,part):
        async def build():
            from .speech_client import amr
            encoded=await amr(data,lambda:self.current(delivery))
            if encoded['source_sha256']!=offer['sha256']:raise Conflict('encoded voice source changed')
            return {'id':offer['id'],'kind':'voice','name':f'result-{part}.amr','mime':'audio/amr',
                'data':encoded['data'],'duration_ms':(encoded['encoded_samples']*1000+15999)//16000,'width':0,'height':0,'cover':None}
        return await self.transform(delivery,offer,'amr-nb-12200-v1',build)

    async def archive(self,delivery,offer,data,part,suffix):
        async def build():
            output=BytesIO();name='result-'+str(part)+(suffix if re.fullmatch(r'\.[a-z0-9]{1,16}',suffix) else '.bin')
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100600<<16
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:archive.writestr(info,data)
            return {'id':offer['id'],'kind':'file','name':f'result-{part}.zip','mime':'application/zip',
                'data':output.getvalue(),'duration_ms':0,'width':0,'height':0,'cover':None}
        return await self.transform(delivery,offer,'zip-v1',build)

    async def preview(self,delivery,offer,data,part):
        async def build():
            from .speech_client import thumbnail
            decoded=await thumbnail(data,lambda:self.current(delivery))
            if decoded['source_sha256']!=offer['sha256']:raise Conflict('decoded video preview source changed')
            return {'id':digest([offer['id'],'cover-v1']),'kind':'image','name':f'cover-{part}.png','mime':'image/png',
                'data':decoded['data'],'source_sha256':offer['sha256'],'duration_ms':decoded['duration_ms'],
                'width':decoded['width'],'height':decoded['height']}
        return await self.transform(delivery,offer,'png-cover-v1',build)

    async def prepare(self,delivery,call):
        paths,cleaned=marked(delivery['content'])
        if not paths:return None
        from gateway.platforms.base import BasePlatformAdapter,_AUDIO_EXTS
        native_paths,_=BasePlatformAdapter.extract_media(delivery['content']);native_set={path for path,_ in native_paths}
        for path in paths:
            if not path.startswith(('~/','./')) and PurePosixPath(path).suffix.lower()!='.bin' and path not in native_set:
                raise PermissionError('native media extractor disagrees with explicit DingTalk output')
        self.adapter._haos_dingtalk_check()
        policy=self.adapter._haos_native.policy();binding=policy.current_binding(delivery)
        if (binding['connector']!=self.adapter._haos_native.connector or policy.connectors[binding['connector']]['platform']!='dingtalk'
                or 'read' not in binding['capabilities']):raise PermissionError('exact private output/read route required')
        if binding.get('allow_outbound_media') is not True:
            return {'items':[],'text':cleaned+'\n[Result files require separate owner approval.]'}
        if self.adapter._haos_dingtalk_value.get('reply_mode','session')!='robot':
            raise PermissionError('DingTalk result files require explicitly selected Robot reply mode')
        items=[]
        for part,path in enumerate(paths):
            self.current(delivery)
            offer=await call('gateway.output.begin',{'delivery':delivery['id'],'attempt':delivery['attempt'],'path':path})
            if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'} or type(offer['size']) is not int
                    or not 1<=offer['size']<=MAX_BYTES or any(not isinstance(offer[key],str) or not re.fullmatch('[0-9a-f]{64}',offer[key]) for key in ['id','sha256'])):
                raise ValueError('bounded exact private controller artifact offer required')
            data=bytearray()
            while len(data)<offer['size']:
                self.current(delivery)
                chunk=await call('gateway.output.chunk',{'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':len(data)})
                if (not isinstance(chunk,dict) or set(chunk)!={'id','offset','data'} or chunk['id']!=offer['id']
                        or type(chunk['offset']) is not int or chunk['offset']!=len(data) or not isinstance(chunk['data'],str)
                        or len(chunk['data'])>4*((CHUNK_BYTES+2)//3)):
                    raise ValueError('exact bounded controller artifact chunk required')
                raw=base64.b64decode(chunk['data'],validate=True)
                if base64.b64encode(raw).decode()!=chunk['data'] or not 1<=len(raw)<=CHUNK_BYTES or len(data)+len(raw)>offer['size']:
                    raise ValueError('sealed artifact chunk size changed')
                data.extend(raw)
            self.current(delivery);data=bytes(data)
            if hashlib.sha256(data).hexdigest()!=offer['sha256']:raise Conflict('controller artifact bytes changed')
            self.scan(data);suffix=PurePosixPath(path).suffix.lower();extension=suffix.lstrip('.')
            document='[[as_document]]' in delivery['content']
            if extension in {'png','jpg','jpeg'} and not document:
                mime=FORMATS['image'][extension];kind='image'
                output={**offer,'data':data,'name':f'result-{part}{suffix}','kind':kind,'mime':mime,'duration_ms':0,'width':0,'height':0,'cover':None}
            elif suffix in _AUDIO_EXTS and not document:
                if binding.get('allow_voice') is not True:raise PermissionError('separate voice output approval required')
                output=await self.voice(delivery,offer,data,part)
            elif extension=='mp4' and not document:
                if binding.get('allow_video') is not True:raise PermissionError('separate video output approval required')
                preview=await self.preview(delivery,offer,data,part)
                cover={key:value for key,value in preview.items() if key not in {'duration_ms','width','height'}}
                output={**offer,'data':data,'name':f'result-{part}.mp4','kind':'video','mime':'video/mp4',
                    'duration_ms':preview['duration_ms'],'width':preview['width'],'height':preview['height'],'cover':cover}
            elif extension in FORMATS['file']:
                output={**offer,'data':data,'name':f'result-{part}{suffix}','kind':'file','mime':FORMATS['file'][extension],
                    'duration_ms':0,'width':0,'height':0,'cover':None}
            else:output=await self.archive(delivery,offer,data,part,suffix)
            items.append(output)
        self.current(delivery)
        return {'items':items,'text':cleaned}
