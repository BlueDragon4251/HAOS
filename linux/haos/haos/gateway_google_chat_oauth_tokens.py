"""Private user token selection, persistent refresh fences and local withdrawal.

No method sends a request or returns credentials through an Owner/Agent IPC.
Only the isolated SDK caller may consume the internal load snapshot.
"""
import json
import math
import secrets
import time

from .gateway import Conflict,digest
from .gateway_google_chat import scope,credentials,resource
from .gateway_google_chat_oauth import client,route,validate_token,AUTH_URI,TOKEN_URI,HEX


def private():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()


def configuration(payload,account):
    return client({'installed':{'client_id':payload['client_id'],'client_secret':payload['client_secret'],
        'project_id':account['service_account']['project_id'],'auth_uri':AUTH_URI,'token_uri':TOKEN_URI,
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','redirect_uris':['http://localhost']}},account)


class Deferred(PermissionError):
    def __init__(self,status,retry_after=0):
        self.status=status;self.retry_after=retry_after
        super().__init__('private Google user credential operation requires inspected recovery or waiting')


class TokenVault:
    def __init__(self,store):
        private();self.store=store;self.db=store.db
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='google_chat_user_tokens'").fetchone():
            if 'public_client' not in {field[1] for field in self.db.execute('PRAGMA table_info(google_chat_user_tokens)')}:
                self.db.execute("ALTER TABLE google_chat_user_tokens ADD COLUMN public_client TEXT NOT NULL DEFAULT '{}'")
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_transport(
            token_id TEXT PRIMARY KEY,generation INTEGER NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_budget(scope TEXT PRIMARY KEY,not_before REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_refreshes(
            id TEXT PRIMARY KEY,token_id TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,
            created_at REAL NOT NULL,receipt TEXT NOT NULL)''')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS google_chat_one_user_refresh ON google_chat_oauth_refreshes(token_id) WHERE state='writing'")
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_token_owner_events(
            receipt TEXT PRIMARY KEY,token_id TEXT NOT NULL,generation INTEGER NOT NULL,event TEXT NOT NULL,
            owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')

    def record(self,record,account):
        private();row=dict(record);account=credentials(account)
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        payload=json.loads(row['credential'],object_pairs_hook=_object,parse_constant=finite)
        conf=configuration(payload,account);validate_token(payload,conf,legacy_for_disposal=True)
        if (row['account_scope']!=scope(account) or row['client_sha256']!=digest(conf)
                or row['id']!=digest([row['account_scope'],row['subject'],row['client_sha256']])
                or row['credential']!=json.dumps(payload,sort_keys=True,separators=(',',':'))
                or type(row['generation']) is not int or not 1<=row['generation']<2**53
                or row['status'] not in {'active','superseded','revoked-local','revoked-remote'}
                or any(not isinstance(row[k],str) or not HEX.fullmatch(row[k]) for k in ['binding_digest','nonce_sha256','pending_id'])):
            raise Conflict('private Google user token custody damaged')
        resource(row['subject'],'user')
        public=json.dumps({'installed':{key:value for key,value in conf['installed'].items() if key!='client_secret'}},sort_keys=True,separators=(',',':'))
        if row['public_client']=='{}':
            # Recover only metadata uniquely anchored by the pre-existing
            # client hash and exact current account, preserving old credentials.
            self.db.execute('UPDATE google_chat_user_tokens SET public_client=? WHERE id=? AND public_client=?',(public,row['id'],'{}'))
            row['public_client']=public
        elif row['public_client']!=public:raise Conflict('Google user public client metadata differs from retained client hash')
        return row,payload,conf

    def load(self,policy,connector,account,selected):
        private()
        if not isinstance(selected,dict) or set(selected)!={'binding_id','binding_digest'}:raise PermissionError('exact current user reply/file route required')
        binding=route(policy,connector,account,selected['binding_id'],selected['binding_digest'])
        exists=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_user_tokens' AND type='table'").fetchone()
        rows=self.db.execute("SELECT * FROM google_chat_user_tokens WHERE account_scope=? AND subject=? AND status='active' LIMIT 2",
            (scope(account),binding['sender'])).fetchall() if exists else []
        if not rows:raise Deferred('user-auth-required')
        if len(rows)!=1:raise Conflict('multiple active Google user OAuth identities')
        row,payload,conf=self.record(rows[0],account)
        from .gateway_google_chat_oauth import SCOPES
        if set(payload['scopes'])!=set(SCOPES):raise Deferred('user-reauth-scope-required')
        budget=digest([row['account_scope'],row['subject'],payload['client_id']]);db=self.db
        db.execute('INSERT OR IGNORE INTO google_chat_oauth_budget VALUES(?,0)',(budget,))
        state=db.execute('SELECT * FROM google_chat_oauth_transport WHERE token_id=?',(row['id'],)).fetchone()
        if state is not None and (type(state['generation']) is not int or not 1<=state['generation']<=row['generation']
                or state['status'] not in {'ready','refreshing','rate-limited','authentication-refused','refresh-uncertain','revoked-local'}):
            raise Conflict('private Google user transport generation or state damaged')
        if state is None:
            db.execute('INSERT INTO google_chat_oauth_transport VALUES(?,?,?,?)',(row['id'],row['generation'],'ready',time.time()))
        elif state['generation']!=row['generation']:
            # A newly verified enrollment may clear an auth block. It never
            # changes the separate stable-account/client rate deadline.
            db.execute("UPDATE google_chat_oauth_transport SET generation=?,status='ready',updated_at=? WHERE token_id=?",
                (row['generation'],time.time(),row['id']))
        status=db.execute('SELECT status FROM google_chat_oauth_transport WHERE token_id=?',(row['id'],)).fetchone()[0]
        not_before=db.execute('SELECT not_before FROM google_chat_oauth_budget WHERE scope=?',(budget,)).fetchone()[0]
        if (type(not_before) not in {int,float} or not math.isfinite(not_before) or not 0<=not_before<=253402300799
                or status not in {'ready','refreshing','rate-limited','authentication-refused','refresh-uncertain','revoked-local'}):
            raise Conflict('private Google user auth/rate state damaged')
        if status in {'authentication-refused','refresh-uncertain','refreshing','revoked-local'}:raise Deferred(status)
        if not_before>time.time():raise Deferred('rate-limited',min(86400,max(1,math.ceil(not_before-time.time()))))
        return {'row':row,'payload':payload,'configuration':conf,'budget':budget,'route':dict(selected)}

    def begin_refresh(self,snapshot):
        private();db=self.db;row=snapshot['row'];db.execute('BEGIN IMMEDIATE')
        try:
            current=db.execute('SELECT status,generation FROM google_chat_user_tokens WHERE id=?',(row['id'],)).fetchone()
            if current is None or current['status']!='active' or current['generation']!=row['generation']:
                raise PermissionError('Google user token changed before refresh')
            if db.execute("SELECT 1 FROM google_chat_oauth_refreshes WHERE token_id=? AND state='writing'",(row['id'],)).fetchone():
                raise Deferred('refresh-uncertain')
            if db.execute('SELECT COUNT(*) FROM google_chat_oauth_refreshes').fetchone()[0]>=65536:raise Conflict('private Google refresh history full')
            if db.execute('SELECT not_before FROM google_chat_oauth_budget WHERE scope=?',(snapshot['budget'],)).fetchone()[0]>time.time():
                raise Deferred('rate-limited')
            identity=digest([row['id'],row['generation'],secrets.token_hex(32)])
            db.execute('INSERT INTO google_chat_oauth_refreshes VALUES(?,?,?,?,?,?)',(identity,row['id'],row['generation'],'writing',time.time(),''))
            db.execute("UPDATE google_chat_oauth_transport SET status='refreshing',updated_at=? WHERE token_id=?",(time.time(),row['id']))
            db.execute('COMMIT');return identity
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def failed_refresh(self,snapshot,identity,status,*,retry_after=0):
        private()
        if status not in {'rate-limited','authentication-refused','refresh-uncertain'} or type(retry_after) is not int or not 0<=retry_after<=86400:
            raise ValueError('finite Google user refresh recovery category required')
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            changed=db.execute("UPDATE google_chat_oauth_refreshes SET state=? WHERE id=? AND token_id=? AND generation=? AND state='writing'",
                (status,identity,snapshot['row']['id'],snapshot['row']['generation'])).rowcount
            if changed!=1:raise Conflict('private Google refresh intent changed')
            db.execute('UPDATE google_chat_oauth_budget SET not_before=MAX(not_before,?) WHERE scope=?',
                (time.time()+retry_after if retry_after else 0,snapshot['budget']))
            db.execute("UPDATE google_chat_oauth_transport SET status=?,updated_at=? WHERE token_id=? AND generation=? AND status!='revoked-local'",
                (status,time.time(),snapshot['row']['id'],snapshot['row']['generation']))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def local_revoke(self,account,request):
        private();fields={'id','generation','owner_uid','note_sha256','confirmed'}
        if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True
                or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','note_sha256'])
                or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
                or type(request['generation']) is not int or not 1<=request['generation']<2**53):
            raise PermissionError('exact confirmed Owner user-token withdrawal required')
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            record=db.execute('SELECT * FROM google_chat_user_tokens WHERE id=?',(request['id'],)).fetchone()
            if record is None:raise PermissionError('known private user token required')
            row,_payload,_conf=self.record(record,account)
            if row['generation']!=request['generation']:raise Conflict('Google user token changed after Owner inspection')
            receipt=digest([request,'revoked-local'])
            old=db.execute('SELECT * FROM google_chat_oauth_token_owner_events WHERE receipt=?',(receipt,)).fetchone()
            if old is None:
                if row['status']!='revoked-remote':db.execute("UPDATE google_chat_user_tokens SET status='revoked-local' WHERE id=?",(row['id'],))
                db.execute("UPDATE google_chat_oauth_transport SET status='revoked-local',updated_at=? WHERE token_id=?",(time.time(),row['id']))
                db.execute('INSERT INTO google_chat_oauth_token_owner_events VALUES(?,?,?,?,?,?,?)',
                    (receipt,row['id'],row['generation'],'revoked-local',request['owner_uid'],request['note_sha256'],time.time()))
            db.execute('COMMIT');return {'id':row['id'],'receipt':receipt,'locally_revoked':True,'remote_revocation_verified':row['status']=='revoked-remote',
                'network_requested':False,'message_sent':False,'private_credentials_returned':False}
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def finish_refresh(self,snapshot,identity,verified):
        private()
        from .gateway_google_chat_oauth_sdk import _checked_grant
        verified=_checked_grant(verified);row=snapshot['row']
        if verified.pending_id!=identity or verified.subject!=row['subject'] or verified.nonce_sha256!=row['nonce_sha256']:
            raise PermissionError('actual SDK refresh differs from retained stable user or operation')
        payload=json.loads(verified.credential_json);validate_token(payload,snapshot['configuration'])
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            current=db.execute('SELECT * FROM google_chat_user_tokens WHERE id=?',(row['id'],)).fetchone()
            if current is None or current['status']!='active' or current['generation']!=row['generation'] or current['credential']!=row['credential']:
                raise PermissionError('Google user credentials changed or were withdrawn during refresh')
            intent=db.execute('SELECT * FROM google_chat_oauth_refreshes WHERE id=?',(identity,)).fetchone()
            if intent is None or intent['token_id']!=row['id'] or intent['generation']!=row['generation'] or intent['state']!='writing':
                raise Conflict('Google user refresh has no current durable intent')
            now=time.time();generation=row['generation']+1
            if generation>=2**53:raise Conflict('Google user credential generation exhausted')
            receipt=digest([identity,row['id'],generation,digest(verified.credential_json),now])
            db.execute('UPDATE google_chat_user_tokens SET credential=?,generation=?,updated_at=? WHERE id=?',
                (verified.credential_json,generation,now,row['id']))
            db.execute("UPDATE google_chat_oauth_refreshes SET state='confirmed',receipt=? WHERE id=?",(receipt,identity))
            db.execute("UPDATE google_chat_oauth_transport SET generation=?,status='ready',updated_at=? WHERE token_id=?",
                (generation,now,row['id']))
            # Never reset the independent account/client not-before deadline.
            db.execute('COMMIT');return {'id':row['id'],'generation':generation,'receipt':receipt,'private_credentials_returned':False}
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def inventory(self,policy,connector,account):
        private()
        if policy.connectors.get(connector,{}).get('platform')!='google_chat':raise PermissionError('selected private Google Owner connector required')
        exists=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='google_chat_user_tokens'").fetchone()
        rows=self.db.execute('SELECT * FROM google_chat_user_tokens WHERE account_scope=? ORDER BY updated_at DESC LIMIT 129',(scope(account),)).fetchall() if exists else []
        from .gateway_google_chat_oauth import SCOPES
        values=[]
        for record in rows[:128]:
            row,payload,_conf=self.record(record,account)
            state=self.db.execute('SELECT status FROM google_chat_oauth_transport WHERE token_id=?',(row['id'],)).fetchone()
            budget=digest([row['account_scope'],row['subject'],payload['client_id']]);deadline=self.db.execute('SELECT not_before FROM google_chat_oauth_budget WHERE scope=?',(budget,)).fetchone()
            wait=deadline[0] if deadline is not None else 0
            if type(wait) not in {int,float} or not math.isfinite(wait) or not 0<=wait<=253402300799:raise Conflict('damaged private user token budget')
            value={key:row[key] for key in ['id','account_scope','subject','client_sha256','status','updated_at','generation']}
            value.update(public_client=json.loads(row['public_client']),transport_status=state['status'] if state is not None else 'ready',next_attempt=wait,
                scopes=list(payload['scopes']),scope_upgrade_required=set(payload['scopes'])!=set(SCOPES),
                current_file_grants=sum(binding['connector']==connector and binding['scope']==row['account_scope'] and binding['sender']==row['subject']
                    and 'read' in binding['capabilities'] and binding.get('allow_outbound_media') is True for binding in policy.bindings.values()),
                private_credentials_returned=False)
            values.append({**value,'snapshot_sha256':digest(value)})
        return {'tokens':values,'history_truncated':len(rows)>128,'network_requested':False,'private_credentials_returned':False}
