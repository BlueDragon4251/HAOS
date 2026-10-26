#!/usr/bin/env python3
"""Native HA POST plus actual native WS receipt witness, only local fixture IO."""
import asyncio
from datetime import datetime,timezone
from email.utils import formatdate
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import web
    from haos.gateway import digest,GatewayEngine
    from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy
    from haos.gateway_homeassistant_delivery import Publisher
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_delivery import delivery_result
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry
        from plugins.platforms.homeassistant import adapter as module
        class Context:
            def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
        context=Context();module.register(context)
        token='disposable-private-hass-delivery-token';user='a'*32;entity='input_text.owner'
        config={'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
            'id':'owner','connector':'ha','sender':user,'chat':entity,'scope':'','thread':'','identity':'owner',
            'capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-10000,
            'homeassistant_shared_notifications':False}]}
        policy=lambda:PreparedHomeAssistantPolicy(config)
        state={'posts':[],'status':200,'mode':'normal','notifications':{},'gets':0,'leaks':0,'revoke':False,'partial':False,'retry_after':'19'}
        publishers=[];sockets=[];proof_waiting=asyncio.Event();release_proof=asyncio.Event()
        async def post(request):
            assert request.headers['Authorization']=='Bearer '+token
            data=await request.json();assert set(data)=={'title','message','notification_id'} and data['title']=='Hermes Agent'
            assert data['notification_id'].startswith('haos_') and len(data['message'])<=4096
            state['posts'].append(data)
            status=429 if state['partial'] and len(state['posts'])==2 else state['status']
            if status!=200:return web.Response(status=status,text=token,headers={'Location':'/leak','Retry-After':state['retry_after']})
            if state['mode']!='missing':
                saved=dict(data);saved['created_at']=datetime.now(timezone.utc).isoformat()
                if state['mode']=='wrong-message':saved['message']='unapproved replacement'
                if state['mode']=='wrong-id':saved['notification_id']='unapproved'
                state['notifications'][saved['notification_id']]=saved
            if state['mode']=='lost':request.transport.close();return web.Response()
            if state['revoke']:config['bindings'][0]['generation']='c'*64
            return web.json_response([])
        async def websocket(request):
            socket=web.WebSocketResponse();await socket.prepare(request);sockets.append(socket)
            await socket.send_json({'type':'auth_required','ha_version':'fixture'})
            assert await socket.receive_json()=={'type':'auth','access_token':token}
            if state['mode']=='auth-invalid':await socket.send_json({'type':'auth_invalid','message':token});return socket
            await socket.send_json({'type':'auth_ok','ha_version':'fixture'})
            sub=await socket.receive_json();assert sub['type']=='subscribe_events' and sub['event_type']=='state_changed'
            await socket.send_json({'id':sub['id'],'type':'result','success':True,'result':None})
            async for message in socket:
                value=json.loads(message.data)
                assert set(value)=={'id','type'} and value['type']=='persistent_notification/get'
                state['gets']+=1;result=list(state['notifications'].values())
                if state['mode']=='held-proof':
                    proof_waiting.set();await release_proof.wait()
                if state['mode']=='duplicate-proof' and state['posts']:
                    result.extend(row for row in list(result) if row['notification_id']==state['posts'][-1]['notification_id'])
                await socket.send_json({'id':value['id']+1 if state['mode']=='wrong-result-id' else value['id'],
                    'type':'result','success':True,'result':result})
            return socket
        async def leak(request):state['leaks']+=1;return web.Response()
        app=web.Application();app.router.add_post('/api/services/persistent_notification/create',post)
        app.router.add_get('/api/websocket',websocket);app.router.add_route('*','/leak',leak)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        base='127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        def build():
            adapter=durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,token=token,extra={'url':'https://owner.invalid'})))
            adapter._haos_native=SimpleNamespace(connector='ha',policy=policy)
            publisher=Publisher(adapter);publisher._target='http://'+base
            publisher.witness.boundary._target='ws://'+base+'/api/websocket';publishers.append(publisher)
            return publisher
        async def run(name,expected,content='actual native notification',outbox=False):
            publisher=build();binding=dict(config['bindings'][0]);state['posts']=[]
            if outbox:
                path=directory/(name+'.db');store=MissionStore(path);engine=GatewayEngine(store)
                await engine.receive(policy(),'ha',{'platform':'homeassistant','sender':user,'chat':entity,'scope':'','thread':'',
                    'message_id':digest(name),'is_bot':False,'text':'native notification outbox fixture'},None)
                obligation=engine.next_delivery(policy());identity=obligation['id']
            else:identity=digest(name)
            result=delivery_result(await publisher.send(binding,identity,content))
            assert result['status']==expected,(name,result)
            if result['status']=='delivered':
                assert result['message_id']==state['posts'][-1]['notification_id']
                assert result['message_id'] in state['notifications']
            if outbox:
                engine.acknowledge(policy(),identity,{'attempt':obligation['attempt'],**result});store.close()
                store=MissionStore(path);engine=GatewayEngine(store)
                wanted={'delivered':'delivered','uncertain':'uncertain','retry':'pending','failed':'failed'}[expected]
                assert store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(identity,)).fetchone()[0]==wanted
                assert engine.next_delivery(policy()) is None
                store.close()
            await publisher.close();cases.append(name)
            return result
        try:
            publisher=build();before=len(state['posts'])
            try:await publisher.send(config['bindings'][0],digest('no-shared-approval'),'private mission data')
            except PermissionError:pass
            else:raise AssertionError('shared notifications were silently authorized')
            assert len(state['posts'])==before;await publisher.close()
            cases.append('shared_instance_audience_requires_explicit_owner_grant_before_any_post')
            config['bindings'][0]['homeassistant_shared_notifications']=True;config['bindings'][0]['generation']='b'*64
            await run('native_http_and_authenticated_ws_verify_exact_real_notification_id','delivered',outbox=True)
            await run('native_unicode_chunks_preserve_complete_message','delivered','🙂'*2300+' full ending')
            assert ''.join(row['message'] for row in state['posts'])=='🙂'*2300+' full ending'
            for status in [400,401,403,404,413,429,500,302]:
                state['status']=status;before=state['gets']
                expected='retry' if status==429 else 'uncertain' if status in {500,302} else 'failed'
                result=await run('native_single_post_'+str(status),expected,outbox=status in {429,500})
                assert len(state['posts'])==1 and state['gets']==before and not state['leaks']
                if status==429:assert result['retry_after']==19
            state['status']=429;state['retry_after']=formatdate(time.time()+3600,usegmt=True)
            result=await run('native_http_date_retry_after_preserves_real_outbox_wait','retry',outbox=True)
            assert 3598<=result['retry_after']<=3600 and len(state['posts'])==1
            state['retry_after']='19'
            state['status']=200
            for mode in ['missing','wrong-message','wrong-id','duplicate-proof','wrong-result-id','auth-invalid','lost']:
                state['mode']=mode
                await run('native_unproven_'+mode+'_cannot_use_random_sdk_uuid','uncertain',outbox=mode in {'missing','lost'})
                assert len(state['posts'])==1
            for mode in ['missing','wrong-result-id','duplicate-proof']:
                state['mode']=mode;publisher=build();state['posts']=[]
                binding=dict(config['bindings'][0])
                result=delivery_result(await publisher.send(binding,digest('unconfirmed-'+mode),'first obligation'))
                assert result['status']=='uncertain' and len(state['posts'])==1
                assert not publisher.witness.boundary.confirmed
                assert publisher.witness.adapter._ws is None and publisher.witness.adapter._session is None
                old_socket=publisher.witness.boundary.socket
                assert old_socket.closed
                state['mode']='normal'
                result=delivery_result(await publisher.send(binding,digest('distinct-next-'+mode),'different new obligation'))
                assert result['status']=='delivered' and len(state['posts'])==2
                assert publisher.witness.boundary.socket is not old_socket
                assert publisher.witness.boundary.confirmed
                await publisher.close()
                cases.append('unconfirmed_'+mode+'_closes_witness_and_next_distinct_obligation_reauthenticates')
            state['mode']='held-proof';publisher=build();state['posts']=[]
            binding=dict(config['bindings'][0])
            task=asyncio.create_task(publisher.send(binding,digest('cancelled-witness'),'ambiguous previous obligation'))
            await asyncio.wait_for(proof_waiting.wait(),2)
            old_socket=publisher.witness.boundary.socket
            task.cancel();release_proof.set()
            try:await task
            except asyncio.CancelledError:pass
            else:raise AssertionError('cancelled witness did not propagate cancellation')
            assert old_socket.closed and not publisher.witness.boundary.confirmed
            assert publisher.witness.adapter._ws is None and publisher.witness.adapter._session is None
            state['mode']='normal'
            result=delivery_result(await publisher.send(binding,digest('distinct-after-cancel'),'separate new obligation'))
            assert result['status']=='delivered' and len(state['posts'])==2
            assert publisher.witness.boundary.socket is not old_socket
            await publisher.close();cases.append('cancelled_witness_closes_connection_and_never_resends_previous_obligation')
            state['mode']='normal';state['partial']=True
            await run('partial_notification_then_429_never_retries_complete_reply','uncertain','p'*5000,outbox=True)
            assert len(state['posts'])==2;state['partial']=False
            state['revoke']=True
            await run('revoke_after_first_native_post_prevents_next_chunk_and_receipt_claim','uncertain','r'*5000)
            assert len(state['posts'])==1;state['revoke']=False
            config['bindings'][0]['generation']='d'*64
            publisher=build();before=len(state['posts'])
            try:await publisher.adapter.send(entity,'unscoped notification')
            except PermissionError:pass
            else:raise AssertionError('native standalone fallback retained publication authority')
            assert len(state['posts'])==before
            cases.append('direct_native_send_has_no_shared_notification_capability')
            publisher.adapter._hass_token='rotated-private-hass-token'
            try:await publisher.send(config['bindings'][0],digest('rotated'),'no old identity')
            except PermissionError:pass
            else:raise AssertionError('rotated token retained publisher authority')
            assert len(state['posts'])==before;cases.append('token_rotation_revokes_old_private_notification_publisher')
        finally:
            for publisher in publishers:await publisher.close()
            for socket in sockets:await socket.close()
            await runner.cleanup()
    with tempfile.TemporaryDirectory(prefix='haos-hass-notify-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_send_codec_rest_ws_and_outbox':True,
        'homeassistant_core_protocol_reference':'9eb964b8b95fddc61ec4841277fbce7ce32dc586',
        'loopback_targets_replaced_only_in_fixture':True,'public_gateway_enabled':False,'shared_audience_requires_explicit_owner_grant':True,
        'external_notification_or_tls_account_accepted':False,'agent_device_tools_enabled':False,'installed_service_accepted':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
