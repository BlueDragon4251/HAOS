"""Native task cancellation requests through the independent root controller.

A request acknowledgment is never a cancelled task. Only a subsequent complete
controller event group may publish that terminal native outcome.
"""
import json
import time

from .gateway import Conflict,digest
from .gateway_event_context import STATES


class Controls:
    def __init__(self,tasks,originals,value,connector,policy):
        self.tasks=tasks;self.originals=originals;self.value=value;self.connector=connector;self.policy=policy;self.db=tasks.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_control_intents(
            task_id TEXT NOT NULL,operation TEXT NOT NULL,source_key TEXT NOT NULL,request TEXT NOT NULL,
            sha256 TEXT NOT NULL,state TEXT NOT NULL,response TEXT NOT NULL,response_sha256 TEXT NOT NULL,
            created_at REAL NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(task_id,operation))''')

    async def cancel(self,source):
        self.tasks.current();row=self.tasks.entry(source['task_id'])
        if row!=source:raise Conflict('native A2A cancellation changed retained task')
        binding=self.tasks.authorize(row)
        if 'cancel' not in binding['capabilities']:raise PermissionError('independent A2A cancellation grant required')
        proof=self.originals.get(self.policy(),self.connector,self.value,self.tasks.peer,row['raw_id'])
        with self.tasks.lock:
            target=self.db.execute('SELECT * FROM a2a_controller_routes WHERE task_id=?',(row['task_id'],)).fetchone()
            if (target is None or target['source_key']!=row['source_key'] or target['binding_digest']!=row['binding_digest']
                    or target['credential_scope']!=row['credential_scope']
                    or target['route_id']!=digest([target['mission_id'],row['binding_id'],row['binding_digest']])):
                raise Conflict('A2A task must first receive its exact controller mission receipt')
            mid=target['mission_id']
            envelope={**proof['envelope'],'message_id':'control-cancel-'+digest([row['task_id'],row['source_key']]),'text':'/cancel '+mid}
            self.policy().authorize(self.connector,envelope)
            request={'connector':self.connector,'envelope':envelope,
                'binding':{'binding_id':row['binding_id'],'binding_digest':row['binding_digest']}}
            encoded=json.dumps(request,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            checksum=digest([row['task_id'],row['source_key'],row['binding_digest'],row['credential_scope'],encoded])
            old=self.db.execute("SELECT * FROM a2a_control_intents WHERE task_id=? AND operation='cancel'",(row['task_id'],)).fetchone()
            if old is not None:
                if old['source_key']!=row['source_key'] or old['request']!=encoded or old['sha256']!=checksum or old['state'] not in {'writing','committed'}:
                    raise Conflict('native A2A cancellation changed source, mission, grant or request')
                if old['state']=='committed':
                    if old['response_sha256']!=digest([checksum,old['response']]):raise Conflict('damaged A2A cancellation receipt')
                    return {'cancel_requested':True}
            else:
                self.db.execute('INSERT INTO a2a_control_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (row['task_id'],'cancel',row['source_key'],encoded,checksum,'writing','','',time.time(),time.time()))
        from .gateway_runtime import call
        # A repeated explicit RPC uses the exact same controller deduplication
        # key. GatewayEngine commits the cancellation and its inbox atomically;
        # no new command identity is invented after a lost local reply.
        response=await call('gateway.receive',request)
        if (not isinstance(response,dict) or set(response)!={'mission_id','state'} or response['mission_id']!=mid
                or not isinstance(response['state'],str) or response['state'] not in STATES):
            raise Conflict('root controller did not confirm exact A2A cancellation request')
        encoded_response=json.dumps(response,sort_keys=True,separators=(',',':'))
        with self.tasks.lock:
            self.tasks.current();self.tasks.authorize(row)
            self.db.execute("UPDATE a2a_control_intents SET state='committed',response=?,response_sha256=?,updated_at=? WHERE task_id=? AND operation='cancel'",
                (encoded_response,digest([checksum,encoded_response]),time.time(),row['task_id']))
        return {'cancel_requested':True}
