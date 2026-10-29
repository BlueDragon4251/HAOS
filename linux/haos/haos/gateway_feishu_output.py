"""Read exact controller-owned output snapshots; never open an agent host path."""
import base64
import hashlib
from pathlib import PurePosixPath
import re

from .gateway_media import MAX_BYTES,CHUNK_BYTES
from .gateway_outbound import approved,marked


class Output:
    def __init__(self,adapter):self.adapter=adapter

    def current(self,delivery):
        self.adapter._haos_feishu_check()
        if not self.adapter.is_connected:raise PermissionError('connected private Feishu identity required')
        policy=self.adapter._haos_native.policy();binding=approved(policy,delivery)
        if (policy.connectors[binding['connector']]['platform']!='feishu'
                or binding['connector']!=self.adapter._haos_native.connector):raise PermissionError('exact current Feishu output route required')
        return binding

    async def prepare(self,delivery,call):
        paths,cleaned=marked(delivery['content'])
        if not paths:return None
        from gateway.platforms.base import BasePlatformAdapter
        native_paths,_=BasePlatformAdapter.extract_media(delivery['content']);native_set={path for path,_ in native_paths}
        for path in paths:
            if not path.startswith(('~/','./')) and PurePosixPath(path).suffix.lower()!='.bin' and path not in native_set:
                raise PermissionError('native media extractor disagrees with the explicit Feishu output')
        binding=self.adapter._haos_native.policy().current_binding(delivery)
        if binding.get('allow_outbound_media') is not True:
            return {'items':[],'text':cleaned+'\n[Result files require separate owner approval.]'}
        self.current(delivery);items=[]
        for index,path in enumerate(paths):
            self.current(delivery)
            offer=await call('gateway.output.begin',{'delivery':delivery['id'],'attempt':delivery['attempt'],'path':path})
            if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'}
                    or type(offer['size']) is not int or not 1<=offer['size']<=MAX_BYTES
                    or any(not isinstance(offer[key],str) or not re.fullmatch('[0-9a-f]{64}',offer[key]) for key in ('id','sha256'))):
                raise ValueError('bounded exact private Feishu artifact offer required')
            data=bytearray()
            while len(data)<offer['size']:
                self.current(delivery)
                chunk=await call('gateway.output.chunk',{'delivery':delivery['id'],'attempt':delivery['attempt'],
                    'id':offer['id'],'offset':len(data)})
                if (not isinstance(chunk,dict) or set(chunk)!={'id','offset','data'} or chunk['id']!=offer['id']
                        or type(chunk['offset']) is not int or chunk['offset']!=len(data) or not isinstance(chunk['data'],str)
                        or len(chunk['data'])>4*((CHUNK_BYTES+2)//3)):
                    raise ValueError('exact private Feishu artifact chunk required')
                part=base64.b64decode(chunk['data'],validate=True)
                if (base64.b64encode(part).decode()!=chunk['data'] or not 1<=len(part)<=CHUNK_BYTES
                        or len(data)+len(part)>offer['size']):raise ValueError('private Feishu artifact chunk size changed')
                data.extend(part)
            self.current(delivery);data=bytes(data)
            if hashlib.sha256(data).hexdigest()!=offer['sha256']:raise ValueError('private Feishu artifact checksum changed')
            if any(secret.encode() in data for secret in self.adapter._haos_native.inbox.redactor.secrets):
                raise PermissionError('private Feishu credential reflection refused')
            from plugins.platforms.feishu.adapter import FeishuAdapter,_IMAGE_EXTENSIONS
            name=f'result-{index}'+PurePosixPath(path).suffix.lower()
            document='[[as_document]]' in delivery['content']
            from gateway.platforms.base import _AUDIO_EXTS
            if PurePosixPath(name).suffix in _AUDIO_EXTS and PurePosixPath(name).suffix not in {'.ogg','.opus'} and not document:
                data=await self.voice(delivery,offer,data)
                offer={**offer,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                name=f'result-{index}.ogg'
            kind='image' if PurePosixPath(name).suffix in _IMAGE_EXTENSIONS and not document else 'file'
            file_type='' if kind=='image' else FeishuAdapter._resolve_outbound_file_routing(file_path=name,requested_message_type='file')[0]
            items.append({**offer,'name':name,'data':data,'kind':kind,'file_type':file_type,'duration_ms':0})
        self.current(delivery)
        return {'items':items,'text':cleaned}


    async def voice(self,delivery,offer,data):
        from .gateway import digest,Conflict
        from .speech_client import opus
        adapter=self.adapter;db=adapter._haos_native.inbox.db
        binding=self.current(delivery);proof=digest([offer,binding,delivery['id']])
        db.execute('CREATE TABLE IF NOT EXISTS feishu_output_voice(id TEXT PRIMARY KEY,proof TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,sha256 TEXT NOT NULL,data BLOB NOT NULL)')
        def retained():
            previous=db.execute('SELECT * FROM feishu_output_voice WHERE id=?',(offer['id'],)).fetchone()
            if previous is None:return None
            raw=bytes(previous['data'])
            if (previous['proof']!=proof or previous['binding_digest']!=digest(binding) or not 1<=len(raw)<=MAX_BYTES
                    or hashlib.sha256(raw).hexdigest()!=previous['sha256']):raise Conflict('retained Opus output changed or was withdrawn')
            return raw
        def capacity(extra=0):
            count,size=db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM feishu_output_voice WHERE length(data)>0').fetchone()
            if db.execute('SELECT COUNT(*) FROM feishu_output_voice').fetchone()[0]>=65536:raise Conflict('private voice metadata limit reached')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='line_output_media'").fetchone():
                other=db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM line_output_media WHERE length(data)>0').fetchone();count+=other[0];size+=other[1]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_cache'").fetchone():
                size+=db.execute("SELECT COALESCE(SUM(length(data)),0) FROM native_media_cache WHERE state='cached'").fetchone()[0]
            if count>=128 or size>=64*1024*1024 or size+extra>64*1024*1024:raise Conflict('private Opus output cache full; owner inspection required')
        previous=retained()
        if previous is not None:return previous
        capacity()
        encoded=await opus(data,lambda:self.current(delivery));self.current(delivery)
        raw=encoded['data']
        if encoded['source_sha256']!=offer['sha256']:raise Conflict('encoded output source changed')
        if any(secret.encode() in raw for secret in adapter._haos_native.inbox.redactor.secrets):
            raise PermissionError('private credentials cannot become output audio')
        # Encoding yields to other deliveries. Recheck under the durable write lock;
        # a concurrent preparation must reuse its first committed Ogg serial bytes.
        db.execute('BEGIN IMMEDIATE')
        try:
            previous=retained()
            if previous is None:
                capacity(len(raw))
                db.execute('INSERT INTO feishu_output_voice VALUES(?,?,?,?,?,?)',
                    (offer['id'],proof,binding['id'],digest(binding),encoded['sha256'],raw))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        return raw if previous is None else previous
