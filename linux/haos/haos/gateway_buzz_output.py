"""Root-controller artifact snapshots and durable native upload custody."""
import base64
import hashlib
import json
from pathlib import PurePosixPath
import time

from .gateway import Conflict,digest
from .gateway_buzz import HEX
from .gateway_buzz_upload import descriptor,upload
from .gateway_event_context import validate
from .gateway_media import MAX_BYTES,CHUNK_BYTES


class Output:
    def __init__(self,adapter):
        self.adapter=adapter;self.db=adapter._haos_native.inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS buzz_output_uploads(
            id TEXT PRIMARY KEY,delivery_id TEXT NOT NULL,proof TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            name TEXT NOT NULL,source_sha256 TEXT NOT NULL,state TEXT NOT NULL,descriptor TEXT NOT NULL,
            source BLOB NOT NULL,stored BLOB NOT NULL,created_at REAL NOT NULL)''')

    def current(self,delivery,*,media=True):
        adapter=self.adapter;adapter._haos_buzz_check();policy=adapter._haos_native.policy();binding=policy.current_binding(delivery)
        if (binding['connector']!=adapter._haos_native.connector or policy.connectors[binding['connector']]['platform']!='buzz'
                or 'read' not in binding['capabilities'] or media and binding.get('allow_outbound_media') is not True):
            raise PermissionError('exact current private Buzz output/read and independent media approval required')
        return binding

    def retained(self,identity,delivery,proof=None):
        binding=self.current(delivery);row=self.db.execute('SELECT * FROM buzz_output_uploads WHERE id=?',(identity,)).fetchone()
        if row is None:return None
        if (row['delivery_id']!=delivery['id'] or row['binding_digest']!=digest(binding)
                or row['credential_scope']!=digest(self.adapter._haos_buzz_value) or proof is not None and row['proof']!=proof
                or not isinstance(row['source'],bytes) or not 1<=len(row['source'])<=MAX_BYTES
                or hashlib.sha256(row['source']).hexdigest()!=row['source_sha256']):
            raise Conflict('Buzz output source changed or was purged; inspected recovery required')
        if row['state']!='ready':raise Conflict('Buzz upload has an unresolved intent; no automatic upload or publication')
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        try:item=descriptor(self.adapter._haos_buzz_value,json.loads(row['descriptor'],object_pairs_hook=_object,parse_constant=finite))
        except (ValueError,PermissionError,RecursionError):raise Conflict('damaged retained Buzz upload descriptor') from None
        data=row['stored']
        if (not isinstance(data,bytes) or len(data)!=item['size'] or hashlib.sha256(data).hexdigest()!=item['sha256']
                or json.dumps(item,sort_keys=True,separators=(',',':'))!=row['descriptor']):
            raise Conflict('damaged retained Buzz blob; automatic restoration refused')
        from .gateway_buzz_send_process import files
        part=files(self.adapter._haos_buzz_value,{'attachments':[{'descriptor':item,'name':row['name']}]})[0]
        redactor=self.adapter._haos_native.inbox.redactor
        if any(secret.encode() in row['source'] or secret.encode() in data for secret in redactor.secrets if secret):
            raise PermissionError('private Buzz credential reflection refused')
        return part

    def resolve(self,delivery,items):
        if (not isinstance(items,list) or len(items)>4 or any(not isinstance(item,str) or not HEX.fullmatch(item) for item in items)
                or len(set(items))!=len(items)):raise PermissionError('bounded distinct retained Buzz output identities required')
        result=[]
        for identity in items:
            part=self.retained(identity,delivery)
            if part is None:raise Conflict('Buzz output was removed; automatic restoration refused')
            result.append(part)
        return result

    async def prepare(self,delivery,call):
        context=validate(delivery['event_context'])
        if context['kind']!='mission.completed':return None
        self.current(delivery,media=False)
        manifest=await call('gateway.output.manifest',{'delivery':delivery['id'],'attempt':delivery['attempt']})
        if (not isinstance(manifest,dict) or set(manifest)!={'paths','text','source_sha256','group_sha256'}
                or not isinstance(manifest['paths'],list) or len(manifest['paths'])>4
                or any(not isinstance(path,str) or not 1<=len(path)<=512 for path in manifest['paths'])
                or len(set(manifest['paths']))!=len(manifest['paths']) or not isinstance(manifest['text'],str)
                or len(manifest['text'].encode())>32000 or manifest['source_sha256']!=context['content_sha256']
                or manifest['group_sha256']!=context['group_sha256']):raise Conflict('exact immutable controller Buzz output projection required')
        result={'items':[],'text':manifest['text']}
        binding=self.current(delivery,media=False)
        if not manifest['paths']:return result if manifest['text']!=delivery['content'] else None
        if binding.get('allow_outbound_media') is not True:
            result['text']+='\n[Result files require separate owner approval.]';return result
        for number,path in enumerate(manifest['paths']):
            self.current(delivery)
            from gateway.platforms.base import BasePlatformAdapter
            native_paths,_=BasePlatformAdapter.extract_media('MEDIA:'+path)
            if not path.startswith(('~/','./')) and PurePosixPath(path).suffix.lower()!='.bin' and path not in {p for p,_ in native_paths}:
                raise PermissionError('native extractor disagrees with exact controller output')
            offer=await call('gateway.output.begin',{'delivery':delivery['id'],'attempt':delivery['attempt'],'path':path})
            if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'} or type(offer['size']) is not int or not 1<=offer['size']<=MAX_BYTES
                    or any(not isinstance(offer[key],str) or not HEX.fullmatch(offer[key]) for key in ['id','sha256'])):
                raise Conflict('bounded root Buzz output snapshot required')
            identity=digest([delivery['id'],offer['id']]);proof=digest([delivery['id'],offer,binding,digest(self.adapter._haos_buzz_value)])
            if self.retained(identity,delivery,proof) is not None:result['items'].append(identity);continue
            data=bytearray()
            while len(data)<offer['size']:
                self.current(delivery)
                chunk=await call('gateway.output.chunk',{'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':len(data)})
                if (not isinstance(chunk,dict) or set(chunk)!={'id','offset','data'} or chunk['id']!=offer['id']
                        or type(chunk['offset']) is not int or chunk['offset']!=len(data) or not isinstance(chunk['data'],str)
                        or len(chunk['data'])>4*((CHUNK_BYTES+2)//3)):raise Conflict('Buzz root artifact frame changed')
                raw=base64.b64decode(chunk['data'],validate=True)
                if base64.b64encode(raw).decode()!=chunk['data'] or not 1<=len(raw)<=CHUNK_BYTES or len(data)+len(raw)>offer['size']:
                    raise Conflict('Buzz root artifact chunk bytes or size changed')
                data.extend(raw)
            data=bytes(data);self.current(delivery)
            if hashlib.sha256(data).hexdigest()!=offer['sha256']:raise Conflict('Buzz root artifact checksum changed')
            if any(secret.encode() in data for secret in self.adapter._haos_native.inbox.redactor.secrets if secret):
                raise PermissionError('private Buzz credential reflection refused')
            suffix=PurePosixPath(path).suffix.lower()
            if len(suffix)>12 or any(c not in '.abcdefghijklmnopqrstuvwxyz0123456789' for c in suffix):suffix='.bin'
            name='result-'+str(context['part']*4+number)+suffix
            count,used=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(source)+length(stored)),0) FROM buzz_output_uploads').fetchone()
            if count>=128 or used+2*len(data)>48*1024*1024:raise Conflict('Buzz output custody full; owner recovery required')
            # Commit before native upload. A restart can never mistake an
            # uncertain upload for a new artifact or authorize publication.
            self.db.execute('INSERT INTO buzz_output_uploads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,delivery['id'],proof,digest(binding),digest(self.adapter._haos_buzz_value),name,offer['sha256'],'uploading','',data,b'',time.time()))
            uploaded=await upload(self.adapter._haos_buzz_value,data,home=self.adapter._haos_buzz_home,
                current=lambda:self.current(delivery),redactor=self.adapter._haos_native.inbox.redactor)
            self.current(delivery)
            if uploaded['source_sha256']!=offer['sha256']:raise Conflict('native Buzz upload changed its root source')
            changed=self.db.execute("UPDATE buzz_output_uploads SET state='ready',descriptor=?,stored=? WHERE id=? AND proof=? AND state='uploading'",
                (json.dumps(uploaded['descriptor'],sort_keys=True,separators=(',',':')),uploaded['stored'],identity,proof)).rowcount
            if changed!=1:raise Conflict('Buzz upload custody disappeared before completion')
            self.retained(identity,delivery,proof);result['items'].append(identity)
        self.current(delivery);return result
