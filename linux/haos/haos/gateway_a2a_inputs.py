"""Retained clarification inputs for an existing native task and exact question."""
import json
import time

from .gateway import Conflict,digest
from .gateway_a2a_admission import parse
from .gateway_event_context import validate


class Inputs:
    def __init__(self,tasks):
        self.tasks=tasks;self.db=tasks.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_task_inputs(
            source_key TEXT PRIMARY KEY,task_id TEXT NOT NULL,raw_id TEXT NOT NULL,binding_id TEXT NOT NULL,
            binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,question_epoch TEXT NOT NULL,
            request_id TEXT NOT NULL,request_method TEXT NOT NULL,envelope TEXT NOT NULL,sha256 TEXT NOT NULL,
            admitted_receipt TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(task_id,question_epoch))''')

    def checked(self,stored,proof):
        row=dict(stored);task=self.tasks.entry(row['task_id'])
        if (task is None or task['binding_id']!=row['binding_id'] or task['binding_digest']!=row['binding_digest']
                or task['credential_scope']!=row['credential_scope'] or row['raw_id']!=proof['id']
                or row['source_key']!=proof['source_key'] or row['task_id']!=proof.get('target_task_id') or row['question_epoch']!=proof.get('question_epoch')
                or proof['binding_digest']!=row['binding_digest'] or proof['credential_scope']!=row['credential_scope']
                or row['admitted_receipt'] not in {'',row['source_key']}
                or digest([row[k] for k in ['source_key','task_id','raw_id','binding_id','binding_digest','credential_scope',
                    'question_epoch','request_id','request_method','envelope']])!=row['sha256']):
            raise Conflict('A2A clarification changed retained task, question, source or grant')
        if 'answer' not in self.tasks.authorize(task)['capabilities']:raise PermissionError('independent A2A answer grant required')
        if self.db.execute("SELECT 1 FROM a2a_task_transitions WHERE task_id=? AND state!='committed'",(row['task_id'],)).fetchone():
            raise Conflict('uncertain native task transition blocks clarification dispatch')
        try:envelope=json.loads(row['envelope'])
        except (ValueError,RecursionError):raise Conflict('damaged A2A clarification command') from None
        # Validate the full independent route again; never inherit authority
        # merely from taskId, contextId or a token-authenticated connection.
        if (set(envelope)!=set(proof['envelope'])
                or any(envelope[k]!=v for k,v in proof['envelope'].items() if k!='text')
                or envelope['text']!='/answer '+self.mission(task)+' '+row['request_id']+' '+self.answer(proof,row['request_method'])):
            raise Conflict('A2A clarification command differs from retained answer and controller question')
        self.tasks.policy().authorize(self.tasks.connector,envelope)
        return {**task,'source_key':row['source_key'],'raw_id':row['raw_id'],'admitted_receipt':row['admitted_receipt']},envelope

    def mission(self,task):
        target=self.db.execute('SELECT * FROM a2a_controller_routes WHERE task_id=?',(task['task_id'],)).fetchone()
        if (target is None or target['source_key']!=task['source_key'] or target['binding_digest']!=task['binding_digest']
                or target['credential_scope']!=task['credential_scope']
                or target['route_id']!=digest([target['mission_id'],task['binding_id'],task['binding_digest']])):
            raise Conflict('A2A clarification requires the exact retained controller mission route')
        return target['mission_id']

    def answer(self,proof,method):
        from plugins.platforms.a2a.protocol import extract_text
        body=extract_text(parse(proof['raw'])['params']).strip()
        if (method not in {'approval','clarify'} or not body or len(body.encode())>16000
                or self.tasks.redactor.text(body)!=body or method=='approval' and body not in {'once','deny'}):
            raise PermissionError('bounded exact clarification or once/deny approval answer required')
        return body

    def lookup(self,proof):
        with self.tasks.lock:
            self.tasks.current()
            stored=self.db.execute('SELECT * FROM a2a_task_inputs WHERE source_key=?',(proof['source_key'],)).fetchone()
            return None if stored is None else self.checked(stored,proof)[0]

    def question(self,task_id):
        from plugins.platforms.a2a import protocol
        with self.tasks.lock:
            task=self.tasks.entry(task_id);record=self.tasks.get(task_id)
            if task is None or record['state']!=protocol.STATE_INPUT_REQUIRED:
                raise Conflict('native A2A task has no current input-required controller question')
            epoch=self.db.execute("SELECT * FROM a2a_result_epochs WHERE task_id=? AND record_sha256=? AND state='committed' ORDER BY created_at DESC LIMIT 1",
                (task_id,task['record_sha256'])).fetchone()
            if epoch is None:raise Conflict('native A2A question lacks a committed controller event epoch')
            wanted={k:epoch[k] for k in ['source_key','binding_digest','credential_scope','body_sha256','expected_sha256']}
            if (any(epoch[k]!=task[k] for k in ['source_key','binding_digest','credential_scope'])
                    or epoch['expected_sha256']!=digest([protocol.STATE_INPUT_REQUIRED,record['reply']])
                    or epoch['receipt_sha256']!=digest([task_id,epoch['epoch'],wanted,task['record_sha256']])):
                raise Conflict('native A2A question epoch has no matching immutable acceptance proof')
            group=self.db.execute('SELECT context FROM a2a_controller_groups WHERE task_id=? AND group_id=?',(task_id,epoch['epoch'])).fetchone()
            if group is None:raise Conflict('native A2A question lacks its retained controller manifest')
            try:context=json.loads(group['context'])
            except (ValueError,RecursionError):raise Conflict('damaged A2A controller question context') from None
            validate({**context,'part':0,'content_sha256':'0'*64})
            if (context['kind']!='mission.request' or context['group_sha256']!=epoch['epoch']
                    or context['mission_id']!=self.mission(task) or not isinstance(context['request_id'],str)
                    or any(c.isspace() for c in context['request_id']) or context['request_method'] not in {'approval','clarify'}):
                raise Conflict('A2A input requires a fresh exact controller approval/clarification question')
            return context

    def prepare(self,proof):
        from plugins.platforms.a2a import protocol
        with self.tasks.lock:
            if self.lookup(proof) is not None:raise Conflict('recover the original clarification input instead of dispatching it twice')
            task=self.tasks.entry(proof['target_task_id']);record=self.tasks.get(proof['target_task_id'])
            if (task is None or task['admitted_receipt']!=task['source_key'] or record['state']!=protocol.STATE_INPUT_REQUIRED
                    or task['context_id']!=proof['envelope']['chat'] or task['binding_digest']!=proof['binding_digest']
                    or 'answer' not in self.tasks.authorize(task)['capabilities']):
                raise PermissionError('exact owned input-required native A2A task and independent answer grant required')
            context=self.question(task['task_id'])
            if proof.get('question_epoch')!=context['group_sha256']:
                raise Conflict('A2A clarification must echo the exact currently offered question epoch')
            envelope={**proof['envelope'],'text':'/answer '+context['mission_id']+' '+context['request_id']+' '+self.answer(proof,context['request_method'])}
            encoded=json.dumps(envelope,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            values=[proof['source_key'],task['task_id'],proof['id'],task['binding_id'],task['binding_digest'],task['credential_scope'],
                context['group_sha256'],context['request_id'],context['request_method'],encoded]
            if self.db.execute('SELECT 1 FROM a2a_task_inputs WHERE task_id=? AND question_epoch=?',(task['task_id'],context['group_sha256'])).fetchone():
                raise Conflict('this exact controller question already has a retained answer; reuse its original message ID')
            self.db.execute('INSERT INTO a2a_task_inputs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(*values,digest(values),'',time.time()))
            self.tasks.current();return self.lookup(proof)

    def admitted(self,proof,receipt):
        with self.tasks.lock:
            if receipt!=proof['source_key'] or self.lookup(proof) is None:raise PermissionError('exact retained parent clarification receipt required')
            self.db.execute('UPDATE a2a_task_inputs SET admitted_receipt=? WHERE source_key=?',(receipt,proof['source_key']))
            self.tasks.current()

    def envelope(self,proof):
        with self.tasks.lock:
            row=self.db.execute('SELECT * FROM a2a_task_inputs WHERE source_key=?',(proof['source_key'],)).fetchone()
            if row is None:raise PermissionError('unretained A2A clarification cannot reach controller')
            return self.checked(row,proof)[1]
