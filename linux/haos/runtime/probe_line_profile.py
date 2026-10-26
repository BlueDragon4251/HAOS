#!/usr/bin/env python3
"""Actual prepared LINE registration, identity HTTP, kernel lease and durable replay."""
import asyncio
import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_line_profile import build,credentials
    from haos.gateway_line_ingress import PreparedLINEPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope,build_adapter,delivery_metadata
    from haos.gateway import GatewayEngine
    from haos.store import MissionStore
    from haos.gateway_delivery import delivery_result
    from haos.redaction import Redactor
    from haos.gateway_raw_recovery import retry_line_auth
    cases=[]
    async def exercise(directory):
        from aiohttp import web,ClientSession
        os.environ['HERMES_HOME']=str(directory/'outer-home');os.environ['HERMES_SAFE_MODE']='1'
        parent=directory/'profiles';parent.mkdir(mode=0o700)
        user='U'+'a'*32;destination='U'+'d'*32
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        value={'channel_secret':'c'*32,'channel_access_token':'private-profile-access-token','destination':destination,'port':port}
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'',
            'identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
        policy=lambda:PreparedLINEPolicy(config);inbox=NativeInbox(directory/'native.db',Redactor())
        relay=RelayInbox(directory/'relay.db',Redactor())
        mode=['success'];lookups=[];pushed=[]
        async def identity(request):
            lookups.append(True);assert request.headers['Authorization']=='Bearer '+value['channel_access_token']
            if isinstance(mode[0],int):return web.Response(status=mode[0],headers={'Retry-After':'21'})
            if mode[0]=='redirect':return web.Response(status=307,headers={'Location':'/foreign'})
            return web.json_response({'userId':destination if mode[0]=='success' else 'U'+'f'*32})
        async def push(request):
            assert request.headers['Authorization']=='Bearer '+value['channel_access_token']
            payload=await request.json();assert payload['to']==user
            pushed.append(payload)
            return web.json_response({'sentMessages':[{'id':str(123456+i)} for i in range(len(payload['messages']))]},
                headers={'X-Line-Request-Id':'f1bc265e-e9a2-4855-a59f-6ded11cb7e3c'})
        app=web.Application();app.router.add_get('/info',identity);app.router.add_post('/push',push)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        target=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/info'
        adapter=None;accepted=[];failure=[False]
        def receive(event):
            if failure[0]:raise ConnectionError('disposable durable admission failure')
            source=adapter_envelope(event,'line');relay.admit(policy(),'line',source)
            accepted.append(source);return True
        def create():
            result=build_adapter('line',value,line_context={'parent':parent,'connector':'line','policy':policy,'inbox':inbox})
            result._haos_line_identity._target=target
            if result._haos_line_publisher is not None:result._haos_line_publisher._target=target.replace('/info','/push')
            result.set_durable_message_handler(receive);return result
        try:
            empty=copy.deepcopy(config);empty['bindings']=[]
            try:build(value,parent,'line',lambda:PreparedLINEPolicy(empty),inbox)
            except PermissionError:pass
            else:raise AssertionError('LINE profile created without owner grants')
            assert not list(parent.iterdir()) and not lookups
            cases.append('no_owner_pairing_cannot_create_profile_or_start_identity_network')
            alias=directory/'profile-alias';alias.symlink_to(parent,target_is_directory=True)
            try:build(value,alias,'line',policy,inbox)
            except PermissionError:pass
            else:raise AssertionError('LINE private profile accepted symlinked parent')
            cases.append('private_profile_rejects_symlinked_parent_before_native_or_network_use')
            adapter=create()
            assert adapter._haos_line_profile.parent==parent and adapter._haos_line_profile.stat().st_mode&0o077==0
            assert (adapter._haos_line_profile/'home').stat().st_mode&0o077==0
            try:build(value,parent,'line',policy,inbox)
            except PermissionError:pass
            else:raise AssertionError('second LINE identity acquired held kernel lease')
            assert not lookups
            cases.append('actual_registered_adapter_uses_private_home_and_exclusive_kernel_lease_without_network_at_build')
            assert adapter._haos_line_publisher is not None
            try:await adapter._haos_line_publisher.send(config['bindings'][0],'f'*64,1,'before bot identity verification')
            except PermissionError:pass
            else:raise AssertionError('LINE profile sent before bot verification')
            cases.append('profile_publisher_cannot_send_before_verified_bot_identity_and_listener_connection')
            assert await adapter.connect() and adapter.is_connected and adapter.native_health()['status']=='listening'
            cases.append('native_bot_info_verifies_exact_destination_before_fixed_loopback_listener_start')
            event={'type':'message','mode':'active','timestamp':int(time.time()*1000),'webhookEventId':'01K8'+'A'*22,
                'source':{'type':'user','userId':user},'message':{'type':'text','id':'1234','text':'retained private profile input'}}
            async def post(event,expected=200):
                body=json.dumps({'destination':destination,'events':[event]}).encode()
                signature=base64.b64encode(hmac.new(value['channel_secret'].encode(),body,hashlib.sha256).digest()).decode()
                async with ClientSession() as client:
                    async with client.post(f'http://127.0.0.1:{port}/line/webhook',data=body,headers={'X-Line-Signature':signature}) as response:assert response.status==expected
            async def until(condition):
                async with asyncio.timeout(5):
                    while not condition():await asyncio.sleep(.02)
            await post(event);await until(lambda:len(accepted)==1)
            assert accepted[0]['scope']==destination and accepted[0]['text']==event['message']['text']
            cases.append('actual_profile_listener_commit_and_native_replay_worker_deliver_exact_owner_event')
            store=MissionStore(directory/'missions.db');engine=GatewayEngine(store)
            try:
                await engine.receive(policy(),'line',accepted[0],None)
                await adapter.disconnect()
                for _ in range(6):assert engine.next_delivery(policy(),time.time()+3600,ready_connectors=[]) is None
                assert tuple(store.db.execute('SELECT state,attempt FROM gateway_outbox').fetchone())==('pending',0)
                assert await adapter.connect()
                delivery=engine.next_delivery(policy(),ready_connectors=['line'])
                assert delivery['attempt']==1
                receipt=await adapter.send(delivery['chat'],delivery['content'],metadata=delivery_metadata(delivery,'line'))
                assert delivery_result(receipt)['status']=='delivered' and len(pushed)==1
                engine.acknowledge(policy(),delivery['id'],{**delivery_result(receipt),'attempt':delivery['attempt']})
                assert tuple(store.db.execute('SELECT state,attempt FROM gateway_outbox').fetchone())==('delivered',1)
            finally:store.close()
            cases.append('actual_common_factory_root_engine_outbox_native_push_remote_receipt_and_durable_ack')
            cases.append('offline_private_profile_keeps_pending_outbox_at_zero_attempts_until_verified_reconnection')
            await post(event);await asyncio.sleep(.25);assert len(accepted)==1
            cases.append('actual_profile_repeated_signed_webhook_cannot_duplicate_local_admission')
            failure[0]=True;second={**event,'webhookEventId':'01K8'+'B'*22};await post(second)
            await until(lambda:inbox.db.execute("SELECT COUNT(*) FROM native_inbox WHERE attempt>0").fetchone()[0]==1)
            await adapter.close_profile();inbox.close();inbox=NativeInbox(directory/'native.db',Redactor());failure[0]=False
            adapter=create();assert await adapter.connect()
            assert len(accepted)==1
            inbox.db.execute("UPDATE native_inbox SET next_attempt=0 WHERE state='pending'")
            await until(lambda:len(accepted)==2)
            cases.append('private_profile_close_reopen_reacquires_kernel_lease_and_replays_retained_local_failure')
            config['bindings'][0]['generation']='c'*64
            await post({**event,'webhookEventId':'01K8'+'C'*22},401)
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==2
            await until(lambda:adapter.native_health()['status']=='revoked')
            cases.append('owner_epoch_change_is_denied_at_http_admission_before_worker_observes_revocation')
            await adapter.close_profile();adapter=create();assert await adapter.connect()
            config['bindings']=[]
            await until(lambda:adapter.native_health()['status']=='revoked')
            assert not adapter.is_connected
            cases.append('current_owner_withdrawal_stops_idle_listener_and_worker_without_inheriting_authority')
            await adapter.close_profile();config['bindings']=[{'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,
                'thread':'','identity':'owner','capabilities':['create'],'generation':'b'*64,'since':int((time.time()-10)*1000)}]
            adapter=create();assert adapter._haos_line_publisher is None
            assert await adapter.connect()
            cases.append('creation_only_profile_has_no_publisher_or_inherited_outbound_authority')
            await adapter.close_profile()
            for error,state in [(401,'authentication-refused'),(403,'authentication-refused'),('wrong-bot','identity-refused'),(429,'rate-limited')]:
                mode[0]=error;value['channel_access_token']='private-profile-access-'+str(error)
                adapter=create();before=len(lookups)
                assert not await adapter.connect() and adapter.native_health()['status']==state and not adapter.is_connected
                assert len(lookups)==before+1
                deadline=adapter.native_health()['next_attempt']
                await adapter.close_profile();config['bindings'][0]['generation']='e'*64
                adapter=create();mode[0]='success';before=len(lookups)
                assert not await adapter.connect() and len(lookups)==before
                if error==429:assert adapter.native_health()['next_attempt']==deadline and deadline>time.time()
                cases.append('native_identity_'+str(error)+'_blocks_listener_and_survives_owner_epoch_profile_reopen')
                before=len(lookups)
                decision=retry_line_auth(inbox,policy(),{'connector':'line','owner_uid':1000,'note_sha256':'f'*64})
                assert decision['network_requested'] is False and len(lookups)==before
                if error==429:
                    assert decision['authentication_blocks_cleared']==0 and not await adapter.connect()
                    assert adapter.native_health()['next_attempt']==deadline
                else:
                    assert decision['authentication_blocks_cleared']>0 and await adapter.connect()
                cases.append('explicit_offline_owner_recheck_'+str(error)+'_preserves_rate_limit_and_requires_fresh_native_verification')
                await adapter.close_profile()
            mode[0]='redirect';value['channel_access_token']='private-profile-redirect-token';adapter=create()
            assert not await adapter.connect() and adapter.native_health()['status']=='transport-unavailable'
            cases.append('native_identity_redirect_never_authenticates_or_opens_listener')
            await adapter.close_profile();mode[0]='success';value['channel_access_token']='private-profile-bind-token';adapter=create()
            with socket.socket() as occupied:
                occupied.bind(('127.0.0.1',port));occupied.listen()
                assert not await adapter.connect() and adapter.native_health()['status']=='transport-unavailable'
            assert await adapter.connect()
            cases.append('actual_occupied_listener_port_reports_failure_and_reconnects_after_release')
            await adapter.close_profile()
            try:await adapter.connect()
            except PermissionError:pass
            else:raise AssertionError('closed private profile reconnected')
            cases.append('closed_profile_rejects_new_network_and_releases_lease')
        finally:
            if adapter is not None:await adapter.close_profile()
            await runner.cleanup();inbox.close();relay.close()
    with tempfile.TemporaryDirectory(prefix='haos-line-profile-') as temporary:asyncio.run(exercise(Path(temporary)))
    receipt={'passed':len(cases),'cases':cases,'actual_registered_native_adapter_http_sqlite_and_kernel_lease':True,
        'fixture_only_loopback_identity_target':True,'public_gateway_enabled':False,
        'fixture_profile_listener':'127.0.0.1 only; external verified TLS ingress not configured here',
        'external_or_installed_acceptance':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
