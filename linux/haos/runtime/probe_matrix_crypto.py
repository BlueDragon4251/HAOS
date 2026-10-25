#!/usr/bin/env python3
"""Real pinned mautrix/libolm + native Hermes crypto state and persistent SQLite.

Local self-room crypto contract only: no remote authentication, key sharing,
device verification or HAOS Matrix authorization is implied.
"""
import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import ClientSession
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.crypto import OlmMachine
    from mautrix.crypto.store.asyncpg import PgCryptoStore
    from mautrix.errors import DecryptionError,DuplicateMessageIndex,EncryptionError
    from mautrix.types import DeviceID,Event,EventType,RoomID,UserID,TrustState,RoomEncryptionStateEventContent,EncryptionAlgorithm
    from mautrix.util.async_db import Database
    from plugins.platforms.matrix.adapter import _CryptoStateStore,_check_e2ee_deps
    manifest=json.loads((root/'runtime/source.json').read_text())
    expected=manifest['gateway_versions']
    installed={name:version(name) for name in expected}
    assert installed==expected and _check_e2ee_deps()
    cases=['actual_pinned_native_e2ee_dependency_imports']
    async def exercise(directory):
        path=directory/'crypto.db';room=RoomID('!fixture:owner.invalid')
        user=UserID('@haos:owner.invalid');device=DeviceID('HAOS_LOCAL_FIXTURE')
        key='disposable-local-pickle-key';body='Private local encryption fixture 漢字'
        async def open_store(pickle_key=key,account_id=str(user)):
            db=Database.create('sqlite:///'+str(path),upgrade_table=PgCryptoStore.upgrade_table)
            await db.start();store=PgCryptoStore(account_id=account_id,pickle_key=pickle_key,db=db)
            await store.open();return db,store
        async def machine(store,session):
            # This real API client is never asked to make an HTTP request in
            # a self-room fixture with no remote recipients.
            api=HTTPAPI(base_url='http://127.0.0.1:1',token='disposable-fixture',client_session=session)
            state=MemoryStateStore()
            await state.set_encryption_info(room,RoomEncryptionStateEventContent(algorithm=EncryptionAlgorithm.MEGOLM_V1))
            client=Client(mxid=user,device_id=device,api=api,state_store=state)
            crypto=OlmMachine(client,store,_CryptoStateStore(state,{room},client))
            await crypto.load();return crypto
        def event(content,identity='$local-fixture',target=room):
            return Event.deserialize({'type':'m.room.encrypted','room_id':str(target),'sender':str(user),
                'event_id':identity,'origin_server_ts':1792800000000,'content':content.serialize()})
        db,store=await open_store()
        try:
            async with ClientSession(trust_env=False) as session:
                crypto=await machine(store,session)
                identity=crypto.account.identity_key;signing=crypto.account.signing_key
                await store.put_device_id(device)
                try:await crypto.encrypt_megolm_event(room,EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':body})
                except EncryptionError:pass
                else:raise AssertionError('unshared room must not encrypt')
                cases.append('unshared_session_cannot_encrypt')
                # Actual SDK session creation for a local self-room, with no
                # fabricated shared flag and no remote recipient/device.
                await crypto.share_group_session(room,[])
                encrypted=await crypto.encrypt_megolm_event(room,EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':body,
                    'm.relates_to':{'rel_type':'m.thread','event_id':'$approved-root','is_falling_back':False}})
                assert body not in json.dumps(encrypted.serialize())
                decoded=await crypto.decrypt_megolm_event(event(encrypted))
                assert decoded.content.body==body and decoded.content.relates_to.event_id=='$approved-root'
                assert decoded['mautrix']['was_encrypted'] and decoded['mautrix']['trust_state']==TrustState.VERIFIED
                cases.append('actual_sdk_self_room_megolm_roundtrip_preserves_unicode_and_thread')
                assert (await crypto.decrypt_megolm_event(event(encrypted))).content.body==body
                cases.append('same_event_replay_remains_same_native_identity')
                try:await crypto.decrypt_megolm_event(event(encrypted,'$forged-replay'))
                except DuplicateMessageIndex:pass
                else:raise AssertionError('same index under another event identity must fail')
                cases.append('different_event_id_cannot_reuse_message_index')
                data=encrypted.serialize();cipher=data['ciphertext']
                # Alter actual authenticated ciphertext without changing its encoding.
                data['ciphertext']=('A' if cipher[0]!='A' else 'B')+cipher[1:]
                try:await crypto.decrypt_megolm_event(Event.deserialize({'type':'m.room.encrypted','room_id':str(room),
                    'sender':str(user),'event_id':'$tampered','origin_server_ts':1792800000001,'content':data}))
                except DecryptionError:pass
                else:raise AssertionError('tampered ciphertext decrypted')
                cases.append('tampered_megolm_ciphertext_refused')
                try:await crypto.decrypt_megolm_event(event(encrypted,'$wrong-room',RoomID('!other:owner.invalid')))
                except DecryptionError:pass
                else:raise AssertionError('room identity was substituted')
                cases.append('other_room_cannot_reuse_private_session')
                await store.put_next_batch('local-sync-receipt')
                count=(await store.get_outbound_group_session(room)).message_count
                await db.stop();db,store=await open_store()
                reopened=await machine(store,session)
                assert reopened.account.identity_key==identity and reopened.account.signing_key==signing
                assert await store.get_device_id()==device and await store.get_next_batch()=='local-sync-receipt'
                assert (await store.get_outbound_group_session(room)).message_count==count
                cases.append('actual_sqlite_reopen_preserves_identity_device_sync_and_ratchet')
                next_encrypted=await reopened.encrypt_megolm_event(room,EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':body+' second'})
                assert next_encrypted.ciphertext!=encrypted.ciphertext
                assert (await reopened.decrypt_megolm_event(event(next_encrypted,'$next'))).content.body==body+' second'
                cases.append('reopened_native_session_advances_message_index')
                try:await reopened.decrypt_megolm_event(event(encrypted,'$replay-after-restart'))
                except DuplicateMessageIndex:pass
                else:raise AssertionError('restart lost replay identity')
                cases.append('replay_index_survives_database_reopen')
                # Wrong account/pickle material must not silently reset an owner store.
                wrong=PgCryptoStore(account_id=str(user),pickle_key='wrong-local-fixture-key',db=db)
                with sqlite3.connect(path) as observer:
                    before=observer.execute('SELECT * FROM crypto_account').fetchall()
                import olm
                try:await wrong.get_account()
                except olm.OlmAccountError:pass
                else:raise AssertionError('wrong private pickle key opened stored account')
                with sqlite3.connect(path) as observer:
                    assert observer.execute('SELECT * FROM crypto_account').fetchall()==before
                cases.append('wrong_pickle_key_fails_without_deleting_private_account')
                other=PgCryptoStore(account_id='@other:owner.invalid',pickle_key=key,db=db)
                assert await other.get_account() is None
                assert (await store.get_account()).identity_key==identity
                cases.append('distinct_account_namespace_does_not_inherit_identity')
                for file in directory.iterdir():
                    if file.is_file():
                        assert stat.S_IMODE(file.stat().st_mode)&0o077==0
                        assert body.encode() not in file.read_bytes()
                cases.append('actual_crypto_files_private_and_no_plaintext_message_persisted')
        finally:await db.stop()
    old=os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    finally:os.umask(old)
    output=json.dumps({'passed':len(cases),'cases':cases,'versions':installed,'external_connections':False,
        'remote_key_share_or_device_verification':False,'haos_matrix_gateway_enabled':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
