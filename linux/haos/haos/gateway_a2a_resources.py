"""Private first-byte custody for approved A2A inline/HTTPS attachment Parts."""
import asyncio
import hashlib
import json
import math
import ssl
import time

from .gateway import Conflict,digest
from .gateway_a2a_admission import parse
from .gateway_a2a_media import part,classify,target,projection
from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES,approved
from .gateway_media_relay import MediaCache


class Refused(PermissionError):
    def __init__(self,reason):
        if reason not in {'authentication-refused','rate-limited','transport-unavailable','source-unavailable','storage-unavailable','private-reflection'}:
            raise ValueError('finite A2A attachment failure required')
        super().__init__('A2A attachment unavailable; inspect its source and owner permission');self.reason=reason


class Resources:
    def __init__(self,value,connector,policy,current,originals,inbox):
        self.value=value;self.connector=connector;self.policy=policy;self.current=current;self.originals=originals
        self.inbox=inbox;self.db=originals.db;self.cache=MediaCache(inbox)
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_input_resources(
            raw_id TEXT NOT NULL,part_index INTEGER NOT NULL,proof_sha256 TEXT NOT NULL,spec TEXT NOT NULL,
            state TEXT NOT NULL,attempt INTEGER NOT NULL,next_attempt REAL NOT NULL,
            data BLOB,descriptor TEXT NOT NULL,sha256 TEXT NOT NULL,media_id TEXT NOT NULL,
            updated_at REAL NOT NULL,PRIMARY KEY(raw_id,part_index))''')

    async def fetch(self,peer,url,mime):
        import httpx
        self.current();target(self.value,peer,url)
        try:
            async with asyncio.timeout(30):
                async with httpx.AsyncClient(verify=ssl.create_default_context(),trust_env=False,follow_redirects=False,
                        timeout=httpx.Timeout(5),headers={'Accept-Encoding':'identity'}) as client:
                    async with client.stream('GET',url) as response:
                        self.current();target(self.value,peer,url)
                        if response.status_code in {401,403}:raise Refused('authentication-refused')
                        if response.status_code==429:raise Refused('rate-limited')
                        if (response.status_code!=200 or response.headers.get('Content-Encoding','identity').lower()!='identity'
                                or response.headers.get('Content-Type',mime).split(';')[0].strip().lower() not in {mime,'application/octet-stream'}):
                            raise Refused('source-unavailable')
                        length=response.headers.get('Content-Length')
                        if length is not None and (not length.isascii() or not length.isdecimal() or len(length)>8 or not 1<=int(length)<=MAX_BYTES):
                            raise Refused('source-unavailable')
                        body=bytearray()
                        async for block in response.aiter_raw(48*1024):
                            self.current()
                            if len(body)+len(block)>MAX_BYTES:raise Refused('source-unavailable')
                            body.extend(block)
                        self.current()
                        if not body or length is not None and len(body)!=int(length):raise Refused('source-unavailable')
                        return bytes(body)
        except Refused:raise
        except (httpx.HTTPError,OSError,TimeoutError):raise Refused('transport-unavailable') from None

    def check(self,proof,spec,row):
        expected=digest([proof['id'],proof['source_key'],proof['binding_digest'],proof['credential_scope'],spec])
        encoded=json.dumps(spec,sort_keys=True,separators=(',',':'))
        if (row['raw_id']!=proof['id'] or row['part_index']!=spec['index'] or row['proof_sha256']!=expected or row['spec']!=encoded
                or row['state'] not in {'prepared','retained','authentication-refused','rate-limited','transport-unavailable','source-unavailable','private-reflection'}
                or type(row['attempt']) is not int or not 0<=row['attempt']<=8
                or type(row['next_attempt']) not in {int,float} or not math.isfinite(row['next_attempt']) or row['next_attempt']<0):
            raise Conflict('A2A attachment changed original source, account, grant or retained manifest')
        if row['state']=='retained':
            data=bytes(row['data']) if row['data'] is not None else b''
            try:meta=json.loads(row['descriptor'])
            except (ValueError,RecursionError):raise Conflict('damaged A2A attachment descriptor') from None
            if (not 1<=len(data)<=MAX_BYTES or hashlib.sha256(data).hexdigest()!=row['sha256'] or classify(spec['kind'],spec['mime'],data)!=meta
                    or spec['mode']=='inline' and spec['source']!=meta):raise Conflict('retained first A2A attachment bytes changed')
            if any(secret.encode() in data for secret in self.inbox.redactor.secrets):raise PermissionError('private credential in retained A2A attachment')
            return data,meta
        if row['data'] is not None or row['descriptor'] or row['sha256'] or row['media_id']:
            raise Conflict('unconfirmed A2A attachment has unexpected retained bytes or receipt')
        return None,None

    async def retained(self,proof):
        self.current();policy=self.policy();binding=policy.current_binding(proof);peer=proof['envelope']['sender']
        params=parse(proof['raw'])['params']
        _,specs=projection(self.value,peer,params,self.inbox.redactor,binding=binding)
        if specs!=proof.get('resources',[]):raise Conflict('A2A resource manifest differs from original authenticated source')
        result=[];images=0
        for spec in specs:
            self.current();binding=self.policy().current_binding(proof)
            if not approved(binding,spec['kind']):raise PermissionError('separate current A2A media kind grant required')
            raw_id=proof['id'];index=spec['index'];key=(raw_id,index)
            row=self.db.execute('SELECT * FROM a2a_input_resources WHERE raw_id=? AND part_index=?',key).fetchone()
            if row is None:
                encoded=json.dumps(spec,sort_keys=True,separators=(',',':'));fingerprint=digest([raw_id,proof['source_key'],proof['binding_digest'],proof['credential_scope'],spec])
                self.db.execute('INSERT INTO a2a_input_resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (raw_id,index,fingerprint,encoded,'prepared',0,0,None,'','','',time.time()))
                row=self.db.execute('SELECT * FROM a2a_input_resources WHERE raw_id=? AND part_index=?',key).fetchone()
            data,meta=self.check(proof,spec,row)
            if data is None:
                if row['state'] in {'authentication-refused','private-reflection'} or row['attempt']>=8:
                    raise Refused(row['state'] if row['state'] in {'authentication-refused','private-reflection'} else 'source-unavailable')
                if row['next_attempt']>time.time():raise Refused('rate-limited' if row['state']=='rate-limited' else 'transport-unavailable')
                self.cache.capacity()
                actual,data,url=part(self.value,peer,params['message']['parts'][index],index)
                if actual!=spec:raise Conflict('A2A attachment selector changed after original custody')
                try:
                    if data is None:data=await self.fetch(peer,url,spec['mime'])
                    try:meta=classify(spec['kind'],spec['mime'],data)
                    except ValueError:raise Refused('source-unavailable') from None
                    if any(secret.encode() in data for secret in self.inbox.redactor.secrets):raise Refused('private-reflection')
                except Refused as error:
                    attempt=row['attempt']+1;delay=60 if error.reason=='rate-limited' else min(60,2**min(attempt,6))
                    self.db.execute('UPDATE a2a_input_resources SET state=?,attempt=?,next_attempt=?,updated_at=? WHERE raw_id=? AND part_index=?',
                        (error.reason,attempt,time.time()+delay,time.time(),*key));raise
                self.current();self.policy().current_binding(proof)
                # The first complete response is committed BEFORE creating any
                # media-cache or relay receipt. Recovery never re-fetches a URI
                # after its first bytes were accepted into private custody.
                self.db.execute("UPDATE a2a_input_resources SET state='retained',data=?,descriptor=?,sha256=?,next_attempt=0,updated_at=? WHERE raw_id=? AND part_index=?",
                    (data,json.dumps(meta,sort_keys=True,separators=(',',':')),hashlib.sha256(data).hexdigest(),time.time(),*key))
                row=self.db.execute('SELECT * FROM a2a_input_resources WHERE raw_id=? AND part_index=?',key).fetchone();data,meta=self.check(proof,spec,row)
            self.current();policy=self.policy();policy.current_binding(proof)
            if row['media_id']:
                item=self.cache.replay(policy,row['media_id'])
                if item['descriptor']!=meta:raise Conflict('A2A attachment media receipt changed descriptor')
            else:
                item=self.cache.put(policy,self.connector,proof['envelope'],data,spec['kind'])
                self.db.execute('UPDATE a2a_input_resources SET media_id=?,updated_at=? WHERE raw_id=? AND part_index=?',(item['id'],time.time(),*key))
            if item['connector']!=self.connector or item['envelope_digest']!=digest(proof['envelope']):raise Conflict('A2A media receipt changed task/source route')
            if spec['kind']=='image':images+=meta['size']
            if images>MAX_IMAGE_BYTES:raise Refused('source-unavailable')
            if item['id'] not in {entry['id'] for entry in result}:result.append({'id':item['id'],'mime':spec['mime'],'kind':spec['kind']})
        self.current();return result
