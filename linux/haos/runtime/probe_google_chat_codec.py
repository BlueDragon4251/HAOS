#!/usr/bin/env python3
"""Actual pinned Google Chat codec and service-account SDK; no live credentials."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    upstream=Path(sys.argv[1]).resolve();sys.path.insert(0,str(upstream));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    assert (upstream/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    with tempfile.TemporaryDirectory(prefix='haos-google-chat-codec-') as directory:
        os.environ['HERMES_HOME']=directory
        from cryptography.hazmat.primitives.asymmetric import rsa,padding
        from cryptography.hazmat.primitives import hashes,serialization
        from google.oauth2 import service_account
        from google.auth import jwt
        from gateway.config import PlatformConfig
        from plugins.platforms.google_chat.adapter import GoogleChatAdapter,_load_sa_credentials_from,_load_google_modules
        from haos.gateway_google_chat import credentials,scope,PreparedGoogleChatPolicy
        from haos.gateway_google_chat_admission import approve,Refused
        from haos.gateway_google_chat_codec import decode_text
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        email='gateway@haos-fixture.iam.gserviceaccount.com'
        sa={'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,'private_key':key.private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),
            'client_email':email,'client_id':'123456789','auth_uri':'https://accounts.google.com/o/oauth2/auth',
            'token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
            'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')}
        value=credentials({'service_account':sa,'bot_user':'users/999','inbound':{'mode':'pubsub',
            'subscription':'projects/haos-fixture/subscriptions/haos-private'}})
        assert _load_google_modules(), "complete frozen Google Chat SDK required"
        native=_load_sa_credentials_from(json.dumps(sa));assert isinstance(native,service_account.Credentials)
        assertion=native._make_authorization_grant_assertion();claims=jwt.decode(assertion,verify=False)
        assert claims['iss']==email and claims['aud']=='https://oauth2.googleapis.com/token'
        assert set(claims['scope'].split())=={'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'}
        import base64
        payload,signature=assertion.rsplit(b'.',1);key.public_key().verify(base64.urlsafe_b64decode(signature+b'='*(-len(signature)%4)),payload,padding.PKCS1v15(),hashes.SHA256())
        cases=['actual_native_service_account_loader_uses_frozen_Google_SDK_and_exact_RSA_signed_bot_pubsub_scopes_without_ADC_or_live_network']
        adapter=GoogleChatAdapter(PlatformConfig(enabled=True,extra={'service_account_json':json.dumps(sa)}))
        async def run():
            for space_type in ['SPACE','DIRECT_MESSAGE']:
                binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
                    'scope':scope(value),'identity':'personal','capabilities':['create','read'],'generation':'a'*64,
                    'since':int(datetime.now(timezone.utc).timestamp()*1000)-60000,'require_mention':True}
                policy=PreparedGoogleChatPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]})
                msg={'name':'spaces/room1/messages/msg1','sender':{'type':'HUMAN','name':'users/123','email':'mutable@example.invalid'},
                    'thread':{'name':binding['thread']},'createTime':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                    'text':'<users/999> /status','argumentText':'/status',
                    'annotations':[{'type':'USER_MENTION','userMention':{'user':{'name':'users/999'}}}]}
                space={'name':binding['chat'],'spaceType':space_type}
                for fmt,data in [('native',{'type':'MESSAGE','message':msg,'space':space}),('addons',{'chat':{'messagePayload':{'message':msg,'space':space}}})]:
                    raw=json.dumps(data).encode();approved=approve(policy,'google',value,raw)
                    for _ in range(2):
                        event=await decode_text(adapter,policy,'google',value,raw,approved)
                        assert event.text=='/status' and event.source.user_id=='users/123' and event.source.thread_id==binding['thread']
                        assert event.source.scope_id==binding['scope'] and event.message_id==msg['name']
                    cases.append('actual_native_'+fmt+'_'+space_type+'_codec_preserves_exact_stable_sender_and_thread_on_replay_despite_mutable_email_and_native_DM_counter')
                    changed=deepcopy(data)
                    changed_msg=changed['message'] if fmt=='native' else changed['chat']['messagePayload']['message']
                    changed_msg['argumentText']='/cancel mission'
                    try:await decode_text(adapter,policy,'google',value,json.dumps(changed).encode(),approved)
                    except PermissionError:pass
                    else:raise AssertionError('changed original reused independent source approval')
                policy.bindings.clear()
                try:await decode_text(adapter,policy,'google',value,raw,approved)
                except PermissionError:pass
                else:raise AssertionError('withdrawn source reached native codec')
                cases.append('withdrawn_'+space_type+'_grant_or_changed_original_refused_before_native_decode')
        asyncio.run(run())
        receipt={'passed':len(cases),'cases':cases,'pinned_Hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
            'native_adapter_sha256':hashlib.sha256((upstream/'plugins/platforms/google_chat/adapter.py').read_bytes()).hexdigest(),
            'actual_native_codec_and_service_account_SDK':True,'ephemeral_local_RSA_key_only':True,
            'transport_AUTH_persistence_UID_mission_media_GUI_live_account_or_public_activation':False}
        Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases)}))


if __name__=='__main__':main()
