#!/usr/bin/env python3
"""Real prepared private ntfy factory, native lifecycle, HTTP and durable journals."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import web
    from haos.gateway import GatewayPolicy,digest
    from haos.gateway_ntfy import PreparedNtfyPolicy
    from haos import gateway_ntfy_profile as profile
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    from haos.gateway_delivery import delivery_result
    cases=[]
    async def exercise(directory):
        global_home=directory/'unrelated-home'; global_home.mkdir(mode=0o700)
        os.environ['HERMES_HOME']=str(global_home)
        parent=directory/'profiles'; parent.mkdir(mode=0o700)
        native=NativeInbox(directory/'native.db',Redactor(['private-fixture-token']))
        relay=RelayInbox(directory/'relay.db',Redactor(['private-fixture-token']))
        config={'version':1,'connectors':[{'id':'test','platform':'ntfy'}],'bindings':[{
            'id':'owner','connector':'test','sender':'private','chat':'private','scope':'','thread':'',
            'identity':'owner','capabilities':['create'],'since':int(time.time()*1000)-10000,
            'generation':'a'*64,'trust_topic_publishers':True}]}
        policy=lambda:PreparedNtfyPolicy(config)
        value={'server_url':'https://fixture.invalid','topic':'private','token':'private-fixture-token'}
        state={'mode':'normal','calls':[],'posts':[],'sockets':[],'event':{
            'event':'message','topic':'private','id':'original','time':int(time.time()),'message':'actual profile message'}}
        release=asyncio.Event()
        async def api(request):
            assert request.headers['Authorization']=='Bearer '+value['token']
            state['calls'].append((request.method,dict(request.query)))
            if request.method=='POST':
                state['posts'].append(await request.read())
                return web.json_response({'event':'message','topic':'private','id':'answer'+str(len(state['posts'])),'time':int(time.time())})
            if state['mode']=='auth': return web.Response(status=401,text=value['token'])
            response=web.StreamResponse(headers={'Content-Type':'application/x-ndjson'}); await response.prepare(request)
            state['sockets'].append(request.transport)
            await response.write(json.dumps(state['event']).encode()+b'\n')
            await release.wait()
            if request.transport is not None and not request.transport.is_closing(): await response.write_eof()
            return response
        app=web.Application(); app.router.add_get('/private/json',api); app.router.add_post('/private',api)
        runner=web.AppRunner(app); await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
        target='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        OriginalSubscription,OriginalPublisher=profile.Subscription,profile.Publisher
        class LocalSubscription(OriginalSubscription):
            def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self._target=target
        class LocalPublisher(OriginalPublisher):
            def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self._target=target
        profile.Subscription,profile.Publisher=LocalSubscription,LocalPublisher
        adapters=[]; accepted=[]
        def build():
            adapter=profile.build(value,parent,'test',policy,native); adapters.append(adapter)
            def receive(event):
                source=adapter_envelope(event,'ntfy'); relay.admit(policy(),'test',source); accepted.append(source)
                return True
            adapter.set_durable_message_handler(receive)
            return adapter
        async def eventually(test):
            async with asyncio.timeout(4):
                while not test(): await asyncio.sleep(.02)
        def denied(action):
            try: action()
            except (PermissionError,ValueError,OSError): return
            raise AssertionError('unsafe private profile admitted')
        try:
            adapter=build(); assert not adapter.is_connected and not state['calls']
            cases.append('prepared_factory_does_not_connect_or_send_before_explicit_start')
            location=adapter._haos_ntfy_profile
            denied(build); cases.append('actual_flock_refuses_duplicate_live_topic_profile')
            assert location.stat().st_mode&0o777==0o700 and (location/'profile.lock').stat().st_mode&0o777==0o600
            cases.append('native_identity_home_and_kernel_lease_are_private')
            binding=config['bindings'][0]
            metadata={'haos_scope':'','thread_id':'','haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)}}
            try: await adapter.send('private','before connect','original',metadata)
            except PermissionError: pass
            else: raise AssertionError('disconnected profile sent')
            cases.append('disconnected_profile_has_no_native_send_authority')
            assert await adapter.connect() and adapter.is_connected
            await eventually(lambda:len(accepted)==1)
            assert adapter.ntfy_status()['status']=='streaming'
            assert native.db.execute("SELECT state FROM native_inbox WHERE message_id='original'").fetchone()[0]=='committed'
            cases.append('actual_private_lifecycle_stream_native_capture_and_relay_commit')
            receipt=delivery_result(await adapter.send('private','profile answer','original',metadata))
            assert receipt['status']=='delivered' and state['posts']==[b'profile answer']
            cases.append('connected_profile_sends_actual_native_reply_only_under_exact_retained_route')
            for bad in [{**metadata,'thread_id':'invented'},{**metadata,'haos_scope':'invented'},
                        {**metadata,'publish_topic':'unapproved'},
                        {**metadata,'haos_binding':{'binding_id':'owner','binding_digest':'0'*64}}]:
                try: await adapter.send('private','forged route','original',bad)
                except PermissionError: pass
                else: raise AssertionError('forged route sent')
                assert len(state['posts'])==1
            cases.append('profile_refuses_forged_scope_thread_metadata_and_grant_without_http')
            before=len(state['calls']); await adapter.disconnect()
            assert not adapter.is_connected and adapter._haos_ntfy_publisher.closed
            assert adapter._haos_ntfy_subscription.client is None
            cases.append('disconnect_closes_real_stream_publisher_and_workers')
            assert await adapter.connect(); await eventually(lambda:len(state['calls'])>before)
            assert state['calls'][-1][1]['since']=='original' and len(accepted)==1
            cases.append('same_profile_reconnect_preserves_cursor_and_native_admission_idempotence')
            receipt=delivery_result(await adapter.send('private','after reconnect','original',metadata))
            assert receipt['status']=='delivered' and state['posts'][-1]==b'after reconnect'
            cases.append('reconnect_replaces_closed_publisher_with_new_guarded_native_send')
            await asyncio.gather(adapter.close_profile(),adapter.close_profile())
            assert not adapter.is_connected and adapter._haos_ntfy_profile_closed
            cases.append('concurrent_profile_close_releases_one_kernel_lease_without_deleting_state')
            replacement=build(); assert replacement._haos_ntfy_profile==location
            assert await replacement.connect() and len(accepted)==1
            cases.append('fresh_factory_reuses_profile_and_persisted_cursor_without_duplicate_relay')
            await replacement.disconnect(); state['mode']='auth'
            assert not await replacement.connect() and not replacement.is_connected
            assert replacement.ntfy_status()['last_error']=='authentication-denied'
            before=len(state['calls']); assert not await replacement.connect(); assert len(state['calls'])==before
            cases.append('real_401_survives_restart_and_stops_automatic_credential_retry')
            await replacement.close_profile(); value['token']='rotated-private-fixture-token'; state['mode']='normal'
            rotated=build(); assert rotated._haos_ntfy_profile==location
            assert await rotated.connect(); assert len(accepted)==1
            cases.append('explicit_credential_rotation_reuses_private_profile_and_preserves_existing_receipts')
            config['bindings']=[]
            await eventually(lambda:not rotated.is_connected)
            assert rotated.ntfy_status()['last_error']=='revoked'
            before=len(state['posts'])
            try: await rotated.send('private','revoked answer','original',metadata)
            except PermissionError: pass
            else: raise AssertionError('revoked profile sent')
            assert len(state['posts'])==before
            cases.append('owner_revocation_stops_native_profile_health_and_reply_authority')
            await rotated.close_profile()
            assert not list(global_home.iterdir()) and os.environ['HERMES_HOME']==str(global_home), [str(p.relative_to(global_home)) for p in global_home.rglob('*')]
            cases.append('actual_native_factory_and_status_never_write_unrelated_process_global_home')
            for change in [{'token':''},{'topic':'topic/escape'},{'server_url':'http://unsafe.invalid'},{'extra':{}}]:
                denied(lambda:profile.credentials({**value,**change}))
            cases.append('private_factory_refuses_unbounded_or_ambiguous_credential_configuration')
            config['bindings']=[dict(binding)]
            neighbor=directory/'unchanged-neighbor'; neighbor.write_text('retained'); neighbor.chmod(0o600)
            lock=location/'profile.lock'; saved=location/'saved.lock'; lock.rename(saved)
            lock.symlink_to(neighbor); denied(build)
            assert neighbor.read_text()=='retained' and neighbor.stat().st_mode&0o777==0o600
            lock.unlink(); os.link(neighbor,lock); denied(build)
            assert neighbor.read_text()=='retained' and neighbor.stat().st_mode&0o777==0o600
            lock.unlink(); saved.rename(lock)
            cases.append('symlink_and_hardlinked_profile_leases_are_refused_without_touching_neighbor')
            location.chmod(0o750); denied(build); location.chmod(0o700)
            cases.append('group_readable_private_profile_is_refused')
            link=directory/'linked-parent'; link.symlink_to(parent,target_is_directory=True)
            denied(lambda:profile.build(value,link,'test',policy,native))
            cases.append('symlink_parent_is_refused_before_any_native_import_or_network')
            denied(lambda:profile.build(value,parent,'test',lambda:GatewayPolicy({'version':1,'connectors':[],'bindings':[]}),native))
            cases.append('private_factory_cannot_bypass_independent_owner_policy')
        finally:
            release.set()
            for adapter in adapters: await adapter.close_profile()
            profile.Subscription,profile.Publisher=OriginalSubscription,OriginalPublisher
            relay.close(); native.close(); await runner.cleanup()
    with tempfile.TemporaryDirectory(prefix='haos-ntfy-profile-') as value: asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_native_factory_http_sqlite_and_flock':True,
        'loopback_target_replacement_only_in_fixture':True,'public_gateway_enabled':False,'external_subscription_or_delivery_accepted':False,
        'installed_service_or_boot_accepted':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt))


if __name__=='__main__':main()
