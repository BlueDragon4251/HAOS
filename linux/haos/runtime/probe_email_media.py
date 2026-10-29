#!/usr/bin/env python3
"""Actual native MIME cache/dispatch into retained media and controller custody."""
import asyncio
from email.message import EmailMessage
from email import policy as mail_policy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import wave


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
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
    from gateway.config import PlatformConfig
    from plugins.platforms.email.adapter import EmailAdapter
    cases=[]
    async def exercise(root):
        os.environ['HERMES_SAFE_MODE']='1'
        value={'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'imap.example.invalid','imap_port':993,
            'imap_security':'tls','smtp_host':'smtp.example.invalid','smtp_port':465,'smtp_security':'tls','authserv_id':'mx.example.invalid'}
        binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':mailbox_scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1,
            'allow_media':True,'allow_voice':True,'allow_video':True}
        config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]};policy=lambda:PreparedEmailPolicy(config)
        inbox=NativeInbox(root/'native.db',Redactor([value['password']]));raw=RawCache(root/'raw.db',inbox.redactor)
        relay=RelayInbox(root/'relay.db',inbox.redactor);cache=MediaCache(inbox)
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused-fixture',set());controller.gateway_policy=policy
        home=root/'home';home.mkdir(mode=0o700);observed=[]
        owner=root/'owner-secret.png';owner.write_bytes(b'preserve-existing-owner-fixture')
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
            def receive(event):
                envelope=adapter_envelope(event,'email');ids=event_media(event,'email')
                observed.append((event,envelope,ids));relay.admit(policy(),'email',envelope,media=ids);return True
            adapter.set_durable_message_handler(receive);return adapter
        audio=BytesIO()
        with wave.open(audio,'wb') as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0'*3200)
        png=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082')
        video=(24).to_bytes(4,'big')+b'ftypisom'+b'\0'*12
        sources=[(png,'image/png','../../owner-secret.png'),(b'An actual bounded document.','application/pdf','../../private-document.pdf'),
            (audio.getvalue(),'audio/wav','voice.wav'),(video,'video/mp4','clip.mp4')]
        def resource(number,items=sources,body='Inspect all approved attachments.'):
            message=EmailMessage();message['From']=binding['sender'];message['To']=value['address']
            message['Message-ID']=f'<media-{number}@example.invalid>';message['Subject']='Native MIME attachments'
            message['Authentication-Results']='mx.example.invalid; dmarc=pass';message.set_content(body)
            for data,mime,name in items:
                major,minor=mime.split('/');message.add_attachment(data,maintype=major,subtype=minor,filename=name)
            content=message.as_bytes(policy=mail_policy.SMTP)
            item={'uid':number,'uid_validity':77,'uid_next':number+1,'internal_at':time.time()-1,'size':len(content),
                'content':content,'sha256':hashlib.sha256(content).hexdigest(),'mime':manifest(content)}
            item['approval']=approve(policy(),'email',value,item);return item
        adapter=create()
        async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
        try:
            item=resource(1);key=capture(adapter,item)
            assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
            assert cache.owner_inventory(policy())['stored_bytes']==0
            cases.append('exact_manifest_is_retained_before_native_attachment_codec_or_mission_admission')
            assert await dispatch_stored(adapter,key)
            pending=relay.next(policy());assert pending and len(pending['media'])==4
            assert len(observed)==1 and observed[0][2]==pending['media']
            assert all(url.startswith('haos-media:') for url in observed[0][0].media_urls)
            assert not list(home.glob('mime-*')) and owner.read_bytes()==b'preserve-existing-owner-fixture'
            cases.append('actual_unmodified_native_attachment_cache_and_dispatch_leave_no_host_paths_or_original_filename_escape_in_the_event')
            admitted=await forward(policy,'email',pending['envelope'],pending['media'],cache,call)
            relay.admitted(pending['id'],admitted['mission_id']);cache.transferred(pending['media'])
            controller.gateway.media.check_mission(policy(),admitted['mission_id'])
            retained=controller.gateway.media.for_mission(policy(),admitted['mission_id'])
            assert [row['descriptor']['kind'] for row in retained]==['image','document','voice','video']
            for row,(data,_mime,_name) in zip(retained,sources):
                assert row['data']==data
            cases.append('actual_native_mime_bytes_cross_durable_relay_into_exact_independent_controller_image_document_voice_and_video_custody')
            assert capture(adapter,item)==key and not await dispatch_stored(adapter,key)
            assert len(store.list())==1 and relay.next(policy()) is None and cache.owner_inventory(policy())['stored_bytes']==0
            cases.append('source_and_media_replay_after_controller_ack_and_transient_compaction_never_create_a_second_mission')
            binding['allow_voice']=False;adapter=create();before=inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
            try:capture(adapter,resource(2))
            except Refused as error:assert error.reason=='media-not-approved'
            else:raise AssertionError('media approval implicitly granted voice')
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==before
            cases.append('image_document_consent_does_not_approve_voice_or_partially_admit_a_mixed_message')
            binding['allow_voice']=True;adapter=create()
            try:capture(adapter,resource(3,body='/cancel an-existing-mission'))
            except Refused as error:assert error.reason=='unsupported-content'
            else:raise AssertionError('attachments changed control into an agent mission')
            cases.append('exact_control_commands_with_attachments_are_refused_instead_of_reinterpreted')
            pending_key=capture(adapter,resource(4));binding['generation']='c'*64
            assert not await dispatch_stored(adapter,pending_key)
            assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(pending_key,)).fetchone()[0]=='revoked'
            assert len(store.list())==1 and raw.db.execute('SELECT COUNT(*) FROM email_raw_messages').fetchone()[0]==2
            cases.append('owner_withdrawal_between_full_source_capture_and_attachment_decode_retains_source_without_upload_or_execution')
        finally:store.close();relay.close();raw.close();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-email-media-') as name:asyncio.run(exercise(Path(name)))
    report={'passed':len(cases),'cases':cases,'actual_native_attachment_cache_dispatch_relay_and_controller':True,
        'public_registry_enabled':True,'headers_accounts_and_controller_transport_are_fixtures':True,
        'external_delivery_agent_backend_or_local_asr_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
