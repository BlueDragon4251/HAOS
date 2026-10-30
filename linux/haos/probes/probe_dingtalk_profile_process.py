"""Real UID/TLS/native SDK no-send action in a guarded offline namespace."""
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
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_DINGTALK_PROFILE_PROCESS')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline DingTalk process namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755);installer='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,installer,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,installer,'/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_DINGTALK_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':raise PermissionError('pinned public source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-dingtalk-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,installer,str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/dingtalk_fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-dingtalk-ws-process-'));work.chmod(0o755)
    sys.path[:0]=['/deps',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    create(work,'api.dingtalk.com')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 api.dingtalk.com\n')
    value={'client_id':'ding_private_fixture_app','client_secret':'private-dingtalk-process-fixture',
        'corp_id':'ding_fixture_corporation','robot_code':'ding_fixture_robot'}
    config=Path('/etc/haos');config.mkdir(mode=0o755)
    policy={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[{
        'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1}]}
    def publish(data):
        PreparedDingTalkPolicy(data);path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(config/'gateways.json')
    publish(policy)
    account=base/'account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    canary=work/'owner-secret';canary.write_text('root-only-disposable-owner-evidence');canary.chmod(0o600)
    ws_cert=work/'wss';ws_cert.mkdir();create(ws_cert,'wss-open-connection.dingtalk.com')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(ws_cert/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 wss-open-connection.dingtalk.com\n')
    script=work/'gateway_profile_fixture.py';script.write_text("\nimport asyncio,json,sys\nfrom pathlib import Path\nfrom haos.gateway_dingtalk import PreparedDingTalkPolicy\nfrom haos.gateway_dingtalk_profile import build\nfrom haos.gateway_raw import NativeInbox\nfrom haos.gateway_relay import RelayInbox\nfrom haos.gateway_runtime import adapter_envelope\nfrom haos.redaction import Redactor\nasync def main():\n    base=Path('/var/lib/haos-gateway');value=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2]\n    policy=lambda:PreparedDingTalkPolicy(json.loads(Path('/etc/haos/gateways.json').read_text()))\n    parent=base/'profiles';parent.mkdir(mode=0o700,exist_ok=True)\n    inbox=NativeInbox(base/'ws-inbox.db',Redactor());relay=RelayInbox(base/'relay.db',Redactor())\n    def create():\n        adapter=build(value,parent=parent,connector='dingtalk',policy=policy,inbox=inbox)\n        def receive(event):\n            assert event.raw_message is None\n            relay.admit(policy(),'dingtalk',adapter_envelope(event,'dingtalk'));return True\n        adapter.set_durable_message_handler(receive);return adapter\n    adapter=create()\n    try:\n        if mode in {'authentication-refused','rate-limited','transport-unavailable'}:\n            assert not await adapter.connect();assert adapter.native_health()['status']==mode,adapter.native_health()\n            first=adapter.native_health();assert not await adapter.connect()\n            await adapter.close_profile();adapter=create()\n            assert not await adapter.connect();assert adapter.native_health()['status']==mode\n            assert adapter.native_health()['next_attempt']==first['next_attempt']\n            print('blocked',flush=True);return\n        assert await adapter.connect(),adapter.native_health();print('ready',flush=True)\n        while adapter.native_health()['status']!='revoked':await asyncio.sleep(.02)\n        assert adapter._haos_dingtalk_socket is None\n        print('stopped',flush=True)\n    finally:\n        await adapter.close_profile();relay.close();inbox.close()\nasyncio.run(main())\n");script.chmod(0o644)
    async def exercise():
        import asyncio,sqlite3
        from aiohttp import web,WSMsgType
        from dingtalk_stream import ChatbotMessage
        discoveries=[];connections=[];acks=[];failures=[];state={'mode':'ok'}
        first=asyncio.Event();second=asyncio.Event();third=asyncio.Event()
        binding=policy['bindings'][0];now=int(time.time()*1000)
        body={'msgId':'nativeMessage-123','createAt':now-1000,'senderId':binding['sender'],
            'senderCorpId':value['corp_id'],'chatbotCorpId':value['corp_id'],'robotCode':value['robot_code'],
            'conversationId':binding['chat'],'conversationType':'1','msgtype':'text',
            'text':{'content':'Actual private supervised DingTalk source.'},
            'sessionWebhook':'https://oapi.dingtalk.com/robot/sendBySession?session=private-process-session',
            'sessionWebhookExpiredTime':now+7200000}
        async def discovery(request):
            assert request.secure;data=await request.json()
            assert data['clientId']==value['client_id'] and data['clientSecret']==value['client_secret']
            assert data['subscriptions']==[{'type':'CALLBACK','topic':ChatbotMessage.TOPIC}]
            assert data['localIp']=='';discoveries.append('native')
            return web.json_response({'endpoint':'wss://wss-open-connection.dingtalk.com/connect','ticket':'private-process-ticket'})
        async def websocket(request):
            assert request.secure and request.query=={'ticket':'private-process-ticket'}
            if state['mode'] in {'401','429','302'}:
                return web.Response(status=int(state['mode']),headers={'Location':'https://api.dingtalk.com/unreviewed'})
            ws=web.WebSocketResponse(compress=False);await ws.prepare(request);connections.append(ws)
            await ws.send_json({'specVersion':'1.0','type':'CALLBACK','headers':{
                'messageId':'native-callback-fixture','time':str(now),'contentType':'application/json',
                'appId':value['client_id'],'topic':ChatbotMessage.TOPIC},'data':json.dumps(body)})
            response=await ws.receive(timeout=15);assert response.type==WSMsgType.TEXT
            ack=json.loads(response.data)
            assert ack['code']==200 and ack['headers']['messageId']=='native-callback-fixture'
            assert json.loads(ack['data'])=={'response':'OK'};acks.append(ack)
            with sqlite3.connect(next((base/'profiles').glob('dingtalk-*/originals.db'))) as db:
                assert db.execute('SELECT COUNT(*) FROM dingtalk_raw_events').fetchone()[0]==1
                original=db.execute('SELECT data FROM dingtalk_raw_events').fetchone()[0]
                assert original==json.dumps(body).encode()
            with sqlite3.connect(base/'ws-inbox.db') as db:
                assert db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
            if len(connections)==1:first.set();await ws.close()
            else:
                (second if len(connections)==2 else third).set()
                async for _ in ws:pass
            return ws
        @web.middleware
        async def checked(request,handler):
            try:return await handler(request)
            except Exception as error:failures.append(type(error).__name__);raise
        async def forbidden(request):raise AssertionError('redirect was followed')
        app=web.Application(middlewares=[checked]);app.router.add_post('/v1.0/gateway/connections/open',discovery)
        app.router.add_get('/connect',websocket);app.router.add_get('/unreviewed',forbidden)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(work/'certificate.pem',work/'key.pem')
        ws_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ws_tls.load_cert_chain(ws_cert/'certificate.pem',ws_cert/'key.pem')
        def choose(sock,name,_context):
            if name=='wss-open-connection.dingtalk.com':sock.context=ws_tls
        tls.set_servername_callback(choose)
        await web.TCPSite(runner,'127.0.0.1',443,ssl_context=tls).start()
        children=[];cases=[]
        def identity():os.setgroups([]);os.setgid(65534);os.setuid(65534)
        async def start(mode):
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(script),str(account),mode,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,preexec_fn=identity,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(base),'HERMES_SAFE_MODE':'1'})
            children.append(child);return child
        def workers(parent):
            result=[]
            for proc in Path('/proc').iterdir():
                if not proc.name.isdecimal():continue
                try:
                    fields=dict(line.split(':',1) for line in (proc/'status').read_text().splitlines() if ':' in line)
                    if int(fields['PPid'])==parent and fields['Uid'].split()[0]=='65534':result.append(proc)
                except (FileNotFoundError,ProcessLookupError):pass
            return result
        try:
            child=await start('twice')
            assert await asyncio.wait_for(child.stdout.readline(),45)==b'ready\n'
            await asyncio.wait_for(first.wait(),15)
            await asyncio.wait_for(second.wait(),15)
            assert discoveries==['native','native'] and len(acks)==2
            deadline=time.monotonic()+5
            while True:
                with sqlite3.connect(base/'relay.db') as db:count=db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]
                if count==1:break
                assert time.monotonic()<deadline;await asyncio.sleep(.05)
            cases.extend(['actual_gateway_UID_native_Hermes_profile_verified_TLS_WSS',
                'actual_SDK_ACK_after_private_FULL_original_and_native_input_commit',
                'actual_production_profile_reconnect_replays_one_original_one_input_one_native_Hermes_relay_obligation'])
            agent_code='''
import json,sys
from pathlib import Path
for path in json.load(sys.stdin):
    try:Path(path).read_bytes()
    except (PermissionError,FileNotFoundError):pass
    else:raise AssertionError('agent read private callback session or credentials')
print('denied')
'''
            worker=workers(child.pid);assert len(worker)==1
            agent=subprocess.run([sys.executable,'-c',agent_code],input=json.dumps([str(account),str(canary),
                str(next((base/'profiles').glob('dingtalk-*/originals.db'))),str(next((base/'profiles').glob('dingtalk-*/originals.db-wal'))),'/proc/'+worker[0].name+'/fd/0']),
                text=True,capture_output=True,user=65533,group=65533,extra_groups=[],timeout=5)
            assert agent.returncode==0 and agent.stdout=='denied\n',agent.stderr
            cases.append('actual_agent_UID_cannot_read_credentials_original_bearer_session_SQLite_WAL_owner_or_worker_stdin')
            publish({**policy,'bindings':[]});out,err=await asyncio.wait_for(child.communicate(),5)
            assert child.returncode==0 and out==b'stopped\n',(out,err)
            assert value['client_secret'].encode() not in err and b'private-process-ticket' not in err
            assert not workers(child.pid)
            cases.append('actual_root_policy_withdrawal_terminates_and_joins_private_continuous_worker_without_ticket_disclosure')
            publish(policy);child=await start('once')
            assert await asyncio.wait_for(child.stdout.readline(),45)==b'ready\n'
            await asyncio.wait_for(third.wait(),15);worker=workers(child.pid);assert len(worker)==1
            pid=int(worker[0].name);child.kill();await child.wait();deadline=time.monotonic()+5
            while True:
                result,status=os.waitpid(pid,os.WNOHANG)
                if result:assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;break
                assert time.monotonic()<deadline;await asyncio.sleep(.02)
            cases.append('actual_parent_SIGKILL_causes_kernel_PDEATHSIG_SIGKILL_of_socket_worker')
            for mode,expected in [('401','authentication-refused'),('429','rate-limited'),('302','transport-unavailable')]:
                state['mode']=mode;before=len(discoveries);child=await start(expected)
                out,err=await asyncio.wait_for(child.communicate(),45)
                assert child.returncode==0 and out==b'blocked\n',(out,err)
                assert len(discoveries)==before+1
                cases.append('actual_profile_WSS_'+mode+'_persistent_block_or_deadline_survives_connect_close_and_profile_reopen_without_another_discovery')
                value['client_secret']='private-profile-credential-rotation-'+mode
                account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
            assert not failures,failures
            print(json.dumps({'passed':len(cases),'cases':cases,'actual_UIDs':[0,65533,65534],
                'live_or_installed_dingtalk_acceptance':False,'API_WSS_domains_mapped_only_in_offline_fixture_hosts':True,
                'owner_publication_and_external_account_are_fixtures_profile_supervisor_is_actual':True,
                'live_messages_missions_or_installed_acceptance':False}))
        finally:
            for child in children:
                if child.returncode is None:child.kill();await child.wait()
            for ws in connections:await ws.close()
            await runner.cleanup()
    import asyncio
    asyncio.run(exercise())


if __name__=='__main__':main()
