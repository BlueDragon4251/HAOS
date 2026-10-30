import asyncio
import copy
import base64
from types import SimpleNamespace

import pytest

from haos.gateway import GatewayEngine,GatewayPolicy,digest,Conflict
from haos.gateway_outbound import Exports,marked
from haos.store import MissionStore
from test_gateway_media import config,envelope


@pytest.mark.parametrize('text', ['```\nMEDIA:/private/example.png\n```', '> MEDIA:/private/example.png',
    '{"output":"MEDIA:/private/example.png"}', '/private/example.png'])
def test_examples_json_and_bare_paths_do_not_authorize_exports(text):
    assert marked(text)[0]==[]


@pytest.mark.parametrize('text',['MEDIA:https://host/a.png','MEDIA:/x/unknown.exe','MEDIA:../x.png'])
def test_invalid_media_references_refused(text):
    with pytest.raises(ValueError):marked(text)


@pytest.fixture
def output(tmp_path):
    store=MissionStore(tmp_path/'missions.db');engine=GatewayEngine(store);configuration=config()
    configuration['bindings'][0]['allow_outbound_media']=True
    controller=SimpleNamespace(store=store,url='ws://127.0.0.1/api/ws?token=fixture',gateway_policy=lambda:GatewayPolicy(configuration))
    admitted=asyncio.run(engine.receive(controller.gateway_policy(),'line',envelope(),None))
    mid=admitted['mission_id'];store.claim();store.session(mid,'runtime-id','stored-id')
    store.settle(mid,'completed',result='Result\nMEDIA:/agent/result.png')
    engine.refresh(controller.gateway_policy())
    deliveries=[]
    while True:
        delivery=engine.next_delivery(controller.gateway_policy())
        if delivery is None:break
        deliveries.append(delivery)
    delivery=next(d for d in deliveries if 'MEDIA:' in d['content'])
    yield store,controller,Exports(controller),delivery,configuration
    store.close()


def test_export_snapshot_replay_chunks_and_reopen_do_not_reread_changed_agent_file(output,monkeypatch):
    store,controller,exports,delivery,configuration=output;calls=[]
    def read(url,sid,path,current):
        current();calls.append((sid,path));return b'approved-byte-result'
    monkeypatch.setattr('haos.hermes_artifact.read',read)
    params={'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/agent/result.png'}
    offer=asyncio.run(exports.begin(params));assert calls==[('stored-id','/agent/result.png')]
    assert asyncio.run(Exports(controller).begin(params))==offer and len(calls)==1
    result=exports.chunk({'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':0})
    assert base64.b64decode(result['data'])==b'approved-byte-result'
    configuration['bindings'][0]['allow_outbound_media']=False
    with pytest.raises(PermissionError):exports.chunk({'delivery':delivery['id'],'attempt':delivery['attempt'],'id':offer['id'],'offset':0})


@pytest.mark.parametrize('change',['path','attempt','lease','approval','result','session'])
def test_export_cannot_widen_mission_path_attempt_lease_or_authority(output,monkeypatch,change):
    store,controller,exports,delivery,configuration=output
    monkeypatch.setattr('haos.hermes_artifact.read',lambda *_:pytest.fail('refusal must precede agent request'))
    params={'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/agent/result.png'}
    if change=='path':params['path']='/owner/private.png'
    if change=='attempt':params['attempt']+=1
    if change=='lease':store.db.execute('UPDATE gateway_outbox SET lease_until=0 WHERE id=?',(delivery['id'],))
    if change=='approval':configuration['bindings'][0]['allow_outbound_media']=False
    if change=='result':store.db.execute("UPDATE missions SET result='No file export' WHERE id=?",(store.list()[0]['id'],))
    if change=='session':store.db.execute('UPDATE missions SET stored_session_id=NULL')
    with pytest.raises((PermissionError,Conflict)):asyncio.run(exports.begin(params))


def test_explicit_owner_purge_keeps_snapshot_tombstone_and_blocks_automatic_reexport(output,monkeypatch):
    store,controller,exports,delivery,_=output
    monkeypatch.setattr('haos.hermes_artifact.read',lambda *_:b'approved-bytes')
    params={'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/agent/result.png'}
    offer=asyncio.run(exports.begin(params))
    with pytest.raises(Conflict):GatewayEngine(store).media.purge([offer['id']],'owner:1000','inspected',confirmed=True)
    store.db.execute("UPDATE gateway_outbox SET state='uncertain' WHERE id=?",(delivery['id'],))
    media=GatewayEngine(store).media
    assert media.purge([offer['id']],'owner:1000','inspected',confirmed=True)['removed_payload_bytes']==len(b'approved-bytes')
    assert store.db.execute('SELECT length(data) FROM gateway_output_files WHERE id=?',(offer['id'],)).fetchone()[0]==0
    assert store.db.execute('SELECT actor FROM gateway_output_purge_audit WHERE id=?',(offer['id'],)).fetchone()[0]=='owner:1000'
    store.db.execute("UPDATE gateway_outbox SET state='sending' WHERE id=?",(delivery['id'],))
    with pytest.raises(Conflict):asyncio.run(exports.begin(params))


def test_output_media_line_is_not_split_across_durable_text_chunks(output):
    store,controller,_,delivery,_=output;engine=GatewayEngine(store)
    content='x'*1780+'\nMEDIA:/agent/long-but-explicit-result.png\n'
    engine._queue(delivery['route_id'],'boundary-fixture',content)
    parts=[r[0] for r in store.db.execute('SELECT content FROM gateway_outbox WHERE id IN (?,?) ORDER BY rowid',
        (digest([delivery['route_id'],'boundary-fixture',0]),digest([delivery['route_id'],'boundary-fixture',1])))]
    assert ''.join(parts)==content and len(parts)==2 and marked(parts[1])[0]==['/agent/long-but-explicit-result.png']


@pytest.mark.parametrize('field,value',[('allow_video',1),('allow_outbound_media','yes'),('allow_video',[]),('allow_outbound_media',{})])
def test_new_permissions_are_strict_booleans(field,value):
    c=config();c['bindings'][0][field]=value
    with pytest.raises(ValueError):GatewayPolicy(c)


@pytest.mark.parametrize('length',[0,8*1024*1024+1])
def test_export_does_not_accept_an_unbounded_internal_reader_receipt(output,monkeypatch,length):
    _,_,exports,delivery,_=output
    monkeypatch.setattr('haos.hermes_artifact.read',lambda *_:b'x'*length)
    with pytest.raises(ValueError):asyncio.run(exports.begin({'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/agent/result.png'}))
