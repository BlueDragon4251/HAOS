"""Private durable config around the pinned native TaskStore push-config codec."""
import json
import re
import time

from .gateway import Conflict,digest

CREATE=frozenset({'CreateTaskPushNotificationConfig','tasks/pushNotificationConfig/create','tasks/pushNotificationConfig/set','tasks/pushNotification/set'})
GET=frozenset({'GetTaskPushNotificationConfig','tasks/pushNotificationConfig/get'})
LIST=frozenset({'ListTaskPushNotificationConfigs','tasks/pushNotificationConfig/list'})
DELETE=frozenset({'DeleteTaskPushNotificationConfig','tasks/pushNotificationConfig/delete'})
METHODS=CREATE|GET|LIST|DELETE


class Configs:
    def __init__(self,tasks):
        from plugins.platforms.a2a.protocol import TaskStore
        self.tasks=tasks;self.db=tasks.db;self.native=TaskStore();self.on_change=None
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_push_configs(
            task_id TEXT NOT NULL,revision INTEGER NOT NULL,source_key TEXT NOT NULL,binding_digest TEXT NOT NULL,
            credential_scope TEXT NOT NULL,config TEXT NOT NULL,state TEXT NOT NULL,sha256 TEXT NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(task_id,revision))''')

    def target(self,task_id):
        from plugins.platforms.a2a.security import is_safe_callback_url
        row=self.tasks.entry(task_id)
        if row is None:raise PermissionError('unknown retained A2A callback task')
        binding=self.tasks.authorize(row);owner=self.tasks.value.get('callbacks',{}).get(self.tasks.peer)
        if (not owner or binding.get('allow_callback') is not True or 'read' not in binding['capabilities']
                or not is_safe_callback_url(owner['url'],localhost_mode=False)):
            raise PermissionError('separate current owner callback destination/read approval required')
        return row,owner

    def checksum(self,row):
        return digest([row[k] for k in ['task_id','revision','source_key','binding_digest','credential_scope','config','state']])

    def load(self,task_id,config_id=''):
        task,owner=self.target(task_id)
        row=self.db.execute('SELECT * FROM a2a_push_configs WHERE task_id=? ORDER BY revision DESC LIMIT 1',(task_id,)).fetchone()
        if row is None:return None
        if (row['state'] not in {'active','deleted','consumed'} or row['sha256']!=self.checksum(row)
                or any(row[k]!=task[k] for k in ['task_id','source_key','binding_digest','credential_scope'])):
            raise Conflict('retained A2A callback config changed source or authority')
        try:config=json.loads(row['config'])
        except (ValueError,RecursionError):raise Conflict('damaged native callback config') from None
        if (not isinstance(config,dict) or set(config)!={'configId','taskId','createdAt','pushNotificationConfig'}
                or config['taskId']!=task_id or config['createdAt']!=self.tasks.get(task_id)['created_iso']
                or not isinstance(config['configId'],str) or not re.fullmatch('cfg-[0-9a-f]{12}',config['configId'])
                or config['pushNotificationConfig']!={'url':owner['url']}):
            raise Conflict('native callback config differs from exact owner destination or task')
        if row['state']!='active' or config_id and config['configId']!=config_id:return None
        record={**self.tasks.get(task_id),'push_url':owner['url'],'push_config_id':config['configId']}
        with self.native._lock:self.native._tasks[task_id]=record
        actual=self.native.get_push_config(task_id,config_id)
        if actual!=config:raise Conflict('actual native callback codec differs from retained config')
        return row

    def set(self,task_id,url,agent_slug='',tenant=''):
        if agent_slug or tenant:raise PermissionError('one fixed local A2A agent required for callbacks')
        with self.tasks.lock:
            task,owner=self.target(task_id)
            if url!=owner['url']:raise PermissionError('callback destination lacks exact independent owner approval')
            row=self.load(task_id)
            if row is not None:return self.native.get_push_config(task_id)
            revision=self.db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM a2a_push_configs WHERE task_id=?',(task_id,)).fetchone()[0]
            if revision>32 or self.db.execute('SELECT COUNT(*) FROM a2a_push_configs').fetchone()[0]>=65536:
                raise Conflict('private A2A callback config history full; owner recovery required')
            with self.native._lock:self.native._tasks[task_id]=dict(self.tasks.get(task_id))
            config=self.native.set_push_config(task_id,url)
            if config is None:raise Conflict('actual native callback config creation failed')
            encoded=json.dumps(config,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            values=[task_id,revision,task['source_key'],task['binding_digest'],task['credential_scope'],encoded,'active']
            self.db.execute('INSERT INTO a2a_push_configs VALUES(?,?,?,?,?,?,?,?,?)',(*values,digest(values),time.time()))
            self.tasks.current()
            if self.on_change is not None:self.on_change(task_id)
            return config

    def get(self,task_id,config_id='',agent_slug='',tenant=''):
        if agent_slug or tenant:raise PermissionError('fixed local callback agent required')
        with self.tasks.lock:
            return self.native.get_push_config(task_id,config_id) if self.load(task_id,config_id) is not None else None

    def list(self,task_id,agent_slug='',tenant=''):
        if agent_slug or tenant:raise PermissionError('fixed local callback agent required')
        with self.tasks.lock:
            if self.load(task_id) is None:return []
            return self.native.list_push_configs(task_id)

    def delete(self,task_id,config_id='',agent_slug='',tenant=''):
        if agent_slug or tenant:raise PermissionError('fixed local callback agent required')
        with self.tasks.lock:
            row=self.load(task_id,config_id)
            if row is None:return False
            if not self.native.delete_push_config(task_id,config_id):raise Conflict('actual native callback deletion failed')
            changed={**dict(row),'state':'deleted'}
            self.db.execute("UPDATE a2a_push_configs SET state='deleted',sha256=?,updated_at=? WHERE task_id=? AND revision=?",
                (self.checksum(changed),time.time(),task_id,row['revision']))
            self.tasks.current();return True

    def consume(self,task_id,config_id):
        with self.tasks.lock:
            row=self.load(task_id,config_id)
            if row is None:raise Conflict('callback config is no longer active')
            changed={**dict(row),'state':'consumed'}
            self.db.execute("UPDATE a2a_push_configs SET state='consumed',sha256=?,updated_at=? WHERE task_id=? AND revision=?",
                (self.checksum(changed),time.time(),task_id,row['revision']))
