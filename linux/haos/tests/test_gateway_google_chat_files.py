"""Real private FULL file-write ledger; no Google auth or inference fixtures."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import sqlite3

import pytest

from haos.gateway import Conflict,digest
from haos.gateway_google_chat_files import FileLedger
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,event
from haos.gateway_google_chat import scope


@pytest.fixture
def ledger(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.sqlite',Redactor([]));writes=FileLedger(inbox)
    proof={'connector':'google','credential_scope':digest(account()),'account_scope':scope(account()),'binding_id':'owner','binding_digest':'a'*64,'chat':'spaces/space1',
        'thread':'spaces/space1/threads/thread1','subject':'users/123','token_id':'b'*64,'client_sha256':'c'*64,
        'source':{'delivery_id':'d'*64,'source_key':'e'*64,'source_id':'spaces/space1/messages/source','source_sha256':'f'*64,'context_sha256':'1'*64,'content_sha256':'2'*64},
        'file_id':'3'*64,'file_sha256':'4'*64,'filename':'result-0.pdf','mime':'application/pdf','caption':'Approved report'}
    try:yield writes,'5'*64,proof,tmp_path/'native.sqlite'
    finally:inbox.close()


def uploaded(writes,identity,proof):
    assert writes.uploading(identity,proof) is None
    return writes.uploaded(identity,proof,{'attachmentUploadToken':'local-private-upload-reference-fixture'})


def accepted(writes,identity,proof):
    row=writes.get(identity,proof);name=proof['chat']+'/messages/server-accepted'
    return {'name':name,'clientAssignedMessageId':row['client_id'],'text':proof['caption'],'thread':{'name':proof['thread']},
        'sender':{'name':proof['subject'],'type':'HUMAN'},'attachment':[{'name':name+'/attachments/file1','contentName':proof['filename'],
            'contentType':proof['mime'],'source':'UPLOADED_CONTENT'}]}


def test_upload_and_create_intents_commit_FULL_before_wire_and_existing_uploaded_reference_reuses_without_reupload(ledger):
    writes,identity,proof,path=ledger;row=writes.get(identity,proof)
    assert row['state']=='prepared' and row['upload_state']=='not-started' and writes.db.execute('PRAGMA synchronous').fetchone()[0]==2
    assert writes.uploading(identity,proof) is None
    with sqlite3.connect(path) as other:assert other.execute('SELECT upload_state FROM google_chat_file_writes').fetchone()[0]=='uploading'
    with pytest.raises(Conflict):writes.uploading(identity,proof)
    ref={'attachmentUploadToken':'local-private-upload-reference-fixture'};assert writes.uploaded(identity,proof,ref)==ref
    assert writes.uploading(identity,proof)==ref
    writing=writes.writing(identity,proof)
    with sqlite3.connect(path) as other:assert other.execute('SELECT state FROM google_chat_file_writes').fetchone()[0]=='writing'
    with pytest.raises(Conflict):writes.writing(identity,proof)
    assert writing['client_id']==row['client_id'] and writing['request_id']==row['request_id']
    receipt=writes.confirm(identity,proof,accepted(writes,identity,proof));assert receipt=='spaces/space1/messages/server-accepted'
    assert writes.get(identity,proof)['receipt']==receipt


@pytest.mark.parametrize('field,change',[
    ('subject','users/124'),('thread','spaces/space1/threads/different'),('caption','Changed report'),('token_id','6'*64),
    ('client_sha256','7'*64),('file_sha256','8'*64),('credential_scope','9'*64),('filename','result-1.pdf'),
    ('mime','text/plain'),('binding_digest','0'*64),('source',{'delivery_id':'a'*64})])
def test_existing_operation_cannot_borrow_other_user_file_body_account_source_context_or_owner_epoch(ledger,field,change):
    writes,identity,proof,_=ledger;writes.get(identity,proof);proof[field]=change
    with pytest.raises((PermissionError,Conflict)):writes.get(identity,proof)
    assert writes.db.execute('SELECT upload_state FROM google_chat_file_writes').fetchone()[0]=='not-started'


@pytest.mark.parametrize('path,change',[
    (['clientAssignedMessageId'],'client-foreign'),(['sender','name'],'users/124'),(['sender','type'],'BOT'),
    (['text'],'different'),(['thread','name'],'spaces/space1/threads/foreign'),(['attachment',0,'contentName'],'different.pdf'),
    (['attachment',0,'contentType'],'text/plain'),(['attachment',0,'source'],'DRIVE_FILE'),
    (['attachment',0,'name'],'spaces/foreign/messages/other/attachments/file1')])
def test_file_confirmation_requires_exact_principal_client_ID_thread_caption_and_uploaded_attachment_receipt(ledger,path,change):
    writes,identity,proof,_=ledger;uploaded(writes,identity,proof);writes.writing(identity,proof);response=accepted(writes,identity,proof)
    current=response
    for part in path[:-1]:current=current[part]
    current[path[-1]]=change
    with pytest.raises((PermissionError,ValueError,Conflict)):writes.confirm(identity,proof,response)
    assert writes.get(identity,proof)['state']=='writing' and not writes.get(identity,proof)['receipt']


def callback(writes,identity,proof,*,client=True):
    data=event();response=accepted(writes,identity,proof)
    response['createTime']=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    if not client:response.pop('clientAssignedMessageId')
    data['message']=response;return data


def test_human_user_authored_echo_is_refused_by_pre_wire_client_ID_even_before_remote_acceptance_returns(ledger):
    writes,identity,proof,_=ledger;uploaded(writes,identity,proof);writes.writing(identity,proof)
    raw=json.dumps(callback(writes,identity,proof)).encode()
    assert writes.own_message('google',account(),raw)
    assert writes.get(identity,proof)['state']=='writing'
    writes.confirm(identity,proof,accepted(writes,identity,proof))
    assert writes.own_message('google',account(),json.dumps(callback(writes,identity,proof,client=False)).encode())
    assert not writes.own_message('another',account(),raw)
    rotated=account();rotated['service_account']['private_key_id']='b'*40
    assert writes.own_message('google',rotated,raw)
    rotated['bot_user']='users/998';assert not writes.own_message('google',rotated,raw)


def test_projection_without_client_ID_is_blocked_only_for_exact_pending_user_file_caption_thread_shape(ledger):
    writes,identity,proof,_=ledger;uploaded(writes,identity,proof);writes.writing(identity,proof)
    data=callback(writes,identity,proof,client=False)
    assert writes.own_message('google',account(),json.dumps(data).encode())
    for changed in [lambda m:m.update(text='A separate human command'),lambda m:m.update(sender={'name':'users/124','type':'HUMAN'}),
            lambda m:m.update(attachment=[]),lambda m:m.update(thread={'name':'spaces/space1/threads/other'})]:
        value=deepcopy(data);changed(value['message']);assert not writes.own_message('google',account(),json.dumps(value).encode())
    ordinary=event();ordinary['message']['text']='A separate human command'
    assert not writes.own_message('google',account(),json.dumps(ordinary).encode())


@pytest.mark.parametrize('reference',[{},[],{'url':'https://foreign.invalid/private'},{'attachmentUploadToken':'invalid\nreference'},
    {'attachmentUploadToken':'x'*8193}])
def test_upload_acceptance_never_adds_unreviewed_capability_fields_or_unbounded_references(ledger,reference):
    writes,identity,proof,_=ledger;writes.uploading(identity,proof)
    with pytest.raises(Conflict):writes.uploaded(identity,proof,reference)
    assert writes.get(identity,proof)['upload_state']=='uploading'
