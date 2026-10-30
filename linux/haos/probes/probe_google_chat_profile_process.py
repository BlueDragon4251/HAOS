"""Actual private UID Google callback TLS, SDK JWT and pre-response custody."""
import asyncio
import datetime
import json
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
from urllib.parse import urlsplit,parse_qs


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_PROFILE_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh explicit readonly disposable namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    prepared=Path('/repo/upstream/hermes-agent')
    assert (prepared/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    staged=Path(tempfile.mkdtemp(prefix='haos-google-profile-source-'))
    shutil.copytree(prepared,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py',str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/deps',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    from google.auth import crypt,jwt
    from haos.gateway_google_chat import scope
    from haos.gateway import digest
    now=datetime.datetime.now(datetime.timezone.utc);directory=Path(tempfile.mkdtemp(prefix='haos-google-http-process-'));directory.chmod(0o755)
    profile=directory/'private';profile.mkdir(mode=0o700);os.chown(profile,65534,65534)
    owner=directory/'owner-canary';owner.write_text('private owner fixture data');owner.chmod(0o600)
    ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048);ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable Google HTTP fixture CA')])
    ca=x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
        now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True,path_length=0),True).add_extension(
        x509.KeyUsage(True,False,False,False,False,True,True,False,False),True).add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),False).sign(ca_key,hashes.SHA256())
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);host='haos-google.fixture.invalid'
    cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,host)])).issuer_name(ca_name).public_key(key.public_key()).serial_number(
        x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(
        x509.BasicConstraints(ca=False,path_length=None),True).add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),True).add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False).add_extension(x509.SubjectAlternativeName([x509.DNSName(host),x509.DNSName('localhost')]),False).add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),False).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).sign(ca_key,hashes.SHA256())
    ca_bytes=ca.public_bytes(serialization.Encoding.PEM)
    with Path(ssl.get_default_verify_paths().cafile).open('ab') as stream:stream.write(b'\n'+ca_bytes)
    caller_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    caller_private=caller_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    signer=crypt.RSASigner.from_string(caller_private,key_id='local-google-caller')
    caller_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'local-google-caller')])
    caller_cert=x509.CertificateBuilder().subject_name(caller_name).issuer_name(caller_name).public_key(caller_key.public_key()).serial_number(2).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).sign(caller_key,hashes.SHA256())
    caller_public=caller_cert.public_bytes(serialization.Encoding.PEM).decode()
    audience='https://'+host+'/google-chat';email='gateway@haos-fixture.iam.gserviceaccount.com';caller='chat-caller@haos-fixture.iam.gserviceaccount.com'
    with socket.socket() as held:held.bind(('127.0.0.1',0));port=held.getsockname()[1]
    service_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    service_private=service_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    service_public=service_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    ca_file=directory/'ca.pem';ca_file.write_bytes(ca_bytes);ca_file.chmod(0o644)
    value={'service_account':{'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':service_private,'client_email':email,'client_id':'123456789',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},'bot_user':'users/999',
        'inbound':{'mode':'http','port':port,'audience':audience,'service_account_email':caller,'tls':{
            'public_url':audience,'certificate':cert.public_bytes(serialization.Encoding.PEM).decode(),
            'private_key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),
            'bind_host':'127.0.0.1','public_listener':False}}}
    binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
        'scope':scope(value),'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':int(now.timestamp()*1000)-60000}
    policy={'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]}
    publication=directory/'policy.json';publication.write_text(json.dumps(policy));publication.chmod(0o644)
    original_path=profile/('google-chat-'+digest(scope(value)))/'originals.sqlite'
    scenario=os.environ.get('HAOS_GOOGLE_CHAT_PROFILE_ACCOUNT','active')
    if scenario not in {'active','auth','rate','tokenrate','sendauth','media','mediaauth','mediarate','mediarange','medialarge'}:raise ValueError('finite private profile fixture scenario required')
    if scenario in {'media','mediaauth','mediarate','mediarange','medialarge'}:
        binding['allow_media']=True;publication.write_text(json.dumps(policy));publication.chmod(0o644)
    import base64
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF10AAAAASUVORK5CYII=')
    api_calls=[];api_requests=[]
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def response(self,data):
            raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            api_requests.append(('POST',urlsplit(self.path).path))
            if urlsplit(self.path).path=='/v1/spaces/room1/messages':
                assert self.headers.get('Authorization')=='Bearer local-profile-google-fixture-token'
                query=parse_qs(urlsplit(self.path).query);body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with sqlite3.connect(profile/'native.sqlite') as db:
                    assert db.execute('SELECT state FROM google_chat_text_writes WHERE client_id=?',(query['messageId'][0],)).fetchone()[0]=='writing'
                assert query['messageReplyOption']==['REPLY_MESSAGE_OR_FAIL'] and body['thread']['name']==binding['thread']
                if scenario=='sendauth':
                    api_calls.append('native-message-auth-refused');data=json.dumps({'error':{'code':401,'message':'local-profile-google-fixture-token'}}).encode()
                    self.send_response(401);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                api_calls.append('native-message-create')
                self.response({'name':'spaces/room1/messages/server.'+str(api_calls.count('native-message-create')),
                    'clientAssignedMessageId':query['messageId'][0],'text':body['text'],'thread':body['thread']});return
            assert self.path=='/oauth-token' and not self.headers.get('Authorization')
            values=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            assert values['grant_type']==['urn:ietf:params:oauth:grant-type:jwt-bearer']
            claims=jwt.decode(values['assertion'][0],certs={'a'*40:service_public},audience='https://oauth2.googleapis.com/token')
            assert claims['iss']==email and set(claims['scope'].split())=={'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'}
            if scenario=='tokenrate':
                data=json.dumps({'error':'rate_limit_exceeded','error_description':'local-profile-google-fixture-token'}).encode()
                self.send_response(429);self.send_header('Retry-After','180');self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            api_calls.append('actual-SDK-RSA-token-grant');self.response({'access_token':'local-profile-google-fixture-token','token_type':'Bearer','expires_in':3600})
        def do_GET(self):
            api_requests.append(('GET',urlsplit(self.path).path))
            if scenario in {'auth','rate'}:
                code=401 if scenario=='auth' else 429
                data=json.dumps({'error':{'code':code,'message':'local-profile-google-fixture-token'}}).encode()
                self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                if scenario=='rate':self.send_header('Retry-After','180')
                self.end_headers();self.wfile.write(data);return
            if urlsplit(self.path).path.startswith('/v1/media/'):
                assert scenario in {'media','mediaauth','mediarate','mediarange','medialarge'} and self.headers.get('Authorization')=='Bearer local-profile-google-fixture-token'
                assert urlsplit(self.path).path in ['/v1/media/spaces/room1/messages/'+mid+'/attachments/resource1' for mid in ['shared','diskretry']]
                assert parse_qs(urlsplit(self.path).query)=={'alt':['media']} and self.headers.get('Range')=='bytes=0-524287'
                if scenario in {'mediaauth','mediarate'}:
                    code=401 if scenario=='mediaauth' else 429;api_calls.append('native-media-'+str(code))
                    body=json.dumps({'error':{'code':code,'message':'local-profile-google-fixture-token'}}).encode()
                    self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                    if code==429:self.send_header('Retry-After','180')
                    self.end_headers();self.wfile.write(body);return
                if scenario in {'mediarange','medialarge'}:
                    api_calls.append('native-media-bound-refused');self.send_response(206);self.send_header('Content-Type','image/png')
                    self.send_header('Content-Length',str(9*1024*1024) if scenario=='medialarge' else str(len(image)))
                    self.send_header('Content-Range','bytes 1-'+str(len(image))+'/'+str(len(image)+1))
                    self.end_headers()
                    if scenario=='mediarange':self.wfile.write(image)
                    return
                api_calls.append('native-media-download');self.send_response(206);self.send_header('Content-Type','image/png')
                self.send_header('Content-Length',str(len(image)));self.send_header('Content-Range','bytes 0-'+str(len(image)-1)+'/'+str(len(image)))
                self.end_headers();self.wfile.write(image);return
            assert urlsplit(self.path).path=='/v1/spaces/room1/members/999'
            assert self.headers.get('Authorization')=='Bearer local-profile-google-fixture-token'
            api_calls.append('own-bot-membership');self.response({'name':'spaces/room1/members/999','state':'MEMBER','member':{'name':'users/999','type':'BOT'}})
    cert_file=directory/'api-cert.pem';key_file=directory/'api-key.pem'
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM));key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_file.chmod(0o600)
    api_server=ThreadingHTTPServer(('127.0.0.1',0),API);api_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);api_tls.load_cert_chain(cert_file,key_file)
    api_server.socket=api_tls.wrap_socket(api_server.socket,server_side=True)
    api_thread=threading.Thread(target=api_server.serve_forever,daemon=True);api_thread.start()
    driver=directory/'driver.py';driver.write_text('''import asyncio,json,sys
from pathlib import Path
from haos.gateway_runtime import require_runtime_identity
try:require_runtime_identity()
except PermissionError:
    from haos.gateway_google_chat_profile import build as denied_build
    try:denied_build(None,parent='/tmp',connector='unapproved',policy=lambda:None,inbox=None)
    except PermissionError:pass
    else:raise AssertionError('private profile factory accepted wrong UID')
    from haos.gateway_google_chat_resources import download
    try:asyncio.run(download(None,None,None))
    except PermissionError:pass
    else:raise AssertionError('foreign UID entered Google media SDK')
    assert 'google.oauth2.id_token' not in sys.modules and 'googleapiclient.http' not in sys.modules
    print(json.dumps({'denied_before_optional_SDK':True}));raise SystemExit(3)
from haos.gateway_google_chat import PreparedGoogleChatPolicy
from haos.gateway_google_chat_profile import build
from haos.gateway_google_chat_auth import CERTS
from haos.gateway_google_chat_http import single_request_http,token_response
from haos.gateway_raw import NativeInbox
from haos.gateway_relay import RelayInbox
from haos.gateway_runtime import adapter_envelope,delivery_metadata
from haos.controller import Controller
from haos.store import MissionStore
from haos.redaction import Redactor
from types import SimpleNamespace,MethodType
from urllib.parse import urlsplit
from google_auth_httplib2 import AuthorizedHttp
import os
v=json.load(sys.stdin);publication=Path(v['policy']);initial=publication.read_bytes();parent=Path(v['profile'])
launcher=parent/'launcher';launcher.mkdir(mode=0o700,exist_ok=True);os.environ['HERMES_HOME']=str(launcher)
def policy():return PreparedGoogleChatPolicy(json.loads(publication.read_text()))
try:Path(v['owner']).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read owner data')
async def run():
    inbox=NativeInbox(parent/'native.sqlite',Redactor([]));relay=RelayInbox(parent/'relay.sqlite',inbox.redactor)
    adapter=build(v['value'],parent=parent,connector='google',policy=policy,inbox=inbox)
    component=MissionStore(parent/'controller-component.sqlite');controller=Controller(component,'ws://127.0.0.1:9119/api/ws',{65534})
    try:
        try:build(v['value'],parent=parent,connector='google',policy=policy,inbox=inbox)
        except PermissionError:pass
        else:raise AssertionError('parallel identity lease accepted')
        def receive(event):
            assert event.raw_message is None and 'opaque-private-upload-reference-fixture' not in event.text
            from haos.gateway_media_relay import event_media
            relay.admit(policy(),'google',adapter_envelope(event,'google_chat'),media=event_media(event,'google_chat'));return True
        adapter.set_durable_message_handler(receive)
        current=adapter._haos_google_check;origin='https://localhost:'+str(v['api_port'])
        def http(self,authority=None):
            selected=authority or current
            selected();base=single_request_http(selected,fixture_origin=origin,limit=8*1024*1024 if authority else 1048576,redactor=inbox.redactor);base.ca_certs=v['ca']
            class Routed:
                def __getattr__(self,key):return getattr(base,key)
                def request(self,uri,method='GET',body=None,headers=None,**kwargs):
                    if uri=='https://oauth2.googleapis.com/token':target=origin+'/oauth-token'
                    else:
                        parsed=urlsplit(uri);assert parsed.scheme=='https' and parsed.hostname=='chat.googleapis.com'
                        target=origin+parsed.path+('?' + parsed.query if parsed.query else '')
                    response,data=base.request(target,method=method,body=body,headers=headers,**kwargs)
                    return token_response(uri,response,data)
            return AuthorizedHttp(self._credentials,http=Routed(),max_refresh_attempts=0)
        adapter._new_authed_http=MethodType(http,adapter)
        adapter._haos_google_media_http=MethodType(lambda self,authority:http(self,authority),adapter)
        if v['scenario'] in {'auth','rate','tokenrate'}:
            assert not await adapter.connect() and not adapter.is_connected
            expected='authentication-refused' if v['scenario']=='auth' else 'rate-limited'
            assert adapter.native_health()['status']==expected
            wait=adapter.native_health()['next_attempt']
            if v['scenario'] in {'rate','tokenrate'}:assert wait>=__import__('time').time()+175
            await adapter.disconnect();assert adapter.native_health()['next_attempt']>=wait
            await adapter.close_profile()
            selected=v['value']
            if v['scenario'] in {'rate','tokenrate'}:
                from cryptography.hazmat.primitives.asymmetric import rsa
                from cryptography.hazmat.primitives import serialization
                replacement=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
                selected={**selected,'service_account':{**selected['service_account'],'private_key_id':'b'*40,'private_key':replacement}}
            adapter=build(selected,parent=parent,connector='google',policy=policy,inbox=inbox);current=adapter._haos_google_check
            adapter._new_authed_http=MethodType(http,adapter)
            if v['scenario']=='auth':await asyncio.sleep(2.1)
            assert not await adapter.connect() and not adapter.is_connected
            if v['scenario'] in {'rate','tokenrate'}:assert adapter.native_health()['next_attempt']>=wait
            else:assert adapter.native_health()['status']==expected
            print(json.dumps({'blocked':True,'expected':expected}),flush=True);return
        assert await adapter.connect(),adapter.native_health()
        assert adapter.is_connected and adapter.native_health()['status']=='listening-tls'
        await adapter.disconnect();assert not adapter.is_connected and adapter.native_health()['status']=='disconnected'
        assert await adapter.connect() and adapter.is_connected and adapter.native_health()['status']=='listening-tls'
        def certificates(url,method='GET',**kwargs):
            current();assert url==CERTS and method=='GET' and not kwargs
            return SimpleNamespace(status=200,data=json.dumps({'local-google-caller':v['caller_public']}).encode())
        adapter._haos_google_receiver.http_verifier.request=certificates
        print(json.dumps({'ready':True}),flush=True)
        while True:
            if adapter.is_connected:
                incoming=relay.next(policy())
                if incoming:
                    from haos.gateway_media_relay import forward,MediaCache
                    async def local_call(method,params):
                        if method=='gateway.media.begin':return controller.gateway.media.begin(policy(),params)
                        if method=='gateway.media.chunk':return controller.gateway.media.chunk(policy(),params)
                        assert method=='gateway.receive'
                        return await controller.gateway.receive(policy(),params['connector'],params['envelope'],controller,media=params.get('media'))
                    received=await forward(policy,'google',incoming['envelope'],incoming['media'],MediaCache(inbox),local_call)
                    if incoming['media']:
                        prepared=controller.gateway.media.for_mission(policy(),received['mission_id'])
                        assert len(prepared)==1 and prepared[0]['descriptor']['kind']=='image'
                        assert prepared[0]['data']==__import__('base64').b64decode(v['image'])
                    relay.admitted(incoming['id'],received['mission_id'])
                delivery=controller.gateway.next_delivery(policy())
                if delivery:
                    metadata=delivery_metadata(delivery,'google_chat')
                    try:result=await adapter.send(delivery['chat'],delivery['content'],reply_to=delivery['reply_to'],metadata=metadata)
                    except PermissionError:
                        if v['scenario']!='sendauth':raise
                        result=None
                    if v['scenario']=='sendauth':assert result is None or not result.success
                    else:
                        assert result.success
                        controller.gateway.acknowledge(policy(),delivery['id'],{'status':'delivered','message_id':result.message_id,'attempt':delivery['attempt']})
            state={'status':adapter.native_health()['status'],'connected':adapter.is_connected,
                'parent_records':relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0],
                'confirmed_outputs':inbox.db.execute("SELECT COUNT(*) FROM google_chat_delivery_groups WHERE state='confirmed'").fetchone()[0]}
            marker=parent/'profile-status.tmp';marker.write_text(json.dumps(state));marker.replace(parent/'profile-status.json')
            await asyncio.sleep(.05)
    finally:await adapter.close_profile();inbox.close();relay.close();component.close()
asyncio.run(run())
''');driver.chmod(0o755)
    def event(mid='shared',sender='users/123'):
        result={'type':'MESSAGE','space':{'name':'spaces/room1','spaceType':'DIRECT_MESSAGE'},'message':{
            'name':'spaces/room1/messages/'+mid,'thread':{'name':binding['thread']},'sender':{'type':'HUMAN','name':sender},
            'createTime':now.isoformat().replace('+00:00','Z'),'text':'Create a local plan'}}
        if scenario in {'media','mediaauth','mediarate','mediarange','medialarge'}:
            resource=result['message']['name']+'/attachments/resource1'
            result['message']['attachment']=[{'name':resource,'attachmentDataRef':{'resourceName':resource,'attachmentUploadToken':'opaque-private-upload-reference-fixture'},'contentType':'image/png',
                'downloadUri':'https://foreign-fixture.invalid/never-fetch'}]
        return result
    claims={'iss':'https://accounts.google.com','aud':audience,'sub':'123456789','email':caller,'email_verified':True,
        'iat':int(now.timestamp()),'exp':int(now.timestamp())+3600}
    def token(change=None):return jwt.encode(signer,{**claims,**(change or {})}).decode()
    request={'value':value,'profile':str(profile),'policy':str(publication),'owner':str(owner),'caller_public':caller_public,'api_port':api_server.server_port,'ca':str(ca_file),'scenario':scenario,'image':base64.b64encode(image).decode()}
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'};cases=[]
    for uid,groups in [(0,()),(65533,()),(65534,(0,))]:
        result=subprocess.run([str(runtime/'bin/python'),'-E','-s',str(driver)],input=json.dumps(request).encode(),capture_output=True,
            timeout=15,user=uid,group=uid,extra_groups=list(groups),cwd=str(code),env=env,umask=0o077)
        assert result.returncode==3 and json.loads(result.stdout)=={'denied_before_optional_SDK':True}
    cases.append('actual_root_agent_UID_and_supplementary_root_group_refused_before_optional_token_SDK_or_listener')
    async def exercise():
        from aiohttp import ClientSession,TCPConnector
        child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(driver),stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,user=65534,group=65534,extra_groups=[],cwd=str(code),env=env,umask=0o077)
        child.stdin.write(json.dumps(request).encode());await child.stdin.drain();child.stdin.close()
        try:
            line=await asyncio.wait_for(child.stdout.readline(),20)
            if scenario in {'auth','rate','tokenrate'}:
                result=json.loads(line)
                assert result=={'blocked':True,'expected':'authentication-refused' if scenario=='auth' else 'rate-limited'}
                assert len(api_requests)==(1 if scenario=='tokenrate' else 2) and api_calls==([] if scenario=='tokenrate' else ['actual-SDK-RSA-token-grant'])
                if scenario=='auth':cases.append('actual_SDK_HTTP401_is_finite_sticky_auth_refusal_across_profile_close_reopen_without_another_OAuth_or_account_request')
                elif scenario=='tokenrate':cases.append('actual_Google_service_account_SDK_token_endpoint_HTTP429_makes_one_RSA_grant_attempt_without_hidden_SDK_retry_and_retains_RetryAfter_across_close_reopen_key_rotation')
                else:cases.append('actual_SDK_HTTP429_RetryAfter180_survives_disconnect_close_reopen_and_same_account_RSA_key_rotation_without_any_new_network_request')
                return
            if line!=b'{"ready": true}\n':raise AssertionError((await child.stderr.read()).decode()[-1800:])
            context=ssl.create_default_context(cadata=ca_bytes.decode())
            async with ClientSession(connector=TCPConnector(ssl=context),trust_env=False) as client:
                async def send(data=None,headers=None,path='/google-chat'):
                    async with client.post('https://localhost:'+str(port)+path,json=data or event(),headers=headers if headers is not None else {'Authorization':'Bearer '+token()}) as response:
                        body=await response.read();assert b'BEGIN PRIVATE KEY' not in body and b'local-google-caller' not in body
                        return response.status,body
                assert await send()==(200,b'{}')
                if scenario in {'mediarange','medialarge'}:
                    deadline=asyncio.get_running_loop().time()+5
                    while True:
                        state=json.loads((profile/'profile-status.json').read_text())
                        if state['status']=='transport-unavailable':break
                        assert asyncio.get_running_loop().time()<deadline;await asyncio.sleep(.05)
                    assert state['parent_records']==0 and state['confirmed_outputs']==0
                    assert api_calls==['actual-SDK-RSA-token-grant','own-bot-membership']*2+['native-media-bound-refused']
                    with sqlite3.connect(profile/'native.sqlite') as db:assert db.execute('SELECT COUNT(*) FROM native_media_cache').fetchone()[0]==0
                    cases.append('actual_private_UID_Google_media_SDK_'+scenario+'_is_refused_before_blob_parent_mission_or_reply_and_never_falls_back_to_foreign_download_URI')
                    return
                if scenario in {'mediaauth','mediarate'}:
                    deadline=asyncio.get_running_loop().time()+5
                    expected='authentication-refused' if scenario=='mediaauth' else 'rate-limited'
                    while True:
                        state=json.loads((profile/'profile-status.json').read_text())
                        if state['status']==expected and (scenario!='mediaauth' or not state['connected']):break
                        assert asyncio.get_running_loop().time()<deadline;await asyncio.sleep(.05)
                    expected_calls=['actual-SDK-RSA-token-grant','own-bot-membership']*2+['native-media-'+('401' if scenario=='mediaauth' else '429')]
                    assert api_calls==expected_calls
                    with sqlite3.connect(original_path) as db:assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
                    if scenario=='mediaauth':
                        try:await send(event('after-auth-refusal'))
                        except OSError:pass
                        else:raise AssertionError('resource authentication failure left listener active')
                        cases.append('actual_private_UID_native_media_SDK_HTTP401_preserves_original_custody_and_sticky_auth_block_then_stops_profile_and_TLS_listener_without_creating_a_mission_or_reply')
                    else:
                        with sqlite3.connect(profile/'native.sqlite') as db:
                            wait=db.execute('SELECT next_attempt FROM google_chat_profile_status').fetchone()[0]
                            assert wait>=__import__('time').time()+175
                            assert db.execute('SELECT not_before FROM google_chat_profile_budget').fetchone()[0]>=wait
                        await asyncio.sleep(.6);assert api_calls==expected_calls
                        cases.append('actual_private_UID_native_media_SDK_HTTP429_has_one_GET_attempt_and_persistent_account_RetryAfter_without_mission_reply_or_automatic_download_retry')
                    return
                if scenario=='sendauth':
                    deadline=asyncio.get_running_loop().time()+5
                    while True:
                        state=json.loads((profile/'profile-status.json').read_text())
                        if state['status']=='authentication-refused' and state['connected'] is False:break
                        assert asyncio.get_running_loop().time()<deadline;await asyncio.sleep(.05)
                    assert api_calls==['actual-SDK-RSA-token-grant','own-bot-membership']*2+['native-message-auth-refused']
                    try:await send(event('after-auth-refusal'))
                    except OSError:pass
                    else:raise AssertionError('outgoing auth failure left inbound profile running')
                    cases.append('actual_native_reply_HTTP401_stops_entire_private_profile_and_TLS_listener_preserves_sticky_auth_error_and_never_exposes_reflected_bearer_or_repeats_post')
                    return
                assert await send()==(200,b'{}')
                with sqlite3.connect(original_path) as db:assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
                cases.append('actual_private_UID_listener_verifies_system_trusted_TLS_material_and_Google_SDK_RSA_token_then_returns_HTTP200_only_after_FULL_original_custody_and_replay_keeps_one_original')
                assert await send(event('unknown','users/456'))==(200,b'{}')
                with sqlite3.connect(original_path) as db:
                    assert db.execute('SELECT COUNT(*) FROM google_chat_source_refusals').fetchone()[0]==1
                    assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
                cases.append('authenticated_unknown_sender_receives_only_durable_hash_refusal_without_native_decode_or_mission_rights')
                for index,headers in enumerate([{},
                        {'Authorization':'Bearer '+token({'aud':'https://other.invalid'})},
                        {'Authorization':'Bearer '+token({'email':'other@haos-fixture.iam.gserviceaccount.com'})}]):
                    status,_=await send(headers=headers);assert status==401,('auth-case',index,status)
                # ClientSession normalizes case-varied duplicate headers.
                # Use actual TLS framing for this independent ambiguity test.
                reader,writer=await asyncio.open_connection('localhost',port,ssl=context,server_hostname='localhost')
                body=json.dumps(event()).encode();bearer=token()
                frame=('POST /google-chat HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n'
                    'Authorization: Bearer '+bearer+'\r\nauthorization: Bearer '+bearer+'\r\nContent-Length: '+str(len(body))+'\r\nConnection: close\r\n\r\n').encode()+body
                writer.write(frame);await writer.drain()
                status=await asyncio.wait_for(reader.readline(),5);assert status.split()[1]==b'401'
                await asyncio.wait_for(reader.read(),5);writer.close();await writer.wait_closed()
                cases.append('actual_TLS_callback_refuses_missing_duplicate_wrong_audience_and_wrong_caller_tokens_without_body_admission_or_secret_errors')
                with sqlite3.connect(original_path) as db:db.execute("CREATE TRIGGER fail_original BEFORE INSERT ON google_chat_originals BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END")
                status,_=await send(event('diskfail'));assert status==503
                with sqlite3.connect(original_path) as db:
                    assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1;db.execute('DROP TRIGGER fail_original')
                assert await send(event('diskretry'))==(200,b'{}')
                cases.append('actual_SQL_failure_returns_retryable_HTTP503_without_success_ACK_and_next_inspected_source_can_be_retained')
                status,_=await send(path='/google-chat?unapproved=1');assert status==400
                status,_=await send(path='/plugins/arbitrary');assert status==404
                cases.append('only_fixed_query_free_callback_path_is_exposed_no_arbitrary_plugin_listener')
                deadline=asyncio.get_running_loop().time()+5
                while True:
                    state=json.loads((profile/'profile-status.json').read_text())
                    if state['parent_records']==2 and state['confirmed_outputs']==2:break
                    assert asyncio.get_running_loop().time()<deadline;await asyncio.sleep(.05)
                base_calls=[call for call in api_calls if call!='native-media-download']
                assert base_calls==['actual-SDK-RSA-token-grant','own-bot-membership']*2+['native-message-create']*2
                if scenario=='media':
                    assert api_calls.count('native-media-download')==2
                    with sqlite3.connect(profile/'native.sqlite') as db:
                        assert db.execute('SELECT COUNT(*) FROM google_chat_input_media').fetchone()[0]==2
                    with sqlite3.connect(profile/'controller-component.sqlite') as db:
                        assert db.execute("SELECT COUNT(*) FROM gateway_media_uploads WHERE state='attached'").fetchone()[0]==2
                    cases.append('actual_private_UID_source_bound_Google_discovery_MediaIoBaseDownload_TLS_GET_native_attachment_codec_FULL_retention_and_real_controller_media_begin_chunk_receive_attach_preserve_exact_PNG_bytes_with_no_foreign_downloadURI_fetch_or_duplicate_download_on_replay')
                cases.append('actual_private_profile_connect_runs_native_service_account_RSA_refresh_and_verified_local_TLS_own_bot_membership_check_before_listening_then_native_replay_admits_two_unique_parent_records')
                cases.append('actual_private_profile_receive_replay_real_controller_component_event_context_and_native_SDK_TLS_reply_form_one_loop_with_FULL_prewrite_custody_and_two_unique_confirmed_outputs')
                cases.append('actual_native_profile_disconnect_and_reconnect_close_and_rebind_TLS_with_the_same_private_lease_and_journals_and_fresh_real_SDK_account_auth_checks')
                publication.write_text(json.dumps({**policy,'bindings':[]}));deadline=asyncio.get_running_loop().time()+5
                while True:
                    state=json.loads((profile/'profile-status.json').read_text())
                    if state['status']=='revoked' and state['connected'] is False:break
                    assert asyncio.get_running_loop().time()<deadline;await asyncio.sleep(.05)
                try:await send(event('withdrawn'))
                except OSError:pass
                else:raise AssertionError('revoked private profile listener remained reachable')
                with sqlite3.connect(original_path) as db:assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==2
                cases.append('actual_root_publication_withdrawal_stops_native_profile_and_TLS_listener_without_another_callback_message_or_success_ACK')
        finally:
            if child.returncode is None:child.terminate()
            _,stderr=await asyncio.wait_for(child.communicate(),10)
            assert b'BEGIN PRIVATE KEY' not in stderr and token().encode() not in stderr
    try:asyncio.run(exercise())
    finally:api_server.shutdown();api_server.server_close();api_thread.join(timeout=2)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_gateway_UID_private_profile_native_lifecycle_RSA_OAuth_TLS_listener_and_FULL_SQLite':True,
        'Google_certificate_endpoint_and_OAuth_service_account_are_explicit_fixtures':True,
        'actual_native_controller_component_outbox_and_TLS_replies':scenario in {'active','sendauth','media'},
        'actual_image_SDK_TLS_native_codec_retention_and_controller_component_transfer':scenario=='media',
        'root_controller_IPC_local_ASR_video_decode_GUI_live_Google_account_or_public_activation':False},indent=2))


if __name__=='__main__':main()
