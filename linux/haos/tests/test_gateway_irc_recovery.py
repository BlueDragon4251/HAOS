"""Prepared owner recovery preserves private content, gaps and other authority."""
import json
import sqlite3
import time

import pytest

from haos.gateway import digest
from haos.gateway_irc_ingress import PreparedIRCPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_irc_auth, unresolved
from haos.redaction import Redactor


def fixture(tmp_path):
    config={'version':1,'connectors':[{'id':'ha','platform':'irc'}],'bindings':[{
        'id':'owner','connector':'ha','sender':'a'*32,'chat':'#owner','scope':'irc.fixture.invalid:6697','thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    policy=PreparedIRCPolicy(config)
    inbox=NativeInbox(tmp_path/'native.db',Redactor())
    inbox.admit(policy,'ha',{'platform':'irc','sender':'a'*32,'chat':'#owner','scope':'irc.fixture.invalid:6697','thread':'',
        'message_id':digest('retained-context-event'),'is_bot':False,'text':'private retained IRC frame'},
        {'event':'private retained IRC frame'})
    inbox.db.execute('CREATE TABLE irc_profile_status(identity TEXT PRIMARY KEY,connector TEXT,status TEXT,updated_at REAL,next_attempt REAL,gap_since REAL)')
    for key,connector,status in [('auth','ha','authentication-refused'),('rate','ha','rate-limited'),
            ('revoked','ha','revoked'),('other','other','authentication-refused')]:
        inbox.db.execute('INSERT INTO irc_profile_status VALUES(?,?,?,?,?,?)',(key,connector,status,time.time(),12345,42))
    return inbox,policy,{'connector':'ha','owner_uid':1000,'note_sha256':'c'*64}


def test_prepared_irc_recovery_is_explicit_audited_and_preserves_gaps_and_rate_limits(tmp_path):
    inbox,policy,params=fixture(tmp_path)
    try:
        before=tuple(inbox.db.execute('SELECT payload,envelope,created_at,state,attempt FROM native_inbox').fetchone())
        metadata=unresolved(inbox)
        assert len(metadata['ingress'])==1 and len(metadata['transport'])==4
        assert 'private retained IRC frame' not in json.dumps(metadata)
        assert all(row['gap_since']==42 and row['unseen_remote_history_recovered'] is False for row in metadata['transport'])
        assert retry_irc_auth(inbox,policy,params)=={'connector':'ha','authentication_blocks_cleared':1,'network_requested':False}
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity='auth'").fetchone())==('created',0,42)
        for key,status in [('rate','rate-limited'),('revoked','revoked'),('other','authentication-refused')]:
            assert tuple(inbox.db.execute('SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity=?',(key,)).fetchone())==(status,12345,42)
        assert tuple(inbox.db.execute('SELECT payload,envelope,created_at,state,attempt FROM native_inbox').fetchone())==before
        assert tuple(inbox.db.execute('SELECT owner_uid,decision,changed,note_sha256 FROM irc_owner_events').fetchone())==(1000,'retry-auth',1,'c'*64)
        assert retry_irc_auth(inbox,policy,params)['authentication_blocks_cleared']==0
        assert inbox.db.execute('SELECT COUNT(*) FROM irc_owner_events').fetchone()[0]==1
    finally:inbox.close()


def test_prepared_irc_auth_retry_rolls_back_when_audit_storage_fails(tmp_path):
    inbox,policy,params=fixture(tmp_path)
    try:
        inbox.db.execute('CREATE TABLE irc_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
        inbox.db.execute("CREATE TRIGGER fixture_audit_failure BEFORE INSERT ON irc_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit unavailable'); END")
        with pytest.raises(sqlite3.IntegrityError):retry_irc_auth(inbox,policy,params)
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity='auth'").fetchone())==('authentication-refused',12345,42)
        assert inbox.db.execute('SELECT COUNT(*) FROM irc_owner_events').fetchone()[0]==0
    finally:inbox.close()


def test_owner_auth_recheck_preserves_unexpired_throttle_even_when_authentication_is_also_refused(tmp_path):
    inbox,policy,params=fixture(tmp_path)
    try:
        deadline=time.time()+3600
        inbox.db.execute("UPDATE irc_profile_status SET next_attempt=? WHERE identity='auth'",(deadline,))
        assert retry_irc_auth(inbox,policy,params)['authentication_blocks_cleared']==1
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity='auth'").fetchone())==('created',deadline,42)
    finally:inbox.close()


@pytest.mark.parametrize('change',[{'connector':'other'},{'owner_uid':True},{'owner_uid':-1},
    {'note_sha256':'raw private note'},{'extra':'unreviewed'}])
def test_prepared_irc_auth_retry_rejects_missing_owner_audit_authority(tmp_path,change):
    inbox,policy,params=fixture(tmp_path)
    try:
        with pytest.raises(ValueError):retry_irc_auth(inbox,policy,{**params,**change})
        assert inbox.db.execute("SELECT status FROM irc_profile_status WHERE identity='auth'").fetchone()[0]=='authentication-refused'
    finally:inbox.close()


@pytest.mark.parametrize('field,value',[('status','raw vendor response'),('gap_since',-1),('next_attempt',-1),('connector','bad\nconnector')])
def test_prepared_irc_owner_metadata_rejects_untrusted_status_values(tmp_path,field,value):
    inbox,_policy,_params=fixture(tmp_path)
    try:
        inbox.db.execute('UPDATE irc_profile_status SET '+field+'=? WHERE identity=?',(value,'auth'))
        with pytest.raises(ValueError):unresolved(inbox)
    finally:inbox.close()


def outgoing_fixture(tmp_path):
    from haos.gateway_irc_recovery import outgoing
    inbox=NativeInbox(tmp_path/'outgoing.db',Redactor())
    inbox.db.execute('CREATE TABLE irc_delivery_intents(delivery_id TEXT,attempt INTEGER,connector TEXT,identity TEXT,binding_digest TEXT,content_digest TEXT,state TEXT,chunk_count INTEGER,receipts TEXT,updated_at REAL,receipt TEXT)')
    inbox.db.execute('INSERT INTO irc_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        ('a'*64,1,'irc','b'*64,'c'*64,'d'*64,'confirmed',1,json.dumps(['private_server_identifier']),123,'irc_echo_'+'e'*64))
    return inbox,outgoing


def test_irc_native_outgoing_inspection_exposes_only_bounded_hashes_and_server_confirmation_reference(tmp_path):
    inbox,outgoing=outgoing_fixture(tmp_path)
    try:
        result=outgoing(inbox)
        assert len(result)==1 and result[0]['server_echo_receipt']=='irc_echo_'+'e'*64
        assert result[0]['confirmed_chunks']==1 and result[0]['recipient_receipt_verified'] is False
        assert 'private_server_identifier' not in json.dumps(result)
        assert unresolved(inbox)['native_outgoing']==result
    finally:inbox.close()


@pytest.mark.parametrize('field,value',[('state','untrusted vendor error'),('connector','bad\nconnector'),
    ('attempt',0),('attempt',6),('chunk_count',65),('receipts','not-json'),('receipts','["duplicate", "duplicate"]'),
    ('receipt','untrusted reference'),('binding_digest','forged'),('updated_at',-1)])
def test_private_irc_outgoing_metadata_rejects_invalid_or_unbounded_fields(tmp_path,field,value):
    inbox,outgoing=outgoing_fixture(tmp_path)
    try:
        inbox.db.execute('UPDATE irc_delivery_intents SET '+field+'=?',(value,))
        with pytest.raises(ValueError):outgoing(inbox)
    finally:inbox.close()


@pytest.mark.parametrize('code',['channel-key-required','nickname-in-use','private-untrusted-vendor-error',None])
def test_private_irc_owner_diagnostics_are_bounded_and_legacy_journals_remain_readable(tmp_path,code):
    inbox,policy,params=fixture(tmp_path)
    try:
        assert all('last_error' not in row for row in unresolved(inbox)['transport'])
        inbox.db.execute("ALTER TABLE irc_profile_status ADD COLUMN last_error TEXT DEFAULT ''")
        inbox.db.execute("UPDATE irc_profile_status SET last_error=? WHERE identity='auth'",(code,))
        if code in {'channel-key-required','nickname-in-use'}:
            assert any(row.get('last_error')==code for row in unresolved(inbox)['transport'])
        else:
            with pytest.raises(ValueError):unresolved(inbox)
    finally:inbox.close()
