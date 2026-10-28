"""Private byte-only LINE output cache and expiring grant-bound HTTPS capabilities."""
import asyncio
import base64
import hashlib
from pathlib import PurePosixPath
import secrets
import re
import time

from .gateway import digest
from .gateway_media import MAX_BYTES,CHUNK_BYTES,describe
from .gateway_outbound import approved,marked


def mp4_duration(data):
    """Read bounded ISO movie-header duration without a native decoder or paths."""
    def boxes(start,end,depth=0):
        if depth>3:raise ValueError('bounded MP4 structure required')
        offset=start;count=0
        while offset+8<=end:
            count+=1
            if count>4096:raise ValueError('MP4 box count exceeds bound')
            size=int.from_bytes(data[offset:offset+4],'big');kind=data[offset+4:offset+8];header=8
            if size==1:
                if offset+16>end:raise ValueError('truncated MP4 box')
                size=int.from_bytes(data[offset+8:offset+16],'big');header=16
            if size==0:size=end-offset
            if size<header or offset+size>end:raise ValueError('invalid MP4 box size')
            if kind==b'mvhd':
                pos=offset+header
                if pos+4>end or data[pos] not in {0,1}:raise ValueError('unsupported MP4 movie header')
                width=8 if data[pos] else 4;scale=pos+4+2*width
                if scale+4+width>offset+size:raise ValueError('truncated MP4 duration')
                rate=int.from_bytes(data[scale:scale+4],'big');ticks=int.from_bytes(data[scale+4:scale+4+width],'big')
                if not rate or not 1<=ticks*1000//rate<=120000:raise ValueError('MP4 duration must be within two minutes')
                return ticks*1000//rate
            if kind==b'moov':
                value=boxes(offset+header,offset+size,depth+1)
                if value is not None:return value
            offset+=size
        return None
    duration=boxes(0,len(data))
    if duration is None:raise ValueError('MP4 movie duration required')
    return duration


