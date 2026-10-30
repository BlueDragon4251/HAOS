"""Durable local denial precedes one explicit bounded Google revocation POST."""
import asyncio
import math
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from .gateway import Conflict,digest
from .gateway_google_chat_oauth_tokens import TokenVault,private

REVOKE_URI='https://oauth2.googleapis.com/revoke'


async def revoke(store,policy,connector,account,request,before_io,*,http=None):
    private()
    if not callable(before_io):raise PermissionError('authenticated current private Owner capability required')
    def current():
        private();before_io()
        if policy().connectors.get(connector,{}).get('platform')!='google_chat':raise PermissionError('selected Google Chat Owner connector required')
    current();vault=TokenVault(store);local=vault.local_revoke(account,request);db=store.db
    if local['remote_revocation_verified']:
        confirmed=db.execute("SELECT receipt FROM google_chat_oauth_revocations WHERE token_id=? AND generation=? AND state='confirmed' ORDER BY created_at DESC LIMIT 1",(request['id'],request['generation'])).fetchone()
        if confirmed is None:raise Conflict('Google remote revocation has no durable confirmation receipt')
        return {**local,'receipt':confirmed['receipt'],'remote_status':'confirmed','retry_after':0}
    row,payload,_conf=vault.record(db.execute('SELECT * FROM google_chat_user_tokens WHERE id=?',(request['id'],)).fetchone(),account)
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_oauth_revocations(
        id TEXT PRIMARY KEY,token_id TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,
        created_at REAL NOT NULL,receipt TEXT NOT NULL)''')
    budget=digest([row['account_scope'],row['subject'],payload['client_id']])
    operation=digest([request,'google-remote-revocation']);old=db.execute('SELECT * FROM google_chat_oauth_revocations WHERE id=?',(operation,)).fetchone()
    def result(state,receipt='',network=False,delay=0):
        return {**local,'receipt':receipt or local['receipt'],'remote_revocation_verified':state=='confirmed',
            'remote_status':state,'network_requested':network,'retry_after':delay}
    if old is not None:
        if old['state'] not in {'writing','confirmed','rate-limited','refused','uncertain'}:raise Conflict('damaged Google revocation state')
        delay=0
        if old['state']=='rate-limited':
            wait=db.execute('SELECT not_before FROM google_chat_oauth_budget WHERE scope=?',(budget,)).fetchone()
            if wait is not None:delay=min(86400,max(0,math.ceil(wait[0]-time.time())))
        return result('uncertain' if old['state']=='writing' else old['state'],old['receipt'],delay=delay)
    db.execute('INSERT OR IGNORE INTO google_chat_oauth_budget VALUES(?,0)',(budget,))
    wait=db.execute('SELECT not_before FROM google_chat_oauth_budget WHERE scope=?',(budget,)).fetchone()[0]
    if type(wait) not in {int,float} or not math.isfinite(wait) or not 0<=wait<=253402300799:raise Conflict('damaged Google user revocation budget')
    if wait>time.time():return result('rate-limited',delay=min(86400,max(1,math.ceil(wait-time.time()))))
    if db.execute('SELECT COUNT(*) FROM google_chat_oauth_revocations').fetchone()[0]>=65536:raise Conflict('private Google revocation history full')
    current()
    # Autocommit/FULL durable intent follows the durable local withdrawal and
    # precedes the first external HTTP byte. A repeated decision cannot resend.
    db.execute('INSERT INTO google_chat_oauth_revocations VALUES(?,?,?,?,?,?)',(operation,row['id'],row['generation'],'writing',time.time(),''))
    from .gateway_google_chat_http import single_request_http
    from .redaction import Redactor
    redactor=store.inbox.redactor;redactor.secrets=Redactor([*redactor.secrets,payload['refresh_token'],payload['token'],payload['client_secret']]).secrets
    transport=http if http is not None else single_request_http(current,limit=65536,redactor=redactor,oauth_revoke=True)
    def post():
        current()
        return transport.request(REVOKE_URI,method='POST',body=urlencode({'token':payload['refresh_token']}),
            headers={'Content-Type':'application/x-www-form-urlencoded'},redirections=0)
    state='uncertain';delay=0
    try:
        response,data=await asyncio.to_thread(post);current()
        if response.status==200 and data.strip() in {b'',b'{}'}:state='confirmed'
        elif response.status==429:
            from .gateway_google_chat_retry import retry_after
            state='rate-limited';delay=retry_after(SimpleNamespace(resp=response))
        elif response.status in {400,401,403}:state='refused'
    except Exception:state='uncertain'
    receipt=digest([operation,row['id'],row['generation'],state,time.time()]);db.execute('BEGIN IMMEDIATE')
    try:
        changed=db.execute("UPDATE google_chat_oauth_revocations SET state=?,receipt=? WHERE id=? AND state='writing'",(state,receipt,operation)).rowcount
        if changed!=1:raise Conflict('Google user revocation receipt changed')
        if delay:db.execute('UPDATE google_chat_oauth_budget SET not_before=MAX(not_before,?) WHERE scope=?',(time.time()+delay,budget))
        if state=='confirmed':
            changed=db.execute("UPDATE google_chat_user_tokens SET status='revoked-remote' WHERE id=? AND generation=? AND status='revoked-local'",(row['id'],row['generation'])).rowcount
            if changed!=1:raise Conflict('Google user credentials changed during revocation')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise
    return result(state,receipt,network=True,delay=delay)
