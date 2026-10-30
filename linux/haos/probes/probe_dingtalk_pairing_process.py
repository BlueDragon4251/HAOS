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
            or os.environ.get('HAOS_DISPOSABLE_DINGTALK_PAIRING_PROCESS')!='1' or Path('/usr/lib/haos').exists()
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
    saved=config/'gateway-credentials';saved.write_text(json.dumps({'connectors':{'dingtalk':value}}));saved.chmod(0o600)
    bridge=work/'owner_bridge.py';bridge.write_text("""
import json,sys
from haos import initial_setup,gateway_setup,owner
from haos import dingtalk_owner_setup
initial_setup.quiesce_for_setup=lambda **kwargs:None
gateway_setup.stopped_gateway=lambda:None
owner.audit=lambda *args:None
request=json.load(sys.stdin)
result=(dingtalk_owner_setup.inspect('dingtalk') if request['action']=='account' else
    dingtalk_owner_setup.observe('dingtalk',request['observation']))
print(json.dumps(result))
""");bridge.chmod(0o644)
    async def exercise():
        import asyncio,sqlite3
        from aiohttp import web,WSMsgType
        from dingtalk_stream import ChatbotMessage
        state={};requests=[];acks=[];failures=[];connections=[];children=[];cases=[]
        def body(challenge=True):
            return {'msgId':'native-pairing-'+state['mode']+('-challenge' if challenge else '-ordinary'),
                'createAt':int(time.time()*1000),'senderId':policy['bindings'][0]['sender'],
                'senderCorpId':value['corp_id'],'chatbotCorpId':value['corp_id'],'robotCode':value['robot_code'],
                'conversationId':policy['bindings'][0]['chat'],'conversationType':'1','msgtype':'text',
                'text':{'content':'HAOS koppeln '+state['observation']['nonce'] if challenge else 'Already approved ordinary message.'}}
        async def discovery(request):
            assert request.secure;data=await request.json();assert data['clientId']==value['client_id'] and data['clientSecret']==value['client_secret']
            assert data['subscriptions']==[{'type':'CALLBACK','topic':ChatbotMessage.TOPIC}] and data['localIp']==''
            requests.append('native-discovery')
            return web.json_response({'endpoint':'wss://wss-open-connection.dingtalk.com/connect','ticket':'private-pairing-ticket'})
        async def token(request):
            assert request.secure and await request.json()=={'appKey':value['client_id'],'appSecret':value['client_secret']}
            requests.append('native-token');return web.json_response({'accessToken':'private-observation-fixture-token','expireIn':7200})
        async def websocket(request):
            assert request.secure and request.query=={'ticket':'private-pairing-ticket'}
            ws=web.WebSocketResponse(compress=False);await ws.prepare(request);connections.append(ws);state['connected'].set()
            if state['mode']=='withdraw':
                async for _ in ws:pass
                return ws
            messages=[body(False),body()] if state['mode']=='existing-grant' else [body()]
            if state['mode']=='wrong-nonce':messages[0]['text']['content']='HAOS koppeln '+'f'*32
            if state['mode']=='wrong-corp':messages[0]['senderCorpId']='another_corporation'
            for index,data in enumerate(messages):
                await ws.send_json({'specVersion':'1.0','type':'CALLBACK','headers':{'messageId':'callback-'+str(index),
                    'time':str(int(time.time()*1000)),'contentType':'application/json','appId':value['client_id'],
                    'topic':ChatbotMessage.TOPIC},'data':json.dumps(data)})
                reply=await ws.receive(timeout=15)
                if state['mode'] in {'wrong-nonce','wrong-corp'}:
                    assert reply.type in {WSMsgType.CLOSE,WSMsgType.CLOSED,WSMsgType.ERROR};return ws
                assert reply.type==WSMsgType.TEXT,(reply.type,reply.data)
                ack=json.loads(reply.data);assert ack['code']==200 and ack['headers']['messageId']=='callback-'+str(index)
                assert json.loads(ack['data'])=={'response':'OK'}
                with sqlite3.connect(base/'native-inbox.db') as db:
                    if state['mode']=='existing-grant' and index==0:
                        assert db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
                        assert db.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
                    else:
                        record=db.execute('SELECT metadata FROM dingtalk_pairing_candidates ORDER BY created_at DESC LIMIT 1').fetchone()
                        item=json.loads(record[0]);assert item['authorized'] is False and not item['mission_created'] and not item['message_sent']
                        assert item['sender']==data['senderId'] and item['source_sha256']==__import__('hashlib').sha256(json.dumps(data).encode()).hexdigest()
                        assert item['challenge_sha256']==__import__('haos.gateway',fromlist=['digest']).digest(state['observation'])
                acks.append(state['mode'])
            async for _ in ws:pass
            return ws
        @web.middleware
        async def checked(request,handler):
            try:return await handler(request)
            except Exception as error:failures.append(type(error).__name__);raise
        app=web.Application(middlewares=[checked]);app.router.add_post('/v1.0/gateway/connections/open',discovery);app.router.add_get('/connect',websocket);app.router.add_post('/v1.0/oauth2/accessToken',token)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(work/'certificate.pem',work/'key.pem')
        ws_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ws_tls.load_cert_chain(ws_cert/'certificate.pem',ws_cert/'key.pem')
        def choose(sock,name,_context):
            if name=='wss-open-connection.dingtalk.com':sock.context=ws_tls
        tls.set_servername_callback(choose);await web.TCPSite(runner,'127.0.0.1',443,ssl_context=tls).start()
        async def start(mode,uid=65534,owner_bridge=False):
            state.update(mode=mode,connected=asyncio.Event());now=int(time.time()*1000)
            state['observation']={'nonce':__import__('secrets').token_hex(16),'since':now-1,'until':now+60000}
            args=([str(bridge)] if owner_bridge else ['-c','from haos.gateway_dingtalk_pairing_worker import main; main()'])
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s',*args,
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=uid,group=uid,extra_groups=[],cwd=str(code),env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HERMES_SAFE_MODE':'1'})
            children.append(child)
            payload=({'action':'account' if mode=='account' else 'observe','observation':state['observation']} if owner_bridge else
                {'connector':'dingtalk','credentials':value,
                'policy_sha256':__import__('haos.gateway',fromlist=['digest']).digest(json.loads((config/'gateways.json').read_text())),
                'parent_pid':os.getpid(),'observation':state['observation']})
            child.stdin.write(json.dumps(payload).encode())
            await child.stdin.drain();child.stdin.close();return child
        try:
            publish({**policy,'bindings':[]})
            child=await start('new-owner');out,err=await asyncio.wait_for(child.communicate(),50)
            assert child.returncode==0,(out,err)
            result=json.loads(out);assert result['observed'] is True and result['candidate']['authorized'] is False
            assert result['candidate']['sender']==policy['bindings'][0]['sender'] and not result['sender_grants_changed']
            assert 'sessionWebhook' not in out.decode() and value['client_secret'].encode() not in out+err
            with sqlite3.connect(base/'native-inbox.db') as db:assert db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
            cases.extend(['actual_gateway_UID_frozen_SDK_discovery_and_verified_TLS_WSS_observation',
                'native_ACK_after_FULL_candidate_metadata_commit_without_grant_or_native_input',
                'root_and_agent_secrets_absent_from_candidate_receipt'])
            child=await start('root-owner',0,owner_bridge=True);out,err=await asyncio.wait_for(child.communicate(),60)
            assert child.returncode==0,(out,err)
            report=json.loads(out);assert report['observed'] is True and not report['sender_grants_changed'] and not report['candidate']['authorized']
            assert json.loads((config/'gateways.json').read_text())['bindings']==[]
            cases.append('actual_root_owner_bridge_drops_UID_and_returns_only_retained_untrusted_candidate_without_modifying_grants')
            before=len(acks);child=await start('account',0,owner_bridge=True);out,err=await asyncio.wait_for(child.communicate(),45)
            assert child.returncode==0,(out,err)
            report=json.loads(out);assert report['app_authenticated'] is True and report['corp_identity_verified'] is False
            assert report['robot_identity_verified'] is False and report['message_sent'] is False and len(acks)==before
            cases.append('actual_root_owner_account_bridge_private_native_token_helper_no_message_or_corp_robot_verification_claim')
            for mode in ['wrong-nonce','wrong-corp']:
                before=len(acks);child=await start(mode);out,err=await asyncio.wait_for(child.communicate(),50)
                assert child.returncode!=0 and not out and len(acks)==before,(mode,out,err)
                cases.append(mode+'_receives_no_ACK_or_implicit_authorization')
            publish(policy);child=await start('existing-grant');out,err=await asyncio.wait_for(child.communicate(),50)
            assert child.returncode==0,(out,err)
            assert json.loads(out)['observed'] is True and acks.count('existing-grant')==2
            cases.append('already_approved_original_and_pending_native_input_retained_before_ACK_during_observation_without_agent_dispatch')
            for uid in [0,65533]:
                before=len(requests);child=await start('denied',uid);out,err=await asyncio.wait_for(child.communicate(),10)
                assert child.returncode!=0 and not out and len(requests)==before
                cases.append('UID_'+str(uid)+'_denied_before_network')
            child=await start('withdraw');await asyncio.wait_for(state['connected'].wait(),45)
            publish({**policy,'connectors':[],'bindings':[]});out,err=await asyncio.wait_for(child.communicate(),8)
            assert child.returncode!=0 and not out
            assert not failures,failures
            cases.append('fresh_root_withdrawal_terminates_and_joins_observation_and_private_socket')
            print(json.dumps({'cases':cases,'scope':'real kernel UID/NSS, isolated fixed-host TLS/WSS and actual SDK ACK; synthetic source frames only',
                'live_delivery_verified':False,'external_messages_sent':False,'service_control_and_system_audit_are_declared_fixtures':True}))
        finally:
            for child in children:
                if child.returncode is None:child.kill();await child.wait()
            for ws in connections:await ws.close()
            await runner.cleanup()
    import asyncio
    asyncio.run(exercise())


if __name__=='__main__':main()
