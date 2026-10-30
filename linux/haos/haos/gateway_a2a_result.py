"""Controller-event-bound native task outcomes, with immutable acceptance history."""
import json
import re
import time

from .gateway import Conflict,digest


class Results:
    def __init__(self,tasks):
        self.tasks=tasks;self.db=tasks.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_result_epochs(
            task_id TEXT NOT NULL,epoch TEXT NOT NULL,source_key TEXT NOT NULL,binding_digest TEXT NOT NULL,
            credential_scope TEXT NOT NULL,body_sha256 TEXT NOT NULL,expected_sha256 TEXT NOT NULL,
            state TEXT NOT NULL,record_sha256 TEXT NOT NULL,receipt_sha256 TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(task_id,epoch))''')

    def target(self,task_id,source_key):
        row=self.tasks.by_source(source_key)
        if row is None or row['task_id']!=task_id or row['admitted_receipt']!=source_key:
            raise PermissionError('exact durably admitted native A2A task required')
        binding=self.tasks.authorize(row)
        if 'read' not in binding['capabilities']:raise PermissionError('independent A2A read grant required')
        return row

    def committed(self,task_id):
        """Read an exact current result acceptance proof without causing a transition."""
        with self.tasks.lock:
            task=self.tasks.entry(task_id)
            if task is None:return None
            record=self.tasks.get(task_id)
            epoch=self.db.execute("SELECT * FROM a2a_result_epochs WHERE task_id=? AND record_sha256=? AND state='committed' ORDER BY created_at DESC LIMIT 1",
                (task_id,task['record_sha256'])).fetchone()
            if epoch is None:return None
            wanted={key:epoch[key] for key in ['source_key','binding_digest','credential_scope','body_sha256','expected_sha256']}
            if (any(epoch[key]!=task[key] for key in ['source_key','binding_digest','credential_scope'])
                    or epoch['expected_sha256']!=digest([record['state'],record['reply']])
                    or epoch['receipt_sha256']!=digest([task_id,epoch['epoch'],wanted,task['record_sha256']])):
                raise Conflict('current native A2A result acceptance proof changed')
            return dict(epoch)

    def expected(self,body,state):
        from plugins.platforms.a2a import protocol,security
        if (not isinstance(body,str) or not body or len(body.encode())>32000 or self.tasks.redactor.text(body)!=body
                or not isinstance(state,str) or state not in protocol.TERMINAL_STATES|{protocol.STATE_INPUT_REQUIRED}):
            raise ValueError('closed credential-free native A2A task outcome required')
        projected=security.redact_outbound(body)
        if state==protocol.STATE_COMPLETED:
            stripped=projected.lstrip()
            if stripped.upper().startswith(protocol.INPUT_REQUIRED_MARKER):
                state=protocol.STATE_INPUT_REQUIRED;projected=stripped[len(protocol.INPUT_REQUIRED_MARKER):].strip()
        return state,projected

    def begin(self,task_id,source_key,epoch,body,state):
        if not isinstance(epoch,str) or not re.fullmatch('[0-9a-f]{64}',epoch):raise ValueError('exact controller event-group digest required')
        requested_state=state
        state,projected=self.expected(body,state)
        with self.tasks.lock:
            row=self.target(task_id,source_key)
            wanted={'source_key':source_key,'binding_digest':row['binding_digest'],'credential_scope':row['credential_scope'],
                'body_sha256':digest(body),'expected_sha256':digest([state,projected])}
            old=self.db.execute('SELECT * FROM a2a_result_epochs WHERE task_id=? AND epoch=?',(task_id,epoch)).fetchone()
            if old is not None:
                if any(old[k]!=value for k,value in wanted.items()) or old['state'] not in {'writing','committed'}:
                    raise Conflict('native A2A event outcome changed body, source, grant or account')
                if old['state']=='committed':
                    proof=digest([task_id,epoch,wanted,old['record_sha256']])
                    if old['receipt_sha256']!=proof:raise Conflict('damaged native A2A event acceptance proof')
                    return True,state,projected
                record=self.tasks.get(task_id)
                if record['state']==state and record['reply']==projected:
                    self.confirm(task_id,source_key,epoch,body,requested_state);return True,state,projected
                raise Conflict('uncertain native A2A event transition requires owner recovery')
            from plugins.platforms.a2a import protocol
            record=self.tasks.get(task_id)
            if record['state'] in protocol.TERMINAL_STATES:raise Conflict('native A2A task already has a terminal outcome')
            if self.db.execute("SELECT 1 FROM a2a_result_epochs WHERE task_id=? AND state='writing'",(task_id,)).fetchone():
                raise Conflict('another native A2A event outcome is uncertain')
            if self.db.execute('SELECT COUNT(*) FROM a2a_result_epochs WHERE task_id=?',(task_id,)).fetchone()[0]>=32:
                raise Conflict('native A2A event outcome budget exhausted')
            now=time.time()
            self.db.execute('INSERT INTO a2a_result_epochs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (task_id,epoch,*[wanted[k] for k in ['source_key','binding_digest','credential_scope','body_sha256','expected_sha256']],
                    'writing','','',now,now))
            self.tasks.current();return False,state,projected

    def confirm(self,task_id,source_key,epoch,body,state):
        state,projected=self.expected(body,state)
        with self.tasks.lock:
            row=self.target(task_id,source_key);record=self.tasks.get(task_id)
            old=self.db.execute('SELECT * FROM a2a_result_epochs WHERE task_id=? AND epoch=?',(task_id,epoch)).fetchone()
            wanted={'source_key':source_key,'binding_digest':row['binding_digest'],'credential_scope':row['credential_scope'],
                'body_sha256':digest(body),'expected_sha256':digest([state,projected])}
            if (old is None or any(old[k]!=value for k,value in wanted.items())
                    or record['state']!=state or record['reply']!=projected):raise Conflict('native A2A outcome was not committed exactly')
            proof=digest([task_id,epoch,wanted,row['record_sha256']])
            self.db.execute("UPDATE a2a_result_epochs SET state='committed',record_sha256=?,receipt_sha256=?,updated_at=? WHERE task_id=? AND epoch=?",
                (row['record_sha256'],proof,time.time(),task_id,epoch))
            self.tasks.current();return proof
