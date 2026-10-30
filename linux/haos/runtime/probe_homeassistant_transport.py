#!/usr/bin/env python3
"""Actual pinned HA WS auth/subscription over loopback with private admission."""
import asyncio
from datetime import datetime,timezone
from email.utils import formatdate
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import web
    from haos.gateway import GatewayPolicy
    from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy,install as ingress
    from haos.gateway_homeassistant_transport import install as transport
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry
        from plugins.platforms.homeassistant import adapter as module
        class Context:
            def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
        context=Context();module.register(context)
        user='a'*32;entity='input_text.owner';token='disposable-private-hass-token'
        config={'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
            'id':'owner','connector':'ha','sender':user,'chat':entity,'scope':'','thread':'',
            'identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-10000}]}
        policy=lambda:GatewayPolicy(config)
        native=NativeInbox(directory/'native.db',Redactor([token]));accepted=[];adapters=[]
        state={'mode':'normal','requests':0,'auth':[],'subscribe':[],'sockets':[],'leaked':0,'events':0}
        ack=asyncio.Event();release=asyncio.Event();send=asyncio.Event();silent=asyncio.Event()
        def event():
            state['events']+=1;stamp=datetime.now(timezone.utc).isoformat()
            identity=str(state['events']).zfill(32);source={'id':identity,'user_id':user}
            return {'event_type':'state_changed','time_fired':stamp,'context':source,'data':{'entity_id':entity,
                'old_state':{'state':'old'},'new_state':{'entity_id':entity,'state':'new','last_updated':stamp,
                    'context':dict(source),'attributes':{'friendly_name':'Owner'}}}}
        async def ws(request):
            state['requests']+=1;mode=state['mode']
            if mode=='redirect':return web.Response(status=302,headers={'Location':'/leak'})
            if mode=='http401':return web.Response(status=401,text=token)
            if mode=='http429':return web.Response(status=429,text=token,headers={'Retry-After':'19'})
            if mode=='http429-date':return web.Response(status=429,text=token,headers={'Retry-After':formatdate(time.time()+3600,usegmt=True)})
            socket=web.WebSocketResponse();await socket.prepare(request);state['sockets'].append(socket)
            if mode=='silent-first':await silent.wait();return socket
            if mode=='wrong-first':await socket.send_json({'type':'auth_ok','message':token});return socket
            await socket.send_json({'type':'auth_required','ha_version':'fixture'})
            auth=await socket.receive_json();assert auth=={'type':'auth','access_token':token};state['auth'].append(auth['type'])
            if mode=='auth-invalid':await socket.send_json({'type':'auth_invalid','message':token});return socket
            await socket.send_json({'type':'auth_ok','ha_version':'fixture'})
            sub=await socket.receive_json();assert sub['type']=='subscribe_events' and sub['event_type']=='state_changed';state['subscribe'].append(sub['id'])
            if mode=='early-event':await socket.send_json({'id':sub['id'],'type':'event','success':True,'event':event()});return socket
            if mode=='duplicate-ack':await socket.send_str('{"id":'+str(sub['id'])+',"type":"result","success":false,"success":true}');return socket
            if mode=='wrong-id':await socket.send_json({'id':sub['id']+1,'type':'result','success':True,'result':token});return socket
            if mode=='bool-id':await socket.send_json({'id':True,'type':'result','success':True});return socket
            await ack.wait()
            await socket.send_json({'id':sub['id'],'type':'result','success':True,'result':None})
            await send.wait()
            if mode=='bad-event-id':await socket.send_json({'id':sub['id']+1,'type':'event','event':event()})
            elif mode=='duplicate-event':await socket.send_str('{"id":'+str(sub['id'])+',"type":"event","event":{},"event":{}}')
            elif mode=='oversize':await socket.send_str('X'*65537)
            elif mode!='quiet':await socket.send_json({'id':sub['id'],'type':'event','event':event()})
            await release.wait()
            await socket.close();return socket
        async def leak(request):state['leaked']+=1;return web.Response()
        app=web.Application();app.router.add_get('/api/websocket',ws);app.router.add_route('*','/leak',leak)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        target='ws://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/api/websocket'
        def build():
            adapter=ingress(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,token=token,
                extra={'url':'https://owner.invalid','watch_all':True,'cooldown_seconds':30}))))
            adapter._haos_native=SimpleNamespace(inbox=native,connector='ha',policy=policy)
            def receive(message):accepted.append(adapter_envelope(message,'homeassistant'));return True
            adapter.set_durable_message_handler(receive)
            adapter=transport(adapter);adapter._haos_ha_transport._target=target;adapters.append(adapter)
            return adapter
        async def until(test):
            async with asyncio.timeout(4):
                while not test():await asyncio.sleep(.01)
        logs=io.StringIO();handler=logging.StreamHandler(logs);logger=logging.getLogger('plugins.platforms.homeassistant.adapter');logger.addHandler(handler)
        try:
            adapter=build();boundary=adapter._haos_ha_transport
            task=asyncio.create_task(adapter._ws_connect())
            await until(lambda:len(state['subscribe'])==1)
            assert not task.done() and not boundary.confirmed and not accepted
            cases.append('actual_native_auth_and_subscribe_wait_for_exact_server_ack_before_authority')
            ack.set();assert await task and boundary.confirmed
            read=asyncio.create_task(adapter._read_events());send.set();await until(lambda:len(accepted)==1)
            assert accepted[0]['sender']==user and accepted[0]['chat']==entity and native.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='committed'
            cases.append('actual_authenticated_loopback_ws_frame_reaches_native_codec_only_after_durable_capture')
            release.set();await asyncio.wait_for(read,3);assert not boundary.confirmed
            cases.append('actual_socket_eof_revokes_transport_health_and_stream_authority')
            for mode in ['redirect','http401','http429','http429-date','wrong-first','auth-invalid','early-event','duplicate-ack','wrong-id','bool-id']:
                state['mode']=mode;adapter=build();before=state['requests']
                assert not await adapter._ws_connect() and not adapter._haos_ha_transport.confirmed
                assert state['requests']==before+1 and state['leaked']==0 and len(accepted)==1
                assert token not in logs.getvalue()
                if mode=='http429':
                    assert adapter._haos_ha_transport.status=='rate-limited'
                    assert adapter._haos_ha_transport.retry_after==19
                if mode=='http429-date':
                    assert adapter._haos_ha_transport.status=='rate-limited'
                    assert 3598<=adapter._haos_ha_transport.retry_after<=3600
                await adapter._haos_ha_transport.close()
                cases.append('actual_native_handshake_refuses_'+mode+'_without_token_log_or_input')
            for mode in ['bad-event-id','duplicate-event','oversize']:
                release.clear();state['mode']=mode;adapter=build();assert await adapter._ws_connect()
                try:await adapter._read_events()
                except ConnectionError:pass
                assert len(accepted)==1 and not adapter._haos_ha_transport.confirmed
                if mode=='oversize':
                    raw=adapter._haos_ha_transport.socket.raw
                    assert raw.close_code==1009
                release.set();await adapter._haos_ha_transport.close();cases.append('actual_bounded_ws_'+mode+'_has_no_ingress_authority')
            release.clear();state['mode']='quiet';adapter=build();assert await adapter._ws_connect();boundary=adapter._haos_ha_transport
            old_socket=boundary.socket;old_reader=asyncio.create_task(adapter._read_events());await asyncio.sleep(0)
            assert await adapter._ws_connect() and boundary.socket is not old_socket
            await state['sockets'][-2].send_json({'id':boundary.subscription_id,'type':'event','event':event()})
            try:await asyncio.wait_for(old_reader,3)
            except PermissionError:pass
            else:raise AssertionError('superseded socket borrowed new subscription proof')
            assert len(accepted)==1 and boundary.confirmed
            cases.append('superseded_native_socket_cannot_borrow_new_subscription_proof_or_revoke_it')
            before=state['requests']
            try:await adapter.send('anywhere','unapproved notification')
            except PermissionError:pass
            else:raise AssertionError('prepared transport enabled native notification fallback')
            assert state['requests']==before;cases.append('unimplemented_notification_and_standalone_fallback_have_no_send_capability')
            for kwargs in [{'ssl':False},{'verify_ssl':False},{'proxy':'http://unapproved.invalid'}]:
                try:await adapter._session.ws_connect(boundary.endpoint,**kwargs)
                except PermissionError:pass
                else:raise AssertionError('TLS or proxy policy bypass')
            assert state['requests']==before;cases.append('native_session_cannot_disable_tls_or_add_an_unapproved_proxy')
            for request in [('POST','https://owner.invalid/api/services/light/turn_on'),('GET','https://unapproved.invalid/api/websocket')]:
                try:await adapter._session.request(*request)
                except PermissionError:pass
                else:raise AssertionError('private session performed unapproved REST or cross-origin request')
            try:await adapter._ws.send_json({'id':99,'type':'call_service','domain':'light','service':'turn_on'})
            except PermissionError:pass
            else:raise AssertionError('native auth socket performed unapproved device control')
            assert state['requests']==before
            cases.append('private_native_rest_and_ws_sessions_cannot_call_device_services_or_other_origins')
            adapter._hass_token='changed-private-token'
            try:boundary.require_ready()
            except PermissionError:pass
            else:raise AssertionError('old socket retained rotated-token authority')
            assert not boundary.confirmed;cases.append('token_rotation_revokes_existing_authenticated_socket_proof')
            release.set();await boundary.close();adapter._hass_token=token
            release.clear()
            adapter=build();assert await adapter._ws_connect();config['bindings'][0]['generation']='b'*64
            try:adapter._haos_ha_transport.require_ready()
            except PermissionError:pass
            else:raise AssertionError('old socket retained regrant authority')
            assert not adapter._haos_ha_transport.confirmed
            cases.append('owner_regrant_revokes_existing_native_subscription_proof')
            ack.clear();adapter=build();count=len(state['subscribe'])
            pending=asyncio.create_task(adapter._ws_connect());await until(lambda:len(state['subscribe'])>count)
            config['bindings'][0]['generation']='c'*64;ack.set()
            assert not await asyncio.wait_for(pending,8) and adapter._haos_ha_transport.status=='revoked'
            assert len(accepted)==1
            cases.append('owner_regrant_during_held_native_ack_cannot_complete_authentication_proof')
            release.set();state['mode']='silent-first';adapter=build()
            boundary=adapter._haos_ha_transport;boundary._handshake_seconds=.05
            timeout=asyncio.create_task(adapter._ws_connect());await asyncio.sleep(.1);silent.set()
            assert not await asyncio.wait_for(timeout,3) and boundary.status=='handshake-timeout'
            assert boundary.socket.closed and len(accepted)==1
            cases.append('real_held_ws_handshake_has_bounded_deadline_and_closes_without_native_auth_proof')
            silent.clear();adapter=build();boundary=adapter._haos_ha_transport
            cancelled=asyncio.create_task(adapter._ws_connect());await until(lambda:boundary.socket is not None)
            cancelled.cancel();silent.set()
            try:await asyncio.wait_for(cancelled,3)
            except asyncio.CancelledError:pass
            else:raise AssertionError('caller cancellation was swallowed')
            assert boundary.socket.closed and boundary.status=='cancelled' and len(accepted)==1
            cases.append('actual_caller_cancellation_closes_native_ws_and_does_not_enable_auth_or_input')

        finally:
            release.set();ack.set();send.set();silent.set()
            for adapter in adapters:await adapter._haos_ha_transport.close()
            logger.removeHandler(handler);native.close();await runner.cleanup()
    with tempfile.TemporaryDirectory(prefix='haos-hass-ws-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_auth_subscription_codec_and_aiohttp':True,
        'loopback_ws_target_replacement_only_in_fixture':True,'held_timeout_case_fixture_deadline_seconds':.05,'public_gateway_enabled':True,
        'external_account_or_tls_or_notification_accepted':False,'agent_device_tools_enabled':False,'installed_service_accepted':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
