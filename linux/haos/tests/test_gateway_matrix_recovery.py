import asyncio
import time
import pytest
from haos.gateway import GatewayPolicy,GatewayEngine
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import unresolved as raw_metadata,reconcile as reconcile_raw
from haos.gateway_recovery import reconcile
from haos.redaction import Redactor
from haos.store import MissionStore


def policy():
    return GatewayPolicy({'version':1,'connectors':[{'id':'matrix-main','platform':'matrix'}],'bindings':[
        {'id':'phone','connector':'matrix-main','sender':'@owner:example.org','chat':'!room:example.org','scope':'','thread':'',
         'identity':'principal','capabilities':['create','read'],'matrix_devices':[],'allow_plaintext':True,'require_mention':False,
         'generation':'a'*64,'since':int(time.time()*1000)-10000}]})


def envelope():
    return {'platform':'matrix','sender':'@owner:example.org','chat':'!room:example.org','scope':'','thread':'',
        'message_id':'$original-event:example.org','is_bot':False,'text':'private local owner recovery fixture'}


def test_matrix_raw_owner_recovery_lists_exact_event_id_without_content_and_retains_original_age(tmp_path):
    current=policy();inbox=NativeInbox(tmp_path/'raw.db',Redactor())
    try:
        original=time.time()-2;key=inbox.admit(current,'matrix-main',envelope(),{'private':'retained fixture'},received_at=original)
        for _ in range(8):
            assert inbox.claim(key,current,time.time()+100)
            inbox.retry(key)
        value=raw_metadata(inbox);assert value['ingress'][0]['message_id']==envelope()['message_id']
        assert 'retained fixture' not in str(value) and envelope()['text'] not in str(value)
        assert reconcile_raw(inbox,current,{'ingress_id':key,'state':'failed','attempt':8,'decision':'retry','owner_uid':1000,'note_sha256':'b'*64})['state']=='pending'
        restored=inbox.claim(key,current);assert restored['created_at']==original and restored['payload']=={'private':'retained fixture'}
    finally:inbox.close()


@pytest.fixture
def outbox(tmp_path):
    current=policy();store=MissionStore(tmp_path/'missions.db');engine=GatewayEngine(store)
    asyncio.run(engine.receive(current,'matrix-main',envelope(),None));delivery=engine.next_delivery(current)
    engine.acknowledge(current,delivery['id'],{'attempt':delivery['attempt'],'status':'uncertain'})
    yield store,current,delivery
    store.close()


def decision(delivery,receipt):
    return {'delivery_id':delivery['id'],'attempt':delivery['attempt'],'decision':'delivered','owner_uid':1000,
        'note_sha256':'b'*64,'receipt':receipt,'confirmed_not_delivered':False}


def test_matrix_owner_can_record_long_inspected_event_receipt_without_sending_or_replaying_mission(outbox):
    store,current,delivery=outbox;receipt='$'+'x'*200
    assert reconcile(store,current,decision(delivery,receipt))['state']=='delivered'
    assert store.db.execute('SELECT receipt FROM gateway_outbox WHERE id=?',(delivery['id'],)).fetchone()[0]==receipt
    assert len(store.list())==1 and GatewayEngine(store).next_delivery(current) is None


@pytest.mark.parametrize('receipt',['','not-event','$bad\nvalue','$'+'x'*255])
def test_matrix_owner_rejects_invalid_inspected_event_receipts(outbox,receipt):
    store,current,delivery=outbox
    with pytest.raises(ValueError):reconcile(store,current,decision(delivery,receipt))
    assert store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(delivery['id'],)).fetchone()[0]=='uncertain'
