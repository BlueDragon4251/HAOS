"""Durable controller chunk custody before a native A2A task outcome.

Partial receipts prove local queue custody only, never peer receipt or mission
completion. A task outcome requires the entire controller-origin event group.
"""
import hashlib
import json
import time

from .gateway import Conflict,digest
from .gateway_event_context import validate,HASH
from .gateway_a2a_result import Results
from .gateway_a2a import scope
from .gateway_raw import NativeInbox


class Publisher:
    def __init__(self,adapter,tasks):
        self.adapter=adapter;self.tasks=tasks;self.db=tasks.db;self.results=Results(tasks)
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_controller_routes(
            task_id TEXT PRIMARY KEY,source_key TEXT NOT NULL,mission_id TEXT NOT NULL,route_id TEXT NOT NULL,
            binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_controller_groups(
            task_id TEXT NOT NULL,group_id TEXT NOT NULL,context TEXT NOT NULL,state TEXT NOT NULL,
            created_at REAL NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(task_id,group_id))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_controller_parts(
            task_id TEXT NOT NULL,group_id TEXT NOT NULL,part INTEGER NOT NULL,delivery_id TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(task_id,group_id,part))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_controller_projections(
            delivery_id TEXT PRIMARY KEY,projection TEXT NOT NULL,sha256 TEXT NOT NULL)''')

    def collect(self,chat,content,reply_to,metadata):
        self.tasks.current()
        required={'notify','haos_scope','haos_binding','haos_delivery_id','haos_delivery_attempt','haos_event_context'}
        if (not isinstance(metadata,dict) or not required<=set(metadata)<=required|{'haos_output'}
                or metadata['notify'] is not True or not isinstance(content,str) or not content or len(content.encode())>32000
                or self.tasks.redactor.text(content)!=content or not isinstance(reply_to,str)
                or type(metadata['haos_delivery_attempt']) is not int or not 1<=metadata['haos_delivery_attempt']<=2**31
                or not isinstance(metadata['haos_delivery_id'],str) or not HASH.fullmatch(metadata['haos_delivery_id'])):
            raise PermissionError('exact credential-free controller delivery required for native A2A task')
        context=dict(validate(metadata['haos_event_context']))
        checksum=hashlib.sha256(content.encode()).hexdigest()
        if context['content_sha256']!=checksum or context['total_bytes']>32000 or context['parts']>64:
            raise Conflict('native A2A outcome requires a complete bounded controller event group')
        envelope={'platform':'a2a','scope':scope(self.tasks.value,self.tasks.peer),'chat':chat,'thread':'','message_id':reply_to}
        source=NativeInbox.key(self.tasks.connector,envelope)
        with self.tasks.lock:
            row=self.tasks.by_source(source)
            if row is None:raise PermissionError('no retained native A2A task for controller source')
            self.results.target(row['task_id'],source)
            if (metadata['haos_binding']!={'binding_id':row['binding_id'],'binding_digest':row['binding_digest']}
                    or metadata['haos_scope']!=envelope['scope']):raise PermissionError('controller delivery changed native task owner route')
            task=row['task_id'];route=digest([context['mission_id'],row['binding_id'],row['binding_digest']])
            if metadata['haos_delivery_id']!=digest([route,context['source_event'],context['part']]):
                raise Conflict('controller delivery identity does not match its exact event and part')
            route_identity=(task,source,context['mission_id'],route,row['binding_digest'],row['credential_scope'])
            group=context['group_sha256'];base={k:v for k,v in context.items() if k not in {'part','content_sha256'}}
            encoded=json.dumps(base,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            projection=metadata.get('haos_output',{'text':content,'artifact_ids':[],'source_sha256':checksum})
            if (not isinstance(projection,dict) or set(projection)!={'text','artifact_ids','source_sha256'}
                    or not isinstance(projection['text'],str) or len(projection['text'].encode())>32000
                    or self.tasks.redactor.text(projection['text'])!=projection['text'] or projection['source_sha256']!=checksum
                    or not isinstance(projection['artifact_ids'],list) or len(projection['artifact_ids'])>4
                    or any(not isinstance(identity,str) or not HASH.fullmatch(identity) for identity in projection['artifact_ids'])
                    or len(set(projection['artifact_ids']))!=len(projection['artifact_ids'])):
                raise Conflict('controller output projection changed source bytes, file receipt or bounded text')
            for artifact_id in projection['artifact_ids']:
                self.adapter._haos_a2a_artifacts.prepared(artifact_id,task,group,metadata['haos_delivery_id'])
            projected=json.dumps(projection,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            self.db.execute('BEGIN IMMEDIATE')
            try:
                old=self.db.execute('SELECT * FROM a2a_controller_routes WHERE task_id=?',(task,)).fetchone()
                if old is not None and tuple(old)!=route_identity:raise Conflict('native A2A task cannot change controller mission or owner route')
                if old is None:self.db.execute('INSERT INTO a2a_controller_routes VALUES(?,?,?,?,?,?)',route_identity)
                prior=self.db.execute('SELECT * FROM a2a_controller_groups WHERE task_id=? AND group_id=?',(task,group)).fetchone()
                if prior is not None and (prior['context']!=encoded or prior['state'] not in {'collecting','committed'}):
                    raise Conflict('controller event group changed its manifest')
                if prior is None:
                    if self.db.execute('SELECT COUNT(*) FROM a2a_controller_groups WHERE task_id=?',(task,)).fetchone()[0]>=128:
                        raise Conflict('native A2A controller event history capacity reached')
                    self.db.execute('INSERT INTO a2a_controller_groups VALUES(?,?,?,?,?,?)',(task,group,encoded,'collecting',time.time(),time.time()))
                part=self.db.execute('SELECT * FROM a2a_controller_parts WHERE task_id=? AND group_id=? AND part=?',(task,group,context['part'])).fetchone()
                wanted=(task,group,context['part'],metadata['haos_delivery_id'],content,checksum)
                if part is not None and tuple(part)!=wanted:raise Conflict('controller event part changed after local queue custody')
                if part is None:self.db.execute('INSERT INTO a2a_controller_parts VALUES(?,?,?,?,?,?)',wanted)
                old_projection=self.db.execute('SELECT projection,sha256 FROM a2a_controller_projections WHERE delivery_id=?',(metadata['haos_delivery_id'],)).fetchone()
                if old_projection is not None and tuple(old_projection)!=(projected,digest(projection)):
                    raise Conflict('A2A output projection changed after local chunk custody')
                if old_projection is None:self.db.execute('INSERT INTO a2a_controller_projections VALUES(?,?,?)',(metadata['haos_delivery_id'],projected,digest(projection)))
                parts=self.db.execute('SELECT * FROM a2a_controller_parts WHERE task_id=? AND group_id=? ORDER BY part',(task,group)).fetchall()
                if len(parts)>context['parts']:raise Conflict('controller event has excess chunks')
                body=None
                if len(parts)==context['parts']:
                    chunks=[p['content'] for p in parts]
                    if (any(p['part']!=i or hashlib.sha256(p['content'].encode()).hexdigest()!=p['sha256'] for i,p in enumerate(parts))
                            or sum(len(c.encode()) for c in chunks)!=context['total_bytes']
                            or digest([route,context['source_event'],chunks])!=group):
                        raise Conflict('complete controller event does not match its original manifest')
                    rendered=[];artifacts=[]
                    for item in parts:
                        saved=self.db.execute('SELECT projection,sha256 FROM a2a_controller_projections WHERE delivery_id=?',(item['delivery_id'],)).fetchone()
                        if saved is None:raise Conflict('A2A result lacks an immutable output projection')
                        try:value=json.loads(saved['projection'])
                        except (ValueError,RecursionError):raise Conflict('damaged A2A output projection') from None
                        if digest(value)!=saved['sha256'] or value['source_sha256']!=item['sha256']:raise Conflict('A2A output projection proof changed')
                        for identity in value['artifact_ids']:
                            self.adapter._haos_a2a_artifacts.prepared(identity,task,group,item['delivery_id'])
                        rendered.append(value['text']);artifacts.extend(value['artifact_ids'])
                    if len(artifacts)>4 or len(set(artifacts))!=len(artifacts):raise Conflict('complete A2A result has an invalid attachment set')
                    body=''.join(rendered)
                    if len(body.encode())>32000:raise Conflict('projected A2A task reply exceeds its bounded native limit')
                    if not body:body='Result files attached.' if artifacts else 'Result contains no public text.'
                self.tasks.current();self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:self.db.execute('ROLLBACK')
                raise
            return task,source,group,context,body

    async def send(self,chat,content,reply_to,metadata):
        from gateway.platforms.base import SendResult
        task,source,group,context,body=self.collect(chat,content,reply_to,metadata)
        if body is not None:
            from plugins.platforms.a2a import protocol
            states={'mission.completed':protocol.STATE_COMPLETED,'mission.failed':protocol.STATE_FAILED,
                'mission.cancelled':protocol.STATE_CANCELED,'mission.request':protocol.STATE_INPUT_REQUIRED,
                'gateway.answer-unconfirmed':protocol.STATE_INPUT_REQUIRED}
            state=states.get(context['kind'])
            if state is not None:
                if context['kind']=='mission.request' and (context['request_id'] is None or context['request_method'] is None):
                    raise Conflict('native input-required outcome lacks the exact controller question identity')
                result=await self.adapter.send_outcome(task,source,group,body,state)
                if result.success is not True or result.message_id!=task:raise Conflict('native A2A outcome was not locally committed')
            with self.tasks.lock:
                self.tasks.current()
                self.db.execute("UPDATE a2a_controller_groups SET state='committed',updated_at=? WHERE task_id=? AND group_id=?",(time.time(),task,group))
        return SendResult(success=True,message_id=metadata['haos_delivery_id'],raw_response={
            'recipient_read_verified':False,'local_controller_chunk_committed':True,'complete_controller_group':body is not None})
