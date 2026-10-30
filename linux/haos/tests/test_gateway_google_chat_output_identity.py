"""Actual legacy SQLite/output custody across key rotation; no SDK or wire calls."""
import pytest

from haos.gateway import Conflict
from haos.gateway_google_chat import scope
from haos.gateway_google_chat_file_recovery import outputs,purge
from haos.gateway_google_chat_output_identity import owner,retain
from test_gateway_google_chat_file_recovery import recovery


def args(row):return {'id':row['id'],'snapshot_sha256':row['snapshot_sha256'],'owner_uid':1000,'note_sha256':'a'*64,'confirmed':True}


def retained(rig):
    inbox,ledger,operation,proof,policy,account,originals=rig
    return inbox.db.execute('SELECT * FROM google_chat_output_files WHERE id=?',(proof['file_id'],)).fetchone()


def test_key_rotation_keeps_original_output_app_ownership_and_explicit_withdrawn_snapshot_purge_is_idempotent(recovery):
    inbox,_,_,proof,policy,account,_=recovery;row=retained(recovery);before=row['data'];original_owner=owner(inbox,row)
    account['service_account']['private_key_id']='b'*40;policy.bindings.clear()
    assert owner(inbox,row)==original_owner
    view=outputs(inbox,policy,'google',account,lambda:None)['outputs'][0]
    assert view['id']==row['id'] and view['purge_allowed'] and view['stored_bytes']==len(before)
    assert inbox.db.execute('SELECT data FROM google_chat_output_files').fetchone()[0]==before
    result=purge(inbox,policy,'google',account,args(view),lambda:None)
    assert result['tombstones_retained'] and not result['network_requested'] and not result['remote_deletion_verified']
    assert purge(inbox,policy,'google',account,args(view),lambda:None)==result
    assert tuple(inbox.db.execute('SELECT state,length(data) FROM google_chat_output_files').fetchone())==('purged',0)
    assert owner(inbox,retained(recovery))==original_owner


def test_legacy_native_file_proof_backfills_after_rotation_without_current_grant_or_fetching_any_root_bytes(recovery):
    inbox,_,_,_,policy,account,_=recovery;before=retained(recovery)['data']
    inbox.db.execute('DELETE FROM google_chat_output_owners');account['service_account']['private_key_id']='b'*40;policy.bindings.clear()
    assert owner(inbox,retained(recovery)) is None
    view=outputs(inbox,policy,'google',account,lambda:None)['outputs'][0]
    assert view['purge_allowed'] and owner(inbox,retained(recovery))['account_scope']==scope(account)
    assert retained(recovery)['data']==before


def test_legacy_output_without_native_file_proof_is_associated_only_by_exact_current_root_binding_and_credential(recovery):
    inbox,_,_,_,policy,account,_=recovery;before=retained(recovery)['data']
    inbox.db.execute('DELETE FROM google_chat_output_owners');inbox.db.execute('DELETE FROM google_chat_file_writes')
    assert outputs(inbox,policy,'google',account,lambda:None)['outputs'][0]['current_grant']
    assert owner(inbox,retained(recovery))['connector']=='google' and retained(recovery)['data']==before


def test_unproven_withdrawn_legacy_output_remains_unassociated_and_private_bytes_are_preserved(recovery):
    inbox,_,_,_,policy,account,_=recovery;before=retained(recovery)['data']
    inbox.db.execute('DELETE FROM google_chat_output_owners');inbox.db.execute('DELETE FROM google_chat_file_writes')
    account['service_account']['private_key_id']='b'*40;policy.bindings.clear()
    assert outputs(inbox,policy,'google',account,lambda:None)['outputs']==[]
    assert owner(inbox,retained(recovery)) is None and retained(recovery)['data']==before


@pytest.mark.parametrize('change',['connector','app'])
def test_same_credentials_or_binding_name_cannot_expose_or_purge_another_connector_or_app_output(recovery,change):
    inbox,_,_,_,policy,account,_=recovery;before=retained(recovery)['data'];policy.bindings.clear();connector='google'
    if change=='connector':connector='foreign'
    else:account['bot_user']='users/998'
    assert outputs(inbox,policy,connector,account,lambda:None)['outputs']==[]
    request={'id':retained(recovery)['id'],'snapshot_sha256':'f'*64,'owner_uid':1000,'note_sha256':'a'*64,'confirmed':True}
    with pytest.raises(PermissionError):purge(inbox,policy,connector,account,request,lambda:None)
    assert retained(recovery)['data']==before


