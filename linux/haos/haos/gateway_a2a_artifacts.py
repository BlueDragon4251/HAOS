"""Private controller-exported A2A artifacts, served only to their current peer."""
import hashlib
import json
import re
import time
from copy import deepcopy

from .gateway import Conflict,digest
from .gateway_media import MAX_BYTES

HASH=re.compile('[0-9a-f]{64}\\Z')
NAME=re.compile('result-[0-9]{1,5}(?:\\.[a-z0-9]{1,12})?\\Z')


class Artifacts:
    def __init__(self,tasks):
        self.tasks=tasks;self.db=tasks.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_output_artifacts(
            id TEXT PRIMARY KEY,task_id TEXT NOT NULL,group_id TEXT NOT NULL,delivery_id TEXT NOT NULL,
            export_id TEXT NOT NULL,metadata TEXT NOT NULL,metadata_sha256 TEXT NOT NULL,
            data BLOB NOT NULL,created_at REAL NOT NULL,UNIQUE(task_id,delivery_id,export_id))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS a2a_artifact_reads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,artifact_id TEXT NOT NULL,task_id TEXT NOT NULL,
            binding_digest TEXT NOT NULL,state TEXT NOT NULL,written INTEGER NOT NULL,
            size INTEGER NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL)''')

    def current(self,task_id,kind='file'):
        row=self.tasks.entry(task_id)
        if row is None or row['admitted_receipt']!=row['source_key']:raise PermissionError('exact retained native A2A task input required')
        binding=self.tasks.authorize(row)
        if kind not in {'file','text'} or 'read' not in binding['capabilities'] or kind=='file' and binding.get('allow_outbound_media') is not True:
            raise PermissionError('separate current A2A file-output/read grant required')
        return row

    def checked(self,row):
        try:meta=json.loads(row['metadata'])
        except (ValueError,RecursionError):raise Conflict('damaged private A2A artifact metadata') from None
        if not isinstance(meta,dict):raise Conflict('damaged private A2A artifact metadata')
        kind=meta.get('kind','file');task=self.current(row['task_id'],kind)
        fields={'task_id','source_key','binding_id','binding_digest','credential_scope','group_id','delivery_id','export_id','sha256','size','name','mime'}
        if kind=='text':fields.add('kind')
        if (not isinstance(meta,dict) or set(meta)!=fields or row['metadata_sha256']!=digest(meta)
                or json.dumps(meta,sort_keys=True,separators=(',',':'))!=row['metadata']
                or any(meta[key]!=task[key] for key in ['task_id','source_key','binding_id','binding_digest','credential_scope'])
                or any(meta[key]!=row[key] for key in ['task_id','group_id','delivery_id','export_id'])
                or any(not isinstance(meta[key],str) or not HASH.fullmatch(meta[key]) for key in ['group_id','delivery_id','export_id','sha256'])
                or row['id']!=digest(meta) or type(meta['size']) is not int or not 1<=meta['size']<=MAX_BYTES
                or not isinstance(meta['name'],str) or not NAME.fullmatch(meta['name'])
                or not isinstance(meta['mime'],str) or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',meta['mime'])
                or kind=='text' and (meta['name']!='result-0.txt' or meta['mime']!='text/plain')):
            raise Conflict('private A2A artifact changed source, grant, bytes or transport identity')
        data=bytes(row['data'])
        if len(data)!=meta['size'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:
            raise Conflict('private A2A artifact bytes changed or were purged')
        if any(secret.encode() in data for secret in self.tasks.redactor.secrets):raise PermissionError('private credential in A2A artifact')
        return meta,data

    def put(self,task_id,group_id,delivery_id,offer,data,name,mime,*,kind='file'):
        with self.tasks.lock:
            task=self.current(task_id,kind)
            if (not isinstance(offer,dict) or set(offer)!={'id','size','sha256'} or not isinstance(data,bytes)
                    or type(offer['size']) is not int or not 1<=offer['size']<=MAX_BYTES or len(data)!=offer['size']
                    or not isinstance(offer['sha256'],str) or hashlib.sha256(data).hexdigest()!=offer['sha256']
                    or not isinstance(offer['id'],str) or not HASH.fullmatch(offer['id'])
                    or any(not isinstance(value,str) or not HASH.fullmatch(value) for value in [group_id,delivery_id])
                    or not isinstance(name,str) or not NAME.fullmatch(name) or not isinstance(mime,str)
                    or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',mime)):
                raise ValueError('exact bounded sealed A2A artifact required')
            if any(secret.encode() in data for secret in self.tasks.redactor.secrets):raise PermissionError('private credential cannot become A2A output')
            meta={key:task[key] for key in ['task_id','source_key','binding_id','binding_digest','credential_scope']}
            meta.update(group_id=group_id,delivery_id=delivery_id,export_id=offer['id'],sha256=offer['sha256'],size=offer['size'],name=name,mime=mime)
            if kind=='text':
                if name!='result-0.txt' or mime!='text/plain':raise ValueError('fixed UTF-8 controller text artifact required')
                text=data.decode('utf-8')
                from plugins.platforms.a2a.security import redact_outbound
                if redact_outbound(text)!=text:raise PermissionError('native A2A egress redaction required before controller text custody')
                meta['kind']='text'
            identity=digest(meta);encoded=json.dumps(meta,sort_keys=True,separators=(',',':'))
            prior=self.db.execute('SELECT * FROM a2a_output_artifacts WHERE task_id=? AND delivery_id=? AND export_id=?',(task_id,delivery_id,offer['id'])).fetchone()
            if prior is not None:
                if prior['id']!=identity:raise Conflict('A2A exported artifact changed after first custody')
                actual,retained=self.checked(prior)
                if actual!=meta or retained!=data:raise Conflict('A2A artifact replay changed bytes')
                return identity
            if self.db.execute("SELECT COUNT(*) FROM a2a_output_artifacts WHERE task_id=? AND group_id=? AND COALESCE(json_extract(metadata,'$.kind'),'file')=?",(task_id,group_id,kind)).fetchone()[0]>=(1 if kind=='text' else 4):
                raise Conflict('A2A task result exceeds its file or text attachment bound')
            if self.db.execute('SELECT COUNT(*) FROM a2a_output_artifacts').fetchone()[0]>=65536:
                raise Conflict('A2A artifact history capacity reached')
            count,total=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)),0) FROM a2a_output_artifacts WHERE length(data)>0').fetchone()
            if count>=128 or total+len(data)>64*1024*1024:raise Conflict('private A2A artifact storage full; owner recovery required')
            self.db.execute('INSERT INTO a2a_output_artifacts VALUES(?,?,?,?,?,?,?,?,?)',
                (identity,task_id,group_id,delivery_id,offer['id'],encoded,digest(meta),data,time.time()))
            self.tasks.current();return identity

    def for_task(self,task_id):
        from plugins.platforms.a2a import protocol
        with self.tasks.lock:
            task=self.tasks.entry(task_id);record=self.tasks.get(task_id)
            if task is None or record['state']!=protocol.STATE_COMPLETED:return []
            epoch=self.db.execute("SELECT * FROM a2a_result_epochs WHERE task_id=? AND record_sha256=? AND state='committed' ORDER BY created_at DESC LIMIT 1",
                (task_id,task['record_sha256'])).fetchone()
            if epoch is None:return []
            wanted={key:epoch[key] for key in ['source_key','binding_digest','credential_scope','body_sha256','expected_sha256']}
            if (any(epoch[key]!=task[key] for key in ['source_key','binding_digest','credential_scope'])
                    or epoch['expected_sha256']!=digest([record['state'],record['reply']])
                    or epoch['receipt_sha256']!=digest([task_id,epoch['epoch'],wanted,task['record_sha256']])):
                raise Conflict('A2A artifact outcome epoch lacks exact committed task proof')
            rows=self.db.execute('SELECT * FROM a2a_output_artifacts WHERE task_id=? AND group_id=? ORDER BY created_at,id',(task_id,epoch['epoch'])).fetchall()
            if len(rows)>5:raise Conflict('A2A committed artifact set exceeds task bound')
            return [{'id':row['id'],**self.checked(row)[0]} for row in rows]

    def get(self,identity):
        if not isinstance(identity,str) or not HASH.fullmatch(identity):raise PermissionError('exact A2A artifact identity required')
        with self.tasks.lock:
            self.tasks.current();row=self.db.execute('SELECT * FROM a2a_output_artifacts WHERE id=?',(identity,)).fetchone()
            if row is None:raise PermissionError('artifact unavailable for this A2A peer')
            available=self.for_task(row['task_id'])
            if identity not in {item['id'] for item in available}:raise PermissionError('artifact has no complete committed A2A task outcome')
            meta,data=self.checked(row);return {**meta,'id':identity,'data':data}

    def prepared(self,identity,task_id,group_id,delivery_id):
        with self.tasks.lock:
            row=self.db.execute('SELECT * FROM a2a_output_artifacts WHERE id=?',(identity,)).fetchone()
            if row is None or (row['task_id'],row['group_id'],row['delivery_id'])!=(task_id,group_id,delivery_id):
                raise PermissionError('A2A artifact belongs to another task, result group or controller chunk')
            return self.checked(row)[0]

    def url(self,identity):return self.tasks.value['tls']['public_url']+'/artifacts/'+identity

    def parts(self,task_id):
        from plugins.platforms.a2a import protocol
        return [protocol.file_part(url=self.url(item['id']),filename=item['name'],media_type=item['mime']) for item in self.for_task(task_id)]

    def decorate(self,payload):
        def task(value):
            if not isinstance(value,dict) or not isinstance(value.get('id'),str):return value
            parts=self.parts(value['id'])
            if not parts:return value
            artifact={'artifactId':'haos-files-'+digest([value['id'],parts]),'parts':parts}
            return {**value,'artifacts':[*value.get('artifacts',[]),artifact]}
        result=deepcopy(payload)
        if not isinstance(result,dict) or not isinstance(result.get('result'),dict):return result
        value=result['result']
        if 'task' in value:value['task']=task(value['task'])
        elif isinstance(value.get('tasks'),list):value['tasks']=[task(item) for item in value['tasks']]
        elif 'id' in value:result['result']=task(value)
        return result

    def begin_read(self,item):
        with self.tasks.lock:
            self.current(item['task_id'],item.get('kind','file'))
            if self.db.execute('SELECT COUNT(*) FROM a2a_artifact_reads').fetchone()[0]>=65536:
                raise Conflict('A2A artifact audit history full; owner recovery required')
            cursor=self.db.execute('INSERT INTO a2a_artifact_reads(artifact_id,task_id,binding_digest,state,written,size,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (item['id'],item['task_id'],item['binding_digest'],'writing',0,item['size'],time.time(),time.time()))
            self.tasks.current();return cursor.lastrowid

    def finish_read(self,receipt,written,complete):
        if type(written) is not int or written<0 or type(complete) is not bool:raise ValueError('exact local artifact transfer outcome required')
        with self.tasks.lock:
            row=self.db.execute('SELECT size FROM a2a_artifact_reads WHERE id=?',(receipt,)).fetchone()
            if row is None or written>row['size'] or complete and written!=row['size']:raise Conflict('A2A artifact audit bytes changed')
            self.db.execute('UPDATE a2a_artifact_reads SET state=?,written=?,updated_at=? WHERE id=?',
                ('stream-written' if complete else 'interrupted',written,time.time(),receipt))