class Output:
    def __init__(self,adapter):
        self.adapter=adapter;self.db=adapter._haos_native.inbox.db;self.readers=asyncio.Semaphore(4)
        self.db.execute('''CREATE TABLE IF NOT EXISTS line_output_media(
            id TEXT PRIMARY KEY,delivery_id TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            sha256 TEXT NOT NULL,mime TEXT NOT NULL,kind TEXT NOT NULL,duration INTEGER NOT NULL,
            data BLOB NOT NULL,token TEXT NOT NULL UNIQUE,expires REAL NOT NULL)''')

    def current(self,row):
        if getattr(self.adapter,'_haos_line_closed',False):raise PermissionError('LINE profile closed')
        if hasattr(self.adapter,'_haos_line_profile') and not self.adapter.is_connected:raise PermissionError('connected LINE identity required')
        binding=approved(self.adapter._haos_native.policy(),row)
        if binding['connector']!=self.adapter._haos_native.connector:raise PermissionError('output connector changed')
        return binding

    def put(self,binding,delivery_id,identity,data,kind,mime,duration=0,*,attempt=1):
        if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise ValueError('bounded output bytes required')
        checksum=hashlib.sha256(data).hexdigest();row={'binding_id':binding['id'],'binding_digest':digest(binding)};self.current(row)
        scope=digest([identity,delivery_id,attempt,digest(binding),checksum,kind,mime,duration])
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_owner_events'").fetchone():
            if self.db.execute('SELECT 1 FROM native_media_owner_events WHERE id=?',(scope,)).fetchone():
                raise PermissionError('owner-purged output cannot be republished')
        old=self.db.execute('SELECT * FROM line_output_media WHERE id=?',(scope,)).fetchone()
        if old is None:
            self.db.execute('DELETE FROM line_output_media WHERE expires<=?',(time.time(),))
            count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM line_output_media').fetchone()
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_cache'").fetchone():
                size+=self.db.execute("SELECT COALESCE(SUM(length(data)),0) FROM native_media_cache WHERE state='cached'").fetchone()[0]
            if count>=128 or size+len(data)>64*1024*1024:raise PermissionError('private LINE output cache capacity reached')
            self.db.execute('INSERT INTO line_output_media VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (scope,delivery_id,binding['id'],digest(binding),checksum,mime,kind,duration,data,secrets.token_urlsafe(32),time.time()+3600))
            old=self.db.execute('SELECT * FROM line_output_media WHERE id=?',(scope,)).fetchone()
        self.current(old)
        if old['expires']<=time.time():raise PermissionError('output link expired; explicit new delivery required')
        return dict(old)

    def url(self,item):
        # Profile configuration already verifies TLS hostname/publication. Keep
        # URLs under its exact HTTPS origin; no user-supplied artifact URL.
        base=self.adapter._haos_line_public_url.removesuffix('/line/webhook')
        if not base.startswith('https://'):raise PermissionError('public HTTPS LINE origin required')
        return base+'/line/output/'+item['token']

    def checked_url(self,binding,delivery_id,url,kind):
        if not isinstance(url,str) or len(url)>2048:raise PermissionError('private output URL required')
        row=self.db.execute('SELECT * FROM line_output_media WHERE token=?',(url.rsplit('/',1)[-1],)).fetchone()
        if (row is None or row['delivery_id']!=delivery_id or row['binding_digest']!=digest(binding)
                or row['kind']!=kind or self.url(row)!=url or row['expires']<=time.time()
                or hashlib.sha256(row['data']).hexdigest()!=row['sha256']):
            raise PermissionError('output URL does not belong to this current delivery')
        self.current(row)
        return row

    async def receive(self,request):
        from aiohttp import web
        if self.readers.locked():return web.Response(status=429,headers={'Retry-After':'5'})
        async with self.readers:
            async with asyncio.timeout(30):return await self._receive(request)

    async def _receive(self,request):
        from aiohttp import web
        token=request.match_info['token']
        if len(token)!=43 or not all(c.isalnum() or c in '_-' for c in token):return web.Response(status=404)
        row=self.db.execute('SELECT * FROM line_output_media WHERE token=?',(token,)).fetchone()
        if row is None or row['expires']<=time.time():return web.Response(status=404)
        try:self.current(row)
        except PermissionError:return web.Response(status=404)
        data=bytes(row['data'])
        if hashlib.sha256(data).hexdigest()!=row['sha256']:return web.Response(status=503)
        start,end=0,len(data)-1;status=200;headers={'Accept-Ranges':'bytes'}
        ranges=request.headers.getall('Range',[])
        if ranges:
            match=re.fullmatch(r'bytes=([0-9]{0,10})-([0-9]{0,10})',ranges[0]) if len(ranges)==1 else None
            if not match or not any(match.groups()):return web.Response(status=416,headers={'Content-Range':'bytes */'+str(len(data))})
            first,last=match.groups()
            if first:start=int(first);end=min(int(last),end) if last else end
            else:start=max(0,len(data)-int(last))
            if start>end or start>=len(data):return web.Response(status=416,headers={'Content-Range':'bytes */'+str(len(data))})
            status=206;headers['Content-Range']=f'bytes {start}-{end}/{len(data)}'
        response=web.StreamResponse(status=status,headers={**headers,'Content-Type':row['mime'],'Content-Length':str(end-start+1),
            'Cache-Control':'no-store, private','X-Content-Type-Options':'nosniff',
            'Content-Disposition':'attachment; filename="haos-output.'+('png' if row['kind']=='preview' else 'bin')+'"'})
        await response.prepare(request)
        try:
            for offset in range(start,end+1,CHUNK_BYTES):
                if row['expires']<=time.time():raise PermissionError('output link expired')
                self.current(row);await response.write(data[offset:min(offset+CHUNK_BYTES,end+1)])
            await response.write_eof()
        except (PermissionError,ConnectionError):
            if request.transport is not None:request.transport.close()
        return response

    async def prepare(self,delivery,call):
        paths,cleaned=marked(delivery['content'])
        if not paths:return None
        from gateway.platforms.base import BasePlatformAdapter
        native_paths,_=BasePlatformAdapter.extract_media(delivery['content'])
        # Tilde expansion must occur in the agent namespace, never as gateway HOME.
        native_set={p for p,_ in native_paths}
        for path in paths:
            if not path.startswith(('~/','./')) and PurePosixPath(path).suffix.lower()!='.bin' and path not in native_set:raise PermissionError('native media extractor disagrees')
        binding=self.adapter._haos_native.policy().current_binding(delivery)
        if binding.get('allow_outbound_media') is not True:
            return {'items':[],'text':cleaned+'\n[Result files require separate owner approval.]'}
        self.current(delivery)
        if not self.adapter._haos_line_public_url:raise PermissionError('public HTTPS origin required for media delivery')
        items=[]
        for path in paths:
            self.current(delivery)
            offer=await call('gateway.output.begin',{'delivery':delivery['id'],'attempt':delivery['attempt'],'path':path})
            if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'} or type(offer['size']) is not int
                    or not 1<=offer['size']<=MAX_BYTES):raise ValueError('bounded private artifact offer required')
            data=bytearray()
            while len(data)<offer['size']:
                self.current(delivery)
                chunk=await call('gateway.output.chunk',{'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':len(data)})
                if chunk.get('id')!=offer['id'] or chunk.get('offset')!=len(data):raise ValueError('artifact chunk identity changed')
                part=base64.b64decode(chunk['data'],validate=True)
                if not 1<=len(part)<=CHUNK_BYTES or len(data)+len(part)>offer['size']:raise ValueError('artifact chunk size changed')
                data.extend(part)
            data=bytes(data)
            if hashlib.sha256(data).hexdigest()!=offer['sha256']:raise ValueError('artifact checksum changed')
            suffix=PurePosixPath(path).suffix.lower();duration=0
            if suffix in {'.jpg','.jpeg','.png'} and '[[as_document]]' not in delivery['content']:
                fmt=describe(data,'image')['format']
                if len(data)>1024*1024:raise ValueError('LINE image preview requires at most 1 MiB')
                kind='image';mime='image/'+fmt
            elif suffix=='.mp4':
                describe(data,'video');mp4_duration(data);kind='video';mime='video/mp4'
            elif suffix=='.m4a':
                describe(data,'video');duration=mp4_duration(data);kind='audio';mime='audio/mp4'
            else:kind='document';mime='application/octet-stream'
            item=self.put(binding,delivery['id'],offer['id'],data,kind,mime,duration,attempt=delivery['attempt'])
            prepared={'kind':kind,'url':self.url(item),'duration':duration}
            if kind=='video':
                from plugins.platforms.line.adapter import _FALLBACK_PNG_PREVIEW
                preview=self.put(binding,delivery['id'],offer['id']+'-preview',_FALLBACK_PNG_PREVIEW,'preview','image/png',attempt=delivery['attempt'])
                prepared['preview']=self.url(preview)
            items.append(prepared)
        return {'items':items,'text':cleaned}
