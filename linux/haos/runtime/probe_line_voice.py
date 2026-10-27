#!/usr/bin/env python3
"""Native LINE HTTPS/media/controller/local-STT composition; kernel RPC tested separately."""
import asyncio
import base64
from datetime import datetime,timezone,timedelta
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
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        from websockets.asyncio.server import serve
        from haos.gateway import GatewayPolicy
        from haos.gateway_runtime import build_adapter,adapter_envelope
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
        user='U'+'a'*32;destination='U'+'d'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'',
            'identity':'personal','capabilities':['create','read'],'allow_media':False,'allow_voice':False,'generation':'b'*64,'since':1}]}
        policy=lambda:GatewayPolicy(config)
        with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        value={'channel_secret':'c'*32,'channel_access_token':'private-line-voice-fixture','destination':destination,'port':port}
        inbox=NativeInbox(root/'native.db',Redactor());relay=RelayInbox(root/'relay.db',Redactor())
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
        profiles=root/'profiles';profiles.mkdir(mode=0o700)
        key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False)
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
        certificate=root/'api.pem';certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private=root/'api.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(certificate,private)
        trusted=ssl.create_default_context(cafile=str(certificate));assert trusted.check_hostname and trusted.verify_mode==ssl.CERT_REQUIRED
        async def info(_request):return web.json_response({'userId':destination})
        async def content(request):
            assert request.headers['Authorization']=='Bearer '+value['channel_access_token']
            downloads.append(request.match_info['identity']);return web.Response(body=content_bytes[0])
        app=web.Application();app.router.add_get('/info',info);app.router.add_get('/content/{identity}',content)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=server_tls);await site.start()
        base='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        def receive(event):
            env=adapter_envelope(event,'line');ids=event_media(event,'line')
            relay.admit(policy(),'line',env,media=ids);accepted.append((env,ids));return True
        def create():
            adapter=build_adapter('line',value,line_context={'parent':profiles,'connector':'line','policy':policy,'inbox':inbox})
            adapter._haos_line_identity._target=base+'/info';adapter._haos_line_identity.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
            adapter._haos_line_identity.client._retry_connection=False
            adapter._haos_line_content._target=base+'/content/{message_id}';adapter._haos_line_content.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
            adapter._haos_line_content.client._retry_connection=False
            adapter.set_durable_message_handler(receive);return adapter
        count=[0]
        async def post(sender=user,previous=None,**changes):
            count[0]+=1
            event=previous or {'type':'message','mode':'active','source':{'type':'user','userId':sender},'timestamp':int(time.time()*1000),
                'webhookEventId':'01K8'+f'{count[0]:022d}','replyToken':'private-unused-voice-reply',
                'message':{'type':'audio','id':str(200000+count[0]),'duration':11000,'contentProvider':{'type':'line'}}}
            event['message'].update(changes)
            raw=json.dumps({'destination':destination,'events':[event]}).encode();signature=base64.b64encode(hmac.new(value['channel_secret'].encode(),raw,hashlib.sha256).digest()).decode()
            async with ClientSession() as client:
                async with client.post(f'http://127.0.0.1:{port}/line/webhook',data=raw,headers={'X-Line-Signature':signature}) as response:assert response.status==200
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
            await post(sender='U'+'e'*32);await asyncio.sleep(.25);assert not downloads
            cases.append('actual_unknown_audio_sender_is_refused_before_content_or_local_stt')
            before=len(downloads);await post(duration=120001);await post(duration=True);await asyncio.sleep(.25);assert len(downloads)==before
            cases.append('signed_audio_declared_over_duration_or_boolean_duration_refused_before_download')
            event=await post();await until(lambda:len(accepted)==1)
            env,ids=accepted[0];item=adapter._haos_media_cache.get(policy(),ids[0]);assert item['data']==audio and item['descriptor']['kind']=='voice'
            async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
            admitted=await forward(policy,'line',env,ids,adapter._haos_media_cache,call)
            relay.admitted(relay.next(policy())['id'],admitted['mission_id']);adapter._haos_media_cache.transferred(ids)
            cases.append('actual_pinned_line_voice_codec_verified_https_content_context_relay_and_controller_store_preserve_m4a_bytes')
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
                admission=await forward(policy,'line',env,ids,adapter._haos_media_cache,call)
                queued=relay.next(policy());assert queued is not None
                relay.admitted(queued['id'],admission['mission_id']);adapter._haos_media_cache.transferred(ids)
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
    with tempfile.TemporaryDirectory(prefix='haos-line-voice-') as directory:asyncio.run(exercise(Path(directory)))
    report={'passed':len(cases),'cases':cases,'actual_line_codec_https_controller_and_native_local_model':True,
        'private_speech_transport_and_agent_terminal_are_fixture':True,'tls_verification_disabled':False,
        'external_line_account_llm_inference_or_installed_acceptance':False}
    if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
