"""Explicit source disposal with real SQLite; source authentication is fixture data."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import pytest
from haos.gateway import Conflict,digest
from haos.gateway_dingtalk import PreparedDingTalkPolicy
from haos.gateway_dingtalk_source_recovery import sources,purge,open_store,STORES
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_dingtalk import binding


@pytest.fixture(params=['original'])
def source(tmp_path,request):
    tmp_path.chmod(0o700);profile='dingtalk-'+'a'*64;folder=tmp_path/profile;folder.mkdir(mode=0o700)
    kind=request.param;path=folder/STORES[kind][0];store=NativeInbox(path,Redactor());b=binding()
    raw=b'private fixture original';sha=hashlib.sha256(raw).hexdigest()
    approval={'binding_id':b['id'],'binding_digest':digest(b),'credential_scope':'e'*64,'envelope':{'platform':'dingtalk'}}
    if kind=='original':
        store.db.execute('CREATE TABLE dingtalk_raw_events(id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,connector TEXT NOT NULL,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,sha256 TEXT NOT NULL,semantic_sha256 TEXT NOT NULL,metadata TEXT NOT NULL,data BLOB NOT NULL,created_at REAL NOT NULL)')
        meta=json.dumps({'approval':approval,'resources':[],'envelope_sha256':'f'*64})
        store.db.execute('INSERT INTO dingtalk_raw_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',('c'*64,'d'*64,'dingtalk',b['id'],digest(b),'e'*64,sha,'f'*64,meta,raw,time.time()))
    store.close()
    config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[b]}
    policy=PreparedDingTalkPolicy(config);config['bindings']=[];revoked=PreparedDingTalkPolicy(config)
    yield tmp_path,profile,kind,path,policy,revoked,raw


def decision(source,policy):
    parent,profile,kind,path,*_=source
    entry=sources(policy,profile,kind,parent=parent)['sources'][0]
    return {'profile':profile,'kind':kind,'id':entry['id'],'snapshot_sha256':entry['snapshot_sha256'],
        'owner_uid':1000,'note_sha256':'a'*64,'confirmed':True}


def test_active_grant_protects_original_and_revoked_inspected_disposal_is_audited_and_idempotent(source):
    parent,profile,kind,path,policy,revoked,raw=source
    listed=sources(policy,parent=parent)
    assert listed['profiles'][0]['profile']==profile and listed['profiles'][0]['kinds'][kind]['active']==1
    report=sources(policy,profile,kind,parent=parent)
    assert report['private_bytes_returned'] is False and raw.decode() not in json.dumps(report)
    assert report['sources'][0]['purge_allowed'] is False
    with pytest.raises(PermissionError):purge(policy,decision(source,policy),parent=parent)
    request=decision(source,revoked);result=purge(revoked,request,parent=parent)
    assert result['removed_payload_bytes']==len(raw) and result['tombstones_retained'] and not result['network_requested']
    assert purge(revoked,request,parent=parent)['removed_payload_bytes']==0
    after=sources(revoked,profile,kind,parent=parent)['sources'][0]
    assert after['stored_bytes']==0 and after['purged'] is True
    db=sqlite3.connect(path)
    try:
        assert db.execute('SELECT owner_uid FROM dingtalk_source_owner_events').fetchone()[0]==1000
        assert db.execute(f'SELECT COUNT(*) FROM {STORES[kind][1]}').fetchone()[0]==1
    finally:db.close()
    with pytest.raises(Conflict):purge(revoked,{**request,'note_sha256':'b'*64},parent=parent)


@pytest.mark.parametrize('change',[{'confirmed':1},{'owner_uid':True},{'snapshot_sha256':'b'*64},
    {'profile':'../../owner'},{'kind':'path'},{'extra':'delete all'}])
def test_ambiguous_stale_or_path_based_decisions_preserve_every_byte(source,change):
    parent,profile,kind,path,policy,revoked,raw=source
    with pytest.raises((PermissionError,Conflict,ValueError)):purge(revoked,{**decision(source,revoked),**change},parent=parent)
    assert sources(revoked,profile,kind,parent=parent)['sources'][0]['stored_bytes']==len(raw)


def test_audit_failure_rolls_back_source_removal(source):
    parent,profile,kind,path,policy,revoked,raw=source;request=decision(source,revoked)
    db=sqlite3.connect(path)
    try:
        db.execute('CREATE TABLE dingtalk_source_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,removed_bytes INTEGER NOT NULL,purged_at REAL NOT NULL)')
        db.execute("CREATE TRIGGER fail_source_audit BEFORE INSERT ON dingtalk_source_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
        db.commit()
    finally:db.close()
    with pytest.raises(sqlite3.IntegrityError):purge(revoked,request,parent=parent)
    assert sources(revoked,profile,kind,parent=parent)['sources'][0]['stored_bytes']==len(raw)


def test_hardlinked_or_symlinked_source_ledgers_are_refused(source):
    import os
    parent,profile,kind,path,*_=source
    linked=path.with_name('alias.db');os.link(path,linked)
    with pytest.raises(PermissionError):open_store(profile,kind,parent=parent)
    linked.unlink();path.rename(linked);path.symlink_to(linked)
    with pytest.raises(PermissionError):open_store(profile,kind,parent=parent)
