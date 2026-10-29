"""Actual private Feishu UID/process/TLS boundaries in a fresh disposable namespace."""
import json
import os
from pathlib import Path
import shutil
import socket
import http.client
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_FEISHU_UPLOAD_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists() or Path('/etc/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Feishu Docker namespace required; never installed HAOS')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    install='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,install,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,install,'/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_FEISHU_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':
        raise PermissionError('pinned public source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-feishu-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,install,str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/feishu_fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable private Feishu identity:/nonexistent:/usr/sbin/nologin\n')
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-feishu-process-'));work.chmod(0o755)
    sys.path[:0]=['/deps',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    create(work,'open.feishu.cn')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    # Fixed production domain is resolved to loopback ONLY in this network-none container.
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 open.feishu.cn\n')
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-process-fixture',
        'domain':'feishu','tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    policy={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[
        {'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':123,'require_mention':True,'allow_outbound_media':True}]}
    config=Path('/etc/haos');config.mkdir(mode=0o755);policy_path=config/'gateways.json'
    def publish(data):
        PreparedFeishuPolicy(data)
        path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(policy_path)
    publish(policy)
    import base64
    import hashlib
    from haos.gateway import digest
    from email import policy as email_policy
    from email.parser import BytesParser
    stamp=str(int(time.time()*1000)-1000);binding=policy['bindings'][0]
    original=json.dumps({'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1','app_id':value['app_id'],
        'tenant_key':value['tenant_key'],'create_time':stamp},'event':{'sender':{'sender_id':{'open_id':binding['sender']},
        'sender_type':'user','tenant_key':value['tenant_key']},'message':{'message_id':'om_'+'f'*32,'create_time':stamp,
            'chat_id':binding['chat'],'chat_type':'p2p','message_type':'text','content':json.dumps({'text':'Actual approved output source.'})}}}).encode()
    data=b'Actual sealed output upload bytes.'
    item={'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':'d'*64,'attempt':1,
        'source_id':'om_'+'f'*32,'source_base64':base64.b64encode(original).decode(),'source_sha256':hashlib.sha256(original).hexdigest(),
        'output':{'id':'c'*64,'kind':'file','name':'result-0.bin','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'file_type':'stream','duration_ms':0}}
    account=base/'upload-account.json';account.write_text(json.dumps({'value':value,'item':item}));account.chmod(0o600);os.chown(account,65534,65534)
    state={'mode':'ok'};seen=[];entered=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def send(self,status,body):
            raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']))
            if self.path=='/open-apis/auth/v3/tenant_access_token/internal':
                assert json.loads(raw)=={'app_id':value['app_id'],'app_secret':value['app_secret']};seen.append('auth')
                return self.send(200,{'code':0,'tenant_access_token':'private-upload-process-token','expire':7200})
            if self.path=='/open-apis/im/v1/messages/om_'+'f'*32+'/reply':
                body=json.loads(raw);assert self.headers['Authorization']=='Bearer private-upload-process-token'
                assert body['msg_type']=='post' and body['reply_in_thread'] is False
                assert 'file_v3_0000000000000000' in body['content'] and 'Actual sealed output caption' in body['content']
                expected=digest([item['delivery_id'],item['binding_digest'],item['source_id'],item['output']['id'],
                    'Actual sealed output caption','file_v3_0000000000000000'])[:32]
                assert body['uuid']==expected;seen.append('reply')
                if state['mode']=='owner-reply-drop':state['mode']='ok';self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                if state['mode']=='reply-drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                return self.send(200,{'code':0,'data':{'message_id':'om_'+'d'*32,'chat_id':binding['chat']}})
            assert self.path=='/open-apis/im/v1/files' and self.headers['Authorization']=='Bearer private-upload-process-token'
            document=BytesParser(policy=email_policy.default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+raw)
            fields={part.get_param('name',header='content-disposition'):part.get_payload(decode=True) for part in document.iter_parts()}
            assert fields=={'file_type':b'stream','file_name':b'result-0.bin','duration':b'','file':data}
            seen.append('upload');mode=state['mode']
            if mode=='block':entered.set();release.wait(20)
            if mode in {'401','429','500'}:return self.send(int(mode),{'code':1})
            if mode=='owner-upload-drop':state['mode']='ok';self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='missing':return self.send(200,{'code':0,'data':{}})
            if mode=='native-rate':return self.send(200,{'code':99991400})
            self.send(200,{'code':0,'data':{'file_key':'file_v3_0000000000000000'}})
    http=ThreadingHTTPServer(('127.0.0.1',443),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(work/'certificate.pem',work/'key.pem');http.socket=tls.wrap_socket(http.socket,server_side=True)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    script=work/'upload_gateway_fixture.py';script.write_text("""
import asyncio,json,sys
from pathlib import Path
from haos.gateway_feishu_upload_process import upload
from haos.gateway_feishu import authority
async def main():
    if sys.argv[2] in {'agent','root'}:
        if sys.argv[2]=='agent':
            try:Path(sys.argv[1]).read_bytes()
            except PermissionError:pass
            else:raise AssertionError('agent read upload credentials')
        try:await upload({},'feishu',lambda:None,{},b'')
        except PermissionError:pass
        else:raise AssertionError('wrong UID invoked uploader')
        print('identity-denied');return
    request=json.loads(Path(sys.argv[1]).read_text());value=request['value'];item=request['item']
    data=b'Actual sealed output upload bytes.'
    if sys.argv[2] in {'journal','drop-journal','crash-journal','recover-journal','media-journal','media-drop-journal','owner-upload','owner-reply'}:
        from types import SimpleNamespace
        from haos.gateway_feishu import PreparedFeishuPolicy
        from haos.gateway_feishu_cache import RawEvents
        from haos.gateway_feishu_ingress import install,capture,dispatch_stored
        from haos.gateway_ingress import durable_adapter
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.gateway_feishu_delivery import Publisher
        from haos.gateway_feishu_upload_journal import Uploads
        from haos.gateway_matrix_profile import scope
        from haos.gateway_runtime import adapter_envelope
        from haos.sandbox import trusted_json
        from haos.redaction import Redactor
        import base64
        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter
        mode='crash-journal' if sys.argv[2]=='recover-journal' else sys.argv[2]
        home=Path('/var/lib/haos-gateway')/mode;home.mkdir(mode=0o700,exist_ok=True)
        policy=lambda:PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
        current=lambda:authority('feishu',value)
        inbox=NativeInbox(home/'native.db',Redactor([value['app_secret']]))
        originals=RawEvents(home/'originals.db',inbox.redactor,current);relay=RelayInbox(home/'relay.db',inbox.redactor)
        env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
            'FEISHU_DOMAIN':value['domain'],'FEISHU_BOT_OPEN_ID':value['bot_open_id'],'FEISHU_ALLOW_ALL_USERS':'false',
            'GATEWAY_ALLOW_ALL_USERS':'false','FEISHU_ALLOW_BOTS':'none','FEISHU_REQUIRE_MENTION':'false',
            'FEISHU_ALLOWED_USERS':policy().bindings['owner']['sender']}
        with scope(home,env):adapter=install(durable_adapter(FeishuAdapter(PlatformConfig(enabled=True))))
        adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox)
        adapter._haos_feishu_check=current;adapter._haos_feishu_value=value;adapter._haos_feishu_raw=originals
        adapter._haos_feishu_home=home;adapter._haos_feishu_environment=env
        # Declared connection/source fixture; upload UID/TLS/lifetime remain actual.
        adapter._running=True
        adapter.set_durable_message_handler(lambda event:(relay.admit(policy(),'feishu',adapter_envelope(event,'feishu')) is not None))
        try:
            key=capture(adapter,base64.b64decode(item['source_base64']))
            if sys.argv[2]!='recover-journal':assert await dispatch_stored(adapter,key)
            adapter._haos_feishu_publisher=Publisher(adapter)
            if sys.argv[2] in {'media-journal','media-drop-journal','owner-upload','owner-reply'}:
                from haos.gateway_feishu_media_delivery import MediaPublisher
                output={**item['output'],'data':data};prepared={'items':[output],'text':'Actual sealed output caption'}
                binding=policy().bindings['owner'];publisher=MediaPublisher(adapter)
                result=await publisher.send(binding,item['delivery_id'],1,item['source_id'],prepared,current)
                assert result.success is (sys.argv[2]=='media-journal')
                reopened=MediaPublisher(adapter)
                again=await reopened.send(binding,item['delivery_id'],2,item['source_id'],prepared,current)
                assert again.success is result.success
                if result.success:assert result.message_id==again.message_id=='om_'+'d'*32
                else:assert result.raw_response==again.raw_response=={'haos_delivery':'uncertain'}
                if sys.argv[2] in {'owner-upload','owner-reply'}:
                    from haos.gateway_feishu_media_recovery import outgoing,approve_retry
                    operation='upload' if sys.argv[2]=='owner-upload' else 'reply'
                    selected=next(row for row in outgoing(inbox) if row['operation']==operation)
                    decision={key:selected[key] for key in ['connector','delivery_id','part','operation','attempt','snapshot_sha256']}
                    decision.update(owner_uid=1000,note_sha256='e'*64,confirmed=True,confirmed_not_accepted=True)
                    assert approve_retry(inbox,policy(),decision)['network_requested'] is False
                    recovered=MediaPublisher(adapter)
                    accepted=await recovered.send(binding,item['delivery_id'],2,item['source_id'],prepared,current)
                    assert accepted.success and accepted.message_id=='om_'+'d'*32
                    repeated=await recovered.send(binding,item['delivery_id'],3,item['source_id'],prepared,current)
                    assert repeated.success and repeated.message_id==accepted.message_id
                    assert inbox.db.execute('SELECT COUNT(*) FROM feishu_media_owner_events').fetchone()[0]==1
                else:
                    assert inbox.db.execute('SELECT COUNT(*) FROM feishu_upload_intents').fetchone()[0]==1
                    assert inbox.db.execute('SELECT COUNT(*) FROM feishu_media_reply_intents').fetchone()[0]==1
                print('media-journal-checked');return
            uploads=Uploads(adapter)
            output={**item['output'],'data':data};binding=policy().bindings['owner']
            attempt=2 if sys.argv[2]=='recover-journal' else 1
            result=await uploads.upload(binding,item['delivery_id'],attempt,0,item['source_id'],output,current)
            expected='confirmed' if sys.argv[2]=='journal' else 'uncertain'
            assert result['state']==expected,result
            reopened=Uploads(adapter)
            again=await reopened.upload(binding,item['delivery_id'],2,0,item['source_id'],output,current)
            assert again==result
            assert inbox.db.execute('SELECT COUNT(*) FROM feishu_upload_intents').fetchone()[0]==1
            print('journal-checked');return
        finally:originals.close();inbox.close();relay.close()
    if sys.argv[2]=='changed':data=b'changed output'
    task=asyncio.create_task(upload(value,'feishu',lambda:authority('feishu',value),item,data))
    if sys.argv[2]=='cancel':
        await asyncio.get_running_loop().run_in_executor(None,sys.stdin.readline);task.cancel()
    try:result=await task
    except (PermissionError,asyncio.CancelledError):
        assert sys.argv[2] in {'revoke','cancel'};print('stopped');return
    except ValueError:
        assert sys.argv[2]=='changed';print('changed-denied');return
    if sys.argv[2] in {'401','429','native-rate'}:
        assert result=={'state':'rejected','error':'authentication-refused' if sys.argv[2]=='401' else 'rate-limited'}
    elif sys.argv[2] in {'500','drop','missing'}:assert result=={'state':'uncertain'}
    else:assert result=={'state':'confirmed','kind':'file','key':'file_v3_0000000000000000'}
    print('result-checked')
asyncio.run(main())
""")
    def start(mode,uid=65534):
        def identity():os.setgroups([]);os.setgid(uid);os.setuid(uid)
        return subprocess.Popen([str(runtime/'bin/python'),'-E','-s',str(script),str(account),mode],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,preexec_fn=identity,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(base),'HERMES_HOME':str(base/'.hermes')})
    cases=[]
    try:
        for mode,uid in [('agent',65533),('root',0)]:
            child=start(mode,uid);out,err=child.communicate(timeout=10)
            assert child.returncode==0 and out==b'identity-denied\n',(out,err)
            assert not seen;cases.append('actual_'+mode+'_UID_refused_before_private_upload')
        child=start('changed');out,err=child.communicate(timeout=10)
        assert child.returncode==0 and out==b'changed-denied\n' and not seen,(out,err)
        cases.append('actual_changed_binary_offer_refused_before_worker_or_network')
        for mode in ['ok','401','429','native-rate','500','drop','missing']:
            state['mode']=mode;before=len(seen);child=start(mode);out,err=child.communicate(timeout=40)
            assert child.returncode==0 and out==b'result-checked\n',(mode,out,err)
            assert seen[before:]==['auth','upload']
            assert value['app_secret'].encode() not in out+err and b'private-upload-process-token' not in out+err
            cases.append('actual_private_native_upload_'+mode+'_finite_receipt_without_hidden_write_retry')
        for mode in ['revoke','cancel']:
            state['mode']='block';entered.clear();release.clear();publish(policy);child=start(mode)
            assert entered.wait(30)
            if mode=='revoke':publish({'version':1,'connectors':[],'bindings':[]})
            else:child.stdin.write(b'cancel\n');child.stdin.flush()
            child.stdin.close();child.stdin=None;out,err=child.communicate(timeout=5);release.set()
            assert child.returncode==0 and out==b'stopped\n',(out,err)
            cases.append('actual_'+mode+'_kills_and_joins_blocked_credential_bearing_upload_worker')
        publish(policy)
        for mode,api_mode in [('journal','ok'),('drop-journal','drop')]:
            state['mode']=api_mode;before=len(seen);child=start(mode);out,err=child.communicate(timeout=50)
            assert child.returncode==0 and out==b'journal-checked\n',(mode,out,err)
            assert seen[before:]==['auth','upload']
            cases.append('actual_'+mode+'_confirmed_or_uncertain_upload_survives_reopen_and_new_attempt_without_second_API_write')
        for mode,api_mode in [('media-journal','ok'),('media-drop-journal','reply-drop')]:
            state['mode']=api_mode;before=len(seen);child=start(mode);out,err=child.communicate(timeout=70)
            assert child.returncode==0 and out==b'media-journal-checked\n',(mode,out,err)
            assert seen[before:]==['auth','upload','auth','reply'],seen[before:]
            cases.append('actual_'+mode+'_native_upload_and_reply_reopen_new_attempt_never_reuploads_or_resends')
        for mode in ['owner-upload','owner-reply']:
            state['mode']=mode+'-drop';before=len(seen);child=start(mode);out,err=child.communicate(timeout=90)
            assert child.returncode==0 and out==b'media-journal-checked\n',(mode,out,err)
            expected=(['auth','upload','auth','upload','auth','reply'] if mode=='owner-upload'
                else ['auth','upload','auth','reply','auth','reply'])
            assert seen[before:]==expected,seen[before:]
            cases.append('actual_'+mode+'_inspected_per_part_release_allows_one_new_native_write_and_reuses_confirmed_parts')
        state['mode']='block';entered.clear();release.clear();before=len(seen);child=start('crash-journal')
        assert entered.wait(30)
        import sqlite3
        with sqlite3.connect('file:/var/lib/haos-gateway/crash-journal/native.db?mode=ro',uri=True) as db:
            assert db.execute('SELECT state FROM feishu_upload_intents').fetchone()[0]=='writing'
        child.kill();child.communicate(timeout=5);release.set();state['mode']='ok'
        recovered=start('recover-journal');out,err=recovered.communicate(timeout=30)
        assert recovered.returncode==0 and out==b'journal-checked\n',(out,err)
        assert seen[before:]==['auth','upload']
        cases.append('actual_committed_write_intent_before_withheld_response_and_SIGKILL_restart_quarantine_prevent_second_upload')
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65533,65534],
            'fixed_origin_loopback_fixture_only':True,'durable_upload_journal':True,'connection_and_original_source_authentication_are_fixtures':True,'native_media_reply_delivery_fixture':True,'public_feishu_enabled':False}))
    finally:release.set();http.shutdown();http.server_close()


if __name__=='__main__':main()
