"""Private transient media copy and context-bound adapter admission proof."""
import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import time

from .gateway import digest,Conflict
from .gateway_media import authorize,approved,describe,descriptor,references,CHUNK_BYTES

_EVENT=ContextVar('haos_admitted_media_event',default=None)


@contextmanager
def event_scope(event,ids,types,*,platform='line'):
    if platform not in {'line','sms','email','feishu','dingtalk','a2a','buzz','google_chat','photon'}:raise PermissionError('reviewed retained media platform required')
    ids=references(ids)
    if not ids or event.media_urls!=['haos-media:'+identity for identity in ids] or event.media_types!=types:
        raise PermissionError('native media must match the private retained copy')
    token=_EVENT.set((event,ids,types,platform))
    try:yield
    finally:_EVENT.reset(token)


def event_media(event,platform):
    proof=_EVENT.get()
    if not event.media_urls:return []
    if (platform not in {'line','sms','email','feishu','dingtalk','a2a','buzz','google_chat','photon'} or proof is None or proof[0] is not event or proof[3]!=platform
            or event.media_urls!=['haos-media:'+identity for identity in proof[1]]):
        raise PermissionError('no independent retained media admission')
    return list(proof[1])


class MediaCache:
    def __init__(self,inbox):
        self.inbox=inbox;self.db=inbox.db
        self.db.execute('CREATE TABLE IF NOT EXISTS native_media_schema(version INTEGER NOT NULL)')
        self.db.execute('INSERT INTO native_media_schema SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM native_media_schema)')
        versions=self.db.execute('SELECT version FROM native_media_schema').fetchall()
        if len(versions)!=1 or versions[0][0]!=1:raise ValueError('unsupported private media relay schema')
        self.db.execute('''CREATE TABLE IF NOT EXISTS native_media_cache(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,envelope_digest TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,descriptor TEXT NOT NULL,
            data BLOB,state TEXT NOT NULL DEFAULT 'cached')''')

    def find(self,policy,connector,envelope,*,retained=False):
        binding=authorize(policy,connector,envelope)
        rows=self.db.execute('SELECT id FROM native_media_cache WHERE connector=? AND envelope_digest=? AND binding_digest=?',
            (connector,digest(envelope),digest(binding))).fetchall()
        if len(rows)>1:raise Conflict('LINE message has conflicting retained media')
        return (self.replay(policy,rows[0]['id']) if retained else self.get(policy,rows[0]['id'])) if rows else None

    def check(self,policy,identity,*,retained=False):
        row=self.db.execute('SELECT id,connector,envelope_digest,binding_id,binding_digest,descriptor,state FROM native_media_cache WHERE id=?',(identity,)).fetchone()
        if row is None or row['state'] not in ({'cached','transferred'} if retained else {'cached'}):raise Conflict('retained media bytes unavailable')
        binding=policy.current_binding(dict(row));meta=descriptor(json.loads(row['descriptor']))
        if (binding['connector']!=row['connector'] or not approved(binding,meta['kind']) or 'create' not in binding['capabilities']
                or row['id']!=digest([row['connector'],row['binding_digest'],row['envelope_digest'],meta])):
            raise PermissionError('retained media grant changed')
        if policy.connectors[row['connector']]['platform']=='line' and meta['kind']=='video' and meta['format']!='mp4':
            raise PermissionError('existing LINE video consent is restricted to MP4')
        return row

    def replay(self,policy,identity):
        row=self.check(policy,identity,retained=True)
        if row['state']=='cached':return self.get(policy,identity)
        return {'id':row['id'],'descriptor':descriptor(json.loads(row['descriptor'])),'data':None,
            'envelope_digest':row['envelope_digest'],'connector':row['connector']}

    def get(self,policy,identity):
        row=self.check(policy,identity);meta=descriptor(json.loads(row['descriptor']))
        raw=self.db.execute('SELECT data FROM native_media_cache WHERE id=?',(identity,)).fetchone()['data']
        if raw is None:raise Conflict('retained media bytes unavailable')
        data=bytes(raw)
        if describe(data,meta['kind'])!=meta:raise Conflict('retained media bytes changed')
        if any(secret.encode('utf-8') in data for secret in self.inbox.redactor.secrets):
            raise PermissionError('private credentials cannot become media input')
        return {'id':row['id'],'descriptor':meta,'data':data,'envelope_digest':row['envelope_digest'],'connector':row['connector']}

    def capacity(self):
        count,size=self.db.execute("SELECT COUNT(*),COALESCE(SUM(LENGTH(data)),0) FROM native_media_cache WHERE state='cached'").fetchone()
        if count>=128 or size>=64*1024*1024:raise Conflict('private media relay capacity reached')

    def put(self,policy,connector,envelope,data,kind):
        binding=authorize(policy,connector,envelope,kind);meta=describe(data,kind)
        if policy.connectors[connector]['platform']=='line' and kind=='video' and meta['format']!='mp4':
            raise PermissionError('existing LINE video consent is restricted to MP4')
        if any(secret.encode('utf-8') in data for secret in self.inbox.redactor.secrets):
            raise PermissionError('private credentials cannot become media input')
        identity=digest([connector,digest(binding),digest(envelope),meta])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT 1 FROM native_media_cache WHERE id=?',(identity,)).fetchone():
                item=self.get(policy,identity)
                if item['data']!=data:raise Conflict('retained media replay changed bytes')
                self.db.execute('COMMIT');return item
            self.capacity()
            size=self.db.execute("SELECT COALESCE(SUM(LENGTH(data)),0) FROM native_media_cache WHERE state='cached'").fetchone()[0]
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='line_output_media'").fetchone():
                size+=self.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM line_output_media').fetchone()[0]
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feishu_output_voice'").fetchone():
                size+=self.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM feishu_output_voice').fetchone()[0]
            if size+len(data)>64*1024*1024:raise Conflict('private media relay byte budget exceeded')
            self.db.execute('INSERT OR IGNORE INTO native_media_cache VALUES(?,?,?,?,?,?,?,?)',
                (identity,connector,digest(envelope),binding['id'],digest(binding),json.dumps(meta),data,'cached'))
            self.get(policy,identity)
            self.db.execute('COMMIT')
        except BaseException:
            # SQLITE_FULL may have already rolled back the transaction. Keep
            # the original capacity error rather than masking it with a second
            # rollback failure; the separately committed source intent survives.
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return self.get(policy,identity)

    def owner_inventory(self,policy):
        rows=self.db.execute("SELECT id,connector,binding_id,binding_digest,descriptor,LENGTH(data) AS stored_bytes FROM native_media_cache WHERE state='cached' ORDER BY id").fetchall()
        uploads=[]
        for row in rows:
            try:policy.current_binding(dict(row));revoked=False
            except PermissionError:revoked=True
            uploads.append({'id':row['id'],'connector':row['connector'],'binding_id':row['binding_id'],
                'descriptor':descriptor(json.loads(row['descriptor'])),'stored_bytes':row['stored_bytes'] or 0,
                'state':'cached','mission_id':None,'mission_state':None,'purge_allowed':revoked})
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='line_output_media'").fetchone():
            for row in self.db.execute('SELECT * FROM line_output_media WHERE length(data)>0'):
                try:binding=policy.current_binding(dict(row));revoked=False
                except PermissionError:binding=policy.bindings.get(row['binding_id'],{});revoked=True
                uploads.append({'id':row['id'],'connector':binding.get('connector','withdrawn-line'),
                    'binding_id':row['binding_id'],'descriptor':{'kind':'document','format':'bin','sha256':row['sha256'],'size':len(row['data'])},
                    'stored_bytes':len(row['data']),'state':'output-cached','mission_id':None,'mission_state':None,'purge_allowed':revoked})
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feishu_output_voice'").fetchone():
            for row in self.db.execute('SELECT * FROM feishu_output_voice WHERE length(data)>0'):
                try:binding=policy.current_binding(dict(row));revoked=False
                except PermissionError:binding=policy.bindings.get(row['binding_id'],{});revoked=True
                uploads.append({'id':row['id'],'connector':binding.get('connector','withdrawn-feishu'),
                    'binding_id':row['binding_id'],'descriptor':{'kind':'voice','format':'bin','sha256':row['sha256'],'size':len(row['data'])},
                    'stored_bytes':len(row['data']),'state':'output-cached','mission_id':None,'mission_state':None,'purge_allowed':revoked})
        size=sum(row['stored_bytes'] for row in uploads)
        return {'uploads':uploads,'stored_bytes':size,'reserved_bytes':size,'limit_bytes':64*1024*1024,'limit_records':256}

    def owner_purge(self,policy,request):
        if (not isinstance(request,dict) or set(request)!={'id','owner_uid','note_sha256','confirmed'}
                or request['confirmed'] is not True or type(request['owner_uid']) is not int or request['owner_uid']<0
                or not isinstance(request['note_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',request['note_sha256'])):
            raise PermissionError('exact inspected owner cache decision required')
        identity=references([request['id']])[0]
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM native_media_cache WHERE id=?',(identity,)).fetchone()
            output=False;voice=False
            if row is None and self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='line_output_media'").fetchone():
                row=self.db.execute('SELECT * FROM line_output_media WHERE id=?',(identity,)).fetchone();output=row is not None
            if row is None and self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feishu_output_voice'").fetchone():
                row=self.db.execute('SELECT * FROM feishu_output_voice WHERE id=?',(identity,)).fetchone();voice=row is not None;output=voice
            if row is None:raise KeyError('unknown private cache ID')
            try:policy.current_binding(dict(row))
            except PermissionError:pass
            else:raise PermissionError('withdraw or change the sender grant before purging its retained cache')
            if not output and row['state'] not in {'cached','purged'}:raise Conflict('only retained unacknowledged cache bytes can be purged')
            size=len(row['data']) if row['data'] is not None else 0
            if output and size or not output and row['state']!='purged':
                self.db.execute('CREATE TABLE IF NOT EXISTS native_media_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,purged_at REAL NOT NULL,removed_bytes INTEGER NOT NULL)')
                if voice:self.db.execute("UPDATE feishu_output_voice SET data=X'' WHERE id=?",(identity,))
                elif output:self.db.execute("UPDATE line_output_media SET data=X'',expires=0 WHERE id=?",(identity,))
                else:self.db.execute("UPDATE native_media_cache SET state='purged',data=NULL WHERE id=?",(identity,))
                self.db.execute('INSERT INTO native_media_owner_events VALUES(?,?,?,?,?)',
                    (identity,request['owner_uid'],request['note_sha256'],time.time(),size))
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return {'ids':[identity],'removed_payload_bytes':size,'tombstones_retained':True,
            'does_not_erase_controller_agent_copies_or_backups':True}

    def transferred(self,ids):
        # Only called after durable controller admission recorded in RelayInbox.
        # Keep metadata/replay identity; compact the acknowledged transient copy.
        for identity in references(ids):
            self.db.execute("UPDATE native_media_cache SET data=NULL,state='transferred' WHERE id=?",(identity,))


async def forward(policy,connector,envelope,ids,cache,call):
    ids=references(ids)
    if ids:authorize(policy(),connector,envelope)
    for identity in ids:
        item=cache.get(policy(),identity)
        if item['envelope_digest']!=digest(envelope) or item['connector']!=connector:raise PermissionError('media relay message changed')
        declaration={'connector':connector,'envelope':envelope,'descriptor':item['descriptor']}
        latest=policy()
        if latest.connectors.get(connector,{}).get('platform')=='a2a':
            binding=latest.authorize(connector,envelope)
            declaration['binding']={'binding_id':binding['id'],'binding_digest':digest(binding)}
        result=await call('gateway.media.begin',declaration)
        size=item['descriptor']['size']
        if (not isinstance(result,dict) or set(result)!={'id','offset','ready'} or result['id']!=identity
                or type(result['offset']) is not int or not 0<=result['offset']<=size or type(result['ready']) is not bool
                or result['ready']!=(result['offset']==size)):
            raise Conflict('private controller media declaration changed')
        offset=result['offset']
        while offset<size:
            cache.check(policy(),identity)
            block=item['data'][offset:offset+CHUNK_BYTES]
            result=await call('gateway.media.chunk',{'id':identity,'offset':offset,'data':base64.b64encode(block).decode()})
            offset+=len(block)
            if result!={'id':identity,'offset':offset,'ready':offset==size}:raise Conflict('private controller media receipt changed')
    params={'connector':connector,'envelope':envelope}
    if ids:params['media']=ids
    policy()  # Publication/epoch revocation before final mission admission too.
    if policy().connectors.get(connector,{}).get('platform')=='a2a':
        binding=policy().authorize(connector,envelope)
        params['binding']={'binding_id':binding['id'],'binding_digest':digest(binding)}
    return await call('gateway.receive',params)
