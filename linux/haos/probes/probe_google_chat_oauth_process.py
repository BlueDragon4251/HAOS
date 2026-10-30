"""Actual private UID Google OAuth SDK/PKCE/RSA fixtures; no live account."""
import asyncio
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_OAUTH_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh readonly disposable OAuth namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    prepared=Path('/repo/upstream/hermes-agent');assert (prepared/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    staged=Path(tempfile.mkdtemp(prefix='haos-google-oauth-source-'))
    shutil.copytree(prepared,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py',str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/deps',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from google.auth import crypt,jwt
    from haos.gateway_google_chat import scope
    from haos.gateway_google_chat_oauth import SCOPES,REDIRECT_URI
    from haos.gateway import digest
    now=datetime.datetime.now(datetime.timezone.utc);directory=Path(tempfile.mkdtemp(prefix='haos-google-oauth-'));directory.chmod(0o755)
    private=directory/'private';private.mkdir(mode=0o700);os.chown(private,65534,65534)
    canary=directory/'owner-data';canary.write_text('private Owner fixture canary');canary.chmod(0o600)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False).sign(key,hashes.SHA256())
    cert_file=directory/'cert.pem';cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM));cert_file.chmod(0o644)
    key_file=directory/'key.pem';key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_file.chmod(0o600)
    signing=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    signing_bytes=signing.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    signer=crypt.RSASigner.from_string(signing_bytes,key_id='local-google-user')
    signing_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'local-google-user')])
    signing_cert=x509.CertificateBuilder().subject_name(signing_name).issuer_name(signing_name).public_key(signing.public_key()).serial_number(1).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).sign(signing,hashes.SHA256())
    public=signing_cert.public_bytes(serialization.Encoding.PEM).decode()
    email='gateway@haos-fixture.iam.gserviceaccount.com'
    account={'service_account':{'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n','client_email':email,'client_id':'123456789',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},
        'bot_user':'users/999','inbound':{'mode':'pubsub','subscription':'projects/haos-fixture/subscriptions/haos-private'}}
    client={'installed':{'client_id':'123456789-private-fixture.apps.googleusercontent.com','project_id':'haos-fixture',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','client_secret':'private-client-fixture-not-a-real-secret','redirect_uris':['http://localhost']}}
    binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
        'scope':scope(account),'identity':'personal','capabilities':['read'],'allow_outbound_media':True,'generation':'a'*64,'since':int(now.timestamp()*1000)-60000}
    policy={'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]}
    public_authorizations={};requests=[];refresh_control={'mode':None};revoke_control={'mode':None}
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path=='/revoke':
                scene=revoke_control['mode'];assert scene in {'ok','refused','rate','disconnect','redirect','body','audit','quarantine'}
                values=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode(),strict_parsing=True)
                assert values in [{'token':[value]} for value in ['local-user-refresh-fixture','local-user-access-fixture','refreshed-user-refresh-fixture','refreshed-user-access-fixture']] and not self.headers.get('Authorization')
                import sqlite3
                with sqlite3.connect(private/'oauth.sqlite') as db:
                    if scene=='quarantine':
                        assert db.execute("SELECT COUNT(*) FROM google_chat_oauth_quarantine_decisions WHERE state='writing'").fetchone()[0]==1
                        assert db.execute("SELECT COUNT(*) FROM google_chat_oauth_quarantine WHERE state='revocation-pending'").fetchone()[0]==1
                    else:
                        assert db.execute('SELECT status FROM google_chat_user_tokens').fetchone()[0]=='revoked-local'
                        assert db.execute("SELECT COUNT(*) FROM google_chat_oauth_revocations WHERE state='writing'").fetchone()[0]==1
                requests.append('revoke-'+scene)
                if scene=='disconnect':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                if scene=='redirect':
                    self.send_response(307);self.send_header('Location','https://foreign.invalid/revoke');self.send_header('Content-Length','0');self.end_headers();return
                status=400 if scene=='refused' else 429 if scene=='rate' else 200
                body=b'{}' if scene in {'ok','audit','quarantine'} else b'foreign response is not a revocation receipt' if scene=='body' else b'{"error":"invalid_token"}'
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                if scene=='rate':self.send_header('Retry-After','180')
                self.end_headers();self.wfile.write(body);return
            assert self.path=='/token'
            values=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode(),strict_parsing=True)
            if values['grant_type']==['refresh_token']:
                scene=refresh_control['mode'];assert scene in {'ok','no-id-token','subject','nonce','partial-scope','auth','rate','disconnect','audit'}
                assert values['refresh_token']==['local-user-refresh-fixture'] and values['client_id']==[client['installed']['client_id']]
                assert values['client_secret']==[client['installed']['client_secret']] and set(values['scope'][0].split())==set(SCOPES)
                import sqlite3
                with sqlite3.connect(private/'oauth.sqlite') as db:
                    assert db.execute("SELECT COUNT(*) FROM google_chat_oauth_refreshes WHERE state='writing'").fetchone()[0]==1
                    assert db.execute('SELECT status FROM google_chat_oauth_transport').fetchone()[0]=='refreshing'
                requests.append('refresh-'+scene)
                if scene=='disconnect':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                claims={'iss':'https://accounts.google.com','aud':client['installed']['client_id'],'sub':'124' if scene=='subject' else '123',
                    'nonce':'b'*43 if scene=='nonce' else public_authorizations['ok']['nonce'][0],'iat':int(now.timestamp()),'exp':int(now.timestamp())+3600}
                payload={'access_token':'refreshed-user-access-fixture','refresh_token':'refreshed-user-refresh-fixture','token_type':'Bearer','expires_in':3600,
                    'scope':' '.join(SCOPES),'id_token':jwt.encode(signer,claims).decode()}
                if scene=='no-id-token':payload.pop('id_token');payload.pop('refresh_token')
                if scene=='partial-scope':payload['scope']=SCOPES[0]
                status=200
                if scene=='auth':status=400;payload={'error':'invalid_grant'}
                if scene=='rate':status=429;payload={'error':'rate_limit_exceeded'}
                body=json.dumps(payload).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                if scene=='rate':self.send_header('Retry-After','180')
                self.end_headers();self.wfile.write(body);return
            assert values['grant_type']==['authorization_code'] and values['redirect_uri']==[REDIRECT_URI]
            assert values['client_id']==[client['installed']['client_id']] and values['client_secret']==[client['installed']['client_secret']]
            scene=values['code'][0].removeprefix('local-code-');entry=public_authorizations[scene]
            import base64
            challenge=base64.urlsafe_b64encode(hashlib.sha256(values['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
            assert entry['code_challenge']==[challenge]
            import sqlite3
            with sqlite3.connect(private/'oauth.sqlite') as db:
                row=db.execute('SELECT status FROM google_chat_oauth_pending WHERE state=?',(entry['state'][0],)).fetchone()
                assert row==('exchanging',)
            requests.append(scene)
            claims={'iss':'https://accounts.google.com','aud':client['installed']['client_id'],'sub':'123','nonce':entry['nonce'][0],
                'iat':int(now.timestamp()),'exp':int(now.timestamp())+3600}
            if scene=='subject':claims['sub']='124'
            if scene=='nonce':claims['nonce']='b'*43
            if scene=='audience':claims['aud']='other-client'
            signed=jwt.encode(signer,claims).decode()
            if scene=='signature':signed=signed[:-12]+'A'*12
            token={'access_token':'local-user-access-fixture','refresh_token':'local-user-refresh-fixture','token_type':'Bearer',
                'expires_in':3600,'scope':' '.join(SCOPES),'id_token':signed}
            if scene=='missing-refresh':token.pop('refresh_token')
            if scene=='partial-scope':token['scope']=SCOPES[0]
            status=200
            if scene=='auth':status=400;token={'error':'invalid_grant','error_description':'local-code-auth'}
            if scene=='rate':status=429;token={'error':'rate_limit_exceeded','error_description':'local-code-rate'}
            if scene=='redirect':
                self.send_response(307);self.send_header('Location','https://foreign.invalid/token');self.send_header('Content-Length','0');self.end_headers();return
            raw=json.dumps(token).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            if scene=='rate':self.send_header('Retry-After','180')
            self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),API);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert_file,key_file)
    server.socket=context.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    driver=directory/'driver.py';driver.write_text('''import asyncio,json,os,sys
from pathlib import Path
from haos.gateway_google_chat_oauth_sdk import private,authorization,exchange
try:private()
except PermissionError:
 from haos.gateway_google_chat_oauth_tokens import TokenVault
 try:TokenVault(None)
 except PermissionError:pass
 else:raise AssertionError('foreign UID entered user token vault')
 try:authorization(None)
 except PermissionError:pass
 else:raise AssertionError('foreign UID entered OAuth SDK')
 assert 'google_auth_oauthlib.flow' not in sys.modules
 print('denied-before-SDK');raise SystemExit(3)
from haos.gateway_google_chat_oauth import OAuthStore,TOKEN_URI,REDIRECT_URI
from haos.gateway_google_chat import PreparedGoogleChatPolicy
from haos.gateway_google_chat_http import single_request_http
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from haos.gateway import digest
from haos.gateway_google_chat_auth import CERTS
from types import SimpleNamespace
from urllib.parse import urlencode
v=json.loads(sys.stdin.readline())
try:Path(v['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read Owner canary')
inbox=NativeInbox(Path(v['private'])/'oauth.sqlite',Redactor([]));store=OAuthStore(inbox);policy=PreparedGoogleChatPolicy(v['policy']);cases=[]
async def run():
 global inbox,store
 for scene in ['ok','subject','nonce','audience','signature','missing-refresh','partial-scope','auth','rate','redirect','audit']:
  if inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_oauth_budget'").fetchone():inbox.db.execute('DELETE FROM google_chat_oauth_budget')
  row=store.begin(policy,'google',v['account'],v['client'],'owner',digest(policy.bindings['owner']),owner_uid=1000,note_sha256='a'*64,confirmed=True)
  url=authorization(row);assert not url['network_requested'] and not url['private_verifier_or_credentials_returned']
  print(json.dumps({'scene':scene,'authorization':url['authorization_url']}),flush=True)
  ack=sys.stdin.readline();assert ack=='ready\\n'
  base=single_request_http(lambda:None,fixture_origin=v['origin'],redactor=inbox.redactor);base.ca_certs=v['ca']
  class Routed:
   def request(self,uri,**kwargs):
    assert uri==TOKEN_URI
    return base.request(v['origin']+'/token',**kwargs)
   def close(self):base.close()
  def certificates(url,method='GET',**kwargs):
   assert url==CERTS and method=='GET' and not kwargs
   return SimpleNamespace(status=200,data=json.dumps({'local-google-user':v['public']}).encode())
  callback=REDIRECT_URI+'/?'+urlencode({'code':'local-code-'+scene,'state':row['state']})
  try:
   original,result=await exchange(store,lambda:policy,'google',v['account'],row['id'],callback,owner_uid=1000,http=Routed(),certificate_request=certificates)
  except Exception:
   assert scene!='ok'
  else:
   assert scene in {'ok','audit'} and result.subject=='users/123'
   if scene=='audit':
    import sqlite3
    inbox.db.execute("CREATE TRIGGER fail_complete_audit BEFORE INSERT ON google_chat_oauth_events WHEN NEW.event='complete' BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
    try:store.complete(policy,'google',v['account'],row['id'],result,owner_uid=1000)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('token credentials accepted without audit')
    assert inbox.db.execute('SELECT generation FROM google_chat_user_tokens').fetchone()[0]==1
    assert inbox.db.execute('SELECT status FROM google_chat_oauth_pending WHERE id=?',(row['id'],)).fetchone()[0]=='exchanging'
    inbox.db.execute('DROP TRIGGER fail_complete_audit')
    cases.append(scene);continue
   metadata=store.complete(policy,'google',v['account'],row['id'],result,owner_uid=1000)
   assert metadata['status']=='active' and not metadata['private_credentials_returned']
   saved=json.loads(inbox.db.execute('SELECT credential FROM google_chat_user_tokens').fetchone()[0])
   assert saved['refresh_token']=='local-user-refresh-fixture' and saved['token']=='local-user-access-fixture'
   pending=inbox.db.execute('SELECT status,client,state,nonce,verifier FROM google_chat_oauth_pending WHERE id=?',(row['id'],)).fetchone()
   assert tuple(pending)==('complete','','','','')
  try:store.exchange(policy,'google',v['account'],row['id'],callback,owner_uid=1000)
  except PermissionError:pass
  else:raise AssertionError('begun OAuth request replayed')
  for secret in ['local-user-access-fixture','local-user-refresh-fixture','local-code-'+scene,row['verifier'],v['client']['installed']['client_secret']]:
   if scene=='ok':assert inbox.redactor.text(secret)=='[REDACTED]'
  cases.append(scene)
 quarantined=inbox.db.execute('SELECT * FROM google_chat_oauth_quarantine').fetchall()
 assert len(quarantined)==6 and all(item['state']=='rejected' for item in quarantined)
 assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_user_tokens').fetchone()[0]==1
 assert all('client_secret' not in item['public_client'] for item in quarantined)
 from haos.gateway_google_chat_oauth_refresh import access
 from haos.gateway_google_chat_oauth_tokens import TokenVault,Deferred
 from haos.gateway_google_chat_http import token_response
 from datetime import datetime,timezone,timedelta
 inbox.db.execute('ALTER TABLE google_chat_user_tokens DROP COLUMN public_client')
 vault=TokenVault(store)
 migrated=vault.load(policy,'google',v['account'],{'binding_id':'owner','binding_digest':digest(policy.bindings['owner'])})
 assert migrated['row']['public_client']!='{}' and 'client_secret' not in migrated['row']['public_client']
 original=dict(inbox.db.execute('SELECT * FROM google_chat_user_tokens').fetchone());refresh_cases=[]
 for scene in ['cached','ok','no-id-token','subject','nonce','partial-scope','auth','rate','disconnect','audit','revoked-local']:
  inbox.db.execute('UPDATE google_chat_user_tokens SET credential=?,generation=1,status=? WHERE id=?',(original['credential'],'active',original['id']))
  for table in ['google_chat_oauth_refreshes','google_chat_oauth_transport','google_chat_oauth_budget']:inbox.db.execute('DELETE FROM '+table)
  selected={'binding_id':'owner','binding_digest':digest(policy.bindings['owner'])}
  if scene not in {'cached','revoked-local'}:
   expired=json.loads(original['credential']);expired['expiry']=(datetime.now(timezone.utc)-timedelta(hours=1)).replace(tzinfo=None).isoformat()+'Z'
   inbox.db.execute('UPDATE google_chat_user_tokens SET credential=?',(json.dumps(expired,sort_keys=True,separators=(',',':')),))
  if scene=='revoked-local':
   revoked=vault.local_revoke(v['account'],{'id':original['id'],'generation':1,'owner_uid':1000,'note_sha256':'b'*64,'confirmed':True})
   assert revoked['locally_revoked'] and not revoked['remote_revocation_verified'] and not revoked['network_requested']
  if scene=='audit':inbox.db.execute("CREATE TRIGGER deny_refresh_acceptance BEFORE UPDATE ON google_chat_oauth_refreshes WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
  print(json.dumps({'refresh':scene}),flush=True);assert sys.stdin.readline()=='ready\\n'
  base=single_request_http(lambda:None,fixture_origin=v['origin'],redactor=inbox.redactor);base.ca_certs=v['ca']
  class RefreshWire:
   def request(self,uri,**kwargs):
    assert uri==TOKEN_URI
    response,data=base.request(v['origin']+'/token',**kwargs)
    return token_response(uri,response,data,redactor=inbox.redactor)
  try:
   sdk,snapshot=await access(store,lambda:policy,'google',v['account'],selected,lambda:None,http=RefreshWire(),certificate_request=certificates)
  except Deferred as error:
   assert scene not in {'cached','ok','no-id-token'}
   expected='user-auth-required' if scene=='revoked-local' else 'rate-limited' if scene=='rate' else 'refresh-uncertain' if scene in {'disconnect','audit'} else 'authentication-refused'
   assert error.status==expected,(scene,error.status)
   if scene!='revoked-local':
    assert inbox.db.execute('SELECT generation FROM google_chat_user_tokens').fetchone()[0]==1
    aliases=list(inbox.redactor.secrets);inbox.close()
    inbox=NativeInbox(Path(v['private'])/'oauth.sqlite',Redactor(aliases));store=OAuthStore(inbox);vault=TokenVault(store)
    try:await access(store,lambda:policy,'google',v['account'],selected,lambda:None,http=RefreshWire(),certificate_request=certificates)
    except Deferred as repeated:assert repeated.status==expected
    else:raise AssertionError('blocked refresh replayed')
   if scene=='rate':
    wait=inbox.db.execute('SELECT not_before FROM google_chat_oauth_budget').fetchone()[0]
    assert wait>=__import__('time').time()+175
    fresh=store.begin(policy,'google',v['account'],v['client'],'owner',digest(policy.bindings['owner']),owner_uid=1000,note_sha256='c'*64,confirmed=True)
    try:store.exchange(policy,'google',v['account'],fresh['id'],REDIRECT_URI+'/?'+urlencode({'code':'not-sent-during-budget','state':fresh['state']}),owner_uid=1000)
    except Deferred as waiting:assert waiting.status=='rate-limited'
    else:raise AssertionError('new enrollment bypassed stable client rate deadline')
    assert inbox.db.execute('SELECT status FROM google_chat_oauth_pending WHERE id=?',(fresh['id'],)).fetchone()[0]=='awaiting'
    inbox.db.execute('UPDATE google_chat_user_tokens SET generation=2')
    try:vault.load(policy,'google',v['account'],selected)
    except Deferred as waiting:assert waiting.status=='rate-limited'
    else:raise AssertionError('new token generation reset stable account/client budget')
    assert inbox.db.execute('SELECT not_before FROM google_chat_oauth_budget').fetchone()[0]==wait
   if scene=='audit':inbox.db.execute('DROP TRIGGER deny_refresh_acceptance')
  else:
   assert scene in {'cached','ok','no-id-token'} and sdk.valid
   assert sdk.token==('local-user-access-fixture' if scene=='cached' else 'refreshed-user-access-fixture')
   assert snapshot['row']['generation']==(1 if scene=='cached' else 2)
  refresh_cases.append(scene)
 from haos.gateway_google_chat_oauth_revoke import revoke,REVOKE_URI
 revoke_cases=[]
 for scene in ['ok','refused','rate','disconnect','redirect','body','audit']:
  inbox.db.execute('UPDATE google_chat_user_tokens SET credential=?,generation=1,status=? WHERE id=?',(original['credential'],'active',original['id']))
  for table in ['google_chat_oauth_refreshes','google_chat_oauth_transport','google_chat_oauth_budget','google_chat_oauth_token_owner_events']:inbox.db.execute('DELETE FROM '+table)
  if inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_oauth_revocations'").fetchone():inbox.db.execute('DELETE FROM google_chat_oauth_revocations')
  print(json.dumps({'revoke':scene}),flush=True);assert sys.stdin.readline()=='ready\\n'
  base=single_request_http(lambda:None,fixture_origin=v['origin'],redactor=inbox.redactor,oauth_revoke=True);base.ca_certs=v['ca']
  class RevokeWire:
   def request(self,uri,**kwargs):
    assert uri==REVOKE_URI
    return base.request(v['origin']+'/revoke',**kwargs)
  request={'id':original['id'],'generation':1,'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True}
  if scene=='audit':
   inbox.db.execute('CREATE TABLE IF NOT EXISTS google_chat_oauth_revocations(id TEXT PRIMARY KEY,token_id TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,receipt TEXT NOT NULL)')
   inbox.db.execute("CREATE TRIGGER deny_revoke_receipt BEFORE UPDATE ON google_chat_oauth_revocations WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
  try:result=await revoke(store,lambda:policy,'google',v['account'],request,lambda:None,http=RevokeWire())
  except sqlite3.IntegrityError:
   assert scene=='audit'
   inbox.db.execute('DROP TRIGGER deny_revoke_receipt')
   result=await revoke(store,lambda:policy,'google',v['account'],request,lambda:None,http=RevokeWire())
   assert result['remote_status']=='uncertain' and not result['network_requested']
  else:
   expected='confirmed' if scene=='ok' else 'refused' if scene=='refused' else 'rate-limited' if scene=='rate' else 'uncertain'
   assert result['remote_status']==expected and result['network_requested'] and not result['message_sent']
  assert result['locally_revoked'] and result['remote_revocation_verified']==(scene=='ok')
  replay=await revoke(store,lambda:policy,'google',v['account'],request,lambda:None,http=RevokeWire())
  assert not replay['network_requested'] and replay['remote_status']==result['remote_status']
  assert inbox.db.execute('SELECT status FROM google_chat_user_tokens').fetchone()[0]==('revoked-remote' if scene=='ok' else 'revoked-local')
  try:TokenVault(store).load(policy,'google',v['account'],selected)
  except Deferred:pass
  else:raise AssertionError('locally withdrawn user credentials selected for API use')
  if scene=='rate':assert inbox.db.execute('SELECT not_before FROM google_chat_oauth_budget').fetchone()[0]>=__import__('time').time()+175
  revoke_cases.append(scene)
 from haos.gateway_google_chat_oauth_quarantine import inventory as rejected_inventory,dispose
 inbox.db.execute('DELETE FROM google_chat_oauth_budget')
 capsules=rejected_inventory(store,v['account'])['quarantines'];assert len(capsules)==10
 assert sum(item['origin']=='refresh' for item in capsules)==4
 quarantine_cases=[]
 for item in capsules:
  assert not item['api_use_authorized'] and not item['actual_user_verified']
  print(json.dumps({'quarantine':len(quarantine_cases)}),flush=True);assert sys.stdin.readline()=='ready\\n'
  base=single_request_http(lambda:None,fixture_origin=v['origin'],redactor=inbox.redactor,oauth_revoke=True);base.ca_certs=v['ca']
  request={'id':item['id'],'snapshot_sha256':item['snapshot_sha256'],'owner_uid':1000,'note_sha256':'e'*64,'confirmed':True}
  result=await dispose(store,lambda:policy,'google',v['account'],request,lambda:None,http=RevokeWire())
  assert result['remote_revocation_verified'] and result['network_requested'] and not result['api_use_authorized']
  replay=await dispose(store,lambda:policy,'google',v['account'],request,lambda:None,http=RevokeWire())
  assert replay['remote_revocation_verified'] and not replay['network_requested']
  assert inbox.db.execute('SELECT tokens,state FROM google_chat_oauth_quarantine WHERE id=?',(item['id'],)).fetchone()['tokens']=='{}'
  assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_user_tokens').fetchone()[0]==1
  quarantine_cases.append('refresh-token' if item['has_refresh_token'] else 'access-token')
 print(json.dumps({'complete':True,'passed':len(cases),'cases':cases,'refresh_cases':refresh_cases,'revoke_cases':revoke_cases,'quarantine_cases':quarantine_cases}),flush=True)
try:asyncio.run(run())
finally:inbox.close()
''');driver.chmod(0o755)
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'};cases=[]
    for uid,groups in [(0,()),(65533,()),(65534,(0,))]:
        child=subprocess.run([str(runtime/'bin/python'),'-E','-s',str(driver)],capture_output=True,text=True,timeout=15,user=uid,group=uid,extra_groups=list(groups),cwd=str(code),env=env)
        assert child.returncode==3 and child.stdout=='denied-before-SDK\n',child.stderr
    cases.append('actual_Root_agent_and_supplementary_root_group_are_refused_before_optional_OAuth_SDK_import')
    async def exercise():
        child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(driver),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            user=65534,group=65534,extra_groups=[],cwd=str(code),env=env,umask=0o077)
        request={'private':str(private),'canary':str(canary),'policy':policy,'account':account,'client':client,'origin':'https://localhost:'+str(server.server_port),'ca':str(cert_file),'public':public}
        child.stdin.write((json.dumps(request)+'\n').encode());await child.stdin.drain()
        try:
            for _ in range(11):
                line=await asyncio.wait_for(child.stdout.readline(),15)
                if not line:raise AssertionError((await child.stderr.read()).decode()[-1800:])
                item=json.loads(line);assert set(item)=={'scene','authorization'}
                assert client['installed']['client_secret'] not in line.decode()
                parsed=urlsplit(item['authorization']);assert parsed.scheme=='https' and parsed.hostname=='accounts.google.com'
                public_authorizations[item['scene']]=parse_qs(parsed.query)
                child.stdin.write(b'ready\n');await child.stdin.drain()
            for scene in ['cached','ok','no-id-token','subject','nonce','partial-scope','auth','rate','disconnect','audit','revoked-local']:
                line=await asyncio.wait_for(child.stdout.readline(),15)
                if not line:raise AssertionError((await child.stderr.read()).decode()[-1800:])
                assert json.loads(line)=={'refresh':scene}
                refresh_control['mode']=scene;child.stdin.write(b'ready\n');await child.stdin.drain()
            for scene in ['ok','refused','rate','disconnect','redirect','body','audit']:
                line=await asyncio.wait_for(child.stdout.readline(),15)
                if not line:raise AssertionError((await child.stderr.read()).decode()[-1800:])
                assert json.loads(line)=={'revoke':scene}
                revoke_control['mode']=scene;child.stdin.write(b'ready\n');await child.stdin.drain()
            for index in range(10):
                line=await asyncio.wait_for(child.stdout.readline(),15)
                if not line:raise AssertionError((await child.stderr.read()).decode()[-1800:])
                assert json.loads(line)=={'quarantine':index}
                revoke_control['mode']='quarantine';child.stdin.write(b'ready\n');await child.stdin.drain()
            line=await asyncio.wait_for(child.stdout.readline(),15)
            if not line:raise AssertionError((await child.stderr.read()).decode()[-1800:])
            report=json.loads(line);assert {key:value for key,value in report.items() if key not in {'refresh_cases','revoke_cases','quarantine_cases'}}=={'complete':True,'passed':11,'cases':['ok','subject','nonce','audience','signature','missing-refresh','partial-scope','auth','rate','redirect','audit']}
            child.stdin.close();await asyncio.wait_for(child.wait(),5);assert child.returncode==0
            stderr=await child.stderr.read()
            assert all(token.encode() not in stderr for token in ['local-user-access-fixture','local-user-refresh-fixture',client['installed']['client_secret']])
            assert requests==report['cases']+['refresh-'+scene for scene in report['refresh_cases'] if scene not in {'cached','revoked-local'}]+['revoke-'+scene for scene in report['revoke_cases']]+['revoke-quarantine']*10
            cases.extend('actual_private_UID_Google_Flow_PKCE_single_TLS_exchange_RSA_identity_and_no_replay_'+scene for scene in report['cases'])
            cases.extend('actual_private_UID_Google_credentials_SDK_FULL_refresh_rate_auth_and_local_withdrawal_'+scene for scene in report['refresh_cases'])
            cases.extend('actual_private_UID_local_denial_before_bounded_TLS_revocation_and_no_repeated_decision_POST_'+scene for scene in report['revoke_cases'])
            cases.extend('actual_private_UID_rejected_enrollment_capsule_never_becomes_active_and_explicit_TLS_disposal_clears_payload_after_receipt_without_replay_'+str(index)+'_'+kind for index,kind in enumerate(report['quarantine_cases']))
        finally:
            if child.returncode is None:child.terminate();await child.wait()
    try:asyncio.run(exercise())
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_private_UID_Google_Flow_PKCE_Token_SDK_TLS_RSA_and_FULL_SQLite':True,
        'Google_token_and_certificate_endpoints_are_explicit_local_fixtures':True,'service_account_is_schema_only_for_user_OAuth_scope':True,
        'actual_verified_user_token_private_FULL_persistence_and_pending_secret_compaction':True,
        'actual_private_UID_SDK_refresh_and_local_withdrawal':True,
        'actual_local_denial_before_remote_revocation_TLS_and_durable_replay':True,
        'actual_rejected_enrollment_disposal_without_active_grant':True,
        'actual_rejected_refresh_disposal_with_original_enrollment_preserved':True,
        'Owner_handoff_GUI_outbound_files_live_account_or_public_activation':False},indent=2))


if __name__=='__main__':main()
