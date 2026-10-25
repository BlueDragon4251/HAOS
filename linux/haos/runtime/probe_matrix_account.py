#!/usr/bin/env python3
"""Actual SDK public-device discovery and native signed-key validation over local HTTP."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import ClientSession,web
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.crypto.account import OlmAccount
    from mautrix.types import UserID,DeviceID
    from mautrix.errors import DeviceValidationError,MatrixRequestError
    from haos.gateway_matrix_http import HTTPBoundary
    from haos.gateway_matrix_account import devices
    cases=[]
    async def exercise():
        bot,peer='@haos:owner.invalid','@owner:owner.invalid';token='disposable-local-private-token'
        account=OlmAccount();signed=account.get_device_keys(UserID(peer),DeviceID('PHONE')).serialize()
        state={'keys':{'PHONE':signed},'user':bot,'device':'HAOS','status':200,'failures':{},'calls':[]}
        async def api(request):
            state['calls'].append(request.path);assert request.headers['Authorization']=='Bearer '+token
            if state['status']!=200:return web.json_response({'errcode':'M_LIMIT_EXCEEDED' if state['status']==429 else 'M_UNKNOWN_TOKEN',
                'error':token,'retry_after_ms':19000},status=state['status'])
            if request.path.endswith('/account/whoami'):return web.json_response({'user_id':state['user'],'device_id':state['device']})
            assert request.path.endswith('/keys/query') and request.method=='POST'
            assert (await request.json())['device_keys']=={peer:[]}
            return web.json_response({'device_keys':{peer:state['keys']},'failures':state['failures']})
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession(trust_env=False) as session:
                client=Client(mxid=UserID(bot),device_id=DeviceID('HAOS'),api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',token=token,client_session=session))
                boundary=HTTPBoundary('https://owner.invalid',bot,'HAOS');boundary._target=f'http://127.0.0.1:{port}'
                value=await devices(client,boundary,peer)
                assert value=={'devices':[{'device_id':'PHONE','ed25519':str(account.signing_key),'curve25519':str(account.identity_key)}],
                    'signature_checked':True,'owner_approval_required':True}
                assert token not in json.dumps(value)
                cases.append('actual_sdk_query_and_native_signature_return_only_public_keys_with_owner_approval_pending')
                state['keys']['PHONE']=deepcopy(signed);state['keys']['PHONE']['signatures'][peer]['ed25519:PHONE']='A'*86
                try:await devices(client,boundary,peer)
                except DeviceValidationError:pass
                else:raise AssertionError('invalid device signature was displayed as checked')
                cases.append('actual_native_device_signature_failure_is_refused')
                state['keys']={'PHONE':deepcopy(signed)};state['keys']['PHONE']['user_id']='@foreign:owner.invalid'
                try:await devices(client,boundary,peer)
                except DeviceValidationError:pass
                else:raise AssertionError('foreign device account accepted')
                cases.append('signed_device_user_must_match_exact_owner_query')
                state['keys']={'*':account.get_device_keys(UserID(peer),DeviceID('*')).serialize()}
                try:await devices(client,boundary,peer)
                except ValueError:pass
                else:raise AssertionError('wildcard device could be proposed for approval')
                cases.append('signed_device_wildcard_is_not_an_owner_identity')
                state['keys']={'PHONE':signed}
                for user,device,label in [('@foreign:owner.invalid','HAOS','foreign-account'),(bot,'FOREIGN','foreign-device'),(bot,None,'missing-device')]:
                    state['user'],state['device']=user,device;before=len(state['calls'])
                    try:await devices(client,boundary,peer)
                    except PermissionError:pass
                    else:raise AssertionError('unconfirmed account queried public devices')
                    assert len(state['calls'])==before+1
                    cases.append('actual_whoami_'+label+'_cannot_authorize_query')
                state['user'],state['device']=bot,'HAOS'
                for code in [401,429]:
                    state['status']=code;before=len(state['calls'])
                    try:await devices(client,boundary,peer)
                    except MatrixRequestError as error:
                        assert token not in str(error)
                        if code==429:assert error.retry_after==19
                    else:raise AssertionError('account refusal bypassed')
                    assert len(state['calls'])==before+1;cases.append('single_safe_account_refusal_'+str(code))
                state['status']=200;state['failures']={'owner.invalid':{'status':503,'message':token}}
                try:await devices(client,boundary,peer)
                except PermissionError as error:assert token not in str(error)
                else:raise AssertionError('partial failed device query became an approval candidate')
                cases.append('partial_federation_failure_cannot_become_complete_device_discovery')
        finally:await runner.cleanup()
    asyncio.run(exercise())
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,'live_account_accepted':False,
        'physical_device_approval_accepted':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    print(output,end='')


if __name__=='__main__':main()
