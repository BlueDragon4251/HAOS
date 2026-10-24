import copy
import hashlib
import json
import time

import pytest

from haos.gateway import Conflict, GatewayPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import reconcile, unresolved
from haos.redaction import Redactor


def fixture(tmp_path):
    policy = GatewayPolicy({'version':1,'connectors':[{'id':'bot','platform':'discord'}],'bindings':[
        {'id':'paired','connector':'bot','sender':'42','chat':'123','scope':'999','thread':'',
         'identity':'principal','capabilities':['create','read'],'generation':'a'*64}]})
    inbox = NativeInbox(tmp_path/'native.db',Redactor())
    envelope = {'platform':'discord','sender':'42','chat':'123','scope':'999','thread':'',
        'message_id':'101','is_bot':False,'text':'private fixture request'}
    key = inbox.admit(policy,'bot',envelope,{'content':'private fixture request'})
    for _ in range(8):
        assert inbox.claim(key,policy,time.time()+100)
        inbox.retry(key)
    request = {'ingress_id':key,'state':'failed','attempt':8,'decision':'retry','owner_uid':1000,'note_sha256':'b'*64}
    return inbox, policy, request


def test_owner_retry_records_evidence_and_preserves_payload(tmp_path):
    inbox,policy,request=fixture(tmp_path)
    try:
        metadata=unresolved(inbox)
        assert len(metadata['ingress'])==1 and 'private fixture request' not in json.dumps(metadata)
        assert metadata['ingress'][0]['payload_sha256']==hashlib.sha256(inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0].encode()).hexdigest()
        assert reconcile(inbox,policy,request)['state']=='pending'
        assert inbox.claim(request['ingress_id'],policy)['payload']=={'content':'private fixture request'}
        audit=inbox.db.execute('SELECT owner_uid,decision,previous_state,previous_attempt,note_sha256 FROM native_owner_events').fetchone()
        assert tuple(audit)==(1000,'retry','failed',8,'b'*64)
        with pytest.raises(Conflict):reconcile(inbox,policy,request)
    finally:inbox.close()


@pytest.mark.parametrize('change',['grant','age','attempt','state'])
def test_owner_retry_cannot_bypass_grant_expiry_or_stale_receipt(tmp_path,change):
    inbox,policy,request=fixture(tmp_path)
    try:
        if change=='grant':
            raw=copy.deepcopy(list(policy.bindings.values()))
            raw[0]['generation']='c'*64
            policy=GatewayPolicy({'version':1,'connectors':list(policy.connectors.values()),'bindings':raw})
        elif change=='age':inbox.db.execute('UPDATE native_inbox SET created_at=?',(time.time()-86401,))
        elif change=='attempt':request['attempt']=7
        else:request['state']='expired'
        with pytest.raises((PermissionError,Conflict)):reconcile(inbox,policy,request)
        row=inbox.db.execute('SELECT state,attempt,payload FROM native_inbox').fetchone()
        assert row['state']=='failed' and row['attempt']==8 and 'private fixture request' in row['payload']
        assert not inbox.db.execute("SELECT name FROM sqlite_master WHERE name='native_owner_events'").fetchall()
    finally:inbox.close()


def test_owner_discard_keeps_unresolved_data_and_does_not_require_revoked_grant(tmp_path):
    inbox,policy,request=fixture(tmp_path)
    try:
        policy=GatewayPolicy({'version':1,'connectors':[],'bindings':[]})
        request['decision']='discard'
        before=tuple(inbox.db.execute('SELECT payload,envelope,created_at FROM native_inbox').fetchone())
        assert reconcile(inbox,policy,request)['state']=='discarded'
        assert tuple(inbox.db.execute('SELECT payload,envelope,created_at FROM native_inbox').fetchone())==before
        assert unresolved(inbox)['ingress']==[]
        assert inbox.claim(request['ingress_id'],policy) is None
    finally:inbox.close()


def test_failed_owner_audit_insert_rolls_back_retry(tmp_path):
    inbox,policy,request=fixture(tmp_path)
    try:
        # Establish the real audit table with a separate preserved decision.
        inbox.db.execute('CREATE TABLE native_owner_events(id INTEGER PRIMARY KEY,ingress_id TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,previous_state TEXT,previous_attempt INTEGER,note_sha256 TEXT)')
        inbox.db.execute("CREATE TRIGGER fixture_audit_failure BEFORE INSERT ON native_owner_events BEGIN SELECT RAISE(ABORT, 'fixture audit unavailable'); END")
        import sqlite3
        with pytest.raises(sqlite3.DatabaseError):reconcile(inbox,policy,request)
        assert tuple(inbox.db.execute('SELECT state,attempt FROM native_inbox').fetchone())==('failed',8)
    finally:inbox.close()
