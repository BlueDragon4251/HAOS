#!/usr/bin/env python3
"""Actual native A2A config/sign/post code over verified local TLS and real SQL.

Only fixture DNS maps the approved fake public hostname to loopback. Parent
admission is direct; installed controller UID/GUI acceptance is separate.
"""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayEngine,digest
    from haos.store import MissionStore
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_tasks import Tasks
    from haos.gateway_a2a_native import build
    from haos.gateway_a2a_publisher import Publisher
    from haos.gateway_runtime import delivery_metadata
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from plugins.platforms.a2a import protocol
    from webhook_tls_fixture import create
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-a2a-callback-') as temp:
        root=Path(temp);create(root,'a2a.fixture.invalid')
        with socket.socket() as chosen:chosen.bind(('127.0.0.1',0));port=chosen.getsockname()[1]
        callback_url='https://a2a.fixture.invalid:'+str(port)+'/callback';secret='private_callback_signing_fixture_'+'b'*32
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32},'port':8448,'agent_name':'HAOS',
            'callbacks':{'alice':{'url':callback_url,'secret':secret}},'tls':{'public_url':'https://a2a.fixture.invalid/a2a',
                'certificate':(root/'certificate.pem').read_text(),'private_key':(root/'key.pem').read_text(),
                'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        binding={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-callback','scope':scope(value,'alice'),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1,'allow_callback':True}
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[binding]};policy=lambda:PreparedA2APolicy(config)
        raw=RawEvents(root/'originals.db',Redactor(),lambda:None);parent=NativeInbox(root/'parent.db',raw.redactor)
        tasks=Tasks(root/'tasks.db','alice',value,lambda:None,policy,connector='a2a')
        store=MissionStore(root/'missions.db');engine=GatewayEngine(store);home=root/'home';home.mkdir(mode=0o700)
        async def exercise():
            nonlocal tasks
            from aiohttp import web
            received=[];posts=[];mode=[200]
            async def receive(event,proof,task_id):
                receipt=parent.admit(policy(),'a2a',proof['envelope'],{'raw_id':proof['id'],'task_id':task_id},received_at=proof['received_at'])
                result=await engine.receive(policy(),'a2a',proof['envelope'],None);received.append(result['mission_id']);return receipt
            async def sink(request):
                body=await request.read();payload=json.loads(body)
                expected=hmac.new(secret.encode(),json.dumps(payload,sort_keys=True,ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
                assert request.secure and hmac.compare_digest(request.headers['X-A2A-Signature'],expected)
                assert 'Authorization' not in request.headers and 'Cookie' not in request.headers
                assert all(token.encode() not in body for token in [secret,*value['peer_tokens'].values()])
                posts.append({'body':body,'signature':request.headers['X-A2A-Signature'],'id':request.headers['X-A2A-Delivery-ID'],'path':request.path})
                status=mode.pop(0) if len(mode)>1 else mode[0]
                if status==0:
                    request.transport.close();return web.Response()
                return web.Response(status=status,headers={'Retry-After':'1','Location':callback_url+'/unapproved'})
            app=web.Application();app.router.add_post('/callback',sink);runner=web.AppRunner(app,access_log=None);await runner.setup()
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
            await web.TCPSite(runner,'127.0.0.1',port,ssl_context=tls).start()
            old_dns=socket.getaddrinfo;old_ca=os.environ.get('SSL_CERT_FILE')
            def fixture_dns(host,*args,**kwargs):return old_dns('127.0.0.1' if host=='a2a.fixture.invalid' else host,*args,**kwargs)
            socket.getaddrinfo=fixture_dns;os.environ['SSL_CERT_FILE']=str(root/'ca.pem');adapter=None
            async def wait(state,count):
                async with asyncio.timeout(10):
                    while True:
                        row=tasks.db.execute('SELECT state FROM a2a_callback_deliveries ORDER BY created_at DESC LIMIT 1').fetchone()
                        if row is not None and row['state']==state and len(posts)==count:return
                        await asyncio.sleep(.02)
            try:
                adapter=build(value,'alice',home,lambda:None,policy,tasks,receive);publisher=Publisher(adapter,tasks)
                assert adapter._build_card()['capabilities']['pushNotifications'] is True
                params={'message':{'messageId':'callback-source','contextId':binding['chat'],'role':'ROLE_USER','parts':[{'text':'Controlled native callback contract.'}]},
                    'configuration':{'taskPushNotificationConfig':{'url':callback_url}}}
                request={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':params}
                proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(request).encode())
                def prepare():
                    with tasks.source('a2a',proof):return adapter._prepare_task(params,'alice')
                terminal,pending=await asyncio.to_thread(prepare);assert terminal is None
                async with asyncio.timeout(5):
                    while not received:await asyncio.sleep(.01)
                task=pending['task_id'];mid=received[0]
                cfg=adapter._rpc_push_config_get(2,{'taskId':task})['result'];assert cfg['pushNotificationConfig']=={'url':callback_url}
                assert secret not in json.dumps(cfg) and value['peer_tokens']['alice'] not in json.dumps(cfg)
                listing=adapter._rpc_push_config_list(3,{'taskId':task})['result'];assert listing['configs']==[cfg]
                assert adapter._rpc_push_config_create(4,{'taskId':task,'pushNotificationConfig':{'url':callback_url}})['result']==cfg
                for url in ['https://unapproved.fixture.invalid/callback',callback_url+'/other','http://127.0.0.1/callback']:
                    try:adapter._rpc_push_config_create(5,{'taskId':task,'pushNotificationConfig':{'url':url}})
                    except PermissionError:pass
                    else:raise AssertionError('peer changed independent owner callback destination')
                assert not posts
                cases.append('actual_native_embedded_config_and_RPC_get_list_create_are_durable_idempotent_owner_bound_and_never_expose_signing_or_peer_keys')
                cases.append('unapproved_destinations_are_refused_before_native_config_or_network_side_effects')
                async def send(delivery):
                    result=await publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],delivery_metadata(delivery,'a2a'))
                    assert result.success
                    engine.acknowledge(policy(),delivery['id'],{'attempt':delivery['attempt'],'status':'delivered','message_id':result.message_id})
                await send(engine.next_delivery(policy()));assert store.claim()['id']==mid
                store.settle(mid,'completed',result='Actual callback Unicode ä result.')
                final=None
                while (delivery:=engine.next_delivery(policy())) is not None:
                    if delivery['event_context']['kind']=='mission.completed':final=delivery
                    else:await send(delivery)
                assert final is not None
                tasks.db.execute("CREATE TRIGGER fail_callback_result BEFORE UPDATE ON a2a_result_epochs BEGIN SELECT RAISE(ABORT,'fixture result receipt failure'); END")
                try:await send(final)
                except sqlite3.IntegrityError:pass
                else:raise AssertionError('actual result receipt failure was hidden')
                assert tasks.get(task)['state']==protocol.STATE_COMPLETED
                await asyncio.sleep(.4);assert not posts
                assert tasks.db.execute('SELECT state FROM a2a_callback_deliveries').fetchone()[0]=='prepared'
                cases.append('real_SQL_result_receipt_failure_blocks_native_callback_POST_despite_native_task_completion_until_exact_root_event_reconciliation')
                tasks.db.execute('DROP TRIGGER fail_callback_result');await send(final);await wait('acknowledged',1)
                payload=json.loads(posts[0]['body']);assert payload['statusUpdate']['taskId']==task and 'Unicode ä result.' in json.dumps(payload,ensure_ascii=False)
                assert adapter._rpc_push_config_get(6,{'taskId':task}).get('error') is not None
                cases.append('actual_pinned_native_status_builder_separate_key_HMAC_and_scoped_HTTPS_POST_receive_definite_ack_without_peer_bearer_or_recipient_read_claim')
                mode[:]=[429,200]
                cfg2=adapter._rpc_push_config_create(7,{'taskId':task,'pushNotificationConfig':{'url':callback_url}})['result']
                assert cfg2['configId']!=cfg['configId'];await wait('acknowledged',3)
                assert posts[1]['id']==posts[2]['id'] and posts[1]['body']==posts[2]['body'] and posts[1]['signature']==posts[2]['signature']
                cases.append('definite_429_uses_bounded_Retry_After_and_same_first_native_wire_body_signature_and_delivery_identity_before_ack')
                mode[:]=[302];adapter._rpc_push_config_create(8,{'taskId':task,'pushNotificationConfig':{'url':callback_url}})
                await wait('uncertain',4);await asyncio.sleep(.3);assert len(posts)==4 and all(post['path']=='/callback' for post in posts)
                cases.append('native_callback_scoped_transport_never_follows_redirect_or_automatically_repeats_unconfirmed_HTTP_outcome')
                mode[:]=[401];adapter._rpc_push_config_create(9,{'taskId':task,'pushNotificationConfig':{'url':callback_url}})
                await wait('authentication-refused',5);await asyncio.sleep(.3);assert len(posts)==5
                cases.append('definite_callback_401_is_persistent_authentication_refusal_without_automatic_retry')
                mode[:]=[429];cfg3=adapter._rpc_push_config_create(10,{'taskId':task,'pushNotificationConfig':{'url':callback_url}})['result']
                await wait('retryable',6)
                assert adapter._rpc_push_config_delete(11,{'taskId':task,'id':cfg3['configId']})['result']=={'deleted':True}
                await wait('revoked',6);await asyncio.sleep(.3);assert len(posts)==6
                cases.append('actual_native_config_delete_revokes_retained_retry_before_another_network_write')
                mode[:]=[0];adapter._rpc_push_config_create(12,{'taskId':task,'pushNotificationConfig':{'url':callback_url}})
                await wait('uncertain',7);await asyncio.sleep(.4);assert len(posts)==7
                cases.append('connection_loss_after_callback_body_read_is_durable_uncertain_and_never_automatically_replayed')
                await adapter.close_profile();adapter=None;tasks.close()
                tasks=Tasks(root/'tasks.db','alice',value,lambda:None,policy,connector='a2a')
                adapter=build(value,'alice',home,lambda:None,policy,tasks,receive)
                await asyncio.sleep(.5)
                assert len(posts)==7 and tasks.get(task)['state']==protocol.STATE_COMPLETED
                assert tasks.db.execute('SELECT state FROM a2a_callback_deliveries ORDER BY created_at DESC LIMIT 1').fetchone()[0]=='uncertain'
                cases.append('actual_SQLite_and_native_TaskStore_reopen_preserve_uncertain_callback_without_reposting_or_changing_task_outcome')
                binding['allow_callback']=False
                try:adapter._rpc_push_config_get(13,{'taskId':task})
                except PermissionError:pass
                else:raise AssertionError('withdrawn owner callback permission read a retained configuration')
                await asyncio.sleep(.3);assert len(posts)==7
                cases.append('current_owner_withdrawal_precedes_retained_callback_configuration_read_and_future_network_use')
            finally:
                if adapter is not None:await adapter.close_profile()
                socket.getaddrinfo=old_dns
                if old_ca is None:os.environ.pop('SSL_CERT_FILE',None)
                else:os.environ['SSL_CERT_FILE']=old_ca
                await runner.cleanup()
        try:asyncio.run(exercise())
        finally:store.close();tasks.close();parent.close();raw.close()
    report={'passed':len(cases),'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'actual_native_config_codec_status_builder_HMAC_sender_SQL_and_verified_TLS':True,'fixture_DNS_only_maps_approved_fake_hostname_to_loopback':True,
        'parent_IPC_UID_GUI_live_peer_inference_or_public_activation':False}
    Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
