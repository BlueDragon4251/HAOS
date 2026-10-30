#!/usr/bin/env python3
"""Actual immutable Matrix client encoding through an isolated bounded HTTP boundary."""
import asyncio
from email.utils import formatdate
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import ClientSession,web
    from mautrix.api import HTTPAPI,Method
    from mautrix.client import Client
    from mautrix.types import UserID,DeviceID,RoomID,EventType
    from mautrix.errors import MatrixRequestError,MUnknownToken,MLimitExceeded
    from haos.gateway_matrix_http import HTTPBoundary,homeserver_url
    cases=[]
    async def exercise():
        user='@haos:owner.invalid';device='LOCAL';room='!approved:owner.invalid';token='disposable-local-private-token'
        state={'calls':[],'leaked':0,'status':200,'bad':False,'large':False,'approve_write':False,'retry_ms':19000,'retry_after':'19'}
        async def api(request):
            state['calls'].append((request.method,request.path))
            assert request.headers.get('Authorization')=='Bearer '+token
            if state['status']==302:return web.Response(status=302,headers={'Location':'/leak'})
            if state['status']!=200:return web.json_response({'errcode':'M_UNKNOWN_TOKEN' if state['status']==401 else 'M_LIMIT_EXCEEDED' if state['status']==429 else 'M_UNKNOWN',
                'error':token,**({'retry_after_ms':state['retry_ms']} if state['retry_ms'] is not None else {})},
                status=state['status'],headers={'Retry-After':state['retry_after']})
            if state['bad']:return web.Response(text='{invalid')
            if state['large']:return web.Response(body=b' '*(8*1024*1024+1))
            if request.path.endswith('/account/whoami'):return web.json_response({'user_id':user,'device_id':device})
            if request.path.endswith('/sync'):return web.json_response({'next_batch':'local-cursor','rooms':{}})
            if '/send/' in request.path:
                body=await request.json();assert body['body']=='local approved write fixture'
                return web.json_response({'event_id':'$local-fixture'})
            if '/state/' in request.path:return web.json_response({'name':'Approved local room'})
            raise AssertionError('unexpected SDK HTTP path '+request.path)
        async def leak(_request):state['leaked']+=1;return web.json_response({})
        app=web.Application();app.router.add_route('*','/_matrix/{tail:.*}',api);app.router.add_route('*','/prefix/_matrix/{tail:.*}',api);app.router.add_route('*','/leak',leak)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            for value in ['http://owner.invalid','https://token@owner.invalid','https://owner.invalid?token=x','https://owner.invalid/../else']:
                try:homeserver_url(value)
                except ValueError:pass
                else:raise AssertionError('ambiguous or unprotected homeserver accepted')
            cases.append('owner_homeserver_requires_unambiguous_https')
            async with ClientSession(trust_env=False) as session:
                client=Client(mxid=UserID(user),device_id=DeviceID(device),
                    api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',token=token,client_session=session))
                boundary=HTTPBoundary('https://owner.invalid',user,device,allow_room_read=lambda value:value==room,
                    allow_write=lambda method,path:state['approve_write'] and method=='PUT' and path==('rooms',room,'send','m.room.message','local-transaction'))
                # Only the fixture maps the approved production HTTPS target
                # onto its local HTTP listener; there is no production skip flag.
                boundary._target=f'http://127.0.0.1:{port}';boundary.bind(client)
                before=len(state['calls'])
                try:await client.sync(timeout=0)
                except PermissionError:pass
                else:raise AssertionError('unconfirmed account could sync')
                assert len(state['calls'])==before;cases.append('private_account_proof_required_before_sync')
                proof=await client.whoami();boundary.confirm(client,proof)
                assert (await client.sync(timeout=0))['next_batch']=='local-cursor'
                cases.append('actual_whoami_and_sync_codecs_cross_confirmed_boundary')
                assert (await client.get_state_event(RoomID(room),EventType.ROOM_NAME)).name=='Approved local room'
                cases.append('explicit_room_read_crosses_actual_sdk_path_encoding')
                for method,path in [(Method.GET,'/_matrix/client/v3/rooms/!other:owner.invalid/state/m.room.name'),
                        (Method.DELETE,'/_matrix/client/v3/devices/LOCAL'),(Method.POST,'/_matrix/client/v3/createRoom'),
                        (Method.POST,'/_matrix/client/v3/join/!other:owner.invalid'),
                        (Method.PUT,'/_matrix/client/v3/user/'+user+'/account_data/m.direct')]:
                    before=len(state['calls'])
                    try:await client.api.request(method,path)
                    except PermissionError:pass
                    else:raise AssertionError('unapproved operation crossed boundary')
                    assert len(state['calls'])==before
                cases.append('foreign_rooms_and_destructive_or_unsolicited_writes_refused_before_http')
                before=len(state['calls'])
                try:await client.send_message_event(RoomID(room),EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':'local approved write fixture'},txn_id='local-transaction')
                except PermissionError:pass
                else:raise AssertionError('room write had implicit authority')
                assert len(state['calls'])==before
                state['approve_write']=True
                assert str(await client.send_message_event(RoomID(room),EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':'local approved write fixture'},txn_id='local-transaction'))=='$local-fixture'
                cases.append('actual_sdk_send_needs_explicit_local_callback_not_account_presence')
                for status,kind in [(401,MUnknownToken),(429,MLimitExceeded),(500,MatrixRequestError),(302,MatrixRequestError)]:
                    state['status']=status;before=len(state['calls'])
                    try:await client.sync(timeout=0)
                    except kind as error:
                        assert token not in str(error) and error.http_status==status
                        if status==429:assert error.retry_after==19
                    else:raise AssertionError('native typed refusal was lost')
                    assert len(state['calls'])==before+1 and state['leaked']==0
                    cases.append('bounded_typed_single_request_'+str(status))
                state['status']=429;state['retry_after']=formatdate(time.time()+3600,usegmt=True)
                for name,milliseconds in [('native-ms-priority',19000),('missing-native-ms',None),('invalid-native-ms',-1)]:
                    state['retry_ms']=milliseconds;before=len(state['calls'])
                    try:await client.sync(timeout=0)
                    except MLimitExceeded as error:
                        assert error.retry_after==19 if milliseconds==19000 else 3598<=error.retry_after<=3600
                    else:raise AssertionError('rate limit unexpectedly accepted')
                    assert len(state['calls'])==before+1
                    cases.append('actual_native_retry_after_'+name+'_and_http_date')
                state['retry_ms']=19000;state['retry_after']='19'
                state['status']=500;before=len(state['calls'])
                try:
                    async with asyncio.timeout(2):
                        await client.api.request(Method.GET,'/_matrix/client/v3/sync',retry_count=3)
                except MatrixRequestError:pass
                else:raise AssertionError('explicit SDK retry setting returned a success')
                assert len(state['calls'])==before+1
                cases.append('explicit_sdk_retry_argument_cannot_replay_request')
                state['status']=200;state['bad']=True
                try:await client.sync(timeout=0)
                except ValueError:pass
                else:raise AssertionError('malformed body accepted')
                state['bad']=False;cases.append('malformed_success_body_has_no_native_result')
                state['large']=True
                try:await client.sync(timeout=0)
                except ValueError:pass
                else:raise AssertionError('oversized body accepted')
                state['large']=False;cases.append('response_size_is_bounded_before_json_decode')
                before=len(state['calls'])
                try:await client.api.request(Method.GET,'/_matrix/client/v3/sync',query_params={'user_id':'@other:owner.invalid'})
                except PermissionError:pass
                else:raise AssertionError('impersonation query accepted')
                assert len(state['calls'])==before;cases.append('appservice_impersonation_query_has_no_authority')
                client.api.token='changed-private-token'
                try:await client.sync(timeout=0)
                except PermissionError:pass
                else:raise AssertionError('changed token silently inherited confirmation')
                assert len(state['calls'])==before;cases.append('token_replacement_needs_new_identity_proof')
                client.api.token=token;client.api.base_url=client.api.base_url.with_host('localhost')
                try:await client.whoami()
                except PermissionError:pass
                else:raise AssertionError('foreign origin accepted')
                assert len(state['calls'])==before;cases.append('another_origin_cannot_receive_private_auth_header')
                prefixed=Client(mxid=UserID(user),device_id=DeviceID(device),
                    api=HTTPAPI(base_url=f'http://127.0.0.1:{port}/prefix',token=token,client_session=session))
                guarded=HTTPBoundary('https://owner.invalid/prefix',user,device)
                guarded._target=f'http://127.0.0.1:{port}/prefix';guarded.bind(prefixed)
                guarded.confirm(prefixed,await prefixed.whoami())
                assert (await prefixed.sync(timeout=0))['next_batch']=='local-cursor'
                assert state['calls'][-1][1]=='/prefix/_matrix/client/v3/sync'
                cases.append('actual_sdk_preserves_owner_deployment_prefix')

        finally:await runner.cleanup()
    asyncio.run(exercise())
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'haos_matrix_gateway_enabled':False,'mission_authorization_accepted':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
