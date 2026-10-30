"""Prepared private PKCE custody and stable-subject checks; no network client."""
import hmac
import json
import math
import re
import secrets
import time
from urllib.parse import urlsplit,parse_qs

from .gateway import Conflict,digest
from .gateway_google_chat import credentials,scope,resource

CHAT_SCOPE='https://www.googleapis.com/auth/chat.messages.create'
SCOPES=(CHAT_SCOPE,'openid')
AUTH_URI='https://accounts.google.com/o/oauth2/auth'
TOKEN_URI='https://oauth2.googleapis.com/token'
REDIRECT_URI='http://localhost:1'
HEX=re.compile('[a-f0-9]{64}\\Z')
OPAQUE=re.compile('[A-Za-z0-9_-]{43,128}\\Z')


def client(value,account):
    account=credentials(account)
    if not isinstance(value,dict) or set(value)!={'installed'}:raise ValueError('dedicated installed Google OAuth client JSON required')
    data=value['installed'];fields={'client_id','project_id','auth_uri','token_uri','auth_provider_x509_cert_url','client_secret','redirect_uris'}
    if (not isinstance(data,dict) or set(data)!=fields or data['project_id']!=account['service_account']['project_id']
            or not isinstance(data['client_id'],str) or not re.fullmatch('[0-9]{1,32}-[A-Za-z0-9_-]{1,128}\\.apps\\.googleusercontent\\.com',data['client_id'])
            or data['auth_uri']!=AUTH_URI or data['token_uri']!=TOKEN_URI
            or data['auth_provider_x509_cert_url']!='https://www.googleapis.com/oauth2/v1/certs'
            or data['redirect_uris']!=['http://localhost'] or not isinstance(data['client_secret'],str)
            or not 1<=len(data['client_secret'])<=4096 or any(not 33<=ord(c)<=126 for c in data['client_secret'])):
        raise ValueError('same-project desktop OAuth client with fixed Google endpoints and loopback redirect required')
    return {'installed':{**data,'redirect_uris':list(data['redirect_uris'])}}


def route(policy,connector,account,binding_id,binding_digest):
    account=credentials(account);binding=policy.current_binding({'binding_id':binding_id,'binding_digest':binding_digest})
    if (policy.connectors.get(connector,{}).get('platform')!='google_chat' or binding['connector']!=connector
            or binding['scope']!=scope(account) or binding['sender']==account['bot_user']
            or 'read' not in binding['capabilities'] or binding.get('allow_outbound_media') is not True):
        raise PermissionError('exact current Google Chat user and explicit reply/read/file-output grant required')
    resource(binding['sender'],'user');return binding


def callback(value,state):
    if (not isinstance(value,str) or not 1<=len(value)<=8192 or any(not 33<=ord(c)<=126 for c in value)
            or not isinstance(state,str) or not OPAQUE.fullmatch(state)):
        raise PermissionError('complete inspected loopback callback URL and pending OAuth state required')
    parsed=urlsplit(value)
    if (parsed.scheme!='http' or parsed.netloc!='localhost:1' or parsed.path not in {'','/'} or parsed.fragment
            or parsed.username is not None or parsed.password is not None):raise PermissionError('fixed native loopback OAuth callback required')
    try:params=parse_qs(parsed.query,strict_parsing=True,max_num_fields=8,keep_blank_values=True)
    except ValueError:raise PermissionError('bounded OAuth callback required') from None
    if (not {'code','state'}<=set(params)<={'code','state','scope','authuser','prompt','hd'} or any(len(values)!=1 for values in params.values())
            or not OPAQUE.fullmatch(params['state'][0]) or not hmac.compare_digest(params['state'][0],state) or not 1<=len(params['code'][0])<=4096
            or any(not 33<=ord(c)<=126 for c in params['code'][0])):raise PermissionError('OAuth callback state or code is invalid')
    return params['code'][0]


