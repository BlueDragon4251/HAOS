"""Exact offline multipart decisions with real SQLite; no delivery or UID mocks."""
import json
import sqlite3
import time
from types import SimpleNamespace
import pytest
from haos.gateway import Conflict,digest
from haos.gateway_feishu import PreparedFeishuPolicy
from haos.gateway_feishu_delivery import Publisher
from haos.gateway_feishu_media_delivery import MediaPublisher
from haos.gateway_feishu_media_recovery import outgoing,approve_retry,TABLES
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_feishu import account,binding


@pytest.fixture
def ledger(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.db',Redactor())
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='feishu',inbox=inbox),_haos_feishu_value=account())
    publisher=Publisher(adapter);media=MediaPublisher(adapter);now=time.time()
    for table in TABLES.values():
        for part in (0,1):inbox.db.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('a'*64,part,1,'feishu',media.scope,'b'*64,'uncertain','','','',now,now))
    b={**binding(),'allow_outbound_media':True}
    policy=PreparedFeishuPolicy({'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[b]})
    yield inbox,policy
    inbox.close()


def request(inbox,operation='upload',part=0):
    item=next(x for x in outgoing(inbox) if x['operation']==operation and x['part']==part)
    return {'connector':'feishu','delivery_id':item['delivery_id'],'operation':operation,'part':part,'attempt':1,
        'snapshot_sha256':item['snapshot_sha256'],'owner_uid':1000,'note_sha256':'c'*64,'confirmed':True,'confirmed_not_accepted':True}


@pytest.mark.parametrize('operation',['upload','reply'])
def test_only_selected_part_and_operation_released_with_durable_idempotent_audit(ledger,operation):
    inbox,policy=ledger;decision=request(inbox,operation);result=approve_retry(inbox,policy,decision)
    assert result['network_requested'] is False and result['controller_reconciliation_still_required'] is True
    items=outgoing(inbox);assert sum(x['state']=='owner-retry-approved' for x in items)==1
    assert next(x for x in items if x['operation']==operation and x['part']==0)['state']=='owner-retry-approved'
    assert approve_retry(inbox,policy,decision)==result
    assert inbox.db.execute('SELECT COUNT(*) FROM feishu_media_owner_events').fetchone()[0]==1
    with pytest.raises(Conflict):approve_retry(inbox,policy,{**decision,'note_sha256':'e'*64})


@pytest.mark.parametrize('change',[{'part':True},{'part':4},{'operation':'delete'},{'operation':[]},
    {'confirmed_not_accepted':1},{'confirmed':False},{'owner_uid':True},{'attempt':5},
    {'snapshot_sha256':'d'*64},{'part':1},{'operation':'reply'},{'connector':'unknown'},{'extra':'unsafe'}])
def test_ambiguous_or_stale_cross_part_decisions_never_release_an_intent(ledger,change):
    inbox,policy=ledger
    # Make each row distinguishable even when the fixture clock is identical.
    inbox.db.execute('UPDATE feishu_media_reply_intents SET fingerprint=?',('f'*64,))
    with pytest.raises((PermissionError,Conflict)):approve_retry(inbox,policy,{**request(inbox),**change})
    assert all(x['state']=='uncertain' for x in outgoing(inbox))


@pytest.mark.parametrize('operation',['upload','reply'])
def test_confirmed_acceptance_is_private_and_cannot_be_released(ledger,operation):
    inbox,policy=ledger;table=TABLES[operation]
    receipt=({'state':'confirmed','kind':'file','key':'file_v3_private_fixture_acceptance'} if operation=='upload'
        else {'state':'confirmed','message_id':'om_'+'e'*32})
    encoded=json.dumps(receipt,sort_keys=True,separators=(',',':'))
    inbox.db.execute(f"UPDATE {table} SET state='confirmed',receipt=?,receipt_sha256=? WHERE part=0",(encoded,digest(['b'*64,encoded])))
    assert 'file_v3_private_fixture_acceptance' not in json.dumps(outgoing(inbox))
    decision=request(inbox,operation)
    with pytest.raises(PermissionError):approve_retry(inbox,policy,decision)
    inbox.db.execute(f'UPDATE {table} SET receipt_sha256=? WHERE part=0',('f'*64,))
    with pytest.raises(Conflict):outgoing(inbox)


def test_audit_failure_rolls_back_the_selected_release_and_requires_current_output_grant(ledger):
    inbox,policy=ledger;decision=request(inbox)
    config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding()]}
    with pytest.raises(PermissionError):approve_retry(inbox,PreparedFeishuPolicy(config),decision)
    approve_retry(inbox,policy,request(inbox,'reply',1))
    inbox.db.execute("CREATE TRIGGER failed_part_audit BEFORE INSERT ON feishu_media_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError):approve_retry(inbox,policy,decision)
    assert next(x for x in outgoing(inbox) if x['operation']=='upload' and x['part']==0)['state']=='uncertain'
    assert inbox.db.execute('SELECT COUNT(*) FROM feishu_media_owner_events').fetchone()[0]==1


def test_native_owner_inventory_accepts_exact_feishu_message_id_without_optional_runtime(ledger):
    from haos.gateway_raw_recovery import unresolved
    inbox,policy=ledger;b=policy.bindings['owner']
    event={'platform':'feishu','sender':b['sender'],'chat':b['chat'],'scope':b['scope'],'thread':'',
        'message_id':'om_'+'f'*32,'is_bot':False,'text':'Retained private source.'}
    key=inbox.admit(policy,'feishu',event,{'text':'Retained private source.'})
    report=unresolved(inbox)
    assert report['ingress'][0]['ingress_id']==key and report['ingress'][0]['message_id']==event['message_id']
    assert len([x for x in report['native_outgoing'] if 'part' in x])==4
