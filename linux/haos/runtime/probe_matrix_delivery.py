#!/usr/bin/env python3
"""Prepared native Matrix text sends into actual reopened HAOS outbox states."""
import asyncio
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import ClientSession,web
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.crypto import OlmMachine
    from mautrix.crypto.store.memory import MemoryCryptoStore
    from mautrix.types import UserID,DeviceID,RoomID,EventType,RoomEncryptionStateEventContent,EncryptionAlgorithm
    from plugins.platforms.matrix.adapter import MatrixAdapter,_CryptoStateStore
    from gateway.config import PlatformConfig
    from haos.gateway import GatewayEngine
    from haos.gateway_matrix_policy import PreparedMatrixPolicy
    from haos.gateway_matrix_http import HTTPBoundary
    from haos.gateway_matrix_delivery import install
    from haos.gateway_delivery import delivery_result
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'home')
        bot,peer,room,thread='@haos:owner.invalid','@owner:owner.invalid','!private:owner.invalid','$root'
        config={'version':1,'connectors':[{'id':'bot','platform':'matrix'}],'bindings':[
            {'id':'paired','connector':'bot','sender':peer,'chat':room,'scope':'','thread':'',
             'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-1000,
             'allow_plaintext':True,'require_mention':True,'matrix_devices':[]}]}
        current=lambda:PreparedMatrixPolicy(deepcopy(config))
        state={'status':200,'posts':0,'disconnect':False,'partial':False,'revoke':False,
            'encrypted':False,'encryption_status':404,'bad_receipt':False,'leaked':0}
        async def api(request):
            assert request.headers['Authorization']=='Bearer disposable-local-private-token'
            if request.path.endswith('/account/whoami'):return web.json_response({'user_id':bot,'device_id':'HAOS'})
            if request.path.rstrip('/').endswith('/state/m.room.encryption'):
                if state['encrypted']:return web.json_response({'algorithm':'m.megolm.v1.aes-sha2'})
                return web.json_response({'errcode':'M_NOT_FOUND' if state['encryption_status']==404 else 'M_FORBIDDEN'},status=state['encryption_status'])
            assert request.method=='PUT' and '/send/m.room.message/' in request.path,request.path
            state['posts']+=1;body=await request.json()
            assert body['msgtype']=='m.text' and body['m.mentions']=={}
            relation=body.get('m.relates_to',{})
            assert relation.get('event_id','')==config['bindings'][0]['thread']
            if state['disconnect']:request.transport.close();return web.Response()
            status=403 if state['partial'] and state['posts']==2 else state['status']
            if status==302:return web.Response(status=302,headers={'Location':'/leak'})
            if status!=200:return web.json_response({'errcode':'M_LIMIT_EXCEEDED' if status==429 else 'M_FORBIDDEN',
                'error':'disposable-local-private-token','retry_after_ms':19000},status=status)
            if state['revoke']:config['bindings'][0]['generation']='b'*64
            return web.json_response({'event_id':'invalid' if state['bad_receipt'] else '$local-'+str(state['posts'])})
        async def leak(request):state['leaked']+=1;return web.json_response({})
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api);app.router.add_route('*','/leak',leak)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession(trust_env=False) as session:
                client=Client(mxid=UserID(bot),device_id=DeviceID('HAOS'),api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',
                    token='disposable-local-private-token',client_session=session),state_store=MemoryStateStore())
                # An actual loaded OlmMachine makes the native adapter's broad
                # E2EE retry branch reachable; no dummy crypto/retry mock.
                crypto=OlmMachine(client,MemoryCryptoStore(bot,'disposable-fixture-key'),_CryptoStateStore(client.state_store,{RoomID(room)},client))
                await crypto.load();client.crypto=crypto
                await client.state_store.set_encryption_info(RoomID(room),RoomEncryptionStateEventContent(algorithm=EncryptionAlgorithm.MEGOLM_V1))
                boundary=HTTPBoundary('https://owner.invalid',bot,'HAOS');boundary._target=f'http://127.0.0.1:{port}';boundary.bind(client)
                boundary.confirm(client,await client.whoami())
                adapter=MatrixAdapter(PlatformConfig(enabled=True,token='disposable-local-private-token',extra={
                    'homeserver':'https://owner.invalid','user_id':bot,'device_id':'HAOS','e2ee_mode':'required'}))
                adapter._client=client;adapter._haos_native=SimpleNamespace(policy=current,connector='bot')
                install(adapter,boundary)
                async def run(name,expected,content=None,forged=None):
                    path=directory/(name+'.db');store=MissionStore(path);engine=GatewayEngine(store)
                    binding=config['bindings'][0]
                    await engine.receive(current(),'bot',{'platform':'matrix','sender':peer,'chat':room,'scope':'',
                        'thread':binding['thread'],'message_id':'$input-'+str(len(cases)),'is_bot':False,'text':'prepared native delivery fixture'},None)
                    obligation=engine.next_delivery(current())
                    metadata={'haos_binding':{'binding_id':obligation['binding_id'],'binding_digest':obligation['binding_digest']},
                        'haos_scope':'','thread_id':binding['thread']}
                    if forged:metadata.update(forged)
                    receipt=await adapter.send(room,content or obligation['content'],obligation['reply_to'],metadata)
                    assert 'disposable-local-private-token' not in (receipt.error or '')
                    result=delivery_result(receipt)
                    if state['revoke']:config['bindings'][0]['generation']='a'*64
                    engine.acknowledge(current(),obligation['id'],{'attempt':obligation['attempt'],**result})
                    store.close();store=MissionStore(path)
                    row=store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(obligation['id'],)).fetchone()
                    assert row['state']==expected,(name,row['state'],result)
                    store.close();cases.append(name);return result
                await run('actual_native_format_sdk_plaintext_and_reopened_outbox','delivered')
                config['bindings'][0]['thread']=thread;state['posts']=0
                await run('actual_native_root_thread_preserved','delivered')
                for status,expected in [(400,'failed'),(401,'failed'),(403,'failed'),(404,'failed'),(413,'failed'),(429,'pending'),(500,'uncertain'),(302,'uncertain')]:
                    state['status']=status;state['posts']=0
                    result=await run('single_native_http_'+str(status),expected)
                    assert state['posts']==1 and state['leaked']==0
                    if status==429:assert result['retry_after']==19
                state['status']=200;state['disconnect']=True;state['posts']=0
                await run('lost_receipt_does_not_trigger_native_e2ee_retry','uncertain');assert state['posts']==1
                state['disconnect']=False;state['bad_receipt']=True;state['posts']=0
                await run('malformed_success_receipt_stays_uncertain','uncertain');assert state['posts']==1
                state['bad_receipt']=False;state['partial']=True;state['posts']=0
                await run('partial_chunks_then_refusal_stays_uncertain','uncertain','p'*33000);assert state['posts']==2
                state['partial']=False;state['revoke']=True;state['posts']=0
                await run('revocation_between_chunks_stops_before_second_send','uncertain','r'*33000);assert state['posts']==1
                state['revoke']=False;state['posts']=0
                await run('forged_binding_cannot_send','failed',forged={'haos_binding':{'binding_id':'paired','binding_digest':'0'*64}});assert state['posts']==0
                await run('scope_substitution_cannot_send','failed',forged={'haos_scope':'foreign'});assert state['posts']==0
                await run('thread_substitution_cannot_send','failed',forged={'thread_id':'$foreign'});assert state['posts']==0
                try:await client.send_message_event(RoomID(room),EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':'unsolicited'},disable_encryption=True)
                except PermissionError:pass
                else:raise AssertionError('raw SDK send inherited account authority')
                assert state['posts']==0;cases.append('raw_sdk_send_outside_private_context_has_no_write_authority')
                state['encrypted']=True
                await run('encrypted_room_cannot_downgrade_or_infer_outbound_device_approval','failed');assert state['posts']==0
                state['encrypted']=False;state['encryption_status']=403
                await run('unavailable_encryption_state_cannot_downgrade','failed');assert state['posts']==0
                state['encryption_status']=404;config['bindings'][0]['allow_plaintext']=False
                public_fixture_key=base64.b64encode(b'x'*32).decode().rstrip('=')
                config['bindings'][0]['matrix_devices']=[{'device_id':'PHONE','ed25519':public_fixture_key,'curve25519':public_fixture_key}]
                await run('plaintext_needs_explicit_owner_consent','failed');assert state['posts']==0
        finally:await runner.cleanup()
    with tempfile.TemporaryDirectory() as temporary:asyncio.run(exercise(Path(temporary)))
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'encrypted_outbound_implemented':False,'installed_matrix_gateway_enabled':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    print(output,end='')


if __name__=='__main__':main()
