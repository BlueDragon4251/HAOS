"""Private, bounded byte uploads bound to an exact gateway grant and message.

No upload accepts a host path or grants the agent access to gateway credentials.
The controller's existing private FULL/WAL mission ledger owns the durable copy.
"""
import base64
import hashlib
import json
import re
import time

from .gateway import Conflict,digest

MAX_BYTES=8*1024*1024
MAX_IMAGE_BYTES=2*1024*1024  # Aggregate base64 images must fit the 4 MiB model broker.
CHUNK_BYTES=48*1024
MAX_FILES=4
MAX_TOTAL=256*1024*1024
_HASH=re.compile(r'[0-9a-f]{64}\Z')


def descriptor(value):
    if (not isinstance(value,dict) or set(value)!={'kind','format','sha256','size'}
            or not isinstance(value['kind'],str) or not isinstance(value['format'],str)
            or value['kind'] not in {'image','document','voice','video'}
            or value['format'] not in ({'png','jpeg'} if value['kind']=='image' else {'mp4','3gp','3g2'} if value['kind']=='video' else {'bin'})
            or type(value['size']) is not int or not 1<=value['size']<=MAX_BYTES
            or value['kind']=='image' and value['size']>MAX_IMAGE_BYTES
            or not isinstance(value['sha256'],str) or not _HASH.fullmatch(value['sha256'])):
        raise ValueError('bounded path-free image/document/voice descriptor required')
    return dict(value)


def describe(data,kind):
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise ValueError('bounded nonempty media bytes required')
    fmt='bin'
    if kind=='image':
        if data.startswith(b'\x89PNG\r\n\x1a\n'):fmt='png'
        elif data.startswith(b'\xff\xd8\xff'):fmt='jpeg'
        else:raise ValueError('only PNG/JPEG image bytes are supported')
    if kind=='video':
        if len(data)<16 or data[4:8]!=b'ftyp' or int.from_bytes(data[:4],'big') not in range(16,min(len(data),4096)+1):
            raise ValueError('bounded ISO MP4 video bytes required')
        brand=data[8:12].lower()
        fmt='3gp' if brand.startswith(b'3gp') else '3g2' if brand.startswith(b'3g2') else 'mp4'
    return descriptor({'kind':kind,'format':fmt,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})


def references(values):
    if (not isinstance(values,list) or len(values)>MAX_FILES
            or any(not isinstance(value,str) or not _HASH.fullmatch(value) for value in values)
            or len(set(values))!=len(values)):
        raise ValueError('at most four distinct private media IDs required')
    return list(values)


def approved(binding,kind=None):
    if kind not in {None,'image','document','voice','video'}:raise ValueError('reviewed attachment kind required')
    if kind=='video':return binding.get('allow_video') is True
    if kind=='voice':return binding.get('allow_voice') is True
    if kind in {'image','document'}:return binding.get('allow_media') is True
    return binding.get('allow_media') is True or binding.get('allow_voice') is True or binding.get('allow_video') is True


def authorize(policy,connector,envelope,kind=None):
    if not isinstance(connector,str):raise ValueError('exact configured media connector required')
    binding=policy.authorize(connector,envelope)
    if (policy.connectors[connector]['platform'] not in {'line','sms','email','feishu','dingtalk','a2a','buzz','google_chat','photon'} or not approved(binding,kind)
            or 'create' not in binding['capabilities'] or not binding.get('generation') or type(binding.get('since')) is not int):
        raise PermissionError('explicit current timed media/create grant required')
    if not isinstance(envelope['text'],str) or not 1<=len(envelope['text'].strip())<=32000 or envelope['text'].lstrip().startswith('/'):
        raise ValueError('media can create a mission, not perform a control command')
    return binding


