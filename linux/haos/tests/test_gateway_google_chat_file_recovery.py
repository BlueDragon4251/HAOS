"""Offline actual SQLite/source/output recovery; no SDK or transport authority."""
from copy import deepcopy
import hashlib
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from haos.gateway import Conflict,digest
from haos.gateway_google_chat_files import FileLedger
from haos.gateway_google_chat_output import Output
from haos.gateway_google_chat_custody import Originals
from haos.gateway_google_chat_file_recovery import inventory,decide,outputs,purge
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,event,policy,admitted
from test_gateway_google_chat_files import accepted,uploaded


@pytest.fixture
def recovery(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.sqlite',Redactor([]));originals=Originals(tmp_path/'originals.sqlite',inbox.redactor)
    selected=policy(allow_outbound_media=True);binding=selected.bindings['owner'];value=account();data=event();raw=json.dumps(data).encode()
    raw_id=originals.retain(selected,'google',value,raw,lambda:None);proof=admitted(data,selected)
    envelope={**proof['envelope'],'text':'/status'};source_key=inbox.admit(selected,'google',envelope,{'raw_id':raw_id})
    assert inbox.claim(source_key,selected);inbox.complete(source_key,True)
    inbox.db.execute('CREATE TABLE google_chat_native_projection(source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,raw_sha256 TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,envelope_sha256 TEXT NOT NULL)')
    inbox.db.execute('INSERT INTO google_chat_native_projection VALUES(?,?,?,?,?,?)',
        (source_key,raw_id,proof['raw_sha256'],digest(binding),digest(['google',value]),digest(envelope)))
    originals.admitted(raw_id,digest(['google',*(envelope[k] for k in ['scope','chat','thread','message_id'])]),selected,'google',value,lambda:None)
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=inbox,policy=lambda:selected,connector='google'),_haos_google_value=value,_haos_google_check=lambda:None)
    Output(adapter);blob=b'%PDF-1.7\nprivate retained result fixture';delivery='d'*64;offer={'id':'c'*64,'size':len(blob),'sha256':hashlib.sha256(blob).hexdigest()};fid=digest([delivery,offer['id']])
    inbox.db.execute('INSERT INTO google_chat_output_files VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (fid,delivery,'owner',digest(binding),digest(value),offer['id'],offer['size'],digest(offer),offer['sha256'],'result-0.pdf','application/pdf',blob,'retained',time.time()))
    file_proof={'connector':'google','account_scope':binding['scope'],'credential_scope':digest(value),'binding_id':'owner','binding_digest':digest(binding),
        'chat':binding['chat'],'thread':binding['thread'],'subject':binding['sender'],'token_id':'b'*64,'client_sha256':'c'*64,
        'source':{'delivery_id':delivery,'source_key':source_key,'source_id':envelope['message_id'],'source_sha256':proof['raw_sha256'],'context_sha256':'e'*64,'content_sha256':'f'*64},
        'file_id':fid,'file_sha256':offer['sha256'],'filename':'result-0.pdf','mime':'application/pdf','caption':'Private caption fixture'}
    ledger=FileLedger(inbox);identity='5'*64;ledger.get(identity,file_proof)
    try:yield inbox,ledger,identity,file_proof,selected,value,originals
    finally:originals.close();inbox.close()


def status(rig):
    inbox,_,_,_,selected,value,originals=rig
    return inventory(inbox,selected,'google',value,lambda:None,originals=originals)['files'][0]


def request(row,action='retry-upload',**changes):return {'id':row['id'],'action':action,'snapshot_sha256':row['snapshot_sha256'],'owner_uid':1000,
    'note_sha256':'a'*64,'confirmed':True,'confirmed_not_delivered':action=='retry-file',**changes}


def decision(rig,params):
    inbox,_,_,_,selected,value,originals=rig
    return decide(inbox,selected,'google',value,params,lambda:None,originals=originals)


def test_snapshot_hides_caption_bytes_and_upload_capability_and_upload_permission_consumes_before_any_new_attempt(recovery):
    inbox,ledger,identity,proof,_,_,_=recovery;ledger.uploading(identity,proof)
    row=status(recovery);assert row['current_grant'] and row['current_account'] and row['source_projection_available'] and row['output_available'] and row['upload_retry_allowed']
    assert 'Private caption fixture' not in json.dumps(row) and not row['private_bytes_returned']
    params=request(row);result=decision(recovery,params);assert result['approval_recorded'] and not result['network_requested'] and not result['message_sent']
    assert decision(recovery,params)==result
    assert ledger.get(identity,proof)['upload_state']=='retry-approved'
    assert ledger.uploading(identity,proof) is None
    assert inbox.db.execute("SELECT state FROM google_chat_file_owner_events WHERE action='retry-upload'").fetchone()[0]=='consumed'
    assert decision(recovery,params)==result and ledger.get(identity,proof)['upload_state']=='uploading'
    with pytest.raises(Conflict):ledger.uploading(identity,proof)
    ledger.uploaded(identity,proof,{'attachmentUploadToken':'private-reference-fixture'})
    assert inbox.db.execute("SELECT state FROM google_chat_file_owner_events").fetchone()[0]=='confirmed'
    assert 'private-reference-fixture' not in json.dumps(status(recovery))


@pytest.mark.parametrize('change',[{'confirmed':False},{'confirmed_not_delivered':True},{'snapshot_sha256':'0'*64},
    {'owner_uid':True},{'note_sha256':'bad'},{'action':'send'},{'extra':'private-command'}])
def test_bad_or_stale_owner_decisions_never_release_an_upload(recovery,change):
    _,ledger,identity,proof,_,_,_=recovery;ledger.uploading(identity,proof)
    with pytest.raises((PermissionError,Conflict)):decision(recovery,request(status(recovery),**change))
    assert ledger.get(identity,proof)['upload_state']=='uploading' and ledger.get(identity,proof)['upload_retry_generation']==0


@pytest.mark.parametrize('case',['grant','source-row','source-bytes','source-receipt','output-bytes','account'])
def test_current_source_output_and_account_are_independent_requirements_for_any_retry(recovery,case):
    inbox,ledger,identity,proof,selected,value,originals=recovery;ledger.uploading(identity,proof)
    if case=='grant':selected.bindings.clear()
    elif case=='source-row':inbox.db.execute('DELETE FROM google_chat_native_projection')
    elif case=='source-bytes':originals.db.execute("UPDATE google_chat_originals SET raw=x'00'")
    elif case=='source-receipt':originals.db.execute("UPDATE google_chat_originals SET admitted_receipt=''")
    elif case=='output-bytes':inbox.db.execute("UPDATE google_chat_output_files SET data=x'00'")
    else:value['service_account']['private_key_id']='b'*40
    row=status(recovery);assert not row['upload_retry_allowed']
    with pytest.raises(PermissionError):decision(recovery,request(row))


def test_each_fresh_upload_approval_advances_snapshot_and_enforces_two_attempt_budget(recovery):
    _,ledger,identity,proof,_,_,_=recovery;ledger.uploading(identity,proof);snapshots=[]
    for number in [1,2]:
        row=status(recovery);snapshots.append(row['snapshot_sha256']);result=decision(recovery,request(row,note_sha256=str(number)*64))
        assert result['generation']==number;ledger.uploading(identity,proof)
    assert len(set(snapshots))==2 and not status(recovery)['upload_retry_allowed']
    with pytest.raises(PermissionError):decision(recovery,request(status(recovery)))


def test_message_permission_consumes_before_read_and_cannot_rearm_after_interruption_or_serialization(recovery):
    inbox,ledger,identity,proof,_,_,_=recovery;uploaded(ledger,identity,proof);ledger.writing(identity,proof)
    row=status(recovery);assert row['file_retry_allowed'];params=request(row,'retry-file');result=decision(recovery,params)
    permission=ledger.lookup(identity,proof)
    assert ledger.get(identity,proof)['state']=='writing'
    assert inbox.db.execute("SELECT state FROM google_chat_file_owner_events WHERE action='retry-file'").fetchone()[0]=='reconciling'
    assert decision(recovery,params)==result
    with pytest.raises(Conflict):ledger.lookup(identity,proof)
    with pytest.raises(Conflict):FileLedger(inbox).writing(identity,proof,lookup=permission)
    with pytest.raises(Conflict):ledger.writing(identity,proof,lookup={'identity':identity,'generation':1})
    # Only this live attempt may proceed after its actual own-ID GET404.
    ledger.writing(identity,proof,lookup=permission)
    assert permission.used and inbox.db.execute("SELECT state FROM google_chat_file_owner_events").fetchone()[0]=='consumed'
    with pytest.raises(Conflict):ledger.writing(identity,proof,lookup=permission)
    ledger.confirm(identity,proof,accepted(ledger,identity,proof))
    assert inbox.db.execute("SELECT state FROM google_chat_file_owner_events").fetchone()[0]=='confirmed' and not status(recovery)['file_retry_allowed']


def test_late_acceptance_closes_an_owner_lookup_without_republishing_or_changing_ids(recovery):
    inbox,ledger,identity,proof,_,_,_=recovery;uploaded(ledger,identity,proof);before=ledger.writing(identity,proof)
    decision(recovery,request(status(recovery),'retry-file'));permission=ledger.lookup(identity,proof)
    ledger.confirm(identity,proof,accepted(ledger,identity,proof));after=ledger.get(identity,proof)
    assert after['client_id']==before['client_id'] and after['request_id']==before['request_id'] and after['state']=='confirmed'
    assert inbox.db.execute('SELECT state FROM google_chat_file_owner_events').fetchone()[0]=='confirmed'
    with pytest.raises(Conflict):ledger.writing(identity,proof,lookup=permission)


def test_failed_owner_audit_rolls_back_permission_and_failed_acceptance_audit_preserves_uncertainty(recovery):
    inbox,ledger,identity,proof,_,_,_=recovery;ledger.uploading(identity,proof)
    inbox.db.execute("CREATE TRIGGER fail_permission BEFORE INSERT ON google_chat_file_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
    with pytest.raises(sqlite3.IntegrityError):decision(recovery,request(status(recovery)))
    assert ledger.get(identity,proof)['upload_retry_generation']==0 and not inbox.db.in_transaction
    inbox.db.execute('DROP TRIGGER fail_permission');decision(recovery,request(status(recovery)));ledger.uploading(identity,proof)
    inbox.db.execute("CREATE TRIGGER fail_acceptance BEFORE UPDATE ON google_chat_file_owner_events WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
    with pytest.raises(sqlite3.IntegrityError):ledger.uploaded(identity,proof,{'attachmentUploadToken':'private-reference-fixture'})
    assert ledger.get(identity,proof)['upload_state']=='uploading' and not ledger.get(identity,proof)['attachment_ref'] and not inbox.db.in_transaction


def test_output_disposal_requires_withdrawal_exact_snapshot_and_audit_then_keeps_tombstone_without_remote_claims(recovery):
    inbox,_,_,proof,selected,value,_=recovery;view=outputs(inbox,selected,'google',value,lambda:None)['outputs'][0]
    params={k:v for k,v in request(view).items() if k not in {'action','confirmed_not_delivered'}}
    with pytest.raises(PermissionError):purge(inbox,selected,'google',value,params,lambda:None)
    selected.bindings.clear();view=outputs(inbox,selected,'google',value,lambda:None)['outputs'][0];params['snapshot_sha256']=view['snapshot_sha256']
    result=purge(inbox,selected,'google',value,params,lambda:None)
    assert result['tombstones_retained'] and not result['remote_deletion_verified'] and not result['network_requested']
    assert purge(inbox,selected,'google',value,params,lambda:None)==result
    row=inbox.db.execute('SELECT state,data,sha256 FROM google_chat_output_files').fetchone()
    assert tuple(row)==('purged',b'',proof['file_sha256']) and outputs(inbox,selected,'google',value,lambda:None)['outputs'][0]['state']=='purged'


def test_four_fresh_file_permissions_have_distinct_snapshots_and_old_decisions_never_rearm(recovery):
    _,ledger,identity,proof,_,_,_=recovery;uploaded(ledger,identity,proof);ledger.writing(identity,proof);snapshots=[];old=[]
    for number in range(1,5):
        view=status(recovery);snapshots.append(view['snapshot_sha256']);params=request(view,'retry-file',note_sha256=str(number)*64)
        result=decision(recovery,params);old.append((params,result));ledger.lookup(identity,proof)
        for previous,receipt in old:assert decision(recovery,previous)==receipt
        assert ledger.get(identity,proof)['state']=='writing'
    assert len(set(snapshots))==4 and not status(recovery)['file_retry_allowed']
    with pytest.raises(PermissionError):decision(recovery,request(status(recovery),'retry-file'))


def test_pre_recovery_file_schema_migrates_without_discarding_pending_body_reference_receipt_or_identity(recovery):
    inbox,ledger,identity,proof,_,_,_=recovery;uploaded(ledger,identity,proof);ledger.writing(identity,proof)
    inbox.db.execute('ALTER TABLE google_chat_file_writes DROP COLUMN upload_retry_generation')
    old=tuple(inbox.db.execute('SELECT * FROM google_chat_file_writes').fetchone())
    migrated=FileLedger(inbox);new=tuple(inbox.db.execute('SELECT * FROM google_chat_file_writes').fetchone())
    assert new[:-1]==old and new[-1]==0 and migrated.get(identity,proof)['state']=='writing'


@pytest.mark.parametrize('kind,field,value',[
    ('files','attachment_ref','private-reference-must-not-render'),('files','caption','private-caption-must-not-render'),
    ('files','current_grant','yes'),('files','recipient_read_verified',True),('files','file_retry_allowed',True),
    ('outputs','data','private-bytes-must-not-render'),('outputs','remote_deletion_verified',True),('outputs','purge_allowed',True)])
def test_Root_file_response_rejects_extra_payloads_and_fabricated_authority_even_with_rehashed_snapshot(recovery,kind,field,value):
    from haos.google_chat_owner_process import response
    inbox,_,_,_,selected,account_value,originals=recovery
    item=(inventory(inbox,selected,'google',account_value,lambda:None,originals=originals) if kind=='files' else outputs(inbox,selected,'google',account_value,lambda:None))
    assert response(item,kind,'google')==item
    item=deepcopy(item);row=item[kind][0];row[field]=value;row['snapshot_sha256']=digest({k:v for k,v in row.items() if k!='snapshot_sha256'})
    with pytest.raises((ValueError,TypeError)):response(item,kind,'google')
