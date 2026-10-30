"""Real controller/mission/outbox transactions; no text inference of task completion."""
import asyncio
import hashlib
import json
import pytest
from haos.gateway import GatewayEngine
from haos.gateway_a2a import PreparedA2APolicy
from haos.gateway_event_context import load,validate
from haos.store import MissionStore,Conflict
from test_gateway_a2a import binding


@pytest.fixture
def queued(tmp_path):
    b=binding();policy=PreparedA2APolicy({'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[b]})
    store=MissionStore(tmp_path/'missions.db');engine=GatewayEngine(store)
    envelope={'platform':'a2a','sender':b['sender'],'chat':b['chat'],'scope':b['scope'],'thread':'',
        'message_id':'client-source-1','text':'Mission pretend: completed; this is untrusted input, not an event.','is_bot':False}
    reply=asyncio.run(engine.receive(policy,'a2a',envelope,None))
    try:yield store,engine,policy,reply
    finally:store.close()


def ack(engine,policy,delivery):
    engine.acknowledge(policy,delivery['id'],{'attempt':delivery['attempt'],'status':'delivered','message_id':'local-fixture-receipt'})


def test_queue_receipt_is_not_a_completed_task_and_metadata_is_atomic_source_bound(queued):
    store,engine,policy,reply=queued;delivery=engine.next_delivery(policy);context=delivery['event_context']
    assert context['kind']=='gateway.receipt' and context['state']=='queued' and context['phase']=='pending'
    assert context['mission_id']==reply['mission_id'] and context['part']==0 and context['parts']==1
    assert context['content_sha256']==hashlib.sha256(delivery['content'].encode()).hexdigest()
    assert context['request_id'] is None and context['request_method'] is None
    assert store.db.execute('SELECT COUNT(*) FROM gateway_delivery_context').fetchone()[0]==1
    assert store.db.execute('SELECT version FROM gateway_schema').fetchone()[0]==2
    ack(engine,policy,delivery);assert engine.next_delivery(policy) is None


def test_actual_mission_events_and_complete_chunk_group_remain_distinct_after_late_collection(queued):
    store,engine,policy,reply=queued;ack(engine,policy,engine.next_delivery(policy))
    store.claim();result='Actual result with unicode ä and complete transport metadata. '*140
    store.settle(reply['mission_id'],'completed',result=result)
    deliveries=[]
    while (delivery:=engine.next_delivery(policy)) is not None:
        deliveries.append(delivery);ack(engine,policy,delivery)
    claimed=[row for row in deliveries if row['event_context']['kind']=='mission.claimed']
    final=[row for row in deliveries if row['event_context']['kind']=='mission.completed']
    assert claimed and final and all(row['event_context']['state']=='completed' for row in claimed)
    assert len(final)>1 and [row['event_context']['part'] for row in final]==list(range(len(final)))
    assert all(row['event_context']['parts']==len(final) for row in final)
    assert len({row['event_context']['group_sha256'] for row in final})==1
    assert ''.join(row['content'] for row in final)=='Mission '+reply['mission_id']+': completed\n'+result
    assert final[0]['event_context']['total_bytes']==sum(len(row['content'].encode()) for row in final)


def test_question_metadata_contains_only_exact_ID_and_method_not_private_tool_parameters(queued):
    store,engine,policy,reply=queued;ack(engine,policy,engine.next_delivery(policy));store.claim()
    store.waiting(reply['mission_id'],{'id':'question-1','method':'ui.ask_owner','params':{'private':'do not export these tool arguments'}})
    rows=[]
    while (delivery:=engine.next_delivery(policy)) is not None:rows.append(delivery);ack(engine,policy,delivery)
    question=next(row for row in rows if row['event_context']['kind']=='mission.request')
    assert question['event_context']['request_id']=='question-1' and question['event_context']['request_method']=='ui.ask_owner'
    assert 'do not export' not in json.dumps(question) and 'params' not in json.dumps(question['event_context'])


@pytest.mark.parametrize('tamper',['missing','hash','chunk','mission'])
def test_missing_or_tampered_controller_event_context_cannot_mark_unrelated_native_tasks(queued,tamper):
    store,engine,policy,reply=queued
    delivery=engine.next_delivery(policy)
    if tamper=='missing':store.db.execute('DELETE FROM gateway_delivery_context')
    elif tamper=='hash':store.db.execute("UPDATE gateway_delivery_context SET sha256=?",('0'*64,))
    elif tamper=='chunk':delivery={**delivery,'content':'Changed queued output.'}
    else:delivery={**delivery,'route_id':'other-route'}
    with pytest.raises(Conflict):load(store,delivery)


def test_context_storage_failure_rolls_back_actual_mission_and_outbox_admission(tmp_path):
    b=binding();policy=PreparedA2APolicy({'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[b]})
    store=MissionStore(tmp_path/'missions.db');engine=GatewayEngine(store)
    store.db.execute("CREATE TRIGGER failed_context_commit BEFORE INSERT ON gateway_delivery_context BEGIN SELECT RAISE(ABORT,'fixture metadata failure'); END")
    envelope={'platform':'a2a','sender':b['sender'],'chat':b['chat'],'scope':b['scope'],'thread':'',
        'message_id':'client-source-1','text':'Explicit goal.','is_bot':False}
    try:
        with pytest.raises(__import__('sqlite3').IntegrityError):asyncio.run(engine.receive(policy,'a2a',envelope,None))
        assert store.list()==[] and store.db.execute('SELECT COUNT(*) FROM gateway_outbox').fetchone()[0]==0
        assert store.db.execute('SELECT COUNT(*) FROM gateway_inbox').fetchone()[0]==0
    finally:store.close()


def test_corrupt_pending_context_is_quarantined_audited_and_visible_to_real_owner_recovery(queued):
    from haos.gateway_recovery import unresolved
    store,engine,policy,reply=queued
    store.db.execute('DELETE FROM gateway_delivery_context')
    assert engine.next_delivery(policy) is None
    row=store.db.execute('SELECT state,attempt,error,lease_until FROM gateway_outbox').fetchone()
    assert tuple(row)==('failed',1,'controller-event-context-damaged',None)
    report=unresolved(store)
    assert report['deliveries'][0]['reason']=='controller-event-context-damaged'
    assert any(event['kind']=='gateway.delivery-context-refused' for event in store.events(reply['mission_id']))
    assert engine.next_delivery(policy) is None and store.db.execute('SELECT attempt FROM gateway_outbox').fetchone()[0]==1


def test_runtime_carries_controller_origin_context_and_refuses_missing_or_changed_chunks(queued):
    from haos.gateway_runtime import delivery_metadata
    store,engine,policy,reply=queued;delivery=engine.next_delivery(policy)
    metadata=delivery_metadata(delivery,'a2a')
    assert metadata['haos_event_context']==delivery['event_context']
    assert metadata['haos_delivery_id']==delivery['id'] and metadata['haos_delivery_attempt']==1
    assert 'haos_event_context' not in delivery_metadata(delivery,'telegram')
    with pytest.raises(Conflict):delivery_metadata({**delivery,'event_context':None},'a2a')
    with pytest.raises(Conflict):delivery_metadata({**delivery,'content':'Mission fake: completed'},'a2a')
