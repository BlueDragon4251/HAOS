import asyncio
import base64
import json

import pytest

from haos.controller import Controller
from haos.gateway import GatewayPolicy
from haos.gateway_media import describe
from haos.store import MissionStore


@pytest.mark.parametrize('mode',['media','plain','revoked','refused'])
def test_real_controller_websocket_orders_attachments_before_model_prompt_and_stops_on_revocation(tmp_path,mode):
    async def exercise():
        from websockets.asyncio.server import serve
        store=MissionStore(tmp_path/'controller.db');controller=Controller(store,'unused',set());seen=[]
        user='U'+'a'*32;scope='U'+'d'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':scope,'thread':'',
            'identity':'personal','capabilities':['create','read'],'allow_media':True,'generation':'b'*64,'since':1}]}
        policy=lambda:GatewayPolicy(config)
        controller.gateway_policy=policy
        async def handler(socket):
            async for frame in socket:
                call=json.loads(frame);method=call['method'];seen.append(method);params=call['params']
                if method=='session.create':result={'session_id':'actual-fixture-session','stored_session_id':'durable-fixture-session'}
                elif method=='file.attach':
                    assert 'path' not in params and base64.b64decode(params['data_url'].split(',',1)[1])==b'private document'
                    result={'attached':mode!='refused','uploaded':True,'name':params['name'],'ref_text':'@file:attachments/'+params['name']}
                    if mode=='revoked':config['bindings'][0]['allow_media']=False
                elif method=='prompt.submit':
                    if mode=='media':assert '@file:attachments/attachment-' in params['text']
                    assert controller.store.get(row['id'])['phase']=='dispatching'
                    result={'status':'streaming'}
                else:raise AssertionError(method)
                await socket.send(json.dumps({'jsonrpc':'2.0','id':call['id'],'result':result}))
                if method=='prompt.submit':
                    await socket.send(json.dumps({'method':'event','params':{'type':'message.complete',
                        'session_id':'actual-fixture-session','payload':{'status':'complete','text':'Local websocket fixture receipt'}}}))
        try:
            if mode=='plain':
                row=store.create('owner','plain','plain mission')
                def denied_policy():raise AssertionError('plain mission read optional gateway configuration')
                controller.gateway_policy=denied_policy
            else:
                event={'platform':'line','sender':user,'chat':user,'scope':scope,'thread':'',
                    'message_id':'c'*64,'is_bot':False,'text':'Inspect the attached document.'}
                started=controller.gateway.media.begin(policy(),{'connector':'line','envelope':event,'descriptor':describe(b'private document','document')})
                controller.gateway.media.chunk(policy(),{'id':started['id'],'offset':0,'data':base64.b64encode(b'private document').decode()})
                admitted=await controller.gateway.receive(policy(),'line',event,controller,media=[started['id']])
                row=store.get(admitted['mission_id'])
            row=store.claim();assert row
            async with serve(handler,'127.0.0.1',0) as server:
                controller.url='ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])
                await asyncio.wait_for(controller.execute(row),5)
            if mode in {'revoked','refused'}:
                assert seen==['session.create','file.attach']
                assert store.get(row['id'])['state']=='queued' and store.get(row['id'])['phase']=='pending'
                assert not any(event['kind']=='mission.dispatching' for event in store.events(row['id']))
            else:
                assert seen==(['session.create','prompt.submit'] if mode=='plain' else ['session.create','file.attach','prompt.submit'])
                assert store.get(row['id'])['state']=='completed'
        finally:store.close()
    asyncio.run(exercise())


def test_owner_dispatch_cannot_impersonate_the_private_gateway_media_interface(tmp_path):
    store=MissionStore(tmp_path/'controller.db');controller=Controller(store,'unused',set())
    try:
        with pytest.raises(ValueError):asyncio.run(controller.dispatch('uid:65534',{'method':'gateway.media.begin','params':{}}))
        assert store.db.execute('SELECT COUNT(*) FROM gateway_media_uploads').fetchone()[0]==0
    finally:store.close()


