"""Actual root SQLite source tombstones; no SDK or transport substitutions."""
import asyncio
import copy
import sqlite3

import pytest

from haos.controller import Controller
from haos.gateway import Conflict,digest
from haos.gateway_a2a import PreparedA2APolicy
from haos.gateway_raw import NativeInbox
from haos.store import MissionStore


@pytest.fixture
def source(tmp_path):
    b={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-input','scope':'a2a:'+'a'*64,'thread':'',
        'identity':'personal','capabilities':['create','read','cancel'],'generation':'a'*64,'since':1}
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[b]}
    policy=lambda:PreparedA2APolicy(config)
    path=tmp_path/'root.db';store=MissionStore(path);controller=Controller(store,'unused',set());controller.gateway_policy=policy
    envelope={'platform':'a2a','sender':'alice','chat':b['chat'],'scope':b['scope'],'thread':'','message_id':'original-source','text':'Controlled original.','is_bot':False}
    params={'connector':'a2a','envelope':envelope,'binding':{'binding_id':b['id'],'binding_digest':digest(b)}}
    yield store,controller,params,config,path
    store.close()


def call(controller,method,params):return asyncio.run(controller.gateway_dispatch({'method':method,'params':params}))


def test_root_proves_absence_and_tombstone_prevents_later_admission_and_replay(source):
    store,controller,params,_,_=source
    result=call(controller,'gateway.cancel-source',params)
    assert result=={'source_key':NativeInbox.key('a2a',params['envelope']),'prevented':True,'mission_id':None}
    assert call(controller,'gateway.cancel-source',params)==result
    with pytest.raises(Conflict):call(controller,'gateway.receive',params)
    assert store.list()==[] and store.db.execute('SELECT COUNT(*) FROM gateway_inbox').fetchone()[0]==0
    assert store.db.execute('SELECT COUNT(*) FROM gateway_source_cancellations').fetchone()[0]==1


def test_already_admitted_source_requests_real_cancel_without_claiming_absence_or_early_terminal_state(source):
    store,controller,params,_,_=source
    original=call(controller,'gateway.receive',params);mid=original['mission_id'];assert store.claim()['id']==mid
    result=call(controller,'gateway.cancel-source',params)
    assert result['prevented'] is False and result['mission_id']==mid
    assert store.get(mid)['cancel_requested']==1 and store.get(mid)['state']=='running'
    assert call(controller,'gateway.cancel-source',params)==result
    assert len([e for e in store.events(mid) if e['kind']=='mission.cancel-requested'])==1
    assert call(controller,'gateway.receive',params)==original


def test_actual_SQL_failure_rolls_back_source_tombstone_and_mission_cancellation_together(source):
    store,controller,params,_,_=source
    mid=call(controller,'gateway.receive',params)['mission_id'];store.claim()
    store.db.execute("CREATE TRIGGER fail_source_cancel BEFORE INSERT ON gateway_source_cancellations BEGIN SELECT RAISE(ABORT,'fixture source SQL failure'); END")
    with pytest.raises(sqlite3.IntegrityError):call(controller,'gateway.cancel-source',params)
    assert store.get(mid)['cancel_requested']==0
    assert not [e for e in store.events(mid) if e['kind']=='mission.cancel-requested']
    assert store.db.execute('SELECT COUNT(*) FROM gateway_source_cancellations').fetchone()[0]==0
    store.db.execute('DROP TRIGGER fail_source_cancel')
    assert call(controller,'gateway.cancel-source',params)['mission_id']==mid


@pytest.mark.parametrize('change',[{'binding':{}},{'binding':{'binding_id':'owner','binding_digest':'f'*64}},
    {'envelope':{'sender':'bob'}},{'envelope':{'chat':'different-context'}}])
def test_source_cancellation_requires_exact_current_sender_context_and_epoch_before_side_effects(source,change):
    store,controller,params,_,_=source;altered=copy.deepcopy(params)
    for key,value in change.items():
        if key=='envelope':altered[key].update(value)
        else:altered[key]=value
    with pytest.raises(PermissionError):call(controller,'gateway.cancel-source',altered)
    assert store.list()==[] and store.db.execute('SELECT COUNT(*) FROM gateway_source_cancellations').fetchone()[0]==0


def test_source_proof_survives_actual_root_database_reopen_and_refuses_tampering(source):
    store,controller,params,config,path=source
    call(controller,'gateway.cancel-source',params)
    reopened=MissionStore(path);other=Controller(reopened,'unused',set());other.gateway_policy=lambda:PreparedA2APolicy(config)
    try:
        with pytest.raises(Conflict):call(other,'gateway.receive',params)
        reopened.db.execute("UPDATE gateway_source_cancellations SET mission_id='fabricated-mission'")
        with pytest.raises(Conflict):call(other,'gateway.receive',params)
        with pytest.raises(Conflict):call(other,'gateway.cancel-source',params)
        assert reopened.list()==[]
    finally:reopened.close()
