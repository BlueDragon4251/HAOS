#!/usr/bin/env python3
"""Actual pinned IRC profile, TLS handshake, kernel lease and durable reopen."""
import asyncio
import copy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos import gateway_irc_profile as profile
    from haos.gateway import GatewayPolicy
    from haos.gateway_irc_ingress import PreparedIRCPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope,maintain,delivery_metadata,build_adapter
    from haos.gateway_delivery import delivery_result
    from haos.gateway_irc_ingress import REQUIRED_CAPS
    from haos.gateway_irc_witness import DELIVERY_CAPS
    from haos.redaction import Redactor
    from haos.gateway import GatewayEngine,digest
    from haos.store import MissionStore
    from haos.gateway_raw_recovery import retry_irc_auth,unresolved
    cases=[]
    async def exercise(directory):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
        now=datetime.now(timezone.utc)
        ca_key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable IRC profile CA')])
        ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(ca_key,hashes.SHA256()))
        key=ec.generate_private_key(ec.SECP256R1());subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'irc.fixture.invalid')])
        cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('irc.fixture.invalid')]),critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(ca_key,hashes.SHA256()))
        ca_path=directory/'ca.pem';ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        cert_path=directory/'server.pem';cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path=directory/'server.key';key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_path.chmod(0o600)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert_path,key_path)
        original_ca=os.environ.get('SSL_CERT_FILE');os.environ['SSL_CERT_FILE']=str(ca_path)
        home=directory/'unrelated-home';home.mkdir(mode=0o700);marker=home/'config.yaml';marker.write_text('private unrelated owner state')
        os.environ['HERMES_HOME']=str(home)
        parent=directory/'profiles';parent.mkdir(mode=0o700)
        native=NativeInbox(directory/'native.db',Redactor());relay=RelayInbox(directory/'relay.db',Redactor())
        value={'server':'irc.fixture.invalid','port':6697,'nickname':'haos-bot','channel':'#haos'}
        config={'version':1,'connectors':[{'id':'irc','platform':'irc'}],'bindings':[{
            'id':'owner','connector':'irc','sender':'owner-account','chat':'#haos','scope':'irc.fixture.invalid:6697',
            'thread':'','identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
        policy=lambda:GatewayPolicy(config)
        state={'mode':'good','connections':0,'writers':set(),'tasks':set(),'message':0}
        accepted=[];fail=[False];adapters=[]
        async def server(reader,writer):
            state['connections']+=1;state['writers'].add(writer);state['tasks'].add(asyncio.current_task())
            mode=state['mode']
            async def put(text):writer.write(text.encode());await writer.drain()
            async def get():return (await asyncio.wait_for(reader.readuntil(b'\r\n'),3)).decode().strip()
            try:
                assert await get()=='CAP LS 302'
                nickline=await get()
                if nickline.startswith('PASS '):
                    assert nickline in {'PASS new-fixture-password','PASS second-fixture-password'};nickline=await get()
                assert nickline.startswith('NICK ');nick=nickline.split(' ',1)[1]
                assert (await get()).startswith('USER ')
                if mode=='hang':await reader.read();return
                if mode=='nickname_refused':await put(':server 433 '+nick+' :private vendor refusal text\r\n');await reader.read();return
                if mode=='auth_refused':await put(':server 464 '+nick+' :access refused\r\n');await reader.read();return
                if mode=='rate_limited':await put(':server 263 '+nick+' CAP :try later\r\n');await reader.read();return
                caps=' '.join(sorted(REQUIRED_CAPS if mode=='incoming_only' else REQUIRED_CAPS|DELIVERY_CAPS))
                await put(':server CAP '+nick+' LS :'+caps+'\r\n')
                assert await get()=='CAP REQ :'+caps
                await put(':server CAP '+nick+' ACK :'+caps+'\r\n')
                assert await get()=='CAP END'
                await put(':server 001 '+nick+' :welcome\r\n');assert await get()=='JOIN #haos'
                await put(':'+nick+'!bot@host JOIN :#haos\r\n')
                if mode in {'good','incoming_only'}:
                    state['message']+=1;stamp=datetime.now(timezone.utc).isoformat()
                    await put(f'@account=owner-account;time={stamp};msgid=profile_{state["message"]} :arbitrary-nick!user@host PRIVMSG #haos :{nick}: retained owner request\r\n')
                    if state.get('one_message'):state['mode']='idle'
                while True:
                    outgoing=await get();tags,core=outgoing.split(' ',1)
                    assert tags.startswith('@label=haos_') and core.startswith('PRIVMSG #haos :')
                    label=tags.split('=',1)[1];body=core.split(' :',1)[1]
                    state['sent']=state.get('sent',0)+1;stamp=datetime.now(timezone.utc).isoformat()
                    await put(f'@label={label};account=*;time={stamp};msgid=accepted_{state["sent"]} :{nick}!bot@server PRIVMSG #haos :{body}\r\n')
            except (ConnectionError,asyncio.IncompleteReadError,asyncio.TimeoutError):pass
            finally:
                writer.close()
                try:await writer.wait_closed()
                except OSError:pass
                state['writers'].discard(writer);state['tasks'].discard(asyncio.current_task())
        listener=await asyncio.start_server(server,'127.0.0.1',0,ssl=tls);port=listener.sockets[0].getsockname()[1]
        def build():
            adapter=build_adapter('irc',value,irc_context={'parent':parent,'connector':'irc','policy':policy,'inbox':native});adapters.append(adapter)
            boundary=adapter._haos_irc_transport;boundary._handshake_seconds=2
            async def open_local(host,remote_port,**kwargs):
                assert (host,remote_port)==('irc.fixture.invalid',6697)
                assert kwargs['ssl'].verify_mode==ssl.CERT_REQUIRED and kwargs['ssl'].check_hostname
                assert kwargs['server_hostname']=='irc.fixture.invalid'
                return await asyncio.open_connection('127.0.0.1',port,**kwargs)
            boundary._open=open_local;adapter._haos_irc_retry_steps=(.1,.1,.1,.1)
            def receive(event):
                source=adapter_envelope(event,'irc')
                if fail[0]:raise ConnectionError('disposable local relay failure')
                relay.admit(policy(),'irc',source);accepted.append(source);return True
            adapter.set_durable_message_handler(receive)
            return adapter
        async def until(predicate):
            async with asyncio.timeout(4):
                while not predicate():await asyncio.sleep(.01)
        try:
            try:build_adapter('irc',value)
            except ValueError:pass
            else:raise AssertionError('IRC shared factory bypassed its independent private profile')
            try:build_adapter('irc',value,irc_context={'parent':parent,'connector':'irc','policy':policy,'inbox':native,'plugin':'unapproved'})
            except ValueError:pass
            else:raise AssertionError('IRC factory admitted arbitrary caller extension')
            assert state['connections']==0
            cases.append('shared_factory_requires_exact_private_context_and_never_enables_unknown_plugin_hooks')
            adapter=build()
            assert adapter._haos_irc_profile!=home and marker.read_text()=='private unrelated owner state'
            assert adapter.server=='irc.fixture.invalid' and adapter.use_tls is True
            cases.append('actual_native_factory_uses_private_home_and_explicit_connection_identity')
            try:build()
            except PermissionError:pass
            else:raise AssertionError('duplicate IRC kernel lease accepted')
            assert state['connections']==0
            cases.append('actual_kernel_lease_refuses_second_active_identity_before_any_network')
            assert await adapter.connect();await until(lambda:len(accepted)==1)
            assert accepted[0]['sender']=='owner-account' and adapter.irc_status()['status']=='streaming'
            gap=adapter.irc_status()['gap_since'];assert gap>0
            cases.append('actual_profile_continuous_tls_native_account_input_and_local_relay')
            store=MissionStore(directory/'missions.db');engine=GatewayEngine(store)
            await engine.receive(policy(),'irc',accepted[0],None)
            await adapter.disconnect()
            for _ in range(8):
                assert engine.next_delivery(policy(),time.time()+3600,ready_connectors=['irc'] if adapter.is_connected else []) is None
            assert tuple(store.db.execute('SELECT state,attempt FROM gateway_outbox').fetchone())==('pending',0)
            store.close();store=MissionStore(directory/'missions.db');engine=GatewayEngine(store)
            assert await adapter.connect()
            delivery=engine.next_delivery(policy(),ready_connectors=['irc'] if adapter.is_connected else [])
            assert delivery['attempt']==1 and delivery['connector']=='irc'
            receipt=await adapter.send(delivery['chat'],delivery['content'],reply_to=delivery['reply_to'],metadata=delivery_metadata(delivery,'irc'))
            assert delivery_result(receipt)['status']=='delivered' and receipt.raw_response['recipient_receipt_verified'] is False
            engine.acknowledge(policy(),delivery['id'],{**delivery_result(receipt),'attempt':delivery['attempt']})
            assert tuple(store.db.execute('SELECT state,attempt FROM gateway_outbox').fetchone())==('delivered',1)
            assert state['sent']>0
            cases.append('actual_registered_private_factory_mission_outbox_native_send_correlated_echo_and_durable_ack')
            store.close()
            cases.append('actual_tls_profile_readiness_preserves_reopened_mission_outbox_offline_and_first_online_attempt')
            before_connections=state['connections'];before_accepted=len(accepted)
            await adapter._haos_irc_transport.disconnect()
            await until(lambda:state['connections']>before_connections and len(accepted)>before_accepted)
            assert adapter.irc_status()['gap_since']==gap
            cases.append('actual_eof_reconnect_preserves_explicit_unrecoverable_remote_gap')
            await asyncio.gather(adapter.close_profile(),adapter.close_profile())
            assert not adapter.is_connected and adapter._haos_irc_worker is None and adapter._haos_irc_replay is None
            cases.append('concurrent_close_joins_workers_and_releases_kernel_lease_once')
            state['mode']='nickname_refused';adapter=build()
            connecting=asyncio.create_task(adapter.connect())
            await until(lambda:adapter.irc_status()['last_error']=='nickname-in-use')
            await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            assert adapter.irc_status()['last_error']=='nickname-in-use'
            from haos.gateway_raw_recovery import unresolved
            metadata=unresolved(native)
            assert any(item.get('last_error')=='nickname-in-use' for item in metadata['transport'])
            assert 'private vendor refusal text' not in json.dumps(metadata)
            cases.append('actual_tls_specific_diagnostic_survives_profile_close_and_private_owner_inspection_without_vendor_text')
            state['mode']='auth_refused';adapter=build();before=state['connections']
            assert not await adapter.connect();assert adapter.irc_status()['status']=='authentication-refused'
            assert state['connections']==before+1
            assert not await adapter.connect() and state['connections']==before+1
            await adapter.close_profile();native.close();native=NativeInbox(directory/'native.db',Redactor())
            adapter=build();assert not await adapter.connect() and state['connections']==before+1
            cases.append('real_server_authentication_refusal_is_sticky_across_connect_profile_and_actual_database_reopen')
            await adapter.close_profile();config['bindings'][0].update(generation='b'*64,since=int(time.time()*1000))
            value['nickname']='other-bot';adapter=build();assert not await adapter.connect() and state['connections']==before+1
            cases.append('new_owner_epoch_and_bot_nickname_cannot_bypass_same_account_authentication_refusal')
            await adapter.close_profile()
            before=state['connections'];metadata=unresolved(native)
            assert metadata['transport'] and all(x['unseen_remote_history_recovered'] is False for x in metadata['transport'])
            assert 'new-fixture-password' not in json.dumps(metadata)
            result=retry_irc_auth(native,policy(),{'connector':'irc','owner_uid':1000,'note_sha256':'a'*64})
            assert result['authentication_blocks_cleared']>=1 and result['network_requested'] is False and state['connections']==before
            assert native.db.execute('SELECT owner_uid FROM irc_owner_events').fetchone()[0]==1000
            state['mode']='good';adapter=build();assert await adapter.connect()
            await until(lambda:state['connections']>before)
            assert adapter.irc_status()['gap_since']>0
            await adapter.close_profile();state['mode']='auth_refused';adapter=build();assert not await adapter.connect()
            await adapter.close_profile()
            cases.append('prepared_audited_owner_recheck_is_offline_and_fresh_profile_performs_real_next_account_authentication')
            # Explicit credential rotation creates a new account scope without
            # clearing or deleting the previous refusal record.
            value['server_password']='new-fixture-password';state['mode']='good'
            adapter=build();before=len(accepted);assert await adapter.connect()
            await until(lambda:len(accepted)>before)
            assert native.db.execute("SELECT COUNT(*) FROM irc_profile_status WHERE status='authentication-refused'").fetchone()[0]>=1
            cases.append('explicit_credential_rotation_permits_new_real_authentication_and_preserves_old_refusal_rows')
            await adapter.close_profile();state['mode']='rate_limited';adapter=build()
            connecting=asyncio.create_task(adapter.connect())
            await until(lambda:adapter.irc_status()['status']=='rate-limited')
            deadline=adapter.irc_status()['next_attempt'];assert deadline>time.time()+58
            before=state['connections'];await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            native.close();native=NativeInbox(directory/'native.db',Redactor());adapter=build()
            connecting=asyncio.create_task(adapter.connect());await asyncio.sleep(.1)
            assert state['connections']==before and abs(adapter.irc_status()['next_attempt']-deadline)<.02
            await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            cases.append('actual_server_throttle_deadline_survives_cancel_close_and_database_reopen_without_early_request')
            config['bindings'][0].update(generation='c'*64,since=int(time.time()*1000));value['nickname']='third-bot'
            adapter=build();connecting=asyncio.create_task(adapter.connect());await asyncio.sleep(.1)
            assert state['connections']==before and abs(adapter.irc_status()['next_attempt']-deadline)<.02
            await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            cases.append('new_owner_epoch_and_bot_nickname_cannot_bypass_same_account_throttle')
            value['server_password']='second-fixture-password';state['mode']='good';state['one_message']=True;fail[0]=True
            adapter=build();connecting=asyncio.create_task(adapter.connect())
            await until(lambda:native.db.execute("SELECT COUNT(*) FROM native_inbox WHERE state='pending'").fetchone()[0]==1)
            retained=native.db.execute("SELECT id FROM native_inbox WHERE state='pending'").fetchone()[0]
            await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            native.close();native=NativeInbox(directory/'native.db',Redactor());fail[0]=False;state['mode']='idle'
            before=len(accepted);messages=state['message'];adapter=build();assert await adapter.connect()
            await until(lambda:len(accepted)==before+1)
            assert state['message']==messages and native.db.execute('SELECT state FROM native_inbox WHERE id=?',(retained,)).fetchone()[0]=='committed'
            assert native.db.execute('SELECT MAX(next_attempt) FROM irc_profile_status').fetchone()[0]>=deadline-.02
            cases.append('independent_local_replay_reopens_real_failed_admission_while_live_tls_has_no_new_message')
            stop=asyncio.Event();await adapter.close_profile();adapter=build()
            supervising=asyncio.create_task(maintain(adapter,stop));await until(lambda:adapter.is_connected)
            stop.set();await asyncio.wait_for(supervising,3)
            assert not adapter.is_connected and adapter._haos_irc_worker is None and adapter._haos_irc_replay is None
            await adapter.close_profile();cases.append('actual_shared_service_supervisor_stop_joins_private_profile_workers')
            adapter=build();assert await adapter.connect()
            config['bindings'][0].update(generation='d'*64,since=int(time.time()*1000))
            await until(lambda:adapter.irc_status()['status']=='revoked')
            assert not adapter.is_connected and adapter._haos_irc_transport.writer is None
            await adapter.close_profile();cases.append('owner_generation_change_revokes_running_idle_tls_profile_without_inheritance')
            state['mode']='hang';adapter=build();before=state['connections'];connecting=asyncio.create_task(adapter.connect())
            await until(lambda:state['connections']>before)
            await adapter.close_profile();await asyncio.gather(connecting,return_exceptions=True)
            assert connecting.done() and adapter._haos_irc_worker is None and adapter._haos_irc_transport.writer is None
            replacement=build();await replacement.close_profile()
            cases.append('close_during_real_tls_handshake_cancels_connect_and_releases_kernel_lease')
            state['mode']='idle';adapter=build();assert await adapter.connect()
            before_sent=state.get('sent',0);binding=config['bindings'][0];outbox=digest(['closing',state['connections']])
            metadata={'haos_scope':binding['scope'],'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},
                'haos_delivery_id':outbox,'haos_delivery_attempt':1,'notify':True}
            sending=asyncio.create_task(adapter.send('#haos','🦊'*300,metadata=metadata))
            await until(lambda:state.get('sent',0)>before_sent)
            await adapter.close_profile();await asyncio.gather(sending,return_exceptions=True)
            assert sending.done() and adapter._haos_irc_publisher.closed and not adapter._haos_irc_publisher.active
            assert native.db.execute('SELECT state FROM irc_delivery_intents WHERE delivery_id=?',(outbox,)).fetchone()[0]=='uncertain'
            assert state['sent']==before_sent+1 and adapter._haos_irc_transport.writer is None
            cases.append('private_profile_close_joins_actual_active_native_send_and_preserves_partial_intent_without_extra_chunk')
            config['bindings'][0].update(capabilities=['create'],generation='e'*64,since=int(time.time()*1000))
            state['mode']='incoming_only';state['one_message']=False;adapter=build();before=len(accepted)
            assert adapter._haos_irc_publisher is None and adapter._haos_irc_transport.required==REQUIRED_CAPS
            assert await adapter.connect();await until(lambda:len(accepted)>before)
            try:await adapter.send('#haos','unapproved reply',metadata={})
            except PermissionError:pass
            else:raise AssertionError('creation-only IRC profile gained a sender')
            await adapter.close_profile();cases.append('creation_only_profile_receives_with_original_caps_and_never_gains_outbound_authority')
        finally:
            for adapter in adapters:await adapter.close_profile()
            for writer in list(state['writers']):writer.close()
            listener.close();await listener.wait_closed()
            if state['tasks']:await asyncio.gather(*list(state['tasks']),return_exceptions=True)
            native.close();relay.close()
            if original_ca is None:os.environ.pop('SSL_CERT_FILE',None)
            else:os.environ['SSL_CERT_FILE']=original_ca
    with tempfile.TemporaryDirectory(prefix='haos-irc-profile-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_native_profile_tls_kernel_lease_and_sqlite':True,
        'fixture_only_loopback_destination_ca_and_short_reconnect_delay':True,'public_gateway_enabled':True,
        'unseen_remote_events_recovered':False,'external_server_account_delivery_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
