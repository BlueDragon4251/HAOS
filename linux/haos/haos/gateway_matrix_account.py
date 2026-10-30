"""Owner-requested signed public-device discovery in the isolated gateway UID."""
import asyncio
import json
import os
import pwd
import resource
import sys

from .gateway_matrix_http import HTTPBoundary
from .gateway_matrix_policy import opaque,public_key
from .gateway_matrix_profile import credentials


async def devices(client,boundary,peer):
    from mautrix.crypto.device_lists import DeviceListMachine
    from mautrix.types import UserID
    if not opaque(peer,'@') or ':' not in peer:raise ValueError('exact Matrix sender account required')
    boundary.bind(client);boundary.confirm(client,await client.whoami())
    response=await client.query_keys({UserID(peer):[]})
    if response.failures or set(response.device_keys)!={peer}:raise PermissionError('Matrix device query is incomplete')
    values=response.device_keys[UserID(peer)]
    if len(values)>256:raise ValueError('Matrix public device list exceeds owner bound')
    result=[]
    for device,key in sorted(values.items()):
        identity=await DeviceListMachine._validate_device(UserID(peer),device,key)
        row={'device_id':str(device),'ed25519':str(identity.signing_key),'curve25519':str(identity.identity_key)}
        if not opaque(row['device_id']) or row['device_id']=='*' or not public_key(row['ed25519']) or not public_key(row['curve25519']):
            raise ValueError('Matrix device identity is not an exact supported fingerprint')
        result.append(row)
    # Native self-signature verification is not owner/physical-device approval.
    return {'devices':result,'signature_checked':True,'owner_approval_required':True}


async def discover(value,peer):
    from aiohttp import ClientSession
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.types import UserID,DeviceID
    value=credentials(value)
    async with ClientSession(trust_env=False) as session:
        client=Client(mxid=UserID(value['user_id']),device_id=DeviceID(value['device_id']),
            api=HTTPAPI(base_url=value['homeserver'],token=value['token'],client_session=session))
        boundary=HTTPBoundary(value['homeserver'],value['user_id'],value['device_id'])
        return await devices(client,boundary,peer)


def main():
    if os.geteuid()==0:raise PermissionError('Matrix account helper may not retain root')
    account=pwd.getpwnam('haos-gateway')
    if os.geteuid()!=account.pw_uid:raise PermissionError('Matrix account helper requires the private gateway UID')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    os.environ['HERMES_SAFE_MODE']='1'
    raw=sys.stdin.buffer.read(32769)
    if len(raw)>32768:raise ValueError('bounded owner Matrix request required')
    request=json.loads(raw)
    if set(request)!={'credentials','sender'}:raise ValueError('invalid owner Matrix device request')
    try:value=asyncio.run(asyncio.wait_for(discover(request['credentials'],request['sender']),60))
    except Exception:
        # Do not forward vendor bodies, exception strings or credentials to an
        # owner UI or subprocess log. No automatic grant or send is performed.
        value={'error':'Matrix-Geräteabfrage abgelehnt oder nicht erreichbar; Konto, Gerät, Token und TLS prüfen.'}
    sys.stdout.write(json.dumps(value)+'\n')


if __name__=='__main__':main()
