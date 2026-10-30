"""Prepared owner recovery preserves private content, gaps and other authority."""
import json
import sqlite3
import time

import pytest

from haos.gateway import digest
from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_homeassistant_auth, unresolved
from haos.redaction import Redactor


def fixture(tmp_path):
    config={'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
        'id':'owner','connector':'ha','sender':'a'*32,'chat':'input_text.owner','scope':'','thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    policy=PreparedHomeAssistantPolicy(config)
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    inbox.admit(policy,'ha',{'platform':'homeassistant','sender':'a'*32,'chat':'input_text.owner','scope':'','thread':'',
        'message_id':digest('retained-context-event'),'is_bot':False,'text':'private retained incoming state'},
        {'event':'private retained incoming state'})
    inbox.db.execute('CREATE TABLE homeassistant_profile_status(identity TEXT PRIMARY KEY,connector TEXT,status TEXT,updated_at REAL,next_attempt REAL,gap_since REAL)')
    for key,connector,status in [('auth','ha','authentication-refused'),('rate','ha','rate-limited'),
            ('revoked','ha','revoked'),('other','other','authentication-refused')]:
        inbox.db.execute('INSERT INTO homeassistant_profile_status VALUES(?,?,?,?,?,?)',(key,connector,status,time.time(),12345,42))
    return inbox,policy,{'connector':'ha','owner_uid':1000,'note_sha256':'c'*64}


def test_prepared_homeassistant_recovery_is_explicit_audited_and_preserves_gaps_and_rate_limits(tmp_path):
    inbox,policy,params=fixture(tmp_path)
    try:
        before=tuple(inbox.db.execute('SELECT payload,envelope,created_at,state,attempt FROM native_inbox').fetchone())
        metadata=unresolved(inbox)
        assert len(metadata['ingress'])==1 and len(metadata['transport'])==4
        assert 'private retained incoming state' not in json.dumps(metadata)
        assert all(row['gap_since']==42 and row['unseen_remote_history_recovered'] is False for row in metadata['transport'])
        assert retry_homeassistant_auth(inbox,policy,params)=={'connector':'ha','authentication_blocks_cleared':1,'network_requested':False}
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity='auth'").fetchone())==('created',0,42)
        for key,status in [('rate','rate-limited'),('revoked','revoked'),('other','authentication-refused')]:
            assert tuple(inbox.db.execute('SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity=?',(key,)).fetchone())==(status,12345,42)
        assert tuple(inbox.db.execute('SELECT payload,envelope,created_at,state,attempt FROM native_inbox').fetchone())==before
        assert tuple(inbox.db.execute('SELECT owner_uid,decision,changed,note_sha256 FROM homeassistant_owner_events').fetchone())==(1000,'retry-auth',1,'c'*64)
        assert retry_homeassistant_auth(inbox,policy,params)['authentication_blocks_cleared']==0
        assert inbox.db.execute('SELECT COUNT(*) FROM homeassistant_owner_events').fetchone()[0]==1
    finally:inbox.close()


def test_prepared_homeassistant_auth_retry_rolls_back_when_audit_storage_fails(tmp_path):
    inbox,policy,params=fixture(tmp_path)
    try:
        inbox.db.execute('CREATE TABLE homeassistant_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
        inbox.db.execute("CREATE TRIGGER fixture_audit_failure BEFORE INSERT ON homeassistant_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit unavailable'); END")
        with pytest.raises(sqlite3.IntegrityError):retry_homeassistant_auth(inbox,policy,params)
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity='auth'").fetchone())==('authentication-refused',12345,42)
        assert inbox.db.execute('SELECT COUNT(*) FROM homeassistant_owner_events').fetchone()[0]==0
    finally:inbox.close()


def test_owner_auth_recheck_preserves_unexpired_throttle_even_when_authentication_is_also_refused(tmp_path):
    inbox,policy,params=fixture(tmp_path)
    try:
        deadline=time.time()+3600
        inbox.db.execute("UPDATE homeassistant_profile_status SET next_attempt=? WHERE identity='auth'",(deadline,))
        assert retry_homeassistant_auth(inbox,policy,params)['authentication_blocks_cleared']==1
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity='auth'").fetchone())==('created',deadline,42)
    finally:inbox.close()


@pytest.mark.parametrize('change',[{'connector':'other'},{'owner_uid':True},{'owner_uid':-1},
    {'note_sha256':'raw private note'},{'extra':'unreviewed'}])
def test_prepared_homeassistant_auth_retry_rejects_missing_owner_audit_authority(tmp_path,change):
    inbox,policy,params=fixture(tmp_path)
    try:
        with pytest.raises(ValueError):retry_homeassistant_auth(inbox,policy,{**params,**change})
        assert inbox.db.execute("SELECT status FROM homeassistant_profile_status WHERE identity='auth'").fetchone()[0]=='authentication-refused'
    finally:inbox.close()


@pytest.mark.parametrize('field,value',[('status','raw vendor response'),('gap_since',-1),('next_attempt',-1),('connector','bad\nconnector')])
def test_prepared_homeassistant_owner_metadata_rejects_untrusted_status_values(tmp_path,field,value):
    inbox,_policy,_params=fixture(tmp_path)
    try:
        inbox.db.execute('UPDATE homeassistant_profile_status SET '+field+'=? WHERE identity=?',(value,'auth'))
        with pytest.raises(ValueError):unresolved(inbox)
    finally:inbox.close()
