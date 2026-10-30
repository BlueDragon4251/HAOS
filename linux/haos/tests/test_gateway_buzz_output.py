"""Real SQLite custody rejects removed bytes, stale accounts and unfinished uploads."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from haos.gateway import Conflict,digest
from haos.gateway_buzz import PreparedBuzzPolicy,scope
from haos.gateway_buzz_output import Output
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def retained(tmp_path):
    value={'private_key':'1'*64,'public_key':'2'*64,'relay_url':'https://buzz.fixture.invalid',
        'channels':['01234567-89ab-4cde-8012-3456789abcde']}
    binding={'id':'owner','connector':'buzz','sender':'3'*64,'chat':value['channels'][0],'scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1,'allow_outbound_media':True}
    config={'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':[binding]}
    policy=lambda:PreparedBuzzPolicy(config)
    native=NativeInbox(tmp_path/'native.db',Redactor([value['private_key']]))
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=native,policy=policy,connector='buzz'),
        _haos_buzz_value=value,_haos_buzz_check=lambda:None)
    output=Output(adapter);delivery={'id':'a'*64,'binding_id':'owner','binding_digest':digest(binding)}
    data=b'%PDF-1.7\nRetained fixture bytes';sha=hashlib.sha256(data).hexdigest()
    item={'url':value['relay_url']+'/media/'+sha+'.pdf','sha256':sha,'size':len(data),'type':'application/pdf','uploaded':1793332800}
    native.db.execute('INSERT INTO buzz_output_uploads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        ('b'*64,delivery['id'],'c'*64,digest(binding),digest(value),'result-0.pdf',sha,'ready',
            json.dumps(item,sort_keys=True,separators=(',',':')),data,data,1793332800))
    try:yield output,delivery,config,adapter
    finally:native.close()


def test_retained_exact_blob_is_reused_without_network_or_native_optional_import(retained):
    output,delivery,_,_=retained
    assert output.resolve(delivery,['b'*64])[0]['name']=='result-0.pdf'
    assert output.db.execute('SELECT COUNT(*) FROM buzz_output_uploads').fetchone()[0]==1


@pytest.mark.parametrize('change',[
    "UPDATE buzz_output_uploads SET source=x'00'",
    "UPDATE buzz_output_uploads SET stored=x'00'",
    "UPDATE buzz_output_uploads SET descriptor='{}'",
    "UPDATE buzz_output_uploads SET state='uploading'",
    "UPDATE buzz_output_uploads SET credential_scope='old-account'",
    'DELETE FROM buzz_output_uploads'])
def test_restart_never_refetches_reuploads_or_restores_corrupt_or_unresolved_custody(retained,change):
    output,delivery,_,_=retained;output.db.execute(change)
    with pytest.raises(Conflict):output.resolve(delivery,['b'*64])


def test_changed_owner_epoch_or_rotated_private_account_cannot_reuse_old_attachment(retained):
    output,delivery,config,adapter=retained
    adapter._haos_buzz_value={**adapter._haos_buzz_value,'private_key':'4'*64}
    with pytest.raises(Conflict):output.resolve(delivery,['b'*64])
    config['bindings'][0]['generation']='d'*64
    with pytest.raises(PermissionError):output.resolve(delivery,['b'*64])


def decision(output,policy,action='retry-upload'):
    from haos.gateway_buzz_output_recovery import inventory
    snapshot=inventory(output.adapter._haos_native.inbox,policy)['outputs'][0]['snapshot_sha256']
    return {'id':'b'*64,'action':action,'snapshot_sha256':snapshot,'owner_uid':1000,'note_sha256':'d'*64,'confirmed':True}


def unfinished(output):output.db.execute("UPDATE buzz_output_uploads SET state='uploading',descriptor='',stored=x''")


def test_offline_owner_retry_is_snapshot_bound_idempotent_and_consumable_once_without_publication(retained):
    from haos.gateway_buzz_output_recovery import decide
    output,delivery,_,adapter=retained;unfinished(output);policy=adapter._haos_native.policy();request=decision(output,policy)
    first=decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)
    assert first['network_requested'] is False and first['message_sent'] is False
    assert decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)==first
    with pytest.raises(Conflict):output.resolve(delivery,['b'*64])
    assert output.retained('b'*64,delivery,retry=True) is None
    output.db.execute("UPDATE buzz_output_uploads SET state='uploading'")
    assert decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)==first
    with pytest.raises(Conflict):output.retained('b'*64,delivery,retry=True)


@pytest.mark.parametrize('change',[{'snapshot_sha256':'0'*64},{'confirmed':False},{'owner_uid':True},{'action':'send'},
    {'action':[]},{'extra':'private-command'}])
def test_upload_decision_rejects_stale_or_implicit_or_untyped_authority(retained,change):
    from haos.gateway_buzz_output_recovery import decide
    output,_,_,adapter=retained;unfinished(output);policy=adapter._haos_native.policy()
    with pytest.raises((PermissionError,Conflict)):
        decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,{**decision(output,policy),**change})
    assert output.db.execute('SELECT state FROM buzz_output_uploads').fetchone()[0]=='uploading'


def test_upload_recovery_never_replaces_an_already_signed_native_reply(retained):
    from haos.gateway_buzz_output_recovery import decide
    output,delivery,_,adapter=retained;unfinished(output);policy=adapter._haos_native.policy()
    output.db.execute('CREATE TABLE buzz_delivery_intents(delivery_id TEXT,signed_raw BLOB)')
    output.db.execute('INSERT INTO buzz_delivery_intents VALUES(?,?)',(delivery['id'],b'retained original'))
    with pytest.raises(PermissionError):decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,decision(output,policy))


def test_retry_state_without_retained_owner_decision_does_not_authorize_network(retained):
    output,delivery,_,_=retained;unfinished(output)
    output.db.execute("UPDATE buzz_output_uploads SET state='retry-approved'")
    with pytest.raises(Conflict):output.retained('b'*64,delivery,retry=True)


def test_each_new_inspected_upload_retry_advances_snapshot_and_enforces_total_budget(retained):
    from haos.gateway_buzz_output_recovery import decide
    output,_,_,adapter=retained;unfinished(output);policy=adapter._haos_native.policy();snapshots=[]
    for _ in range(2):
        request=decision(output,policy);snapshots.append(request['snapshot_sha256'])
        decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)
        output.db.execute("UPDATE buzz_output_uploads SET state='uploading'")
    assert len(set(snapshots))==2
    with pytest.raises(PermissionError):decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,decision(output,policy))


def test_upload_disposal_requires_grant_withdrawal_and_retains_inspected_tombstone(retained):
    from haos.gateway_buzz_output_recovery import decide,inventory
    output,_,config,adapter=retained;policy=adapter._haos_native.policy()
    with pytest.raises(PermissionError):decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,decision(output,policy,'purge-upload'))
    config['bindings']=[];policy=adapter._haos_native.policy();request=decision(output,policy,'purge-upload')
    first=decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)
    assert decide(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)==first
    view=inventory(adapter._haos_native.inbox,policy)['outputs'][0]
    assert view['state']=='purged' and view['source_bytes']==view['stored_bytes']==0
    assert first['tombstones_retained'] is True and first['network_requested'] is False


def test_inspected_auth_recheck_clears_only_saved_account_blocks_and_preserves_rate_deadline(retained):
    from haos.gateway_buzz_recovery import retry_auth,transport
    import time
    output,_,_,adapter=retained;db=output.db;policy=adapter._haos_native.policy();deadline=time.time()+3600
    account=digest(['buzz',adapter._haos_buzz_value])
    db.execute('CREATE TABLE buzz_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
    for identity,scope,status in [('a',account,'authentication-refused'),('b',account,'identity-refused'),
            ('c','e'*64,'authentication-refused'),('d',account,'rate-limited')]:
        db.execute('INSERT INTO buzz_profile_status VALUES(?,?,?,?,?,?)',(identity,'buzz',scope,status,123,deadline))
    request={'connector':'buzz','owner_uid':1000,'note_sha256':'f'*64,'confirmed':True}
    result=retry_auth(adapter._haos_native.inbox,policy,adapter._haos_buzz_value,request)
    assert result['authentication_blocks_cleared']==2 and result['network_requested'] is False and result['message_sent'] is False
    assert [row[0] for row in db.execute('SELECT status FROM buzz_profile_status ORDER BY identity')]==[
        'created','created','authentication-refused','rate-limited']
    assert all(row[0]==deadline for row in db.execute('SELECT next_attempt FROM buzz_profile_status'))
    assert len(transport(adapter._haos_native.inbox))==4
    assert db.execute('SELECT owner_uid,changed FROM buzz_auth_owner_events').fetchone()[:]==(1000,2)
