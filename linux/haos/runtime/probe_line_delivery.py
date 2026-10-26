#!/usr/bin/env python3
"""Actual native LINE text codec/push HTTP and observable private write intent."""
import asyncio
import copy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import sqlite3
import ssl
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_line_ingress import PreparedLINEPolicy,install
    from haos.gateway_line_delivery import Publisher
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_delivery import delivery_result
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        from aiohttp import web,ClientSession,TCPConnector
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from plugins.platforms.line.adapter import LineAdapter,_text_messages
        user='U'+'a'*32;destination='U'+'d'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'',
            'identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
        inbox=NativeInbox(directory/'native.db',Redactor());policy=lambda:PreparedLINEPolicy(config)
        adapter=install(durable_adapter(LineAdapter(PlatformConfig(enabled=True,extra={
            'channel_secret':'private-disposable-channel-secret','channel_access_token':'private-disposable-access-token'}))))
        adapter._haos_native=SimpleNamespace(connector='line',policy=policy,inbox=inbox)
        publisher=Publisher(adapter);binding=copy.deepcopy(config['bindings'][0]);requests=[];mode=['success'];current_id=['a'*64];foreign=[]
        hang_started=asyncio.Event();hang_release=asyncio.Event()
        async def receive(request):
            body=await request.json();requests.append(body)
            with sqlite3.connect(directory/'native.db') as observer:
                assert observer.execute('SELECT state FROM line_delivery_intents WHERE delivery_id=? AND attempt=1',(current_id[0],)).fetchone()==('writing',)
            assert request.headers.get('Authorization')=='Bearer '+adapter.channel_access_token
            assert body['to']==user and 1<=len(body['messages'])<=5
            status=mode[0]
            if status=='hang':hang_started.set();await hang_release.wait()
            if status=='redirect':return web.Response(status=307,headers={'Location':str(request.url.with_path('/foreign'))})
            if status=='abort':request.transport.close();return web.Response(status=200)
            if isinstance(status,int):return web.Response(status=status,headers={'Retry-After':'17'},text='private-vendor-error-token')
            if status=='huge':return web.Response(body=b'x'*65537)
            if status=='revoke':config['bindings']=[]
            if status=='confirmation-fault':
                inbox.db.execute("CREATE TRIGGER confirmation_fault BEFORE UPDATE ON line_delivery_intents BEGIN SELECT RAISE(ABORT,'private-confirmation-fault'); END")
            ids=[{'id':str(123456+i),'quoteToken':'private-quote-capability'} for i in range(len(body['messages']))]
            proof={'sentMessages':ids}
            headers={'X-Line-Request-Id':'d6f3be33-8d24-40a5-a6ab-8116de7744ad'}
            if status=='missing-request-id':headers={}
            if status=='missing-message-id':proof={'sentMessages':[{}]}
            if status=='wrong-count':proof={'sentMessages':[]}
            if status=='duplicate-id':proof={'sentMessages':[{'id':'123456'} for _ in ids]}
            return web.json_response(proof,headers=headers)
        async def other(request):foreign.append(True);return web.Response(status=200)
        app=web.Application();app.router.add_post('/push',receive);app.router.add_post('/foreign',other)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        target=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/push';publisher._target=target
        try:
            content='**actual native LINE**\nhttps://owner.invalid'
            result=await publisher.send(binding,current_id[0],1,content)
            assert result.success is True and result.message_id.startswith('line_push_')
            confirmed_receipt=result.message_id
            assert result.raw_response['recipient_receipt_verified'] is False
            assert requests[0]['messages']==_text_messages(content) and adapter._client is None
            assert delivery_result(result)['status']=='delivered'
            assert 'private-quote' not in inbox.db.execute('SELECT receipt FROM line_delivery_intents').fetchone()[0]
            cases.append('actual_native_markdown_codec_and_push_after_observable_write_intent_uses_remote_receipt_not_native_none')
            assert (await publisher.send(binding,current_id[0],1,content)).message_id==result.message_id and len(requests)==1
            cases.append('confirmed_same_attempt_returns_journaled_receipt_without_another_native_push')
            try:await publisher.send(binding,current_id[0],1,'different content')
            except PermissionError:pass
            else:raise AssertionError('changed content inherited successful outbox attempt')
            cases.append('same_attempt_changed_content_refused_before_socket')
            try:await publisher.native.push(user,_text_messages('unapproved raw push'))
            except PermissionError:pass
            else:raise AssertionError('native client sent without private capability')
            assert len(requests)==1
            cases.append('actual_native_client_push_without_context_cannot_open_socket')
            for index,(scenario,expected) in enumerate([(401,'failed'),(403,'failed'),(429,'retry'),(500,'uncertain'),
                    ('abort','uncertain'),('redirect','uncertain'),('huge','uncertain'),('missing-request-id','uncertain'),
                    ('missing-message-id','uncertain'),('wrong-count','uncertain'),('duplicate-id','uncertain')],2):
                mode[0]=scenario;current_id[0]=f'{index:064x}';before=len(requests)
                text='x'*5000 if scenario=='duplicate-id' else 'private contract text'
                result=await publisher.send(binding,current_id[0],1,text)
                assert delivery_result(result)['status']==expected,(scenario,result)
                assert len(requests)==before+1 and not foreign
                if scenario==429:assert delivery_result(result)['retry_after']==17
                repeated=await publisher.send(binding,current_id[0],1,text)
                assert delivery_result(repeated)['status']=='uncertain' and len(requests)==before+1
                cases.append('native_http_'+str(scenario)+'_classified_without_redirect_or_repeat')
            before=len(requests);mode[0]='success'
            for content in ['x'*23000,'🙂'*3000]:
                result=await publisher.send(binding,'e'*64,1,content)
                assert delivery_result(result)['status']=='failed' and len(requests)==before
            cases.append('native_ellipsis_truncation_and_oversized_utf16_bubble_refused_before_side_effect')
            mode[0]='success';current_id[0]='b'*64
            inbox.db.execute("CREATE TRIGGER intent_fault BEFORE INSERT ON line_delivery_intents BEGIN SELECT RAISE(ABORT,'private-intent-fault'); END")
            try:await publisher.send(binding,current_id[0],1,'must not send')
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('failed intent storage did not refuse write')
            assert len(requests)==before
            inbox.db.execute('DROP TRIGGER intent_fault')
            cases.append('actual_sqlite_intent_failure_prevents_every_native_side_effect')
            mode[0]='confirmation-fault';current_id[0]='c'*64
            result=await publisher.send(binding,current_id[0],1,'accepted but local confirmation failed')
            assert delivery_result(result)['status']=='uncertain' and len(requests)==before+1
            inbox.db.execute('DROP TRIGGER confirmation_fault')
            await publisher.close();inbox.close();inbox=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=inbox
            publisher=Publisher(adapter);publisher._target=target
            cached=await publisher.send(binding,'a'*64,1,'**actual native LINE**\nhttps://owner.invalid')
            assert cached.success is True and cached.message_id==confirmed_receipt and len(requests)==before+1
            cases.append('confirmed_receipt_survives_actual_sqlite_reopen_without_repeat')
            repeated=await publisher.send(binding,current_id[0],1,'accepted but local confirmation failed')
            assert delivery_result(repeated)['status']=='uncertain' and len(requests)==before+1
            cases.append('actual_sqlite_confirmation_failure_and_reopen_preserve_uncertainty_without_resend')
            mode[0]='success';adapter._reply_tokens[user]=('unapproved-single-use',time.time()+50);current_id[0]='d'*64
            result=await publisher.send(binding,current_id[0],1,'must not consume reply token')
            assert delivery_result(result)['status']=='uncertain' and len(requests)==before+1
            adapter._reply_tokens.clear()
            cases.append('native_reply_token_cannot_trigger_reply_then_push_fallback')
            mode[0]='hang';current_id[0]='4'*64
            task=asyncio.create_task(publisher.send(binding,current_id[0],1,'cancel after native HTTP write'))
            await asyncio.wait_for(hang_started.wait(),5);task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            else:raise AssertionError('cancelled native send did not propagate cancellation')
            hang_release.set();before+=1
            repeated=await publisher.send(binding,current_id[0],1,'cancel after native HTTP write')
            assert delivery_result(repeated)['status']=='uncertain' and len(requests)==before+1
            cases.append('actual_cancel_after_http_write_preserves_intent_and_never_reposts_same_attempt')
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
            now=datetime.now(timezone.utc)
            cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
                .not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False)
                .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
            cert_path=directory/'tls.pem';key_path=directory/'tls.key'
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert_path,key_path)
            tls_site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=tls);await tls_site.start()
            tls_port=tls_site._server.sockets[0].getsockname()[1]
            publisher._target=f'https://localhost:{tls_port}/push';mode[0]='success';current_id[0]='1'*64
            result=await publisher.send(binding,current_id[0],1,'untrusted certificate')
            assert delivery_result(result)['status']=='uncertain' and len(requests)==before+1
            cases.append('actual_native_https_refuses_unknown_certificate_without_http_request')
            await publisher.client.close()
            ca=ssl.create_default_context(cafile=str(cert_path))
            assert ca.check_hostname and ca.verify_mode==ssl.CERT_REQUIRED
            publisher.client=ClientSession(connector=TCPConnector(ssl=ca),trust_env=False)
            publisher._target=f'https://127.0.0.1:{tls_port}/push';current_id[0]='2'*64
            result=await publisher.send(binding,current_id[0],1,'wrong certificate hostname')
            assert delivery_result(result)['status']=='uncertain' and len(requests)==before+1
            cases.append('actual_native_https_refuses_wrong_hostname_without_http_request')
            publisher._target=f'https://localhost:{tls_port}/push';current_id[0]='3'*64
            result=await publisher.send(binding,current_id[0],1,'verified TLS fixture')
            assert result.success is True and len(requests)==before+2
            cases.append('actual_native_https_push_accepts_explicit_fixture_ca_with_hostname_verification')
            config['bindings']=[]
            try:await publisher.send(binding,'f'*64,1,'revoked')
            except PermissionError:pass
            else:raise AssertionError('revoked LINE authority sent')
            assert len(requests)==before+2
            cases.append('current_owner_withdrawal_prevents_native_push')
        finally:hang_release.set();await publisher.close();await runner.cleanup();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-line-send-') as temporary:asyncio.run(exercise(Path(temporary)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_native_codec_push_and_loopback_http_sqlite':True,
        'fixture_only_loopback_target':True,'fixture_only_disposable_ca':True,'tls_verification_disabled':False,
        'public_gateway_enabled':False,
        'external_account_or_recipient_receipt_or_installed_acceptance':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
