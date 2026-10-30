"""Actual private UID Google callback TLS, SDK JWT and pre-response custody."""
import asyncio
import datetime
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_HTTP_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh explicit readonly disposable namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/fixture.pth').write_text('/sdk\n/usr/lib/haos\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/deps',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    from google.auth import crypt,jwt
    from haos.gateway_google_chat import scope
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
    value={'service_account':{'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n','client_email':email,'client_id':'123456789',
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
    driver=directory/'driver.py';driver.write_text('''import asyncio,json,sys
from pathlib import Path
from haos.gateway_runtime import require_runtime_identity
try:require_runtime_identity()
except PermissionError:
    assert 'google.oauth2.id_token' not in sys.modules
    print(json.dumps({'denied_before_optional_SDK':True}));raise SystemExit(3)
from haos.gateway_google_chat import PreparedGoogleChatPolicy
from haos.gateway_google_chat_custody import Originals
from haos.gateway_google_chat_receive import Receiver
from haos.gateway_google_chat_auth import TokenVerifier,CERTS
from haos.gateway_google_chat_listener import application
from haos.gateway_line_tls import context
from haos.redaction import Redactor
from types import SimpleNamespace
from aiohttp import web
v=json.load(sys.stdin);publication=Path(v['policy']);initial=publication.read_bytes()
def current():
    require_runtime_identity()
    if publication.read_bytes()!=initial:raise PermissionError('publication withdrawn')
try:Path(v['owner']).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read owner data')
def certificates(url,method='GET',**kwargs):
    current();assert url==CERTS and method=='GET' and not kwargs
    return SimpleNamespace(status=200,data=json.dumps({'local-google-caller':v['caller_public']}).encode())
async def run():
    store=Originals(Path(v['profile'])/'originals.sqlite',Redactor([]));inbound=v['value']['inbound']
    verifier=TokenVerifier(inbound['audience'],inbound['service_account_email'],current,certificate_request=certificates)
    receiver=Receiver('google',v['value'],store,lambda:PreparedGoogleChatPolicy(json.loads(publication.read_text())),current,http_verifier=verifier)
    tls=context(inbound['tls'],v['profile'],webhook_path='/google-chat')
    runner=web.AppRunner(application(receiver),access_log=None,auto_decompress=False,max_field_size=16384,shutdown_timeout=2)
    await runner.setup()
    try:
        await web.TCPSite(runner,inbound['tls']['bind_host'],inbound['port'],ssl_context=tls).start()
        print(json.dumps({'ready':True}),flush=True)
        await asyncio.Event().wait()
    finally:await runner.cleanup();store.close()
asyncio.run(run())
''');driver.chmod(0o755)
    def event(mid='shared',sender='users/123'):
        return {'type':'MESSAGE','space':{'name':'spaces/room1','spaceType':'DIRECT_MESSAGE'},'message':{
            'name':'spaces/room1/messages/'+mid,'thread':{'name':binding['thread']},'sender':{'type':'HUMAN','name':sender},
            'createTime':now.isoformat().replace('+00:00','Z'),'text':'/status'}}
    claims={'iss':'https://accounts.google.com','aud':audience,'sub':'123456789','email':caller,'email_verified':True,
        'iat':int(now.timestamp()),'exp':int(now.timestamp())+3600}
    def token(change=None):return jwt.encode(signer,{**claims,**(change or {})}).decode()
    request={'value':value,'profile':str(profile),'policy':str(publication),'owner':str(owner),'caller_public':caller_public}
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
            if line!=b'{"ready": true}\n':raise AssertionError((await child.stderr.read()).decode()[-1800:])
            context=ssl.create_default_context(cadata=ca_bytes.decode())
            async with ClientSession(connector=TCPConnector(ssl=context),trust_env=False) as client:
                async def send(data=None,headers=None,path='/google-chat'):
                    async with client.post('https://localhost:'+str(port)+path,json=data or event(),headers=headers if headers is not None else {'Authorization':'Bearer '+token()}) as response:
                        body=await response.read();assert b'BEGIN PRIVATE KEY' not in body and b'local-google-caller' not in body
                        return response.status,body
                assert await send()==(200,b'{}')
                assert await send()==(200,b'{}')
                with sqlite3.connect(profile/'originals.sqlite') as db:assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
                cases.append('actual_private_UID_listener_verifies_system_trusted_TLS_material_and_Google_SDK_RSA_token_then_returns_HTTP200_only_after_FULL_original_custody_and_replay_keeps_one_original')
                assert await send(event('unknown','users/456'))==(200,b'{}')
                with sqlite3.connect(profile/'originals.sqlite') as db:
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
                with sqlite3.connect(profile/'originals.sqlite') as db:db.execute("CREATE TRIGGER fail_original BEFORE INSERT ON google_chat_originals BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END")
                status,_=await send(event('diskfail'));assert status==503
                with sqlite3.connect(profile/'originals.sqlite') as db:
                    assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1;db.execute('DROP TRIGGER fail_original')
                assert await send(event('diskretry'))==(200,b'{}')
                cases.append('actual_SQL_failure_returns_retryable_HTTP503_without_success_ACK_and_next_inspected_source_can_be_retained')
                status,_=await send(path='/google-chat?unapproved=1');assert status==400
                status,_=await send(path='/plugins/arbitrary');assert status==404
                cases.append('only_fixed_query_free_callback_path_is_exposed_no_arbitrary_plugin_listener')
                publication.write_text(json.dumps({**policy,'bindings':[]}));status,_=await send(event('withdrawn'));assert status==401
                with sqlite3.connect(profile/'originals.sqlite') as db:assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==2
                cases.append('actual_root_publication_replacement_immediately_refuses_new_callback_admission_and_success_ACK')
        finally:
            if child.returncode is None:child.terminate()
            _,stderr=await asyncio.wait_for(child.communicate(),10)
            assert b'BEGIN PRIVATE KEY' not in stderr and token().encode() not in stderr
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_gateway_UID_TLS_listener_Google_SDK_JWT_and_FULL_SQLite':True,
        'Google_certificate_endpoint_and_OAuth_service_account_are_explicit_fixtures':True,
        'native_controller_missions_media_GUI_live_Google_account_or_public_activation':False},indent=2))


if __name__=='__main__':main()
