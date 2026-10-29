#!/usr/bin/env python3
"""Native Feishu retained-media/dispatch/controller composition with actual offline local ASR."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));assets=Path(sys.argv[2]).resolve();cases=[]
    async def exercise(root):
        from websockets.asyncio.server import serve
        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter
        from haos.gateway import digest
        from haos.gateway_feishu import PreparedFeishuPolicy,scope as account_scope
        from haos.gateway_feishu_admission import Refused
        from haos.gateway_feishu_ingress import install,capture,dispatch_stored
        from haos.gateway_feishu_cache import RawEvents
        from haos.gateway_ingress import durable_adapter
        from haos.gateway_matrix_profile import scope
        from haos.gateway_media_relay import MediaCache,event_media,forward
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.gateway_runtime import adapter_envelope
        from haos.redaction import Redactor
        from haos.store import MissionStore
        from haos.controller import Controller
        from haos import speech,speech_client
        engine=root/'engine';engine.mkdir();(engine/'config.yaml').write_text('stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n')
        os.environ.update(HERMES_HOME=str(engine),HERMES_SAFE_MODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        audio=(assets/'reference.flac').read_bytes()
        assert hashlib.sha256(audio).hexdigest()=='63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
        value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-voice-fixture','domain':'feishu',
            'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
        binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':account_scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1,'allow_media':True,'allow_voice':False}
        config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]};policy=lambda:PreparedFeishuPolicy(config)
        inbox=NativeInbox(root/'native.db',Redactor([value['app_secret']]));raw=RawEvents(root/'raw.db',inbox.redactor,lambda:None)
        relay=RelayInbox(root/'relay.db',inbox.redactor);cache=MediaCache(inbox)
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
        home=root/'home';home.mkdir(mode=0o700);prompts=[];methods=[];asr=[];revoke=[False]
        env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
            'FEISHU_DOMAIN':value['domain'],'FEISHU_BOT_OPEN_ID':value['bot_open_id'],'FEISHU_ALLOWED_USERS':binding['sender'],
            'FEISHU_ALLOW_ALL_USERS':'false','GATEWAY_ALLOW_ALL_USERS':'false','FEISHU_ALLOW_BOTS':'none',
            'FEISHU_REQUIRE_MENTION':'false','FEISHU_REACTIONS':'false'}
        def create():
            with scope(home,env):adapter=install(durable_adapter(FeishuAdapter(PlatformConfig(enabled=True))))
            adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox)
            adapter._haos_feishu_value=value;adapter._haos_feishu_raw=raw;adapter._haos_feishu_home=home;adapter._haos_feishu_environment=env
            epoch=digest(config)
            def current():
                if digest(config)!=epoch:raise PermissionError('fixture owner publication withdrawn')
            adapter._haos_feishu_check=current
            def receive(event):relay.admit(policy(),'feishu',adapter_envelope(event,'feishu'),media=event_media(event,'feishu'));return True
            adapter.set_durable_message_handler(receive);return adapter
        def resource(number,sender=None):
            stamp=str(int(time.time()*1000)-1000)
            return json.dumps({'schema':'2.0','header':{'event_id':format(number,'032x'),'event_type':'im.message.receive_v1',
                'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
                'event':{'sender':{'sender_id':{'open_id':sender or binding['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
                'message':{'message_id':'om_'+format(number,'032x'),'create_time':stamp,'chat_id':binding['chat'],'chat_type':'p2p',
                    'message_type':'audio','content':json.dumps({'file_key':'file_v3_'+format(number,'016x'),'duration':11000})}}}).encode()
        async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
        async def admit(source,data=audio):
            # Resource retrieval is an explicit fixture. Seed the real private
            # SQLite capability with the exact bytes; do not replace a UID gate
            # or SDK client. Separate real-UID/HTTPS probes exercise retrieval.
            key=capture(adapter,source);original=raw.capture(policy(),'feishu',value,source)
            cached=cache.put(policy(),'feishu',original['envelope'],data,'voice');mime='audio/flac'
            db=inbox.db;db.execute("""CREATE TABLE IF NOT EXISTS feishu_input_media(input_id TEXT NOT NULL,resource_index INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,upload_id TEXT NOT NULL,mime TEXT NOT NULL,PRIMARY KEY(input_id,resource_index))""")
            row=db.execute('SELECT binding_digest,fingerprint FROM native_inbox WHERE id=?',(key,)).fetchone()
            source_proof=digest([row['binding_digest'],row['fingerprint'],original['id'],original['resources'][0]])
            db.execute('INSERT INTO feishu_input_media VALUES(?,?,?,?,?)',(key,0,digest([source_proof,cached['id'],mime]),cached['id'],mime))
            assert await dispatch_stored(adapter,key)
            pending=relay.next(policy());assert pending and len(pending['media'])==1
            result=await forward(policy,'feishu',pending['envelope'],pending['media'],cache,call)
            relay.admitted(pending['id'],result['mission_id']);cache.transferred(pending['media']);return result['mission_id'],pending['media'][0]
        saved=speech_client.transcribe
        async def local_engine(data,current):
            current();asr.append(hashlib.sha256(data).hexdigest())
            result=await asyncio.to_thread(speech.transcribe,data,model_root=assets/'model',model_owner_uid=os.geteuid())
            if revoke[0]:binding['allow_voice']=False
            current();return result
        speech_client.transcribe=local_engine
        async def agent(socket):
            session='feishu-voice-'+str(len(methods))
            async for raw_request in socket:
                request=json.loads(raw_request);method=request['method'];methods.append(method)
                if method=='session.create':result={'session_id':session,'stored_session_id':session+'-durable'}
                elif method=='prompt.submit':
                    text=request['params']['text'];assert 'ask not what your country can do for you' in text.lower()
                    assert '@file:' not in text and 'data:' not in text;prompts.append(text);result={'status':'streaming'}
                else:raise AssertionError('raw Feishu voice reached agent RPC '+method)
                await socket.send(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}))
                if method=='prompt.submit':await socket.send(json.dumps({'method':'event','params':{'type':'message.complete',
                    'session_id':session,'payload':{'status':'complete','text':'Protocol terminal fixture; no model inference'}}}))
        async def execute(mid):
            async with serve(agent,'127.0.0.1',0) as endpoint:
                controller.url='ws://127.0.0.1:'+str(endpoint.sockets[0].getsockname()[1]);row=store.claim();assert row['id']==mid
                await asyncio.wait_for(controller.execute(row),30)
        adapter=create()
        try:
            try:capture(adapter,resource(1))
            except Refused as error:assert error.reason=='media-not-approved'
            else:raise AssertionError('document approval implicitly granted voice')
            assert not asr and inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
            cases.append('voice_without_separate_consent_never_reaches_native_cache_asr_or_mission')
            binding.update(allow_voice=True,generation='c'*64);adapter=create()
            try:capture(adapter,resource(2,sender='ou_'+'f'*32))
            except Refused as error:assert error.reason=='unapproved-route'
            else:raise AssertionError('unknown Feishu audio sender admitted')
            assert not asr
            cases.append('unknown_audio_sender_is_refused_before_native_decode_cache_or_local_asr')
            item=resource(3);mid,identity=await admit(item)
            assert controller.gateway.media.for_mission(policy(),mid)[0]['data']==audio
            await execute(mid)
            assert store.get(mid)['state']=='completed' and len(asr)==1 and len(prompts)==1
            transcript=controller.gateway.media.transcript(policy(),mid,identity)
            assert 'ask what you can do for your country' in transcript['transcript'].lower()
            assert methods==['session.create','prompt.submit']
            cases.append('actual_native_Feishu_media_decode_and_dispatch_relay_controller_and_offline_pinned_asr_reach_prompt_as_text_without_raw_agent_audio_or_inference')
            key=capture(adapter,item);assert not await dispatch_stored(adapter,key)
            assert len(store.list())==1 and len(asr)==1 and relay.next(policy()) is None
            cases.append('retained_Feishu_voice_replay_does_not_redecode_retranscribe_or_create_another_mission')
            invalid,identity=await admit(resource(4),data=b'not-valid-audio');await execute(invalid)
            assert store.get(invalid)['phase']=='pending' and len(prompts)==1
            assert controller.gateway.media.transcript(policy(),invalid,identity) is None
            store.request_cancel(invalid,'owner:0')
            cases.append('invalid_audio_retains_source_and_mission_without_transcript_cache_raw_agent_file_or_model_prompt')
            withdrawn,identity=await admit(resource(5));revoke[0]=True;await execute(withdrawn)
            assert store.get(withdrawn)['phase']=='pending' and len(prompts)==1
            assert store.db.execute('SELECT COUNT(*) FROM gateway_media_transcripts').fetchone()[0]==1
            assert methods==['session.create','prompt.submit','session.create','session.create']
            cases.append('owner_withdrawal_after_actual_local_asr_prevents_transcript_write_and_agent_prompt')
        finally:speech_client.transcribe=saved;store.close();relay.close();raw.close();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-feishu-voice-') as name:asyncio.run(exercise(Path(name)))
    report={'passed':len(cases),'cases':cases,'actual_native_Feishu_decode_retained_media_dispatch_controller_and_local_model':True,
        'source_transport_resource_retrieval_private_speech_transport_and_agent_terminal_are_fixtures':True,'public_registry_activation_established_by_this_probe':False,
        'external_Feishu_account_delivery_llm_inference_or_installed_acceptance':False}
    if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