class OAuthStore:
    def __init__(self,inbox):
        self.inbox=inbox;self.db=inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_pending(
            id TEXT PRIMARY KEY,connector TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
            account_scope TEXT NOT NULL,credential_scope TEXT NOT NULL,client_sha256 TEXT NOT NULL,client TEXT NOT NULL,
            subject TEXT NOT NULL,state TEXT NOT NULL,nonce TEXT NOT NULL,verifier TEXT NOT NULL,status TEXT NOT NULL,
            created_at REAL NOT NULL,expires_at REAL NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_events(
            receipt TEXT PRIMARY KEY,pending_id TEXT NOT NULL,event TEXT NOT NULL,owner_uid INTEGER NOT NULL,
            note_sha256 TEXT NOT NULL,created_at REAL NOT NULL)''')

    def _current(self,row,policy,connector,account):
        account=credentials(account)
        if (row['connector']!=connector or row['account_scope']!=scope(account) or row['credential_scope']!=digest(account)
                or row['client_sha256']!=digest(client(json.loads(row['client']),account))):
            raise PermissionError('OAuth account or private client changed')
        binding=route(policy,connector,account,row['binding_id'],row['binding_digest'])
        if binding['sender']!=row['subject']:raise PermissionError('OAuth stable Google user changed')
        if any(not isinstance(row[k],str) or not OPAQUE.fullmatch(row[k]) for k in ['state','nonce','verifier']):
            raise Conflict('damaged private PKCE custody')
        if (row['id']!=digest([connector,row['account_scope'],row['subject'],row['state']])
                or any(type(row[k]) not in {int,float} or not math.isfinite(row[k]) for k in ['created_at','expires_at'])
                or not 0<row['created_at']<=time.time()+60 or not row['created_at']<row['expires_at']<=row['created_at']+600):raise Conflict('damaged private OAuth lifetime or identity')
        return binding

    def begin(self,policy,connector,account,configuration,binding_id,binding_digest,*,owner_uid,note_sha256,confirmed):
        if (confirmed is not True or type(owner_uid) is not int or not 0<=owner_uid<2**32-1
                or not isinstance(note_sha256,str) or not HEX.fullmatch(note_sha256)):
            raise PermissionError('explicit authenticated Owner OAuth enrollment required')
        configuration=client(configuration,account);binding=route(policy,connector,account,binding_id,binding_digest)
        state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
        identity=digest([connector,scope(account),binding['sender'],state]);now=time.time();db=self.db
        db.execute('BEGIN IMMEDIATE')
        try:
            count=db.execute('SELECT COUNT(*) FROM google_chat_oauth_pending').fetchone()[0]
            live=db.execute("SELECT COUNT(*) FROM google_chat_oauth_pending WHERE status IN ('awaiting','exchanging') AND expires_at>?",(now,)).fetchone()[0]
            size=db.execute('SELECT COALESCE(SUM(length(client)+length(state)+length(nonce)+length(verifier)),0) FROM google_chat_oauth_pending').fetchone()[0]
            if count>=65536 or live>=32 or size+len(json.dumps(configuration).encode())+1024>8*1024*1024:
                raise Conflict('private Google OAuth enrollment capacity reached')
            db.execute('INSERT INTO google_chat_oauth_pending VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,connector,binding_id,binding_digest,scope(account),digest(account),digest(configuration),
                    json.dumps(configuration,sort_keys=True,separators=(',',':')),binding['sender'],state,nonce,verifier,'awaiting',now,now+600,owner_uid,note_sha256))
            receipt=digest([identity,'begun',owner_uid,note_sha256,now]);db.execute('INSERT INTO google_chat_oauth_events VALUES(?,?,?,?,?,?)',
                (receipt,identity,'begun',owner_uid,note_sha256,now));db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        # Private result for the isolated SDK signer only, never a Root/Agent
        # inventory response. Owner UI gets a separately validated auth URL.
        return dict(db.execute('SELECT * FROM google_chat_oauth_pending WHERE id=?',(identity,)).fetchone())

    def exchange(self,policy,connector,account,identity,returned_url,*,owner_uid):
        if not isinstance(identity,str) or not HEX.fullmatch(identity) or type(owner_uid) is not int:
            raise PermissionError('exact current Owner OAuth session required')
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            row=db.execute('SELECT * FROM google_chat_oauth_pending WHERE id=?',(identity,)).fetchone()
            if row is None:raise PermissionError('unknown private Google OAuth session')
            if row['owner_uid']!=owner_uid or row['status']!='awaiting' or time.time()>=row['expires_at']:
                raise PermissionError('OAuth session is expired, already begun or belongs to another Owner')
            self._current(row,policy,connector,account)
            code=callback(returned_url,row['state'])
            changed=db.execute("UPDATE google_chat_oauth_pending SET status='exchanging' WHERE id=? AND status='awaiting'",(identity,)).rowcount
            if changed!=1:raise Conflict('Google OAuth exchange changed before its durable intent')
            receipt=digest([identity,'exchanging',owner_uid,row['note_sha256'],time.time()]);db.execute('INSERT INTO google_chat_oauth_events VALUES(?,?,?,?,?,?)',
                (receipt,identity,'exchanging',owner_uid,row['note_sha256'],time.time()));db.execute('COMMIT')
            return dict(row),code
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def identity(self,row,claims):
        """Post-SDK claim constraints; the caller must verify the JWT signature."""
        configuration=json.loads(row['client'])['installed']
        if (not isinstance(claims,dict) or not isinstance(claims.get('iss'),str) or claims.get('iss') not in {'accounts.google.com','https://accounts.google.com'}
                or claims.get('aud')!=configuration['client_id'] or claims.get('azp',configuration['client_id'])!=configuration['client_id']
                or not isinstance(claims.get('nonce'),str) or not OPAQUE.fullmatch(claims['nonce']) or not hmac.compare_digest(claims['nonce'],row['nonce'])
                or not isinstance(claims.get('sub'),str) or not re.fullmatch('[0-9]{1,32}',claims['sub'])
                or 'users/'+claims['sub']!=row['subject'] or type(claims.get('iat')) is not int or type(claims.get('exp')) is not int
                or not 0<claims['exp']-claims['iat']<=7200 or claims['iat']>time.time()+60 or claims['exp']<=time.time()):
            raise PermissionError('verified Google OAuth token differs from the approved stable user, nonce or client')
        return row['subject']

    def inventory(self):
        rows=self.db.execute('SELECT id,connector,binding_id,binding_digest,account_scope,client_sha256,subject,status,created_at,expires_at FROM google_chat_oauth_pending ORDER BY created_at DESC LIMIT 65').fetchall()
        allowed={'awaiting','exchanging','complete','refused','uncertain','cancelled'};items=[]
        for record in rows[:64]:
            row=dict(record)
            if row['status'] not in allowed:raise Conflict('damaged private OAuth enrollment status')
            resource(row['subject'],'user');items.append(row)
        return {'sessions':items,'history_truncated':len(rows)>64,'network_requested':False,'private_bytes_returned':False}


    def complete(self,policy,connector,account,identity,verified,*,owner_uid):
        from .gateway_google_chat_oauth_sdk import _checked_grant
        verified=_checked_grant(verified)
        if verified.pending_id!=identity or type(owner_uid) is not int:raise PermissionError('exact verified current Owner OAuth session required')
        db=self.db;db.execute('BEGIN IMMEDIATE')
        try:
            row=db.execute('SELECT * FROM google_chat_oauth_pending WHERE id=?',(identity,)).fetchone()
            if row is None or row['status']!='exchanging' or row['owner_uid']!=owner_uid or time.time()>=row['expires_at']:
                raise PermissionError('OAuth verified exchange is stale or belongs to another Owner')
            self._current(row,policy,connector,account)
            import hashlib
            if verified.subject!=row['subject'] or verified.nonce_sha256!=hashlib.sha256(row['nonce'].encode()).hexdigest():
                raise PermissionError('Google SDK grant differs from retained stable user and nonce')
            payload=json.loads(verified.credential_json);configuration=json.loads(row['client'])
            validate_token(payload,configuration)
            db.execute("""CREATE TABLE IF NOT EXISTS google_chat_user_tokens(
                id TEXT PRIMARY KEY,account_scope TEXT NOT NULL,subject TEXT NOT NULL,client_sha256 TEXT NOT NULL,
                credential TEXT NOT NULL,status TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
                nonce_sha256 TEXT NOT NULL,updated_at REAL NOT NULL,generation INTEGER NOT NULL,pending_id TEXT NOT NULL)""")
            token_id=digest([row['account_scope'],row['subject'],row['client_sha256']])
            previous=db.execute('SELECT generation,length(credential) AS size FROM google_chat_user_tokens WHERE id=?',(token_id,)).fetchone()
            count,size=db.execute('SELECT COUNT(*),COALESCE(SUM(length(credential)),0) FROM google_chat_user_tokens').fetchone()
            if count>=128 and previous is None or size-(previous['size'] if previous else 0)+len(verified.credential_json.encode())>8*1024*1024:
                raise Conflict('private Google OAuth user/token capacity reached')
            if previous is not None and (type(previous['generation']) is not int or not 1<=previous['generation']<2**53):
                raise Conflict('private Google OAuth token generation damaged')
            generation=previous['generation']+1 if previous else 1
            if type(generation) is not int or not 1<=generation<2**53:raise Conflict('private Google OAuth token generation damaged')
            # Keep old private credentials for an explicit remote revocation,
            # but immediately stop selecting them for new native operations.
            db.execute("UPDATE google_chat_user_tokens SET status='superseded' WHERE account_scope=? AND subject=? AND id!=? AND status='active'",
                (row['account_scope'],row['subject'],token_id))
            now=time.time()
            db.execute('INSERT OR REPLACE INTO google_chat_user_tokens VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (token_id,row['account_scope'],row['subject'],row['client_sha256'],verified.credential_json,'active',row['binding_id'],row['binding_digest'],verified.nonce_sha256,now,generation,identity))
            receipt=digest([identity,token_id,'complete',owner_uid,row['note_sha256'],generation,now])
            db.execute('INSERT INTO google_chat_oauth_events VALUES(?,?,?,?,?,?)',(receipt,identity,'complete',owner_uid,row['note_sha256'],now))
            db.execute("UPDATE google_chat_oauth_pending SET status='complete',client='',state='',nonce='',verifier='' WHERE id=?",(identity,))
            db.execute('COMMIT')
            return {'id':token_id,'subject':verified.subject,'status':'active','generation':generation,'receipt':receipt,
                'network_requested':False,'message_sent':False,'private_credentials_returned':False}
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise


def validate_token(value,configuration):
    from datetime import datetime
    fields={'token','refresh_token','token_uri','client_id','client_secret','scopes','expiry','universe_domain','account'}
    if (not isinstance(value,dict) or not fields<=set(value)<=fields|{'rapt_token'} or value['token_uri']!=TOKEN_URI
            or value['client_id']!=configuration['installed']['client_id'] or value['client_secret']!=configuration['installed']['client_secret']
            or not isinstance(value['scopes'],(list,tuple)) or any(not isinstance(v,str) for v in value['scopes'])
            or len(value['scopes'])!=len(SCOPES) or set(value['scopes'])!=set(SCOPES)
            or value['universe_domain']!='googleapis.com' or not isinstance(value['account'],str) or len(value['account'])>320):
        raise PermissionError('exact dedicated Google Chat/OpenID user credentials required')
    for key in ['token','refresh_token','client_secret',*(['rapt_token'] if 'rapt_token' in value else [])]:
        if not isinstance(value[key],str) or not 1<=len(value[key])<=16384 or any(not 33<=ord(c)<=126 for c in value[key]):
            raise ValueError('bounded private Google token material required')
    if not isinstance(value['expiry'],str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z',value['expiry']):
        raise ValueError('exact private Google access-token expiry required')
    expires=datetime.fromisoformat(value['expiry'][:-1]+'+00:00').timestamp()
    if not 0<expires<=time.time()+86460:raise ValueError('bounded private Google access-token expiry required')
    if len(json.dumps(value).encode())>65536:raise ValueError('bounded private Google credential record required')
    return value
