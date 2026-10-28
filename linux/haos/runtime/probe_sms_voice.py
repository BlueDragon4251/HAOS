#!/usr/bin/env python3
"""Native SMS/MMS HTTPS/media/controller/local-STT composition; kernel RPC tested separately."""
import asyncio
import base64
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    assets=Path(sys.argv[2]).resolve();cases=[]
    async def exercise(root):
        import av
        from aiohttp import web,ClientSession,TCPConnector
        from websockets.asyncio.server import serve
        from haos.gateway_sms import PreparedSMSPolicy,scope
        from haos.gateway_runtime import build_adapter
        def build(value,**context):return build_adapter('sms',value,sms_context=context)
        from haos.gateway_media_relay import MediaCache
        from webhook_tls_fixture import create as create_tls
        from haos.gateway_runtime import adapter_envelope
        from haos.gateway_media_relay import event_media,forward
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.redaction import Redactor
        from haos.store import MissionStore
        from haos.controller import Controller
        from haos import speech,speech_client
        home=root/'engine';home.mkdir();(home/'config.yaml').write_text('stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n')
        os.environ.update(HERMES_HOME=str(home),HERMES_SAFE_MODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        original=(assets/'reference.flac').read_bytes()
        assert hashlib.sha256(original).hexdigest()=='63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
        pcm,samples=speech.decode(original);assert samples==176000
        encoded=BytesIO()
        with av.open(encoded,'w',format='mp4') as target:
            stream=target.add_stream('aac',rate=16000);stream.layout='mono'
            with av.open(BytesIO(pcm)) as source:
                for frame in source.decode(audio=0):
                    for packet in stream.encode(frame):target.mux(packet)
                for packet in stream.encode(None):target.mux(packet)
        audio=encoded.getvalue();content_bytes=[audio];revoke_after_asr=[False];downloads=[];accepted=[];prompts=[];native=[];asr=[]
        user='+12025550101';value={'account_sid':'AC'+'a'*32,'auth_token':'c'*32,'from_number':'+12025550100'}
        destination=scope(value)
        config={'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{
            'id':'owner','connector':'sms','sender':user,'chat':user,'scope':destination,'thread':'',
            'identity':'personal','capabilities':['create','read'],'allow_media':False,'allow_voice':False,'generation':'b'*64,'since':1}]}
        policy=lambda:PreparedSMSPolicy(config)
        with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        value.update(port=port,tls=create_tls(root,'sms.fixture.invalid'))
        os.environ['SSL_CERT_FILE']=str(root/'ca.pem')
        inbox=NativeInbox(root/'native.db',Redactor());relay=RelayInbox(root/'relay.db',Redactor());cache=MediaCache(inbox)
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
        profiles=root/'profiles';profiles.mkdir(mode=0o700)
        server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        trusted=ssl.create_default_context(cafile=str(root/'ca.pem'));assert trusted.check_hostname and trusted.verify_mode==ssl.CERT_REQUIRED
        auth='Basic '+base64.b64encode((value['account_sid']+':'+value['auth_token']).encode()).decode();messages={}
        from email.utils import formatdate
        async def info(request):
            assert request.headers['Authorization']==auth
            return web.json_response({'sid':value['account_sid'],'status':'active'})
        async def phones(request):
            assert request.headers['Authorization']==auth and request.query['PhoneNumber']==value['from_number']
            return web.json_response({'incoming_phone_numbers':[{'account_sid':value['account_sid'],'phone_number':value['from_number'],'capabilities':{'sms':True,'mms':True}}]})
        async def resource(request):
            assert request.headers['Authorization']==auth
            fields=messages[request.match_info['identity']]
            return web.json_response({'sid':fields['MessageSid'],'account_sid':value['account_sid'],'from':fields['From'],'to':fields['To'],
                'body':'','direction':'inbound','status':'received','num_media':'1','date_created':fields['created']})
        async def media(request):
            assert request.headers['Authorization']==auth
            return web.json_response({'media_list':[{'sid':'ME'+'f'*32,'account_sid':value['account_sid'],
                'parent_sid':request.match_info['identity'],'content_type':'audio/mp4'}],'next_page_uri':None})
        async def content(request):
            assert request.headers['Authorization']==auth
            downloads.append(request.match_info['identity']);return web.Response(body=content_bytes[0])
        app=web.Application();app.router.add_get('/accounts/{account}.json',info)
        app.router.add_get('/accounts/{account}/IncomingPhoneNumbers.json',phones)
        app.router.add_get('/accounts/{account}/Messages/{identity}.json',resource)
        app.router.add_get('/accounts/{account}/Messages/{identity}/Media.json',media)
        app.router.add_get('/accounts/{account}/Messages/{identity}/Media/{media}',content)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=server_tls);await site.start()
        base='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        def receive(event):
            env=adapter_envelope(event,'sms');ids=event_media(event,'sms')
            relay.admit(policy(),'sms',env,media=ids);accepted.append((env,ids));return True
        def create():
            adapter=build(value,parent=profiles,connector='sms',policy=policy,inbox=inbox)
            adapter._haos_sms_rest._fixture_origin=base+'/accounts/'
            adapter._haos_sms_rest.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
            adapter._haos_sms_rest.client._retry_connection=False
            adapter.set_durable_message_handler(receive);return adapter
        count=[0]
        async def post(sender=user,previous=None):
            count[0]+=1
            event=previous or {'AccountSid':value['account_sid'],'MessageSid':'MM'+f'{count[0]:032x}',
                'From':sender,'To':value['from_number'],'Body':'','NumMedia':'1'}
            if previous is None:messages[event['MessageSid']]={**event,'created':formatdate(time.time(),usegmt=True)}
            from urllib.parse import urlencode
            raw=urlencode(event).encode();material=value['tls']['public_url']+''.join(k+event[k] for k in sorted(event))
            signature=base64.b64encode(hmac.new(value['auth_token'].encode(),material.encode(),hashlib.sha1).digest()).decode()
            async with ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False) as client:
                async with client.post(f'https://localhost:{port}/webhooks/twilio',data=raw,
                    headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature}) as response:assert response.status==200
            return event
        async def until(predicate):
            async with asyncio.timeout(10):
                while not predicate():await asyncio.sleep(.02)
        # Only the private transport is substituted in this composition fixture:
        # invoke the actual local engine, never a canned transcript. Real socket/
        # UID/cancellation are mandatory in the separate kernel process probe.
        saved_client=speech_client.transcribe
        async def local_engine(data,current):
            assert data in {audio,b'not-valid-audio'};current();asr.append(True)
            result=await asyncio.to_thread(speech.transcribe,data,model_root=assets/'model',model_owner_uid=os.geteuid())
            if revoke_after_asr[0]:config['bindings'][0]['allow_voice']=False
            current();return result
        speech_client.transcribe=local_engine
        async def agent(socket):
            async for raw in socket:
                request=json.loads(raw);method=request['method'];native.append(method)
                if method=='session.create':result={'session_id':'voice-composition','stored_session_id':'voice-composition-durable'}
                elif method=='prompt.submit':
                    text=request['params']['text'];assert 'ask not what your country can do for you' in text.lower()
                    assert '@file:' not in text and 'data:' not in text;prompts.append(text);result={'status':'streaming'}
                else:raise AssertionError('raw audio sent to agent: '+method)
                await socket.send(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}))
                if method=='prompt.submit':await socket.send(json.dumps({'method':'event','params':{'type':'message.complete','session_id':'voice-composition',
                    'payload':{'status':'complete','text':'Composition protocol fixture; no LLM inference'}}}))
        adapter=create()
        try:
            assert await adapter.connect();await post();await asyncio.sleep(.25)
            assert not downloads and not accepted
            cases.append('actual_signed_audio_without_separate_voice_grant_never_downloads_or_admits')
            await adapter.close_profile();config['bindings'][0].update(allow_voice=True,generation='d'*64)
            adapter=create();assert await adapter.connect()
            await post(sender='+12025550199');await asyncio.sleep(.25);assert not downloads
            cases.append('actual_unknown_audio_sender_is_refused_before_content_or_local_stt')
            event=await post();await until(lambda:len(accepted)==1)
            env,ids=accepted[0];item=cache.get(policy(),ids[0]);assert item['data']==audio and item['descriptor']['kind']=='voice'
            async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
            admitted=await forward(policy,'sms',env,ids,cache,call)
            relay.admitted(relay.next(policy())['id'],admitted['mission_id']);cache.transferred(ids)
            cases.append('actual_pinned_sms_mms_voice_codec_verified_https_content_context_relay_and_controller_store_preserve_m4a_bytes')
            async with serve(agent,'127.0.0.1',0) as endpoint:
                controller.url='ws://127.0.0.1:'+str(endpoint.sockets[0].getsockname()[1]);row=store.claim();assert row['id']==admitted['mission_id']
                await asyncio.wait_for(controller.execute(row),30)
            assert store.get(row['id'])['state']=='completed' and len(asr)==1 and len(prompts)==1
            assert native==['session.create','prompt.submit']
            receipt=controller.gateway.media.transcript(policy(),row['id'],ids[0]);assert 'ask what you can do for your country' in receipt['transcript'].lower()
            cases.append('actual_local_native_stt_reaches_controller_prompt_as_text_without_raw_audio_agent_rpc_or_llm_inference')
            await post(previous=event);await asyncio.sleep(.25)
            assert len(accepted)==1 and len(downloads)==1 and len(store.list())==1 and len(asr)==1
            cases.append('signed_voice_replay_after_durable_admission_does_not_redownload_retranscribe_or_create_another_mission')
            async def admitted_voice():
                before=len(accepted);await post();await until(lambda:len(accepted)>before)
                env,ids=accepted[-1]
                admission=await forward(policy,'sms',env,ids,cache,call)
                queued=relay.next(policy());assert queued is not None
                relay.admitted(queued['id'],admission['mission_id']);cache.transferred(ids)
                return admission['mission_id']
            content_bytes[0]=b'not-valid-audio';bad=await admitted_voice()
            async with serve(agent,'127.0.0.1',0) as endpoint:
                controller.url='ws://127.0.0.1:'+str(endpoint.sockets[0].getsockname()[1]);row=store.claim();assert row['id']==bad
                await asyncio.wait_for(controller.execute(row),30)
            assert len(prompts)==1 and store.get(bad)['phase']=='pending' and store.get(bad)['state']=='queued'
            assert controller.gateway.media.transcript(policy(),bad,accepted[-1][1][0]) is None
            store.request_cancel(bad,'owner:0')
            cases.append('actual_invalid_audio_decode_preserves_source_and_prevents_transcript_cache_raw_agent_file_and_model_prompt')
            content_bytes[0]=audio;revoked=await admitted_voice();revoke_after_asr[0]=True
            async with serve(agent,'127.0.0.1',0) as endpoint:
                controller.url='ws://127.0.0.1:'+str(endpoint.sockets[0].getsockname()[1]);row=store.claim();assert row['id']==revoked
                await asyncio.wait_for(controller.execute(row),30)
            assert len(prompts)==1 and store.get(revoked)['phase']=='pending'
            assert store.db.execute('SELECT COUNT(*) FROM gateway_media_transcripts').fetchone()[0]==1
            assert native==['session.create','prompt.submit','session.create','session.create']
            cases.append('owner_voice_grant_withdrawal_after_actual_stt_prevents_cache_write_and_agent_prompt')

        finally:
            speech_client.transcribe=saved_client
            await adapter.close_profile();await runner.cleanup();inbox.close();relay.close();store.close()
    with tempfile.TemporaryDirectory(prefix='haos-sms-voice-') as directory:asyncio.run(exercise(Path(directory)))
    report={'passed':len(cases),'cases':cases,'actual_sms_codec_https_controller_and_native_local_model':True,
        'private_speech_transport_and_agent_terminal_are_fixture':True,'tls_verification_disabled':False,
        'external_sms_account_llm_inference_or_installed_acceptance':False}
    if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
