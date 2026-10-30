"""Independent, durable export of explicitly marked mission output artifacts."""
import asyncio
import base64
import hashlib
from pathlib import PurePosixPath
import re
import time
import threading

from .gateway import Conflict,digest
from .gateway_media import MAX_BYTES,CHUNK_BYTES

_HASH=re.compile(r'[0-9a-f]{64}\Z')
# Reviewed pinned media extensions; non-native types use attachment downloads.
EXTENSIONS=frozenset(['.3gp', '.7z', '.apk', '.avi', '.bin', '.bmp', '.bz2', '.csv', '.doc', '.docx', '.epub', '.flac', '.geojson', '.gif', '.gpx', '.gz', '.htm', '.html', '.ipa', '.jpeg', '.jpg', '.json', '.key', '.kml', '.kmz', '.m2a', '.m4a', '.md', '.mkv', '.mov', '.mp3', '.mp4', '.odp', '.ods', '.odt', '.ogg', '.opus', '.pdf', '.png', '.ppt', '.pptx', '.rar', '.rtf', '.svg', '.tar', '.tgz', '.tiff', '.tsv', '.txt', '.wav', '.webm', '.webp', '.xls', '.xlsx', '.xml', '.xz', '.yaml', '.yml', '.zip'])


def marked(content):
    """Reviewed output grammar: standalone MEDIA lines outside fences/quotes.

    Never export bare paths, URLs, JSON tool logs or code examples. The native
    adapter's extractor must independently recognize the same selected paths.
    """
    if not isinstance(content,str) or len(content)>65536:raise ValueError('bounded output text required')
    paths=[];lines=[];fence=None
    for line in content.splitlines():
        text=line.strip()
        if text.startswith(('```','~~~')):
            marker=text[:3]
            fence=None if fence==marker else marker if fence is None else fence
            lines.append(line);continue
        if fence is None and text.startswith('MEDIA:'):
            path=text[6:].strip()
            if path[:1] in {'"',"'"} and path[-1:]==path[:1]:path=path[1:-1]
            if (not 1<=len(path)<=512 or any(ord(c)<32 for c in path) or '\\' in path
                    or '://' in path or not path.startswith(('/','~/','./'))
                    or PurePosixPath(path).suffix.lower() not in EXTENSIONS):
                raise ValueError('explicit bounded local output MEDIA path required')
            if path not in paths:paths.append(path)
        elif fence is None and text in {'[[audio_as_voice]]','[[as_document]]'}:continue
        else:lines.append(line)
    if len(paths)>4:raise ValueError('at most four output attachments per delivery')
    return paths,'\n'.join(lines).strip()


def approved(policy,row):
    binding=policy.current_binding(dict(row))
    if (policy.connectors.get(binding['connector'],{}).get('platform') not in {'line','sms','email','feishu','dingtalk'}
            or binding.get('allow_outbound_media') is not True or 'read' not in binding['capabilities']
            or not binding.get('generation') or type(binding.get('since')) is not int):
        raise PermissionError('separate current output-file/read approval required')
    return binding


