"""Actual durable SQLite originals and recovery, before transport acknowledgment."""
import json
import pytest
from haos.gateway import Conflict
from haos.gateway_google_chat_custody import Originals
from haos.redaction import Redactor
from test_gateway_google_chat import account,event,policy


def open_store(tmp_path):
    tmp_path.chmod(0o700)
    return Originals(tmp_path/'originals.sqlite',Redactor([]))


def test_reopen_preserves_first_wire_across_equivalent_native_addon_envelopes_and_parent_receipt(tmp_path):
    store=open_store(tmp_path);p=policy();data=event();raw=json.dumps(data).encode()
    key=store.retain(p,'google',account(),raw,lambda:None)
    assert store.db.execute('PRAGMA synchronous').fetchone()[0]==2
    store.close();store=open_store(tmp_path)
    other=json.dumps({'chat':{'messagePayload':{'message':data['message'],'space':data['space']}}}).encode()
    assert store.retain(p,'google',account(),other,lambda:None)==key
    assert store.load(key,p,'google',account(),lambda:None)[0]==raw
    store.admitted(key,'a'*64,p,'google',account(),lambda:None);store.close();store=open_store(tmp_path)
    store.admitted(key,'a'*64,p,'google',account(),lambda:None)
    with pytest.raises(Conflict):store.admitted(key,'b'*64,p,'google',account(),lambda:None)
    assert store.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
    store.close()


def test_modified_source_bytes_never_restore_on_replay_and_withdrawn_authority_cannot_read(tmp_path):
    store=open_store(tmp_path);p=policy();raw=json.dumps(event()).encode();key=store.retain(p,'google',account(),raw,lambda:None)
    store.db.execute("UPDATE google_chat_originals SET raw=x'00' WHERE id=?",(key,));store.close();store=open_store(tmp_path)
    with pytest.raises(Conflict):store.retain(p,'google',account(),raw,lambda:None)
    with pytest.raises(Conflict):store.load(key,p,'google',account(),lambda:None)
    assert store.db.execute('SELECT raw FROM google_chat_originals').fetchone()[0]==b'\0'
    store.close()


def test_reused_message_id_with_changed_content_or_key_scope_and_changed_grant_are_refused(tmp_path):
    store=open_store(tmp_path);p=policy();data=event();raw=json.dumps(data).encode();key=store.retain(p,'google',account(),raw,lambda:None)
    data['message']['argumentText']='/cancel another'
    with pytest.raises(Conflict):store.retain(p,'google',account(),json.dumps(data).encode(),lambda:None)
    value=account();value['service_account']['private_key_id']='b'*40
    with pytest.raises(Conflict):store.retain(p,'google',value,raw,lambda:None)
    p.bindings['owner']['generation']='b'*64
    with pytest.raises(Conflict):store.load(key,p,'google',account(),lambda:None)
    p.bindings.clear()
    with pytest.raises(PermissionError):store.load(key,p,'google',account(),lambda:None)
    store.close()


def test_current_publication_failure_rolls_back_before_acknowledgeable_receipt(tmp_path):
    store=open_store(tmp_path);p=policy();calls=[]
    def current():
        calls.append(True)
        if len(calls)>1:raise PermissionError('publication changed')
    with pytest.raises(PermissionError):store.retain(p,'google',account(),json.dumps(event()).encode(),current)
    assert store.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==0
    assert not store.db.in_transaction
    store.close()
