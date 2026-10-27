"""Private transient media copy and context-bound adapter admission proof."""
import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json

from .gateway import digest,Conflict
from .gateway_media import authorize,describe,descriptor,references,CHUNK_BYTES

_EVENT=ContextVar('haos_admitted_media_event',default=None)


@contextmanager
def event_scope(event,ids,types):
    ids=references(ids)
    if not ids or event.media_urls!=['haos-media:'+identity for identity in ids] or event.media_types!=types:
        raise PermissionError('native media must match the private retained copy')
    token=_EVENT.set((event,ids))
    try:yield
    finally:_EVENT.reset(token)


def event_media(event,platform):
    proof=_EVENT.get()
    if not event.media_urls:return []
    if (platform!='line' or proof is None or proof[0] is not event
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

    def find(self,policy,connector,envelope):
        binding=authorize(policy,connector,envelope)
        rows=self.db.execute('SELECT id FROM native_media_cache WHERE connector=? AND envelope_digest=? AND binding_digest=?',
            (connector,digest(envelope),digest(binding))).fetchall()
        if len(rows)>1:raise Conflict('LINE message has conflicting retained media')
        return self.get(policy,rows[0]['id']) if rows else None

    def check(self,policy,identity):
        row=self.db.execute('SELECT id,connector,envelope_digest,binding_id,binding_digest,descriptor,state FROM native_media_cache WHERE id=?',(identity,)).fetchone()
        if row is None or row['state']!='cached':raise Conflict('retained media bytes unavailable')
        binding=policy.current_binding(dict(row));meta=descriptor(json.loads(row['descriptor']))
        if (binding['connector']!=row['connector'] or binding.get('allow_media') is not True or 'create' not in binding['capabilities']
                or row['id']!=digest([row['connector'],row['binding_digest'],row['envelope_digest'],meta])):
            raise PermissionError('retained media grant changed')
        return row

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
        binding=authorize(policy,connector,envelope);meta=describe(data,kind)
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
            if size+len(data)>64*1024*1024:raise Conflict('private media relay byte budget exceeded')
            self.db.execute('INSERT OR IGNORE INTO native_media_cache VALUES(?,?,?,?,?,?,?,?)',
                (identity,connector,digest(envelope),binding['id'],digest(binding),json.dumps(meta),data,'cached'))
            self.get(policy,identity)
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return self.get(policy,identity)

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
        result=await call('gateway.media.begin',{'connector':connector,'envelope':envelope,'descriptor':item['descriptor']})
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
    return await call('gateway.receive',params)