class Exports:
    def __init__(self,controller):
        self.controller=controller;self.store=controller.store;self.db=self.store.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS gateway_output_files(
            id TEXT PRIMARY KEY,delivery_id TEXT NOT NULL REFERENCES gateway_outbox(id),
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,path_digest TEXT NOT NULL,
            source_session TEXT NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL,
            data BLOB NOT NULL,created_at REAL NOT NULL)''')
        self.lock=asyncio.Lock()

    def current(self,delivery_id,attempt):
        if (not isinstance(delivery_id,str) or not _HASH.fullmatch(delivery_id)
                or type(attempt) is not int or not 1<=attempt<=5):raise ValueError('exact in-flight output attempt required')
        row=self.db.execute('''SELECT o.*,r.binding_id,r.binding_digest,r.mission_id
            FROM gateway_outbox o JOIN gateway_routes r ON r.id=o.route_id WHERE o.id=?''',(delivery_id,)).fetchone()
        if row is None or row['state']!='sending' or row['attempt']!=attempt or row['lease_until']<=time.time():
            raise Conflict('output attempt is not currently in flight')
        approved(self.controller.gateway_policy(),row)
        mission=self.store.get(row['mission_id'])
        if mission['state']!='completed' or not mission['stored_session_id'] or mission['cancel_requested']:
            raise PermissionError('completed uncancelled source session required')
        return row,mission

    async def begin(self,params):
        if not isinstance(params,dict) or set(params)!={'delivery','attempt','path'}:raise ValueError('exact output export declaration required')
        path=params['path']
        async with self.lock:
            row,mission=self.current(params['delivery'],params['attempt'])
            if path not in marked(row['content'])[0] or path not in marked(mission['result'])[0]:
                raise PermissionError('artifact is not explicitly marked in this immutable mission output')
            identity=digest([row['id'],row['binding_digest'],mission['stored_session_id'],path])
            prior=self.db.execute('SELECT * FROM gateway_output_files WHERE id=?',(identity,)).fetchone()
            if prior is not None:
                if (prior['delivery_id']!=row['id'] or prior['binding_id']!=row['binding_id']
                        or prior['binding_digest']!=row['binding_digest'] or prior['source_session']!=mission['stored_session_id']
                        or prior['path_digest']!=digest(path) or not 1<=prior['size']<=MAX_BYTES
                        or len(prior['data'])!=prior['size'] or hashlib.sha256(prior['data']).hexdigest()!=prior['sha256']):
                    raise Conflict('stored output artifact damaged')
                return {'id':identity,'size':prior['size'],'sha256':prior['sha256']}
            if self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM gateway_output_files WHERE length(data)>0').fetchone()[0]>=128:
                raise Conflict('private output capacity reached; owner inspection required')
            from .hermes_artifact import read
            # The worker thread reads only the agent HTTP API. SQLite and grant
            # checks stay on the controller event loop, never in the worker.
            revoked=threading.Event()
            task=asyncio.create_task(asyncio.to_thread(read,self.controller.url,mission['stored_session_id'],path,
                lambda: (_ for _ in ()).throw(PermissionError('output grant withdrawn')) if revoked.is_set() else None))
            try:
                while not task.done():
                    self.current(row['id'],params['attempt'])
                    await asyncio.wait({task},timeout=.1)
                data=await task
                self.current(row['id'],params['attempt'])
            finally:
                revoked.set()
                if not task.done():
                    # to_thread cancellation cannot terminate a blocking syscall;
                    # its bounded socket read will observe revoked before returning.
                    await asyncio.shield(asyncio.gather(task,return_exceptions=True))
            if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise ValueError('bounded nonempty output bytes required')
            if any(secret.encode() in data for secret in self.store.redactor.secrets):raise PermissionError('private credential reflection refused')
            with self.store.transaction():
                used=self.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM gateway_output_files').fetchone()[0]
                if used+len(data)>64*1024*1024:raise Conflict('private output byte capacity reached')
                checksum=hashlib.sha256(data).hexdigest()
                self.db.execute('INSERT INTO gateway_output_files VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (identity,row['id'],row['binding_id'],row['binding_digest'],digest(path),mission['stored_session_id'],checksum,len(data),data,time.time()))
                self.store._event(mission['id'],'gateway.output-file',{'delivery':row['id'],'sha256':checksum,'bytes':len(data)})
            return {'id':identity,'size':len(data),'sha256':checksum}

    def chunk(self,params):
        if (not isinstance(params,dict) or set(params)!={'delivery','attempt','id','offset'}
                or not isinstance(params['id'],str) or not _HASH.fullmatch(params['id'])
                or type(params['offset']) is not int or params['offset']<0):raise ValueError('bounded output chunk required')
        row,_=self.current(params['delivery'],params['attempt'])
        item=self.db.execute('SELECT * FROM gateway_output_files WHERE id=?',(params['id'],)).fetchone()
        if item is None or item['delivery_id']!=row['id'] or item['binding_digest']!=row['binding_digest']:
            raise PermissionError('output chunk belongs to another delivery/grant')
        if params['offset']>=item['size']:raise ValueError('output chunk offset outside artifact')
        data=bytes(item['data'])[params['offset']:params['offset']+CHUNK_BYTES]
        return {'id':item['id'],'offset':params['offset'],'data':base64.b64encode(data).decode()}