@pytest.mark.parametrize('field,value',[('connector','foreign'),('account_scope','google-chat:'+'f'*64),('immutable_sha256','f'*64),('evidence_sha256','invalid')])
def test_changed_ownership_metadata_never_rebinds_or_deletes_retained_bytes(recovery,field,value):
    inbox,_,_,_,policy,account,_=recovery;row=retained(recovery);before=row['data']
    inbox.db.execute('UPDATE google_chat_output_owners SET '+field+'=?',(value,))
    with pytest.raises(Conflict):owner(inbox,row)
    with pytest.raises(Conflict):retain(inbox,row,'google',scope(account),'a'*64)
    assert retained(recovery)['data']==before


def test_active_original_grant_blocks_purge_even_after_account_key_rotation(recovery):
    inbox,_,_,_,policy,account,_=recovery;before=retained(recovery)['data'];account['service_account']['private_key_id']='b'*40
    view=outputs(inbox,policy,'google',account,lambda:None)['outputs'][0];assert view['current_grant'] and not view['purge_allowed']
    with pytest.raises(PermissionError):purge(inbox,policy,'google',account,args(view),lambda:None)
    assert retained(recovery)['data']==before


def test_historical_output_inventory_and_explicit_local_purge_need_only_public_identity_and_return_no_bytes(recovery):
    from haos.gateway_google_chat_identity import descriptor
    from haos.gateway_google_chat_file_recovery import outputs_identity,purge_identity
    from haos.google_chat_retired_process import response
    from test_google_chat_retired_process import selected
    inbox,_,_,_,policy,account,_=recovery;identity=descriptor(account);before=retained(recovery)['data']
    view=outputs_identity(inbox,None,identity,lambda:None)
    assert len(view['outputs'])==1 and view['outputs'][0]['purge_allowed']
    value={'account':selected(),'result':view,'active_authorization_returned':False}
    assert response(value,'outputs')==value
    import json
    assert before.decode() not in json.dumps(value)
    item=view['outputs'][0];request={**args(item),'connector':item['connector'],'ownership_sha256':item['ownership_sha256']}
    result=purge_identity(inbox,None,identity,request,lambda:None)
    assert purge_identity(inbox,None,identity,request,lambda:None)==result
    assert retained(recovery)['data']==b'' and not result['remote_deletion_verified']


@pytest.mark.parametrize('case',['scope','connector','ownership','stale-bytes','active-grant'])
def test_historical_output_wrong_app_route_changed_metadata_or_active_grant_cannot_delete_bytes(recovery,case):
    from haos.gateway_google_chat_identity import descriptor
    from haos.gateway_google_chat_file_recovery import outputs_identity,purge_identity
    inbox,_,_,_,policy,account,_=recovery;identity=descriptor(account);before=retained(recovery)['data']
    item=outputs_identity(inbox,None,identity,lambda:None)['outputs'][0]
    request={**args(item),'connector':item['connector'],'ownership_sha256':item['ownership_sha256']};selected_policy=None
    if case=='scope':identity['bot_user']='users/998'
    elif case=='connector':request['connector']='foreign'
    elif case=='ownership':request['ownership_sha256']='f'*64
    elif case=='stale-bytes':inbox.db.execute("UPDATE google_chat_output_files SET data=x'00'")
    else:
        selected_policy=policy;item=outputs_identity(inbox,policy,identity,lambda:None)['outputs'][0]
        request.update(snapshot_sha256=item['snapshot_sha256'])
    with pytest.raises((PermissionError,Conflict)):purge_identity(inbox,selected_policy,identity,request,lambda:None)
    assert retained(recovery)['data']==(b'\x00' if case=='stale-bytes' else before)


def test_historical_output_failed_owner_audit_commit_rolls_back_byte_disposal(recovery):
    from haos.gateway_google_chat_identity import descriptor
    from haos.gateway_google_chat_file_recovery import outputs_identity,purge_identity
    import sqlite3
    inbox,_,_,_,_,account,_=recovery;identity=descriptor(account);before=retained(recovery)['data']
    item=outputs_identity(inbox,None,identity,lambda:None)['outputs'][0]
    request={**args(item),'connector':item['connector'],'ownership_sha256':item['ownership_sha256']}
    inbox.db.execute('CREATE TABLE google_chat_output_owner_events(id TEXT PRIMARY KEY,output_id TEXT NOT NULL,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)')
    inbox.db.execute("CREATE TRIGGER fail_historical_audit BEFORE INSERT ON google_chat_output_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError):purge_identity(inbox,None,identity,request,lambda:None)
    assert retained(recovery)['data']==before and retained(recovery)['state']=='retained' and not inbox.db.in_transaction
