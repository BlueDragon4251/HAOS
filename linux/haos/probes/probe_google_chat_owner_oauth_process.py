"""Real fixed Root/private-UID OAuth worker; Google HTTPS is namespace-local."""
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit,urlencode


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_OWNER_OAUTH_PROCESS')!='1'
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
    cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'oauth2.googleapis.com')])).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('oauth2.googleapis.com'),x509.DNSName('www.googleapis.com')]),False).sign(key,hashes.SHA256())
    for path in {ssl.get_default_verify_paths().cafile,httplib2.CA_CERTS}:
        with Path(path).open('ab') as stream:stream.write(b'\n'+ca.public_bytes(serialization.Encoding.PEM))
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 oauth2.googleapis.com www.googleapis.com\n')
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
 else:raise ValueError('fixture action')
 print(json.dumps(result))
except PermissionError:print(json.dumps({'error':'root-backend-authority-refused'}))
''');helper.chmod(0o700)
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','SUDO_UID':'1000'};requests=[];authorizations={}
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body):
            raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            assert self.headers['Host']=='www.googleapis.com' and self.path=='/oauth2/v1/certs' and not self.headers.get('Authorization')
            requests.append('certificates');self.reply(200,{'local-owner-google-user':public})
        def do_POST(self):
            assert self.headers['Host']=='oauth2.googleapis.com'
            values=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode(),strict_parsing=True)
            if self.path=='/revoke':
                assert values['token'][0] in {'owner-private-refresh-fixture','owner-rejected-refresh-fixture'}
                requests.append('revoke');self.reply(200,{});return
            assert self.path=='/token' and values['grant_type']==['authorization_code']
            code=values['code'][0];entry=authorizations[code]
            import base64
            challenge=base64.urlsafe_b64encode(__import__('hashlib').sha256(values['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
            assert entry['code_challenge']==[challenge] and values['client_secret']==[configuration['installed']['client_secret']]
            with sqlite3.connect(database) as db:assert db.execute('SELECT status FROM google_chat_oauth_pending WHERE state=?',(entry['state'][0],)).fetchone()[0]=='exchanging'
            requests.append('token-'+code)
            bad=code=='owner-wrong-account';claims={'iss':'https://accounts.google.com','aud':configuration['installed']['client_id'],'sub':'124' if bad else '123',
                'nonce':entry['nonce'][0],'iat':int(now.timestamp()),'exp':int(now.timestamp())+3600}
            self.reply(200,{'access_token':'owner-private-access-fixture','refresh_token':'owner-rejected-refresh-fixture' if bad else 'owner-private-refresh-fixture',
                'token_type':'Bearer','expires_in':3600,'scope':' '.join(SCOPES),'id_token':jwt.encode(signer,claims).decode()})
    server=ThreadingHTTPServer(('127.0.0.1',443),API);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(certfile,keyfile)
    server.socket=tls.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def call(action,params=None):
        child=subprocess.run([sys.executable,str(helper)],input=json.dumps({'action':action,'params':params or {}}),text=True,capture_output=True,timeout=50,cwd=str(code),env=env)
        assert child.returncode==0,child.stderr
        assert all(token not in child.stdout+child.stderr for token in [configuration['installed']['client_secret'],'owner-private-access-fixture','owner-private-refresh-fixture','owner-rejected-refresh-fixture'])
        assert not child.stderr,child.stderr
        return json.loads(child.stdout)
    cases=[]
    try:
        for kind in ['sessions','tokens','quarantines']:
            empty=call('inspect',{'kind':kind});assert empty[kind]==[] and not empty['network_requested']
        assert not database.exists() and state.stat().st_uid==65534 and state.stat().st_gid==65534 and state.stat().st_mode&0o777==0o700;cases.append('actual_Root_backend_private_UID_closed_empty_OAuth_inventories_do_not_create_token_database_or_send_network_requests')
        state.chmod(0o755)
        assert call('inspect',{'kind':'tokens'})=={'error':'root-backend-authority-refused'} and state.stat().st_mode&0o777==0o755
        state.chmod(0o700);retained=state.with_name('retained-gateway-fixture');state.rename(retained);state.symlink_to(retained,target_is_directory=True)
        assert call('inspect',{'kind':'tokens'})=={'error':'root-backend-authority-refused'} and state.is_symlink() and retained.stat().st_uid==65534
        state.unlink();retained.rename(state)
        cases.append('actual_Root_first_setup_creates_missing_private_service_state_but_refuses_existing_insecure_or_symlinked_custody_without_chown_chmod_or_deletion')
        denied='''from haos import google_chat_owner_setup as owner
