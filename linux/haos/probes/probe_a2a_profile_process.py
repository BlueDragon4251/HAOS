"""Offline installed-code A2A UID/TLS/process-kill/controller socket contract.

The actual root Controller uses its existing policy callback with the prepared
A2A policy. Its real Unix client checks SO_PEERCRED; no model inference,
external peer or full public owner activation is claimed.
"""
import asyncio
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
    value={'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32},'port':port,'agent_name':'HAOS',
        'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(work/'certificate.pem').read_text(),
            'private_key':(work/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}}
    grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-process-device','scope':scope(value,'alice'),'thread':'',
        'identity':'personal','capabilities':['create','read','cancel'],'generation':'a'*64,'since':1}
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[grant]}
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
    inbox=NativeInbox(base/'native.db',Redactor());relay=RelayInbox(base/'relay.db',Redactor())
    parent=base/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
    value=json.loads((base/'account.json').read_text())
    adapter=None
    try:
        adapter=build_adapter('a2a',value,a2a_context={'parent':parent,'connector':'a2a','policy':policy,'inbox':inbox})
        def receive(event):
            assert event.raw_message is None and event.media_urls==[]
            relay.admit(policy(),'a2a',adapter_envelope(event,'a2a'));return True
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
                result=await call('gateway.receive',{'connector':'a2a','envelope':item['envelope'],
                    'binding':{'binding_id':item['binding_id'],'binding_digest':item['binding_digest']}})
                relay.admitted(item['id'],result['mission_id'])
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
                    sent=await adapter.send(d['chat'],d['content'],reply_to=d['reply_to'],metadata=delivery_metadata(d,'a2a'))
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
        process.stdin.write(json.dumps(data)+'\n');process.stdin.flush();return await line(process)
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
        from haos.gateway import GatewayEngine
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
            cases.append('actual_installed_readonly_code_dedicated_gateway_UID_and_verified_TLS_listener')
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
            source=next((base/'profiles').glob('a2a-*/peer-*/tasks.db'))
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
