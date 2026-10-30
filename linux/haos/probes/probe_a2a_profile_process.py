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
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-a2a-process-'));work.chmod(0o755)
    sys.path[:0]=['/sdk',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_a2a import PreparedA2APolicy,scope
    create(work,'a2a.fixture.invalid')
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));media_port=reserved.getsockname()[1]
    value={'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32,'unpaired':'private_fixture_unpaired_'+'z'*32},'port':port,'agent_name':'HAOS',
        'download_origins':{'alice':['https://localhost:'+str(media_port)]},
        'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(work/'certificate.pem').read_text(),
            'private_key':(work/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}}
    grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-process-device','scope':scope(value,'alice'),'thread':'',
        'identity':'personal','capabilities':['create','read','cancel','answer'],'generation':'a'*64,'since':1}
    media_grants=[{**grant,'id':'media-'+name,'chat':'ctx-media-'+name,'identity':'media-'+name,
        'capabilities':['create','read'],'allow_media':True,'allow_voice':True,'allow_video':True}
        for name in ['input','auth','rate','drop','revoke']]
    loop_grant={**grant,'id':'loop-check','chat':'ctx-loop-check','identity':'loop-check','capabilities':['create','read']}
    output_grant={**grant,'id':'output-check','chat':'ctx-output-check','identity':'output-check','capabilities':['create','read'],'allow_outbound_media':True}
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
    try:asyncio.run(call('gateway.next',{'ready':['a2a']}))
    except PermissionError:pass
    else:raise AssertionError('controller socket authorized foreign UID with gateway group access')
    print(json.dumps({'agent_private_data_and_factory_denied':True}));sys.exit(0)
require_runtime_identity()
try:Path(sys.argv[2]).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read owner credential')
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
            text=True,user=uid,group=65534,extra_groups=[],env=environment)
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
        assert all(token not in stderr for token in value['peer_tokens'].values()) and value['tls']['private_key'] not in stderr
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
            async def attachment(web_request):
                assert web_request.secure and 'Authorization' not in web_request.headers and 'Cookie' not in web_request.headers
                assert all(token not in str(web_request.headers) for token in value['peer_tokens'].values())
                fetched.append(web_request.path)
                if web_request.path=='/stall':
                    response=web.StreamResponse(headers={'Content-Type':'application/octet-stream','Content-Length':'1024'})
                    await response.prepare(web_request);stalled.set()
                    while not release_stall.is_set():
                        if web_request.transport is None or web_request.transport.is_closing():stall_closed.set();break
                        await asyncio.sleep(.02)
                    return response
                if web_request.path=='/image.png':
                    assert dict(web_request.query)=={'signed':'private-fixture-attachment-capability'}
                    response=web.StreamResponse(status=200,headers={'Content-Type':'image/png','Content-Length':str(len(png))})
                    await response.prepare(web_request);started.set();await released.wait();await response.write(png);await response.write_eof();return response
                if web_request.path=='/voice.flac':return web.Response(body=flac,content_type='audio/flac')
                return web.Response(status=mode['status'],body=b'fixture resource refusal')
            media_app=web.Application();media_app.router.add_get('/{name}',attachment)
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
                    pending=asyncio.create_task(client.post(address,headers=headers,json=output_request))
                    async with asyncio.timeout(10):
                        while (await command(process,{'method':'counts'}))['relay']!=9:await asyncio.sleep(.02)
                    output_mid=(await command(process,{'method':'forward'}))['mission_id']
                    assert store.claim()['id']==output_mid
                    store.session(output_mid,'runtime-output-session','stored-output-session')
                    result_text='Full controller text '+('x'*1710)+'\n```text\nMEDIA:./not-an-export.key\n```\nActual file follows.\nMEDIA:./result.csv\nDone.\n'
                    store.settle(output_mid,'completed',result=result_text)
                    assert (await command(process,{'method':'pump'}))['delivered']>=3
                    delivered=(await pending).json()['result']['task']
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
            finally:released.set();release_stall.set();await media_runner.cleanup()
            changed={**config,'bindings':[{**grant,'generation':'b'*64}]};publish(changed)
            async with asyncio.timeout(5):
                while (await command(process,{'method':'health'}))['status']!='revoked':await asyncio.sleep(.02)
            try:await client.post(address,headers=headers,json={'jsonrpc':'2.0','id':5,'method':'GetTask','params':{'id':task}})
            except httpx.TransportError:pass
            else:raise AssertionError('withdrawn saved owner publication left listener reachable')
            cases.append('actual_root_owned_policy_replacement_immediately_closes_gateway_listener_and_retained_peer_authority')
            await stop(process)
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
        'live_peer_inference_public_activation_or_release':False},indent=2))


if __name__=='__main__':main()
