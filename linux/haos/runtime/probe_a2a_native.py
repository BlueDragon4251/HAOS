#!/usr/bin/env python3
"""Actual native A2A prepare/dispatch/send/Future/RPC codecs with local parent custody.

No network listener, UID boundary, agent inference or live A2A peer is claimed.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import Conflict,digest
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_tasks import Tasks
    from haos.gateway_a2a_native import build
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from plugins.platforms.a2a import protocol
    from gateway.platforms.event import MessageEvent,MessageType
    from webhook_tls_fixture import create
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-a2a-native-core-') as temp:
        root=Path(temp);create(root,'a2a.fixture.invalid')
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32},'port':8448,'agent_name':'HAOS',
            'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(root/'certificate.pem').read_text(),
                'private_key':(root/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-owner-device','scope':scope(value,'alice'),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':123}
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[grant]};active=[True]
        policy=lambda:PreparedA2APolicy(config)
        def current():
            if not active[0]:raise PermissionError('fixture publication withdrawal')
        raw=RawEvents(root/'originals.db',Redactor(),current);parent=NativeInbox(root/'parent-inputs.db',Redactor())
        tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a');home=root/'native-home';home.mkdir(mode=0o700)
        (home/'config.yaml').write_text('a2a_served_agents:\n  arbitrary:\n    profile: owner\n    local: false\n')
        def request(index):return {'jsonrpc':'2.0','id':index,'method':'SendMessage','params':{'message':{
            'messageId':'message-'+str(index),'contextId':grant['chat'],'role':'ROLE_USER','parts':[{'text':'Explicit native peer goal '+str(index)}]}}}
        async def exercise():
            accepted=[]
            async def receive(event,proof,task_id):
                assert event.message_id==task_id and event.text==proof['envelope']['text']
                receipt=parent.admit(policy(),'a2a',proof['envelope'],{'raw_id':proof['id'],'task_id':task_id},received_at=proof['received_at'])
                assert receipt==proof['source_key'];accepted.append((task_id,receipt));return receipt
            adapter=build(value,'alice',home,current,policy,tasks,receive)
            assert set(adapter._agents)=={''} and adapter._agents['']['local'] is True
            assert adapter._security_context.authenticate('Bearer '+value['peer_tokens']['alice'],'127.0.0.1')=='alice'
            assert adapter._security_context.authenticate(None,'127.0.0.1') is None
            card=adapter._build_card();assert card['security']==[{'bearer':[]}]
            assert [skill['id'] for skill in card['skills']]==['toolset.haos_missions']
            cases.append('actual_native_constructor_token_comparer_and_card_use_one_fixed_local_agent_without_ambient_profile_or_tool_registry')
            try:await adapter.connect()
            except PermissionError:pass
            else:raise AssertionError('native unbounded plaintext server enabled')
            cases.append('native_plaintext_connect_is_unavailable_outside_the_future_bounded_HTTPS_broker')
            message=request(1);proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(message).encode())
            altered=deepcopy(message['params']);altered['message']['parts']=[{'text':'changed after custody'}]
            def changed():
                with tasks.source('a2a',proof):adapter._prepare_task(altered,'alice')
            try:await asyncio.to_thread(changed)
            except PermissionError:pass
            else:raise AssertionError('changed native parameters caused task side effects')
            assert tasks.by_source(proof['source_key']) is None
            cases.append('parameters_must_match_retained_semantic_fingerprint_before_native_task_or_log_creation')
            def rpc():
                with tasks.source('a2a',proof):return adapter._rpc_message_send(1,message['params'],'alice',v1_response=True)
            response=asyncio.create_task(asyncio.to_thread(rpc))
            async with asyncio.timeout(5):
                while not accepted:await asyncio.sleep(.01)
            task_id,source_key=accepted[0]
            assert not response.done() and parent.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
            metadata={'notify':True,'haos_task_id':task_id,'source_key':source_key}
            result=await adapter.send(grant['chat'],'Actual native result.',metadata=metadata)
            assert result.success and result.message_id==task_id
            assert result.raw_response=={'recipient_read_verified':False,'local_task_committed':True}
            wire=await asyncio.wait_for(response,5);task=wire['result']['task']
            assert wire['id']==1 and task['id']==task_id and task['status']['state']==protocol.STATE_COMPLETED
            assert task['artifacts'][0]['parts']==[protocol.text_part('Actual native result.')]
            cases.append('actual_native_prepare_emits_MessageEvent_and_waits_for_local_durable_parent_receipt_before_final_result')
            cases.append('actual_native_send_resolves_exact_Future_and_native_RPC_builder_returns_committed_result_not_timestamp_fake_ACK')
            before=tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]
            cached=await adapter.send(grant['chat'],'Actual native result.',metadata=metadata)
            assert cached.message_id==task_id and tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]==before
            cases.append('same_result_replay_uses_committed_task_without_a_second_native_resolution')
            for changed_meta,changed_chat,content in [({**metadata,'haos_task_id':'task-'+'f'*16},grant['chat'],'Actual native result.'),
                (metadata,'other-context','Actual native result.'),(metadata,grant['chat'],'Changed result.'),
                (metadata,grant['chat'],value['peer_tokens']['alice'])]:
                try:await adapter.send(changed_chat,content,metadata=changed_meta)
                except (PermissionError,Conflict):pass
                else:raise AssertionError('native result changed target or exposed a private token')
            cases.append('other_task_context_changed_result_and_credential_reflection_are_refused_before_native_send')
            forged=MessageEvent(text='unretained',message_type=MessageType.TEXT,message_id=task_id,
                source=adapter.build_source(chat_id=grant['chat'],user_id='alice'))
            try:await adapter.handle_message(forged)
            except PermissionError:pass
            else:raise AssertionError('native event bypassed retained source context')
            cases.append('direct_native_event_without_sealed_source_context_cannot_reach_parent_or_agent')
            for index,body in [(2,'Contact alice@example.invalid for the result.'),(3,'[INPUT_REQUIRED] Which approved option?')]:
                message=request(index);proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(message).encode())
                def prepare():
                    with tasks.source('a2a',proof):return adapter._prepare_task(message['params'],'alice')
                terminal,pending=await asyncio.to_thread(prepare);assert terminal is None
                async with asyncio.timeout(5):
                    while len(accepted)<index:await asyncio.sleep(.01)
                if index==2:
                    assert adapter._finalize_task(pending,protocol.STATE_FAILED,'[client disconnected]')==(protocol.STATE_WORKING,'')
                    assert adapter._finalize_task(pending,protocol.STATE_FAILED,'[agent did not reply in time]')==(protocol.STATE_WORKING,'')
                    assert not pending['future'].done()
                    cases.append('client_disconnect_and_request_timeout_do_not_invent_failed_durable_missions_or_drop_their_future')
                metadata={'notify':True,'haos_task_id':pending['task_id'],'source_key':proof['source_key']}
                await adapter.send(grant['chat'],body,metadata=metadata)
                committed=tasks.get(pending['task_id'])
                if index==2:assert committed['reply']=='Contact [redacted-email] for the result.'
                else:assert committed['state']==protocol.STATE_INPUT_REQUIRED and committed['reply']=='Which approved option?'
                before=deepcopy(committed);await adapter.send(grant['chat'],body,metadata=metadata)
                assert tasks.get(pending['task_id'])==before
                cases.append('actual_native_finalization_and_cached_projection_'+('email_redaction' if index==2 else 'input_required_marker'))
            # These are structured controller outcomes, rather than language
            # model text interpreted as mission state. Exercise actual native
            # Futures and both SQLite commit boundaries.
            for index,state in [(4,protocol.STATE_INPUT_REQUIRED),(5,protocol.STATE_FAILED),(6,protocol.STATE_CANCELED),(7,protocol.STATE_COMPLETED)]:
                await adapter.close_profile()
                adapter=build(value,'alice',home,current,policy,tasks,receive)
                message=request(index);proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(message).encode())
                def prepare_outcome():
                    with tasks.source('a2a',proof):return adapter._prepare_task(message['params'],'alice')
                terminal,pending=await asyncio.to_thread(prepare_outcome);assert terminal is None
                async with asyncio.timeout(5):
                    while len(accepted)<index:await asyncio.sleep(.01)
                target=pending['task_id'];key=proof['source_key'];epoch=digest(['controller-event',index])
                body='Which approved option?' if index==4 else 'Controller outcome '+str(index)+'.'
                if index==7:
                    tasks.db.execute("CREATE TRIGGER failed_epoch_commit BEFORE UPDATE ON a2a_result_epochs BEGIN SELECT RAISE(ABORT,'fixture epoch receipt failure'); END")
                    try:await adapter.send_outcome(target,key,epoch,body,state)
                    except __import__('sqlite3').IntegrityError:pass
                    else:raise AssertionError('epoch receipt commit failure was hidden')
                    assert tasks.get(target)['state']==state and tasks.get(target)['reply']==body
                    assert tasks.db.execute('SELECT state FROM a2a_result_epochs WHERE task_id=?',(target,)).fetchone()[0]=='writing'
                    tasks.db.execute('DROP TRIGGER failed_epoch_commit')
                    before=tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]
                    recovered=await adapter.send_outcome(target,key,epoch,body,state)
                    assert recovered.success and tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]==before
                    cases.append('committed_native_outcome_recovers_failed_epoch_receipt_without_repeating_native_resolution')
                else:
                    result=await adapter.send_outcome(target,key,epoch,body,state)
                    assert result.success and result.message_id==target
                assert tasks.get(target)['state']==state and tasks.get(target)['reply']==body
                before=deepcopy(tasks.get(target))
                await adapter.send_outcome(target,key,epoch,body,state)
                assert tasks.get(target)==before
                if index==4:
                    finished=await adapter.send_outcome(target,key,digest(['controller-completed',index]),'Owner answered; mission completed.',protocol.STATE_COMPLETED)
                    assert finished.success and tasks.get(target)['state']==protocol.STATE_COMPLETED
                    completed=deepcopy(tasks.get(target))
                    await adapter.send_outcome(target,key,epoch,body,state)
                    assert tasks.get(target)==completed
                    cases.append('input_required_then_completed_uses_distinct_immutable_epochs_and_old_question_replay_cannot_replace_final_result')
                else:cases.append('structured_controller_state_uses_actual_native_Future_and_immutable_epoch_'+state)
                for wrong_epoch,wrong_body,wrong_state in [(epoch,body+' changed',state),(epoch,body,protocol.STATE_WORKING)]:
                    try:await adapter.send_outcome(target,key,wrong_epoch,wrong_body,wrong_state)
                    except (ValueError,PermissionError,Conflict):pass
                    else:raise AssertionError('controller event changed outcome or used a non-outcome state')
            cases.append('changed_epoch_bodies_and_non_outcome_states_are_refused_before_native_resolution')
            active[0]=False
            try:await adapter.send(grant['chat'],body,metadata=metadata)
            except PermissionError:pass
            else:raise AssertionError('revoked native profile sent a result')
            cases.append('current_publication_withdrawal_precedes_native_result_use')
            active[0]=True;await adapter.close_profile()
        try:asyncio.run(exercise())
        finally:tasks.close();parent.close();raw.close()
    receipt={'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'scope':'actual native A2A constructor/prepare/MessageEvent/send/Future/finalization/RPC codecs and real local parent SQLite; IPC receiver is direct fixture substitution',
        'HTTP_TLS_UID_worker_controller_mission_model_inference_live_peer_or_public_activation':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
