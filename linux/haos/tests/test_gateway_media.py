import asyncio
import base64

import pytest

from haos.gateway import GatewayEngine,GatewayPolicy,Conflict
from haos.gateway_media import CHUNK_BYTES,MAX_BYTES,describe,descriptor
from haos.store import MissionStore


def config():
    return {'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_media':True,'generation':'b'*64,'since':1}]}


def envelope():
    return {'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'Inspect the attached document.'}


@pytest.fixture
def media(tmp_path):
    store=MissionStore(tmp_path/'missions.db');engine=GatewayEngine(store)
    yield store,engine,GatewayPolicy(config()),envelope()
    store.close()


def begin(engine,policy,event,data):
    return engine.media.begin(policy,{'connector':'line','envelope':event,'descriptor':describe(data,'document')})


def chunk(engine,policy,identity,offset,data):
    return engine.media.chunk(policy,{'id':identity,'offset':offset,'data':base64.b64encode(data).decode()})


def test_real_sqlite_upload_resumes_after_reopen_and_admission_is_atomic_and_idempotent(media,tmp_path):
    store,engine,policy,event=media;data=b'd'*(CHUNK_BYTES+9000)
    started=begin(engine,policy,event,data)
    assert started['offset']==0 and not started['ready']
    first=chunk(engine,policy,started['id'],0,data[:CHUNK_BYTES]);assert first['offset']==CHUNK_BYTES
    reopened=MissionStore(tmp_path/'missions.db');second=GatewayEngine(reopened)
    try:
        assert begin(second,policy,event,data)==first
        duplicate=chunk(second,policy,started['id'],0,data[:CHUNK_BYTES]);assert duplicate==first
        done=chunk(second,policy,started['id'],CHUNK_BYTES,data[CHUNK_BYTES:]);assert done['ready']
        response=asyncio.run(second.receive(policy,'line',event,None,media=[started['id']]))
        assert second.media.for_mission(policy,response['mission_id'])[0]['data']==data
        assert asyncio.run(second.receive(policy,'line',event,None,media=[started['id']]))==response
        assert len(reopened.list())==1
        with pytest.raises(Conflict):asyncio.run(second.receive(policy,'line',event,None))
    finally:reopened.close()


@pytest.mark.parametrize('change',[{'allow_media':False},{'capabilities':['read'],'allow_media':False},
    {'generation':'a'*64},{'sender':'U'+'e'*32,'chat':'U'+'e'*32}])
def test_grant_withdrawal_or_route_edit_denies_later_chunks_and_dispatch(media,change):
    store,engine,policy,event=media;data=b'owner scoped bytes';started=begin(engine,policy,event,data)
    altered=config();altered['bindings'][0].update(change);changed=GatewayPolicy(altered)
    with pytest.raises(PermissionError):chunk(engine,changed,started['id'],0,data)
    assert store.db.execute('SELECT received FROM gateway_media_uploads').fetchone()[0]==0
    chunk(engine,policy,started['id'],0,data)
    response=asyncio.run(engine.receive(policy,'line',event,None,media=[started['id']]))
    with pytest.raises(PermissionError):engine.media.for_mission(changed,response['mission_id'])


@pytest.mark.parametrize('change',[{'kind':[]},{'format':'../../owner'},{'size':True},{'size':0},{'size':MAX_BYTES+1},
    {'sha256':'bad'},{'path':'/etc/haos/gateway-credentials'},{'url':'https://example.invalid'}])
def test_descriptor_never_admits_host_paths_urls_ambiguous_kinds_or_unbounded_data(change):
    meta=describe(b'data','document');meta.update(change)
    with pytest.raises(ValueError):descriptor(meta)


def test_failed_checksum_offset_or_replay_cannot_publish_changed_bytes(media):
    store,engine,policy,event=media;data=b'correct document';started=begin(engine,policy,event,data)
    with pytest.raises(Conflict):chunk(engine,policy,started['id'],1,data)
    with pytest.raises(Conflict):chunk(engine,policy,started['id'],0,b'changed document')
    assert store.db.execute('SELECT received FROM gateway_media_uploads').fetchone()[0]==0
    chunk(engine,policy,started['id'],0,data)
    with pytest.raises(Conflict):chunk(engine,policy,started['id'],0,b'different bytes!')
    assert store.db.execute('SELECT state FROM gateway_media_uploads').fetchone()[0]=='ready'


def test_wrong_message_media_cannot_create_a_mission_or_leave_partial_routes(media):
    store,engine,policy,event=media;data=b'private file';started=begin(engine,policy,event,data)
    chunk(engine,policy,started['id'],0,data)
    other={**event,'message_id':'f'*64}
    with pytest.raises(PermissionError):asyncio.run(engine.receive(policy,'line',other,None,media=[started['id']]))
    assert store.list()==[]
    assert store.db.execute('SELECT COUNT(*) FROM gateway_routes').fetchone()[0]==0
    assert store.db.execute('SELECT mission_id FROM gateway_media_uploads').fetchone()[0] is None


def test_expired_staging_unknown_ids_and_control_commands_never_attach(media):
    store,engine,policy,event=media;data=b'staged document';started=begin(engine,policy,event,data)
    store.db.execute('UPDATE gateway_media_uploads SET created_at=1')
    with pytest.raises(Conflict):chunk(engine,policy,started['id'],0,data)
    with pytest.raises(Conflict):begin(engine,policy,event,data)
    with pytest.raises(PermissionError):chunk(engine,policy,'f'*64,0,data)
    with pytest.raises(ValueError):begin(engine,policy,{**event,'text':'/cancel id'},data)


def test_private_chunk_corruption_after_admission_is_detected_before_agent_transfer(media):
    store,engine,policy,event=media;data=b'private document';started=begin(engine,policy,event,data)
    chunk(engine,policy,started['id'],0,data)
    response=asyncio.run(engine.receive(policy,'line',event,None,media=[started['id']]))
    store.db.execute('UPDATE gateway_media_chunks SET data=?',(b'x'*len(data),))
    with pytest.raises(Conflict):engine.media.for_mission(policy,response['mission_id'])


def test_legacy_missions_need_no_gateway_configuration_for_media_lookup(media):
    store,engine,policy,event=media
    row=store.create('owner','normal','normal text mission')
    assert not engine.media.has_mission(row['id'])


def test_unknown_media_schema_refuses_reopen_without_destroying_the_original_mission(media,tmp_path):
    store,engine,policy,event=media;row=store.create('owner','kept','preserve this owner mission')
    store.db.execute('UPDATE gateway_media_schema SET version=99')
    other=MissionStore(tmp_path/'missions.db')
    try:
        with pytest.raises(RuntimeError,match='media schema'):GatewayEngine(other)
        assert other.get(row['id'])['goal']=='preserve this owner mission'
    finally:other.close()


def test_private_credentials_cannot_cross_the_binary_boundary_by_hiding_in_a_document(media):
    from haos.redaction import Redactor
    store,engine,policy,event=media;store.redactor=Redactor(['private-controller-fixture-value'])
    data=b'document private-controller-fixture-value bytes';started=begin(engine,policy,event,data)
    with pytest.raises(PermissionError,match='private credential'):chunk(engine,policy,started['id'],0,data)
    assert store.db.execute('SELECT received FROM gateway_media_uploads').fetchone()[0]==0


def test_ready_but_unadmitted_expired_upload_cannot_create_a_mission(media):
    store,engine,policy,event=media;data=b'document';started=begin(engine,policy,event,data)
    chunk(engine,policy,started['id'],0,data);store.db.execute('UPDATE gateway_media_uploads SET created_at=1')
    with pytest.raises(Conflict):asyncio.run(engine.receive(policy,'line',event,None,media=[started['id']]))
    assert store.list()==[]


def test_missing_previously_admitted_attachment_is_not_silently_treated_as_a_text_mission(media):
    store,engine,policy,event=media;data=b'document';started=begin(engine,policy,event,data)
    chunk(engine,policy,started['id'],0,data)
    response=asyncio.run(engine.receive(policy,'line',event,None,media=[started['id']]))
    store.db.execute("UPDATE gateway_media_uploads SET state='purged'")
    assert engine.media.has_mission(response['mission_id'])
    with pytest.raises(Conflict):engine.media.for_mission(policy,response['mission_id'])


def test_aggregate_images_fit_the_existing_model_broker_and_admission_rolls_back_atomically(media):
    from haos.gateway_media import MAX_IMAGE_BYTES
    store,engine,policy,event=media;ids=[]
    for marker in [b'a',b'b']:
        data=b'\x89PNG\r\n\x1a\n'+marker*(MAX_IMAGE_BYTES//2)
        started=engine.media.begin(policy,{'connector':'line','envelope':event,'descriptor':describe(data,'image')})
        for offset in range(0,len(data),CHUNK_BYTES):chunk(engine,policy,started['id'],offset,data[offset:offset+CHUNK_BYTES])
        ids.append(started['id'])
    with pytest.raises(Conflict,match='byte budget'):asyncio.run(engine.receive(policy,'line',event,None,media=ids))
    assert store.list()==[]
    assert store.db.execute('SELECT COUNT(*) FROM gateway_media_uploads WHERE mission_id IS NOT NULL').fetchone()[0]==0


@pytest.mark.parametrize('raw',['!!!!','YWJj\n','YQ==junk','eA== '])
def test_noncanonical_chunk_encoding_is_rejected_before_any_write(media,raw):
    store,engine,policy,event=media;started=begin(engine,policy,event,b'data')
    with pytest.raises(ValueError):engine.media.chunk(policy,{'id':started['id'],'offset':0,'data':raw})
    assert store.db.execute('SELECT COUNT(*) FROM gateway_media_chunks').fetchone()[0]==0


def test_owner_inventory_purge_retains_tombstone_and_audit(media):
    store,engine,policy,event=media
    payload=b'owner-visible retention fixture'
    upload=begin(engine,policy,event,payload)
    chunk(engine,policy,upload['id'],0,payload)
    inventory=engine.media.inventory()
    assert inventory['stored_bytes']==len(payload) and inventory['reserved_bytes']==len(payload)
    assert payload.decode() not in str(inventory) and inventory['uploads'][0]['purge_allowed']
    for actor,note,confirmation in [('gateway:0','inspected',True),('owner:0','',True),('owner:0','inspected',False)]:
        with pytest.raises(PermissionError):engine.media.purge([upload['id']],actor,note,confirmed=confirmation)
    assert engine.media.inventory()['stored_bytes']==len(payload)
    result=engine.media.purge([upload['id']],'owner:1000','Inspected unadmitted payload',confirmed=True)
    assert result['removed_payload_bytes']==len(payload)
    assert engine.media.inventory()['reserved_bytes']==0 and engine.media.inventory()['stored_bytes']==0
    assert engine.media.inventory()['uploads'][0]['state']=='purged'
    assert store.db.execute('SELECT actor FROM gateway_media_purge_audit').fetchone()[0]=='owner:1000'
    assert engine.media.purge([upload['id']],'owner:1000','Repeated receipt',confirmed=True)['removed_payload_bytes']==0
    with pytest.raises(Conflict):begin(engine,policy,event,payload)
    with pytest.raises(Conflict):chunk(engine,policy,upload['id'],0,payload)


def test_owner_purge_batch_atomic_and_terminal_mission_preserved(media):
    store,engine,policy,event=media
    first=begin(engine,policy,event,b'first');chunk(engine,policy,first['id'],0,b'first')
    event2=dict(event,message_id='d'*64)
    second=begin(engine,policy,event2,b'second');chunk(engine,policy,second['id'],0,b'second')
    mission=store.create('gateway:personal','media-retention-fixture','Review payload')
    engine.media.attach(policy,'line',event2,[second['id']],mission['id'])
    with pytest.raises(Conflict):engine.media.purge([first['id'],second['id']],'owner:0','Inspected',confirmed=True)
    assert engine.media.inventory()['stored_bytes']==11
    assert not next(r for r in engine.media.inventory()['uploads'] if r['id']==second['id'])['purge_allowed']
    store.request_cancel(mission['id'],'owner:0')
    engine.media.purge([first['id'],second['id']],'owner:0','Inspected cancelled mission',confirmed=True)
    assert store.get(mission['id'])['state']=='cancelled' and engine.media.has_mission(mission['id'])
    with pytest.raises(Conflict):engine.media.for_mission(policy,mission['id'])
    assert store.db.execute('SELECT COUNT(*) FROM gateway_media_purge_audit').fetchone()[0]==2
