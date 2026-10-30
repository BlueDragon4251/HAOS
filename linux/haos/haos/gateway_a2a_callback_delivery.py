"""Durable signed native callbacks through an exact private HTTPS transport.

The pinned adapter builds/signs/posts via its scoped opener. Writing/uncertain
requests are not automatically replayed. A definite 429 can retry the retained
first native wire body/signature with a stable delivery identity.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import hmac
import http.client
import json
import ssl
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from .gateway import Conflict,digest
from .gateway_a2a_result import Results

_ACTIVE=ContextVar('haos_private_native_callback_attempt',default=None)

class Pending(Conflict):pass
class Superseded(Conflict):pass


def semantic(value):
    result=deepcopy(value)
    try:
        status=result['statusUpdate']['status'];status.pop('timestamp')
        if 'message' in status:status['message'].pop('messageId')
    except (KeyError,TypeError,AttributeError):raise Conflict('closed actual native callback payload required') from None
    return result


class Delivery:
    def __init__(self,adapter,tasks,configs,native_send):
        self.adapter=adapter;self.tasks=tasks;self.db=tasks.db;self.configs=configs;self.native_send=native_send
        self.transport=None;self.stopped=False
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_callback_deliveries(
            id TEXT PRIMARY KEY,task_id TEXT NOT NULL,config_id TEXT NOT NULL,source_key TEXT NOT NULL,
            binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,record_sha256 TEXT NOT NULL,
            semantic TEXT NOT NULL,sha256 TEXT NOT NULL,reply TEXT NOT NULL,state TEXT NOT NULL,
            attempt INTEGER NOT NULL,next_attempt REAL NOT NULL,wire BLOB,signature TEXT NOT NULL,
            wire_sha256 TEXT NOT NULL,phase TEXT NOT NULL,status INTEGER NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL)''')
        # A prior process may have died after a write; never infer non-delivery.
        self.db.execute("UPDATE a2a_callback_deliveries SET state='uncertain',updated_at=? WHERE state='writing'",(time.time(),))
        configs.on_change=self.queue_current

    def queue_current(self,task_id):
        from plugins.platforms.a2a import protocol
        record=self.tasks.get(task_id)
        if record['state'] in protocol.TERMINAL_STATES|{protocol.STATE_INPUT_REQUIRED}:
            self.queue(task_id,record['context_id'],record['reply'],record['state'])

    def queue(self,task_id,context_id,reply,state):
        from plugins.platforms.a2a import protocol
        with self.tasks.lock:
            self.tasks.current();task=self.tasks.entry(task_id);record=self.tasks.get(task_id)
            # Having an owner destination does not implicitly register a callback.
            if self.tasks.value.get('callbacks',{}).get(self.tasks.peer) is None:return
            binding=self.tasks.authorize(task)
            if binding.get('allow_callback') is not True:return
            config=self.configs.get(task_id)
            if config is None:return
            if record['context_id']!=context_id or record['state']!=state or record['reply']!=reply:
                raise Conflict('callback differs from committed native task record')
            identity=digest([task_id,config['configId'],task['binding_digest'],task['credential_scope']])
            if self.db.execute('SELECT 1 FROM a2a_callback_deliveries WHERE id=?',(identity,)).fetchone():return
            if self.db.execute('SELECT COUNT(*) FROM a2a_callback_deliveries').fetchone()[0]>=65536:
                raise Conflict('private callback history capacity reached; owner recovery required')
            value=semantic(protocol.status_update(task_id,context_id,state,(reply or '')[:2000]))
            encoded=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            proof=digest([identity,task_id,config['configId'],task['source_key'],task['binding_digest'],task['credential_scope'],task['record_sha256'],encoded,reply])
            self.db.execute('INSERT INTO a2a_callback_deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,task_id,config['configId'],task['source_key'],task['binding_digest'],task['credential_scope'],task['record_sha256'],encoded,proof,reply,
                    'prepared',0,0,None,'','','prepared',0,time.time(),time.time()))
            self.tasks.current()

    def current(self,identity,*,proof=True):
        self.adapter._haos_a2a_check();self.tasks.current()
        if self.stopped:raise PermissionError('private callback transport stopped')
        row=self.db.execute('SELECT * FROM a2a_callback_deliveries WHERE id=?',(identity,)).fetchone()
        if row is None:raise PermissionError('unknown exact callback delivery')
        task,owner=self.configs.target(row['task_id']);config=self.configs.get(row['task_id'],row['config_id'])
        expected=digest([row[k] for k in ['id','task_id','config_id','source_key','binding_digest','credential_scope','record_sha256','semantic','reply']])
        if config is None:raise PermissionError('native callback config was deleted or consumed')
        if row['record_sha256']!=task['record_sha256']:raise Superseded('callback task outcome has advanced')
        if (row['sha256']!=expected or any(row[k]!=task[k] for k in ['source_key','binding_digest','credential_scope'])
                or row['id']!=digest([row['task_id'],row['config_id'],row['binding_digest'],row['credential_scope']])):
            raise Conflict('callback source, task outcome, config or authority changed')
        if proof and Results(self.tasks).committed(row['task_id']) is None:
            from .gateway_a2a_controls import source_receipt
            record=self.tasks.get(row['task_id'])
            from plugins.platforms.a2a import protocol
            if (record['state']!=protocol.STATE_CANCELED or record['reply']!='Cancelled by root before mission admission.'
                    or source_receipt(self.tasks,task)!={'cancel_requested':True,'source_prevented':True}):
                raise Pending('callback native outcome awaits root acceptance proof')
        return row,task,owner

    def pop_url(self,task_id):
        active=_ACTIVE.get()
        if active is None or active[0] is not self:return ''
        with self.tasks.lock:
            row,_,owner=self.current(active[1])
            if row['task_id']!=task_id or row['state']!='writing':raise PermissionError('exact in-flight native callback required')
            return owner['url']

    @contextmanager
    def open(self,request,*,timeout):
        active=_ACTIVE.get()
        if active is None or active[0] is not self:raise PermissionError('native callback opener has no private delivery context')
        identity=active[1]
        with self.tasks.lock:
            row,task,owner=self.current(identity)
            if (request.full_url!=owner['url'] or request.get_method()!='POST' or not isinstance(request.data,bytes)
                    or not 1<=len(request.data)<=32768 or request.get_header('Content-type')!='application/json'
                    or request.get_header('Authorization') is not None or timeout!=10):
                raise PermissionError('exact bounded native callback request required')
            try:payload=json.loads(request.data)
            except (ValueError,RecursionError):raise Conflict('actual native callback JSON required') from None
            if json.dumps(semantic(payload),sort_keys=True,separators=(',',':'),ensure_ascii=False)!=row['semantic']:
                raise Conflict('native callback payload differs from retained task outcome')
            signature=self.adapter._security_context.sign_push_payload(payload)
            if not signature or not hmac.compare_digest(request.get_header('X-a2a-signature',''),signature):
                raise PermissionError('actual separate-key native callback signature required')
            if any(secret.encode() in request.data for secret in self.tasks.redactor.secrets):
                raise PermissionError('private credential in callback body')
            if row['wire'] is None:
                self.db.execute('UPDATE a2a_callback_deliveries SET wire=?,signature=?,wire_sha256=?,updated_at=? WHERE id=?',
                    (request.data,signature,hashlib.sha256(request.data).hexdigest(),time.time(),identity))
            row,_,owner=self.current(identity);body=bytes(row['wire'])
            if (len(body)>32768 or hashlib.sha256(body).hexdigest()!=row['wire_sha256']
                    or not hmac.compare_digest(self.adapter._security_context.sign_push_payload(json.loads(body)),row['signature'])):
                raise Conflict('retained native callback wire body/signature changed')
        url=urlsplit(owner['url']);connection=http.client.HTTPSConnection(url.hostname,url.port or 443,timeout=5,context=ssl.create_default_context())
        self.transport=connection;phase='connecting'
        try:
            connection.connect()
            with self.tasks.lock:
                self.current(identity);phase='sending'
                self.db.execute("UPDATE a2a_callback_deliveries SET phase='sending',updated_at=? WHERE id=?",(time.time(),identity))
            connection.request('POST',url.path,body,{'Content-Type':'application/json','X-A2A-Signature':row['signature'],
                'X-A2A-Delivery-ID':identity,'Content-Length':str(len(body))})
            response=connection.getresponse();status=response.status
            # No redirects, cookies, bearer token, ambient proxy or response body
            # are consumed. Acknowledgment is HTTP status, never recipient read.
            with self.tasks.lock:
                self.current(identity)
                if 200<=status<300:state='acknowledged';delay=0
                elif status==429 and row['attempt']<8:
                    from .gateway_retry import retry_after
                    state='retryable';delay=retry_after(response.getheader('Retry-After')) or 60
                elif status in {401,403}:state='authentication-refused';delay=0
                else:state='uncertain';delay=0
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    self.db.execute('UPDATE a2a_callback_deliveries SET state=?,phase=?,status=?,next_attempt=?,updated_at=? WHERE id=?',
                        (state,'response',status,time.time()+delay,time.time(),identity))
                    if state!='retryable':self.configs.consume(row['task_id'],row['config_id'])
                    self.tasks.current();self.db.execute('COMMIT')
                except BaseException:
                    if self.db.in_transaction:self.db.execute('ROLLBACK')
                    raise
            yield SimpleNamespace(status=status)
        except BaseException:
            with self.tasks.lock:
                row=self.db.execute('SELECT attempt,state FROM a2a_callback_deliveries WHERE id=?',(identity,)).fetchone()
                if row is not None and row['state']=='writing':
                    retry=phase=='connecting' and row['attempt']<8 and not self.stopped
                    self.db.execute('UPDATE a2a_callback_deliveries SET state=?,next_attempt=?,updated_at=? WHERE id=?',
                        ('retryable' if retry else 'uncertain',time.time()+min(60,2**min(row['attempt'],6)),time.time(),identity))
            raise
        finally:connection.close();self.transport=None

    async def run(self):
        while not self.stopped:
            self.tasks.current()
            rows=self.db.execute("SELECT id FROM a2a_callback_deliveries WHERE state IN ('prepared','retryable') AND next_attempt<=? ORDER BY created_at LIMIT 16",(time.time(),)).fetchall()
            for candidate in rows:
                try:
                    with self.tasks.lock:
                        row,task,_=self.current(candidate['id']);record=self.tasks.get(row['task_id'])
                        self.db.execute("UPDATE a2a_callback_deliveries SET state='writing',phase='preparing',attempt=attempt+1,updated_at=? WHERE id=?",(time.time(),row['id']))
                    token=_ACTIVE.set((self,row['id']))
                    operation=asyncio.create_task(asyncio.to_thread(self.native_send,self.adapter,row['task_id'],record['context_id'],row['reply'],record['state']))
                    try:await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        self.stop();await asyncio.shield(asyncio.gather(operation,return_exceptions=True));raise
                    finally:_ACTIVE.reset(token)
                    with self.tasks.lock:
                        # If native preflight failed before the scoped opener,
                        # no POST occurred; retain an inspectable refusal.
                        self.db.execute("UPDATE a2a_callback_deliveries SET state='transport-refused',updated_at=? WHERE id=? AND state='writing'",(time.time(),row['id']))
                except asyncio.CancelledError:raise
                except Pending:
                    # An outcome may await its controller receipt; keep prepared
                    # custody without publishing an unproven callback.
                    pass
                except (PermissionError,Conflict) as error:
                    state='revoked' if isinstance(error,PermissionError) else 'superseded' if isinstance(error,Superseded) else 'damaged'
                    with self.tasks.lock:
                        self.db.execute("UPDATE a2a_callback_deliveries SET state=?,updated_at=? WHERE id=? AND state IN ('prepared','retryable','writing')",
                            (state,time.time(),candidate['id']))
            await asyncio.sleep(.2)

    def stop(self):
        self.stopped=True
        if self.transport is not None:self.transport.close()

    def health(self):
        with self.tasks.lock:
            counts=dict(self.db.execute('SELECT state,COUNT(*) FROM a2a_callback_deliveries GROUP BY state').fetchall())
            return {'pending':counts.get('prepared',0)+counts.get('retryable',0),'uncertain':counts.get('writing',0)+counts.get('uncertain',0),
                'authentication_refused':counts.get('authentication-refused',0),'damaged':counts.get('damaged',0)+counts.get('transport-refused',0)}
