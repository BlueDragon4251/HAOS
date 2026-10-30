"""Prepared Root-output snapshots; no host paths or Google upload authority."""
import asyncio
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import mimetypes
import os
from pathlib import PurePosixPath
import re
import time

from .gateway import Conflict,digest
from .gateway_google_chat import checked_policy,scope
from .gateway_event_context import validate
from .gateway_media import MAX_BYTES,CHUNK_BYTES

HEX=re.compile('[a-f0-9]{64}\\Z')


@contextmanager
def sealed(data):
    """The actual native MediaFileUpload opens only an immutable local memfd."""
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise ValueError('bounded Root output bytes required')
    fd=os.memfd_create('haos-approved-google-output',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    try:
        offset=0
        while offset<len(data):
            written=os.write(fd,data[offset:])
            if written<=0:raise OSError('incomplete sealed output')
            offset+=written
        fcntl.fcntl(fd,getattr(fcntl,'F_ADD_SEALS',1033),getattr(fcntl,'F_SEAL_WRITE',8)|getattr(fcntl,'F_SEAL_GROW',4)|getattr(fcntl,'F_SEAL_SHRINK',2)|getattr(fcntl,'F_SEAL_SEAL',1))
        os.lseek(fd,0,os.SEEK_SET)
        yield '/proc/self/fd/'+str(fd)
    finally:os.close(fd)


def reserve_capacity(db,size):
    if type(size) is not int or not 1<=size<=MAX_BYTES:raise ValueError('bounded Root output reservation required')
    count,live,used=db.execute("SELECT COUNT(*),COALESCE(SUM(state!='purged'),0),COALESCE(SUM(length(data)),0) FROM google_chat_output_files").fetchone()
    if count>=65536 or live>=128 or used+size>48*1024*1024:raise Conflict('Google output custody full; Owner recovery required')


class Output:
    def __init__(self,adapter):
        self.adapter=adapter;self.db=adapter._haos_native.inbox.db;self.lock=asyncio.Lock()
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_output_manifests(
            delivery_id TEXT PRIMARY KEY,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            context_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,projection TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_output_files(
            id TEXT PRIMARY KEY,delivery_id TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            credential_scope TEXT NOT NULL,offer_id TEXT NOT NULL,size INTEGER NOT NULL,offer_sha256 TEXT NOT NULL,sha256 TEXT NOT NULL,
            filename TEXT NOT NULL,mime TEXT NOT NULL,data BLOB NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL)''')

    def current(self,delivery,*,media=True):
        adapter=self.adapter;adapter._haos_google_check();policy=adapter._haos_native.policy()
        if not isinstance(delivery.get('id'),str) or not HEX.fullmatch(delivery['id']):raise PermissionError('exact Root Google delivery identity required')
        checked_policy(policy)
        binding=policy.current_binding(delivery)
        if (binding['connector']!=adapter._haos_native.connector or policy.connectors[binding['connector']]['platform']!='google_chat'
                or binding['scope']!=scope(adapter._haos_google_value) or 'read' not in binding['capabilities']
                or media and binding.get('allow_outbound_media') is not True):raise PermissionError('current exact Google read and separate output-file approval required')
        for key in ['chat','scope']:
            if key in delivery and delivery[key]!=binding[key]:raise PermissionError('Google output recipient changed')
        if 'thread' in delivery:
            from .gateway_google_chat import thread_allowed
            if not thread_allowed(binding,delivery['thread']):raise PermissionError('Google output thread changed')
        return binding

    def file(self,delivery,identity,offer_sha256=None):
        binding=self.current(delivery)
        if not isinstance(identity,str) or not HEX.fullmatch(identity):raise PermissionError('retained Google file identity required')
        row=self.db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(identity,)).fetchone()
        if row is None:raise Conflict('Google output is missing; no automatic restoration')
        if (row['delivery_id']!=delivery['id'] or row['binding_id']!=binding['id'] or row['binding_digest']!=digest(binding)
                or row['credential_scope']!=digest(self.adapter._haos_google_value)
                or offer_sha256 is not None and row['offer_sha256']!=offer_sha256 or row['state']!='retained'
                or not isinstance(row['offer_id'],str) or not HEX.fullmatch(row['offer_id']) or row['id']!=digest([delivery['id'],row['offer_id']])
                or type(row['size']) is not int or not 1<=row['size']<=MAX_BYTES or row['offer_sha256']!=digest({'id':row['offer_id'],'size':row['size'],'sha256':row['sha256']})
                or not isinstance(row['data'],bytes) or len(row['data'])!=row['size']
                or hashlib.sha256(row['data']).hexdigest()!=row['sha256']
                or not re.fullmatch('result-[0-9]{1,6}\\.[a-z0-9]{1,10}',row['filename'])
                or not isinstance(row['mime'],str) or not re.fullmatch('[a-z0-9.+-]+/[a-z0-9.+-]+',row['mime'])):
            raise Conflict('Google file source, account, grant or retained bytes changed')
        if any(secret.encode() in row['data'] for secret in self.adapter._haos_native.inbox.redactor.secrets if secret):
            raise PermissionError('private Google credential reflection refused')
        from .gateway_google_chat_output_identity import retain
        retain(self.adapter._haos_native.inbox,row,self.adapter._haos_native.connector,scope(self.adapter._haos_google_value),
            digest(['current-owner-route',row['delivery_id'],row['binding_digest'],row['credential_scope']]))
        return dict(row)

    def resolve(self,delivery,projection):
        self.current(delivery,media=False)
        if (not isinstance(projection,dict) or set(projection)!={'text','items'} or not isinstance(projection['text'],str)
                or not isinstance(projection['items'],list) or len(projection['items'])>4
                or any(not isinstance(item,str) or not HEX.fullmatch(item) for item in projection['items'])
                or len(set(projection['items']))!=len(projection['items'])):raise PermissionError('exact retained Google output projection required')
        stored=self.db.execute('SELECT * FROM google_chat_output_manifests WHERE delivery_id=?',(delivery['id'],)).fetchone()
        if stored is None:raise Conflict('Google output lacks its retained Root projection')
        binding=self.current(delivery,media=False);context=validate(delivery['event_context'])
        if (stored['binding_digest']!=digest(binding) or stored['credential_scope']!=digest(self.adapter._haos_google_value)
                or stored['context_sha256']!=digest(context) or stored['source_sha256']!=context['content_sha256']):
            raise Conflict('Google Root output context changed')
        expected=json.loads(stored['projection'])
        if expected!=projection or stored['projection']!=json.dumps(projection,sort_keys=True,separators=(',',':')):
            raise Conflict('Google output text or file identities changed after Root projection')
        return [self.file(delivery,item) for item in projection['items']]

    async def prepare(self,delivery,call):
        async with self.lock:return await self._prepare(delivery,call)

    async def _prepare(self,delivery,call):
        context=validate(delivery['event_context'])
        if not isinstance(delivery.get('content'),str) or hashlib.sha256(delivery['content'].encode()).hexdigest()!=context['content_sha256']:
            raise Conflict('Google Root output content differs from its event context')
        if context['kind']!='mission.completed':return None
        binding=self.current(delivery,media=False)
        old=self.db.execute('SELECT projection FROM google_chat_output_manifests WHERE delivery_id=?',(delivery['id'],)).fetchone()
        if old is not None:
            projection=json.loads(old['projection']);self.resolve(delivery,projection);return projection
        manifest=await call('gateway.output.manifest',{'delivery':delivery['id'],'attempt':delivery['attempt']})
        if (not isinstance(manifest,dict) or set(manifest)!={'paths','text','source_sha256','group_sha256'}
                or not isinstance(manifest['paths'],list) or len(manifest['paths'])>4
                or any(not isinstance(path,str) or not 1<=len(path)<=512 for path in manifest['paths'])
                or len(set(manifest['paths']))!=len(manifest['paths']) or not isinstance(manifest['text'],str)
                or len(manifest['text'].encode())>32000 or manifest['source_sha256']!=context['content_sha256']
                or manifest['group_sha256']!=context['group_sha256']):raise Conflict('exact immutable Root Google output projection required')
        projection={'text':manifest['text'],'items':[]};self.current(delivery,media=False)
        if manifest['paths'] and binding.get('allow_outbound_media') is not True:
            projection['text']+='\n[Result files require separate owner approval.]'
        else:
            for index,path in enumerate(manifest['paths']):
                self.current(delivery)
                from .gateway_outbound import marked
                selected,_=marked('MEDIA:'+path)
                if selected!=[path]:raise PermissionError('explicit Root media marker required')
                from gateway.platforms.base import BasePlatformAdapter
                native_paths,_=BasePlatformAdapter.extract_media('MEDIA:'+path)
                suffix=PurePosixPath(path).suffix.lower()
                if not path.startswith(('~/','./')) and suffix!='.bin' and path not in {p for p,_ in native_paths}:
                    raise PermissionError('actual native extractor differs from Root output marker')
                offer=await call('gateway.output.begin',{'delivery':delivery['id'],'attempt':delivery['attempt'],'path':path})
                if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'} or type(offer['size']) is not int or not 1<=offer['size']<=MAX_BYTES
                        or any(not isinstance(offer[k],str) or not HEX.fullmatch(offer[k]) for k in ['id','sha256'])):raise Conflict('bounded Root Google file offer required')
                identity=digest([delivery['id'],offer['id']]);proof=digest(offer)
                filename='result-'+str(context['part']*4+index)+(suffix if re.fullmatch('\\.[a-z0-9]{1,10}',suffix) else '.bin')
                mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                previous=self.db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(identity,)).fetchone()
                if previous is not None:
                    if previous['state']!='fetching':self.file(delivery,identity,proof);projection['items'].append(identity);continue
                    if (previous['delivery_id']!=delivery['id'] or previous['binding_id']!=binding['id'] or previous['binding_digest']!=digest(binding)
                            or previous['credential_scope']!=digest(self.adapter._haos_google_value) or previous['offer_sha256']!=proof
                            or previous['offer_id']!=offer['id'] or previous['size']!=offer['size'] or previous['sha256']!=offer['sha256'] or previous['filename']!=filename or previous['mime']!=mime or previous['data']!=b''):
                        raise Conflict('Google initial Root-byte identity changed; no restoration')
                else:
                    reserve_capacity(self.db,offer['size'])
                    # The first byte identity is durable before fetching chunks.
                    # An interrupted Root-only read can resume that exact offer;
                    # purged/changed data cannot be restored. No Google I/O here.
                    self.db.execute('INSERT INTO google_chat_output_files VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (identity,delivery['id'],binding['id'],digest(binding),digest(self.adapter._haos_google_value),offer['id'],offer['size'],proof,offer['sha256'],filename,mime,b'','fetching',time.time()))
                from .gateway_google_chat_output_identity import retain
                retained=self.db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(identity,)).fetchone()
                retain(self.adapter._haos_native.inbox,retained,self.adapter._haos_native.connector,scope(self.adapter._haos_google_value),
                    digest(['current-owner-route',retained['delivery_id'],retained['binding_digest'],retained['credential_scope']]))
                data=bytearray()
                while len(data)<offer['size']:
                    self.current(delivery)
                    chunk=await call('gateway.output.chunk',{'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':len(data)})
                    if (not isinstance(chunk,dict) or set(chunk)!={'id','offset','data'} or chunk['id']!=offer['id']
                            or type(chunk['offset']) is not int or chunk['offset']!=len(data) or not isinstance(chunk['data'],str)
                            or len(chunk['data'])>4*((CHUNK_BYTES+2)//3)):raise Conflict('Google Root file frame changed')
                    block=base64.b64decode(chunk['data'],validate=True)
                    if base64.b64encode(block).decode()!=chunk['data'] or not 1<=len(block)<=CHUNK_BYTES or len(data)+len(block)>offer['size']:
                        raise Conflict('Google Root file chunk bytes or size changed')
                    data.extend(block)
                data=bytes(data);self.current(delivery)
                if hashlib.sha256(data).hexdigest()!=offer['sha256']:raise Conflict('Google Root file checksum changed')
                if any(secret.encode() in data for secret in self.adapter._haos_native.inbox.redactor.secrets if secret):raise PermissionError('private Google credential reflection refused')
                used=self.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM google_chat_output_files').fetchone()[0]
                if used+len(data)>48*1024*1024:raise Conflict('Google output custody full; Owner recovery required')
                changed=self.db.execute("UPDATE google_chat_output_files SET data=?,state='retained' WHERE id=? AND state='fetching' AND data=x''",(data,identity)).rowcount
                if changed!=1:raise Conflict('Google file custody changed during Root fetch')
                self.file(delivery,identity,proof);projection['items'].append(identity)
        self.current(delivery,media=False);encoded=json.dumps(projection,sort_keys=True,separators=(',',':'))
        count,used=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(projection)),0) FROM google_chat_output_manifests').fetchone()
        if count>=65536 or used+len(encoded.encode())>8*1024*1024:raise Conflict('Google output projection history full')
        self.db.execute('INSERT INTO google_chat_output_manifests VALUES(?,?,?,?,?,?)',
            (delivery['id'],digest(binding),digest(self.adapter._haos_google_value),digest(context),context['content_sha256'],encoded))
        self.resolve(delivery,projection);return projection
