import asyncio
import base64
import hashlib
import io
import json
import os
import time
import uuid

from PIL import Image
import pytest

from haos.controller import Controller
from haos.gui import GuiBroker
from haos.application_launcher import running_mission
from haos.application_session import jpeg_capture
from haos.store import Conflict,MissionStore


@pytest.fixture
def live(tmp_path):
    path=tmp_path/'missions.db';tmp_path.chmod(0o700)
    store=MissionStore(path);path.chmod(0o600)
    mission=store.create('owner-fixture','private-app','providerless application queue fixture')
    store.claim();store.session(mission['id'],'offline-session','offline-stored');store.dispatching(mission['id'])
    gui=GuiBroker(store)
    yield store,gui,mission['id'],path
    store.close()


def submit(gui,mission,action,key=None):
    return gui.submit(mission,{'session':'offline-session','id':key or str(uuid.uuid4()),'action':action})


def test_actual_application_dispatch_does_not_need_a_native_session_and_commits_before_root_execution(live):
    store,gui,mission,path=live
    action={'operation':'app.start','program':'approved-terminal'}
    with pytest.raises(Conflict):submit(gui,mission,action)
    gui.application_seen_at=time.time();admitted=submit(gui,mission,action)
    dispatched=gui.application_poll(mission)
    assert dispatched=={'id':admitted['id'],'mission':mission,'action':action}
    assert tuple(store.db.execute('SELECT arguments,state FROM gui_actions').fetchone())==(None,'dispatched')
    if os.geteuid()!=0:running_mission(path,mission,os.geteuid(),request=admitted['id'],action=action)
    assert gui.application_poll(mission) is None
    gui.application_acknowledge(admitted['id'],result={'instance':admitted['id'],'program':'approved-terminal','state':'submitted'})
    assert submit(gui,mission,action,admitted['id'])['state']=='succeeded'


def test_native_poll_ack_and_restart_cannot_execute_invalidate_or_forge_application_actions(live):
    _,gui,mission,_=live;gui.application_seen_at=time.time()
    admitted=submit(gui,mission,{'operation':'app.start','program':'approved-terminal'})
    epoch=str(uuid.uuid4());gui.attach({'epoch':epoch})
    assert gui.poll(mission,{'epoch':epoch})['request'] is None
    assert gui.application_poll(mission)['id']==admitted['id']
    # Even knowledge of the internal epoch must not grant the renderer an ack.
    gui.attach({'epoch':gui.application_epoch})
    with pytest.raises(Conflict):gui.acknowledge({'epoch':gui.epoch,'id':admitted['id'],'ok':True,
        'result':{'instance':admitted['id'],'program':'approved-terminal','state':'submitted'}})
    assert gui.result(mission,{'session':'offline-session','id':admitted['id']})['state']=='dispatched'
    with pytest.raises(PermissionError):gui.application_acknowledge(admitted['id'],result={'instance':str(uuid.uuid4()),'program':'approved-terminal','state':'submitted'})
    gui.application_acknowledge(admitted['id'])
    assert submit(gui,mission,{'operation':'app.start','program':'approved-terminal'},admitted['id'])['state']=='uncertain'


def test_application_captures_expire_and_only_integrity_metadata_is_durable(live):
    store,gui,mission,_=live;gui.application_seen_at=time.time();instance=str(uuid.uuid4())
    admitted=submit(gui,mission,{'operation':'app.capture','instance':instance});gui.application_poll(mission)
    output=io.BytesIO();Image.new('RGB',(80,60),(15,30,70)).save(output,format='PNG');pixels=jpeg_capture(output.getvalue())
    data={'instance':instance,'mime':'image/jpeg','bytes':len(pixels),'sha256':hashlib.sha256(pixels).hexdigest(),'base64':base64.b64encode(pixels).decode()}
    gui.application_acknowledge(admitted['id'],result=data)
    assert gui.result(mission,{'session':'offline-stored','id':admitted['id']})['result']==data
    assert data['base64'] not in '\n'.join(str(tuple(r)) for r in store.db.execute('SELECT * FROM gui_actions'))
    assert data['base64'] not in json.dumps(store.events(mission))
    gui.images[admitted['id']]=(time.time()-16,data)
    result=gui.result(mission,{'session':'offline-session','id':admitted['id']})['result']
    assert 'base64' not in result and result['capture_available'] is False


