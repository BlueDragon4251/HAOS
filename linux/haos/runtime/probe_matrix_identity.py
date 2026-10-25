#!/usr/bin/env python3
"""Actual native Matrix auth/crypto setup, real local HTTP and retained private SQLite."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import web,ClientSession
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.types import UserID,DeviceID,RoomID,EventType,TrustState
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter
    from haos.gateway_matrix import protect_crypto,private_store
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'home')
        user='@haos:owner.invalid';device='HAOS_LOCAL_FIXTURE';token='disposable-private-token'
        state={'user':user,'device':device,'keys':None,'methods':[],'auth_status':200}
        async def api(request):
            state['methods'].append(request.method+' '+request.path)
            assert request.headers['Authorization']=='Bearer '+token
            if request.path.endswith('/account/whoami'):
                if state['auth_status']!=200:return web.json_response({'errcode':'M_UNKNOWN_TOKEN','error':'fixture refusal'},status=state['auth_status'])
                return web.json_response({'user_id':state['user'],'device_id':state['device']})
            if request.path.endswith('/keys/query'):
                body=await request.json();assert body['device_keys']=={user:[state['device']]}
                return web.json_response({'device_keys':{user:{state['device']:state['keys']}} if state['keys'] else {}})
            if request.path.endswith('/keys/upload'):
                body=await request.json()
                if body.get('device_keys'):state['keys']=body['device_keys']
                return web.json_response({'one_time_key_counts':{'signed_curve25519':50}})
            raise AssertionError('unapproved Matrix side effect '+request.method+' '+request.path)
        app=web.Application();app.router.add_route('*','/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        def adapter(profile,expected_device=device):
            native=MatrixAdapter(PlatformConfig(enabled=True,token=token,extra={
                'homeserver':f'http://127.0.0.1:{port}','user_id':user,'device_id':expected_device,'e2ee_mode':'required'}))
            return protect_crypto(native,directory/profile)
        async def client(session,dev=device):
            return Client(mxid=UserID(user),device_id=DeviceID(dev),
                api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',token=token,client_session=session),state_store=MemoryStateStore())
        def snapshot(path):
            with sqlite3.connect(path) as db:
                return [(name,db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()) for (name,) in
                    db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'crypto_%' ORDER BY name").fetchall()]
        first=adapter('profile')
        try:
            async with ClientSession(trust_env=False) as session:
                actual=await client(session)
                assert await first._connect_authenticate(actual,actual.api)
                cases.append('actual_native_whoami_matches_explicit_user_and_device')
                assert await first._connect_setup_e2ee(actual,actual.api,actual.state_store)
                assert actual.crypto is not None and state['keys'] is not None
                assert actual.crypto.share_keys_min_trust==TrustState.VERIFIED and actual.crypto.send_keys_min_trust==TrustState.VERIFIED
                cases.append('actual_sdk_initial_key_publication_requires_matching_server_keys')
                assert not await actual.crypto.allow_key_share(None,None)
                assert first._haos_cross_signing_verified is False
                assert not any(item.startswith('DELETE ') for item in state['methods'])
                cases.append('unverified_device_and_unsolicited_key_requests_not_enabled')
                room=RoomID('!self:owner.invalid')
                await actual.crypto.share_group_session(room,[])
                await actual.crypto.encrypt_megolm_event(room,EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':'local retained crypto fixture'})
            await first.disconnect()
            path=directory/'profile/crypto.db';before=snapshot(path)
            same=adapter('profile')
            try:
                async with ClientSession(trust_env=False) as session:
                    actual=await client(session)
                    assert await same._connect_authenticate(actual,actual.api)
                    assert await same._connect_setup_e2ee(actual,actual.api,actual.state_store)
                    assert (await actual.crypto.crypto_store.get_outbound_group_session(room)).message_count==1
                    cases.append('same_private_identity_reopens_actual_existing_crypto_store')
            finally:await same.disconnect()
            baseline=snapshot(path)
            state['device']='HAOS_CHANGED_DEVICE'
            changed=adapter('profile',state['device'])
            try:
                async with ClientSession(trust_env=False) as session:
                    actual=await client(session,state['device'])
                    assert await changed._connect_authenticate(actual,actual.api)
                    assert not await changed._connect_setup_e2ee(actual,actual.api,actual.state_store)
            finally:await changed.disconnect()
            assert snapshot(path)==baseline
            cases.append('actual_device_change_refused_without_deleting_accounts_or_sessions')
            state['device']=device
            old_keys=json.loads(json.dumps(state['keys']));state['keys']['keys']['ed25519:'+device]='mismatched-fixture-signing-key'
            mismatch=adapter('profile')
            uploads=state['methods'].count('POST /_matrix/client/v3/keys/upload')
            try:
                async with ClientSession(trust_env=False) as session:
                    actual=await client(session)
                    assert await mismatch._connect_authenticate(actual,actual.api)
                    assert not await mismatch._connect_setup_e2ee(actual,actual.api,actual.state_store)
            finally:await mismatch.disconnect()
            assert snapshot(path)==baseline and not any(item.startswith('DELETE ') for item in state['methods'])
            assert state['methods'].count('POST /_matrix/client/v3/keys/upload')==uploads
            cases.append('mismatched_server_keys_never_trigger_device_delete_or_replacement')
            state['keys']=json.loads(json.dumps(old_keys))
            state['keys']['keys']['curve25519:'+device]='mismatched-fixture-curve-key'
            curve=adapter('profile')
            try:
                async with ClientSession(trust_env=False) as session:
                    actual=await client(session)
                    assert await curve._connect_authenticate(actual,actual.api)
                    assert not await curve._connect_setup_e2ee(actual,actual.api,actual.state_store)
            finally:await curve.disconnect()
            assert snapshot(path)==baseline and not any(item.startswith('DELETE ') for item in state['methods'])
            cases.append('curve_identity_mismatch_also_refused_without_destructive_recovery')
            state['keys']=old_keys
            # A real legacy-derived pickle key is intentionally not rewritten by login.
            from mautrix.crypto import OlmAccount
            from mautrix.crypto.store.asyncpg import PgCryptoStore
            from mautrix.util.async_db import Database
            legacy_path=private_store(directory/'legacy-key')/'crypto.db'
            db=Database.create('sqlite:///'+str(legacy_path),upgrade_table=PgCryptoStore.upgrade_table)
            await db.start()
            try:
                legacy_store=PgCryptoStore(account_id=user,pickle_key=user+':default',db=db)
                await legacy_store.put_account(OlmAccount());await legacy_store.put_device_id(device)
            finally:await db.stop()
            legacy_before=snapshot(legacy_path);keyed=adapter('legacy-key')
            try:
                async with ClientSession(trust_env=False) as session:
                    actual=await client(session)
                    assert await keyed._connect_authenticate(actual,actual.api)
                    assert not await keyed._connect_setup_e2ee(actual,actual.api,actual.state_store)
            finally:await keyed.disconnect()
            assert snapshot(legacy_path)==legacy_before
            cases.append('legacy_pickle_key_never_silently_repicks_or_replaces_owner_material')
            for name,alter in [('wrong_user',{'user':'@other:owner.invalid'}),('wrong_device',{'device':'OTHER'}),('missing_device',{'device':None}),('revoked_token',{'auth_status':401})]:
                saved={key:state[key] for key in alter};state.update(alter)
                item=adapter(name)
                try:
                    async with ClientSession(trust_env=False) as session:
                        actual=await client(session)
                        assert not await item._connect_authenticate(actual,actual.api)
                finally:await item.disconnect();state.update(saved)
                assert not (directory/name/'crypto.db').exists()
                cases.append('actual_http_'+name+'_refused_before_crypto_setup')
            legacy=private_store(directory/'legacy');canary=legacy/'crypto_store.pickle';canary.write_bytes(b'opaque-owner-recovery-canary')
            try:private_store(legacy)
            except PermissionError:pass
            else:raise AssertionError('legacy recovery file was automatically accepted')
            assert canary.read_bytes()==b'opaque-owner-recovery-canary'
            cases.append('real_legacy_recovery_file_preserved_without_deserializing_or_deleting')
            unsafe=directory/'unsafe';unsafe.symlink_to(directory/'profile',target_is_directory=True)
            try:private_store(unsafe)
            except PermissionError:pass
            else:raise AssertionError('symlink profile accepted')
            cases.append('real_profile_symlink_refused_before_database_open')
            assert snapshot(path)==baseline
        finally:
            await first.disconnect();await runner.cleanup()
    old=os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    finally:os.umask(old)
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'haos_matrix_gateway_enabled':False,'real_account_device_verification':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
