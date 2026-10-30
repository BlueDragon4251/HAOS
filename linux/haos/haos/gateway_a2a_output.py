"""Read exact root-controller snapshots; never open a path from agent output."""
import base64
import hashlib
import mimetypes
from pathlib import PurePosixPath
import re

from .gateway import Conflict
from .gateway_a2a import scope
from .gateway_raw import NativeInbox
from .gateway_media import MAX_BYTES,CHUNK_BYTES
from .gateway_event_context import validate


class Output:
    def __init__(self,adapter):self.adapter=adapter

    def current(self,delivery):
        self.adapter._haos_a2a_check();policy=self.adapter._haos_native.policy();binding=policy.current_binding(delivery)
        if (binding['connector']!=self.adapter._haos_native.connector or policy.connectors[binding['connector']]['platform']!='a2a'
                or binding['chat']!=delivery['chat'] or binding['scope']!=delivery['scope'] or binding['thread']!=delivery['thread']
                or 'read' not in binding['capabilities']):raise PermissionError('exact current A2A controller output route required')
        return binding

    async def prepare(self,delivery,call):
        context=validate(delivery['event_context'])
        if context['kind']!='mission.completed':return None
        binding=self.current(delivery)
        manifest=await call('gateway.output.manifest',{'delivery':delivery['id'],'attempt':delivery['attempt']})
        if (not isinstance(manifest,dict) or set(manifest)!={'paths','text','source_sha256','group_sha256'}
                or not isinstance(manifest['paths'],list) or len(manifest['paths'])>4 or len(set(manifest['paths']))!=len(manifest['paths'])
                or any(not isinstance(path,str) or not 1<=len(path)<=512 for path in manifest['paths'])
                or not isinstance(manifest['text'],str) or len(manifest['text'].encode())>32000
                or manifest['source_sha256']!=context['content_sha256'] or manifest['group_sha256']!=context['group_sha256']):
            raise Conflict('root A2A output projection differs from the original controller chunk')
        self.current(delivery)
        if not manifest['paths'] and manifest['text']==delivery['content']:return None
        projected={'text':manifest['text'],'artifact_ids':[],'source_sha256':context['content_sha256']}
        if manifest['paths'] and binding.get('allow_outbound_media') is not True:
            projected['text']+='\n[Result files require separate owner approval.]\n';return projected
        peers=self.adapter._haos_a2a_peers
        selected=[peer for peer,native in peers.items() if scope(native.tasks.value,peer)==delivery['scope']]
        if len(selected)!=1:raise PermissionError('one exact output destination peer required')
        native=peers[selected[0]];index=native.tasks
        envelope={'platform':'a2a','scope':delivery['scope'],'chat':delivery['chat'],'thread':delivery['thread'],'message_id':delivery['reply_to']}
        row=index.by_source(NativeInbox.key(binding['connector'],envelope))
        if row is None:raise PermissionError('output has no retained native A2A input')
        for number,path in enumerate(manifest['paths']):
            self.current(delivery)
            from gateway.platforms.base import BasePlatformAdapter
            native_paths,_=BasePlatformAdapter.extract_media('MEDIA:'+path)
            if not path.startswith(('~/','./')) and PurePosixPath(path).suffix.lower()!='.bin' and path not in {p for p,_ in native_paths}:
                raise PermissionError('native media extractor disagrees with exact controller output')
            offer=await call('gateway.output.begin',{'delivery':delivery['id'],'attempt':delivery['attempt'],'path':path})
            if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'} or type(offer['size']) is not int or not 1<=offer['size']<=MAX_BYTES
                    or any(not isinstance(offer[k],str) or not re.fullmatch('[0-9a-f]{64}',offer[k]) for k in ['id','sha256'])):
                raise Conflict('bounded exact root A2A artifact offer required')
            data=bytearray()
            while len(data)<offer['size']:
                self.current(delivery)
                chunk=await call('gateway.output.chunk',{'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':len(data)})
                if (not isinstance(chunk,dict) or set(chunk)!={'id','offset','data'} or chunk['id']!=offer['id']
                        or type(chunk['offset']) is not int or chunk['offset']!=len(data) or not isinstance(chunk['data'],str)
                        or len(chunk['data'])>4*((CHUNK_BYTES+2)//3)):
                    raise Conflict('root A2A artifact chunk changed identity, offset or frame')
                block=base64.b64decode(chunk['data'],validate=True)
                if base64.b64encode(block).decode()!=chunk['data'] or not 1<=len(block)<=CHUNK_BYTES or len(data)+len(block)>offer['size']:
                    raise Conflict('root A2A artifact chunk changed bytes or size')
                data.extend(block)
            data=bytes(data);self.current(delivery)
            if hashlib.sha256(data).hexdigest()!=offer['sha256']:raise Conflict('root A2A artifact checksum changed')
            if any(secret.encode() in data for secret in self.adapter._haos_native.inbox.redactor.secrets):
                raise PermissionError('private gateway credential cannot become an A2A artifact')
            name='result-'+str(context['part']*4+number)+PurePosixPath(path).suffix.lower()
            mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
            artifact=native._haos_a2a_artifacts.put(row['task_id'],context['group_sha256'],delivery['id'],offer,data,name,mime)
            projected['artifact_ids'].append(artifact)
        self.current(delivery);return projected
