#!/usr/bin/env python3
"""Actual isolated prepared HA profile with local WS and private SQLite journals."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import web
    from haos import gateway_homeassistant_profile as profile
    from haos.gateway import digest,GatewayPolicy
    from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy,capture,snapshot
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        home=directory/'unrelated-home';home.mkdir(mode=0o700);os.environ['HERMES_HOME']=str(home)
        parent=directory/'profiles';parent.mkdir(mode=0o700)
        token='private-disposable-ha-profile-token';user='a'*32;entity='input_text.owner'
        native=NativeInbox(directory/'native.db',Redactor([token]))
        relay=RelayInbox(directory/'relay.db',Redactor([token]))
        config={'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
            'id':'owner','connector':'ha','sender':user,'chat':entity,'scope':'','thread':'','identity':'owner',
            'capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-10000,
            'homeassistant_shared_notifications':True}]}
        policy=lambda:PreparedHomeAssistantPolicy(config)
        value={'server_url':'https://fixture.invalid','token':token}
        stamp=datetime.now(timezone.utc).isoformat()
        context={'id':'b'*32,'user_id':user}
        event={'event_type':'state_changed','time_fired':stamp,'context':context,'data':{'entity_id':entity,
            'old_state':{'state':'before'},'new_state':{'entity_id':entity,'state':'after','attributes':{},
            'context':context,'last_updated':stamp}}}
        state={'mode':'normal','connections':0,'requests':0,'posts':[],'notifications':{},'sockets':[],'admit_failures':0};accepted=[];adapters=[]
        async def post(request):
            assert request.headers['Authorization']=='Bearer '+token
            data=await request.json();state['posts'].append(data)
            state['notifications'][data['notification_id']]=data
            return web.json_response([])
        async def websocket(request):
            state['requests']+=1
            if state['mode']=='rate-limit':return web.Response(status=429,text=token,headers={'Retry-After':'19'})
            socket=web.WebSocketResponse();await socket.prepare(request);state['sockets'].append(socket)
            state['connections']+=1
            await socket.send_json({'type':'auth_required','ha_version':'fixture'})
            assert await socket.receive_json()=={'type':'auth','access_token':token}
            if state['mode']=='auth-invalid':
                await socket.send_json({'type':'auth_invalid','message':token});await socket.close();return socket
            await socket.send_json({'type':'auth_ok','ha_version':'fixture'})
            sub=await socket.receive_json();assert sub['type']=='subscribe_events' and sub['event_type']=='state_changed'
            await socket.send_json({'id':sub['id'],'type':'result','success':True,'result':None})
            if state['mode']!='quiet':await socket.send_json({'id':sub['id'],'type':'event','event':event})
            async for message in socket:
                request=json.loads(message.data)
                assert set(request)=={'id','type'} and request['type']=='persistent_notification/get'
                await socket.send_json({'id':request['id'],'type':'result','success':True,'result':list(state['notifications'].values())})
            return socket
        app=web.Application();app.router.add_get('/api/websocket',websocket)
        app.router.add_post('/api/services/persistent_notification/create',post)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        target='ws://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/api/websocket'
        original=profile.install_transport;original_publisher=profile.Publisher
        def local(adapter):
            result=original(adapter);adapter._haos_ha_transport._target=target;return result
        profile.install_transport=local
        class LocalPublisher(original_publisher):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                self._target=target.replace('ws:','http:').removesuffix('/api/websocket')
                self.witness.boundary._target=target
        profile.Publisher=LocalPublisher
        def build():
            adapter=profile.build(value,parent,'ha',policy,native);adapters.append(adapter)
            adapter._haos_ha_retry_steps=(.05,.1)
            def receive(message):
                if state['admit_failures']:
                    state['admit_failures']-=1;raise RuntimeError('disposable relay admission failure')
                envelope=adapter_envelope(message,'homeassistant')
                relay.admit(policy(),'ha',envelope);accepted.append(envelope);return True
            adapter.set_durable_message_handler(receive)
            return adapter
        async def eventually(condition):
            async with asyncio.timeout(4):
                while not condition():await asyncio.sleep(.02)
        def refused(action):
            try:action()
            except (ValueError,PermissionError,OSError):return
            raise AssertionError('unsafe profile accepted')
        try:
            refused(lambda:GatewayPolicy(config));cases.append('prepared_profile_does_not_enable_public_homeassistant_policy')
            adapter=build();location=adapter._haos_ha_profile
            assert not adapter.is_connected and state['connections']==0
            cases.append('private_factory_never_connects_before_explicit_start')
            refused(build);cases.append('actual_kernel_flock_refuses_parallel_homeassistant_profile')
            assert location.stat().st_mode&0o777==0o700 and (location/'home').stat().st_mode&0o777==0o700
            assert (location/'profile.lock').stat().st_mode&0o777==0o600
            assert list(home.iterdir())==[]
            cases.append('private_native_imports_leave_unrelated_home_untouched')
            binding=config['bindings'][0]
            metadata={'haos_scope':'','haos_binding':{'binding_id':'owner','binding_digest':digest(binding)},
                'haos_delivery_id':digest('actual prepared profile obligation')}
            try:await adapter.send(entity,'before explicit connect',metadata=metadata)
            except PermissionError:pass
            else:raise AssertionError('disconnected native profile sent')
            assert not state['posts'];cases.append('disconnected_profile_cannot_publish')
            assert await adapter.connect()
            await eventually(lambda:len(accepted)==1)
            assert adapter.homeassistant_status()['status']=='streaming'
            assert native.db.execute("SELECT state FROM native_inbox").fetchone()[0]=='committed'
            cases.append('actual_profile_native_auth_stream_durable_capture_and_relay')
            try:await adapter.send(entity,'missing outbox identity',metadata={k:v for k,v in metadata.items() if k!='haos_delivery_id'})
            except PermissionError:pass
            else:raise AssertionError('unidentified publication admitted')
            assert not state['posts'];cases.append('profile_send_requires_exact_outbox_identity_and_current_owner_route')
            for name,altered,reply in [
                    ('extra_binding_fields',{**metadata,'haos_binding':{**metadata['haos_binding'],'plugin':'unreviewed'}},None),
                    ('truthy_notification_flag',{**metadata,'notify':'true'},None),
                    ('unbounded_reply_identity',metadata,'unreviewed reply')]:
                try:await adapter.send(entity,'unapproved metadata',reply_to=reply,metadata=altered)
                except PermissionError:pass
                else:raise AssertionError('unapproved metadata accepted')
                assert not state['posts'];cases.append('profile_refuses_'+name+'_before_native_post')
            result=await adapter.send(entity,'private lifecycle response',metadata=metadata)
            assert result.success and state['posts'][-1]['message']=='private lifecycle response'
            assert result.message_id==state['posts'][-1]['notification_id']
            cases.append('actual_private_profile_send_uses_native_rest_and_separate_authenticated_receipt_witness')
            before=state['connections'];await state['sockets'][0].close()
            await eventually(lambda:state['connections']>before and adapter.is_connected)
            assert len(accepted)==1 and adapter.homeassistant_status()['gap_since']>0
            cases.append('actual_eof_reconnect_preserves_idempotency_and_reports_unrecoverable_gap')
            await adapter.disconnect();assert not adapter.is_connected
            assert await adapter.connect();await asyncio.sleep(.1);assert len(accepted)==1
            cases.append('explicit_disconnect_reconnect_retains_raw_journal_and_profile')
            config['bindings'][0]['generation']='c'*64
            await eventually(lambda:adapter.homeassistant_status()['status']=='revoked')
            await eventually(lambda:not adapter.is_connected)
            assert adapter._haos_ha_transport.socket.closed
            assert not await adapter.connect()
            cases.append('owner_regrant_revokes_running_profile_without_automatic_inheritance')
            await asyncio.gather(adapter.close_profile(),adapter.close_profile())
            assert all(socket.closed for socket in adapter._haos_ha_transport.sockets)
            cases.append('concurrent_profile_close_releases_lease_once_and_closes_sockets')
            state['mode']='auth-invalid';adapter=build()
            assert not await adapter.connect()
            assert adapter.homeassistant_status()['status']=='authentication-refused'
            before=state['connections'];assert not await adapter.connect();assert state['connections']==before
            await adapter.close_profile();adapter=build()
            assert not await adapter.connect() and state['connections']==before
            cases.append('authentication_refusal_is_sticky_across_connect_close_and_actual_profile_reopen')
            await adapter.close_profile();value['token']='rotated-private-disposable-token';token=value['token']
            stamp=datetime.now(timezone.utc).isoformat();context={'id':'d'*32,'user_id':user}
            event['time_fired']=stamp;event['context']=context
            event['data']['new_state']['context']=context;event['data']['new_state']['last_updated']=stamp
            state['mode']='normal';adapter=build();assert await adapter.connect()
            assert adapter._haos_ha_profile==location
            assert list(home.iterdir())==[]
            cases.append('credential_rotation_reuses_private_home_with_new_authenticated_identity')
            await adapter.close_profile()
            state['mode']='quiet';adapter=build()
            stamp=datetime.now(timezone.utc).isoformat();context={'id':'e'*32,'user_id':user}
            event['time_fired']=stamp;event['context']=context
            event['data']['new_state']['context']=context;event['data']['new_state']['last_updated']=stamp
            retained=capture(adapter,event,snapshot(policy(),'ha'))
            assert retained is not None
            await adapter.close_profile();native.close()
            native=NativeInbox(directory/'native.db',Redactor([token]));adapter=build()
            state['admit_failures']=1;before=len(accepted)
            assert await adapter.connect()
            connections=state['connections']
            await eventually(lambda:len(accepted)==before+1)
            row=native.db.execute('SELECT state,attempt FROM native_inbox WHERE id=?',(retained,)).fetchone()
            assert row['state']=='committed' and row['attempt']==1 and state['connections']==connections
            cases.append('actual_raw_journal_reopen_replays_retained_input_without_any_new_remote_event')
            cases.append('independent_replay_retries_real_failed_relay_admission_while_live_socket_is_idle')
            await adapter.close_profile()
            state['mode']='rate-limit';adapter=build()
            connecting=asyncio.create_task(adapter.connect())
            await eventually(lambda:adapter.homeassistant_status()['status']=='rate-limited')
            deadline=adapter.homeassistant_status()['next_attempt']
            assert 17<deadline-time.time()<=19
            before=state['requests'];await adapter.close_profile()
            result=await asyncio.gather(connecting,return_exceptions=True)
            assert isinstance(result[0],asyncio.CancelledError)
            adapter=build();connecting=asyncio.create_task(adapter.connect())
            await asyncio.sleep(.15)
            assert state['requests']==before
            assert abs(adapter.homeassistant_status()['next_attempt']-deadline)<.02
            await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            cases.append('actual_http429_retry_after_survives_close_and_profile_reopen_without_early_request')
            cases.append('close_during_connect_cancels_and_joins_workers_before_releasing_identity_lease')
            refused(lambda:profile.credentials({'server_url':'http://fixture.invalid','token':token}))
            refused(lambda:profile.credentials({'server_url':'https://fixture.invalid','token':token,'plugin':'arbitrary'}))
            cases.append('plain_http_and_arbitrary_plugin_configuration_are_refused')
        finally:
            for adapter in adapters:await adapter.close_profile()
            profile.install_transport=original;profile.Publisher=original_publisher
            for socket in state['sockets']:await socket.close()
            await runner.cleanup();native.close();relay.close()
    with tempfile.TemporaryDirectory(prefix='haos-hass-profile-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_native_profile_ws_kernel_lease_and_sqlite':True,
        'loopback_target_replacement_only_in_fixture':True,'public_gateway_enabled':False,
        'reconnect_delay_shortened_only_in_fixture':True,'unseen_remote_events_recovered':False,
        'external_account_notification_tls_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
