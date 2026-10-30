"""Actual private native file adapter/SDK with namespace-local Google HTTPS."""
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import socket
import hashlib
import base64
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit,urlencode


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_FILE_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh readonly disposable Owner OAuth namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    prepared=Path('/repo/upstream/hermes-agent');assert (prepared/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    staged=Path(tempfile.mkdtemp(prefix='haos-owner-oauth-source-'));shutil.copytree(prepared,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py',str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/sdk',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from google.auth import crypt,jwt
    import httplib2
    from haos.gateway_google_chat import scope
    from haos.gateway_google_chat_oauth import SCOPES,REDIRECT_URI
    from haos.gateway import digest
    now=datetime.datetime.now(datetime.timezone.utc);directory=Path(tempfile.mkdtemp(prefix='haos-owner-oauth-'));directory.chmod(0o755)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'local-Google-namespace-fixture')])
    ca=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256())
    cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'oauth2.googleapis.com')])).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('oauth2.googleapis.com'),x509.DNSName('www.googleapis.com'),x509.DNSName('chat.googleapis.com')]),False).sign(key,hashes.SHA256())
    for path in {ssl.get_default_verify_paths().cafile,httplib2.CA_CERTS}:
        with Path(path).open('ab') as stream:stream.write(b'\n'+ca.public_bytes(serialization.Encoding.PEM))
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 oauth2.googleapis.com www.googleapis.com chat.googleapis.com\n')
    certfile=directory/'cert.pem';certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile=directory/'key.pem';keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));keyfile.chmod(0o600)
    signing=rsa.generate_private_key(public_exponent=65537,key_size=2048);signer=crypt.RSASigner.from_string(signing.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),key_id='local-owner-google-user')
    signing_cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'oauth2.googleapis.com')])).issuer_name(name).public_key(signing.public_key()).serial_number(2).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).sign(signing,hashes.SHA256())
    public=signing_cert.public_bytes(serialization.Encoding.PEM).decode()
    email='gateway@haos-fixture.iam.gserviceaccount.com';value={'service_account':{'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n','client_email':email,'client_id':'123456789',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},'bot_user':'users/999',
        'inbound':{'mode':'pubsub','subscription':'projects/haos-fixture/subscriptions/haos-private'}}
    configuration={'installed':{'client_id':'123456789-owner-fixture.apps.googleusercontent.com','project_id':'haos-fixture','auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','client_secret':'private-owner-client-fixture','redirect_uris':['http://localhost']}}
    binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1','scope':scope(value),
        'identity':'personal','capabilities':['read'],'allow_outbound_media':True,'generation':'a'*64,'since':int(now.timestamp()*1000)-60000}
    policy={'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]}
    config=Path('/etc/haos');config.mkdir(mode=0o755);publication=config/'gateways.json';publication.write_text(json.dumps(policy));publication.chmod(0o644)
    secret=config/'gateway-credentials';secret.write_text(json.dumps({'connectors':{'google':value}}));secret.chmod(0o600)
    state=Path('/var/lib/haos-gateway');assert not state.exists()
    database=state/'profiles'/('google-chat-'+digest(scope(value)))/'user-oauth.sqlite'
    systemctl=Path('/usr/bin/systemctl');systemctl.write_text('''#!/usr/local/bin/python3
import sys
if sys.argv[1]=='stop':raise SystemExit(0)
if sys.argv[1]=='show':print('LoadState=loaded\\nActiveState=inactive\\nMainPID=0\\nControlPID=0')
else:raise SystemExit(2)
''');systemctl.chmod(0o755)
    helper=Path('/root/owner-oauth-parent.py');helper.write_text('''import json,sys
sys.path.insert(0,'/usr/lib/haos')
from haos import google_chat_owner_setup as owner
v=json.load(sys.stdin);action=v['action'];params=v.get('params',{})
try:
 if action=='inspect':result=owner.oauth_inspect('google',**params)
 elif action=='begin':result=owner.oauth_begin('google',**params)
 elif action=='finish':result=owner.oauth_finish('google',**params)
 elif action=='revoke':result=owner.oauth_revoke('google',**params)
 elif action=='dispose':result=owner.oauth_dispose('google',**params)
 elif action=='file-inspect':result=owner.inspect('google',**params)
 elif action=='file-retry':result=owner.file_retry('google',**params)
 elif action=='output-purge':result=owner.output_purge('google',**params)
 else:raise ValueError('fixture action')
 print(json.dumps(result))
except PermissionError:print(json.dumps({'error':'root-backend-authority-refused'}))
''');helper.chmod(0o700)
    scene=os.environ.get('HAOS_GOOGLE_CHAT_FILE_SCENE','active')
    assert scene in {'active','upload-auth','upload-rate','upload-disconnect','create-auth','create-rate','create-disconnect','response-mismatch','callback-no-client','publisher','local-logout','recover-upload','recover-create','recover-late','recover-read-disconnect','recover-read-body','recover-output-purge'}
    publisher=scene=='publisher' or scene.startswith('recover-');phase={'value':1}
    sa_key=None
    if publisher:
        sa_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        value['service_account']['private_key']=sa_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        binding['capabilities']=['create','read']
        binding['allow_media']=True;binding['require_mention']=False
        publication.write_text(json.dumps(policy));secret.write_text(json.dumps({'connectors':{'google':value}}))
    requests=[];authorizations={};wire={'client':None,'request':None,'message':None};body_bytes=b'%PDF-1.7\nApproved exact Root output fixture\n'
    signals,child_signals=socket.socketpair();signals.settimeout(15)
    profile_directory=state/'profiles'/('google-chat-'+digest(scope(value)))
    native_database=state/'native-inbox.db' if scene.startswith('recover-') else profile_directory/'file-native.sqlite'
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            if status==429:self.send_header('Retry-After','180')
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            host=self.headers['Host'];path=urlsplit(self.path)
            if host=='www.googleapis.com':
                assert path.path=='/oauth2/v1/certs' and not self.headers.get('Authorization');requests.append('certificates');self.reply(200,{'local-owner-google-user':public});return
            if publisher and path.path=='/v1/spaces/room1/members/999':
                assert host=='chat.googleapis.com' and self.headers['Authorization']=='Bearer owner-private-bot-access-fixture'
                requests.append('bot-membership');self.reply(200,{'state':'MEMBER','member':{'name':'users/999','type':'BOT'}});return
            assert host=='chat.googleapis.com' and self.headers['Authorization']=='Bearer owner-private-access-fixture'
            assert path.path=='/v1/spaces/room1/messages/'+wire['client'] and parse_qs(path.query)=={'alt':['json']}
            requests.append('read-own-write')
            if scene=='recover-read-disconnect' and phase['value']==2:self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if scene=='recover-read-body' and phase['value']==2:
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length','1');self.end_headers();self.wfile.write(b'{');return
            if scene=='recover-late':self.reply(200,wire['message']);return
            if scene in {'create-disconnect','response-mismatch'}:self.reply(200,wire['message'])
            else:self.reply(404,{'error':{'code':404,'message':'own file not accepted','status':'NOT_FOUND'}})
        def do_POST(self):
            host=self.headers['Host'];path=urlsplit(self.path);raw=self.rfile.read(int(self.headers['Content-Length']))
            if host=='oauth2.googleapis.com':
                assert path.path=='/token';values=parse_qs(raw.decode(),strict_parsing=True)
                if values['grant_type']==['urn:ietf:params:oauth:grant-type:jwt-bearer']:
                    assert publisher;signed=values['assertion'][0].encode();payload,signature=signed.rsplit(b'.',1)
                    from cryptography.hazmat.primitives.asymmetric import padding
                    sa_key.public_key().verify(base64.urlsafe_b64decode(signature+b'='*(-len(signature)%4)),payload,padding.PKCS1v15(),hashes.SHA256())
                    claims=jwt.decode(signed,verify=False);assert claims['iss']==email and claims['aud']=='https://oauth2.googleapis.com/token'
                    assert set(claims['scope'].split())=={'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'}
                    requests.append('bot-token');self.reply(200,{'access_token':'owner-private-bot-access-fixture','token_type':'Bearer','expires_in':3600});return
                entry=authorizations['owner-good-account']
                assert values['grant_type']==['authorization_code'] and values['client_secret']==[configuration['installed']['client_secret']]
                challenge=base64.urlsafe_b64encode(hashlib.sha256(values['code_verifier'][0].encode()).digest()).rstrip(b'=').decode();assert entry['code_challenge']==[challenge]
                requests.append('token');claims={'iss':'https://accounts.google.com','aud':configuration['installed']['client_id'],'sub':'123','nonce':entry['nonce'][0],
                    'iat':int(now.timestamp()),'exp':int(now.timestamp())+3600}
                self.reply(200,{'access_token':'owner-private-access-fixture','refresh_token':'owner-private-refresh-fixture','token_type':'Bearer',
                    'expires_in':3600,'scope':' '.join(SCOPES),'id_token':jwt.encode(signer,claims).decode()});return
            if publisher and self.headers.get('Authorization')=='Bearer owner-private-bot-access-fixture':
                assert host=='chat.googleapis.com' and path.path=='/v1/spaces/room1/messages';query=parse_qs(path.query);content=json.loads(raw)
                with sqlite3.connect(profile_directory/'controller-component.sqlite') as control_db:mission_id=control_db.execute('SELECT id FROM missions').fetchone()[0]
                assert content=={'text':'Mission '+mission_id+': completed\nApproved report\n','thread':{'name':binding['thread']}}
                assert set(query)=={'alt','messageId','requestId','messageReplyOption'} and query['messageReplyOption']==['REPLY_MESSAGE_OR_FAIL']
                with sqlite3.connect(native_database) as db:
                    row=db.execute('SELECT state,client_id,request_id FROM google_chat_text_writes').fetchone();assert row==('writing',query['messageId'][0],query['requestId'][0])
                requests.append('bot-text-create');self.reply(200,{'name':binding['chat']+'/messages/bot-reply','clientAssignedMessageId':query['messageId'][0],**content});return
            assert host=='chat.googleapis.com' and self.headers['Authorization']=='Bearer owner-private-access-fixture'
            if path.path=='/upload/v1/spaces/room1/attachments:upload':
                assert parse_qs(path.query)=={'alt':['json'],'uploadType':['multipart']}
                from email.parser import BytesParser
                from email import policy as mime_policy
                message=BytesParser(policy=mime_policy.default).parsebytes(b'Content-Type: '+self.headers['Content-Type'].encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw)
                parts=list(message.iter_parts());assert len(parts)==2 and json.loads(parts[0].get_payload(decode=True))=={'filename':'result-0.pdf'}
                assert parts[1].get_payload(decode=True)==body_bytes and parts[1].get_content_type()=='application/pdf'
                with sqlite3.connect(native_database) as db:assert db.execute('SELECT upload_state,state FROM google_chat_file_writes').fetchone()==('uploading','prepared')
                requests.append('upload')
                if scene=='upload-disconnect' or scene=='recover-upload' and phase['value']==1:self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                if scene in {'upload-auth','upload-rate'}:
                    self.reply(401 if scene=='upload-auth' else 429,{'error':{'code':401 if scene=='upload-auth' else 429,'message':'private SDK refusal','status':'UNAUTHENTICATED' if scene=='upload-auth' else 'RESOURCE_EXHAUSTED'}});return
                self.reply(200,{'attachmentDataRef':{'attachmentUploadToken':'private-native-upload-reference-fixture'}});return
            assert path.path=='/v1/spaces/room1/messages';query=parse_qs(path.query)
            assert set(query)=={'alt','messageId','requestId','messageReplyOption'} and query['alt']==['json'] and query['messageReplyOption']==['REPLY_MESSAGE_OR_FAIL']
            content=json.loads(raw);expected={'attachment':[{'attachmentDataRef':{'attachmentUploadToken':'private-native-upload-reference-fixture'}}],
                'text':'Approved report','thread':{'name':binding['thread']}}
            if publisher:expected.pop('text')
            assert content==expected
            with sqlite3.connect(native_database) as db:
                row=db.execute('SELECT upload_state,state,client_id,request_id FROM google_chat_file_writes').fetchone();assert row[:2]==('uploaded','writing')
                assert query['messageId']==[row[2]] and query['requestId']==[row[3]];wire['client']=row[2];wire['request']=row[3]
            requests.append('create')
            if scene in {'recover-create','recover-read-disconnect','recover-read-body'} and phase['value']==1:
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if scene in {'create-auth','create-rate'}:
                self.reply(401 if scene=='create-auth' else 429,{'error':{'code':401 if scene=='create-auth' else 429,'message':'private SDK refusal','status':'UNAUTHENTICATED' if scene=='create-auth' else 'RESOURCE_EXHAUSTED'}});return
            name=binding['chat']+'/messages/user-file'
            accepted={'name':name,'clientAssignedMessageId':wire['client'],'text':content.get('text',''),'sender':{'name':'users/123','type':'HUMAN'},
                'thread':{'name':binding['thread']},'attachment':[{'name':name+'/attachments/file1','contentName':'result-0.pdf','contentType':'application/pdf','source':'UPLOADED_CONTENT'}]}
            wire['message']=accepted
            callback={'type':'MESSAGE','space':{'name':binding['chat'],'spaceType':'SPACE'},'message':{**accepted,'createTime':datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')}}
            if scene=='callback-no-client':callback['message'].pop('clientAssignedMessageId')
            signals.sendall(json.dumps(callback).encode()+b'\n');assert signals.recv(32)==b'blocked-before-response\n'
            requests.append('own-echo-blocked-before-response')
            if scene=='create-disconnect' or scene=='recover-late' and phase['value']==1:self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if scene=='response-mismatch':accepted={**accepted,'sender':{'name':'users/124','type':'HUMAN'}}
            self.reply(200,accepted)
    server=ThreadingHTTPServer(('127.0.0.1',443),API);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(certfile,keyfile)
    server.socket=tls.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','SUDO_UID':'1000'}
    def owner_call(action,params):
        result=subprocess.run([sys.executable,str(helper)],input=json.dumps({'action':action,'params':params}),text=True,capture_output=True,cwd=str(code),env=env,timeout=50)
        assert result.returncode==0 and not result.stderr,result.stderr
        return json.loads(result.stdout)
    class AgentArtifact(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlsplit(self.path);assert publisher and path.path=='/api/fs/read-data-url'
            assert parse_qs(path.query)=={'session_id':['stored-file-session'],'path':['/agent/report.pdf']} and self.headers['Authorization']=='Bearer local-artifact-fixture'
            requests.append('agent-session-artifact-read');raw=json.dumps({'dataUrl':'data:application/pdf;base64,'+base64.b64encode(body_bytes).decode()}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    agent=ThreadingHTTPServer(('127.0.0.1',0),AgentArtifact);agent_thread=threading.Thread(target=agent.serve_forever,daemon=True);agent_thread.start()
    driver=directory/'file-driver.py';driver.write_text('''import asyncio,json,os,sys,socket,hashlib
from pathlib import Path
from types import SimpleNamespace
from haos.gateway_runtime import require_runtime_identity,prepare_runtime_home
try:require_runtime_identity()
except PermissionError:
 assert 'googleapiclient.discovery' not in sys.modules
 print('denied-before-SDK');raise SystemExit(3)
prepare_runtime_home()
from haos.gateway import GatewayPolicy
from haos.gateway_google_chat import authority
from haos.gateway_google_chat_oauth import OAuthStore
from haos.gateway_google_chat_files import Files
from haos.gateway_google_chat_output import Output
from haos.gateway_google_chat_delivery import Publisher
from haos.gateway_google_chat_custody import Originals
from haos.gateway_google_chat_receive import Receiver
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from haos.gateway import digest
from haos.sandbox import trusted_json
v=json.load(sys.stdin);account=v['account'];binding=v['policy']['bindings'][0];profile=Path(v['profile']);redactor=Redactor([])
try:Path('/root/owner-oauth-parent.py').read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read Root Owner canary')
from haos.gateway_matrix_profile import acquire_lease
lease=acquire_lease(profile) if not v['publisher'] else None
import logging
from haos.gateway_runtime import SafeFormatter
handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor));logging.basicConfig(level=logging.ERROR,handlers=[handler],force=True)
from plugins.platforms.google_chat import adapter as native
from gateway.config import PlatformConfig
import warnings
with warnings.catch_warnings(record=True) as notices:
 warnings.simplefilter('always',FutureWarning);assert native._load_google_modules()
assert len(notices)==2
for notice in notices:
 assert notice.category is FutureWarning and notice.filename.endswith('/google/api_core/_python_version_support.py')
 assert str(notice.message).startswith('You are using a Python version (3.11.17) which Google will stop supporting in new releases of google.') and '2027-10-24' in str(notice.message)
adapter=native.GoogleChatAdapter(PlatformConfig(enabled=True,extra={}))
inbox=NativeInbox(Path(v['native_database']),redactor);oauth_inbox=NativeInbox(profile/'user-oauth.sqlite',redactor);store=OAuthStore(oauth_inbox)
def policy():return GatewayPolicy(trusted_json(Path('/etc/haos/gateways.json')))
def current():require_runtime_identity();authority('google',account)
adapter._haos_native=SimpleNamespace(inbox=inbox,connector='google',policy=policy);adapter._haos_google_value=account;adapter._haos_google_check=current
if v['publisher']:
 from haos.gateway_google_chat_profile import build
 adapter=build(account,parent=profile.parent,connector='google',policy=policy,inbox=inbox)
 output=adapter._haos_google_output;files=None
else:Publisher(adapter);output=Output(adapter);files=Files(adapter,store)
adapter._last_sender_by_chat[binding['chat']]='different-display-email@example.invalid'
adapter._user_chat_api=object();adapter._user_credentials=object()
originals=adapter._haos_google_originals if v['publisher'] else Originals(profile/'echo-originals.sqlite',redactor)
receiver=adapter._haos_google_receiver if v['publisher'] else Receiver('google',account,originals,policy,current,own_message=lambda raw:files.ledger.own_message('google',account,raw))
signal=socket.socket(fileno=v['signal']);signal.setblocking(False)
async def run():
 data=bytes.fromhex(v['data_hex']);content='Approved report\\nMEDIA:/agent/report.pdf'
 context={'version':1,'mission_id':'fixture-mission','kind':'mission.completed','source_event':'fixture-event','state':'completed','phase':'done',
  'request_id':None,'request_method':None,'part':0,'parts':1,'total_bytes':len(content),'content_sha256':hashlib.sha256(content.encode()).hexdigest(),'group_sha256':'a'*64}
 delivery={'id':'b'*64,'attempt':1,'binding_id':'owner','binding_digest':digest(binding),'chat':binding['chat'],'scope':binding['scope'],'thread':binding['thread'],
  'event_context':context,'content':content}
 offer={'id':'c'*64,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()};calls=[]
 async def root_call(method,params):
  import base64
  calls.append(method);assert params['delivery']==delivery['id'] and params['attempt']==1
  if method=='gateway.output.manifest':return {'paths':['/agent/report.pdf'],'text':'Approved report','source_sha256':context['content_sha256'],'group_sha256':context['group_sha256']}
  if method=='gateway.output.begin':assert params['path']=='/agent/report.pdf';return offer
  assert method=='gateway.output.chunk' and params['id']==offer['id'] and params['offset']==0
  return {'id':offer['id'],'offset':0,'data':base64.b64encode(data).decode()}
 if v['publisher']:
  from haos.gateway_relay import RelayInbox
  from haos.gateway_runtime import adapter_envelope,delivery_metadata
  from haos.gateway_google_chat_ingress import capture_stored,dispatch_stored
  from haos.controller import Controller
  from haos.store import MissionStore
  from haos.gateway_outbound import Exports
  relay=RelayInbox(profile/'file-relay.sqlite',redactor);component=MissionStore(profile/'controller-component.sqlite')
  controller=Controller(component,'ws://127.0.0.1:'+str(v['agent_port'])+'/api/ws?token=local-artifact-fixture',{65534});controller.gateway_policy=policy
  exports=Exports(controller)
  adapter.set_durable_message_handler(lambda ev:bool(relay.admit(policy(),'google',adapter_envelope(ev,'google_chat'))) or True)
  await adapter._haos_google_account_check()
  if v['phase']==1:
   from datetime import datetime,timezone
   incoming={'type':'MESSAGE','space':{'name':binding['chat'],'spaceType':'SPACE'},'message':{'name':binding['chat']+'/messages/source',
    'thread':{'name':binding['thread']},'sender':{'name':'users/123','type':'HUMAN'},'createTime':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
    'text':'<users/999> Create a report','argumentText':'Create a report','annotations':[{'type':'USER_MENTION','userMention':{'user':{'name':'users/999'}}}]}}
   raw=json.dumps(incoming).encode();identity=originals.retain(policy(),'google',account,raw,current)
   key=await capture_stored(adapter,identity);assert await dispatch_stored(adapter,key)
   received=relay.next(policy());assert received is not None
   mission=await controller.gateway.receive(policy(),'google',received['envelope'],controller);relay.admitted(received['id'],mission['mission_id'])
   component.claim();component.session(mission['mission_id'],'native-file-session','stored-file-session');component.settle(mission['mission_id'],'completed',result=content)
   controller.gateway.refresh(policy());deliveries=[]
   while True:
    item=controller.gateway.next_delivery(policy())
    if item is None:break
    deliveries.append(item)
   delivery=next(item for item in deliveries if item['event_context']['kind']=='mission.completed')
  else:delivery=json.loads((profile/'file-delivery-fixture.json').read_text())
  async def root_call(method,params):
   if method=='gateway.output.manifest':return exports.manifest(params)
   if method=='gateway.output.begin':return await exports.begin(params)
   assert method=='gateway.output.chunk';return exports.chunk(params)
 if v['publisher']:(profile/'file-delivery-fixture.json').write_text(json.dumps(delivery))
 projection=await output.prepare(delivery,root_call);artifact=output.resolve(delivery,projection)[0];assert artifact['data']==data
 source={'delivery_id':delivery['id'],'source_key':'d'*64,'source_id':binding['chat']+'/messages/source','source_sha256':'e'*64,'context_sha256':digest(context),'content_sha256':context['content_sha256']}
 route={'binding_id':'owner','binding_digest':digest(binding)}
 def checked():current();assert output.resolve(delivery,projection)[0]['data']==data
 async def echo():
  raw=bytearray();loop=asyncio.get_running_loop()
  while not raw.endswith(b'\\n'):
   raw.extend(await loop.sock_recv(signal,65536));assert len(raw)<=65536
  assert receiver._http_retain(bytes(raw[:-1])) is None
  assert originals.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==(1 if v['publisher'] else 0)
  assert originals.db.execute('SELECT reason FROM google_chat_source_refusals').fetchone()[0]=='self-or-automated'
  await loop.sock_sendall(signal,b'blocked-before-response\\n')
 expect_echo=v['scene'] in {'active','callback-no-client','create-disconnect','response-mismatch','publisher','local-logout'}
 if v['scene'].startswith('recover-'):expect_echo=(v['phase']==1 and v['scene'] in {'recover-late','recover-output-purge'} or v['phase']>=2 and v['scene'] in {'recover-upload','recover-create'})
 echo_task=asyncio.create_task(echo()) if expect_echo else None
 result=None;error_type=None
 try:
  if v['publisher']:
   metadata=delivery_metadata(delivery,'google_chat');metadata['haos_output']=projection
   result=await adapter._haos_google_publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],metadata)
  else:result=await files.send('f'*64,route,source,artifact,projection['text'],binding['thread'],checked)
 except Exception as error:error_type=type(error).__name__
 if echo_task:await asyncio.wait_for(echo_task,5)
 row=dict(inbox.db.execute('SELECT * FROM google_chat_file_writes').fetchone())
 if v['scene'].startswith('recover-'):
  expected_success=v['scene']=='recover-output-purge' or v['phase']==2 and v['scene'] in {'recover-upload','recover-create','recover-late'}
  assert (result is not None and result.success)==expected_success
  assert (row['state']=='confirmed')==expected_success
 elif v['scene'] in {'active','callback-no-client','publisher','local-logout'}:assert result.success and row['state']=='confirmed'
 else:assert result is None and row['state']!='confirmed'
 initial=(row['upload_state'],row['state'])
 if v['scene']=='local-logout':
  from haos.gateway_google_chat_oauth_tokens import TokenVault
  record=oauth_inbox.db.execute('SELECT id,generation FROM google_chat_user_tokens').fetchone()
  revoked=TokenVault(store).local_revoke(account,{'id':record['id'],'generation':record['generation'],'owner_uid':1000,'note_sha256':'a'*64,'confirmed':True})
  assert revoked['locally_revoked'] and not revoked['network_requested'] and not revoked['remote_revocation_verified']
  try:await files.send('6'*64,route,source,artifact,projection['text'],binding['thread'],checked)
  except PermissionError:pass
  else:raise AssertionError('withdrawn user could start a new Google file operation')
  assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_file_writes').fetchone()[0]==1
 # Native entry points and cached legacy/display-email identity cannot grant
 # a second write. Replay is either the existing receipt or own-ID GET only.
 if not v['scene'].startswith('recover-'):
  try:
   replay=(await adapter._haos_google_publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],metadata) if v['publisher'] else
    await files.send('f'*64,route,source,artifact,projection['text'],binding['thread'],checked))
   assert replay.success and v['scene'] in {'active','callback-no-client','create-disconnect','response-mismatch','publisher','local-logout'}
  except Exception:
   assert v['scene'] in {'upload-auth','upload-rate','upload-disconnect','create-auth','create-rate'}
 for action in [lambda:adapter._send_file(binding['chat'],'/root/owner-oauth-parent.py',None,None),lambda:adapter._post_attachment_fallback(binding['chat'],'/owner/private','private',None,None)]:
  try:await action()
  except PermissionError:pass
  else:raise AssertionError('unscoped native file/fallback call accepted')
 if v['scene'] in {'upload-auth','create-auth','upload-rate','create-rate'}:
  status=oauth_inbox.db.execute('SELECT status FROM google_chat_oauth_transport').fetchone()[0]
  assert status==('rate-limited' if v['scene'].endswith('rate') else 'authentication-refused')
  if v['scene'].endswith('rate'):assert oauth_inbox.db.execute('SELECT not_before FROM google_chat_oauth_budget').fetchone()[0]>__import__('time').time()+170
 print(json.dumps({'scene':v['scene'],'initial_state':initial,'final_state':inbox.db.execute('SELECT state FROM google_chat_file_writes').fetchone()[0],
  'actual_private_UID_native_MediaFileUpload_sealed_Root_bytes_and_Google_discovery':True,'own_echo_blocked_before_create_response':expect_echo,
  'Root_artifact_methods_are_explicit_fixtures':not v['publisher'],'controller_Unix_IPC_not_exercised':True,'actual_source_codec_relay_controller_export_and_private_publisher_components':v['publisher'],'no_arbitrary_host_path_fallback_or_legacy_email_identity':True}))
try:asyncio.run(run())
finally:
 signal.close()
 if v['publisher']:asyncio.run(adapter.close_profile())
 else:originals.close();os.close(lease)
 oauth_inbox.close();inbox.close()
''');driver.chmod(0o644)
    try:
        for uid,gid,groups in [(0,0,[]),(65533,65533,[]),(65534,65534,[0])]:
            result=subprocess.run([str(runtime/'bin/python'),'-E','-s',str(driver)],capture_output=True,text=True,user=uid,group=gid,extra_groups=groups,cwd=str(code),env=env,timeout=10)
            assert result.returncode==3 and result.stdout=='denied-before-SDK\n',result.stderr
        session=owner_call('begin',{'binding_id':'owner','configuration':configuration,'note':'explicit file fixture enrollment','confirmed':True})
        authorizations['owner-good-account']=parse_qs(urlsplit(session['authorization_url']).query)
        callback=REDIRECT_URI+'/?'+urlencode({'code':'owner-good-account','state':authorizations['owner-good-account']['state'][0]})
        enrolled=owner_call('finish',{'session':session,'returned_url':callback,'confirmed':True});assert enrolled['status']=='active'
        params={'account':value,'policy':policy,'profile':str(profile_directory),'data_hex':body_bytes.hex(),'scene':scene,'signal':child_signals.fileno(),'agent_port':agent.server_port,'publisher':publisher,'phase':1,'native_database':str(native_database)}
        def execute_child(number):
            phase['value']=number;params['phase']=number
            child=subprocess.Popen([str(runtime/'bin/python'),'-E','-s',str(driver)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                user=65534,group=65534,extra_groups=[],umask=0o077,cwd=str(code),env=env,pass_fds=(child_signals.fileno(),))
            stdout,stderr=child.communicate(json.dumps(params),timeout=60)
            assert child.returncode==0,(stdout,stderr)
            for secret_value in [configuration['installed']['client_secret'],'owner-private-access-fixture','owner-private-refresh-fixture','private-native-upload-reference-fixture','owner-private-bot-access-fixture']:
                assert secret_value not in stdout+stderr
            assert not stderr,stderr
            return json.loads(stdout)
        receipt=execute_child(1);phases=[receipt];decisions=[]
        if scene.startswith('recover-'):
            item=owner_call('file-inspect',{'action':'files'})['files'][0]
            if scene=='recover-output-purge':
                if os.environ.get('HAOS_GOOGLE_CHAT_HISTORICAL_OUTPUT'):
                    sys.path.insert(0,'/repo/linux/haos/runtime')
                    from google_chat_historical_output_fixture import exercise as historical_output
                    decisions.append(historical_output(mode=os.environ['HAOS_GOOGLE_CHAT_HISTORICAL_OUTPUT'],runtime=runtime,code=code,env=env,
                        publication=publication,secret=secret,policy=policy,value=value,native_database=native_database,database=database,requests=requests))
                else:
                    assert item['state']=='confirmed';before=len(requests);policy['bindings']=[];publication.write_text(json.dumps(policy))
                    output=owner_call('file-inspect',{'action':'outputs'})['outputs'][0]
                    disposed=owner_call('output-purge',{'row':output,'note':'explicit withdrawn local copy disposal','confirmed':True})
                    assert disposed['tombstones_retained'] and not disposed['remote_deletion_verified'] and not disposed['network_requested']
                    assert owner_call('output-purge',{'row':output,'note':'explicit withdrawn local copy disposal','confirmed':True})==disposed
                    assert len(requests)==before;decisions.append(disposed)
            else:
                action='retry-upload' if scene=='recover-upload' else 'retry-file';before=len(requests)
                approved=owner_call('file-retry',{'row':item,'action':action,'note':'independent fixture source and non-delivery inspection','confirmed':True,'confirmed_not_delivered':action=='retry-file'})
                assert approved['approval_recorded'] and not approved['network_requested'] and not approved['message_sent'] and len(requests)==before
                decisions.append(approved);phases.append(execute_child(2))
                old=owner_call('file-retry',{'row':item,'action':action,'note':'independent fixture source and non-delivery inspection','confirmed':True,'confirmed_not_delivered':action=='retry-file'})
                assert old==approved
                if scene in {'recover-read-disconnect','recover-read-body'}:
                    with sqlite3.connect(native_database) as db:
                        assert db.execute("SELECT state FROM google_chat_file_owner_events WHERE action='retry-file'").fetchone()[0]=='reconciling'
                        assert db.execute('SELECT state FROM google_chat_file_writes').fetchone()[0]=='writing'
                    phases.append(execute_child(3));assert requests.count('create')==1
                else:assert phases[-1]['final_state']=='confirmed'
            assert requests.count('upload')==(2 if scene=='recover-upload' else 1)
            assert requests.count('create')==(2 if scene=='recover-create' else 1)
            assert requests.count('read-own-write')==(2 if scene in {'recover-read-disconnect','recover-read-body'} else 1 if scene in {'recover-create','recover-late'} else 0)
        else:
            assert requests.count('upload')==1 and requests.count('create')==(0 if scene.startswith('upload-') else 1)
            assert requests.count('read-own-write')==(1 if scene in {'create-disconnect','response-mismatch'} else 0)
        if publisher:
            assert requests.count('bot-token')==len(phases) and requests.count('bot-membership')==len(phases) and requests.count('agent-session-artifact-read')==1
            assert requests.count('bot-text-create')==(0 if scene in {'recover-read-disconnect','recover-read-body'} else 1)
        print(json.dumps({'scene':scene,'passed':1,'process':receipt,'private_process_phases':phases,'actual_Root_offline_decisions':decisions,'observed_operations':requests,
            'actual_Root_OAuth_then_private_UID_native_file_SDK_TLS_and_FULL_journals':True,'all_endpoints_CA_DNS_namespace_local':True,
            'PubSub_profile_and_production_controller_Unix_IPC_not_tested':True,'systemctl_and_agent_artifact_service_are_explicit_fixtures':True,'actual_RSA_service_account_bot_identity_check':publisher,
            'live_Google_account_external_delivery_production_IPC_or_public_activation':False},indent=2))
    finally:signals.close();child_signals.close();server.shutdown();server.server_close();thread.join(timeout=2);agent.shutdown();agent.server_close();agent_thread.join(timeout=2)


if __name__=='__main__':main()
