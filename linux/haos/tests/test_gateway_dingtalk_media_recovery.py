"""Exact offline multipart decisions with real SQLite; no delivery or UID mocks."""
import json
import sqlite3
import time
from types import SimpleNamespace
import pytest
from haos.gateway import Conflict,digest
from haos.gateway_dingtalk import PreparedDingTalkPolicy
from haos.gateway_dingtalk_delivery import Publisher
from haos.gateway_dingtalk_media_delivery import MediaPublisher
from haos.gateway_dingtalk_media_recovery import outgoing,approve_retry,TABLES
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_dingtalk import account,binding


@pytest.fixture
def ledger(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.db',Redactor())
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='dingtalk',inbox=inbox),_haos_dingtalk_value={**account(),'reply_mode':'robot'})
    publisher=Publisher(adapter);adapter._haos_dingtalk_publisher=publisher;media=MediaPublisher(adapter);now=time.time()
    for table in TABLES.values():
        for part in (0,1):inbox.db.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('a'*64,part,1,'dingtalk',media.scope,'b'*64,'uncertain','','','',now,now))
    b={**binding(),'allow_outbound_media':True}
    policy=PreparedDingTalkPolicy({'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[b]})
    yield inbox,policy
    inbox.close()


def request(inbox,operation='upload',part=0):
    item=next(x for x in outgoing(inbox) if x['operation']==operation and x['part']==part)
    return {'connector':'dingtalk','delivery_id':item['delivery_id'],'operation':operation,'part':part,'attempt':1,
        'snapshot_sha256':item['snapshot_sha256'],'owner_uid':1000,'note_sha256':'c'*64,'confirmed':True,'confirmed_not_accepted':True}


@pytest.mark.parametrize('operation',['upload','reply'])
def test_only_selected_part_and_operation_released_with_durable_idempotent_audit(ledger,operation):
    inbox,policy=ledger;decision=request(inbox,operation);result=approve_retry(inbox,policy,decision)
    assert result['network_requested'] is False and result['controller_reconciliation_still_required'] is True
    items=outgoing(inbox);assert sum(x['state']=='owner-retry-approved' for x in items)==1
    assert next(x for x in items if x['operation']==operation and x['part']==0)['state']=='owner-retry-approved'
    assert approve_retry(inbox,policy,decision)==result
    assert inbox.db.execute('SELECT COUNT(*) FROM dingtalk_media_owner_events').fetchone()[0]==1
    with pytest.raises(Conflict):approve_retry(inbox,policy,{**decision,'note_sha256':'e'*64})


@pytest.mark.parametrize('change',[{'part':True},{'part':8},{'operation':'delete'},{'operation':[]},
    {'confirmed_not_accepted':1},{'confirmed':False},{'owner_uid':True},{'attempt':5},
    {'snapshot_sha256':'d'*64},{'part':1},{'operation':'reply'},{'connector':'unknown'},{'extra':'unsafe'}])
def test_ambiguous_or_stale_cross_part_decisions_never_release_an_intent(ledger,change):
    inbox,policy=ledger
    # Make each row distinguishable even when the fixture clock is identical.
    inbox.db.execute('UPDATE dingtalk_media_reply_intents SET fingerprint=?',('f'*64,))
    with pytest.raises((PermissionError,Conflict)):approve_retry(inbox,policy,{**request(inbox),**change})
    assert all(x['state']=='uncertain' for x in outgoing(inbox))


@pytest.mark.parametrize('operation',['upload','reply'])
def test_confirmed_acceptance_is_private_and_cannot_be_released(ledger,operation):
    inbox,policy=ledger;table=TABLES[operation]
    receipt=({'state':'confirmed','kind':'file','media_id':'$private_fixture_upload_acceptance','created_at':int(time.time()*1000)} if operation=='upload'
        else {'state':'confirmed','acceptance_id':'haos-dingtalk-'+'e'*64,'remote_message_id':None,'recipient_read_verified':False})
    encoded=json.dumps(receipt,sort_keys=True,separators=(',',':'))
    inbox.db.execute(f"UPDATE {table} SET state='confirmed',receipt=?,receipt_sha256=? WHERE part=0",(encoded,digest(['b'*64,encoded])))
    assert '$private_fixture_upload_acceptance' not in json.dumps(outgoing(inbox))
    decision=request(inbox,operation)
    with pytest.raises(PermissionError):approve_retry(inbox,policy,decision)
    inbox.db.execute(f'UPDATE {table} SET receipt_sha256=? WHERE part=0',('f'*64,))
    with pytest.raises(Conflict):outgoing(inbox)


def test_audit_failure_rolls_back_the_selected_release_and_requires_current_output_grant(ledger):
    inbox,policy=ledger;decision=request(inbox)
    config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[binding()]}
    with pytest.raises(PermissionError):approve_retry(inbox,PreparedDingTalkPolicy(config),decision)
    approve_retry(inbox,policy,request(inbox,'reply',1))
    inbox.db.execute("CREATE TRIGGER failed_part_audit BEFORE INSERT ON dingtalk_media_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError):approve_retry(inbox,policy,decision)
    assert next(x for x in outgoing(inbox) if x['operation']=='upload' and x['part']==0)['state']=='uncertain'
    assert inbox.db.execute('SELECT COUNT(*) FROM dingtalk_media_owner_events').fetchone()[0]==1


def test_native_owner_inventory_accepts_exact_dingtalk_message_id_without_optional_runtime(ledger):
    from haos.gateway_raw_recovery import unresolved
    inbox,policy=ledger;b=policy.bindings['owner']
    event={'platform':'dingtalk','sender':b['sender'],'chat':b['chat'],'scope':b['scope'],'thread':'',
        'message_id':'native-canonical-message','is_bot':False,'text':'Retained private source.'}
    key=inbox.admit(policy,'dingtalk',event,{'text':'Retained private source.'})
    report=unresolved(inbox)
    assert report['ingress'][0]['ingress_id']==key and report['ingress'][0]['message_id']==event['message_id']
    assert len([x for x in report['native_outgoing'] if 'part' in x])==4


@pytest.mark.parametrize('caption',['','Approved caption.'])
def test_batch_receipt_is_recovered_only_when_every_required_native_acceptance_is_committed(ledger,caption):
    from haos.gateway_dingtalk_media_recovery import batches
    inbox,policy=ledger;db=inbox.db;credential_scope=db.execute('SELECT credential_scope FROM dingtalk_upload_intents').fetchone()[0]
    def item(index,kind):return {'id':str(index+1)*64,'kind':kind,'name':'result-'+str(index)+'.'+('png' if kind=='image' else 'zip'),
        'size':100,'sha256':'e'*64,'mime':'image/png' if kind=='image' else 'application/zip',
        'duration_ms':0,'width':0,'height':0,'cover':None}
    manifest={'text':caption,'items':[item(0,'image'),item(1,'file')]};fingerprint='f'*64
    db.execute('INSERT INTO dingtalk_output_manifests VALUES(?,?,?,?,?,?,?,?,?)',
        ('a'*64,'dingtalk',credential_scope,'owner',digest(policy.bindings['owner']),'c'*64,fingerprint,
            json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False),time.time()))
    receipts=[]
    for part,kind in [(0,'image'),(1,'file')]:
        for operation,table in TABLES.items():
            result=({'state':'confirmed','kind':kind,'media_id':'private-upload-'+str(part),'created_at':123}
                if operation=='upload' else {'state':'confirmed','acceptance_id':'haos-dingtalk-'+str(part+1)*64,
                    'remote_message_id':None,'recipient_read_verified':False})
            encoded=json.dumps(result,sort_keys=True,separators=(',',':'))
            db.execute(f"UPDATE {table} SET state='confirmed',receipt=?,receipt_sha256=? WHERE part=?",
                (encoded,digest(['b'*64,encoded]),part))
            if operation=='reply':receipts.append(result['acceptance_id'])
    caption_receipt=None
    if caption:
        assert batches(inbox)[0]['native_acceptance_receipt'] is None
        caption_receipt='haos-dingtalk-'+'3'*64;now=time.time()
        db.execute('INSERT INTO dingtalk_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
            ('a'*64,1,'dingtalk',credential_scope,'b'*64,'confirmed',caption_receipt,'',now,now))
    expected='haos-dingtalk-'+digest(['a'*64,fingerprint,caption_receipt,receipts])
    recovered=batches(inbox)[0]
    assert recovered['native_acceptance_receipt']==expected and recovered['state']=='confirmed'
    assert recovered['confirmed_parts']==2 and recovered['recipient_read_verified'] is False and recovered['remote_message_id'] is None
    # A final API message receipt is insufficient if the separate upload decision
    # never committed. Owner sees an incomplete batch, with no aggregate proof.
    db.execute("UPDATE dingtalk_upload_intents SET state='uncertain',receipt='',receipt_sha256='' WHERE part=1")
    incomplete=batches(inbox)[0]
    assert incomplete['native_acceptance_receipt'] is None and incomplete['state']=='incomplete' and incomplete['confirmed_parts']==1
    assert 'private-upload' not in str(incomplete)
    if caption:assert caption not in str(incomplete)
