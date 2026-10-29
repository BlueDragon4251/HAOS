"""Durable audio retry and owner disposal; codec/UID tests run separately."""
import asyncio
import hashlib
from types import SimpleNamespace
import pytest
from haos.gateway import Conflict,digest
from haos.gateway_feishu_output import Output
from haos.gateway_media_relay import MediaCache
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def voice(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.db',Redactor())
    binding={'id':'owner','connector':'feishu','generation':'a'*64};active=[True];calls=[]
    class Policy:
        bindings={'owner':binding}
        def current_binding(self,row):
            if not active[0] or row['binding_digest']!=digest(binding):raise PermissionError('withdrawn')
            return binding
    policy=Policy();adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=inbox))
    output=Output(adapter)
    def current(_delivery):
        if not active[0]:raise PermissionError('withdrawn')
        return binding
    output.current=current
    async def encode(data,check):
        calls.append(data);check();await asyncio.sleep(0)
        raw=b'OggSOpusHead'+str(len(calls)).encode()
        return {'data':raw,'sha256':hashlib.sha256(raw).hexdigest(),'source_sha256':hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr('haos.speech_client.opus',encode)
    raw=b'original audio';offer={'id':'c'*64,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    yield SimpleNamespace(inbox=inbox,output=output,policy=policy,active=active,calls=calls,offer=offer,raw=raw,
        delivery={'id':'d'*64},binding=binding)
    inbox.close()


def prepare(v):return v.output.voice(v.delivery,v.offer,v.raw)


def test_repeated_and_concurrent_encoding_reuses_first_committed_bytes(voice):
    v=voice
    async def run():return await asyncio.gather(prepare(v),prepare(v))
    first,second=asyncio.run(run());assert first==second
    assert asyncio.run(prepare(v))==first and len(v.calls)==2
    assert v.inbox.db.execute('SELECT COUNT(*) FROM feishu_output_voice').fetchone()[0]==1
    v.offer['sha256']='f'*64
    with pytest.raises(Conflict):asyncio.run(prepare(v))
    assert len(v.calls)==2


def test_owner_purge_requires_withdrawal_retains_audit_and_prevents_regeneration(voice):
    v=voice;raw=asyncio.run(prepare(v));media=MediaCache(v.inbox)
    request={'id':v.offer['id'],'owner_uid':1000,'note_sha256':'e'*64,'confirmed':True}
    entry=media.owner_inventory(v.policy)['uploads'][0]
    assert entry['stored_bytes']==len(raw) and entry['purge_allowed'] is False and 'data' not in entry
    with pytest.raises(PermissionError):media.owner_purge(v.policy,request)
    v.active[0]=False
    assert media.owner_inventory(v.policy)['uploads'][0]['purge_allowed'] is True
    assert media.owner_purge(v.policy,request)['removed_payload_bytes']==len(raw)
    assert media.owner_purge(v.policy,request)['removed_payload_bytes']==0
    assert media.owner_inventory(v.policy)['stored_bytes']==0
    assert v.inbox.db.execute('SELECT data FROM feishu_output_voice').fetchone()[0]==b''
    assert v.inbox.db.execute('SELECT owner_uid FROM native_media_owner_events').fetchone()[0]==1000
    v.active[0]=True
    with pytest.raises(Conflict):asyncio.run(prepare(v))
    assert len(v.calls)==1


def test_owner_audit_failure_does_not_remove_retained_voice(voice):
    import sqlite3
    v=voice;raw=asyncio.run(prepare(v));media=MediaCache(v.inbox);v.active[0]=False
    v.inbox.db.execute('CREATE TABLE native_media_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,purged_at REAL NOT NULL,removed_bytes INTEGER NOT NULL)')
    v.inbox.db.execute("CREATE TRIGGER failed_voice_audit BEFORE INSERT ON native_media_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError):media.owner_purge(v.policy,{'id':v.offer['id'],'owner_uid':1000,'note_sha256':'e'*64,'confirmed':True})
    assert v.inbox.db.execute('SELECT data FROM feishu_output_voice').fetchone()[0]==raw


def test_withdrawal_during_encoding_never_persists_result(voice,monkeypatch):
    v=voice
    async def encode(data,current):
        v.active[0]=False
        return {'data':b'OggSOpusHead','source_sha256':v.offer['sha256'],'sha256':'a'*64}
    monkeypatch.setattr('haos.speech_client.opus',encode)
    with pytest.raises(PermissionError):asyncio.run(prepare(v))
    assert v.inbox.db.execute('SELECT COUNT(*) FROM feishu_output_voice').fetchone()[0]==0


def test_full_cache_refuses_encoding_before_worker_and_rechecks_after_yield(voice,monkeypatch):
    v=voice;db=v.inbox.db
    db.execute('CREATE TABLE line_output_media(id TEXT PRIMARY KEY,data BLOB)')
    db.execute('INSERT INTO line_output_media VALUES(?,zeroblob(?))',('other',64*1024*1024))
    with pytest.raises(Conflict):asyncio.run(prepare(v))
    assert not v.calls
    db.execute('DELETE FROM line_output_media')
    async def encode(data,current):
        db.execute('INSERT INTO line_output_media VALUES(?,zeroblob(?))',('other',64*1024*1024))
        raw=b'OggSOpusHead'
        return {'data':raw,'source_sha256':v.offer['sha256'],'sha256':hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr('haos.speech_client.opus',encode)
    with pytest.raises(Conflict):asyncio.run(prepare(v))
    assert db.execute('SELECT COUNT(*) FROM feishu_output_voice').fetchone()[0]==0
