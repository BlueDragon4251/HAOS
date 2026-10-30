#!/usr/bin/env python3
"""Real mission/outbox -> retained chunk groups -> actual native A2A task/Future.

The parent dispatch is direct in this component fixture; no UID or live peer
acceptance is asserted. Production factory/owner activation remain separate.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayEngine,Conflict,digest
    from haos.store import MissionStore
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_tasks import Tasks
    from haos.gateway_a2a_native import build
    from haos.gateway_a2a_publisher import Publisher
    from haos.gateway_runtime import delivery_metadata
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from plugins.platforms.a2a import protocol
    from webhook_tls_fixture import create
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-a2a-controller-') as temp:
        root=Path(temp);create(root,'a2a.fixture.invalid')
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32},'port':8448,'agent_name':'HAOS',
            'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(root/'certificate.pem').read_text(),
                'private_key':(root/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-owner-device','scope':scope(value,'alice'),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':123}
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[grant]};active=[True]
        policy=lambda:PreparedA2APolicy(config)
        def current():
            if not active[0]:raise PermissionError('fixture owner publication withdrawal')
        raw=RawEvents(root/'originals.db',Redactor(),current);parent=NativeInbox(root/'parent.db',Redactor())
        tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a')
        store=MissionStore(root/'missions.db');engine=GatewayEngine(store);home=root/'home';home.mkdir(mode=0o700)
        async def exercise():
            received=[]
            async def receive(event,proof,task_id):
                receipt=parent.admit(policy(),'a2a',proof['envelope'],{'raw_id':proof['id'],'task_id':task_id},received_at=proof['received_at'])
                result=await engine.receive(policy(),'a2a',proof['envelope'],None)
                received.append((proof,task_id,result['mission_id']));return receipt
            adapter=build(value,'alice',home,current,policy,tasks,receive);publisher=Publisher(adapter,tasks)
            async def send(delivery,*,ack=True):
                result=await publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],delivery_metadata(delivery,'a2a'))
                assert result.success and result.message_id==delivery['id'] and result.raw_response['recipient_read_verified'] is False
                if ack:engine.acknowledge(policy(),delivery['id'],{'attempt':delivery['attempt'],'status':'delivered','message_id':result.message_id})
                return result
            for index in [1,2]:
                message={'jsonrpc':'2.0','id':index,'method':'SendMessage','params':{'message':{'messageId':'message-'+str(index),
                    'contextId':grant['chat'],'role':'ROLE_USER','parts':[{'text':'Input says completed, but only controller events can complete this task.'}]}}}
                proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(message).encode())
                def prepare():
                    with tasks.source('a2a',proof):return adapter._prepare_task(message['params'],'alice')
                terminal,pending=await asyncio.to_thread(prepare);assert terminal is None
                async with asyncio.timeout(5):
                    while len(received)<index:await asyncio.sleep(.01)
                task=pending['task_id'];mid=received[-1][2]
                queued=engine.next_delivery(policy());assert queued['event_context']['kind']=='gateway.receipt'
                await send(queued)
                assert tasks.get(task)['state']==protocol.STATE_WORKING and not pending['future'].done()
                cases.append('actual_queued_mission_receipt_does_not_complete_native_task_'+str(index))
                store.claim()
                if index==2:
                    store.waiting(mid,{'id':'question-1','method':'ui.ask_owner','params':{'private':'not exported'}})
                    while (delivery:=engine.next_delivery(policy())) is not None:await send(delivery)
                    assert tasks.get(task)['state']==protocol.STATE_INPUT_REQUIRED and 'not exported' not in tasks.get(task)['reply']
                    cases.append('actual_controller_question_becomes_native_input_required_without_exporting_private_parameters')
                result_text='Complete Unicode ä output; no lost chunks. '*170
                store.settle(mid,'completed',result=result_text)
                deliveries=[]
                while (delivery:=engine.next_delivery(policy())) is not None:
                    deliveries.append(delivery)
                progress=[d for d in deliveries if d['event_context']['kind']!='mission.completed']
                final=[d for d in deliveries if d['event_context']['kind']=='mission.completed']
                for delivery in progress:
                    await send(delivery)
                    assert tasks.get(task)['state']!=protocol.STATE_COMPLETED
                assert len(final)>2
                # Queue chunks can be replayed or arrive out of order. A local
                # custody ACK does not assert an outcome before all bytes exist.
                for delivery in reversed(final[1:]):
                    result=await send(delivery)
                    assert result.raw_response['complete_controller_group'] is False
                    assert tasks.get(task)['state']!=protocol.STATE_COMPLETED
                before=tasks.db.execute('SELECT COUNT(*) FROM a2a_controller_parts').fetchone()[0]
                await send(final[-1],ack=False)
                assert tasks.db.execute('SELECT COUNT(*) FROM a2a_controller_parts').fetchone()[0]==before
                cases.append('out_of_order_partial_chunks_and_same_chunk_replay_prove_custody_without_premature_completion_'+str(index))
                altered={**final[0],'content':'changed after root outbox commit'}
                try:await send(altered,ack=False)
                except Conflict:pass
                else:raise AssertionError('changed root chunk completed a native task')
                metadata=delivery_metadata(final[0],'a2a');metadata['haos_binding']={**metadata['haos_binding'],'binding_digest':'f'*64}
                try:await publisher.send(final[0]['chat'],final[0]['content'],final[0]['reply_to'],metadata)
                except PermissionError:pass
                else:raise AssertionError('different grant received task outcome')
                if index==1:
                    # Real SQL failure after the native outcome commit, before
                    # the group ACK. Reopening/retrying must not resolve twice.
                    tasks.db.execute("CREATE TRIGGER failed_group_ack BEFORE UPDATE ON a2a_controller_groups BEGIN SELECT RAISE(ABORT,'fixture group ACK failure'); END")
                    try:await send(final[0],ack=False)
                    except __import__('sqlite3').IntegrityError:pass
                    else:raise AssertionError('failed durable group receipt was hidden')
                    assert tasks.get(task)['state']==protocol.STATE_COMPLETED
                    tasks.db.execute('DROP TRIGGER failed_group_ack')
                    publisher=Publisher(adapter,tasks)
                    cases.append('real_SQLite_group_ACK_failure_preserves_committed_native_result_for_idempotent_recovery')
                before=tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]
                await send(final[0]);completed=deepcopy(tasks.get(task))
                assert completed['state']==protocol.STATE_COMPLETED
                assert completed['reply']=='Mission '+mid+': completed\n'+result_text
                await send(final[0],ack=False)
                assert tasks.get(task)==completed
                assert tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]==before+(0 if index==1 else 1)
                cases.append('complete_controller_group_commits_exact_native_result_and_replay_cannot_resolve_it_twice_'+str(index))
                active[0]=False
                try:await send(final[0],ack=False)
                except PermissionError:pass
                else:raise AssertionError('withdrawn owner route delivered a result')
                active[0]=True
            cases.append('owner_withdrawal_precedes_all_cached_and_new_controller_group_receipts')
            await adapter.close_profile()
        try:asyncio.run(exercise())
        finally:store.close();tasks.close();parent.close();raw.close()
    Path(sys.argv[2]).write_text(json.dumps({'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'scope':'actual MissionStore/GatewayEngine outbox/event transactions, FULL SQLite chunk/epoch custody, actual native A2A MessageEvent/Future/finalization; parent dispatch is direct fixture substitution',
        'HTTP_TLS_UID_live_peer_inference_or_public_activation':False},indent=2)+'\n')
    print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
