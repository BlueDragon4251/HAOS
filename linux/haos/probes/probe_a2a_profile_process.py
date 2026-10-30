"""Offline installed-code A2A UID/TLS/process-kill/controller socket contract.

The actual root Controller uses its existing policy callback with the prepared
A2A policy. Its real Unix client checks SO_PEERCRED; no model inference,
external peer or full public owner activation is claimed.
"""
import asyncio
import base64
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_A2A_PROFILE_PROCESS')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline A2A process namespace required')
    installer='/repo/linux/haos/runtime/install_package.py';code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,installer,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,installer,'/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_A2A_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':raise PermissionError('exact prepared public source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-a2a-public-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,installer,str(staged),str(code/'hermes-source')],check=True)
    sys.path.insert(0,str(code/'hermes-source'))
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    with Path('/etc/group').open('a') as stream:stream.write('haos-gateway:x:65534:\n')
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-a2a-process-'));work.chmod(0o755)
    sys.path[:0]=['/sdk',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_a2a import PreparedA2APolicy,scope
    create(work,'a2a.fixture.invalid')
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));media_port=reserved.getsockname()[1]
    with Path('/etc/hosts').open('a') as hostfile:hostfile.write('\n127.0.0.1 a2a.fixture.invalid\n')
    value={'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32,'unpaired':'private_fixture_unpaired_'+'z'*32},'port':port,'agent_name':'HAOS',
        'download_origins':{'alice':['https://localhost:'+str(media_port)]},
        'callbacks':{'alice':{'url':'https://a2a.fixture.invalid:'+str(media_port)+'/callback','secret':'private_fixture_signing_key_'+'s'*32}},
        'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(work/'certificate.pem').read_text(),
            'private_key':(work/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}}
    grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-process-device','scope':scope(value,'alice'),'thread':'',
        'identity':'personal','capabilities':['create','read','cancel','answer'],'generation':'a'*64,'since':1}
    media_grants=[{**grant,'id':'media-'+name,'chat':'ctx-media-'+name,'identity':'media-'+name,
        'capabilities':['create','read','cancel'] if name=='cancel' else ['create','read'],'allow_media':True,'allow_voice':True,'allow_video':True}
        for name in ['input','auth','rate','drop','revoke','cancel']]
    loop_grant={**grant,'id':'loop-check','chat':'ctx-loop-check','identity':'loop-check','capabilities':['create','read']}
    output_grant={**grant,'id':'output-check','chat':'ctx-output-check','identity':'output-check','capabilities':['create','read'],'allow_outbound_media':True,'allow_callback':True}
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[grant,*media_grants,loop_grant,output_grant]}
    etc=Path('/etc/haos');etc.mkdir(mode=0o755)
    def publish(data):
        PreparedA2APolicy(data);temp=etc/'next-policy';temp.write_text(json.dumps(data));temp.chmod(0o640);os.chown(temp,0,65534);temp.replace(etc/'gateways.json')
    publish(config)
    account=base/'account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    canary=work/'owner-secret';canary.write_text('root-only-disposable-owner-data');canary.chmod(0o600)
    script=work/'worker.py';script.write_text('''
import asyncio,json,os,sys
from pathlib import Path
from haos.gateway_a2a import PreparedA2APolicy
from haos.gateway_runtime import build_adapter,adapter_envelope,require_runtime_identity,call,delivery_metadata
from haos.gateway import digest
from haos.gateway_relay import RelayInbox
from haos.gateway_raw import NativeInbox
from haos.gateway_media_relay import MediaCache,event_media,forward
from haos.redaction import Redactor
assert os.getgroups()==[]
base=Path('/var/lib/haos-gateway')
if sys.argv[1]=='agent':
    assert os.geteuid()==65533
    for target in [base/'account.json',base/'relay.db',Path(sys.argv[2]),Path('/usr/lib/haos/haos/gateway_a2a_profile.py')]:
        try:
            if target.name=='gateway_a2a_profile.py':target.write_text('tampered')
            else:target.read_bytes()
        except PermissionError:pass
        else:raise AssertionError('agent accessed private data or changed installed code')
    try:build_adapter('a2a',{},a2a_context={'parent':base,'connector':'a2a','policy':lambda:None,'inbox':None})
    except PermissionError:pass
    else:raise AssertionError('agent constructed privileged A2A profile')
    async def refused_before_request():
        from haos.gateway_runtime import SOCKET
        reader,writer=await asyncio.wait_for(asyncio.open_unix_connection(SOCKET),5)
        try:
            # SO_PEERCRED is checked before reading a request. Read its exact
            # refusal first; writing an unread frame races the server close and
            # can replace the actual denial reply with a transport reset.
            line=await asyncio.wait_for(reader.readline(),5)
            assert json.loads(line)=={'ok':False,'error':'control peer is not authorized'}
        finally:writer.close();await writer.wait_closed()
    asyncio.run(refused_before_request())
    print(json.dumps({'agent_private_data_and_factory_denied':True}));sys.exit(0)
require_runtime_identity()
try:Path(sys.argv[2]).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read owner credential')
if sys.argv[1]=='production':
    from haos.gateway_runtime import serve
    asyncio.run(serve());sys.exit(0)
async def exercise():
    policy=lambda:PreparedA2APolicy(json.loads(Path('/etc/haos/gateways.json').read_text()))
    inbox=NativeInbox(base/'native.db',Redactor());relay=RelayInbox(base/'relay.db',Redactor());cache=MediaCache(inbox)
    parent=base/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
    value=json.loads((base/'account.json').read_text())
    adapter=None
    try:
        adapter=build_adapter('a2a',value,a2a_context={'parent':parent,'connector':'a2a','policy':policy,'inbox':inbox})
        def receive(event):
            assert event.raw_message is None
            media=event_media(event,'a2a')
            assert (event.message_type.value in {'photo','document','voice','video'}) if media else event.message_type.value=='text'
            relay.admit(policy(),'a2a',adapter_envelope(event,'a2a'),media=media);return True
        adapter.set_durable_message_handler(receive)
        assert await adapter.connect() and adapter.health()['status']=='listening'
        print(json.dumps({'ready':True,'uid':os.geteuid()}),flush=True)
        while True:
            line=await asyncio.to_thread(sys.stdin.readline)
            if not line:break
            command=json.loads(line)
            if command['method']=='health':result=adapter.health()
            elif command['method']=='counts':
                result={'relay':relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0],
                    'native_committed':inbox.db.execute("SELECT COUNT(*) FROM native_inbox WHERE state='committed'").fetchone()[0]}
            elif command['method']=='forward':
                item=relay.next(policy());assert item is not None
                result=await forward(policy,'a2a',item['envelope'],item['media'],cache,call)
                relay.admitted(item['id'],result['mission_id'])
                cache.transferred(item['media'])
            elif command['method']=='wrong-binding':
                item=relay.next(policy());assert item is not None
                try:await call('gateway.receive',{'connector':'a2a','envelope':item['envelope'],
                    'binding':{'binding_id':item['binding_id'],'binding_digest':'f'*64}})
                except PermissionError:result={'denied':True}
                else:raise AssertionError('controller admitted a changed owner grant epoch')
            elif command['method']=='late-cancelled-source':
                index=adapter._haos_a2a_indexes['alice'];row=index.entry(command['task_id'])
                proof=adapter._haos_a2a_originals.get(policy(),'a2a',value,'alice',row['raw_id'])
                try:await call('gateway.receive',{'connector':'a2a','envelope':proof['envelope'],
                    'binding':{'binding_id':row['binding_id'],'binding_digest':row['binding_digest']}})
                except PermissionError:result={'root_denied':True}
                else:raise AssertionError('root admitted a source after confirming its cancellation')
            elif command['method']=='cancel-receipt-fault':
                from haos.gateway_a2a_controls import Controls
                index=adapter._haos_a2a_indexes['alice']
                Controls(index,adapter._haos_a2a_originals,value,'a2a',policy)
                if command['enabled']:
                    index.db.execute("CREATE TRIGGER failed_cancel_receipt BEFORE UPDATE ON a2a_control_intents BEGIN SELECT RAISE(ABORT,'fixture cancellation receipt failure'); END")
                else:index.db.execute('DROP TRIGGER failed_cancel_receipt')
                result={'armed':command['enabled']}
            elif command['method']=='pump':
                count=0
                while (d:=await call('gateway.next',{'ready':['a2a']})) is not None:
                    metadata=delivery_metadata(d,'a2a')
                    output=await adapter._haos_a2a_output.prepare(d,call)
                    if output is not None:metadata['haos_output']=output
                    sent=await adapter.send(d['chat'],d['content'],reply_to=d['reply_to'],metadata=metadata)
                    assert sent.success and sent.raw_response['recipient_read_verified'] is False
                    await call('gateway.ack',{'id':d['id'],'result':{'attempt':d['attempt'],'status':'delivered','message_id':sent.message_id}})
                    count+=1
                result={'delivered':count}
            elif command['method']=='delivery':
                d=command['delivery'];sent=await adapter.send(d['chat'],d['content'],reply_to=d['reply_to'],metadata=command['metadata'])
                result={'success':sent.success,'message_id':sent.message_id,'raw_response':sent.raw_response}
            elif command['method']=='close':break
            else:raise AssertionError('unknown fixture command')
            print(json.dumps(result),flush=True)
    finally:
        if adapter is not None:await adapter.close_profile()
        relay.close();inbox.close()
asyncio.run(exercise())
''');script.chmod(0o644)
    environment={'PATH':os.environ['PATH'],'PYTHONPATH':'/usr/lib/haos:/usr/lib/haos/hermes-source:/sdk','HOME':'/nonexistent','HERMES_SAFE_MODE':'1'}
    def spawn(mode='gateway',uid=65534):
        return subprocess.Popen([sys.executable,str(script),mode,str(canary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,user=uid,group=65534,extra_groups=[],env={**environment,'CREDENTIALS_DIRECTORY':str(base/'installed-credentials')})
    async def line(process):
        text=await asyncio.wait_for(asyncio.to_thread(process.stdout.readline),30)
        if not text:
            raise AssertionError('worker exited: '+process.stderr.read())
        return json.loads(text)
    async def command(process,data):
        try:process.stdin.write(json.dumps(data)+'\n');process.stdin.flush()
        except BrokenPipeError:raise AssertionError('worker failed: '+process.stderr.read()) from None
        return await line(process)
    async def stop(process):
        if process.poll() is None:
            process.stdin.write(json.dumps({'method':'close'})+'\n');process.stdin.flush()
            await asyncio.wait_for(asyncio.to_thread(process.wait),10)
        stderr=process.stderr.read()
        assert process.returncode==0,stderr
        assert all(token not in stderr for token in [*value['peer_tokens'].values(),*[item['secret'] for item in value.get('callbacks',{}).values()]]) and value['tls']['private_key'] not in stderr
    cases=[]
    async def exercise():
        import httpx
        from haos.gateway import GatewayEngine,digest
        from haos.gateway_runtime import delivery_metadata
        from haos.store import MissionStore
        from haos.controller import Controller,MAX_FRAME
        from haos.gateway_runtime import SOCKET
        from haos.sandbox import trusted_json
        from plugins.platforms.a2a import protocol
        store=MissionStore(work/'root-missions.db');controller=Controller(store,'ws://127.0.0.1:1/fixture-not-inferred',{0})
        controller.gateway_uids={65534};controller.agent_uid=65533
        controller.gateway_policy=lambda:PreparedA2APolicy(trusted_json(etc/'gateways.json'))
        socket_path=Path(SOCKET);socket_path.parent.mkdir(mode=0o750);os.chown(socket_path.parent,0,65534)
        async def control_client(reader,writer):
            with redirect_stdout(sys.stderr):await controller.client(reader,writer,gateway=True)
        control_server=await asyncio.start_unix_server(control_client,path=SOCKET,limit=MAX_FRAME)
        socket_path.chmod(0o660);os.chown(socket_path,0,65534)
        process=spawn();pending=None
        client=httpx.AsyncClient(verify=ssl.create_default_context(cafile=str(work/'ca.pem')),trust_env=False,timeout=20)
        address='https://localhost:'+str(port)+'/a2a';headers={'Host':'a2a.fixture.invalid','Authorization':'Bearer '+value['peer_tokens']['alice']}
        request={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':{'messageId':'client-process-1','contextId':grant['chat'],
            'role':'ROLE_USER','parts':[{'text':'Actual dedicated-UID native A2A source.'}]}}}
        try:
            ready=await line(process);assert ready=={'ready':True,'uid':65534}
            async with asyncio.timeout(5):
                while not (base/'launcher/gateway_state.json').exists():await asyncio.sleep(.02)
            assert (base/'launcher/gateway_state.json').stat().st_uid==65534
            assert __import__('stat').S_IMODE((base/'launcher').stat().st_mode)==0o700
            cases.append('actual_installed_readonly_code_dedicated_gateway_UID_and_verified_TLS_listener')
            cases.append('actual_native_background_status_writer_uses_private_process_launcher_HOME_not_session_override_or_owner_HOME')
            alien=spawn('agent',65533);assert (await line(alien))['agent_private_data_and_factory_denied'] is True
            assert await asyncio.to_thread(alien.wait)==0
            cases.append('actual_other_UID_cannot_read_account_journals_owner_canary_or_modify_code_or_construct_A2A_profile')
            cases.append('actual_controller_Unix_socket_SO_PEERCRED_denies_foreign_UID_even_with_socket_group_access')
            denied=await client.post(address,headers={'Host':'a2a.fixture.invalid'},json=request)
            assert denied.status_code==401
            cases.append('actual_loopback_TCP_without_named_peer_token_has_no_A2A_rights')
            pending=asyncio.create_task(client.post(address,headers=headers,json=request))
            async with asyncio.timeout(10):
                while (await command(process,{'method':'counts'}))['relay']!=1:await asyncio.sleep(.03)
            assert await command(process,{'method':'counts'})=={'relay':1,'native_committed':1}
            assert not pending.done()
            with sqlite3.connect('file:'+str(base/'relay.db')+'?mode=ro',uri=True) as db:envelope=json.loads(db.execute('SELECT envelope FROM inbox').fetchone()[0])
            assert envelope['message_id']=='client-process-1' and envelope['scope']==grant['scope'] and envelope['sender']=='alice'
            source=next((base/'profiles').glob('a2a-*/peer-'+digest('alice')+'/tasks.db'))
            with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db:task=db.execute('SELECT task_id FROM a2a_tasks').fetchone()[0]
            assert task.startswith('task-') and task!=envelope['message_id']
            cases.append('actual_native_MessageEvent_preserves_wire_client_deduplication_identity_through_retained_parent_relay')
            assert (await command(process,{'method':'wrong-binding'}))['denied'] is True
            assert store.list()==[]
            cases.append('actual_root_controller_checks_expected_owner_grant_epoch_before_mission_admission')
            result=await command(process,{'method':'forward'});mid=result['mission_id']
            assert (await command(process,{'method':'pump'}))['delivered']==1
            assert not pending.done()
            cases.append('actual_gateway_UID_controller_Unix_admission_and_queue_receipt_do_not_complete_waiting_native_JSON_RPC')
            # The lease is kernel flock, not a fixture boolean.
            competing=spawn();assert await asyncio.to_thread(competing.wait)!=0
            assert 'private A2A profile lease unavailable or already in use' in competing.stderr.read()
            cases.append('actual_concurrent_gateway_process_cannot_reuse_private_profile_lease')
            process.kill();await asyncio.to_thread(process.wait)
            try:await pending
            except httpx.TransportError:pass
            else:raise AssertionError('killed native listener claimed completed RPC')
            process=spawn();assert (await line(process))['ready'] is True
            got=await client.post(address,headers=headers,json={'jsonrpc':'2.0','id':2,'method':'GetTask','params':{'id':task}})
            assert got.status_code==200 and got.json()['result']['status']['state']==protocol.STATE_WORKING,got.text
            replay={**request,'id':3};recovered=await client.post(address,headers=headers,json=replay)
            assert recovered.json()['result']['task']['id']==task
            assert await command(process,{'method':'counts'})=={'relay':1,'native_committed':1}
            assert len(store.list())==1
            cases.append('actual_SIGKILL_reopen_restores_working_native_task_and_replay_does_not_repeat_relay_or_root_mission')
            store.claim();store.settle(mid,'completed',result='Complete result after real process restart. '*150)
            assert (await command(process,{'method':'pump'}))['delivered']>2
            got=await client.post(address,headers=headers,json={'jsonrpc':'2.0','id':4,'method':'GetTask','params':{'id':task}})
            native=got.json()['result'];assert native['status']['state']==protocol.STATE_COMPLETED
            assert native['artifacts'][0]['parts'][0]['text']=='Mission '+mid+': completed\n'+'Complete result after real process restart. '*150
            cases.append('actual_UID_restart_then_complete_multichunk_root_output_commits_exact_native_task_available_over_verified_TLS')
            second=json.loads(json.dumps(request));second['id']=6;second['params']['message']['messageId']='client-process-2'
            pending=asyncio.create_task(client.post(address,headers=headers,json=second))
            async with asyncio.timeout(10):
                while (await command(process,{'method':'counts'}))['relay']!=2:await asyncio.sleep(.02)
            second_mid=(await command(process,{'method':'forward'}))['mission_id']
            assert (await command(process,{'method':'pump'}))['delivered']==1
            store.claim()
            with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db:
                second_task=db.execute('SELECT task_id FROM a2a_tasks WHERE task_id!=?',(task,)).fetchone()[0]
            assert (await command(process,{'method':'cancel-receipt-fault','enabled':True}))['armed'] is True
            cancel_request={'jsonrpc':'2.0','id':7,'method':'CancelTask','params':{'id':second_task}}
            refused=await client.post(address,headers=headers,json=cancel_request)
            assert refused.status_code==503 or 'error' in refused.json()
            assert store.get(second_mid)['cancel_requested']==1 and store.get(second_mid)['state']=='running'
            assert not pending.done()
            assert (await command(process,{'method':'cancel-receipt-fault','enabled':False}))['armed'] is False
            cancelled=await client.post(address,headers=headers,json={**cancel_request,'id':8})
            assert cancelled.status_code==200 and cancelled.json()['result']['status']['state']==protocol.STATE_WORKING,cancelled.text
            assert cancelled.json()['result']['metadata']=={'haosCancelRequested':True}
            assert not pending.done() and store.get(second_mid)['state']=='running'
            again=await client.post(address,headers=headers,json={**cancel_request,'id':9})
            assert again.json()['result']['metadata']=={'haosCancelRequested':True}
            assert len([e for e in store.events(second_mid) if e['kind']=='mission.cancel-requested'])==1
            cases.append('actual_native_CancelTask_uses_root_controller_and_lost_receipt_replay_does_not_repeat_cancellation_or_invent_terminal_task')
            store.settle(second_mid,'cancelled')
            assert (await command(process,{'method':'pump'}))['delivered']>=2
            terminal=(await pending).json()['result']['task']
            assert terminal['id']==second_task and terminal['status']['state']==protocol.STATE_CANCELED
            cases.append('actual_controller_terminal_cancellation_event_alone_completes_native_Future_and_JSON_RPC_as_cancelled')
            # Real WebSocket JSON-RPC peer for the actual HermesConnection /
            # Controller.question/respond path; no inference is substituted.
            import websockets
            from haos.hermes import HermesConnection
            responses=[];peer_ready=asyncio.Event();question_frame=[None];backend_socket=[None]
            async def backend(socket):
                backend_socket[0]=socket;peer_ready.set()
                async for text in socket:
                    frame=json.loads(text);responses.append(frame)
            backend_server=await websockets.serve(backend,'127.0.0.1',0)
            backend_port=backend_server.sockets[0].getsockname()[1]
            backend_client=await websockets.connect('ws://127.0.0.1:'+str(backend_port))
            await peer_ready.wait()
            controller.connection=HermesConnection(backend_client,controller.event,controller.question)
            try:
                third=json.loads(json.dumps(request));third['id']=10;third['params']['message']['messageId']='client-process-3'
                pending=asyncio.create_task(client.post(address,headers=headers,json=third))
                async with asyncio.timeout(10):
                    while (await command(process,{'method':'counts'}))['relay']!=3:await asyncio.sleep(.02)
                third_mid=(await command(process,{'method':'forward'}))['mission_id']
                assert (await command(process,{'method':'pump'}))['delivered']==1
                store.claim();controller.current=third_mid
                session=store.get(third_mid)['session_id']
                await backend_socket[0].send(json.dumps({'jsonrpc':'2.0','id':17,'method':'clarify','params':{
                    'session_id':session,'question':'Choose the exact option.','private':'never export this tool parameter'}}))
                async with asyncio.timeout(5):
                    while store.get(third_mid)['state']!='waiting':await asyncio.sleep(.01)
                assert (await command(process,{'method':'pump'}))['delivered']>=2
                question=(await pending).json()['result']['task'];third_task=question['id']
                assert question['status']['state']==protocol.STATE_INPUT_REQUIRED
                assert 'never export' not in json.dumps(question)
                cases.append('actual_Hermes_WebSocket_request_Controller_question_and_native_input_required_export_only_question_identity')
                continuation=json.loads(json.dumps(third));continuation['id']=11
                offered=question['metadata']['haosQuestion']
                assert offered['requestId']=='17' and offered['method']=='clarify' and len(offered['epoch'])==64
                continuation['params']['message'].update({'messageId':'client-process-3-answer','taskId':third_task,
                    'metadata':{'haosQuestionEpoch':offered['epoch']},'parts':[{'text':'Approved option A.'}]})
                pending=asyncio.create_task(client.post(address,headers=headers,json=continuation))
                async with asyncio.timeout(10):
                    while (await command(process,{'method':'counts'}))['relay']!=4:await asyncio.sleep(.02)
                assert (await command(process,{'method':'forward'}))['mission_id']==third_mid
                async with asyncio.timeout(5):
                    while len(responses)!=1:await asyncio.sleep(.01)
                assert responses==[{'jsonrpc':'2.0','id':17,'result':{'answer':'Approved option A.'}}]
                assert len(store.list())==3 and store.get(third_mid)['state']=='running'
                try:again=await client.post(address,headers=headers,json={**continuation,'id':12})
                except httpx.TransportError as error:
                    raise AssertionError('native continuation HTTP transport: '+json.dumps(await command(process,{'method':'health'}))) from error
                assert again.json()['result']['task']['id']==third_task and len(responses)==1
                assert await command(process,{'method':'counts'})=={'relay':4,'native_committed':4}
                cases.append('actual_native_taskId_continuation_answers_exact_numeric_Hermes_question_through_root_without_new_task_mission_or_replayed_answer')
                await backend_socket[0].send(json.dumps({'jsonrpc':'2.0','id':18,'method':'approval','params':{
                    'session_id':session,'choices':['once','deny'],'private':'never export approval tool arguments'}}))
                async with asyncio.timeout(5):
                    while store.get(third_mid)['state']!='waiting':await asyncio.sleep(.01)
                assert (await command(process,{'method':'pump'}))['delivered']>=2
                approval=(await pending).json()['result']['task']
                assert approval['id']==third_task and approval['status']['state']==protocol.STATE_INPUT_REQUIRED
                next_question=approval['metadata']['haosQuestion']
                assert next_question['requestId']=='18' and next_question['method']=='approval' and next_question['epoch']!=offered['epoch']
                assert 'never export' not in json.dumps(approval)
                for msg_id,epoch,body in [('stale-question-answer',offered['epoch'],'once'),('permanent-approval-answer',next_question['epoch'],'always')]:
                    bad=json.loads(json.dumps(continuation));bad['params']['message'].update({'messageId':msg_id,
                        'metadata':{'haosQuestionEpoch':epoch},'parts':[{'text':body}]})
                    rejected=await client.post(address,headers=headers,json=bad)
                    assert rejected.status_code==403 and 'error' in rejected.json()
                    assert len(responses)==1 and await command(process,{'method':'counts'})=={'relay':4,'native_committed':4}
                cases.append('new_wire_message_ID_cannot_reuse_old_question_epoch_or_request_permanent_approval_before_parent_dispatch')
                approved=json.loads(json.dumps(continuation));approved['id']=13;approved['method']='SendStreamingMessage'
                approved['params']['message'].update({'messageId':'client-process-3-approval',
                    'metadata':{'haosQuestionEpoch':next_question['epoch']},'parts':[{'text':'once'}]})
                async with client.stream('POST',address,headers=headers,json=approved) as streaming:
                    assert streaming.status_code==200 and streaming.headers['content-type'].startswith('text/event-stream')
                    lines=streaming.aiter_lines();early=[]
                    while len(early)<2:
                        text=await anext(lines)
                        if text.startswith('data:'):early.append(json.loads(text[5:]))
                    assert early[0]['result']['task']['id']==third_task and early[0]['result']['task']['status']['state']==protocol.STATE_WORKING
                    assert early[1]['result']['statusUpdate']['status']['state']==protocol.STATE_WORKING
                    async with asyncio.timeout(10):
                        while (await command(process,{'method':'counts'}))['relay']!=5:await asyncio.sleep(.02)
                    assert (await command(process,{'method':'forward'}))['mission_id']==third_mid
                    async with asyncio.timeout(5):
                        while len(responses)!=2:await asyncio.sleep(.01)
                    assert responses[1]=={'jsonrpc':'2.0','id':18,'result':{'choice':'once'}}
                    assert store.get(third_mid)['state']=='running' and len(store.list())==3
                    cases.append('actual_native_continuation_SSE_keeps_original_task_ID_and_once_approval_reaches_exact_numeric_Hermes_request')
                    store.settle(third_mid,'completed',result='Final result after explicit clarification and once approval.')
                    assert (await command(process,{'method':'pump'}))['delivered']>=2
                    remaining=[]
                    async for text in lines:
                        if text.startswith('data:'):remaining.append(json.loads(text[5:]))
                    assert remaining[-1]['result']['statusUpdate']['taskId']==third_task
                    assert remaining[-1]['result']['statusUpdate']['status']['state']==protocol.STATE_COMPLETED
                    artifact=next(item['result']['artifactUpdate']['artifact'] for item in remaining if 'artifactUpdate' in item.get('result',{}))
                    assert artifact['parts'][0]['text']=='Mission '+third_mid+': completed\nFinal result after explicit clarification and once approval.'
                    cases.append('actual_clarification_and_approval_same_native_task_Future_and_SSE_receive_final_controller_result_without_new_mission')
                fourth=json.loads(json.dumps(request));fourth['id']=14;fourth['params']['message']['messageId']='client-process-4'
                pending=asyncio.create_task(client.post(address,headers=headers,json=fourth))
                async with asyncio.timeout(10):
                    while (await command(process,{'method':'counts'}))['relay']!=6:await asyncio.sleep(.02)
                fourth_mid=(await command(process,{'method':'forward'}))['mission_id']
                assert (await command(process,{'method':'pump'}))['delivered']==1
                store.claim();controller.current=fourth_mid
                await backend_socket[0].send(json.dumps({'jsonrpc':'2.0','id':19,'method':'clarify','params':{
                    'session_id':store.get(fourth_mid)['session_id'],'question':'Owner must inspect if this connection is lost.'}}))
                async with asyncio.timeout(5):
                    while store.get(fourth_mid)['state']!='waiting':await asyncio.sleep(.01)
                assert (await command(process,{'method':'pump'}))['delivered']>=2
                lost_question=(await pending).json()['result']['task']
                await backend_socket[0].close()
                failed_answer=json.loads(json.dumps(fourth));failed_answer['id']=15
                failed_answer['params']['message'].update({'messageId':'client-process-4-answer','taskId':lost_question['id'],
                    'metadata':{'haosQuestionEpoch':lost_question['metadata']['haosQuestion']['epoch']},'parts':[{'text':'Explicit answer before peer transport loss is known.'}]})
                pending=asyncio.create_task(client.post(address,headers=headers,json=failed_answer))
                async with asyncio.timeout(10):
                    while (await command(process,{'method':'counts'}))['relay']!=7:await asyncio.sleep(.02)
                assert (await command(process,{'method':'forward'}))['mission_id']==fourth_mid
                assert (await command(process,{'method':'pump'}))['delivered']>=2
                unconfirmed=(await pending).json()['result']['task']
                assert unconfirmed['id']==lost_question['id'] and unconfirmed['status']['state']==protocol.STATE_INPUT_REQUIRED
                assert unconfirmed['metadata']=={'haosQuestionUnavailable':True,'haosAction':'inspect-owner-console'}
                assert 'unconfirmed' in unconfirmed['status']['message']['parts'][0]['text'].lower()
                replay=await client.post(address,headers=headers,json={**failed_answer,'id':16})
                assert replay.json()['result']['task']['metadata']==unconfirmed['metadata']
                fresh=json.loads(json.dumps(failed_answer));fresh['id']=17;fresh['params']['message']['messageId']='do-not-repeat-uncertain-answer'
                refused=await client.post(address,headers=headers,json=fresh)
                assert refused.status_code==403
                assert len([e for e in store.events(fourth_mid) if e['kind']=='gateway.answer-dispatching'])==1
                assert len([e for e in store.events(fourth_mid) if e['kind']=='gateway.answer-unconfirmed'])==1
                assert len(responses)==2 and len(store.list())==4
                cases.append('actual_closed_Hermes_WebSocket_preserves_unconfirmed_answer_with_owner_action_and_no_automatic_or_new_ID_resend')
            finally:
                await controller.connection.close();controller.connection=None;controller.current=None
                backend_server.close();await backend_server.wait_closed()
            await controller.dispatch('uid:0',{'method':'missions.cancel','params':{'id':fourth_mid}})
            store.unavailable(fourth_mid,'actual closed fixture question connection before any dispatched prompt')
            assert store.get(fourth_mid)['state']=='cancelled'
            await command(process,{'method':'pump'})
            from aiohttp import web
            from video_fixture import movie
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5tUAAAAASUVORK5CYII=')
            flac=Path('/public-input/reference.flac').read_bytes()
            assert __import__('hashlib').sha256(flac).hexdigest()=='63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
            video=movie(width=64,height=32);document=b'Exact private A2A document fixture.'
            fetched=[];released=asyncio.Event();started=asyncio.Event();stalled=asyncio.Event();stall_closed=asyncio.Event();release_stall=asyncio.Event();mode={'status':200}
            cancel_started=asyncio.Event();cancel_closed=asyncio.Event();cancel_release=asyncio.Event()
            notifications=[]
            async def notification(web_request):
                import hmac,hashlib
                body=await web_request.read();payload=json.loads(body)
                signature=hmac.new(value['callbacks']['alice']['secret'].encode(),json.dumps(payload,sort_keys=True,ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
                assert web_request.secure and hmac.compare_digest(web_request.headers['X-A2A-Signature'],signature)
                assert 'Authorization' not in web_request.headers and 'Cookie' not in web_request.headers
                assert all(token.encode() not in body for token in [*value['peer_tokens'].values(),value['callbacks']['alice']['secret']])
                notifications.append((payload,web_request.headers['X-A2A-Delivery-ID']));return web.Response(status=204)
            async def attachment(web_request):
                assert web_request.secure and 'Authorization' not in web_request.headers and 'Cookie' not in web_request.headers
                assert all(token not in str(web_request.headers) for token in value['peer_tokens'].values())
                fetched.append(web_request.path)
                if web_request.path in {'/stall','/cancel'}:
                    response=web.StreamResponse(headers={'Content-Type':'application/octet-stream','Content-Length':'1024'})
                    beginning,closed,released_now=((stalled,stall_closed,release_stall) if web_request.path=='/stall' else (cancel_started,cancel_closed,cancel_release))
                    await response.prepare(web_request);beginning.set()
                    while not released_now.is_set():
                        if web_request.transport is None or web_request.transport.is_closing():closed.set();break
                        await asyncio.sleep(.02)
                    return response
                if web_request.path=='/image.png':
                    assert dict(web_request.query)=={'signed':'private-fixture-attachment-capability'}
                    response=web.StreamResponse(status=200,headers={'Content-Type':'image/png','Content-Length':str(len(png))})
                    await response.prepare(web_request);started.set();await released.wait();await response.write(png);await response.write_eof();return response
                if web_request.path=='/voice.flac':return web.Response(body=flac,content_type='audio/flac')
                return web.Response(status=mode['status'],body=b'fixture resource refusal')
            media_app=web.Application();media_app.router.add_get('/{name}',attachment);media_app.router.add_post('/callback',notification)
            media_runner=web.AppRunner(media_app,access_log=None);await media_runner.setup()
            media_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);media_tls.load_cert_chain(work/'certificate.pem',work/'key.pem')
            await web.TCPSite(media_runner,'127.0.0.1',media_port,ssl_context=media_tls).start()
            try:
                image_url='https://localhost:'+str(media_port)+'/image.png?signed=private-fixture-attachment-capability'
                media_request={'jsonrpc':'2.0','id':20,'method':'SendStreamingMessage','params':{'message':{
                    'messageId':'actual-four-media-source','contextId':'ctx-media-input','role':'ROLE_USER','parts':[
                        {'text':'Inspect the four explicitly granted original attachments.'},
                        {'url':image_url,'filename':'image.png','mediaType':'image/png'},
                        {'raw':base64.b64encode(document).decode(),'filename':'document.txt','mediaType':'text/plain'},
                        {'url':'https://localhost:'+str(media_port)+'/voice.flac','filename':'reference.flac','mediaType':'audio/flac'},
                        {'raw':base64.b64encode(video).decode(),'filename':'clip.mp4','mediaType':'video/mp4'}]}}}
                assert len(json.dumps(media_request).encode())<1024*1024
                denied=json.loads(json.dumps(media_request));denied['params']['message']['contextId']=grant['chat']
                denied['params']['message']['messageId']='no-separate-media-consent'
                refused=await client.post(address,headers=headers,json=denied)
                assert refused.status_code==200 and refused.json()['error']['message']=='independent-media-consent-required',refused.text
                assert fetched==[] and len(store.list())==4
                cases.append('actual_A2A_media_create_token_without_separate_kind_flags_cannot_fetch_or_admit_files')
                async with client.stream('POST',address,headers=headers,json=media_request) as streaming:
                    assert streaming.status_code==200
                    lines=streaming.aiter_lines();early=[]
                    while len(early)<2:
                        text=await anext(lines)
                        if text.startswith('data:'):early.append(json.loads(text[5:]))
                    media_task=early[0]['result']['task']['id']
                    assert early[1]['result']['statusUpdate']['status']['state']==protocol.STATE_WORKING
                    await asyncio.wait_for(started.wait(),5)
                    assert (await command(process,{'method':'counts'}))['relay']==7 and len(store.list())==4
                    released.set()
                    async with asyncio.timeout(10):
                        while (await command(process,{'method':'counts'}))['relay']!=8:await asyncio.sleep(.02)
                    media_mid=(await command(process,{'method':'forward'}))['mission_id']
                    items=controller.gateway.media.for_mission(PreparedA2APolicy(config),media_mid)
                    assert [item['descriptor']['kind'] for item in items]==['image','document','voice','video']
                    assert [item['data'] for item in items]==[png,document,flac,video]
                    assert 'private-fixture-attachment-capability' not in store.get(media_mid)['goal'] and image_url not in store.get(media_mid)['goal']
                    assert await command(process,{'method':'counts'})=={'relay':8,'native_committed':8}
                    cases.append('actual_native_A2A_early_SSE_precedes_complete_verified_TLS_file_read_then_four_exact_bytes_cross_real_media_and_controller_Unix_gates')
                    cases.append('actual_A2A_URI_capability_stays_private_and_agent_goal_has_only_native_opaque_file_carriers')
                again=await client.post(address,headers=headers,json={**media_request,'id':21,'method':'SendMessage'})
                assert again.json()['result']['task']['id']==media_task and fetched==['/image.png','/voice.flac']
                assert len(store.list())==5 and await command(process,{'method':'counts'})=={'relay':8,'native_committed':8}
                cases.append('actual_A2A_transferred_media_replay_never_refetches_URI_or_creates_second_input_or_mission')
                await controller.dispatch('uid:0',{'method':'missions.cancel','params':{'id':media_mid}})
                await command(process,{'method':'pump'})
                early_cancel={'jsonrpc':'2.0','id':40,'method':'SendStreamingMessage','params':{'message':{'messageId':'source-cancel-during-download',
                    'contextId':'ctx-media-cancel','role':'ROLE_USER','parts':[{'url':'https://localhost:'+str(media_port)+'/cancel',
                    'filename':'waiting.bin','mediaType':'application/octet-stream'}]}}}
                async with client.stream('POST',address,headers=headers,json=early_cancel) as stream:
                    frames=stream.aiter_lines();early=[]
                    while len(early)<2:
                        frame=await anext(frames)
                        if frame.startswith('data:'):early.append(json.loads(frame[5:]))
                    cancel_task=early[0]['result']['task']['id'];await asyncio.wait_for(cancel_started.wait(),5)
                    cancelled=await client.post(address,headers=headers,json={'jsonrpc':'2.0','id':41,'method':'CancelTask','params':{'id':cancel_task}})
                    assert cancelled.status_code==200 and cancelled.json()['result']['status']['state']==protocol.STATE_CANCELED,cancelled.text
                    await asyncio.wait_for(cancel_closed.wait(),3)
                    endings=[]
                    async for frame in frames:
                        if frame.startswith('data:'):endings.append(json.loads(frame[5:]))
                    assert endings[-1]['result']['statusUpdate']['status']['state']==protocol.STATE_CANCELED
                assert len(store.list())==5 and await command(process,{'method':'counts'})=={'relay':8,'native_committed':8}
                assert store.db.execute("SELECT COUNT(*) FROM gateway_source_cancellations WHERE mission_id=''").fetchone()[0]==1
                cases.append('actual_native_CancelTask_during_stalled_TLS_download_commits_root_absence_tombstone_then_closes_reader_and_native_Future_without_creating_mission')
                assert await command(process,{'method':'late-cancelled-source','task_id':cancel_task})=={'root_denied':True}
                assert len(store.list())==5
                cases.append('actual_gateway_UID_controller_Unix_request_cannot_admit_original_source_after_root_confirmed_prevention')
                before_cancel_fetches=list(fetched);await stop(process);process=spawn();assert (await line(process))['ready'] is True
                replay=await client.post(address,headers=headers,json={**early_cancel,'id':42,'method':'SendMessage'})
                assert replay.json()['result']['task']['status']['state']==protocol.STATE_CANCELED
                assert fetched==before_cancel_fetches and len(store.list())==5
                cases.append('actual_UID_profile_restart_retains_pre_admission_cancelled_native_source_and_never_refetches_or_replays_it_into_root_mission')
                file_bytes=b'row,value\n'+b'1,reviewed bounded artifact bytes\n'*10000;file_reads=[]
                artifact_token='private-fixture-hermes-file-capability'
                store.redactor=__import__('haos.redaction',fromlist=['Redactor']).Redactor([artifact_token,*value['peer_tokens'].values()])
                async def artifact_read(request):
                    assert request.headers.get('Authorization')=='Bearer '+artifact_token
                    assert dict(request.query)=={'session_id':'stored-output-session','path':'./result.csv'}
                    file_reads.append(dict(request.query))
                    return web.json_response({'dataUrl':'data:text/csv;base64,'+base64.b64encode(file_bytes).decode()})
                artifact_app=web.Application();artifact_app.router.add_get('/api/fs/read-data-url',artifact_read)
                artifact_runner=web.AppRunner(artifact_app,access_log=None);await artifact_runner.setup()
                artifact_site=web.TCPSite(artifact_runner,'127.0.0.1',0);await artifact_site.start()
                artifact_port=artifact_site._server.sockets[0].getsockname()[1]
                controller.url='ws://127.0.0.1:'+str(artifact_port)+'/api/ws?token='+artifact_token
                try:
                    output_request={'jsonrpc':'2.0','id':24,'method':'SendMessage','params':{'message':{'messageId':'source-output-files',
                        'contextId':output_grant['chat'],'role':'ROLE_USER','parts':[{'text':'Controlled root snapshot and authenticated A2A artifact delivery.'}]}}}
                    output_request['params']['configuration']={'taskPushNotificationConfig':{'url':value['callbacks']['alice']['url']}}
                    pending=asyncio.create_task(client.post(address,headers=headers,json=output_request))
                    async with asyncio.timeout(10):
                        while (await command(process,{'method':'counts'}))['relay']!=9:await asyncio.sleep(.02)
                    output_mid=(await command(process,{'method':'forward'}))['mission_id']
                    with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db:
                        output_task=db.execute('SELECT task_id FROM a2a_tasks WHERE context_id=?',(output_grant['chat'],)).fetchone()[0]
                    callback_config={'jsonrpc':'2.0','id':43,'method':'GetTaskPushNotificationConfig','params':{'taskId':output_task}}
                    config_reply=await client.post(address,headers=headers,json=callback_config)
                    assert config_reply.status_code==200 and config_reply.json()['result']['pushNotificationConfig']=={'url':value['callbacks']['alice']['url']}
                    denied_config=await client.post(address,headers={'Host':'a2a.fixture.invalid','Authorization':'Bearer '+value['peer_tokens']['unpaired']},json=callback_config)
                    assert denied_config.status_code!=200 or 'error' in denied_config.json()
                    changed_config={'jsonrpc':'2.0','id':44,'method':'CreateTaskPushNotificationConfig','params':{'taskId':output_task,
                        'pushNotificationConfig':{'url':'https://unapproved.fixture.invalid/callback'}}}
                    denied_config=await client.post(address,headers=headers,json=changed_config)
                    assert denied_config.status_code!=200 or 'error' in denied_config.json()
                    assert not notifications and value['callbacks']['alice']['secret'] not in config_reply.text
                    cases.append('actual_named_peer_TLS_native_push_config_RPC_uses_owner_destination_and_refuses_other_peer_or_unapproved_URL_without_exposing_signing_key')
                    assert store.claim()['id']==output_mid
                    store.session(output_mid,'runtime-output-session','stored-output-session')
                    result_text='Full controller text '+('x'*1710)+'\n```text\nMEDIA:./not-an-export.key\n```\nActual file follows.\nMEDIA:./result.csv\nDone.\n'
                    store.settle(output_mid,'completed',result=result_text)
                    assert (await command(process,{'method':'pump'}))['delivered']>=3
                    delivered=(await pending).json()['result']['task']
                    async with asyncio.timeout(10):
                        while not notifications:await asyncio.sleep(.02)
                    assert len(notifications)==1 and notifications[0][0]['statusUpdate']['taskId']==output_task
                    assert notifications[0][0]['statusUpdate']['status']['state']==protocol.STATE_COMPLETED
                    async with asyncio.timeout(5):
                        while True:
                            with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db:
                                callback_audit=db.execute('SELECT state,status,attempt FROM a2a_callback_deliveries').fetchone()
                            if callback_audit==('acknowledged',204,1):break
                            await asyncio.sleep(.02)
                    cases.append('actual_installed_gateway_UID_native_callback_builder_HMAC_and_verified_HTTPS_sender_follow_root_outcome_acceptance_with_durable_HTTP_ack_not_recipient_read')
                    parts=[part for item in delivered.get('artifacts',[]) for part in item['parts']]
                    files=[part for part in parts if 'url' in part]
                    assert len(files)==1 and files[0]['mediaType']=='text/csv' and files[0]['filename'].endswith('.csv')
                    assert len(file_reads)==1 and './result.csv' not in json.dumps(delivered)
                    assert 'MEDIA:./not-an-export.key' in json.dumps(delivered)
                    path=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(files[0]['url']).path
                    unauthenticated=await client.get(address.removesuffix('/a2a')+path,headers={'Host':'a2a.fixture.invalid'})
                    assert unauthenticated.status_code==401
                    other=await client.get(address.removesuffix('/a2a')+path,headers={'Host':'a2a.fixture.invalid','Authorization':'Bearer '+value['peer_tokens']['unpaired']})
                    assert other.status_code==404
                    download=await client.get(address.removesuffix('/a2a')+path,headers=headers)
                    assert download.status_code==200 and download.content==file_bytes
                    assert download.headers['content-type']=='text/csv' and download.headers['x-content-type-options']=='nosniff'
                    assert download.headers['cache-control']=='no-store' and 'attachment;' in download.headers['content-disposition']
                    assert artifact_token not in json.dumps(delivered) and len(file_reads)==1
                    async with client.stream('POST',address,headers=headers,json={**output_request,'id':26,'method':'SendStreamingMessage'}) as replay:
                        replayed=[]
                        async for frame in replay.aiter_lines():
                            if frame.startswith('data:'):replayed.append(json.loads(frame[5:]))
                        repeated_parts=[part for item in replayed[0]['result']['task']['artifacts'] for part in item['parts'] if 'url' in part]
                        assert repeated_parts==files and len(file_reads)==1
                    cases.append('actual_completed_task_SSE_replay_preserves_native_file_Parts_without_second_agent_file_read')
                    cases.append('actual_root_export_manifest_preserves_cross_chunk_code_examples_and_only_explicit_real_file_uses_bounded_authenticated_agent_HTTP_reader')
                    cases.append('actual_native_Task_file_Parts_and_TLS_artifact_endpoint_deliver_exact_snapshot_only_to_current_named_peer_without_paths_or_credentials')
                    audit_db=source
                    with sqlite3.connect('file:'+str(audit_db)+'?mode=ro',uri=True) as db:
                        logged=db.execute("SELECT state,written,size FROM a2a_artifact_reads WHERE state='stream-written'").fetchall()
                        assert logged==[('stream-written',len(file_bytes),len(file_bytes))]
                    cases.append('actual_artifact_download_has_durable_local_write_audit_without_claiming_remote_recipient_read')
                    no_output=json.loads(json.dumps(output_request));no_output['id']=25
                    no_output['params'].pop('configuration')
                    no_output['params']['message'].update({'messageId':'source-without-file-grant','contextId':grant['chat']})
                    pending=asyncio.create_task(client.post(address,headers=headers,json=no_output))
                    async with asyncio.timeout(10):
                        while (await command(process,{'method':'counts'}))['relay']!=10:await asyncio.sleep(.02)
                    without_mid=(await command(process,{'method':'forward'}))['mission_id']
                    assert store.claim()['id']==without_mid;store.session(without_mid,'runtime-without-files','stored-without-files')
                    long_text='Text result remains public. ä '*3000
                    store.settle(without_mid,'completed',result=long_text+'\nMEDIA:./result.csv')
                    await command(process,{'method':'pump'});without=(await pending).json()['result']['task']
                    assert without['status']['state']==protocol.STATE_COMPLETED and 'UTF-8 text' in json.dumps(without)
                    text_files=[part for item in without.get('artifacts',[]) for part in item['parts'] if 'url' in part]
                    assert './result.csv' not in json.dumps(without) and len(text_files)==1 and text_files[0]['mediaType']=='text/plain'
                    text_path=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(text_files[0]['url']).path
                    text_download=await client.get(address.removesuffix('/a2a')+text_path,headers=headers)
                    assert text_download.status_code==200
                    assert text_download.content==('Mission '+without_mid+': completed\n'+long_text+'\n\n[Result files require separate owner approval.]\n').encode()
                    assert len(file_reads)==1
                    cases.append('actual_TLS_long_UTF8_text_artifact_preserves_every_byte_with_read_only_grant_without_agent_file_export_or_native_response_overflow')
                    cases.append('separate_outbound_file_grant_is_required_before_any_root_snapshot_read_or_native_artifact_URL')
                finally:await artifact_runner.cleanup()
                # Five actual accepted native turns followed by its real sixth-
                # turn anti-loop rejection. The private recovery loop must not
                # turn that rejected native source into a fresh root mission.
                for index in range(5):
                    loop_request={'jsonrpc':'2.0','id':30+index,'method':'SendMessage','params':{'message':{
                        'messageId':'loop-source-'+str(index),'contextId':loop_grant['chat'],'role':'ROLE_USER','parts':[{'text':'Controlled local loop contract '+str(index)}]}}}
                    pending=asyncio.create_task(client.post(address,headers=headers,json=loop_request))
                    async with asyncio.timeout(10):
                        while (await command(process,{'method':'counts'}))['relay']!=11+index:await asyncio.sleep(.02)
                    loop_mid=(await command(process,{'method':'forward'}))['mission_id']
                    # The fixture root is the configured owner (allowed UID 0).
                    # Cancel queued test goals through the real owner dispatch;
                    # do not bypass the active question's agent-home lock.
                    await controller.dispatch('uid:0',{'method':'missions.cancel','params':{'id':loop_mid}})
                    assert store.get(loop_mid)['state']=='cancelled'
                    await command(process,{'method':'pump'})
                    assert (await pending).json()['result']['task']['status']['state']==protocol.STATE_CANCELED
                refused_loop=json.loads(json.dumps(loop_request));refused_loop['id']=35
                refused_loop['params']['message']['messageId']='sixth-loop-source'
                rejected=(await client.post(address,headers=headers,json=refused_loop)).json()['result']['task']
                assert rejected['status']['state']==protocol.STATE_REJECTED
                await asyncio.sleep(.3)
                assert len(store.list())==12 and await command(process,{'method':'counts'})=={'relay':15,'native_committed':15}
                cases.append('actual_native_sixth_turn_anti_loop_rejection_is_never_replayed_by_private_pending_input_recovery_into_a_root_mission')
                for name,status in [('auth',401),('rate',429)]:
                    mode['status']=status
                    failed={'jsonrpc':'2.0','id':22,'method':'SendStreamingMessage','params':{'message':{'messageId':'media-'+name,
                        'contextId':'ctx-media-'+name,'role':'ROLE_USER','parts':[{'url':'https://localhost:'+str(media_port)+'/file.bin',
                        'filename':'file.bin','mediaType':'application/octet-stream'}]}}}
                    before=len(fetched)
                    async with client.stream('POST',address,headers=headers,json=failed) as response:
                        assert response.status_code==200
                        lines=response.aiter_lines();frames=0
                        while frames<2:
                            text=await anext(lines)
                            if text.startswith('data:'):frames+=1
                        async with asyncio.timeout(5):
                            while len(fetched)!=before+1:await asyncio.sleep(.02)
                    await asyncio.sleep(.3)
                    assert len(fetched)==before+1 and len(store.list())==12
                    assert (await command(process,{'method':'counts'}))['relay']==15
                    cases.append('actual_A2A_HTTPS_'+str(status)+'_retains_native_input_and_blocks_automatic_resource_refetch_without_mission')
                waiting={'jsonrpc':'2.0','id':23,'method':'SendStreamingMessage','params':{'message':{'messageId':'media-revoke-stalled',
                    'contextId':'ctx-media-revoke','role':'ROLE_USER','parts':[{'url':'https://localhost:'+str(media_port)+'/stall',
                    'filename':'waiting.bin','mediaType':'application/octet-stream'}]}}}
                async with client.stream('POST',address,headers=headers,json=waiting) as response:
                    lines=response.aiter_lines();frames=[]
                    while len(frames)<2:
                        text=await anext(lines)
                        if text.startswith('data:'):frames.append(json.loads(text[5:]))
                    stalled_task=frames[0]['result']['task']['id'];await asyncio.wait_for(stalled.wait(),5)
                    changed={**config,'bindings':[{**grant,'generation':'b'*64}]};publish(changed)
                    await asyncio.wait_for(stall_closed.wait(),3)
                    async with asyncio.timeout(5):
                        while (await command(process,{'method':'health'}))['status']!='revoked':await asyncio.sleep(.02)
                with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db:
                    record,receipt=db.execute('SELECT record,admitted_receipt FROM a2a_tasks WHERE task_id=?',(stalled_task,)).fetchone()
                    assert json.loads(record)['state']==protocol.STATE_WORKING and receipt==''
                assert len(store.list())==12 and (await command(process,{'method':'counts'}))['relay']==15
                cases.append('actual_owner_withdrawal_cancels_stalled_HTTPS_resource_reader_and_native_dispatch_without_partial_media_mission_or_fake_terminal_task')
            finally:released.set();release_stall.set();cancel_release.set();await media_runner.cleanup()
            changed={**config,'bindings':[{**grant,'generation':'b'*64}]};publish(changed)
            async with asyncio.timeout(5):
                while (await command(process,{'method':'health'}))['status']!='revoked':await asyncio.sleep(.02)
            try:await client.post(address,headers=headers,json={'jsonrpc':'2.0','id':5,'method':'GetTask','params':{'id':task}})
            except httpx.TransportError:pass
            else:raise AssertionError('withdrawn saved owner publication left listener reachable')
            cases.append('actual_root_owned_policy_replacement_immediately_closes_gateway_listener_and_retained_peer_authority')
            await stop(process)
            # Disposable installed owner interpreter. The real private worker
            # uses -E/-s and root-owned .pth entries, not caller PYTHONPATH.
            import venv
            installed=Path('/usr/lib/haos/hermes/.venv');venv.EnvBuilder(with_pip=False).create(installed)
            site=installed/'lib/python3.11/site-packages';site.mkdir(parents=True,exist_ok=True)
            (site/'haos-installed.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
            private=etc/'gateway-credentials';private.write_text(json.dumps({'connectors':{'a2a':value}}));private.chmod(0o600)
            from haos.gateway_publication import validate_snapshot
            owner_policy_value=json.loads((etc/'gateways.json').read_text());validate_snapshot(owner_policy_value,{'connectors':{'a2a':value}})
            wrong_scope=json.loads(json.dumps(owner_policy_value));wrong_scope['bindings'][0]['scope']='a2a:'+'f'*64
            missing_callback=json.loads(json.dumps(value));missing_callback.pop('callbacks')
            callback_policy=json.loads(json.dumps(owner_policy_value));callback_policy['bindings'][0]['allow_callback']=True
            for bad_policy,bad_private in [(wrong_scope,value),(callback_policy,missing_callback)]:
                try:validate_snapshot(bad_policy,{'connectors':{'a2a':bad_private}})
                except ValueError:pass
                else:raise AssertionError('owner publication accepted scope or callback outside its private identity')
            cases.append('actual_TLS_owner_snapshot_validation_refuses_wrong_peer_server_scope_and_callback_without_private_destination_or_key')
            from haos import a2a_owner_setup,initial_setup,gateway_setup
            from haos.a2a_owner_process import command as owner_command
            isolated={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HERMES_SAFE_MODE':'1'}
            for denied_uid in [0,65533]:
                denied_worker=subprocess.run(owner_command(),input='',capture_output=True,text=True,user=denied_uid,
                    group=65534,extra_groups=[],cwd='/usr/lib/haos',env=isolated,timeout=10)
                assert denied_worker.returncode!=0 and 'gateway runtime requires its unprivileged service UID/GID' in denied_worker.stderr,denied_worker.stderr
            denied_code='''from haos import a2a_owner_setup as owner
actions=[lambda:owner.configure('a2a',{}),lambda:owner.save_account('a2a',{},'alice',''),lambda:owner.saved('a2a'),
lambda:owner.set_peer('a2a','alice',''),lambda:owner.remove_peer('a2a','alice'),
lambda:owner.pair('owner','a2a','alice','ctx-input','personal',['create','read']),lambda:owner.inspect('a2a'),
lambda:owner.recover('a2a',{},'purge-source-inputs','foreign UID',confirmed=True)]
for action in actions:
    try:action()
    except PermissionError:continue
    raise AssertionError('foreign UID entered A2A owner management')
import sys
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
print('all-owner-actions-denied-before-sdk')
'''
            rejected=subprocess.run([str(installed/'bin/python'),'-E','-s','-c',denied_code],capture_output=True,text=True,
                user=65533,group=65534,extra_groups=[],cwd='/usr/lib/haos',env=isolated,timeout=10)
            assert rejected.returncode==0 and rejected.stdout.strip()=='all-owner-actions-denied-before-sdk',rejected.stderr
            cases.append('actual_owner_backend_rejects_eight_foreign_UID_actions_before_SDK_and_private_inspection_worker_rejects_root_and_agent_UID')
            # No systemd runs in this offline namespace. Only the service-stop
            # boundary is a fixture; worker UID, saved files, runtime checks,
            # parent lifetime, TLS validation and private journals are real.
            original_quiesce=initial_setup.quiesce_for_setup;original_stopped=gateway_setup.stopped_gateway
            initial_setup.quiesce_for_setup=lambda **kwargs:None;gateway_setup.stopped_gateway=lambda:None
            try:
                checked=a2a_owner_setup.inspect('a2a')
                assert checked=={'runtime_ready':True,'tls_material_valid':True,'listener_bindable':True,
                    'external_reachability_verified':False,'message_sent':False,'mission_created':False},checked
                cases.append('actual_root_owner_no_send_inspection_drops_to_gateway_UID_and_checks_installed_native_runtime_TLS_and_exclusive_bind_without_external_reachability_claim')
                inventory=a2a_owner_setup.inspect('a2a','sources')
                assert 'tasks' in inventory,inventory
                assert len(inventory['tasks'])>=17 and inventory['has_more'] is False
                assert all(row['current_grant'] is False and row['original_retained'] is True for row in inventory['tasks'])
                assert any(row['resources'].get('authentication-refused') for row in inventory['tasks'])
                assert any(row['callbacks'].get('acknowledged') for row in inventory['tasks'])
                assert len(store.list())==12 and all(secret not in json.dumps(inventory) for secret in [*value['peer_tokens'].values(),value['callbacks']['alice']['secret']])
                cases.append('actual_owner_private_UID_readonly_inventory_exposes_retained_tasks_media_auth_refusal_callback_receipts_and_withdrawn_grants_without_raw_URI_keys_or_new_missions')
                rejected=next(row for row in inventory['tasks'] if row['native_state']=='TASK_STATE_REJECTED')
                working=next(row for row in inventory['tasks'] if row['native_state']=='TASK_STATE_WORKING')
                denied=a2a_owner_setup.recover('a2a',working,'purge-source-inputs','fixture terminal-state review',confirmed=True)
                assert denied=={'error':'authority-refused'},denied
                assert a2a_owner_setup.recover('a2a',working,'retry-source-auth','fixture revoked-grant review',confirmed=True)=={'error':'authority-refused'}
                cases.append('actual_private_UID_owner_recovery_refuses_active_or_unreconciled_sources_and_never_retries_withdrawn_authentication')
                purged=a2a_owner_setup.recover('a2a',rejected,'purge-source-inputs','fixture inspected rejected source',confirmed=True)
                assert purged.get('affected')==1 and purged['removed_bytes']>0 and purged['message_sent'] is False,purged
                repeated=a2a_owner_setup.recover('a2a',rejected,'purge-source-inputs','fixture inspected rejected source',confirmed=True)
                assert repeated==purged
                after=a2a_owner_setup.inspect('a2a','sources');retained_rejected=next(row for row in after['tasks'] if row['task_id']==rejected['task_id'])
                assert len(after['tasks'])==len(inventory['tasks']) and not retained_rejected['original_retained']
                assert retained_rejected['native_state']=='TASK_STATE_REJECTED' and not retained_rejected['parent_admitted'] and len(store.list())==12
                stale=a2a_owner_setup.recover('a2a',rejected,'purge-source-inputs','fixture different review cannot reuse stale snapshot',confirmed=True)
                assert stale=={'error':'authority-refused'},stale
                cases.append('actual_private_UID_atomic_logical_original_purge_preserves_task_and_replay_tombstones_and_idempotently_replays_receipt_after_lost_owner_response')
                output_source=next(row for row in inventory['tasks'] if row['task_id']==output_task)
                removed_output=a2a_owner_setup.recover('a2a',output_source,'purge-task-outputs','fixture inspected withdrawn completed artifact',confirmed=True)
                assert removed_output.get('affected')==1 and removed_output['removed_bytes']==len(file_bytes),removed_output
                assert a2a_owner_setup.recover('a2a',output_source,'purge-task-outputs','fixture inspected withdrawn completed artifact',confirmed=True)==removed_output
                with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as checked_db:
                    artifact_rows=checked_db.execute('SELECT metadata,length(data) FROM a2a_output_artifacts WHERE task_id=?',(output_task,)).fetchall()
                    assert len(artifact_rows)==1 and all(metadata and size==0 for metadata,size in artifact_rows)
                    retained_task=checked_db.execute('SELECT record,admitted_receipt,source_key FROM a2a_tasks WHERE task_id=?',(output_task,)).fetchone()
                    assert json.loads(retained_task[0])['state']==protocol.STATE_COMPLETED and retained_task[1]==retained_task[2]
                cases.append('actual_owner_atomic_output_byte_purge_preserves_completed_task_metadata_and_native_and_root_outcome_receipts_without_recreating_exports')
                # Restore the fixture's unchanged saved epoch solely to exercise
                # current-grant authentication recovery. A real new owner grant
                # receives a new epoch and cannot resurrect an old source.
                publish(config)
                current_inventory=a2a_owner_setup.inspect('a2a','sources')
                auth_source=next(row for row in current_inventory['tasks'] if row['resources'].get('authentication-refused'))
                assert auth_source['current_grant'] and not auth_source['parent_admitted']
                retried=a2a_owner_setup.recover('a2a',auth_source,'retry-source-auth','fixture exact unchanged source credentials checked',confirmed=True)
                assert retried.get('affected')==1 and retried['removed_bytes']==0 and retried['message_sent'] is False,retried
                assert a2a_owner_setup.recover('a2a',auth_source,'retry-source-auth','fixture exact unchanged source credentials checked',confirmed=True)==retried
                reset=a2a_owner_setup.inspect('a2a','sources')
                reset_auth=next(row for row in reset['tasks'] if row['task_id']==auth_source['task_id'])
                assert reset_auth['resources']=={'prepared':1} and reset_auth['resource_attempts']==0 and reset_auth['resource_retry_at']==0
                assert reset_auth['original_retained'] and not reset_auth['parent_admitted'] and len(store.list())==12
                publish(changed)
                cases.append('actual_root_private_UID_authentication_retry_resets_only_unchanged_current_unadmitted_resource_and_persists_idempotent_receipt_without_fetch_or_mission')
                metadata=initial_setup.gateway_configuration()['a2a']['a2a']
                assert all(secret not in json.dumps(metadata) for secret in [*value['peer_tokens'].values(),value['callbacks']['alice']['secret'],value['tls']['private_key']])
                server_fields={key:metadata[key] for key in ['agent_name','port','public_url','bind_host','public_listener']}
                saved_server=a2a_owner_setup.save_account('a2a',server_fields,'alice','',keep_tls=True,keep_token=True)
                assert saved_server['configured'] is True
                paired=a2a_owner_setup.pair('owner-ui','a2a','alice','ctx-owner-ui','personal',['create','read','cancel','answer'],
                    allow_media=True,allow_outbound_media=True,allow_callback=True)
                updated,stored=gateway_setup.load();paired_row=next(row for row in updated['bindings'] if row['id']=='owner-ui')
                assert paired['paired'] is True and paired_row['sender']=='alice' and paired_row['scope']==grant['scope']
                assert paired_row['generation'] not in {'a'*64,'b'*64} and paired_row['since']>1
                assert paired_row['allow_media'] is True and paired_row['allow_voice'] is False and paired_row['allow_callback'] is True
                assert stored['connectors']['a2a']['peer_tokens']['alice']==value['peer_tokens']['alice']
                cases.append('actual_root_owner_saved_TLS_and_named_peer_key_reuse_and_exact_context_pairing_publish_real_private_files_fresh_epoch_and_explicit_flags_without_message_or_mission')
                replacement='private_fixture_owner_rotation_'+'r'*32
                before_count=len(inventory['tasks']);a2a_owner_setup.set_peer('a2a','alice',replacement)
                updated,stored=gateway_setup.load()
                assert updated['bindings']==[] and stored['connectors']['a2a']['peer_tokens']['alice']==replacement
                assert stored['connectors']['a2a']['callbacks']==value['callbacks'] and stored['connectors']['a2a']['download_origins']==value['download_origins']
                retained=a2a_owner_setup.inspect('a2a','sources')
                assert len(retained['tasks'])==before_count and all(not row['current_account'] and not row['current_grant'] for row in retained['tasks'])
                assert len(store.list())==12
                audit=Path('/var/lib/haos-owner/audit.jsonl').read_text()
                assert all(secret not in audit for secret in [replacement,*value['peer_tokens'].values(),value['callbacks']['alice']['secret']])
                cases.append('actual_root_peer_token_rotation_revokes_all_old_connector_grants_preserves_resource_callback_settings_and_all_historical_task_data_without_credentials_in_owner_audit')
                # Exercise the actual production serve loop, not this fixture's
                # manual forwarding/pumping helpers or a prepared policy factory.
                a2a_owner_setup.pair('production-ui','a2a','alice','ctx-production-runtime','personal',['create','read','cancel'])
                production_policy,_=gateway_setup.load()
                production_private=json.loads((etc/'gateway-credentials').read_text())
                from haos.gateway import GatewayPolicy
                assert GatewayPolicy(production_policy).connectors['a2a']['platform']=='a2a'
                credential_directory=base/'installed-credentials';credential_directory.mkdir(mode=0o700);os.chown(credential_directory,65534,65534)
                credential_file=credential_directory/'gateway-credentials';credential_file.write_text(json.dumps(production_private));credential_file.chmod(0o400);os.chown(credential_file,65534,65534)
                process=spawn('production')
                production_headers={**headers,'Authorization':'Bearer '+replacement}
                async with asyncio.timeout(15):
                    while True:
                        if process.poll() is not None:raise AssertionError('production runtime exited: '+process.stderr.read())
                        try:
                            health=await client.get(address+'/health',headers=production_headers)
                            if health.status_code==200:break
                        except httpx.TransportError:pass
                        await asyncio.sleep(.05)
                production_request={'jsonrpc':'2.0','id':80,'method':'SendMessage','params':{'message':{
                    'messageId':'actual-production-source','contextId':'ctx-production-runtime','role':'ROLE_USER',
                    'parts':[{'text':'Actual production runtime loop input without model inference.'}]}}}
                pending=asyncio.create_task(client.post(address,headers=production_headers,json=production_request))
                async with asyncio.timeout(15):
                    while len(store.list())!=13:
                        if process.poll() is not None:raise AssertionError('production runtime exited: '+process.stderr.read())
                        await asyncio.sleep(.05)
                production_mission=next(row for row in store.list() if 'Actual production runtime loop input' in row['goal'])
                assert production_mission['state']=='queued' and not pending.done()
                listing=(await client.post(address,headers=production_headers,json={'jsonrpc':'2.0','id':81,'method':'ListTasks','params':{'pageSize':10}})).json()
                production_task=next(task['id'] for task in listing['result']['tasks'] if task['contextId']=='ctx-production-runtime')
                process.kill();await asyncio.to_thread(process.wait)
                try:await pending
                except httpx.TransportError:pass
                else:raise AssertionError('killed production listener claimed a complete task outcome')
                pending=None;process=spawn('production')
                async with asyncio.timeout(15):
                    while True:
                        if process.poll() is not None:raise AssertionError('production restart exited: '+process.stderr.read())
                        try:
                            health=await client.get(address+'/health',headers=production_headers)
                            if health.status_code==200:break
                        except httpx.TransportError:pass
                        await asyncio.sleep(.05)
                recovered=(await client.post(address,headers=production_headers,json=production_request)).json()
                assert recovered['result']['task']['id']==production_task and recovered['result']['task']['status']['state']==protocol.STATE_WORKING,recovered
                assert len(store.list())==13 and store.get(production_mission['id'])['state']=='queued'
                cases.append('actual_production_serve_SIGKILL_and_reopen_restore_native_task_and_parent_inbox_without_repeating_root_mission_on_same_wire_source_replay')
                await controller.dispatch('uid:0',{'method':'missions.cancel','params':{'id':production_mission['id']}})
                async with asyncio.timeout(15):
                    while True:
                        production_reply=(await client.post(address,headers=production_headers,json={'jsonrpc':'2.0','id':82,'method':'GetTask','params':{'id':production_task}})).json()
                        if production_reply['result']['status']['state']==protocol.STATE_CANCELED:break
                        await asyncio.sleep(.05)
                assert store.get(production_mission['id'])['state']=='cancelled'
                cases.append('actual_public_GatewayPolicy_and_production_serve_use_private_credentials_native_profile_TLScodec_automatic_root_admission_and_durable_outcome_publishing_without_fixture_forward_or_pump')
                process.terminate();await asyncio.wait_for(asyncio.to_thread(process.wait),20)
                production_stderr=process.stderr.read();assert process.returncode==0,production_stderr
                assert all(secret not in production_stderr for secret in [replacement,*value['peer_tokens'].values(),value['tls']['private_key'],value['callbacks']['alice']['secret']])
                cases.append('actual_production_serve_SIGTERM_closes_native_TLS_tasks_workers_and_journals_cleanly_without_exposing_private_credentials')
            finally:initial_setup.quiesce_for_setup=original_quiesce;gateway_setup.stopped_gateway=original_stopped
        finally:
            if process.poll() is None:process.kill();await asyncio.to_thread(process.wait)
            if pending is not None:
                if not pending.done():pending.cancel()
                await asyncio.gather(pending,return_exceptions=True)
            await client.aclose();store.close()
            control_server.close();await control_server.wait_closed()
    asyncio.run(exercise())
    print(json.dumps({'cases':cases,'passed':len(cases),'actual_UID_TLS_kernel_flock_SIGKILL_SQLite_reopen':True,
        'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'actual_controller_Unix_socket_SO_PEERCRED':True,
        'actual_public_registry_and_production_runtime':True,
        'live_peer_inference_installed_OS_or_release':False},indent=2))


if __name__=='__main__':main()
