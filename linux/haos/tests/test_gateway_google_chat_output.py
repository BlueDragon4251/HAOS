"""Prepared Root export and real SQLite/memfd custody; no Google SDK/network."""
import asyncio
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from haos.gateway import GatewayEngine,GatewayPolicy,digest,Conflict
from haos.gateway_google_chat import PreparedGoogleChatPolicy
from haos.gateway_google_chat_output import Output,sealed
from haos.gateway_outbound import Exports,approved
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from haos.store import MissionStore
from test_gateway_google_chat import account,policy,admitted


@pytest.fixture(params=['prepared','public'])
def root_export(tmp_path,request):
    store=MissionStore(tmp_path/'missions.sqlite');engine=GatewayEngine(store);selected=policy(allow_outbound_media=True)
    config=deepcopy({'version':1,'connectors':list(selected.connectors.values()),'bindings':list(selected.bindings.values())})
    policy_type=GatewayPolicy if request.param=='public' else PreparedGoogleChatPolicy
    controller=SimpleNamespace(store=store,url='ws://127.0.0.1/fixture',gateway_policy=lambda:policy_type(config))
    envelope=admitted(selected=selected)['envelope'];envelope['text']='Create a report.'
    mid=asyncio.run(engine.receive(controller.gateway_policy(),'google',envelope,None))['mission_id']
    store.claim();store.session(mid,'native-session','stored-session');store.settle(mid,'completed',result='Report\nMEDIA:/agent/report.pdf')
    engine.refresh(controller.gateway_policy());deliveries=[]
    while True:
        delivery=engine.next_delivery(controller.gateway_policy())
        if delivery is None:break
        deliveries.append(delivery)
    delivery=next(d for d in deliveries if d['event_context']['kind']=='mission.completed')
    try:yield controller,Exports(controller),delivery,config
    finally:store.close()


def test_real_root_controller_manifest_is_original_source_bound_and_export_reads_only_exact_completed_mission_path(root_export,monkeypatch):
    controller,exports,delivery,config=root_export;calls=[]
    def read(url,session,path,current):
        current();calls.append((session,path));return b'%PDF-1.7\nRoot report fixture'
    monkeypatch.setattr('haos.hermes_artifact.read',read)
    args={'delivery':delivery['id'],'attempt':delivery['attempt']};manifest=exports.manifest(args)
    assert manifest['paths']==['/agent/report.pdf'] and manifest['text']=='Mission '+delivery['event_context']['mission_id']+': completed\nReport\n' and manifest['source_sha256']==delivery['event_context']['content_sha256']
    offer=asyncio.run(exports.begin({**args,'path':'/agent/report.pdf'}))
    assert offer['sha256']==hashlib.sha256(b'%PDF-1.7\nRoot report fixture').hexdigest() and calls==[('stored-session','/agent/report.pdf')]
    assert asyncio.run(Exports(controller).begin({**args,'path':'/agent/report.pdf'}))==offer and len(calls)==1
    config['bindings'][0]['allow_outbound_media']=False
    with pytest.raises(PermissionError):exports.chunk({**args,'id':offer['id'],'offset':0})


@pytest.mark.parametrize('case',['unapproved','wrong-path','stale-attempt','expired','unfinished','wrong-session','ordinary-policy'])
def test_root_export_refuses_widened_stale_or_unapproved_google_file_authority_before_any_agent_read(root_export,monkeypatch,case):
    controller,exports,delivery,config=root_export
    monkeypatch.setattr('haos.hermes_artifact.read',lambda *_:pytest.fail('refusal must precede artifact read'))
    args={'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/agent/report.pdf'}
    if case=='unapproved':config['bindings'][0]['allow_outbound_media']=False
    elif case=='wrong-path':args['path']='/owner/private.pdf'
    elif case=='stale-attempt':args['attempt']+=1
    elif case=='expired':controller.store.db.execute('UPDATE gateway_outbox SET lease_until=0')
    elif case=='unfinished':controller.store.db.execute("UPDATE missions SET state='running'")
    elif case=='wrong-session':controller.store.db.execute('UPDATE missions SET stored_session_id=NULL')
    else:
        # Mutating a generic parsed policy cannot open the prepared-only path.
        from haos.gateway import GatewayPolicy
        forged=GatewayPolicy({'version':1,'connectors':[],'bindings':[]});forged.connectors=controller.gateway_policy().connectors;forged.bindings=controller.gateway_policy().bindings
        controller.gateway_policy=lambda:forged
    with pytest.raises((PermissionError,Conflict)):asyncio.run(exports.begin(args))