class GatewayMedia:
    def __init__(self,store):
        self.store=store;self.db=store.db
        self.db.executescript('''CREATE TABLE IF NOT EXISTS gateway_media_schema(version INTEGER NOT NULL);
            INSERT INTO gateway_media_schema SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM gateway_media_schema);
            CREATE TABLE IF NOT EXISTS gateway_media_uploads(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,envelope_digest TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,descriptor TEXT NOT NULL,
            received INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'uploading',
            created_at REAL NOT NULL,mission_id TEXT REFERENCES missions(id));
            CREATE TABLE IF NOT EXISTS gateway_media_chunks(
            upload_id TEXT NOT NULL REFERENCES gateway_media_uploads(id),offset INTEGER NOT NULL,
            data BLOB NOT NULL,PRIMARY KEY(upload_id,offset));
            CREATE TABLE IF NOT EXISTS gateway_media_transcripts(
            upload_id TEXT PRIMARY KEY REFERENCES gateway_media_uploads(id),receipt TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS gateway_media_purge_audit(
            upload_id TEXT PRIMARY KEY REFERENCES gateway_media_uploads(id),
            actor TEXT NOT NULL,note TEXT NOT NULL,purged_at REAL NOT NULL,removed_bytes INTEGER NOT NULL);''')
        versions=self.db.execute('SELECT version FROM gateway_media_schema').fetchall()
        if len(versions)!=1 or versions[0][0]!=1:raise RuntimeError('unsupported private gateway media schema')

    def _current(self,policy,row):
        binding=policy.current_binding(dict(row));meta=descriptor(json.loads(row['descriptor']))
        if (policy.connectors.get(row['connector'],{}).get('platform') not in {'line','sms','email','feishu','dingtalk','a2a','buzz','google_chat','photon'}
                or binding['connector']!=row['connector']
                or not approved(binding,meta['kind']) or 'create' not in binding['capabilities']):
            raise PermissionError('media grant withdrawn')
        meta=descriptor(json.loads(row['descriptor']))
        if policy.connectors[row['connector']]['platform']=='line' and meta['kind']=='video' and meta['format']!='mp4':
            raise PermissionError('existing LINE video approval is restricted to MP4')
        if (row['id']!=digest([row['connector'],row['binding_digest'],row['envelope_digest'],meta])
                or type(row['received']) is not int or not 0<=row['received']<=meta['size']):
            raise Conflict('private media declaration damaged')
        return binding

    def begin(self,policy,params):
        if not isinstance(params,dict) or set(params)!={'connector','envelope','descriptor'}:raise ValueError('exact media upload declaration required')
        connector=params['connector'];envelope=params['envelope'];meta=descriptor(params['descriptor'])
        binding=authorize(policy,connector,envelope,meta['kind'])
        if policy.connectors[connector]['platform']=='line' and meta['kind']=='video' and meta['format']!='mp4':
            raise PermissionError('existing LINE video approval is restricted to MP4')
        identity=digest([connector,digest(binding),digest(envelope),meta])
        with self.store.transaction():
            row=self.db.execute('SELECT * FROM gateway_media_uploads WHERE id=?',(identity,)).fetchone()
            if row is None:
                rows=self.db.execute("SELECT descriptor,state FROM gateway_media_uploads WHERE state!='purged'").fetchall()
                if len(rows)>=1024 or sum(descriptor(json.loads(r['descriptor']))['size'] for r in rows)+meta['size']>MAX_TOTAL:
                    raise Conflict('private media capacity reached; owner inspection required')
                self.db.execute('''INSERT INTO gateway_media_uploads
                    (id,connector,envelope_digest,binding_id,binding_digest,descriptor,created_at) VALUES(?,?,?,?,?,?,?)''',
                    (identity,connector,digest(envelope),binding['id'],digest(binding),json.dumps(meta),time.time()))
                row=self.db.execute('SELECT * FROM gateway_media_uploads WHERE id=?',(identity,)).fetchone()
            self._current(policy,row)
            if row['state'] not in {'uploading','ready','attached'} or row['state']=='uploading' and time.time()>row['created_at']+86400:
                raise Conflict('media upload no longer reusable; owner inspection required')
            return {'id':identity,'offset':row['received'],'ready':row['state'] in {'ready','attached'}}

    def chunk(self,policy,params):
        if (not isinstance(params,dict) or set(params)!={'id','offset','data'} or not isinstance(params['id'],str)
                or not _HASH.fullmatch(params['id']) or type(params['offset']) is not int or params['offset']<0
                or not isinstance(params['data'],str) or not 1<=len(params['data'])<=CHUNK_BYTES*4//3):
            raise ValueError('bounded exact media chunk required')
        try:data=base64.b64decode(params['data'],validate=True)
        except Exception:raise ValueError('canonical base64 media chunk required') from None
        if not 1<=len(data)<=CHUNK_BYTES or base64.b64encode(data).decode()!=params['data']:raise ValueError('canonical bounded media bytes required')
        with self.store.transaction():
            row=self.db.execute('SELECT * FROM gateway_media_uploads WHERE id=?',(params['id'],)).fetchone()
            if row is None:raise PermissionError('unknown private media upload')
            self._current(policy,row);meta=descriptor(json.loads(row['descriptor']))
            if row['state'] not in {'uploading','ready','attached'}:raise Conflict('media upload refused or purged')
            prior=self.db.execute('SELECT data FROM gateway_media_chunks WHERE upload_id=? AND offset=?',(row['id'],params['offset'])).fetchone()
            if prior is not None:
                if bytes(prior['data'])!=data:raise Conflict('media chunk replay changed bytes')
            else:
                if row['state']!='uploading' or time.time()>row['created_at']+86400:raise Conflict('media upload is no longer writable')
                if params['offset']!=row['received'] or row['received']+len(data)>meta['size']:raise Conflict('media chunk offset or size mismatch')
                self.db.execute('INSERT INTO gateway_media_chunks VALUES(?,?,?)',(row['id'],params['offset'],data))
                self.db.execute('UPDATE gateway_media_uploads SET received=received+? WHERE id=?',(len(data),row['id']))
            received=self.db.execute('SELECT received FROM gateway_media_uploads WHERE id=?',(row['id'],)).fetchone()[0]
            if received==meta['size'] and row['state']=='uploading':
                payload=self._bytes(row['id'],meta)
                if any(secret.encode('utf-8') in payload for secret in self.store.redactor.secrets):
                    raise PermissionError('private credential bytes cannot become a mission attachment')
                if hashlib.sha256(payload).hexdigest()!=meta['sha256']:
                    # Roll back the final chunk; the unchanged prior bytes remain
                    # inspectable and cannot become a ready attachment.
                    raise Conflict('media checksum mismatch')
                if describe(payload,meta['kind'])!=meta:raise Conflict('media format mismatch')
                self.db.execute("UPDATE gateway_media_uploads SET state='ready' WHERE id=?",(row['id'],))
            return {'id':row['id'],'offset':received,'ready':received==meta['size']}

    def _bytes(self,identity,meta):
        blocks=self.db.execute('SELECT offset,data FROM gateway_media_chunks WHERE upload_id=? ORDER BY offset',(identity,)).fetchall()
        size=0;result=bytearray()
        for block in blocks:
            data=bytes(block['data'])
            if block['offset']!=size or not 1<=len(data)<=CHUNK_BYTES or size+len(data)>meta['size']:raise Conflict('private media chunks damaged')
            result.extend(data);size+=len(data)
        if size!=meta['size']:raise Conflict('private media bytes incomplete')
        return bytes(result)

    def attach(self,policy,connector,envelope,ids,mission):
        ids=references(ids)
        if not ids:return
        binding=authorize(policy,connector,envelope)
        if self.store.get(mission)['actor']!='gateway:'+binding['identity']:raise PermissionError('media mission identity mismatch')
        with self.store.transaction():
            images=0
            for identity in ids:
                row=self.db.execute('SELECT * FROM gateway_media_uploads WHERE id=?',(identity,)).fetchone()
                if (row is None or row['connector']!=connector or row['envelope_digest']!=digest(envelope)
                        or row['state'] not in {'ready','attached'} or row['mission_id'] not in {None,mission}):
                    raise PermissionError('ready media belongs to another message or mission')
                self._current(policy,row)
                meta=descriptor(json.loads(row['descriptor']))
                if meta['kind']=='image':images+=meta['size']
                if images>MAX_IMAGE_BYTES:raise Conflict('mission images exceed the model broker byte budget')
                if row['mission_id'] is None and time.time()>row['created_at']+86400:
                    raise Conflict('unadmitted media expired; owner inspection required')
                self.db.execute("UPDATE gateway_media_uploads SET state='attached',mission_id=? WHERE id=?",(mission,identity))

    def has_mission(self,mission):
        return self.db.execute('SELECT 1 FROM gateway_media_uploads WHERE mission_id=?',(mission,)).fetchone() is not None

    def check_mission(self,policy,mission,expected=None):
        rows=self.db.execute('SELECT * FROM gateway_media_uploads WHERE mission_id=? ORDER BY rowid',(mission,)).fetchall()
        if len(rows)>MAX_FILES or any(row['state']!='attached' for row in rows):raise Conflict('mission media unavailable or exceeds its limit')
        if expected is not None and [row['id'] for row in rows]!=expected:raise Conflict('mission media set changed before dispatch')
        for row in rows:
            binding=self._current(policy,row)
            if self.store.get(mission)['actor']!='gateway:'+binding['identity']:raise PermissionError('media mission identity changed')
        return rows

    def for_mission(self,policy,mission):
        result=[]
        for row in self.check_mission(policy,mission):
            meta=descriptor(json.loads(row['descriptor']));data=self._bytes(row['id'],meta)
            if describe(data,meta['kind'])!=meta:raise Conflict('private mission attachment damaged')
            result.append({'id':row['id'],'descriptor':meta,'data':data})
        return result


    def inventory(self):
        """Owner metadata only: no payload, filenames, goals or credential values."""
        rows=self.db.execute("""SELECT u.id,u.connector,u.binding_id,u.state,u.descriptor,u.received,
            u.created_at,u.mission_id,m.state AS mission_state,
            (SELECT COALESCE(SUM(LENGTH(data)),0) FROM gateway_media_chunks WHERE upload_id=u.id) AS stored_bytes
            FROM gateway_media_uploads u LEFT JOIN missions m ON m.id=u.mission_id
            WHERE u.state!='purged' OR u.rowid IN (SELECT rowid FROM gateway_media_uploads WHERE state='purged' ORDER BY rowid DESC LIMIT 128)
            ORDER BY u.created_at,u.id""").fetchall()
        result=[];reserved=0
        for row in rows:
            meta=descriptor(json.loads(row['descriptor']))
            if row['state']!='purged':reserved+=meta['size']
            result.append({key:row[key] for key in ['id','connector','binding_id','state','received','created_at',
                'mission_id','mission_state','stored_bytes']} | {'descriptor':meta,
                'admission_expired':row['mission_id'] is None and time.time()>row['created_at']+86400,
                'purge_allowed':row['state']!='purged' and (row['mission_id'] is None or row['mission_state'] in {'completed','failed','cancelled'})})
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gateway_output_files'").fetchone():
            for row in self.db.execute('''SELECT f.*,r.connector,r.mission_id,m.state AS mission_state,o.state AS delivery_state
                    FROM gateway_output_files f JOIN gateway_outbox o ON o.id=f.delivery_id
                    JOIN gateway_routes r ON r.id=o.route_id JOIN missions m ON m.id=r.mission_id
                    WHERE length(f.data)>0 OR f.rowid IN
                        (SELECT rowid FROM gateway_output_files WHERE length(data)=0 ORDER BY rowid DESC LIMIT 128)
                    ORDER BY f.created_at'''):
                size=len(row['data']);reserved+=size
                result.append({'id':row['id'],'connector':row['connector'],'binding_id':row['binding_id'],
                    'state':'output-ready' if size else 'purged','received':size,'created_at':row['created_at'],
                    'mission_id':row['mission_id'],'mission_state':row['mission_state'],'stored_bytes':size,
                    'descriptor':{'kind':'document','format':'bin','sha256':row['sha256'],'size':row['size']},
                    'admission_expired':False,'purge_allowed':bool(size) and row['delivery_state'] not in {'pending','sending'}})
        return {'uploads':result,'reserved_bytes':reserved,'limit_bytes':MAX_TOTAL+64*1024*1024,
            'stored_bytes':sum(row['stored_bytes'] for row in result),'limit_records':1152,'recent_purged_limit':128,'output_recent_purged_limit':128}

    def purge(self,ids,actor,note,*,confirmed=False):
        """Explicit owner-only caller; retain tombstones, grants, missions and audit."""
        if (confirmed is not True or not isinstance(actor,str) or not re.fullmatch(r'owner:[0-9]+',actor)
                or not isinstance(note,str) or not 1<=len(note.strip())<=2000):
            raise PermissionError('explicit authenticated owner inspection and bounded note required')
        ids=references(ids)
        if not ids:raise ValueError('explicit media IDs required; no wildcard purge')
        removed=0
        with self.store.transaction():
            rows=[]
            for identity in ids:
                row=self.db.execute('SELECT * FROM gateway_media_uploads WHERE id=?',(identity,)).fetchone()
                if row is None and self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gateway_output_files'").fetchone():
                    output=self.db.execute('''SELECT f.*,o.state AS delivery_state FROM gateway_output_files f
                        JOIN gateway_outbox o ON o.id=f.delivery_id WHERE f.id=?''',(identity,)).fetchone()
                    if output is not None:
                        if output['delivery_state'] in {'pending','sending'}:raise Conflict('output delivery must be resolved before purge')
                        rows.append(('output',output));continue
                if row is None:raise KeyError('unknown private media ID')
                if row['mission_id'] is not None and self.store.get(row['mission_id'])['state'] not in {'completed','failed','cancelled'}:
                    raise Conflict('media for a nonterminal mission cannot be purged')
                rows.append(row)
            for row in rows:
                if isinstance(row,tuple):
                    output=row[1];size=len(output['data'])
                    if size:
                        self.db.execute('CREATE TABLE IF NOT EXISTS gateway_output_purge_audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,note TEXT NOT NULL,purged_at REAL NOT NULL,removed_bytes INTEGER NOT NULL)')
                        self.db.execute("UPDATE gateway_output_files SET data=X'' WHERE id=?",(output['id'],))
                        self.db.execute('INSERT INTO gateway_output_purge_audit VALUES(?,?,?,?,?)',
                            (output['id'],actor,self.store.redactor.text(note.strip()),time.time(),size))
                        removed+=size
                    continue
                if row['state']=='purged':continue
                size=self.db.execute('SELECT COALESCE(SUM(LENGTH(data)),0) FROM gateway_media_chunks WHERE upload_id=?',(row['id'],)).fetchone()[0]
                self.db.execute('DELETE FROM gateway_media_chunks WHERE upload_id=?',(row['id'],))
                self.db.execute('DELETE FROM gateway_media_transcripts WHERE upload_id=?',(row['id'],))
                self.db.execute("UPDATE gateway_media_uploads SET state='purged' WHERE id=?",(row['id'],))
                self.db.execute('INSERT INTO gateway_media_purge_audit VALUES(?,?,?,?,?)',
                    (row['id'],actor,self.store.redactor.text(note.strip()),time.time(),size))
                removed+=size
        return {'ids':ids,'removed_payload_bytes':removed,'tombstones_retained':True,
            'does_not_erase_agent_copies_or_backups':True}


    def transcript(self,policy,mission,identity):
        rows=self.check_mission(policy,mission)
        row=next((row for row in rows if row['id']==identity),None)
        if row is None or descriptor(json.loads(row['descriptor']))['kind']!='voice':
            raise PermissionError('voice attachment for this mission required')
        saved=self.db.execute('SELECT receipt,receipt_sha256 FROM gateway_media_transcripts WHERE upload_id=?',(identity,)).fetchone()
        if saved is None:return None
        value=json.loads(saved['receipt'])
        if digest([identity,value])!=saved['receipt_sha256']:raise Conflict('private voice transcript receipt damaged')
        from .speech_client import result
        return result(value,json.loads(row['descriptor'])['sha256'])

    def save_transcript(self,policy,mission,identity,value):
        from .speech_client import result
        with self.store.transaction():
            self.check_mission(policy,mission)
            row=self.db.execute('SELECT descriptor,mission_id FROM gateway_media_uploads WHERE id=?',(identity,)).fetchone()
            if row is None or row['mission_id']!=mission or json.loads(row['descriptor'])['kind']!='voice':
                raise PermissionError('exact mission voice attachment required')
            value=result(value,json.loads(row['descriptor'])['sha256'])
            if any(secret in value['transcript'] for secret in self.store.redactor.secrets):
                raise PermissionError('private credential reflection cannot become a voice transcript')
            existing=self.transcript(policy,mission,identity)
            if existing is not None:
                if existing!=value:raise Conflict('retained voice transcript cannot be replaced silently')
                return existing
            self.db.execute('INSERT INTO gateway_media_transcripts VALUES(?,?,?,?)',
                (identity,json.dumps(value),digest([identity,value]),time.time()))
            self.store._event(mission,'mission.voice-transcribed',{'media_id':identity,'source_sha256':value['source_sha256'],
                'model_revision':value['model_revision'],'samples':value['samples'],'sample_rate':value['sample_rate']})
            return value
