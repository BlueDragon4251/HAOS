#!/usr/bin/env python3
"""Actual native email decoding through private journals, relay and controller missions."""
import asyncio
from email import policy as email_policy
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_email import PreparedEmailPolicy,scope as mailbox_scope
    from haos.gateway_email_admission import approve
    from haos.gateway_email_ingress import capture,dispatch_stored,install
    from haos.gateway_email_cache import RawCache
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_matrix_profile import scope
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
            'imap_security':'tls','smtp_host':'smtp.example.invalid','smtp_port':587,'smtp_security':'starttls','authserv_id':'mx.example.invalid'}
        binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':mailbox_scope(value),
            'thread':'','identity':'personal','capabilities':['create','read','cancel'],'generation':'b'*64,'since':1}
        config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]};policy=lambda:PreparedEmailPolicy(config)
        inbox=NativeInbox(root/'native.db',Redactor([value['password']]));raw=RawCache(root/'raw.db',inbox.redactor)
        relay=RelayInbox(root/'relay.db',inbox.redactor);store=MissionStore(root/'controller.db')
        controller=Controller(store,'unused-local-fixture',set());controller.gateway_policy=policy
        home=root/'home';home.mkdir(mode=0o700)
        env={'EMAIL_'+key.upper():str(item) for key,item in value.items() if key!='authserv_id'}
        env.update(EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_TRUST_FROM_HEADER='false',EMAIL_ALLOW_ALL_USERS='false',
            GATEWAY_ALLOW_ALL_USERS='false',EMAIL_ALLOWED_USERS='',GATEWAY_ALLOWED_USERS='')
        def create():
            with scope(home,env):
                adapter=install(durable_adapter(EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,
                    'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))))
            adapter._haos_native=SimpleNamespace(connector='email',policy=policy,inbox=inbox)
            adapter._haos_email_value=value;adapter._haos_email_raw=raw;adapter._haos_email_home=home;adapter._haos_email_environment=env
            pinned=__import__('haos.gateway',fromlist=['digest']).digest(config)
            def current():
                if __import__('haos.gateway',fromlist=['digest']).digest(config)!=pinned:raise PermissionError('fixture owner publication changed')
            adapter._haos_email_check=current
            def receive(event):relay.admit(policy(),'email',adapter_envelope(event,'email'));return True
            adapter.set_durable_message_handler(receive);return adapter
        adapter=create()
        def resource(number=1,body='An actual scoped email mission',subject='Native email goal'):
            message=EmailMessage();message['From']=binding['sender'];message['To']=value['address']
            message['Message-ID']=f'<goal-{number}@example.invalid>';message['Subject']=subject
            message['Date']='Fri, 1 Jan 1999 00:00:00 +0000';message['Authentication-Results']='mx.example.invalid; dmarc=pass'
            message.set_content(body);data=message.as_bytes(policy=email_policy.SMTP)
            item={'uid':number,'uid_validity':77,'uid_next':number+1,'internal_at':time.time()-1,'size':len(data),'content':data,
                'sha256':hashlib.sha256(data).hexdigest()}
            item['approval']=approve(policy(),'email',value,item);return item
        try:
            item=resource();key=capture(adapter,item)
            assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
            assert relay.next(policy()) is None
            cases.append('approved_actual_native_body_is_durable_before_native_dispatch_or_root_mission')
            assert await dispatch_stored(adapter,key)
            pending=relay.next(policy());assert pending and pending['envelope']['text']=='[Subject: Native email goal]\n\nAn actual scoped email mission'
            assert pending['envelope']['scope']==mailbox_scope(value) and not pending['media']
            admitted=await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':'email','envelope':pending['envelope']}})
            relay.admitted(pending['id'],admitted['mission_id'])
            assert len(store.list())==1 and store.get(admitted['mission_id'])['actor']=='gateway:personal'
            cases.append('actual_pinned_dispatch_source_and_durable_relay_reach_independent_controller_mission_without_model_or_smtp_send')
            assert capture(adapter,item)==key and not await dispatch_stored(adapter,key)
            assert len(store.list())==1 and relay.next(policy()) is None
            cases.append('native_input_replay_after_compaction_never_creates_a_second_mission')
            control=resource(2,body='/status '+admitted['mission_id'],subject='A new subject must not hide the exact command')
            control_key=capture(adapter,control);assert await dispatch_stored(adapter,control_key)
            pending=relay.next(policy());assert pending['envelope']['text']=='/status '+admitted['mission_id']
            await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':'email','envelope':pending['envelope']}})
            assert len(store.list())==1
            cases.append('authenticated_body_control_command_reaches_exact_root_parser_without_subject_reinterpretation_or_new_mission')
            for number,body in [(4,value['password']),(5,'x'*32001)]:
                before=inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
                try:capture(adapter,resource(number,body=body))
                except __import__('haos.gateway_email_admission',fromlist=['Refused']).Refused as error:
                    assert error.reason=='unsupported-content'
                else:raise AssertionError('unsupported native email became a mission source')
                assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==before
            cases.append('credential_reflection_and_oversized_native_goal_are_explicit_source_refusals_without_poisoning_the_receiving_loop')
            captured=capture(adapter,resource(3));binding['generation']='c'*64
            assert not await dispatch_stored(adapter,captured)
            retained=inbox.db.execute('SELECT state,payload FROM native_inbox WHERE id=?',(captured,)).fetchone()
            assert retained['state']=='revoked' and json.loads(retained['payload'])['raw_id']
            assert len(store.list())==1
            cases.append('owner_epoch_withdrawal_after_durable_capture_blocks_dispatch_without_deleting_source')
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
        finally:store.close();relay.close();raw.close();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-email-ingress-') as name:asyncio.run(exercise(Path(name)))
    report={'passed':len(cases),'cases':cases,'actual_native_codec_journals_relay_and_controller':True,
        'account_auth_headers_and_direct_controller_transport_are_fixtures':True,'prepared_only_not_public':True,
        'external_accounts_smtp_messages_model_inference_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