@pytest.fixture(params=['prepared','public'])
def retained(tmp_path,request):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'native.sqlite',Redactor([]));selected=policy(allow_outbound_media=True)
    if request.param=='public':selected=GatewayPolicy({'version':1,'connectors':list(selected.connectors.values()),'bindings':list(selected.bindings.values())})
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(inbox=inbox,policy=lambda:selected,connector='google'),_haos_google_value=account(),_haos_google_check=lambda:None)
    output=Output(adapter);binding=selected.bindings['owner'];content='Report\nMEDIA:/agent/report.pdf'
    context={'version':1,'mission_id':'local-mission','kind':'mission.completed','source_event':'local-source','state':'completed','phase':'done',
        'request_id':None,'request_method':None,'part':0,'parts':1,'total_bytes':len(content),'content_sha256':hashlib.sha256(content.encode()).hexdigest(),'group_sha256':'a'*64}
    delivery={'id':'b'*64,'binding_id':'owner','binding_digest':digest(binding),'chat':binding['chat'],'scope':binding['scope'],'thread':binding['thread'],
        'event_context':context,'content':content,'attempt':1}
    data=b'%PDF-1.7\nExact approved retained bytes';offer={'id':'c'*64,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()};identity=digest([delivery['id'],offer['id']]);projection={'text':'Report\n','items':[identity]}
    output.db.execute('INSERT INTO google_chat_output_files VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (identity,delivery['id'],'owner',digest(binding),digest(account()),offer['id'],offer['size'],digest(offer),offer['sha256'],'result-0.pdf','application/pdf',data,'retained',1793430000))
    output.db.execute('INSERT INTO google_chat_output_manifests VALUES(?,?,?,?,?,?)',
        (delivery['id'],digest(binding),digest(account()),digest(context),context['content_sha256'],json.dumps(projection,sort_keys=True,separators=(',',':'))))
    try:yield output,delivery,projection,adapter,selected,data
    finally:inbox.close()


def test_retained_google_root_bytes_replay_without_sdk_HTTP_or_opening_any_agent_path(retained):
    output,delivery,projection,adapter,_,data=retained
    assert output.resolve(delivery,projection)[0]['data']==data
    assert asyncio.run(Output(adapter).prepare(delivery,lambda *_:pytest.fail('no repeated Root export')))==projection
    assert output.db.execute('PRAGMA synchronous').fetchone()[0]==2


@pytest.mark.parametrize('change',[
    "UPDATE google_chat_output_files SET data=x'00'", "UPDATE google_chat_output_files SET state='purged',data=x''",
    "UPDATE google_chat_output_files SET state='fetching',data=x''", "UPDATE google_chat_output_files SET credential_scope='foreign'",
    "UPDATE google_chat_output_files SET offer_sha256='foreign'", "UPDATE google_chat_output_files SET filename='../private.pdf'",
    "UPDATE google_chat_output_files SET mime='image/png;secret=reflected'", 'DELETE FROM google_chat_output_files',
    "UPDATE google_chat_output_manifests SET context_sha256='foreign'", 'DELETE FROM google_chat_output_manifests'])
def test_google_output_never_restores_missing_purged_or_corrupt_bytes_or_reuses_foreign_receipts(retained,change):
    output,delivery,projection,_,_,_=retained;output.db.execute(change)
    with pytest.raises(Conflict):output.resolve(delivery,projection)


@pytest.mark.parametrize('case',['body','items','extra','account','binding','thread','private-reflection'])
def test_output_projection_and_materialization_require_current_exact_owner_route_and_root_content(retained,case):
    output,delivery,projection,adapter,selected,data=retained
    if case=='body':projection['text']='Injected text'
    elif case=='items':projection['items']=[]
    elif case=='extra':projection['path']='/owner/private'
    elif case=='account':adapter._haos_google_value['bot_user']='users/998'
    elif case=='binding':selected.bindings['owner']['generation']='f'*64
    elif case=='thread':delivery['thread']='spaces/space1/threads/foreign'
    else:adapter._haos_native.inbox.redactor.secrets=[data.decode()]
    with pytest.raises((PermissionError,Conflict)):output.resolve(delivery,projection)


def test_actual_native_upload_source_memfd_is_sealed_against_rewrite_growth_shrink_and_is_closed_after_use():
    data=b'%PDF-1.7\nImmutable approved fixture'
    with sealed(data) as path:
        assert Path(path).read_bytes()==data
        with open(path,'rb') as stream:assert fcntl.fcntl(stream,getattr(fcntl,'F_GET_SEALS',1034))&getattr(fcntl,'F_SEAL_WRITE',8)
        for mode in ['wb','ab']:
            with pytest.raises(OSError):
                with open(path,mode) as stream:stream.write(b'changed');stream.flush()
        with pytest.raises(OSError):os.truncate(path,1)
    assert not Path(path).exists()
