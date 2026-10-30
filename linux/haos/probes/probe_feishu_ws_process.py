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
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_FEISHU_WS_PROCESS')!='1'
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
            'identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':123,'require_mention':True}]}
    config=Path('/etc/haos');config.mkdir(mode=0o755);policy_path=config/'gateways.json'
    def publish(data):
        PreparedFeishuPolicy(data)
        path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(policy_path)
    publish(policy)
    script=work/'ws_gateway_fixture.py'
    script.write_text("""
import asyncio,json,os,sys
from pathlib import Path
from haos.gateway_feishu import PreparedFeishuPolicy
from haos.gateway_runtime import build_adapter
def build(value,**context):return build_adapter('feishu',value,feishu_context=context)
from haos.gateway_raw import NativeInbox
from haos.gateway_relay import RelayInbox
from haos.gateway_runtime import adapter_envelope
from haos.redaction import Redactor
async def main():
    value=json.loads(Path(sys.argv[1]).read_text());base=Path('/var/lib/haos-gateway')
    def policy():
        from haos.gateway import GatewayPolicy
        return GatewayPolicy(json.loads(Path('/etc/haos/gateways.json').read_text()))
    inbox=NativeInbox(base/'ws-inbox.db',Redactor());relay=RelayInbox(base/'ws-relay.db',Redactor())
    parent=base/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
    adapter=build(value,parent=parent,connector='feishu',policy=policy,inbox=inbox)
    def receive(event):relay.admit(policy(),'feishu',adapter_envelope(event,'feishu'));return True
    adapter.set_durable_message_handler(receive)
    try:
        if len(sys.argv)>2:
            assert not await adapter.connect()
            assert adapter.native_health()['status']==sys.argv[2],adapter.native_health()
            assert not await adapter.connect()
            print('blocked',flush=True);return
        assert await adapter.connect(),adapter.native_health();print('ready',flush=True)
        while adapter.native_health()['status']!='revoked':await asyncio.sleep(.05)
        assert adapter._haos_feishu_socket is None
        print('stopped',flush=True)
    finally:await adapter.close_profile();relay.close();inbox.close()
asyncio.run(main())
""")
    account=base/'ws-account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    async def exercise():
        import asyncio
        from aiohttp import web,WSMsgType
        import lark_oapi.ws.client as sdk
        seen=[];ack=asyncio.Event();reconnected=asyncio.Event();third_ack=asyncio.Event();connections=[];original=[None];state={'mode':'ok'}
        async def token(request):
            assert await request.json()=={'app_id':value['app_id'],'app_secret':value['app_secret']}
            seen.append('auth');return web.json_response({'code':0,'tenant_access_token':'private-ws-process-token','expire':7200})
        async def bot(request):
            assert request.headers['Authorization']=='Bearer private-ws-process-token'
            seen.append('bot');return web.json_response({'code':0,'bot':{'open_id':value['bot_open_id']}})
        async def discover(request):
            assert request.secure and await request.json()=={'AppID':value['app_id'],'AppSecret':value['app_secret']}
            seen.append('discovery')
            return web.json_response({'code':0,'data':{'URL':'wss://open.feishu.cn/ws/v2?device_id=fixture-device&service_id=1&ticket=private-process-ticket',
                'ClientConfig':{'ReconnectCount':-1,'ReconnectInterval':120,'ReconnectNonce':30,'PingInterval':120}}})
        async def websocket(request):
            if state['mode']=='auth':return web.Response(status=401)
            if state['mode']=='rate':return web.Response(status=429)
            ws=web.WebSocketResponse();await ws.prepare(request);connections.append(ws)
            stamp=str(int(time.time()*1000)-1000);binding=policy['bindings'][0]
            body=json.dumps({'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1',
                'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
                'event':{'sender':{'sender_id':{'open_id':binding['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
                'message':{'message_id':'om_'+'f'*32,'create_time':stamp,'chat_id':binding['chat'],'chat_type':'p2p',
                    'message_type':'text','content':json.dumps({'text':'Actual supervised native source 1.'})}}}).encode()
            if original[0] is None:original[0]=body
            else:body=original[0]
            frame=sdk.Frame();frame.SeqID=0;frame.LogID=0;frame.method=sdk.FrameType.DATA.value;frame.service=1;frame.payload=body
            for key,item in {'message_id':'fixture_ws_message','trace_id':'fixture_trace','sum':'1','seq':'0','type':'event'}.items():
                header=frame.headers.add();header.key=key;header.value=item
            await ws.send_bytes(frame.SerializeToString());response=await ws.receive(timeout=20)
            assert response.type==WSMsgType.BINARY
            reply=sdk.Frame();reply.ParseFromString(response.data)
            if reply.method==sdk.FrameType.CONTROL.value:
                assert {header.key:header.value for header in reply.headers}['type']=='ping'
                response=await ws.receive(timeout=20);assert response.type==WSMsgType.BINARY
                reply=sdk.Frame();reply.ParseFromString(response.data)
            assert reply.method==sdk.FrameType.DATA.value and json.loads(reply.payload)['code']==200, (reply.method,reply.payload)
            import sqlite3
            db=sqlite3.connect(base/'ws-inbox.db')
            assert db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM feishu_source_context').fetchone()[0]==1;db.close()
            if len(connections)==1:
                ack.set();await ws.close()
            else:
                reconnected.set()
                if len(connections)==3:third_ack.set()
                async for _ in ws:pass
            return ws
        failures=[]
        @web.middleware
        async def checked_handler(request,handler):
            try:return await handler(request)
            except Exception as error:failures.append(type(error).__name__);raise
        app=web.Application(middlewares=[checked_handler]);app.router.add_post('/callback/ws/endpoint',discover);app.router.add_get('/ws/v2',websocket)
        app.router.add_post('/open-apis/auth/v3/tenant_access_token/internal',token);app.router.add_get('/open-apis/bot/v3/info',bot)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(work/'certificate.pem',work/'key.pem')
        await web.TCPSite(runner,'127.0.0.1',443,ssl_context=tls).start()
        def identity():os.setgroups([]);os.setgid(65534);os.setuid(65534)
        child=None
        try:
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(script),str(account),
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,preexec_fn=identity,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(base),'HERMES_HOME':str(base/'.hermes')})
            try:await asyncio.wait_for(ack.wait(),60)
            except Exception:
                if child.returncode is None:child.kill()
                await child.wait()
                raise AssertionError('private WS profile failed before durable ACK') from None
            assert await asyncio.wait_for(child.stdout.readline(),5)==b'ready\n'
            await asyncio.wait_for(reconnected.wait(),20)
            import sqlite3
            end=time.monotonic()+5
            while True:
                db=sqlite3.connect(base/'ws-relay.db')
                count=db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0];db.close()
                if count==1:break
                assert time.monotonic()<end;await asyncio.sleep(.1)
            original_db=next((base/'profiles').glob('feishu-*/originals.db'))
            db=sqlite3.connect(original_db);assert db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]==1;db.close()
            publish({'version':1,'connectors':[],'bindings':[]})
            await asyncio.wait_for(child.wait(),5)
            out=await child.stdout.read();err=await child.stderr.read()
            assert child.returncode==0,(out,err)
            assert out==b'stopped\n' and value['app_secret'].encode() not in err and b'private-process-ticket' not in err
            assert seen==['auth','bot','discovery','discovery'],seen
            publish(policy)
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(script),str(account),
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,preexec_fn=identity,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(base),'HERMES_HOME':str(base/'.hermes')})
            assert await asyncio.wait_for(child.stdout.readline(),60)==b'ready\n'
            await asyncio.wait_for(third_ack.wait(),10)
            workers=[]
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit():continue
                try:
                    status=(proc/'status').read_text();fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
                    if int(fields['PPid'])==child.pid and fields['Uid'].split()[0]=='65534':workers.append(proc)
                except (FileNotFoundError,ProcessLookupError):pass
            assert len(workers)==1
            child.kill();await child.wait();end=time.monotonic()+5
            while workers[0].exists():
                try:
                    if 'State:\tZ' in (workers[0]/'status').read_text():break
                except FileNotFoundError:break
                assert time.monotonic()<end;await asyncio.sleep(.05)
            for mode,expected in [('auth','authentication-refused'),('rate','rate-limited')]:
                state['mode']=mode;before=len(seen)
                child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',str(script),str(account),expected,
                    stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,preexec_fn=identity,
                    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(base),'HERMES_HOME':str(base/'.hermes')})
                out,err=await asyncio.wait_for(child.communicate(),80)
                assert child.returncode==0 and out==b'blocked\n',(out,err)
                assert seen[before:]==['auth','bot','discovery'],seen[before:]
                # Distinct account publication for the next case avoids clearing any persisted block.
                value['app_secret']='private-ws-process-fixture-rotated'
                account.write_text(json.dumps(value));os.chown(account,65534,65534);account.chmod(0o600)
            assert not failures,failures
            print(json.dumps({'passed':9,'cases':['actual_private_uid_native_runner_https_verified_wss',
                'actual_native_protobuf_ack_after_independent_parent_full_sqlite_commit',
                'root_publication_withdrawal_terminates_continuous_worker',
                'no_hidden_sdk_reconnect_or_ticket_disclosure','private_profile_reconnects_with_fresh_supervised_worker',
                'remote_duplicate_replay_keeps_one_original_one_native_input_one_relay_mission',
                'actual_gateway_parent_sigkill_terminates_ws_worker_via_kernel_parent_death_signal',
                'actual_wss_401_persists_authentication_block_without_automatic_retry',
                'actual_wss_429_persists_rate_deadline_second_connect_cannot_bypass']}))
        finally:
            if child is not None and child.returncode is None:child.kill();await child.wait()
            for ws in connections:await ws.close()
            await runner.cleanup()
    import asyncio
    asyncio.run(exercise())


if __name__=='__main__':main()
