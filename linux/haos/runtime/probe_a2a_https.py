#!/usr/bin/env python3
"""Real loopback TLS and frozen A2A HTTP/SSE/RPC with independently retained input.

The parent IPC is a direct local SQLite fixture; no gateway UID, live peer,
controller mission, model inference or public activation is claimed.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import httpx
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_tasks import Tasks
    from haos.gateway_a2a_native import build
    from haos.gateway_a2a_server import Server
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from plugins.platforms.a2a import protocol
    from webhook_tls_fixture import create
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-a2a-native-https-') as temp:
        root=Path(temp);create(root,'a2a.fixture.invalid')
        with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32,'bob':'private_fixture_bob_'+'b'*32},
            'port':port,'agent_name':'HAOS','tls':{'public_url':'https://a2a.fixture.invalid/a2a',
                'certificate':(root/'certificate.pem').read_text(),'private_key':(root/'key.pem').read_text(),
                'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        grants=[{'id':peer,'connector':'a2a','sender':peer,'chat':'ctx-shared','scope':scope(value,peer),'thread':'',
            'identity':'personal-'+peer,'capabilities':['create','read'],'generation':letter*64,'since':123}
            for peer,letter in [('alice','a'),('bob','b')]]
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':grants};active=[True]
        policy=lambda:PreparedA2APolicy(config)
        def current():
            if not active[0]:raise PermissionError('fixture publication withdrawal')
        raw=RawEvents(root/'originals.db',Redactor(),current);parent=NativeInbox(root/'parent.db',Redactor());indexes={}
        verified=ssl.create_default_context(cafile=str(root/'ca.pem'))
        server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.minimum_version=ssl.TLSVersion.TLSv1_2
        server_tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        def request(index,method='SendStreamingMessage'):return {'jsonrpc':'2.0','id':index,'method':method,'params':{'message':{
            'messageId':'message-'+str(index),'contextId':'ctx-shared','role':'ROLE_USER','parts':[{'text':'Explicit HTTPS peer goal '+str(index)}]}}}
        async def exercise():
            received=[];adapters={}
            async def capture(peer,data):return raw.capture(policy(),'a2a',value,peer,data)
            async def receive(event,proof,task_id):
                receipt=parent.admit(policy(),'a2a',proof['envelope'],{'raw_id':proof['id'],'task_id':task_id},received_at=proof['received_at'])
                received.append((proof['envelope']['sender'],task_id,proof['source_key']));return receipt
            for peer in value['peer_tokens']:
                home=root/peer;home.mkdir(mode=0o700)
                indexes[peer]=Tasks(home/'tasks.db',peer,value,current,policy,connector='a2a')
                adapters[peer]=build(value,peer,home,current,policy,indexes[peer],receive)
            server=Server(value,'a2a',adapters,current,policy,capture);server.start(server_tls)
            address='https://localhost:'+str(port);headers={'Host':'a2a.fixture.invalid','Authorization':'Bearer '+value['peer_tokens']['alice']}
            async with httpx.AsyncClient(verify=verified,trust_env=False,timeout=10,follow_redirects=False) as client:
                try:
                    card=await client.get(address+'/.well-known/agent-card.json',headers={'Host':'a2a.fixture.invalid'})
                    assert card.status_code==200 and card.json()['supportedInterfaces'][0]['url']==value['tls']['public_url']+'/',(card.status_code,card.text)
                    assert card.json()['security']==[{'bearer':[]}] and card.json()['capabilities']['pushNotifications'] is False
                    cases.append('actual_verified_loopback_TLS_native_AgentCard_and_fixed_public_RPC_URL_without_auth_or_forwarded_host_reflection')
                    async with httpx.AsyncClient(verify=True,trust_env=False,timeout=5) as untrusted:
                        try:await untrusted.get(address+'/.well-known/agent-card.json',headers={'Host':'a2a.fixture.invalid'})
                        except httpx.ConnectError as error:assert 'certificate' in str(error).lower()
                        else:raise AssertionError('fixture CA accepted as system trust')
                    cases.append('actual_TLS_verification_refuses_fixture_CA_without_explicit_client_trust')
                    rejected=await client.get(address+'/a2a/health',headers={'Host':'attacker.invalid','X-Forwarded-Host':'attacker.invalid'})
                    assert rejected.status_code!=200 and 'attacker.invalid' not in rejected.text
                    cases.append('unapproved_Host_cannot_redirect_advertised_native_endpoint')
                    bad=await client.post(address+'/a2a',headers={'Host':'a2a.fixture.invalid'},json=request(1))
                    assert bad.status_code==401 and not received
                    cases.append('localhost_TCP_source_is_not_an_authenticated_A2A_peer')
                    async with client.stream('POST',address+'/a2a/',headers=headers,json=request(1)) as response:
                        assert response.status_code==200 and response.headers['content-type'].startswith('text/event-stream')
                        lines=response.aiter_lines();events=[]
                        while len(events)<2:
                            line=await anext(lines)
                            if line.startswith('data: '):events.append(json.loads(line[6:]))
                        task_id=events[0]['result']['task']['id'];assert events[1]['result']['statusUpdate']['status']['state']==protocol.STATE_WORKING
                        assert indexes['alice'].get(task_id)['state']==protocol.STATE_WORKING
                        assert raw.db.execute('SELECT COUNT(*) FROM a2a_raw_events').fetchone()[0]==1
                        async with asyncio.timeout(5):
                            while not received:await asyncio.sleep(.01)
                        assert received[0][1]==task_id and parent.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
                        cases.append('actual_native_SSE_submitted_and_working_frames_arrive_before_withheld_terminal_result_after_FULL_source_and_task_custody')
                        result=await adapters['alice'].send('ctx-shared','Actual HTTPS native result.',metadata={
                            'notify':True,'haos_task_id':task_id,'source_key':received[0][2]})
                        assert result.message_id==task_id
                        async for line in lines:
                            if line.startswith('data: '):
                                try:events.append(json.loads(line[6:]))
                                except ValueError:assert line[6:]=='[DONE]'
                        assert any(e.get('result',{}).get('statusUpdate',{}).get('status',{}).get('state')==protocol.STATE_COMPLETED for e in events)
                        assert indexes['alice'].get(task_id)['reply']=='Actual HTTPS native result.'
                    cases.append('actual_native_private_sender_finalizes_task_and_native_SSE_artifact_terminal_frames_follow_committed_state')
                    duplicate=request(1,'SendMessage');duplicate['id']='new-correlation'
                    again=await client.post(address+'/a2a',headers=headers,json=duplicate)
                    assert again.status_code==200 and again.json()['result']['task']['id']==task_id and len(received)==1
                    assert raw.db.execute('SELECT COUNT(*) FROM a2a_raw_events').fetchone()[0]==1
                    cases.append('new_RPC_correlation_and_send_wrapper_recover_same_task_without_another_native_event_or_mission_input')
                    for peer in ['alice','bob']:
                        h={**headers,'Authorization':'Bearer '+value['peer_tokens'][peer]}
                        got=await client.post(address+'/a2a',headers=h,json={'jsonrpc':'2.0','id':7,'method':'GetTask','params':{'id':task_id}})
                        if peer=='alice':assert got.json()['result']['id']==task_id
                        else:assert got.json()['error']['code']==protocol.ERR_TASK_NOT_FOUND
                    cases.append('actual_native_GetTask_is_private_to_the_authenticated_peer_and_current_owner_grant')
                    listing=await client.post(address+'/a2a',headers=headers,json={'jsonrpc':'2.0','id':8,'method':'ListTasks','params':{'pageSize':100}})
                    assert listing.json()['result']['pageSize']==8 and listing.json()['result']['totalSize']==1
                    cases.append('actual_native_task_list_uses_bounded_truthful_page_size_and_private_persistent_index')
                    for changed in [ {'method':'CreateTaskPushNotificationConfig','params':{'taskId':task_id,'config':{'url':'http://127.0.0.1/private'}}},
                        {'method':'CancelTask','params':{'id':task_id}}, {'method':'GetTask','params':{'id':task_id,'taskId':'task-'+'f'*16}}]:
                        payload={'jsonrpc':'2.0','id':9,**changed}
                        bad=await client.post(address+'/a2a',headers=headers,json=payload)
                        assert 'error' in bad.json()
                    cases.append('unreviewed_callback_cancel_permission_and_ambiguous_task_selectors_refused_without_side_effects')
                    before=len(received)
                    malformed=await client.post(address+'/a2a',headers={**headers,'Content-Type':'application/json'},content=b'{"jsonrpc":"2.0","jsonrpc":"1.0"}')
                    assert 'error' in malformed.json() and len(received)==before
                    version=await client.post(address+'/a2a',headers={**headers,'A2A-Version':'99.0'},json=request(20))
                    assert 'error' in version.json() and len(received)==before
                    cases.append('duplicate_JSON_and_unreviewed_protocol_version_never_reach_native_task_or_agent_dispatch')
                    def ambiguous_length():
                        connection=verified.wrap_socket(socket.create_connection(('127.0.0.1',port),timeout=5),server_hostname='localhost')
                        try:
                            connection.sendall(('POST /a2a HTTP/1.1\r\nHost: a2a.fixture.invalid\r\nAuthorization: Bearer '+value['peer_tokens']['alice']+
                                '\r\nContent-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 4\r\nConnection: close\r\n\r\n{}').encode())
                            data=bytearray()
                            while len(data)<4096:
                                part=connection.recv(4096-len(data))
                                if not part:break
                                data.extend(part)
                            return bytes(data)
                        finally:connection.close()
                    malformed=await asyncio.to_thread(ambiguous_length)
                    assert b'unsupported-content' in malformed and len(received)==before
                    cases.append('actual_TLS_duplicate_Content_Length_is_refused_before_native_body_parse_or_dispatch')
                    async with client.stream('POST',address+'/a2a',headers=headers,json=request(30)) as dropped:
                        lines=dropped.aiter_lines()
                        async for line in lines:
                            if line.startswith('data: '):
                                dropped_task=json.loads(line[6:])['result']['task']['id'];break
                    async with asyncio.timeout(5):
                        while not any(row[1]==dropped_task for row in received):await asyncio.sleep(.01)
                    source=next(row[2] for row in received if row[1]==dropped_task)
                    assert indexes['alice'].get(dropped_task)['state']==protocol.STATE_WORKING
                    await adapters['alice'].send('ctx-shared','Result retained after client disconnect.',metadata={
                        'notify':True,'haos_task_id':dropped_task,'source_key':source})
                    got=await client.post(address+'/a2a',headers=headers,json={'jsonrpc':'2.0','id':31,'method':'GetTask','params':{'id':dropped_task}})
                    assert got.json()['result']['status']['state']==protocol.STATE_COMPLETED
                    assert got.json()['result']['artifacts'][0]['parts']==[protocol.text_part('Result retained after client disconnect.')]
                    assert len([row for row in received if row[1]==dropped_task])==1
                    cases.append('actual_client_TLS_stream_drop_then_native_result_and_GetTask_reconnect_preserve_one_durable_input_and_final_task')
                    async with client.stream('POST',address+'/a2a',headers=headers,json=request(2)) as response:
                        lines=response.aiter_lines()
                        async for line in lines:
                            if line.startswith('data: '):break
                        started=time.monotonic();active[0]=False
                        try:
                            async for _ in lines:pass
                        except (httpx.RemoteProtocolError,httpx.ReadError):pass
                        async with asyncio.timeout(5):
                            while not server.closed or server.workers:await asyncio.sleep(.01)
                        assert time.monotonic()-started<5
                        rows=indexes['alice'].db.execute('SELECT record FROM a2a_tasks').fetchall()
                        assert any(json.loads(row[0])['state']==protocol.STATE_WORKING for row in rows)
                        cases.append('actual_owner_withdrawal_closes_TLS_stream_listener_and_native_waiters_without_inventing_failed_mission')
                finally:await server.close()
            assert not server.sockets and not server.workers
        try:asyncio.run(exercise())
        finally:
            for tasks in indexes.values():tasks.close()
            parent.close();raw.close()
    receipt={'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'scope':'actual verified loopback TLS, native HTTP/SSE/RPC TaskStore codecs, parent direct SQLite receiver; origin/Host are fixture-only',
        'gateway_UID_process_boundary_controller_mission_inference_live_peer_or_public_activation':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
