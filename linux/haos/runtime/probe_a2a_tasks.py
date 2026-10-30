#!/usr/bin/env python3
"""Actual frozen A2A TaskStore/Futures with local private SQLite source custody."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import Conflict
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_tasks import Tasks
    from haos.redaction import Redactor
    from plugins.platforms.a2a import protocol
    from webhook_tls_fixture import create
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-a2a-native-tasks-') as temp:
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
        raw=RawEvents(root/'originals.db',Redactor(),current)
        body={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':{'messageId':'message-1',
            'contextId':grant['chat'],'role':'ROLE_USER','parts':[{'text':'Independently approved peer goal.'}]}}}
        proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(body).encode())
        tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a');task=protocol.new_task_id()
        assert type(tasks.native) is protocol.TaskStore and tasks.db.execute('PRAGMA synchronous').fetchone()[0]==2
        try:tasks.create(task,grant['chat'],'alice')
        except PermissionError:pass
        else:raise AssertionError('unretained native task accepted')
        assert tasks.get(task) is None;cases.append('actual_native_TaskStore_creation_requires_retained_source_context')
        with tasks.source('a2a',proof):created=tasks.create(task,grant['chat'],'alice')
        assert created==tasks.native.get(task)==tasks.get(task) and created['state']==protocol.STATE_SUBMITTED
        assert tasks.by_source(proof['source_key'])['task_id']==task
        assert tasks.db.execute('SELECT admitted_receipt FROM a2a_tasks').fetchone()[0]==''
        cases.append('actual_native_task_ID_builder_and_record_creation_commit_before_return_with_immutable_source_mapping')
        for kind in ['same-source','other-context','other-peer','other-profile']:
            args=(protocol.new_task_id(),grant['chat'],'alice','','')
            if kind=='other-context':args=(args[0],'other-context',*args[2:])
            if kind=='other-peer':args=(args[0],args[1],'bob','','')
            if kind=='other-profile':args=(args[0],args[1],args[2],'unreviewed-profile','')
            try:
                with tasks.source('a2a',proof):tasks.create(*args)
            except (PermissionError,Conflict):pass
            else:raise AssertionError('native task rebound source or route')
            cases.append('native_task_refuses_'+kind)
        tasks.admitted(task,proof['source_key'])
        assert tasks.by_source(proof['source_key'])['admitted_receipt']==proof['source_key']
        try:tasks.admitted(task,'f'*64)
        except (PermissionError,Conflict):pass
        else:raise AssertionError('native task and parent source receipt disagreed')
        cases.append('separate_parent_durable_input_receipt_must_match_exact_source')
        tasks.set_state(task,protocol.STATE_WORKING);watch=tasks.watch(task);assert not watch.done()
        complete=tasks.complete(task,protocol.STATE_COMPLETED,'Approved local task result.')
        assert watch.result()==(protocol.STATE_COMPLETED,'Approved local task result.') and complete==tasks.get(task)
        assert tasks.db.execute("SELECT COUNT(*) FROM a2a_task_transitions WHERE state='committed'").fetchone()[0]==2
        cases.append('actual_native_Future_and_completion_commit_both_working_and_final_transition_proofs')
        before=deepcopy(complete);tasks.close();tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a')
        assert tasks.get(task)==before and tasks.native.get(task)==before
        assert tasks.complete(task,protocol.STATE_COMPLETED,'Approved local task result.') is None
        assert tasks.db.execute('SELECT COUNT(*) FROM a2a_task_transitions').fetchone()[0]==2
        cases.append('actual_native_state_restores_after_reopen_and_same_final_outcome_is_idempotent')
        try:tasks.complete(task,protocol.STATE_COMPLETED,'Replaced result.')
        except Conflict:pass
        else:raise AssertionError('confirmed task outcome replaced')
        cases.append('terminal_native_outcome_cannot_change_on_replay')
        page,next_offset,total=tasks.list(with_total=True)
        assert page==[before] and next_offset==0 and total==1
        card=protocol.TaskStore.to_task(page[0]);assert card['id']==task and card['status']['state']==protocol.STATE_COMPLETED
        assert card['artifacts'][0]['parts']==[protocol.text_part('Approved local task result.')]
        cases.append('actual_native_task_renderer_and_retained_pagination_use_original_completed_record')
        active[0]=False
        for call in [lambda:tasks.get(task),lambda:tasks.list(),lambda:tasks.complete(task,protocol.STATE_COMPLETED,'Approved local task result.')]:
            try:call()
            except PermissionError:pass
            else:raise AssertionError('withdrawn publication continued to use tasks')
        active[0]=True;cases.append('current_publication_withdrawal_blocks_read_list_and_completion_before_native_use')
        import concurrent.futures
        second=deepcopy(body);second['params']['message']['messageId']='message-concurrent'
        concurrent_source=raw.capture(policy(),'a2a',value,'alice',json.dumps(second).encode())
        def create_concurrently(_):
            task_id=protocol.new_task_id()
            try:
                with tasks.source('a2a',concurrent_source):tasks.create(task_id,grant['chat'],'alice')
                return task_id
            except Conflict:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:created=list(executor.map(create_concurrently,range(2)))
        assert len([task_id for task_id in created if task_id])==1
        other_task=next(task_id for task_id in created if task_id)
        assert tasks.by_source(concurrent_source['source_key'])['task_id']==other_task
        cases.append('actual_concurrent_HTTP_style_threads_bind_one_retained_source_to_exactly_one_native_task')
        tasks.set_state(other_task,protocol.STATE_WORKING)
        # A real failing SQLite update after the native Future resolves leaves a
        # durable writing intent. It cannot silently retry after process reopen.
        tasks.db.execute("CREATE TRIGGER failed_native_completion BEFORE UPDATE OF record ON a2a_tasks WHEN NEW.task_id='"+other_task+"' BEGIN SELECT RAISE(ABORT,'fixture final commit failure'); END")
        watcher=tasks.watch(other_task)
        try:tasks.complete(other_task,protocol.STATE_COMPLETED,'Locally accepted native result; HTTP not tested.')
        except __import__('sqlite3').IntegrityError:pass
        else:raise AssertionError('failing SQLite final transition commit was hidden')
        assert watcher.done() and tasks.get(other_task)['state']==protocol.STATE_WORKING
        assert tasks.db.execute("SELECT COUNT(*) FROM a2a_task_transitions WHERE state='writing'").fetchone()[0]==1
        tasks.db.execute('DROP TRIGGER failed_native_completion');tasks.close()
        tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a')
        try:tasks.complete(other_task,protocol.STATE_COMPLETED,'Locally accepted native result; HTTP not tested.')
        except Conflict:pass
        else:raise AssertionError('uncertain transition silently repeated after reopen')
        cases.append('actual_SQLite_final_commit_failure_retains_writing_intent_and_blocks_implicit_repeat_after_reopen')
        config['bindings'][0]={**grant,'generation':'b'*64}
        try:tasks.get(task)
        except PermissionError:pass
        else:raise AssertionError('new owner grant inherited old task')
        tasks.close();tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a')
        assert tasks.native.get(task) is None
        assert tasks.db.execute('SELECT COUNT(*) FROM a2a_tasks').fetchone()[0]==2
        cases.append('changed_owner_grant_preserves_private_history_but_never_restores_it_into_native_active_store')
        tasks.close();raw.close()
    receipt={'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'scope':'actual frozen native TaskStore, task ID and task renderer, real Future, private SQLite; fixture source policy and local result bytes only',
        'HTTP_TLS_UID_worker_delivery_controller_mission_or_public_activation':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
