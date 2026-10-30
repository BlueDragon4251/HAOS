#!/usr/bin/env python3
"""Native email MIME/dispatch/controller composition with actual offline local ASR."""
import asyncio
from email.message import EmailMessage
from email import policy as mail_policy
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
        from plugins.platforms.email.adapter import EmailAdapter
        from haos.gateway import digest
        from haos.gateway_email import PreparedEmailPolicy,scope as mailbox_scope
        from haos.gateway_email_admission import approve,Refused
        from haos.gateway_email_ingress import install,capture,dispatch_stored
        from haos.gateway_email_media import manifest
        from haos.gateway_email_cache import RawCache
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
        value={'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'imap.example.invalid','imap_port':993,
            'imap_security':'tls','smtp_host':'smtp.example.invalid','smtp_port':465,'smtp_security':'tls','authserv_id':'mx.example.invalid'}
        binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':mailbox_scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1,'allow_media':True,'allow_voice':False}
        config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]};policy=lambda:PreparedEmailPolicy(config)
        inbox=NativeInbox(root/'native.db',Redactor([value['password']]));raw=RawCache(root/'raw.db',inbox.redactor)
        relay=RelayInbox(root/'relay.db',inbox.redactor);cache=MediaCache(inbox)
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
        home=root/'home';home.mkdir(mode=0o700);prompts=[];methods=[];asr=[];revoke=[False]
        env={'EMAIL_'+key.upper():str(item) for key,item in value.items() if key!='authserv_id'}
        env.update(EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_TRUST_FROM_HEADER='false',EMAIL_ALLOW_ALL_USERS='false',
            GATEWAY_ALLOW_ALL_USERS='false',EMAIL_ALLOWED_USERS='',GATEWAY_ALLOWED_USERS='')
        def create():
            with scope(home,env):adapter=install(durable_adapter(EmailAdapter(PlatformConfig(enabled=True,extra={
                'skip_attachments':True,'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))))
            adapter._haos_native=SimpleNamespace(connector='email',policy=policy,inbox=inbox)
            adapter._haos_email_value=value;adapter._haos_email_raw=raw;adapter._haos_email_home=home;adapter._haos_email_environment=env
            epoch=digest(config)
            def current():
                if digest(config)!=epoch:raise PermissionError('fixture owner publication withdrawn')
            adapter._haos_email_check=current
            def receive(event):relay.admit(policy(),'email',adapter_envelope(event,'email'),media=event_media(event,'email'));return True
            adapter.set_durable_message_handler(receive);return adapter
        def resource(number,data=audio,sender='owner@example.invalid'):
            message=EmailMessage();message['From']=sender;message['To']=value['address'];message['Message-ID']=f'<voice-{number}@example.invalid>'
            message['Authentication-Results']='mx.example.invalid; dmarc=pass';message.set_content('Process the approved voice request.')
            message.add_attachment(data,maintype='audio',subtype='flac',filename='../../private-audio.flac')
            content=message.as_bytes(policy=mail_policy.SMTP)
            item={'uid':number,'uid_validity':77,'uid_next':number+1,'internal_at':time.time()-1,'size':len(content),
                'content':content,'sha256':hashlib.sha256(content).hexdigest(),'mime':manifest(content)}
            item['approval']=approve(policy(),'email',value,item);return item
        async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
        async def admit(item):
            key=capture(adapter,item);assert await dispatch_stored(adapter,key)
            pending=relay.next(policy());assert pending and len(pending['media'])==1
            result=await forward(policy,'email',pending['envelope'],pending['media'],cache,call)
            relay.admitted(pending['id'],result['mission_id']);cache.transferred(pending['media']);return result['mission_id'],pending['media'][0]
        saved=speech_client.transcribe
        async def local_engine(data,current):
            current();asr.append(hashlib.sha256(data).hexdigest())
            result=await asyncio.to_thread(speech.transcribe,data,model_root=assets/'model',model_owner_uid=os.geteuid())
            if revoke[0]:binding['allow_voice']=False
            current();return result
        speech_client.transcribe=local_engine
        async def agent(socket):
            session='email-voice-'+str(len(methods))
            async for raw_request in socket:
                request=json.loads(raw_request);method=request['method'];methods.append(method)
                if method=='session.create':result={'session_id':session,'stored_session_id':session+'-durable'}
                elif method=='prompt.submit':
                    text=request['params']['text'];assert 'ask not what your country can do for you' in text.lower()
                    assert '@file:' not in text and 'data:' not in text;prompts.append(text);result={'status':'streaming'}
                else:raise AssertionError('raw email voice reached agent RPC '+method)
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
            try:resource(2,sender='unknown@example.invalid')
            except Refused as error:assert error.reason=='unapproved-sender'
            else:raise AssertionError('unknown email audio sender admitted')
            assert not asr
            cases.append('unknown_audio_sender_is_refused_before_native_decode_cache_or_local_asr')
            item=resource(3);mid,identity=await admit(item)
            assert controller.gateway.media.for_mission(policy(),mid)[0]['data']==audio
            await execute(mid)
            assert store.get(mid)['state']=='completed' and len(asr)==1 and len(prompts)==1
            transcript=controller.gateway.media.transcript(policy(),mid,identity)
            assert 'ask what you can do for your country' in transcript['transcript'].lower()
            assert methods==['session.create','prompt.submit']
            cases.append('actual_native_mime_and_dispatch_relay_controller_and_offline_pinned_asr_reach_prompt_as_text_without_raw_agent_audio_or_inference')
            key=capture(adapter,item);assert not await dispatch_stored(adapter,key)
            assert len(store.list())==1 and len(asr)==1 and relay.next(policy()) is None
            cases.append('retained_email_voice_replay_does_not_redecode_retranscribe_or_create_another_mission')
            invalid,identity=await admit(resource(4,data=b'not-valid-audio'));await execute(invalid)
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
    with tempfile.TemporaryDirectory(prefix='haos-email-voice-') as name:asyncio.run(exercise(Path(name)))
    report={'passed':len(cases),'cases':cases,'actual_native_email_mime_dispatch_controller_and_local_model':True,
        'private_speech_transport_and_agent_terminal_are_fixtures':True,'public_registry_enabled':True,
        'external_mail_account_delivery_llm_inference_or_installed_acceptance':False}
    if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
