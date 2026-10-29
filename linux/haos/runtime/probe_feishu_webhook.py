#!/usr/bin/env python3
"""Actual Feishu signatures/AES/codec and durable ingress over loopback HTTPS."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import ssl
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest,Conflict
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_webhook import Receiver
    from haos.gateway_feishu_listener import application
    from haos.gateway_feishu_admission import Refused
    from haos.gateway_feishu_cache import RawEvents
    from haos.gateway_feishu_ingress import install,dispatch_stored
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    cases=[]
    async def exercise(root):
        from aiohttp import web,ClientSession,TCPConnector
        from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
        tls_value=create(root,'feishu.fixture.invalid');tls_value['public_url']='https://feishu.fixture.invalid/feishu/webhook'
        value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-webhook-fixture','domain':'feishu',
            'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'webhook',
            'verification_token':'private-feishu-verification-fixture','encrypt_key':'private-feishu-encryption-fixture',
            'port':8648,'tls':tls_value}
        binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}
        config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]};epoch=digest(config);live=[True]
        policy=lambda:PreparedFeishuPolicy(config)
        def current():
            if not live[0] or digest(config)!=epoch:raise PermissionError('fixture owner publication withdrawn')
        redactor=Redactor([value['app_secret']]);inbox=NativeInbox(root/'native.db',redactor);originals=RawEvents(root/'originals.db',redactor,current)
        home=root/'home';home.mkdir(mode=0o700)
        env={'HERMES_SAFE_MODE':'1','FEISHU_ALLOWED_USERS':binding['sender'],'FEISHU_ALLOW_ALL_USERS':'false',
            'FEISHU_GROUP_POLICY':'allowlist','GATEWAY_ALLOW_ALL_USERS':'false','FEISHU_REQUIRE_MENTION':'false'}
        with private_scope(home,env):
            from plugins.platforms.feishu.adapter import FeishuAdapter
            from gateway.config import PlatformConfig
            adapter=install(durable_adapter(FeishuAdapter(PlatformConfig(enabled=True))))
        adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox)
        adapter._haos_feishu_check=current;adapter._haos_feishu_value=value;adapter._haos_feishu_raw=originals
        adapter._haos_feishu_home=home;adapter._haos_feishu_environment=env
        observed=[]
        def receive(event):observed.append(event);return True
        adapter.set_durable_message_handler(receive)
        receiver=Receiver(adapter,root/'webhooks.db')
        def event(number,text='Actual authenticated native webhook goal.'):
            stamp=str(int(time.time()*1000)-1000)
            return {'schema':'2.0','header':{'event_id':format(number,'032x'),'event_type':'im.message.receive_v1',
                'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp,'token':value['verification_token']},
                'event':{'sender':{'sender_id':{'open_id':binding['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
                    'message':{'message_id':'om_'+format(number,'032x'),'create_time':stamp,'chat_id':binding['chat'],
                        'chat_type':'p2p','message_type':'text','content':json.dumps({'text':text},ensure_ascii=False)}}}
        def wire(body,encrypted=False):
            plain=json.dumps(body,ensure_ascii=False).encode()
            if not encrypted:return plain
            iv=os.urandom(16);pad=16-len(plain)%16;encryptor=Cipher(algorithms.AES(hashlib.sha256(value['encrypt_key'].encode()).digest()),modes.CBC(iv)).encryptor()
            data=iv+encryptor.update(plain+bytes([pad])*pad)+encryptor.finalize()
            return json.dumps({'encrypt':base64.b64encode(data).decode()}).encode()
        counter=[0]
        def signed(data,stamp=None):
            counter[0]+=1;stamp=str(int(time.time())) if stamp is None else str(stamp);nonce='fixture_nonce_'+str(counter[0])
            signature=hashlib.sha256((stamp+nonce+value['encrypt_key']).encode()+data).hexdigest()
            return {'x-lark-request-timestamp':stamp,'x-lark-request-nonce':nonce,'x-lark-signature':signature,'Content-Type':'application/json'}
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/'certificate.pem',root/'key.pem')
        app=application(receiver);runner=web.AppRunner(app,access_log=None,auto_decompress=False);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=context);await site.start();port=site._server.sockets[0].getsockname()[1]
        trust=ssl.create_default_context(cafile=str(root/'ca.pem'));url='https://localhost:'+str(port)+'/feishu/webhook'
        async def request(session,data,head):
            async with session.post(url,data=data,headers=head) as response:return response.status,await response.text()
        try:
            async with ClientSession(connector=TCPConnector(ssl=trust)) as session:
                raw=wire(event(1));head=signed(raw)
                status,_=await request(session,raw,head);assert status==200
                assert len(observed)==0 and inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
                assert receiver.db.execute("SELECT COUNT(*) FROM feishu_webhook_receipts WHERE state='captured'").fetchone()[0]==1
                cases.append('actual_loopback_HTTPS_ACK_follows_signature_token_owner_checks_wire_original_and_input_commit_before_agent_dispatch')
                key=inbox.db.execute('SELECT id FROM native_inbox').fetchone()[0]
                assert await dispatch_stored(adapter,key) and len(observed)==1
                assert await request(session,raw,head)==(200,'{"code": 0, "msg": "ok"}')
                assert not await dispatch_stored(adapter,key) and len(observed)==1
                cases.append('actual_native_codec_dispatch_and_same_signed_delivery_replay_produce_one_durable_input')
                encrypted=wire(event(2),True);status,_=await request(session,encrypted,signed(encrypted));assert status==200
                row=receiver.db.execute('SELECT wire FROM feishu_webhook_receipts ORDER BY created_at DESC LIMIT 1').fetchone()
                assert bytes(row['wire'])==encrypted and b'Actual authenticated' not in encrypted
                cases.append('actual_Lark_AES_decrypts_independently_encrypted_fixture_and_retains_original_ciphertext_before_ACK')
                challenge=wire({'type':'url_verification','token':value['verification_token'],'challenge':'owner-controlled-fixture'},True)
                status,text=await request(session,challenge,signed(challenge));assert status==200 and json.loads(text)=={'challenge':'owner-controlled-fixture'}
                assert receiver.db.execute('SELECT COUNT(*) FROM feishu_webhook_receipts').fetchone()[0]==2
                cases.append('encrypted_signed_token_verified_URL_challenge_does_not_create_sender_authority_or_mission')
                for label,body,changed in [
                    ('tampered_signature',wire(event(3)),{'x-lark-signature':'0'*64}),
                    ('stale_signature',wire(event(4)),None),
                    ('wrong_token',wire({**event(5),'header':{**event(5)['header'],'token':'wrong-verification-fixture'}}),{}),
                    ('unknown_sender',wire({**event(6),'event':{**event(6)['event'],'sender':{
                        'sender_id':{'open_id':'ou_'+'f'*32},'sender_type':'user','tenant_key':value['tenant_key']}}}),{}),
                ]:
                    auth=signed(body,int(time.time())-600 if changed is None else None);auth.update(changed or {})
                    before=receiver.db.execute('SELECT COUNT(*) FROM feishu_webhook_receipts').fetchone()[0]
                    status,_=await request(session,body,auth);assert status==401,(label,status)
                    assert receiver.db.execute('SELECT COUNT(*) FROM feishu_webhook_receipts').fetchone()[0]==before
                    cases.append(label+'_does_not_fill_private_journals_or_receive_success')
                duplicate=list(head.items())+[('X-Lark-Signature',head['x-lark-signature'])]
                reader,writer=await asyncio.open_connection('localhost',port,ssl=trust,server_hostname='localhost')
                outgoing='POST /feishu/webhook HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: '+str(len(raw))+'\r\n'
                outgoing+=''.join(name+': '+item+'\r\n' for name,item in duplicate)+'\r\n'
                writer.write(outgoing.encode()+raw);await writer.drain()
                response_head=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),5)
                assert response_head.split(b' ',2)[1]==b'401',response_head
                writer.close();await writer.wait_closed()
                cases.append('case_duplicated_signature_header_refused_by_actual_HTTPS_application')
                changed=wire(event(7));same_nonce=dict(head);same_nonce['x-lark-signature']=hashlib.sha256((head['x-lark-request-timestamp']+head['x-lark-request-nonce']+value['encrypt_key']).encode()+changed).hexdigest()
                status,text=await request(session,changed,same_nonce);assert status==503,(status,text)
                assert bytes(receiver.db.execute('SELECT wire FROM feishu_webhook_receipts ORDER BY created_at LIMIT 1').fetchone()[0])==raw
                cases.append('authenticated_nonce_reuse_with_other_message_cannot_overwrite_retained_original')
                # A real SQLite failure after wire commit leaves recoverable original custody.
                originals.db.execute("CREATE TEMP TRIGGER fixture_stop BEFORE INSERT ON feishu_raw_events BEGIN SELECT RAISE(ABORT,'fixture input storage unavailable'); END")
                delayed=wire(event(8),True);old_head=signed(delayed,int(time.time())-299)
                status,_=await request(session,delayed,old_head);assert status==503
                assert receiver.db.execute("SELECT COUNT(*) FROM feishu_webhook_receipts WHERE state='retained'").fetchone()[0]==1
                originals.db.execute('DROP TRIGGER fixture_stop')
                receiver.close();receiver=Receiver(adapter,root/'webhooks.db')
                await asyncio.sleep(2.1)
                try:receiver.receive(old_head,delayed)
                except Refused as error:assert error.reason=='stale-authentication'
                else:raise AssertionError('stale live delivery admitted')
                recovered=receiver.recover();assert len(recovered)==1 and inbox.claim(recovered[0],policy()) is not None
                inbox.retry(recovered[0]);assert receiver.recover()==[]
                cases.append('actual_SQLite_failure_close_reopen_and_real_freshness_expiry_recover_only_previously_authenticated_retained_original')
                # Quota exhaustion fails before any new native input, retaining prior rows.
                pages=receiver.db.execute('PRAGMA page_count').fetchone()[0];receiver.db.execute('PRAGMA max_page_count='+str(pages))
                large=wire(event(9,'🤖'*32000),True);before=inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
                try:receiver.receive(signed(large),large)
                except sqlite3.DatabaseError:pass
                else:raise AssertionError('physical receipt quota did not fail closed')
                assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==before and not receiver.db.in_transaction
                assert receiver.db.execute('SELECT COUNT(*) FROM feishu_webhook_receipts').fetchone()[0]==3
                cases.append('actual_physical_SQLite_receipt_quota_refuses_new_input_without_losing_prior_originals')
                receiver.db.execute('PRAGMA max_page_count=16384')
                reflected=wire(event(10,value['verification_token']))
                try:receiver.receive(signed(reflected),reflected)
                except Refused:pass
                else:raise AssertionError('verification secret became agent text')
                cases.append('webhook_verification_and_encryption_secrets_registered_before_native_agent_text_projection')
                live[0]=False
                try:receiver.receive(head,raw)
                except PermissionError:pass
                else:raise AssertionError('withdrawn publication accepted webhook')
                cases.append('owner_publication_withdrawal_immediately_denies_signed_replay')
        finally:await runner.cleanup();receiver.close();originals.close();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-feishu-webhook-') as directory:asyncio.run(exercise(Path(directory)))
    report={'passed':len(cases),'cases':cases,'actual_native_signature_AES_codec_SQLite_and_verified_HTTPS':True,
        'all_network_targets_loopback_fixtures':True,'public_feishu_enabled':False,
        'kernel_listener_publication_live_account_external_messages_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
