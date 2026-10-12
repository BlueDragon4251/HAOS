import base64
import hashlib
import json
import os
import time
import uuid

import pytest

from haos.application_protocol import action,action_digest,receipt
from haos.application_launcher import running_mission
from haos.store import MissionStore


def test_owner_registered_id_and_opaque_instances_are_the_only_application_targets():
    instance=str(uuid.uuid4())
    assert action({'operation':'app.catalog'})=={'operation':'app.catalog'}
    assert action({'operation':'app.start','program':'approved-terminal'})['program']=='approved-terminal'
    for op in ('state','focus','capture','close'):
        assert action({'operation':'app.'+op,'instance':instance})['instance']==instance
    assert action_digest({'program':'approved-terminal','operation':'app.start'})==action_digest({'operation':'app.start','program':'approved-terminal'})


@pytest.mark.parametrize('value',[
    {'operation':'app.start','program':'/usr/bin/bash'},
    {'operation':'app.start','program':'approved','argv':['-c','id']},
    {'operation':'app.start','program':'approved','environment':{'WAYLAND_DISPLAY':'owner'}},
    {'operation':'app.state','instance':'owner-window'},
    {'operation':'app.capture','instance':str(uuid.uuid4()),'path':'/etc/haos'},
    {'operation':'app.key','instance':str(uuid.uuid4()),'key':'Super'},
    {'operation':'app.type','instance':str(uuid.uuid4()),'text':'a'*513},
    {'operation':'app.type','instance':str(uuid.uuid4()),'text':'a\n'},
    {'operation':'app.shell','command':'id'},
    {'operation':'app.catalog','owner':True},
])
def test_application_targets_cannot_import_owner_windows_files_commands_or_credentials(value):
    with pytest.raises((ValueError,PermissionError)):action(value)


def test_actual_capture_receipt_checks_pixels_hash_size_and_closed_fields():
    pixels=b'\xff\xd8'+b'x'*200+b'\xff\xd9'
    value={'instance':str(uuid.uuid4()),'mime':'image/jpeg','bytes':len(pixels),
           'sha256':hashlib.sha256(pixels).hexdigest(),'base64':base64.b64encode(pixels).decode()}
    assert receipt('app.capture',value)==value
    for delta in ({'bytes':True},{'sha256':'a'*64},{'base64':'not base64'},{'owner_window':True}):
        with pytest.raises(ValueError):receipt('app.capture',dict(value,**delta))


def test_catalog_exposes_only_bounded_owner_approval_metadata():
    item={'program':'approved-editor','class':'editor','approved_sha256':'a'*64,'memory_mib':512,'runtime_seconds':60}
    assert receipt('app.catalog',{'programs':[item]})=={'programs':[item]}
    assert receipt('app.catalog',{'programs':[]})=={'programs':[]}
    for delta in ({'argv':['private-owner-args']},{'executable':'/etc/haos/secret'},{'memory_mib':True},{'runtime_seconds':0},{'class':'owner'},{'program':'/usr/bin/bash'}):
        with pytest.raises(ValueError):receipt('app.catalog',{'programs':[dict(item,**delta)]})
    with pytest.raises(ValueError):receipt('app.catalog',{'programs':[item,item]})


@pytest.fixture
def ledger(tmp_path):
    if os.geteuid()==0:pytest.skip('requires the actual unprivileged controller identity')
    path=tmp_path/'missions.db';tmp_path.chmod(0o700)
    store=MissionStore(path);path.chmod(0o600)
    mission=store.create('isolated-authority','fresh-dispatch','application authority unit fixture')
    store.claim();store.session(mission['id'],'stored-fixture','stored-fixture');store.dispatching(mission['id'])
    store.db.execute('CREATE TABLE gui_actions (id TEXT PRIMARY KEY,mission_id TEXT,request_hash TEXT,operation TEXT,state TEXT,created_at REAL)')
    request=str(uuid.uuid4());value={'operation':'app.start','program':'approved-terminal'}
    store.db.execute('INSERT INTO gui_actions VALUES(?,?,?,?,?,?)',(request,mission['id'],action_digest(value),'app.start','dispatched',time.time()))
    yield store,path,mission['id'],request,value
    store.close()


def test_same_real_wal_snapshot_requires_matching_committed_gui_action(ledger):
    store,path,mission,request,value=ledger
    running_mission(path,mission,os.geteuid(),request=request,action=value)
    with pytest.raises(PermissionError):running_mission(path,mission,os.geteuid(),request=request,action=dict(value,program='unapproved'))
    store.request_cancel(mission,'isolated-authority')
    with pytest.raises(PermissionError):running_mission(path,mission,os.geteuid(),request=request,action=value)


@pytest.mark.parametrize('change',["state='pending'","state='succeeded'","state='uncertain'","created_at=0",'created_at=9999999999',
    "operation='app.close'","request_hash='forged'","mission_id='other-mission'"])
def test_pending_finished_replayed_stale_future_and_foreign_gui_dispatches_are_denied(ledger,change):
    store,path,mission,request,value=ledger;store.db.execute('UPDATE gui_actions SET '+change+' WHERE id=?',(request,))
    with pytest.raises(PermissionError):running_mission(path,mission,os.geteuid(),request=request,action=value)


def test_a_model_supplied_request_id_without_durable_admission_is_not_authority(ledger):
    _,path,mission,_,value=ledger
    with pytest.raises(PermissionError):running_mission(path,mission,os.geteuid(),request=str(uuid.uuid4()),action=value)
