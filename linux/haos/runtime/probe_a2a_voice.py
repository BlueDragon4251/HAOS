#!/usr/bin/env python3
"""Native A2A voice -> retained HTTPS media -> controller -> real offline ASR.

Parent IPC, private speech IPC and agent terminal are explicit fixture seams.
The independent installed-process probe covers UID/controller/TLS boundaries.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));assets=Path(sys.argv[2]).resolve();cases=[]
    async def exercise(root):
        from aiohttp import web
        from websockets.asyncio.server import serve
        from gateway.platforms.base import MessageEvent,MessageType
        from haos.gateway import Conflict
        from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
        from haos.gateway_a2a_cache import RawEvents
        from haos.gateway_a2a_tasks import Tasks
        from haos.gateway_a2a_native import build
        from haos.gateway_a2a_ingress import dispatch
        from haos.gateway_a2a_resources import Resources
        from haos.gateway_media_relay import event_scope,event_media,forward
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.gateway_runtime import adapter_envelope
        from haos.redaction import Redactor
        from haos.store import MissionStore
        from haos.controller import Controller
        from haos import speech,speech_client
        from webhook_tls_fixture import create
        audio=(assets/'reference.flac').read_bytes();body=[audio];fetches=[]
        create(root,'a2a.fixture.invalid')
        with socket.socket() as choice:choice.bind(('127.0.0.1',0));port=choice.getsockname()[1]
        origin='https://localhost:'+str(port)
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32,'bob':'private_fixture_bob_'+'b'*32},
            'port':8448,'agent_name':'HAOS','download_origins':{'alice':[origin]},
            'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(root/'certificate.pem').read_text(),
                'private_key':(root/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        binding={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-voice','scope':scope(value,'alice'),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1,'allow_media':True,'allow_voice':False}
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[binding]};policy=lambda:PreparedA2APolicy(config)
        raw=RawEvents(root/'raw.db',Redactor(),lambda:None);inbox=NativeInbox(root/'native.db',raw.redactor)
        relay=RelayInbox(root/'relay.db',raw.redactor);resources=Resources(value,'a2a',policy,lambda:None,raw,inbox)
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
        home=root/'home';home.mkdir(mode=0o700);prompts=[];methods=[];asr=[];revoke=[False];received=[]
        def request(number):return {'jsonrpc':'2.0','id':number,'method':'SendMessage','params':{'message':{
            'messageId':'voice-'+str(number),'contextId':binding['chat'],'role':'ROLE_USER',
            'parts':[{'url':origin+'/voice-'+str(number)+'.flac','filename':'voice.flac','mediaType':'audio/flac'}]}}}
        def capture(number,peer='alice'):return raw.capture(policy(),'a2a',value,peer,json.dumps(request(number)).encode())
        async def download(request):
            assert request.secure and 'Authorization' not in request.headers and 'Cookie' not in request.headers
            fetches.append(request.path);return web.Response(body=body[0],content_type='audio/flac')
        app=web.Application();app.router.add_get('/{path:.*}',download);runner=web.AppRunner(app,access_log=None);await runner.setup()
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        await web.TCPSite(runner,'127.0.0.1',port,ssl_context=tls).start()
        prior=os.environ.get('SSL_CERT_FILE');os.environ['SSL_CERT_FILE']=str(root/'ca.pem');tasks=None;adapter=None
        saved=speech_client.transcribe
        async def local_engine(data,current):
            current();asr.append(len(data))
            result=await asyncio.to_thread(speech.transcribe,data,model_root=assets/'model',model_owner_uid=os.geteuid())
            if revoke[0]:binding['allow_voice']=False
            current();return result
        speech_client.transcribe=local_engine
        async def agent(connection):
            session='a2a-voice-'+str(len(methods))
            async for frame in connection:
                item=json.loads(frame);method=item['method'];methods.append(method)
                if method=='session.create':result={'session_id':session,'stored_session_id':session+'-durable'}
                elif method=='prompt.submit':
                    text=item['params']['text'];assert 'ask not what your country can do for you' in text.lower()
                    assert '@file:' not in text and 'data:' not in text and origin not in text;prompts.append(text);result={'status':'streaming'}
                else:raise AssertionError('raw A2A audio reached agent RPC '+method)
                await connection.send(json.dumps({'jsonrpc':'2.0','id':item['id'],'result':result}))
                if method=='prompt.submit':await connection.send(json.dumps({'method':'event','params':{'type':'message.complete',
                    'session_id':session,'payload':{'status':'complete','text':'Protocol terminal fixture; no inference'}}}))
        async def execute(mid):
            async with serve(agent,'127.0.0.1',0) as endpoint:
                controller.url='ws://127.0.0.1:'+str(endpoint.sockets[0].getsockname()[1]);row=store.claim();assert row['id']==mid
                await asyncio.wait_for(controller.execute(row),30)
        try:
            try:capture(1)
            except PermissionError:pass
            else:raise AssertionError('document approval implicitly granted A2A voice')
            assert not fetches and not asr
            cases.append('separate_voice_permission_precedes_native_task_download_cache_and_asr')
            binding['allow_voice']=True
            try:capture(2,'bob')
            except PermissionError:pass
            else:raise AssertionError('named_but_unapproved_peer_admitted_voice')
            assert not fetches and not asr
            cases.append('named_but_unapproved_peer_cannot_create_task_download_voice_or_use_asr')
            tasks=Tasks(root/'tasks.db','alice',value,lambda:None,policy,connector='a2a')
            async def receive(event,proof,task_id):
                media=await resources.retained(proof)
                mapped=MessageEvent(text=event.text,message_type=MessageType.VOICE,message_id=event.message_id,source=event.source,
                    media_urls=['haos-media:'+item['id'] for item in media],media_types=[item['mime'] for item in media])
                with dispatch(adapter,event,proof,parent_event=mapped),event_scope(mapped,[item['id'] for item in media],mapped.media_types,platform='a2a'):
                    envelope=adapter_envelope(mapped,'a2a');ids=event_media(mapped,'a2a')
                    receipt=inbox.admit(policy(),'a2a',envelope,{'raw_id':proof['id'],'task_id':task_id})
                    relay.admit(policy(),'a2a',envelope,media=ids)
                received.append(task_id);return receipt
            adapter=build(value,'alice',home,lambda:None,policy,tasks,receive)
            async def admit(number):
                proof=capture(number);before=len(received)
                def prepare():
                    with tasks.source('a2a',proof):return adapter._prepare_task(request(number)['params'],'alice')
                terminal,pending=await asyncio.to_thread(prepare);assert terminal is None
                async with asyncio.timeout(10):
                    while len(received)==before:await asyncio.sleep(.01)
                pending_relay=relay.next(policy());assert pending_relay and len(pending_relay['media'])==1
                async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
                result=await forward(policy,'a2a',pending_relay['envelope'],pending_relay['media'],resources.cache,call)
                relay.admitted(pending_relay['id'],result['mission_id']);resources.cache.transferred(pending_relay['media'])
                return result['mission_id'],pending_relay['media'][0],proof
            mid,identity,proof=await admit(3);assert controller.gateway.media.for_mission(policy(),mid)[0]['data']==audio
            await execute(mid);assert store.get(mid)['state']=='completed' and len(prompts)==1 and len(asr)==1
            transcript=controller.gateway.media.transcript(policy(),mid,identity)
            assert 'ask what you can do for your country' in transcript['transcript'].lower()
            assert methods==['session.create','prompt.submit']
            cases.append('actual_native_A2A_MessageEvent_verified_HTTPS_retained_media_controller_and_pinned_offline_ASR_reach_text_prompt_without_raw_audio_or_inference')
            replay=capture(3);assert replay==proof and tasks.by_source(proof['source_key']) is not None
            assert len(fetches)==1 and len(store.list())==1 and relay.next(policy()) is None
            cases.append('retained_voice_source_task_and_relay_receipts_prevent_new_download_asr_or_mission_on_replay')
            body[0]=b'not-valid-audio';invalid,identity,_=await admit(4);await execute(invalid)
            assert store.get(invalid)['phase']=='pending' and len(prompts)==1
            assert controller.gateway.media.transcript(policy(),invalid,identity) is None
            store.request_cancel(invalid,'owner:0')
            cases.append('invalid_audio_retains_source_without_transcript_cache_raw_agent_file_or_prompt')
            body[0]=audio;withdrawn,identity,_=await admit(5);revoke[0]=True;await execute(withdrawn)
            assert store.get(withdrawn)['phase']=='pending' and len(prompts)==1
            assert store.db.execute('SELECT COUNT(*) FROM gateway_media_transcripts').fetchone()[0]==1
            cases.append('owner_voice_withdrawal_after_actual_local_ASR_prevents_transcript_commit_and_agent_prompt')
        finally:
            speech_client.transcribe=saved
            if adapter is not None:await adapter.close_profile()
            if tasks is not None:tasks.close()
            store.close();relay.close();raw.close();inbox.close();await runner.cleanup()
            if prior is None:os.environ.pop('SSL_CERT_FILE',None)
            else:os.environ['SSL_CERT_FILE']=prior
    with tempfile.TemporaryDirectory(prefix='haos-a2a-voice-') as temp:asyncio.run(exercise(Path(temp)))
    report={'passed':len(cases),'cases':cases,'actual_native_A2A_decode_verified_HTTPS_retained_media_controller_and_local_model':True,
        'parent_IPC_private_speech_IPC_and_agent_terminal_are_fixtures':True,'public_activation_live_peer_or_inference':False}
    if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