for action in [lambda:owner.oauth_inspect('google'),lambda:owner.oauth_begin('google','owner',{},'fixture',confirmed=True),lambda:owner.oauth_finish('google',{},'fixture',confirmed=True),lambda:owner.oauth_revoke('google',{},'fixture',confirmed=True),lambda:owner.oauth_dispose('google',{},'fixture',confirmed=True)]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('foreign UID entered Root OAuth backend')
print('denied')
'''
        child=subprocess.run([str(runtime/'bin/python'),'-E','-s','-c',denied],capture_output=True,text=True,user=65534,group=65534,extra_groups=[],cwd=str(code),env=env,timeout=15)
        assert child.returncode==0 and child.stdout=='denied\n',child.stderr
        cases.append('actual_gateway_UID_cannot_call_five_Root_OAuth_backend_entry_points')
        for code_value in ['owner-good-account','owner-wrong-account']:
            session=call('begin',{'binding_id':'owner','configuration':configuration,'note':'explicit fixture user file delegation','confirmed':True})
            assert session['subject']=='users/123' and not session['private_verifier_or_credentials_returned'] and not session['network_requested']
            url=urlsplit(session['authorization_url']);assert url.hostname=='accounts.google.com';authorizations[code_value]=parse_qs(url.query)
            callback=REDIRECT_URI+'/?'+urlencode({'code':code_value,'state':authorizations[code_value]['state'][0]})
            result=call('finish',{'session':session,'returned_url':callback,'confirmed':True})
            if code_value=='owner-good-account':
                assert 'status' in result,(result,requests)
                assert result['status']=='active' and result['network_requested'] and not result['private_credentials_returned']
                cases.append('actual_fixed_Owner_worker_ROOT_parent_private_UID_native_Flow_default_Google_TLS_endpoint_RSA_subject_verification_and_FULL_token_acceptance_return_only_closed_receipt')
                tokens=call('inspect',{'kind':'tokens'});assert len(tokens['tokens'])==1 and tokens['tokens'][0]['subject']=='users/123'
                assert tokens['tokens'][0]['scopes']==list(SCOPES) and not tokens['tokens'][0]['scope_upgrade_required']
                cases.append('actual_Root_private_UID_token_status_exposes_only_exact_public_client_scopes_generation_budget_and_snapshot_without_token_readback')
            else:
                assert result['error']=='identity-refused'
                items=call('inspect',{'kind':'quarantines'})['quarantines'];assert len(items)==1 and not items[0]['api_use_authorized']
                disposed=call('dispose',{'row':items[0],'note':'explicit wrong-account cleanup','confirmed':True})
                assert disposed['remote_revocation_verified'] and disposed['network_requested'] and not disposed['api_use_authorized']
                assert not call('dispose',{'row':items[0],'note':'explicit wrong-account cleanup','confirmed':True})['network_requested']
                cases.append('actual_Owner_worker_refuses_wrong_signed_Google_user_retains_private_nonactive_capsule_and_explicit_snapshot_disposal_revokes_once_before_compaction')
        sessions=call('inspect',{'kind':'sessions'})['sessions'];assert {row['status'] for row in sessions}=={'complete','refused'}
        policy['bindings']=[];publication.write_text(json.dumps(policy));publication.chmod(0o644)
        row=call('inspect',{'kind':'tokens'})['tokens'][0];assert row['current_file_grants']==0
        revoked=call('revoke',{'row':row,'note':'explicit owner logout after withdrawal','confirmed':True})
        assert revoked['locally_revoked'] and revoked['remote_revocation_verified'] and revoked['network_requested']
        replay=call('revoke',{'row':row,'note':'explicit owner logout after withdrawal','confirmed':True})
        assert replay['remote_revocation_verified'] and not replay['network_requested'] and replay['receipt']==revoked['receipt']
        cases.append('actual_authenticated_Root_handoff_can_revoke_after_all_file_grants_are_withdrawn_and_repeated_decision_returns_existing_receipt_without_HTTP')
        assert requests.count('revoke')==2 and sum(item.startswith('token-') for item in requests)==2
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT status FROM google_chat_user_tokens').fetchone()[0]=='revoked-remote'
            assert db.execute('SELECT tokens FROM google_chat_oauth_quarantine').fetchone()[0]=='{}'
        audit=Path('/var/lib/haos-owner/audit.jsonl').read_text();assert 'google-chat-owner-oauth-finish' in audit and configuration['installed']['client_secret'] not in audit
        cases.append('real_Root_and_private_credential_audits_persist_actor_and_receipts_without_secret_material_or_external_chat_message_requests')
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_Root_backend_fixed_worker_private_UID_RSA_PKCE_default_HTTPS_and_FULL_SQLite':True,
        'systemctl_state_is_explicit_fixture':True,'Google_DNS_and_CA_are_substituted_only_in_disposable_network_none_namespace':True,
        'service_account_schema_only_for_user_OAuth_component':True,'live_Google_account_installed_Owner_login_GUI_or_public_activation':False},indent=2))


if __name__=='__main__':main()
