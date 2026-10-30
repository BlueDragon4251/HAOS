"""Payload-free rejected credential inventory and one-shot explicit disposal."""
import asyncio
import json
import math
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from .gateway import Conflict,digest
from .gateway_google_chat import scope,resource
from .gateway_google_chat_oauth import HEX
from .gateway_google_chat_oauth_tokens import private,TokenVault
from .gateway_google_chat_oauth_revoke import REVOKE_URI


def checked(record,account):
    row=dict(record)
    if (any(not isinstance(row[k],str) or not HEX.fullmatch(row[k]) for k in ['id','pending_id','client_sha256','tokens_sha256','note_sha256'])
            or row['account_scope']!=scope(account) or row.get('origin','enrollment') not in {'enrollment','refresh'}
            or row['id']!=digest([row['pending_id'],row['tokens_sha256']] if row.get('origin','enrollment')=='enrollment' else ['refresh',row['pending_id'],row['tokens_sha256']])
            or row['state'] not in {'rejected','revocation-pending','revoked-remote'}
            or type(row['owner_uid']) is not int or not 0<=row['owner_uid']<2**32-1
            or type(row['created_at']) not in {int,float} or not math.isfinite(row['created_at'])):
        raise Conflict('damaged private rejected Google credential custody')
    resource(row['subject_expected'],'user')
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    tokens=json.loads(row['tokens'],object_pairs_hook=_object,parse_constant=finite)
    public=json.loads(row['public_client'],object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(public,dict) or set(public)!={'installed'} or not isinstance(public['installed'],dict)
            or set(public['installed'])!={'client_id','project_id','auth_uri','token_uri','auth_provider_x509_cert_url','redirect_uris'}):
        raise Conflict('rejected Google client metadata is not payload-free')
    from .gateway_google_chat_oauth import AUTH_URI,TOKEN_URI
    import re
    info=public['installed']
    if (info['project_id']!=account['service_account']['project_id'] or not isinstance(info['client_id'],str)
            or not re.fullmatch('[0-9]{1,32}-[A-Za-z0-9_-]{1,128}\\.apps\\.googleusercontent\\.com',info['client_id'])
            or info['auth_uri']!=AUTH_URI or info['token_uri']!=TOKEN_URI
            or info['auth_provider_x509_cert_url']!='https://www.googleapis.com/oauth2/v1/certs' or info['redirect_uris']!=['http://localhost']):
        raise Conflict('rejected Google public client differs from exact project/protocol')
    if (not isinstance(tokens,dict) or not set(tokens)<={'access_token','refresh_token'}
            or any(not isinstance(v,str) or not 1<=len(v)<=16384 or any(not 33<=ord(c)<=126 for c in v) for v in tokens.values())
            or json.dumps(tokens,sort_keys=True,separators=(',',':'))!=row['tokens']):raise Conflict('damaged rejected Google token capsule')
    if row['state']=='revoked-remote':
        if tokens:raise Conflict('confirmed rejected-token disposal retained active payload')
    elif not tokens or digest(row['tokens'])!=row['tokens_sha256']:raise Conflict('rejected Google token bytes changed')
    return row,tokens,public


def view(record,account):
    row,tokens,public=checked(record,account)
    value={k:row[k] for k in ['id','pending_id','account_scope','subject_expected','client_sha256','tokens_sha256','state','created_at']}
    value.update(origin=row.get('origin','enrollment'),public_client=public,stored_bytes=len(row['tokens'].encode()) if tokens else 0,has_refresh_token=bool(tokens.get('refresh_token')),
        actual_user_verified=False,api_use_authorized=False,remote_revocation_verified=row['state']=='revoked-remote',private_credentials_returned=False)
    return {**value,'snapshot_sha256':digest(value)}


def inventory(store,account):
    private();exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='google_chat_oauth_quarantine'").fetchone()
    rows=store.db.execute('SELECT * FROM google_chat_oauth_quarantine WHERE account_scope=? ORDER BY created_at DESC LIMIT 65',(scope(account),)).fetchall() if exists else []
    return {'quarantines':[view(row,account) for row in rows[:64]],'history_truncated':len(rows)>64,'network_requested':False,'private_credentials_returned':False}


