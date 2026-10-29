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
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_FEISHU_RESOURCE_PROCESS')!='1'
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
            'identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':123,'require_mention':True,'allow_media':True,'allow_voice':True,'allow_video':True}]}
    config=Path('/etc/haos');config.mkdir(mode=0o755);policy_path=config/'gateways.json'
    def publish(data):
        PreparedFeishuPolicy(data)
        path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(policy_path)
    publish(policy)
    import base64
    import hashlib
    from haos.gateway import digest
    stamp=str(int(time.time()*1000)-1000);binding=policy['bindings'][0]
    original=json.dumps({'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1','app_id':value['app_id'],
        'tenant_key':value['tenant_key'],'create_time':stamp},'event':{'sender':{'sender_id':{'open_id':binding['sender']},
        'sender_type':'user','tenant_key':value['tenant_key']},'message':{'message_id':'om_'+'f'*32,'create_time':stamp,
            'chat_id':binding['chat'],'chat_type':'p2p','message_type':'file',
            'content':json.dumps({'file_key':'file_v3_0000000000000000','file_name':'../../owner-document.txt'})}}}).encode()
    item={'binding_id':binding['id'],'binding_digest':digest(binding),'source_base64':base64.b64encode(original).decode(),
        'source_sha256':hashlib.sha256(original).hexdigest(),'resource_index':0}
    import io,wave
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0XsAAAAASUVORK5CYII=')
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as audio:audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0'*16000)
    wav=buffer.getvalue();video=(16).to_bytes(4,'big')+b'ftypisom'+b'\0'*4
    data=b'Actual private native resource bytes.';state={'mode':'ok'};seen=[];entered=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def send(self,status,raw,mime):
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Content-Disposition','attachment; filename="../../vendor-path.txt"');self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_POST(self):
            assert self.path=='/open-apis/auth/v3/tenant_access_token/internal'
            assert json.loads(self.rfile.read(int(self.headers['Content-Length'])))=={'app_id':value['app_id'],'app_secret':value['app_secret']}
            seen.append('auth');self.send(200,b'{"code":0,"tenant_access_token":"private-resource-process-token","expire":7200}','application/json')
        def do_GET(self):
            kind=state['mode'];selector='image' if kind=='image' else 'audio' if kind=='voice' else 'file'
            key='img_v3_0000000000000000' if kind=='image' else 'file_v3_0000000000000000'
            assert self.path=='/open-apis/im/v1/messages/om_'+'f'*32+'/resources/'+key+'?type='+selector
            assert self.headers['Authorization']=='Bearer private-resource-process-token';seen.append('resource')
            if state['mode']=='block':entered.set();release.wait(20)
            if state['mode'] in {'401','429'}:return self.send(int(state['mode']),b'failure','application/octet-stream')
            payload,mime=(png,'image/png') if kind=='image' else (wav,'audio/wav') if kind=='voice' else (video,'video/mp4') if kind=='video' else (b'R'*131072,'application/octet-stream') if kind=='large' else (data,'application/octet-stream')
            self.send(200,payload,mime)
    http=ThreadingHTTPServer(('127.0.0.1',443),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(work/'certificate.pem',work/'key.pem');http.socket=tls.wrap_socket(http.socket,server_side=True)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    account=base/'resource-account.json';account.write_text(json.dumps({'value':value,'item':item}));account.chmod(0o600);os.chown(account,65534,65534)
    script=work/'resource_gateway_fixture.py'
    script.write_text("""
import asyncio,json,sys
from pathlib import Path
from haos.gateway_feishu_process import resource
from haos.gateway_feishu import authority
async def main():
    if sys.argv[2]=='agent':
        try:Path(sys.argv[1]).read_bytes()
        except PermissionError:pass
        else:raise AssertionError('agent read private media source credentials')
        try:await resource({},'feishu',lambda:None,{})
        except PermissionError:pass
        else:raise AssertionError('agent invoked private resource worker')
        print('agent-denied');return
    request=json.loads(Path(sys.argv[1]).read_text());value=request['value'];item=request['item']
    current=lambda:authority('feishu',value)
    if sys.argv[2]=='ingress':
        import base64,sqlite3
        from types import SimpleNamespace
        from haos.gateway_feishu import PreparedFeishuPolicy
        from haos.sandbox import trusted_json
        from haos.gateway_feishu_cache import RawEvents
        from haos.gateway_feishu_ingress import install,capture,dispatch_stored
        from haos.gateway_ingress import durable_adapter
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.gateway_runtime import adapter_envelope
        from haos.gateway_media_relay import MediaCache,event_media,forward
        from haos.gateway_matrix_profile import scope
        from haos.redaction import Redactor
        from haos.store import MissionStore
        from haos.controller import Controller
        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter
        base=Path('/var/lib/haos-gateway');home=base/'media-profile';home.mkdir(mode=0o700)
        policy=lambda:PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
        redactor=Redactor([value['app_secret']]);inbox=NativeInbox(home/'native.db',redactor)
        originals=RawEvents(home/'originals.db',redactor,current);relay=RelayInbox(home/'relay.db',redactor)
        store=MissionStore(home/'controller.db');controller=Controller(store,'unused-loopback-fixture',set());controller.gateway_policy=policy
        env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
            'FEISHU_DOMAIN':value['domain'],'FEISHU_BOT_OPEN_ID':value['bot_open_id'],'FEISHU_ALLOW_ALL_USERS':'false',
            'GATEWAY_ALLOW_ALL_USERS':'false','FEISHU_ALLOW_BOTS':'none','FEISHU_REQUIRE_MENTION':'false',
            'FEISHU_ALLOWED_USERS':policy().bindings['owner']['sender']}
        with scope(home,env):adapter=install(durable_adapter(FeishuAdapter(PlatformConfig(enabled=True))))
        adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox)
        adapter._haos_feishu_check=current;adapter._haos_feishu_value=value;adapter._haos_feishu_raw=originals
        adapter._haos_feishu_home=home;adapter._haos_feishu_environment=env
        def receive(event):
            ids=event_media(event,'feishu');assert len(ids)==1 and event.media_urls==['haos-media:'+ids[0]]
            assert event.source.user_id_alt is None
            relay.admit(policy(),'feishu',adapter_envelope(event,'feishu'),media=ids);return True
        adapter.set_durable_message_handler(receive)
        try:
            raw=base64.b64decode(item['source_base64']);key=capture(adapter,raw)
            relay.db.execute("CREATE TRIGGER force_media_storage_failure BEFORE INSERT ON inbox BEGIN SELECT RAISE(ABORT,'fixture storage failure'); END")
            try:await dispatch_stored(adapter,key)
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('relay failure falsely accepted media input')
            cache=MediaCache(inbox)
            assert inbox.db.execute('SELECT COUNT(*) FROM feishu_input_media').fetchone()[0]==1
            assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
            relay.db.execute('DROP TRIGGER force_media_storage_failure');await asyncio.sleep(2.2)
            assert await dispatch_stored(adapter,key)
            pending=relay.next(policy());assert pending and len(pending['media'])==1
            async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
            admitted=await forward(policy,'feishu',pending['envelope'],pending['media'],cache,call)
            relay.admitted(pending['id'],admitted['mission_id']);cache.transferred(pending['media'])
            attachments=controller.gateway.media.for_mission(policy(),admitted['mission_id'])
            assert len(attachments)==1 and attachments[0]['data']==b'Actual private native resource bytes.'
            assert cache.replay(policy(),pending['media'][0])['data'] is None
            assert capture(adapter,raw)==key and not await dispatch_stored(adapter,key)
            assert relay.next(policy()) is None and len(store.list())==1
            print('result-checked');return
        finally:originals.close();inbox.close();relay.close();store.close()
    task=asyncio.create_task(resource(value,'feishu',current,item))
    if sys.argv[2]=='cancel':
        await asyncio.get_running_loop().run_in_executor(None,sys.stdin.readline);task.cancel()
    try:result=await task
    except (PermissionError,asyncio.CancelledError):
        assert sys.argv[2] in {'revoke','cancel'};print(sys.argv[2]+'-stopped');return
    if sys.argv[2] in {'401','429'}:
        assert result=={'error':'authentication-refused' if sys.argv[2]=='401' else 'rate-limited'}
    else:
        expected='document' if sys.argv[2] in {'ok','large'} else sys.argv[2]
        assert result['descriptor']['kind']==expected
        if sys.argv[2]=='ok':assert result['data']==b'Actual private native resource bytes.'
        if sys.argv[2]=='large':assert result['data']==b'R'*131072
        assert result['descriptor']['size']==len(result['data'])
        assert set(result)=={'data','descriptor','mime'}
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
        child=start('agent',65533);out,err=child.communicate(timeout=10)
        assert child.returncode==0 and out==b'agent-denied\n',(out,err)
        cases.append('actual_agent_UID_cannot_read_credentials_original_proof_or_invoke_resource_worker')
        for mode in ['ok','401','429']:
            state['mode']=mode;before=len(seen);child=start(mode);out,err=child.communicate(timeout=40)
            assert child.returncode==0 and out==b'result-checked\n',(mode,out,err)
            assert seen[before:]==['auth','resource']
            assert value['app_secret'].encode() not in out+err and b'private-resource-process-token' not in out+err
            cases.append('actual_native_UID_TLS_resource_'+mode+'_result_without_false_acceptance_or_credentials')
        for mode in ['image','voice','video','large']:
            source=json.loads(original);message=source['event']['message']
            message['message_type']={'image':'image','voice':'audio','video':'media','large':'file'}[mode]
            content=({'image_key':'img_v3_0000000000000000'} if mode=='image' else
                {'file_key':'file_v3_0000000000000000','file_name':'owner-attachment.bin'})
            message['content']=json.dumps(content);raw=json.dumps(source).encode()
            proof={**item,'source_base64':base64.b64encode(raw).decode(),'source_sha256':hashlib.sha256(raw).hexdigest()}
            account.write_text(json.dumps({'value':value,'item':proof}));os.chown(account,65534,65534)
            state['mode']=mode;before=len(seen);child=start(mode);out,err=child.communicate(timeout=40)
            assert child.returncode==0 and out==b'result-checked\n',(mode,out,err)
            assert seen[before:]==['auth','resource']
            cases.append('actual_private_native_'+mode+'_binary_and_descriptor_without_host_path_or_private_token')
        account.write_text(json.dumps({'value':value,'item':item}));os.chown(account,65534,65534)
        state['mode']='ingress';before=len(seen);child=start('ingress');out,err=child.communicate(timeout=50)
        assert child.returncode==0 and out==b'result-checked\n',(out,err)
        assert seen[before:]==['auth','resource'],seen[before:]
        cases.append('actual_native_media_decode_original_SQLite_cache_relay_storage_failure_retry_and_independent_controller_mission')
        cases.append('durable_media_retry_and_remote_replay_do_not_refetch_resource_or_create_second_mission')
        for mode in ['revoke','cancel']:
            state['mode']='block';entered.clear();release.clear();publish(policy);child=start(mode)
            assert entered.wait(30)
            if mode=='revoke':publish({'version':1,'connectors':[],'bindings':[]})
            else:child.stdin.write(b'cancel\n');child.stdin.flush()
            child.stdin.close();child.stdin=None
            out,err=child.communicate(timeout=5);release.set()
            assert child.returncode==0 and out==(mode+'-stopped\n').encode(),(out,err)
            cases.append('actual_'+mode+'_kills_and_joins_blocked_private_binary_worker_before_return')
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65533,65534],
            'loopback_fixed_origin_fixture_only':True,'direct_controller_policy_and_calls_are_fixtures':True,'public_feishu_enabled':False}))
    finally:
        release.set();http.shutdown();http.server_close()


if __name__=='__main__':main()
