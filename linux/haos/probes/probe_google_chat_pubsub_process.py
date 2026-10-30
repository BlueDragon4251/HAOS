"""Disposable actual-UID Google SDK TLS/gRPC pull, custody and ACK/NACK fixture."""
import datetime
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
from urllib.parse import urlsplit,parse_qs
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit readonly disposable namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    prepared=Path('/repo/upstream/hermes-agent')
    assert (prepared/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    staged=Path(tempfile.mkdtemp(prefix='haos-google-native-source-'))
    shutil.copytree(prepared,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py',str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    (runtime/'lib/python3.11/site-packages/fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/deps',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec,rsa
    from cryptography.x509.oid import NameOID
    import grpc
    from google.pubsub_v1.types import PullRequest,PullResponse,AcknowledgeRequest,ModifyAckDeadlineRequest,ReceivedMessage,PubsubMessage
    from google.protobuf.empty_pb2 import Empty
    from haos.gateway_google_chat import scope
    from haos.gateway import digest
    directory=Path(tempfile.mkdtemp(prefix='haos-google-pubsub-process-'));directory.chmod(0o755)
    profile=directory/'private';profile.mkdir(mode=0o700);os.chown(profile,65534,65534)
    owner=directory/'owner-canary';owner.write_text('private owner fixture data');owner.chmod(0o600)
    email='gateway@haos-fixture.iam.gserviceaccount.com'
    value={'service_account':{'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n','client_email':email,'client_id':'123456789',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},
        'bot_user':'users/999','inbound':{'mode':'pubsub','subscription':'projects/haos-fixture/subscriptions/haos-private'}}
    service_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    value['service_account']['private_key']=service_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    service_public=service_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now=datetime.datetime.now(datetime.timezone.utc)
    binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
        'scope':scope(value),'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':int(now.timestamp()*1000)-60000}
    policy={'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]}
    publication=directory/'policy.json';publication.write_text(json.dumps(policy));publication.chmod(0o644)
    key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(
        now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(
        x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256())
    cert_bytes=cert.public_bytes(serialization.Encoding.PEM);key_bytes=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    state={'mode':'accepted','requests':[]}
    def authenticate(context):
        assert dict(context.invocation_metadata()).get('authorization')=='Bearer local-private-transport-fixture'
    def event(mid,sender='users/123'):
        return json.dumps({'type':'MESSAGE','space':{'name':'spaces/room1','spaceType':'DIRECT_MESSAGE'},'message':{
            'name':'spaces/room1/messages/'+mid,'thread':{'name':binding['thread']},'sender':{'type':'HUMAN','name':sender},
            'createTime':now.isoformat().replace('+00:00','Z'),'text':'Create a local plan' if mid=='publisher' else '/status'}}).encode()
    def pull(request,context):
        authenticate(context);assert request.subscription==value['inbound']['subscription'] and request.max_messages==1
        mode=state['mode'];state['requests'].append(('Pull',mode))
        if mode=='auth':context.abort(grpc.StatusCode.UNAUTHENTICATED,'finite local auth fixture')
        if mode=='disconnect':context.abort(grpc.StatusCode.UNAVAILABLE,'finite local disconnect fixture')
        if mode=='empty':return PullResponse()
        if mode=='revoke':publication.write_text(json.dumps({**policy,'bindings':[]}))
        data=event('shared' if mode=='accepted' else 'gap' if mode=='gap-recover' else mode,'users/456' if mode=='unknown' else 'users/123')
        return PullResponse(received_messages=[ReceivedMessage(ack_id='local-'+mode,message=PubsubMessage(data=data,message_id='transport-'+mode),delivery_attempt=1)])
    def ack(request,context):
        authenticate(context);assert request.subscription==value['inbound']['subscription'] and len(request.ack_ids)==1
        import sqlite3
        with sqlite3.connect(profile/'originals.sqlite') as db:
            table='google_chat_source_refusals' if state['mode']=='unknown' else 'google_chat_originals'
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]>=1
        state['requests'].append(('Ack',state['mode']));return Empty()
    def nack(request,context):
        authenticate(context);assert request.subscription==value['inbound']['subscription'] and request.ack_deadline_seconds==0
        state['requests'].append(('Nack',state['mode']));return Empty()
    server=grpc.server(ThreadPoolExecutor(max_workers=2))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('google.pubsub.v1.Subscriber',{
        'Pull':grpc.unary_unary_rpc_method_handler(pull,request_deserializer=PullRequest.deserialize,response_serializer=PullResponse.serialize),
        'Acknowledge':grpc.unary_unary_rpc_method_handler(ack,request_deserializer=AcknowledgeRequest.deserialize,response_serializer=Empty.SerializeToString),
        'ModifyAckDeadline':grpc.unary_unary_rpc_method_handler(nack,request_deserializer=ModifyAckDeadlineRequest.deserialize,response_serializer=Empty.SerializeToString)}),))
    port=server.add_secure_port('localhost:0',grpc.ssl_server_credentials([(key_bytes,cert_bytes)]));assert port;server.start()
    text_requests=[];text_responses={};token_grants=[]
    class TextAPI(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value):
            data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            if urlsplit(self.path).path=='/oauth-token':
                from google.auth import jwt
                data=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                assert data['grant_type']==['urn:ietf:params:oauth:grant-type:jwt-bearer']
                claims=jwt.decode(data['assertion'][0],certs={'a'*40:service_public},audience='https://oauth2.googleapis.com/token')
                assert claims['iss']==email and set(claims['scope'].split())=={'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'}
                token_grants.append(True);self.reply(200,{'access_token':'local-private-transport-fixture','token_type':'Bearer','expires_in':3600});return
            assert self.headers.get('Authorization')=='Bearer local-outbox-token-fixture'
            query=parse_qs(urlsplit(self.path).query);body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));client_id=query['messageId'][0]
            import sqlite3
            with sqlite3.connect(profile/'native.sqlite') as db:
                assert db.execute('SELECT state FROM google_chat_text_writes WHERE client_id=?',(client_id,)).fetchone()[0]=='writing'
                assert db.execute("SELECT COUNT(*) FROM native_inbox WHERE state='committed'").fetchone()[0]>=1
            text_requests.append(('POST',client_id,body))
            response={'name':'spaces/room1/messages/server.'+str(len(text_requests)),'text':body['text'],
                'thread':body.get('thread',{'name':'spaces/room1/threads/serverroot'}),'clientAssignedMessageId':client_id}
            text_responses[client_id]=response;self.reply(200,response)
        def do_GET(self):
            client_id=urlsplit(self.path).path.rsplit('/',1)[1];text_requests.append(('GET',client_id))
            self.reply(200 if client_id in text_responses else 404,text_responses.get(client_id,{'error':{'code':404,'message':'fixture unknown'}}))
    text_server=ThreadingHTTPServer(('127.0.0.1',0),TextAPI)
    tls_cert=directory/'api-cert.pem';tls_key=directory/'api-key.pem';tls_cert.write_bytes(cert_bytes);tls_key.write_bytes(key_bytes);tls_key.chmod(0o600)
    import ssl
    api_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);api_tls.load_cert_chain(tls_cert,tls_key);text_server.socket=api_tls.wrap_socket(text_server.socket,server_side=True)
    text_thread=threading.Thread(target=text_server.serve_forever,daemon=True);text_thread.start()
    driver=directory/'driver.py';driver.write_text('''import asyncio,json,os,sys
from pathlib import Path
from types import SimpleNamespace
import os
from haos.gateway_google_chat_pubsub import private_identity
try:private_identity()
except PermissionError:
    assert 'google.cloud.pubsub_v1' not in sys.modules
    print(json.dumps({'denied_before_optional_SDK':True}));raise SystemExit(3)
from haos.gateway_google_chat import PreparedGoogleChatPolicy
from haos.gateway_google_chat_custody import Originals
from haos.gateway_google_chat_receive import Receiver
from haos.gateway_google_chat_pubsub import PullTransport
from haos.redaction import Redactor
from haos.gateway import digest
import grpc
from google.cloud.pubsub_v1 import SubscriberClient
from google.pubsub_v1.services.subscriber.transports.grpc import SubscriberGrpcTransport
v=json.load(sys.stdin);publication=Path(v['policy']);initial=publication.read_bytes()
def current():
    private_identity()
    if publication.read_bytes()!=initial:raise PermissionError('publication withdrawn')
try:Path(v['owner']).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read owner data')
from google.oauth2 import service_account
from google_auth_httplib2 import Request
from haos.gateway_google_chat_http import single_request_http,token_response
from haos.gateway_google_chat_pubsub import _subscriber_client
store=Originals(Path(v['profile'])/'originals.sqlite',Redactor([]))
account=service_account.Credentials.from_service_account_info(v['value']['service_account'],scopes=['https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'])
origin='https://localhost:'+str(v['text_port'])
base=single_request_http(current,fixture_origin=origin,redactor=store.redactor);base.ca_certs=v['ca']
class TokenWire:
    def __getattr__(self,key):return getattr(base,key)
    def request(self,uri,method='GET',body=None,headers=None,**kwargs):
        assert uri=='https://oauth2.googleapis.com/token'
        response,data=base.request(origin+'/oauth-token',method=method,body=body,headers=headers,**kwargs)
        return token_response(uri,response,data,redactor=store.redactor)
client=_subscriber_client(account,current,store.redactor,target='localhost:'+str(v['port']),roots=v['certificate'].encode(),token_request=Request(http=TokenWire()))
receiver=Receiver('google',v['value'],store,lambda:PreparedGoogleChatPolicy(json.loads(publication.read_text())),current)
if v['mode']=='sqlfail':store.db.execute("CREATE TEMP TRIGGER fail_original BEFORE INSERT ON google_chat_originals BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END")
transport=PullTransport(client,receiver,current)
native_store=None;relay=None
async def exercise():
    global native_store,relay
    result=await transport.step()
    if result is None:return result
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_google_chat_ingress import install,capture_stored,dispatch_stored
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_matrix_profile import scope
    home=Path(v['profile'])/'home';home.mkdir(mode=0o700,exist_ok=True);os.environ['HERMES_HOME']=str(home)
    from gateway.config import PlatformConfig
    from plugins.platforms.google_chat.adapter import GoogleChatAdapter
    native_store=NativeInbox(Path(v['profile'])/'native.sqlite',store.redactor);relay=RelayInbox(Path(v['profile'])/'relay.sqlite',store.redactor)
    with scope(home,{'HERMES_SAFE_MODE':'1'}):adapter=install(durable_adapter(GoogleChatAdapter(PlatformConfig(enabled=True))))
    adapter._haos_native=SimpleNamespace(connector='google',policy=lambda:PreparedGoogleChatPolicy(json.loads(publication.read_text())),inbox=native_store)
    adapter._haos_google_check=current;adapter._haos_google_originals=store;adapter._haos_google_value=v['value']
    adapter._haos_google_home=home;adapter._haos_google_environment={'HERMES_SAFE_MODE':'1'}
    def accepted(event):
        relay.admit(adapter._haos_native.policy(),'google',adapter_envelope(event,'google_chat'));return True
    adapter.set_durable_message_handler(accepted)
    # No event without retained source context can call durable admission.
    try:adapter._haos_admit(object())
    except PermissionError:pass
    else:raise AssertionError('unretained native event accepted')
    key=await capture_stored(adapter,result)
    if v['mode']=='gap':store.db.execute("CREATE TEMP TRIGGER fail_receipt BEFORE UPDATE ON google_chat_originals BEGIN SELECT RAISE(ABORT,'fixture source receipt failure'); END")
    if v['mode']=='gap-recover':await asyncio.sleep(2.1)
    await dispatch_stored(adapter,key)
    assert native_store.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='committed'
    assert store.db.execute('SELECT admitted_receipt FROM google_chat_originals WHERE id=?',(result,)).fetchone()[0]
    assert await capture_stored(adapter,result)==key and await dispatch_stored(adapter,key) is False
    if v['mode']=='publisher':
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from haos.gateway_google_chat_http import single_request_http
        from haos.gateway_google_chat_delivery import Publisher
        from haos.gateway_runtime import delivery_metadata
        from haos.store import MissionStore
        from haos.controller import Controller
        component=MissionStore(Path(v['profile'])/'controller-component.sqlite')
        controller=Controller(component,'ws://127.0.0.1:9119/api/ws',{65534})
        source=store.db.execute('SELECT admitted_receipt FROM google_chat_originals WHERE id=?',(result,)).fetchone()[0]
        original=json.loads(relay.db.execute('SELECT envelope FROM inbox WHERE id=?',(source,)).fetchone()[0])
        await controller.gateway.receive(adapter._haos_native.policy(),'google',original,controller)
        delivery=controller.gateway.next_delivery(adapter._haos_native.policy());metadata=delivery_metadata(delivery,'google_chat')
        origin='https://localhost:'+str(v['text_port'])
        def http():
            transport=single_request_http(current,fixture_origin=origin,redactor=native_store.redactor);transport.ca_certs=v['ca']
            return AuthorizedHttp(Credentials('local-outbox-token-fixture'),http=transport,max_refresh_attempts=0)
        adapter._new_authed_http=http
        adapter._chat_api=build('chat','v1',http=single_request_http(current,fixture_origin=origin),cache_discovery=False,static_discovery=True,client_options={'api_endpoint':origin+'/'})
        publisher=Publisher(adapter)
        sent=await publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],metadata)
        assert sent.success and sent.message_id.startswith('spaces/room1/messages/server.')
        assert (await publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],metadata)).message_id==sent.message_id
        try:await adapter._create_message(delivery['chat'],{'text':'unscoped bypass'})
        except PermissionError:pass
        else:raise AssertionError('unscoped native create accepted')
        try:await publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],{**metadata,'thread_id':'spaces/room1/threads/foreign'})
        except PermissionError:pass
        else:raise AssertionError('source route changed')
        try:await publisher.send(delivery['chat'],delivery['content']+' changed',delivery['reply_to'],metadata)
        except Exception:pass
        else:raise AssertionError('root event bytes changed')
        component.close()
    return result
try:
    try:result=asyncio.run(exercise());outcome={'key':result,'failed':False}
    except Exception as error:
        assert not store.db.in_transaction
        outcome={'failed':True,'category':type(error).__name__}
    outcome['originals']=store.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]
    if relay is not None:outcome['parent_records']=relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]
    outcome['refusals']=store.db.execute('SELECT COUNT(*) FROM google_chat_source_refusals').fetchone()[0]
    print(json.dumps(outcome))
finally:
    transport.close();store.close()
    if native_store is not None:native_store.close()
    if relay is not None:relay.close()
''');driver.chmod(0o755)
    def invoke(uid,mode='accepted',groups=()):
        state['mode']=mode;request={'mode':mode,'value':value,'profile':str(profile),'policy':str(publication),
            'owner':str(owner),'port':port,'certificate':cert_bytes.decode(),'text_port':text_server.server_port,'ca':str(tls_cert)}
        child=subprocess.run([str(runtime/'bin/python'),'-E','-s',str(driver)],input=json.dumps(request).encode(),capture_output=True,
            timeout=35,user=uid,group=uid,extra_groups=list(groups),cwd=str(code),umask=0o077,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
        if child.returncode not in {0,3}:raise AssertionError(child.stderr.decode()[-1500:])
        assert b'local-private-transport-fixture' not in child.stdout and b'local-private-transport-fixture' not in child.stderr
        return child.returncode,json.loads(child.stdout)
    cases=[]
    try:
        for uid,groups in [(0,()),(65533,()),(65534,(0,))]:
            before=len(state['requests']);status,result=invoke(uid,groups=groups)
            assert status==3 and result=={'denied_before_optional_SDK':True} and len(state['requests'])==before
        cases.append('actual_root_agent_UID_and_gateway_with_supplementary_root_group_refused_before_optional_Google_SDK_or_TLS_network')
        status,result=invoke(65534);assert status==0 and not result['failed'] and result['originals']==1
        assert state['requests'][-2:]==[('Pull','accepted'),('Ack','accepted')]
        old=result['key'];status,result=invoke(65534);assert result['key']==old and result['originals']==1 and result['parent_records']==1
        cases.append('actual_pinned_native_Google_Chat_codec_and_durable_MRO_admit_only_retained_source_context_then_FULL_native_and_parent_relay_reopen_with_one_parent_record')
        assert len(token_grants)==2
        cases.append('actual_private_scoped_Google_auth_metadata_plugin_performs_real_SDK_RSA_OAuth_grant_over_verified_TLS_and_captures_bearer_before_native_gRPC_metadata_without_default_requests_or_global_auth_hooks')
        cases.append('actual_gateway_UID_Google_SDK_verified_local_TLS_gRPC_pull_and_server_ACK_observe_committed_FULL_original_then_fresh_process_replay_keeps_one_source_and_cannot_read_owner_canary')
        _,result=invoke(65534,'unknown');assert not result['failed'] and result['key'] is None and result['refusals']==1
        assert state['requests'][-1]==('Ack','unknown')
        cases.append('actual_TLS_server_ACK_for_unknown_sender_occurs_only_after_private_hash_only_refusal_without_new_original_or_mission_authority')
        _,result=invoke(65534,'sqlfail');assert result['failed'] and result['originals']==1 and state['requests'][-1]==('Nack','sqlfail')
        cases.append('actual_SQL_insert_failure_after_authenticated_pull_sends_native_TLS_gRPC_NACK_without_ACK_or_lost_custody_claim')
        for mode in ['auth','disconnect']:
            before=len(state['requests']);_,result=invoke(65534,mode)
            assert result['failed'] and state['requests'][before:]==[('Pull',mode)]
        cases.append('actual_TLS_gRPC_UNAUTHENTICATED_and_UNAVAILABLE_fail_without_SDK_auto_retry_ACK_or_empty_history_substitution')
        _,result=invoke(65534,'empty');assert not result['failed'] and result['key'] is None and state['requests'][-1]==('Pull','empty')
        cases.append('actual_empty_authenticated_pull_returns_no_source_and_never_ACKs_an_invented_message')
        _,result=invoke(65534,'gap');assert result['failed'] and result['parent_records']==2 and result['originals']==2
        _,result=invoke(65534,'gap-recover');assert not result['failed'] and result['parent_records']==2 and result['originals']==2
        cases.append('real_source_receipt_SQL_failure_after_parent_commit_recovers_on_fresh_UID_process_without_duplicate_parent_admission_or_lost_original')
        _,result=invoke(65534,'publisher');assert not result['failed'],result
        assert len(text_requests)==1 and text_requests[0][0]=='POST' and text_requests[0][2]['thread']['name']==binding['thread']
        cases.append('actual_UID_retained_source_and_real_controller_component_outbox_context_drive_native_Google_send_with_FULL_intent_before_HTTP_confirmed_replay_no_wire_and_unscoped_changed_event_or_cross_thread_calls_refused')
        before=len(state['requests']);_,result=invoke(65534,'revoke');assert result['failed'] and state['requests'][before:]==[('Pull','revoke')]
        cases.append('root_publication_withdrawal_during_actual_TLS_pull_prevents_original_admission_and_ACK_then_actual_UID_closes_channel')
    finally:
        server.stop(0).wait(3);text_server.shutdown();text_server.server_close();text_thread.join(timeout=2)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_gateway_UID_Google_SDK_TLS_gRPC_FULL_SQLite':True,
        'service_account_OAuth_and_remote_Google_subscription_are_fixtures':True,
        'actual_pinned_native_codec_and_durable_parent_relay':True,
        'root_controller_missions_media_GUI_live_account_installed_OS_or_public_activation':False},indent=2))


if __name__=='__main__':main()
