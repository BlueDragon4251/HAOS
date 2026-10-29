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
            kind='image' if PurePosixPath(name).suffix in _IMAGE_EXTENSIONS and not document else 'file'
            file_type='' if kind=='image' else FeishuAdapter._resolve_outbound_file_routing(file_path=name,requested_message_type='file')[0]
            items.append({**offer,'name':name,'data':data,'kind':kind,'file_type':file_type,'duration_ms':0})
        self.current(delivery)
        return {'items':items,'text':cleaned}
