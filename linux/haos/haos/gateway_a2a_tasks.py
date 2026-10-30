"""Private persistent index around the actual frozen native A2A TaskStore.

This is task custody, not an HTTP authorization endpoint. Callers still need the
independent peer/context permission gate before any native RPC or response.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time

from .gateway import Conflict,GatewayPolicy,digest
from .gateway_a2a import opaque,scope
from .gateway_raw import NativeInbox
from .gateway_line_ingress import _object
from .gateway_dingtalk_admission import finite
from .redaction import Redactor

_SOURCE=ContextVar('haos_private_a2a_task_source',default=None)
HASH=re.compile('[0-9a-f]{64}\\Z')
TASK=re.compile('task-[0-9a-f]{16}\\Z')
LIMIT=64*1024*1024


class Tasks:
    def __init__(self,path,peer,value,current,policy,*,connector):
        if (not callable(current) or not callable(policy) or not isinstance(peer,str)
                or peer not in value['peer_tokens'] or not isinstance(policy(),GatewayPolicy)
                or policy().connectors.get(connector,{}).get('platform')!='a2a'):
            raise PermissionError('private A2A peer, current publication and independent policy required')
        current();self.peer=peer;self.value=value;self.current=current;self.policy=policy;self.connector=connector
        self.credential_scope=digest([connector,value])
        secrets=set([*value['peer_tokens'].values(),value['tls']['private_key']])
        for _ in range(2):secrets|={json.dumps(text,ensure_ascii=ascii)[1:-1] for text in tuple(secrets) for ascii in (True,False)}
        self.redactor=Redactor(sorted(secrets,key=len,reverse=True))
        # Reuse the established actual private-dir/file/owner/WAL checks. The
        # protocol HTTP threads share only this separately locked connection.
        checked=NativeInbox(Path(path),self.redactor);checked.close()
        self.db=sqlite3.connect(path,isolation_level=None,check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA busy_timeout=5000');self.db.execute('PRAGMA max_page_count='+str(LIMIT//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_tasks(
            task_id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,raw_id TEXT NOT NULL,connector TEXT NOT NULL,
            binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
            peer TEXT NOT NULL,context_id TEXT NOT NULL,record TEXT NOT NULL,record_sha256 TEXT NOT NULL,
            admitted_receipt TEXT NOT NULL,updated_at REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_task_transitions(
            task_id TEXT NOT NULL,sequence INTEGER NOT NULL,previous_sha256 TEXT NOT NULL,intent TEXT NOT NULL,
            intent_sha256 TEXT NOT NULL,state TEXT NOT NULL,final_sha256 TEXT NOT NULL,created_at REAL NOT NULL,
            updated_at REAL NOT NULL,PRIMARY KEY(task_id,sequence))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_result_intents(
            task_id TEXT PRIMARY KEY,source_key TEXT NOT NULL,body_sha256 TEXT NOT NULL,expected_sha256 TEXT NOT NULL,
            binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,state TEXT NOT NULL,record_sha256 TEXT NOT NULL,
            created_at REAL NOT NULL,updated_at REAL NOT NULL)''')
        self.lock=threading.RLock()
        from plugins.platforms.a2a.protocol import TaskStore
        self.native=TaskStore();self.base=TaskStore
        self.db.execute('CREATE INDEX IF NOT EXISTS a2a_tasks_current ON a2a_tasks(connector,peer,credential_scope,binding_digest,updated_at)')
        selection=self.selection()
        if selection is not None:
            where,params=selection
            from plugins.platforms.a2a import protocol
            terminal=sorted(protocol.TERMINAL_STATES);holders=','.join('?' for _ in terminal)
            active=self.db.execute('SELECT * FROM a2a_tasks WHERE '+where+
                " AND json_extract(record,'$.state') NOT IN ("+holders+') ORDER BY updated_at DESC LIMIT 129',(*params,*terminal)).fetchall()
            if len(active)>128:raise Conflict('private A2A active-task recovery exceeds its retained-source bound')
            recent=self.db.execute('SELECT * FROM a2a_tasks WHERE '+where+
                " AND json_extract(record,'$.state') IN ("+holders+') ORDER BY updated_at DESC LIMIT 500',(*params,*terminal)).fetchall()
            for row in reversed([*active,*recent]):
                record=self.validate(row);self.authorize(row);self.native._tasks[row['task_id']]=record
        current()

    def selection(self,*,read=False):
        self.current();policy=self.policy()
        bindings=[digest(b) for b in policy.bindings.values() if b['connector']==self.connector and b['sender']==self.peer
            and b['scope']==scope(self.value,self.peer) and (not read or 'read' in b['capabilities'])]
        if not bindings:return None
        return ('connector=? AND peer=? AND credential_scope=? AND binding_digest IN ('+','.join('?' for _ in bindings)+')',
            [self.connector,self.peer,self.credential_scope,*bindings])

    def close(self):
        with self.lock:self.db.close()

    def authorize(self,row):
        self.current();policy=self.policy();binding=policy.current_binding(dict(row))
        if (row['connector']!=self.connector or binding['connector']!=row['connector'] or binding['sender']!=self.peer or binding['chat']!=row['context_id']
                or binding['scope']!=scope(self.value,self.peer) or row['peer']!=self.peer
                or row['credential_scope']!=digest([row['connector'],self.value])):
            raise PermissionError('A2A task belongs to another peer, account, context or owner grant')
        return binding

    def validate(self,row):
        value=dict(row)
        if (set(value)!={'task_id','source_key','raw_id','connector','binding_id','binding_digest','credential_scope','peer','context_id',
                'record','record_sha256','admitted_receipt','updated_at'}
                or not isinstance(value['task_id'],str) or not TASK.fullmatch(value['task_id'])
                or any(not isinstance(value[k],str) or not HASH.fullmatch(value[k]) for k in ['source_key','raw_id','binding_digest','credential_scope','record_sha256'])
                or not isinstance(value['record'],str) or not 1<=len(value['record'].encode())<=65536
                or not isinstance(value['admitted_receipt'],str) or value['admitted_receipt'] not in {'',value['source_key']}
                or type(value['updated_at']) not in {int,float} or not math.isfinite(value['updated_at']) or value['updated_at']<=0):
            raise Conflict('damaged private A2A task metadata')
        try:record=json.loads(value['record'],object_pairs_hook=_object,parse_constant=finite)
        except (ValueError,RecursionError):raise Conflict('damaged private A2A native task record') from None
        self.record(record)
        if (digest([value['source_key'],value['raw_id'],value['binding_digest'],value['credential_scope'],value['record']])!=value['record_sha256']
                or record['task_id']!=value['task_id'] or record['peer']!=value['peer'] or record['context_id']!=value['context_id']
                or json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)!=value['record']):
            raise Conflict('private A2A native task proof changed')
        return record

    def record(self,value):
        from plugins.platforms.a2a import protocol
        fields={'task_id','context_id','peer','agent_slug','tenant','state','reply','created_at','created_iso','push_url','push_config_id'}
        if (not isinstance(value,dict) or set(value) not in (fields,fields|{'completed_at'})
                or not isinstance(value['task_id'],str) or not TASK.fullmatch(value['task_id'])
                or value['peer']!=self.peer or value['agent_slug']!='' or value['tenant']!=''
                or not isinstance(value['state'],str) or value['state'] not in protocol.TERMINAL_STATES|{protocol.STATE_SUBMITTED,protocol.STATE_WORKING,protocol.STATE_INPUT_REQUIRED}
                or not isinstance(value['reply'],str) or len(value['reply'].encode())>32000 or self.redactor.text(value['reply'])!=value['reply']
                or value['push_url']!='' or value['push_config_id']!=''
                or not isinstance(value['created_iso'],str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z',value['created_iso'])
                or any(type(value[k]) not in {int,float} or not math.isfinite(value[k]) or value[k]<=0 for k in ['created_at',*(['completed_at'] if 'completed_at' in value else [])])):
            raise Conflict('unreviewed or damaged private A2A task state')
        opaque(value['context_id'])
        return value

    @contextmanager
    def source(self,connector,proof):
        self.current()
        if (connector!=self.connector or not isinstance(proof,dict) or not {'id','source_key','binding_id','binding_digest','credential_scope','envelope'}<=set(proof)
                or any(not isinstance(proof[k],str) or not HASH.fullmatch(proof[k]) for k in ['id','source_key','binding_digest','credential_scope'])
                or not isinstance(proof['envelope'],dict) or proof['envelope'].get('sender')!=self.peer or proof['envelope'].get('platform')!='a2a'
                or proof['credential_scope']!=digest([connector,self.value])
                or NativeInbox.key(connector,proof['envelope'])!=proof['source_key']):
            raise PermissionError('exact retained authenticated A2A source proof required')
        binding=self.policy().current_binding(proof)
        if (binding['connector']!=connector or binding['scope']!=scope(self.value,self.peer)
                or binding['sender']!=self.peer or binding['chat']!=proof['envelope']['chat']
                or ('answer' if 'target_task_id' in proof else 'create') not in binding['capabilities']):
            raise PermissionError('source is not approved to create this exact A2A task')
        token=_SOURCE.set((self,connector,proof))
        try:yield
        finally:_SOURCE.reset(token)

    def create(self,task_id,context_id,peer,agent_slug='',tenant=''):
        self.current();state=_SOURCE.get()
        if (state is None or state[0] is not self or state[2]['envelope']['chat']!=context_id or peer!=self.peer or agent_slug or tenant
                or 'target_task_id' in state[2]):
            raise PermissionError('native A2A task creation requires its exact retained source context')
        _,connector,proof=state
        with self.lock:
            if self.db.execute('SELECT 1 FROM a2a_tasks WHERE source_key=?',(proof['source_key'],)).fetchone():
                raise Conflict('A2A source already has a native task; recover it instead of dispatching again')
            if self.db.execute('SELECT COUNT(*) FROM a2a_tasks').fetchone()[0]>=65536:raise Conflict('private A2A task history full')
            record=self.native.create(task_id,context_id,peer,agent_slug,tenant)
            try:
                self.record(record);encoded=json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)
                checksum=digest([proof['source_key'],proof['id'],proof['binding_digest'],proof['credential_scope'],encoded])
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('INSERT INTO a2a_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (task_id,proof['source_key'],proof['id'],connector,proof['binding_id'],proof['binding_digest'],proof['credential_scope'],
                        peer,context_id,encoded,checksum,'',time.time()))
                self.current();self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:self.db.execute('ROLLBACK')
                with self.native._lock:self.native._tasks.pop(task_id,None)
                raise
            return record

    def get(self,task_id,agent_slug='',tenant=''):
        self.current()
        if agent_slug or tenant:raise PermissionError('unreviewed A2A profile/tenant route')
        with self.lock:
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None:return None
            record=self.validate(row);self.authorize(row);return record

    def entry(self,task_id):
        with self.lock:
            self.current()
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None:return None
            self.validate(row);self.authorize(row);return dict(row)

    def by_source(self,source_key):
        self.current()
        if not isinstance(source_key,str) or not HASH.fullmatch(source_key):raise ValueError('exact A2A source key required')
        with self.lock:
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE source_key=?',(source_key,)).fetchone()
            if row is None:return None
            self.validate(row);self.authorize(row);return dict(row)

    def admitted(self,task_id,receipt):
        if not isinstance(receipt,str) or not HASH.fullmatch(receipt):raise ValueError('exact durable parent input receipt required')
        with self.lock:
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None:raise PermissionError('unknown native A2A task')
            self.validate(row);self.authorize(row)
            if row['admitted_receipt'] and row['admitted_receipt']!=receipt:raise Conflict('A2A task input receipt changed')
            if receipt!=row['source_key']:raise PermissionError('native task and parent input source must agree')
            self.db.execute('UPDATE a2a_tasks SET admitted_receipt=?,updated_at=? WHERE task_id=?',(receipt,time.time(),task_id))
            self.current()

    def transition(self,task_id,operation,state,reply=''):
        from plugins.platforms.a2a import protocol
        self.current()
        if (operation not in {'state','complete'} or state not in protocol.TERMINAL_STATES|{protocol.STATE_SUBMITTED,protocol.STATE_WORKING,protocol.STATE_INPUT_REQUIRED}
                or not isinstance(reply,str) or len(reply.encode())>32000 or self.redactor.text(reply)!=reply
                or operation=='state' and reply or operation=='complete' and state not in protocol.TERMINAL_STATES|{protocol.STATE_INPUT_REQUIRED}):
            raise ValueError('closed credential-free native A2A task transition required')
        with self.lock:
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None:raise PermissionError('unknown A2A task')
            before=self.validate(row);self.authorize(row)
            if before['state'] in protocol.TERMINAL_STATES:
                if operation=='complete' and (before['state']!=state or before['reply']!=reply):raise Conflict('terminal native A2A outcome cannot be replaced')
                return None
            if before['state']==state and (operation=='state' or before['reply']==reply):return None
            if self.native.get(task_id)!=before:raise Conflict('uncommitted native A2A state requires owner recovery')
            if self.db.execute("SELECT 1 FROM a2a_task_transitions WHERE task_id=? AND state!='committed'",(task_id,)).fetchone():
                raise Conflict('uncertain native A2A transition requires owner recovery')
            sequence=self.db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM a2a_task_transitions WHERE task_id=?',(task_id,)).fetchone()[0]
            if sequence>32:raise Conflict('native A2A task transition budget exhausted')
            intent=json.dumps({'operation':operation,'state':state,'reply':reply},sort_keys=True,separators=(',',':'),ensure_ascii=False)
            checksum=digest([task_id,sequence,row['record_sha256'],intent]);now=time.time()
            self.db.execute('INSERT INTO a2a_task_transitions VALUES(?,?,?,?,?,?,?,?,?)',
                (task_id,sequence,row['record_sha256'],intent,checksum,'writing','',now,now))
            self.current()
            result=(self.native.set_state(task_id,state) if operation=='state' else self.native.complete(task_id,state,reply))
            after=self.native.get(task_id);self.record(after)
            if after['state']!=state or operation=='complete' and after['reply']!=reply:
                raise Conflict('native A2A transition did not produce the exact approved state')
            encoded=json.dumps(after,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            final=digest([row['source_key'],row['raw_id'],row['binding_digest'],row['credential_scope'],encoded])
            try:
                self.db.execute('BEGIN IMMEDIATE');self.authorize(row)
                self.db.execute('UPDATE a2a_tasks SET record=?,record_sha256=?,updated_at=? WHERE task_id=?',(encoded,final,time.time(),task_id))
                self.db.execute("UPDATE a2a_task_transitions SET state='committed',final_sha256=?,updated_at=? WHERE task_id=? AND sequence=?",
                    (final,time.time(),task_id,sequence))
                self.current();self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:self.db.execute('ROLLBACK')
                raise
            return result

    def set_state(self,task_id,state):return self.transition(task_id,'state',state)

    def complete(self,task_id,state,reply=''):return self.transition(task_id,'complete',state,reply)

    def watch(self,task_id,agent_slug='',tenant=''):
        with self.lock:
            if self.get(task_id,agent_slug,tenant) is None:return None
            return self.native.watch(task_id,agent_slug,tenant)

    def list(self,context_id='',state='',page_size=50,offset=0,agent_slug='',tenant='',with_total=False):
        self.current()
        if (agent_slug or tenant or type(page_size) is not int or not 1<=page_size<=100
                or type(offset) is not int or not 0<=offset<=65536):raise ValueError('bounded single-agent A2A task page required')
        with self.lock:
            # The HTTP gate must separately check read permissions. Never return
            # another peer's or withdrawn/replaced grant's retained task record.
            selection=self.selection(read=True)
            if selection is None:return ([],0,0) if with_total else ([],0)
            where,params=selection
            if context_id:where+=' AND context_id=?';params.append(context_id)
            if state:where+=" AND json_extract(record,'$.state')=?";params.append(state)
            total=self.db.execute('SELECT COUNT(*) FROM a2a_tasks WHERE '+where,params).fetchone()[0]
            records=self.db.execute('SELECT * FROM a2a_tasks WHERE '+where+' ORDER BY updated_at DESC LIMIT ? OFFSET ?',
                (*params,page_size,offset)).fetchall()
            page=[]
            for row in records:
                record=self.validate(row);self.authorize(row);page.append(record)
            next_offset=offset+page_size if offset+page_size<total else 0
            return (page,next_offset,total) if with_total else (page,next_offset)

    def set_push_config(self,*_args,**_kwargs):
        raise PermissionError('A2A callback delivery requires a separate reviewed owner destination and private transport')

    def get_push_config(self,*_args,**_kwargs):return None

    def list_push_configs(self,*_args,**_kwargs):return []

    def delete_push_config(self,*_args,**_kwargs):return False

    def fail_orphans(self,timeout_seconds=300,*,exclude=None):
        # HTTP disconnect and process restart do not cancel durable HAOS missions.
        # Only peer-authorized controller cancellation or inspected owner recovery
        # may publish a terminal outcome. No SDK watchdog can invent one here.
        self.current();return []


    def pop_push_url(self,task_id):
        if self.get(task_id) is None:return ''
        return ''  # No callback can have been configured through this closed index.

    def result_intent(self,task_id,body,state,projected):
        from plugins.platforms.a2a import protocol
        if (not isinstance(body,str) or not body or len(body.encode())>32000 or self.redactor.text(body)!=body
                or state not in {protocol.STATE_COMPLETED,protocol.STATE_INPUT_REQUIRED}
                or not isinstance(projected,str) or len(projected.encode())>32000 or self.redactor.text(projected)!=projected):
            raise PermissionError('exact credential-free native A2A result projection required')
        with self.lock:
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None:raise PermissionError('unknown native A2A result target')
            record=self.validate(row);binding=self.authorize(row)
            if 'read' not in binding['capabilities'] or row['admitted_receipt']!=row['source_key']:
                raise PermissionError('current independent result-read grant and durable input receipt required')
            body_sha=digest(body);expected_sha=digest([state,projected])
            old=self.db.execute('SELECT * FROM a2a_result_intents WHERE task_id=?',(task_id,)).fetchone()
            if old is not None:
                if (old['source_key']!=row['source_key'] or old['binding_digest']!=row['binding_digest']
                        or old['credential_scope']!=row['credential_scope'] or old['body_sha256']!=body_sha
                        or old['expected_sha256']!=expected_sha or old['state'] not in {'writing','committed'}):
                    raise Conflict('native A2A result changed original body, source, grant or account')
                if record['state']==state and record['reply']==projected:
                    # This only recovers an already committed local task outcome.
                    # It never calls the native sender or repeats network output.
                    self.confirm_result(task_id,body,state,projected);return True
                raise Conflict('unfinished native A2A result requires owner recovery')
            if record['state'] in protocol.TERMINAL_STATES:raise Conflict('native A2A task already has another terminal outcome')
            now=time.time()
            self.db.execute('INSERT INTO a2a_result_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
                (task_id,row['source_key'],body_sha,expected_sha,row['binding_digest'],row['credential_scope'],'writing','',now,now))
            self.current();return False

    def confirm_result(self,task_id,body,state,projected):
        with self.lock:
            row=self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None:raise PermissionError('unknown native A2A result target')
            record=self.validate(row);self.authorize(row)
            old=self.db.execute('SELECT * FROM a2a_result_intents WHERE task_id=?',(task_id,)).fetchone()
            if (old is None or old['body_sha256']!=digest(body) or old['expected_sha256']!=digest([state,projected])
                    or old['source_key']!=row['source_key'] or old['binding_digest']!=row['binding_digest']
                    or old['credential_scope']!=row['credential_scope'] or record['state']!=state or record['reply']!=projected):
                raise Conflict('native A2A task does not match its original committed result intent')
            if old['state']=='committed' and old['record_sha256']!=row['record_sha256']:
                raise Conflict('native A2A result acceptance proof changed')
            self.db.execute("UPDATE a2a_result_intents SET state='committed',record_sha256=?,updated_at=? WHERE task_id=?",
                (row['record_sha256'],time.time(),task_id))
            self.current();return {'task_id':task_id,'source_key':row['source_key'],'task_record_sha256':row['record_sha256'],
                'recipient_read_verified':False,'local_task_committed':True}