@pytest.mark.parametrize('mode',['fresh','cached','revoked','refused','cancelled'])
def test_controller_voice_uses_bound_local_transcript_never_raw_agent_file_and_stops_before_prompt(tmp_path,monkeypatch,mode):
    from haos import speech_client
    from haos.speech_model import REVISION
    from haos.speech import SpeechRefused
    import hashlib
    async def exercise():
        from websockets.asyncio.server import serve
        store=MissionStore(tmp_path/'controller.db');controller=Controller(store,'unused',set());seen=[];calls=[]
        user='U'+'a'*32;scope='U'+'d'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':scope,'thread':'',
            'identity':'personal','capabilities':['create','read'],'allow_voice':True,'allow_media':False,'generation':'b'*64,'since':1}]}
        policy=lambda:GatewayPolicy(config);controller.gateway_policy=policy
        event={'platform':'line','sender':user,'chat':user,'scope':scope,'thread':'','message_id':'c'*64,
            'is_bot':False,'text':'Process approved voice request'}
        data=b'unit controller audio bytes; actual ASR tested separately'
        receipt={'transcript':'unit protocol request; actual native ASR has independent fixtures','source_sha256':hashlib.sha256(data).hexdigest(),
            'samples':16000,'sample_rate':16000,'model_revision':REVISION,'provider':'local'}
        async def local_fixture(audio,current):
            assert audio==data;calls.append(True);current()
            if mode=='revoked':config['bindings'][0]['allow_voice']=False;current()
            if mode=='cancelled':store.request_cancel(row['id'],'owner:0');current()
            if mode=='refused':raise SpeechRefused('unit unavailable fixture')
            return receipt
        monkeypatch.setattr(speech_client,'transcribe',local_fixture)
        async def handler(socket):
            async for frame in socket:
                call=json.loads(frame);method=call['method'];seen.append(method)
                if method=='session.create':reply={'session_id':'voice-fixture','stored_session_id':'voice-durable'}
                elif method=='prompt.submit':
                    assert receipt['transcript'] in call['params']['text']
                    assert '@file:' not in call['params']['text'] and 'data:' not in call['params']['text']
                    assert store.get(row['id'])['phase']=='dispatching';reply={'status':'streaming'}
                else:raise AssertionError('raw audio reached native agent RPC: '+method)
                await socket.send(json.dumps({'jsonrpc':'2.0','id':call['id'],'result':reply}))
                if method=='prompt.submit':
                    await socket.send(json.dumps({'method':'event','params':{'type':'message.complete','session_id':'voice-fixture',
                        'payload':{'status':'complete','text':'unit protocol terminal receipt'}}}))
        try:
            started=controller.gateway.media.begin(policy(),{'connector':'line','envelope':event,'descriptor':describe(data,'voice')})
            controller.gateway.media.chunk(policy(),{'id':started['id'],'offset':0,'data':base64.b64encode(data).decode()})
            admitted=await controller.gateway.receive(policy(),'line',event,controller,media=[started['id']])
            if mode=='cached':controller.gateway.media.save_transcript(policy(),admitted['mission_id'],started['id'],receipt)
            row=store.claim()
            assert row['id']==admitted['mission_id']
            async with serve(handler,'127.0.0.1',0) as server:
                controller.url='ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])
                await asyncio.wait_for(controller.execute(row),5)
            if mode in {'fresh','cached'}:
                assert seen==['session.create','prompt.submit'] and store.get(row['id'])['state']=='completed'
                assert controller.gateway.media.transcript(policy(),row['id'],started['id'])==receipt
                assert len(calls)==(0 if mode=='cached' else 1)
            else:
                assert seen==['session.create'] and store.get(row['id'])['phase']!='dispatching'
                assert store.db.execute('SELECT COUNT(*) FROM gateway_media_transcripts').fetchone()[0]==0
                if mode=='cancelled':assert store.get(row['id'])['state']=='cancelled'
        finally:store.close()
    asyncio.run(exercise())


def test_raw_gateway_voice_cannot_be_accidentally_forwarded_by_attachment_helper():
    from haos.hermes_media import attach
    from haos.gateway_media import describe
    class Connection:
        async def request(self,*_args,**_kwargs):raise AssertionError('raw voice reached agent RPC')
    data=b'private audio source'
    with pytest.raises(ValueError,match='isolated transcription'):
        asyncio.run(attach(Connection(),'native-session',[{'descriptor':describe(data,'voice'),'data':data}]))