async def dispose(store,policy,connector,account,request,before_io,*,http=None):
    private();fields={'id','snapshot_sha256','owner_uid','note_sha256','confirmed'}
    if (not isinstance(request,dict) or set(request)!=fields or request['confirmed'] is not True
            or any(not isinstance(request[k],str) or not HEX.fullmatch(request[k]) for k in ['id','snapshot_sha256','note_sha256'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1 or not callable(before_io)):
        raise PermissionError('exact inspected rejected-token Owner disposal required')
    def current():
        private();before_io()
        if policy().connectors.get(connector,{}).get('platform')!='google_chat':raise PermissionError('selected Google Owner connector required')
    current();TokenVault(store);db=store.db
    row=db.execute('SELECT * FROM google_chat_oauth_quarantine WHERE id=?',(request['id'],)).fetchone()
    if row is None:raise PermissionError('known private rejected Google credential capsule required')
    row,tokens,public=checked(row,account);snapshot=view(row,account)
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_quarantine_decisions(
        id TEXT PRIMARY KEY,quarantine_id TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,
        snapshot_sha256 TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)''')
    operation=digest([request,'rejected-google-token-disposal'])
    old=db.execute('SELECT * FROM google_chat_oauth_quarantine_decisions WHERE id=?',(operation,)).fetchone()
    def result(state,receipt='',network=False,delay=0):
        return {'id':row['id'],'receipt':receipt or operation,'remote_status':state,'remote_revocation_verified':state=='confirmed',
            'api_use_authorized':False,'network_requested':network,'message_sent':False,'retry_after':delay,'private_credentials_returned':False}
    if old is not None:return result('uncertain' if old['state']=='writing' else old['state'],old['receipt'])
    if row['state']=='revoked-remote':raise PermissionError('rejected Google credential already disposed; use its retained receipt')
    if snapshot['snapshot_sha256']!=request['snapshot_sha256']:raise Conflict('rejected Google capsule changed after Owner inspection')
    budget=digest([row['account_scope'],row['subject_expected'],public['installed']['client_id']])
    db.execute('INSERT OR IGNORE INTO google_chat_oauth_budget VALUES(?,0)',(budget,))
    wait=db.execute('SELECT not_before FROM google_chat_oauth_budget WHERE scope=?',(budget,)).fetchone()[0]
    if type(wait) not in {int,float} or not math.isfinite(wait) or not 0<=wait<=253402300799:raise Conflict('damaged rejected-token disposal budget')
    if wait>time.time():return result('rate-limited',delay=min(86400,max(1,math.ceil(wait-time.time()))))
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute('SELECT COUNT(*) FROM google_chat_oauth_quarantine_decisions').fetchone()[0]>=65536:raise Conflict('Google rejected-token disposal history full')
        db.execute('INSERT INTO google_chat_oauth_quarantine_decisions VALUES(?,?,?,?,?,?,?,?)',
            (operation,row['id'],request['owner_uid'],request['note_sha256'],request['snapshot_sha256'],'writing','',time.time()))
        db.execute("UPDATE google_chat_oauth_quarantine SET state='revocation-pending' WHERE id=?",(row['id'],));db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    from .gateway_google_chat_http import single_request_http
    from .redaction import Redactor
    redactor=store.inbox.redactor;redactor.secrets=Redactor([*redactor.secrets,*tokens.values()]).secrets
    transport=http if http is not None else single_request_http(current,limit=65536,redactor=redactor,oauth_revoke=True)
    token=tokens.get('refresh_token') or tokens['access_token']
    def post():
        current();return transport.request(REVOKE_URI,method='POST',body=urlencode({'token':token}),headers={'Content-Type':'application/x-www-form-urlencoded'},redirections=0)
    state='uncertain';delay=0
    try:
        response,data=await asyncio.to_thread(post);current()
        if response.status==200 and data.strip() in {b'',b'{}'}:state='confirmed'
        elif response.status==429:
            from .gateway_google_chat_retry import retry_after
            state='rate-limited';delay=retry_after(SimpleNamespace(resp=response))
        elif response.status in {400,401,403}:state='refused'
    except Exception:pass
    receipt=digest([operation,state,time.time()]);db.execute('BEGIN IMMEDIATE')
    try:
        changed=db.execute("UPDATE google_chat_oauth_quarantine_decisions SET state=?,receipt=? WHERE id=? AND state='writing'",(state,receipt,operation)).rowcount
        if changed!=1:raise Conflict('Google rejected-token disposal receipt changed')
        if delay:db.execute('UPDATE google_chat_oauth_budget SET not_before=MAX(not_before,?) WHERE scope=?',(time.time()+delay,budget))
        if state=='confirmed':db.execute("UPDATE google_chat_oauth_quarantine SET state='revoked-remote',tokens='{}' WHERE id=?",(row['id'],))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return result(state,receipt,True,delay)
