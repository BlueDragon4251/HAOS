import copy
import json
import sqlite3
import time

import pytest

from haos.gateway import GatewayPolicy, Conflict
from haos.gateway_raw import NativeInbox
from haos.gateway_setup import renewed_policy
from haos.redaction import Redactor


def policy():
    value={'version':1,'connectors':[{'id':'bot','platform':'discord'}],'bindings':[
        {'id':'paired','connector':'bot','sender':'42','chat':'123','scope':'999','thread':'',
         'identity':'principal','capabilities':['create','read']}]}
    return renewed_policy(value,{**value,'bindings':[]})


def envelope(**changes):
    return {'platform':'discord','sender':'42','chat':'123','scope':'999','thread':'',
        'message_id':'101','is_bot':False,'text':'fixture request',**changes}


def test_committed_native_capture_survives_crash_and_has_single_processing_owner(tmp_path):
    config=policy();p=GatewayPolicy(config);path=tmp_path/'native.db'
    inbox=NativeInbox(path,Redactor())
    key=inbox.admit(p,'bot',envelope(),{'content':'fixture request'})
    with sqlite3.connect(path) as independent:
        assert independent.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
    assert inbox.claim(key,p)['payload']=={'content':'fixture request'}
    assert inbox.claim(key,p) is None
    inbox.close()
    inbox=NativeInbox(path,Redactor())
    assert inbox.claim(key,p)['id']==key
    inbox.complete(key,True)
    assert inbox.admit(p,'bot',envelope(),{'content':'fixture request'})==key
    assert inbox.claim(key,p) is None
    assert inbox.db.execute('SELECT state,payload FROM native_inbox').fetchone()[:]==('committed','{}')
    inbox.close()


def test_native_repair_and_mutated_replay_cannot_redirect_pending_input(tmp_path):
    config=policy();p=GatewayPolicy(config);inbox=NativeInbox(tmp_path/'native.db',Redactor())
    key=inbox.admit(p,'bot',envelope(),{'content':'fixture request'})
    with pytest.raises(Conflict):inbox.admit(p,'bot',envelope(text='changed'),{'content':'changed'})
    new=copy.deepcopy(config);new['bindings'][0].pop('generation')
    repaired=renewed_policy(new,{**config,'bindings':[]});new_policy=GatewayPolicy(repaired)
    with pytest.raises(Conflict):inbox.admit(new_policy,'bot',envelope(),{'content':'fixture request'})
    assert inbox.claim(key,new_policy) is None
    assert inbox.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='revoked'
    inbox.close()


def test_native_payload_redaction_and_size_are_enforced_before_commit(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor(['fixture-private-credential']))
    key=inbox.admit(GatewayPolicy(policy()),'bot',envelope(text='fixture-private-credential'),
        {'content':'fixture-private-credential'})
    row=inbox.db.execute('SELECT envelope,payload FROM native_inbox').fetchone()
    assert 'fixture-private-credential' not in ''.join(row)
    with pytest.raises(ValueError):inbox.admit(GatewayPolicy(policy()),'bot',envelope(message_id='102'),{'content':'x'*65536})
    assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
    inbox.close()


def test_native_retry_expiry_and_failure_budget_preserve_unresolved_payload(tmp_path):
    p=GatewayPolicy(policy());inbox=NativeInbox(tmp_path/'native.db',Redactor())
    key=inbox.admit(p,'bot',envelope(),{'content':'fixture request'})
    for attempt in range(8):
        assert inbox.claim(key,p,time.time()+100)['id']==key
        inbox.retry(key)
    row=inbox.db.execute('SELECT state,attempt,payload FROM native_inbox').fetchone()
    assert row['state']=='failed' and row['attempt']==8 and json.loads(row['payload'])['content']=='fixture request'
    new=inbox.admit(p,'bot',envelope(message_id='102'),{'content':'late fixture'})
    assert inbox.claim(new,p,time.time()+86401) is None
    assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(new,)).fetchone()[0]=='expired'
    inbox.close()


def test_native_storage_failure_does_not_create_a_receipt(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    inbox.db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON native_inbox BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):inbox.admit(GatewayPolicy(policy()),'bot',envelope(),{})
    assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
    inbox.close()


def test_native_journal_refuses_links_and_writable_locations(tmp_path):
    real=tmp_path/'real';real.write_text('unchanged')
    link=tmp_path/'link';link.symlink_to(real)
    with pytest.raises(OSError):NativeInbox(link,Redactor())
    assert real.read_text()=='unchanged'
    public=tmp_path/'public';public.mkdir(mode=0o755)
    with pytest.raises(PermissionError):NativeInbox(public/'native.db',Redactor())


def test_native_journal_refuses_replaced_sqlite_sidecars(tmp_path):
    path=tmp_path/'native.db'
    sidecar=tmp_path/'native.db-wal'
    target=tmp_path/'owner-data';target.write_text('preserved')
    sidecar.symlink_to(target)
    with pytest.raises(PermissionError):NativeInbox(path,Redactor())
    assert target.read_text()=='preserved'


@pytest.mark.parametrize('received_at',[True,0,-1,float('nan'),float('inf'),1e30])
def test_native_original_receive_time_is_bounded_before_commit(tmp_path,received_at):
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    try:
        with pytest.raises(ValueError):inbox.admit(GatewayPolicy(policy()),'bot',envelope(),{},received_at=received_at)
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
    finally:inbox.close()
