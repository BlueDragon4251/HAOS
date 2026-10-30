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
            or os.environ.get('HAOS_DISPOSABLE_DINGTALK_REPLY_PROCESS')!='1' or Path('/usr/lib/haos').exists()
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
    reply_mode=os.environ.get('HAOS_DINGTALK_REPLY_MODE','session')
    if reply_mode not in {'session','robot'}:raise PermissionError('explicit fixture reply mode required')
    conversation=os.environ.get('HAOS_DINGTALK_REPLY_CONVERSATION','oto')
    if conversation not in {'oto','group'} or reply_mode=='session' and conversation!='oto':raise PermissionError('reviewed fixture route required')
    if reply_mode=='robot':value['reply_mode']='robot'
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
    script=work/'gateway_profile_fixture.py';script.write_text("\nimport asyncio,json,sys,hashlib\nfrom pathlib import Path\nfrom haos.gateway_dingtalk import PreparedDingTalkPolicy\nfrom haos.gateway_dingtalk_profile import build\nfrom haos.gateway_raw import NativeInbox\nfrom haos.gateway_relay import RelayInbox\nfrom haos.gateway_runtime import adapter_envelope\nfrom haos.redaction import Redactor\nasync def main():\n    base=Path('/var/lib/haos-gateway');value=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2]\n    policy=lambda:PreparedDingTalkPolicy(json.loads(Path('/etc/haos/gateways.json').read_text()))\n    parent=base/'profiles';parent.mkdir(mode=0o700,exist_ok=True)\n    inbox=NativeInbox(base/'ws-inbox.db',Redactor());relay=RelayInbox(base/'relay.db',Redactor())\n    def create():\n        adapter=build(value,parent=parent,connector='dingtalk',policy=policy,inbox=inbox)\n        def receive(event):\n            assert event.raw_message is None\n            relay.admit(policy(),'dingtalk',adapter_envelope(event,'dingtalk'));return True\n        adapter.set_durable_message_handler(receive);return adapter\n    adapter=create()\n    try:\n        if mode in {'authentication-refused','rate-limited','transport-unavailable'}:\n            assert not await adapter.connect();assert adapter.native_health()['status']==mode,adapter.native_health()\n            first=adapter.native_health();assert not await adapter.connect()\n            await adapter.close_profile();adapter=create()\n            assert not await adapter.connect();assert adapter.native_health()['status']==mode\n            assert adapter.native_health()['next_attempt']==first['next_attempt']\n            print('blocked',flush=True);return\n        assert await adapter.connect(),adapter.native_health();print('ready',flush=True)\n        while relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]!=1 or not adapter.is_connected:\n            await asyncio.sleep(.02)\n        ack_path=Path(sys.argv[3])\n        while not ack_path.exists() or ack_path.read_text()!=sys.argv[4]:await asyncio.sleep(.02)\n        from haos.gateway import digest\n        binding=policy().bindings['owner']\n        metadata={'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},\n            'haos_scope':binding['scope'],'thread_id':'','haos_delivery_id':'c'*64,'haos_delivery_attempt':1}\n        if mode in {'cancel-write','revoke-write','orphan-write','deadline-write','disconnect-write','close-write'}:\n            delivery=hashlib.sha256(mode.encode()).hexdigest();metadata['haos_delivery_id']=delivery\n            task=asyncio.create_task(adapter.send(binding['chat'],mode,reply_to='nativeMessage-123',metadata=metadata))\n            stopping=None\n            if mode in {'cancel-write','disconnect-write','close-write'}:\n                await asyncio.get_running_loop().run_in_executor(None,sys.stdin.readline)\n                if mode=='cancel-write':task.cancel()\n                else:stopping=asyncio.create_task(adapter.disconnect() if mode=='disconnect-write' else adapter.close_profile())\n            try:result=await task\n            except (asyncio.CancelledError,PermissionError):\n                assert mode in {'cancel-write','revoke-write','disconnect-write','close-write'}\n            else:\n                assert mode=='deadline-write' and not result.success and result.raw_response=={'haos_delivery':'uncertain'}\n            if stopping is not None:await asyncio.wait_for(stopping,5)\n            row=inbox.db.execute('SELECT state FROM dingtalk_delivery_intents WHERE delivery_id=?',(delivery,)).fetchone()\n            assert row['state']=='uncertain'\n            if mode not in {'revoke-write','disconnect-write','close-write'}:\n                metadata['haos_delivery_attempt']=2\n                repeated=await adapter.send(binding['chat'],mode,reply_to='nativeMessage-123',metadata=metadata)\n                assert not repeated.success and repeated.raw_response=={'haos_delivery':'uncertain'}\n            print('quarantined',flush=True);return\n        for previous_mode in ['orphan-write']:\n            delivery=hashlib.sha256(previous_mode.encode()).hexdigest()\n            row=inbox.db.execute('SELECT state FROM dingtalk_delivery_intents WHERE delivery_id=?',(delivery,)).fetchone()\n            if row is not None:\n                assert row['state']=='uncertain'\n                check={**metadata,'haos_delivery_id':delivery,'haos_delivery_attempt':2}\n                result=await adapter.send(binding['chat'],previous_mode,reply_to='nativeMessage-123',metadata=check)\n                assert not result.success and result.raw_response=={'haos_delivery':'uncertain'}\n        result=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='nativeMessage-123',metadata=metadata)\n        assert result.success and result.message_id.startswith('haos-dingtalk-')\n        assert result.raw_response=={'remote_message_id':None,'recipient_read_verified':False,'local_vendor_acceptance_only':True}\n        metadata['haos_delivery_attempt']=2\n        duplicate=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='nativeMessage-123',metadata=metadata)\n        assert duplicate.success and duplicate.message_id==result.message_id\n        metadata['haos_delivery_id']='d'*64;metadata['haos_delivery_attempt']=1\n        uncertain=await adapter.send(binding['chat'],'Uncertain private native reply.',reply_to='nativeMessage-123',metadata=metadata)\n        assert not uncertain.success and uncertain.raw_response=={'haos_delivery':'uncertain'}\n        row=inbox.db.execute('SELECT state FROM dingtalk_delivery_intents WHERE delivery_id=?',('d'*64,)).fetchone()\n        assert row['state']=='uncertain'\n        metadata['haos_delivery_attempt']=2\n        repeated=await adapter.send(binding['chat'],'Uncertain private native reply.',reply_to='nativeMessage-123',metadata=metadata)\n        assert not repeated.success and repeated.raw_response=={'haos_delivery':'uncertain'}\n        print('sent',flush=True)\n        while adapter.native_health()['status']!='revoked':await asyncio.sleep(.02)\n        assert adapter._haos_dingtalk_socket is None\n        print('stopped',flush=True)\n    finally:\n        await adapter.close_profile();relay.close();inbox.close()\nasyncio.run(main())\n");script.chmod(0o644)
    async def exercise():
        import asyncio,sqlite3
        from aiohttp import web,WSMsgType
        from dingtalk_stream import ChatbotMessage
        discoveries=[];connections=[];acks=[];replies=[];failures=[];state={'mode':'ok'}
        state['ack_generation']=0
        first=asyncio.Event();second=asyncio.Event();third=asyncio.Event();write_entered=asyncio.Event();write_release=asyncio.Event()
        binding=policy['bindings'][0];now=int(time.time()*1000)
        body={'msgId':'nativeMessage-123','createAt':now-1000,'senderId':binding['sender'],
            'senderCorpId':value['corp_id'],'chatbotCorpId':value['corp_id'],'robotCode':value['robot_code'],
            'conversationId':binding['chat'],'conversationType':'1','msgtype':'text',
            'text':{'content':'Actual private supervised DingTalk source.'},
            'sessionWebhook':'https://api.dingtalk.com/robot/sendBySession?session=private-process-session',
            'sessionWebhookExpiredTime':now+7200000}
        if reply_mode=='robot':
            body.update(senderStaffId='native-approved-staff',sessionWebhookExpiredTime=now-500,
                conversationType='2' if conversation=='group' else '1',isInAtList=True)
        async def token(request):
            assert request.secure and await request.json()=={'appKey':value['client_id'],'appSecret':value['client_secret']}
            return web.json_response({'accessToken':'private-native-reply-token','expireIn':7200})
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
            ack_path=work/'callback-ack-generation';ack_path.write_text(str(state['ack_generation']));ack_path.chmod(0o644)
            if len(connections)==1:first.set();await ws.close()
            else:
                (second if len(connections)==2 else third).set()
                async for _ in ws:pass
            return ws
        async def reply(request):
            assert request.secure
            assert request.query==({'session':'private-process-session'} if reply_mode=='session' else {})
            assert request.headers.get('Cookie') is None and request.headers.get('Accept-Encoding')=='identity'
            payload=await request.json()
            if reply_mode=='robot':
                assert request.path==('/v1.0/robot/groupMessages/send' if conversation=='group' else '/v1.0/robot/oToMessages/batchSend')
                assert request.headers['x-acs-dingtalk-access-token']=='private-native-reply-token'
                assert set(payload)=={'msgKey','msgParam','robotCode'}|({'openConversationId'} if conversation=='group' else {'userIds'})
                assert payload['robotCode']==value['robot_code']
                if conversation=='group':assert payload['openConversationId']==binding['chat']
                else:assert payload['userIds']==['native-approved-staff']
                assert payload['msgKey']=='sampleMarkdown'
                payload={'msgtype':'markdown','markdown':json.loads(payload['msgParam'])}
            assert payload['msgtype']=='markdown' and payload['markdown']['title']=='Hermes'
            assert payload['markdown']['text'] in {'Actual private native reply.','Uncertain private native reply.','cancel-write','revoke-write','orphan-write','deadline-write','disconnect-write','close-write'}
            text=payload['markdown']['text']
            import hashlib
            delivery='c'*64 if text=='Actual private native reply.' else 'd'*64 if text=='Uncertain private native reply.' else hashlib.sha256(text.encode()).hexdigest()
            with sqlite3.connect(base/'ws-inbox.db') as db:
                assert db.execute('SELECT state FROM dingtalk_delivery_intents WHERE delivery_id=?',(delivery,)).fetchone()[0]=='writing'
            replies.append(payload)
            if text in {'cancel-write','revoke-write','orphan-write','disconnect-write','close-write'}:
                write_entered.set();await asyncio.wait_for(write_release.wait(),20)
            if text=='deadline-write':
                response=web.StreamResponse(headers={'Content-Type':'application/json','Content-Length':'50000'})
                await response.prepare(request);write_entered.set()
                try:
                    for _ in range(50000):await response.write(b' ');await asyncio.sleep(.1)
                except (ConnectionResetError,RuntimeError):pass
                return response
            if delivery=='d'*64:
                request.transport.abort()
                return web.Response(status=200)
            return web.json_response({'errcode':0,'errmsg':'ok'} if reply_mode=='session' else {'processQueryKey':'fixture-native-queued-result','invalidStaffIdList':[],'flowControlledStaffIdList':[]})
        @web.middleware
        async def checked(request,handler):
            try:return await handler(request)
            except Exception as error:failures.append(type(error).__name__);raise
        async def forbidden(request):raise AssertionError('redirect was followed')
        app=web.Application(middlewares=[checked]);app.router.add_post('/v1.0/gateway/connections/open',discovery)
        app.router.add_get('/connect',websocket);app.router.add_get('/unreviewed',forbidden);app.router.add_post('/robot/sendBySession',reply)
        app.router.add_post('/v1.0/oauth2/accessToken',token)
        app.router.add_post('/v1.0/robot/oToMessages/batchSend',reply)
        app.router.add_post('/v1.0/robot/groupMessages/send',reply)
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
            state['ack_generation']+=1
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(script),str(account),mode,str(work/'callback-ack-generation'),str(state['ack_generation']),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,preexec_fn=identity,
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
            assert await asyncio.wait_for(child.stdout.readline(),10)==b'sent\n'
            assert len(replies)==2
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
            assert value['client_secret'].encode() not in err and b'private-process-ticket' not in err and b'private-process-session' not in err
            assert not workers(child.pid)
            cases.append('actual_parent_FULL_write_intent_precedes_HTTP_and_dropped_reply_is_quarantined_without_resend_across_attempt_or_profile_restart')
            cases.append('actual_native_reply_private_worker_vendor_ACK_and_per_write_journal_confirmed_replay_emit_one_HTTP_write_and_no_fake_remote_ID')
            cases.append('actual_root_policy_withdrawal_terminates_and_joins_private_continuous_worker_without_ticket_disclosure')
            publish(policy);child=await start('once')
            assert await asyncio.wait_for(child.stdout.readline(),45)==b'ready\n'
            await asyncio.wait_for(third.wait(),15)
            assert await asyncio.wait_for(child.stdout.readline(),10)==b'sent\n' and len(replies)==2
            worker=workers(child.pid);assert len(worker)==1
            pid=int(worker[0].name);child.kill();await child.wait();deadline=time.monotonic()+5
            while True:
                result,status=os.waitpid(pid,os.WNOHANG)
                if result:assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;break
                assert time.monotonic()<deadline;await asyncio.sleep(.02)
            cases.append('actual_parent_SIGKILL_causes_kernel_PDEATHSIG_SIGKILL_of_socket_worker')
            for mode in ['cancel-write','revoke-write','orphan-write','deadline-write','disconnect-write','close-write']:
                publish(policy);write_entered.clear();write_release.clear();before=len(replies);child=await start(mode)
                assert await asyncio.wait_for(child.stdout.readline(),45)==b'ready\n'
                await asyncio.wait_for(write_entered.wait(),15)
                active=workers(child.pid);assert len(active)==2
                start_time=time.monotonic()
                if mode=='orphan-write':
                    pids=[int(proc.name) for proc in active];child.kill();await child.wait()
                    deadline=time.monotonic()+5
                    for pid in pids:
                        while True:
                            result,status=os.waitpid(pid,os.WNOHANG)
                            if result:assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;break
                            assert time.monotonic()<deadline;await asyncio.sleep(.02)
                    with sqlite3.connect(base/'ws-inbox.db') as db:
                        import hashlib
                        assert db.execute('SELECT state FROM dingtalk_delivery_intents WHERE delivery_id=?',
                            (hashlib.sha256(mode.encode()).hexdigest(),)).fetchone()[0]=='writing'
                else:
                    if mode in {'cancel-write','disconnect-write','close-write'}:child.stdin.write(b'cancel\n');await child.stdin.drain()
                    elif mode=='revoke-write':publish({**policy,'bindings':[]})
                    out,err=await asyncio.wait_for(child.communicate(),35 if mode=='deadline-write' else 5)
                    assert child.returncode==0 and out==b'quarantined\n',(out,err)
                    assert not workers(child.pid)
                    if mode=='deadline-write':assert 20<time.monotonic()-start_time<35
                write_release.set();assert len(replies)==before+1
                cases.append('actual_native_reply_'+mode+'_terminates_private_worker_and_retains_begun_write_without_implicit_retry')
                if mode=='orphan-write':
                    child=await start('once')
                    assert await asyncio.wait_for(child.stdout.readline(),45)==b'ready\n'
                    assert await asyncio.wait_for(child.stdout.readline(),15)==b'sent\n'
                    assert len(replies)==before+1
                    publish({**policy,'bindings':[]});out,err=await asyncio.wait_for(child.communicate(),5)
                    assert child.returncode==0 and out==b'stopped\n',(out,err)
            publish(policy)
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
                'public_dingtalk_enabled':False,'reply_mode':reply_mode,'conversation':conversation,'API_WSS_domains_mapped_only_in_offline_fixture_hosts':True,
                'owner_publication_and_external_account_are_fixtures_profile_supervisor_is_actual':True,
                'live_messages_missions_or_installed_acceptance':False}))
        finally:
            write_release.set()
            for child in children:
                if child.returncode is None:child.kill();await child.wait()
            for ws in connections:await ws.close()
            await runner.cleanup()
    import asyncio
    asyncio.run(exercise())


if __name__=='__main__':main()
