"""Actual cache/audit SQLite transactions with synthetic codec bytes and owner policy."""
import asyncio
from copy import deepcopy
import hashlib
import sqlite3
from types import SimpleNamespace
import pytest

from haos.gateway import Conflict,digest
from haos.gateway_dingtalk import PreparedDingTalkPolicy
from haos.gateway_dingtalk_delivery import Publisher
from haos.gateway_dingtalk_output import Output
from haos.gateway_dingtalk_transform_recovery import inventory,purge
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_dingtalk import account,binding


@pytest.fixture
def fixture(tmp_path):
    inbox=NativeInbox(tmp_path/'native.db',Redactor());grant={**binding(),'allow_outbound_media':True}
    raw={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[deepcopy(grant)]}
    policy=lambda:PreparedDingTalkPolicy(raw)
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='dingtalk',inbox=inbox,policy=policy),
        _haos_dingtalk_value={**account(),'reply_mode':'robot'},_haos_dingtalk_live=True,
        _haos_dingtalk_check=lambda:None,native_health=lambda:{'status':'connected-ws'})
    adapter._haos_dingtalk_publisher=Publisher(adapter);output=Output(adapter)
    delivery={'id':'a'*64,'binding_id':'owner','binding_digest':digest(grant)}
    data=b'private synthetic codec bytes; no vendor acceptance claim'
    offer={'id':'b'*64,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()};calls=[]
    async def build():
        calls.append(True)
        return {'id':offer['id'],'kind':'file','name':'result-0.zip','mime':'application/zip','data':data,
            'duration_ms':0,'width':0,'height':0,'cover':None}
    asyncio.run(output.transform(delivery,offer,'fixture-codec',build))
    try:yield inbox,policy,raw,output,delivery,offer,build,data,calls
    finally:inbox.close()


def decision(inbox,policy):
    item=inventory(inbox,policy)['outputs'][0]
    return {'id':item['id'],'snapshot_sha256':item['snapshot_sha256'],'owner_uid':1000,'note_sha256':'c'*64,'confirmed':True}


def test_withdrawn_inspected_disposal_is_atomic_audited_idempotent_and_never_restores_codec_bytes(fixture):
    inbox,policy,raw,output,delivery,offer,build,data,calls=fixture
    report=inventory(inbox,policy());assert not report['private_bytes_returned'] and data.decode() not in str(report)
    with pytest.raises(PermissionError):purge(inbox,policy(),decision(inbox,policy()))
    original=deepcopy(raw['bindings']);raw['bindings']=[];request=decision(inbox,policy())
    result=purge(inbox,policy(),request)
    assert result['removed_payload_bytes']==len(data) and result['tombstones_retained'] and not result['network_requested']
    assert purge(inbox,policy(),request)['removed_payload_bytes']==0
    assert inbox.db.execute('SELECT COUNT(*),length(data) FROM dingtalk_output_transforms').fetchone()[1]==0
    assert inbox.db.execute('SELECT owner_uid FROM dingtalk_transform_owner_events').fetchone()[0]==1000
    raw['bindings']=original
    with pytest.raises(Conflict):asyncio.run(output.transform(delivery,offer,'fixture-codec',build))
    assert calls==[True]


@pytest.mark.parametrize('change',[{'confirmed':1},{'owner_uid':True},{'owner_uid':-1},{'id':'../private'},
    {'snapshot_sha256':'0'*64},{'extra':'all files'},{'note_sha256':'not a hash'}])
def test_invalid_or_stale_decisions_leave_every_codec_byte_unchanged(fixture,change):
    inbox,policy,raw,*_=fixture;raw['bindings']=[]
    with pytest.raises((PermissionError,Conflict)):purge(inbox,policy(),{**decision(inbox,policy()),**change})
    assert inventory(inbox,policy())['stored_bytes']>0


def test_audit_failure_rolls_back_removal_and_keeps_original_proofs(fixture):
    inbox,policy,raw,*_=fixture;raw['bindings']=[];request=decision(inbox,policy())
    inbox.db.execute('CREATE TABLE dingtalk_transform_owner_events(id TEXT PRIMARY KEY,owner_uid INTEGER NOT NULL,note_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,removed_bytes INTEGER NOT NULL,policy_sha256 TEXT NOT NULL,created_at REAL NOT NULL)')
    inbox.db.execute("CREATE TRIGGER failed_cache_audit BEFORE INSERT ON dingtalk_transform_owner_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
    before=inventory(inbox,policy())
    with pytest.raises(sqlite3.IntegrityError):purge(inbox,policy(),request)
    assert inventory(inbox,policy())==before and inbox.db.execute('SELECT COUNT(*) FROM dingtalk_transform_owner_events').fetchone()[0]==0
