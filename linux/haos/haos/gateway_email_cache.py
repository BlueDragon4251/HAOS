"""Private bounded durable raw-mail custody, never an agent-readable pathname."""
import hashlib
import json
import math
import re
import time

from .gateway import digest,Conflict
from .gateway_email_codec import MAX_RAW,MAX_HEADERS
from .gateway_email_imap import uid_number
from .gateway_raw import NativeInbox

LIMIT=64*1024*1024


class RawCache:
    def __init__(self,path,redactor):
        self.store=NativeInbox(path,redactor);self.db=self.store.db;self.redactor=redactor
        self.db.execute('PRAGMA max_page_count='+str(LIMIT//self.db.execute('PRAGMA page_size').fetchone()[0]))
        self.db.execute('''CREATE TABLE IF NOT EXISTS email_raw_messages(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            source_id TEXT NOT NULL,uid_validity INTEGER NOT NULL,uid INTEGER NOT NULL,
            sha256 TEXT NOT NULL,metadata TEXT NOT NULL,data BLOB NOT NULL,created_at REAL NOT NULL)''')

    def close(self):self.store.close()

    @staticmethod
    def current(policy,row):
        binding=policy.current_binding({'binding_id':row['binding_id'],'binding_digest':row['binding_digest']})
        if policy.connectors[binding['connector']]['platform']!='email' or binding['connector']!=row['connector']:
            raise PermissionError('exact current email raw-custody grant required')
        return binding

    def put(self,policy,connector,resource):
        if not isinstance(resource,dict) or 'content' not in resource or 'approval' not in resource:
            raise ValueError('complete independently approved raw email required')
        data=resource['content'];approval=resource['approval']
        if not isinstance(data,bytes) or not 1<=len(data)<=MAX_RAW or resource.get('size')!=len(data):
            raise ValueError('bounded complete raw email bytes required')
        uid_number(resource['uid']);uid_number(resource['uid_validity'])
        checksum=hashlib.sha256(data).hexdigest()
        boundary=data.find(b'\r\n\r\n')
        if (checksum!=resource['sha256'] or not 0<boundary<=MAX_HEADERS
                or hashlib.sha256(data[:boundary+4]).hexdigest()!=approval['header_sha256']):
            raise Conflict('raw mail resource changed after independent approval')
        binding=self.current(policy,{'connector':connector,**approval})
        routed=policy.authorize(connector,approval['envelope'])
        if routed['id']!=binding['id'] or digest(routed)!=digest(binding):raise PermissionError('raw email source differs from the captured recipient grant')
        stamp=resource.get('internal_at')
        if (type(stamp) not in {int,float} or not math.isfinite(stamp) or not binding['since']<stamp*1000
                or not 0<stamp<=time.time()+300 or approval.get('received_at')!=stamp):
            raise PermissionError('raw email was not received under this exact timed owner grant')
        if any(secret.encode() in data for secret in self.redactor.secrets):raise PermissionError('private email credential reflection refused')
        metadata=json.dumps({key:value for key,value in resource.items() if key!='content'},ensure_ascii=False,allow_nan=False)
        if len(metadata.encode())>16384:raise ValueError('bounded private mail source metadata required')
        identity=digest([connector,digest(binding),resource['uid_validity'],resource['uid'],checksum])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT sha256 FROM email_raw_messages WHERE id=?',(identity,)).fetchone()
            if old is None:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(length(data)+length(metadata)),0) FROM email_raw_messages WHERE length(data)>0').fetchone()
                if (count>=128 or size+len(data)+len(metadata.encode())>LIMIT
                        or self.db.execute('SELECT COUNT(*) FROM email_raw_messages').fetchone()[0]>=65536):
                    raise Conflict('private raw email custody capacity reached')
                self.db.execute('INSERT INTO email_raw_messages VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,connector,binding['id'],digest(binding),approval['envelope']['message_id'],resource['uid_validity'],resource['uid'],
                     checksum,metadata,data,time.time()))
            elif old['sha256']!=checksum:raise Conflict('raw email replay changed bytes')
            self.current(policy,{'connector':connector,**approval});self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return identity

    def get(self,policy,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{64}',identity):raise ValueError('exact opaque raw email receipt required')
        row=self.db.execute('SELECT * FROM email_raw_messages WHERE id=?',(identity,)).fetchone()
        if row is None:raise PermissionError('private raw email resource unavailable')
        self.current(policy,row);data=bytes(row['data'])
        if not data:raise PermissionError('raw email source was purged after explicit owner inspection')
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Conflict('private raw email bytes are damaged')
        return {**json.loads(row['metadata']),'content':data}

    def owner_inventory(self,inbox,policy):
        result=[]
        rows=self.db.execute('SELECT id,connector,binding_id,binding_digest,source_id,uid_validity,uid,sha256,metadata,created_at,length(data) AS stored_bytes FROM email_raw_messages ORDER BY (length(data)>0) DESC,created_at DESC LIMIT 128').fetchall()
        for row in rows:
            approval=json.loads(row['metadata'])['approval']
            native_id=inbox.key(row['connector'],approval['envelope'])
            native=inbox.db.execute('SELECT state,binding_digest FROM native_inbox WHERE id=?',(native_id,)).fetchone()
            if native is not None and native['binding_digest']!=row['binding_digest']:raise Conflict('raw email custody points at another input grant')
            try:self.current(policy,row);revoked=False
            except PermissionError:revoked=True
            state=native['state'] if native is not None else 'unadmitted'
            allowed=bool(row['stored_bytes']) and (state in {'committed','ignored','discarded'} or native is None and revoked)
            item={'id':row['id'],'connector':row['connector'],'binding_id':row['binding_id'],'source_id':row['source_id'],
                'uid_validity':row['uid_validity'],'uid':row['uid'],'sha256':row['sha256'],'rfc_message_id':approval['rfc_message_id'],
                'stored_bytes':row['stored_bytes'],'created_at':row['created_at'],'input_state':state,
                'state':'retained' if row['stored_bytes'] else 'purged','purge_allowed':allowed}
            item['snapshot_sha256']=digest(item);result.append(item)
        total=self.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM email_raw_messages').fetchone()[0]
        return {'sources':result,'stored_bytes':total,'limit_bytes':LIMIT,'limit_active_records':128,
            'history_truncated':self.db.execute('SELECT COUNT(*) FROM email_raw_messages').fetchone()[0]>128}

    def owner_purge(self,inbox,policy,request):
        from .gateway_email_recovery import decision
        decision(request,{'id','snapshot_sha256'})
        if any(not isinstance(request[key],str) or not re.fullmatch('[0-9a-f]{64}',request[key]) for key in ('id','snapshot_sha256')):
            raise ValueError('exact inspected raw email receipt required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('''CREATE TABLE IF NOT EXISTS email_raw_owner_events(
                id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
                removed_bytes INTEGER NOT NULL,purged_at REAL NOT NULL)''')
            old=self.db.execute('SELECT * FROM email_raw_owner_events WHERE id=?',(request['id'],)).fetchone()
            if old is not None:
                if (old['snapshot_sha256']!=request['snapshot_sha256'] or old['owner_uid']!=request['owner_uid']
                        or old['note_sha256']!=request['note_sha256']):raise Conflict('raw email purge was already recorded under another decision')
                size=0
            else:
                # At most 128 active sources precede metadata-only tombstones.
                # Active sources are ordered before bounded tombstone history.
                row=self.db.execute('SELECT * FROM email_raw_messages WHERE id=?',(request['id'],)).fetchone()
                if row is None:raise KeyError('unknown raw email receipt')
                items=self.owner_inventory(inbox,policy)['sources']
                selected=next((item for item in items if item['id']==request['id']),None)
                if selected is None:raise Conflict('refresh the bounded raw source inventory before purging')
                if selected['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('raw email state changed after owner inspection')
                if not selected['purge_allowed']:raise PermissionError('retain unresolved source; inspect and discard input before purging bytes')
                size=selected['stored_bytes']
                self.db.execute("UPDATE email_raw_messages SET data=X'' WHERE id=?",(request['id'],))
                self.db.execute('INSERT INTO email_raw_owner_events VALUES(?,?,?,?,?,?)',
                    (request['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],size,time.time()))
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return {'id':request['id'],'removed_payload_bytes':size,'tombstone_and_audit_retained':True,
            'does_not_erase_controller_agent_copies_or_backups':True}
