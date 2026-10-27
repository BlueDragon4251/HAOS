import asyncio
import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from haos.gateway import GatewayPolicy,GatewayEngine,Conflict
from haos.gateway_media_relay import MediaCache,event_scope,event_media,forward
from haos.gateway_media import describe
from haos.gateway_raw import NativeInbox
from haos.gateway_relay import RelayInbox
from haos.redaction import Redactor
from haos.store import MissionStore


def config():
    return {'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,
        'thread':'','identity':'personal','capabilities':['create'],'allow_media':True,'generation':'b'*64,'since':1}]}


def envelope():
    return {'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'Inspect the attached document.'}


@pytest.fixture
def cache(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.db',Redactor())
    yield inbox,MediaCache(inbox),GatewayPolicy(config()),envelope()
    inbox.close()


def test_context_proof_cannot_be_forged_by_uri_or_a_copied_event(cache):
    inbox,media,policy,event=cache;item=media.put(policy,'line',event,b'document','document')
    native=SimpleNamespace(media_urls=['haos-media:'+item['id']],media_types=['application/octet-stream'])
    with pytest.raises(PermissionError):event_media(native,'line')
    with event_scope(native,[item['id']],['application/octet-stream']):
        assert event_media(native,'line')==[item['id']]
        with pytest.raises(PermissionError):event_media(copy.copy(native),'line')
        with pytest.raises(PermissionError):event_media(native,'telegram')
    with pytest.raises(PermissionError):event_media(native,'line')


def test_private_media_cache_persists_reopen_and_metadata_survives_acknowledged_compaction(cache,tmp_path):
    inbox,media,policy,event=cache;item=media.put(policy,'line',event,b'private document','document')
    other=NativeInbox(tmp_path/'native.db',Redactor())
    try:
        reopened=MediaCache(other);assert reopened.get(policy,item['id'])['data']==b'private document'
        reopened.transferred([item['id']])
        with pytest.raises(Conflict):media.get(policy,item['id'])
        row=inbox.db.execute('SELECT descriptor,data,state FROM native_media_cache').fetchone()
        assert json.loads(row['descriptor'])==describe(b'private document','document') and row['data'] is None and row['state']=='transferred'
    finally:other.close()


@pytest.mark.parametrize('change',[{'allow_media':False},{'generation':'f'*64}])
def test_private_cached_bytes_cannot_outlive_their_owner_grant(cache,change):
    inbox,media,policy,event=cache;item=media.put(policy,'line',event,b'document','document')
    changed=config();changed['bindings'][0].update(change)
    with pytest.raises(PermissionError):media.get(GatewayPolicy(changed),item['id'])
    assert inbox.db.execute('SELECT data FROM native_media_cache').fetchone()[0]==b'document'


def test_binary_credential_reflection_is_refused_before_private_cache_publication(cache):
    inbox,media,policy,event=cache;inbox.redactor=Redactor(['private-fixture-credential'])
    with pytest.raises(PermissionError):media.put(policy,'line',event,b'private-fixture-credential','document')
    assert inbox.db.execute('SELECT COUNT(*) FROM native_media_cache').fetchone()[0]==0


def test_legacy_relay_migration_preserves_text_admission_fingerprint(cache,tmp_path):
    inbox,media,policy,event=cache;relay=RelayInbox(tmp_path/'relay.db',Redactor())
    try:
        first=relay.admit(policy,'line',event);assert relay.next(policy)['media']==[]
        relay.close()
        with sqlite3.connect(tmp_path/'relay.db') as legacy:legacy.execute('ALTER TABLE inbox DROP COLUMN media')
        relay=RelayInbox(tmp_path/'relay.db',Redactor())
        assert relay.next(policy)['id']==first and relay.next(policy)['media']==[]
        item=media.put(policy,'line',event,b'document','document')
        with pytest.raises(Conflict):relay.admit(policy,'line',event,media=[item['id']])
        assert relay.next(policy)['id']==first and relay.next(policy)['media']==[]
    finally:relay.close()


def test_real_chunk_receipt_loss_resumes_and_changed_private_receipts_never_reach_mission(cache,tmp_path):
    inbox,media,policy,event=cache;item=media.put(policy,'line',event,b'd'*60000,'document')
    store=MissionStore(tmp_path/'controller.db');engine=GatewayEngine(store);lost=[True];calls=[]
    async def request(method,params):
        calls.append(method)
        result=engine.media.begin(policy,params) if method.endswith('begin') else engine.media.chunk(policy,params) if method.endswith('chunk') else await engine.receive(policy,params['connector'],params['envelope'],None,media=params['media'])
        if method.endswith('chunk') and lost[0]:lost[0]=False;raise ConnectionError('lost committed receipt')
        return result
    try:
        with pytest.raises(ConnectionError):asyncio.run(forward(lambda:policy,'line',event,[item['id']],media,request))
        assert store.list()==[] and media.get(policy,item['id'])['data']==b'd'*60000
        result=asyncio.run(forward(lambda:policy,'line',event,[item['id']],media,request))
        assert len(store.list())==1 and engine.media.for_mission(policy,result['mission_id'])[0]['data']==b'd'*60000
        assert calls.count('gateway.media.chunk')==2
    finally:store.close()


@pytest.mark.parametrize('message_id,kind',[('../owner','document'),('1','voice'),('1',[]),('', 'image')])
def test_invalid_content_request_fails_before_any_optional_sdk_import(message_id,kind):
    from haos.gateway_line_content import Content
    content=Content('private-fixture-access',Redactor())
    with pytest.raises(ValueError):asyncio.run(content.fetch(message_id,kind,lambda:None))
    assert content.active is None and content.client is None