def test_controller_restart_and_mission_cancellation_never_re_dispatch_an_application(live):
    store,gui,mission,_=live;gui.application_seen_at=time.time()
    admitted=submit(gui,mission,{'operation':'app.start','program':'approved-terminal'});gui.application_poll(mission)
    recovered=GuiBroker(store);recovered.application_seen_at=time.time()
    assert recovered.application_poll(mission) is None
    assert recovered.result(mission,{'session':'offline-session','id':admitted['id']})['state']=='uncertain'
    next_action=submit(recovered,mission,{'operation':'app.start','program':'approved-terminal'})
    store.request_cancel(mission,'owner-fixture')
    assert recovered.application_poll(mission) is None
    assert store.db.execute('SELECT state FROM gui_actions WHERE id=?',(next_action['id'],)).fetchone()[0]=='uncertain'


def test_export_bytes_expire_and_do_not_enter_mission_ledger_or_observer_snapshot(live):
    store,gui,mission,_=live;gui.application_seen_at=time.time();instance=str(uuid.uuid4())
    admitted=submit(gui,mission,{'operation':'app.export','instance':instance,'file':'result.txt'});gui.application_poll(mission)
    contents=b'private application artifact fixture'
    data={'instance':instance,'file':'result.txt','mime':'application/octet-stream','bytes':len(contents),
        'sha256':hashlib.sha256(contents).hexdigest(),'base64':base64.b64encode(contents).decode()}
    gui.application_acknowledge(admitted['id'],result=data)
    assert gui.result(mission,{'session':'offline-stored','id':admitted['id']})['result']==data
    durable='\n'.join(str(tuple(row)) for row in store.db.execute('SELECT * FROM gui_actions'))+json.dumps(store.events(mission))
    assert data['base64'] not in durable and contents.decode() not in durable
    assert data['base64'] not in json.dumps(gui.application_snapshot(mission))
    gui.images[admitted['id']]=(time.time()-16,data)
    result=gui.result(mission,{'session':'offline-session','id':admitted['id']})['result']
    assert 'base64' not in result and result['artifact_available'] is False


def test_controller_lost_root_receipt_is_uncertain_and_dispatches_only_once(live):
    store,_,mission,_=live
    controller=Controller(store,'ws://offline.invalid',set());controller.current=mission
    controller.gui.application_seen_at=time.time();admitted=submit(controller.gui,mission,{'operation':'app.start','program':'approved-terminal'})
    calls=[]
    def transport(value):
        if value=={'method':'health'}:return {'available':True,'isolation':'private-wayland-rootfs-network','external_network':False}
        calls.append(value);controller.stop.set();raise TimeoutError('offline transport fault')
    controller.application_request=transport
    asyncio.run(controller.application_worker())
    assert len(calls)==1 and calls[0]['id']==admitted['id']
    assert controller.gui.result(mission,{'session':'offline-session','id':admitted['id']})['state']=='uncertain'


def test_observer_snapshot_has_actual_scoped_receipts_and_purges_cancelled_images(live):
    store,gui,mission,_=live;gui.application_seen_at=time.time()
    start=submit(gui,mission,{'operation':'app.start','program':'approved-terminal'});gui.application_poll(mission)
    gui.application_acknowledge(start['id'],result={'instance':start['id'],'program':'approved-terminal','state':'submitted'})
    captured=submit(gui,mission,{'operation':'app.capture','instance':start['id']});gui.application_poll(mission)
    output=io.BytesIO();Image.new('RGB',(80,60),(15,30,70)).save(output,format='PNG');pixels=jpeg_capture(output.getvalue())
    data={'instance':start['id'],'mime':'image/jpeg','bytes':len(pixels),'sha256':hashlib.sha256(pixels).hexdigest(),'base64':base64.b64encode(pixels).decode()}
    gui.application_acknowledge(captured['id'],result=data)
    snapshot=gui.application_snapshot(mission);app=snapshot['applications'][0]
    assert snapshot['mission']==mission and snapshot['mission_active'] and app['jpeg']==data['base64']
    assert app['running'] is None and app['observed_at'] is None  # a screenshot does not certify process state
    foreign=store.create('owner-fixture','foreign','separate application visibility')
    assert gui.application_snapshot(foreign['id'])['applications']==[]
    store.request_cancel(mission,'owner-fixture')
    assert gui.application_snapshot(mission)['applications'][0]['jpeg'] is None
    assert not gui.application_snapshot(mission)['mission_active']


def test_application_authority_outage_expires_pending_requests_without_dispatch(live):
    store,gui,mission,_=live;gui.application_seen_at=time.time()
    admitted=submit(gui,mission,{'operation':'app.start','program':'approved-terminal'})
    store.db.execute('UPDATE gui_actions SET created_at=? WHERE id=?',(time.time()-21,admitted['id']))
    assert gui.application_poll(mission,dispatch=False) is None
    assert store.db.execute('SELECT state,arguments FROM gui_actions WHERE id=?',(admitted['id'],)).fetchone()[0]=='uncertain'
