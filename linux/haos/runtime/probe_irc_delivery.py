#!/usr/bin/env python3
"""Actual pinned native IRC send and loopback TLS server acceptance witnesses."""
import asyncio
import base64
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import ssl
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest,GatewayEngine,GatewayPolicy
    from haos.gateway_irc_ingress import PreparedIRCPolicy,install as ingress,REQUIRED_CAPS
    from haos.gateway_irc_transport import install as transport
    from haos.gateway_irc_delivery import Publisher
    from haos.gateway_irc_witness import DELIVERY_CAPS
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from haos.gateway_delivery import delivery_result
    from haos.gateway_runtime import delivery_metadata,credential_redactor
    from haos.gateway_irc_recovery import outgoing
    from haos.gateway_recovery import reconcile
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from plugins.platforms.irc.adapter import IRCAdapter
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
        state={'mode':'direct','writes':[],'writers':set(),'tasks':set(),'held':asyncio.Event(),'release':asyncio.Event()}
        resources=[];counter=[0]
        async def server(reader,writer):
            mode=state['mode'];state['writers'].add(writer);state['tasks'].add(asyncio.current_task())
            async def put(text):writer.write(text.encode());await writer.drain()
            async def get():return (await asyncio.wait_for(reader.readuntil(b'\r\n'),3)).decode().rstrip('\r\n')
            try:
                assert await get()=='CAP LS 302';assert (await get()).startswith('NICK ');assert (await get()).startswith('USER ')
                available=REQUIRED_CAPS|DELIVERY_CAPS
                if mode.startswith('sasl_'):available=available|{'sasl'}
                if mode.startswith('no_cap_'):available=available-{mode[len('no_cap_'):]}
                caps=' '.join(sorted(available))
                await put(':server CAP haos-bot LS :'+caps+'\r\n');assert await get()=='CAP REQ :'+caps
                await put(':server CAP haos-bot ACK :'+caps+'\r\n')
                if mode.startswith('sasl_'):
                    assert await get()=='AUTHENTICATE PLAIN';await put('AUTHENTICATE +\r\n')
                    auth=await get();assert auth.startswith('AUTHENTICATE ')
                    assert base64.b64decode(auth.split(' ',1)[1],validate=True)==b'bot-account\0bot-account\0private-sasl-fixture'
                    await put(':server 900 haos-bot haos-bot!bot@server bot-account :authenticated\r\n:server 903 haos-bot :SASL complete\r\n')
                assert await get()=='CAP END'
                await put(':server 001 haos-bot :welcome\r\n');assert await get()=='JOIN #haos'
                await put(':haos-bot!bot@server JOIN :#haos\r\n')
                index=0
                while True:
                    raw=await get();tags,core=raw.split(' ',1)
                    assert tags.startswith('@label=haos_') and len(tags.split('=',1)[1])<=64
                    label=tags.split('=',1)[1];assert core.startswith('PRIVMSG #haos :') and len(core.encode())<=510
                    body=core.split(' :',1)[1];state['writes'].append(body);index+=1
                    if mode=='drop':return
                    if mode=='silent':continue
                    if mode=='ack':await put('@label='+label+' :server ACK\r\n');continue
                    stamp=datetime.now(timezone.utc).isoformat()
                    account=('unexpected-account' if mode=='sasl_account_mismatch' else 'bot-account') if mode.startswith('sasl_') else '*'
                    common='account='+account+';time='+stamp+';msgid=server_'+str(index)
                    if mode=='case_variants':prefix='HAOS-BOT!bot@server'
                    elif mode=='wrong_sender':prefix='imposter!bot@server'
                    else:prefix='haos-bot!bot@server'
                    target='#other' if mode=='wrong_channel' else '#HAOS' if mode=='case_variants' else '#haos'
                    echoed=body+' changed' if mode=='modified_body' else body
                    if mode=='sasl_secret_msgid':common='account=bot-account;time='+stamp+';msgid=private-sasl-fixture'
                    if mode=='missing_msgid':common='account=*;time='+stamp
                    if mode=='missing_account':common='time='+stamp+';msgid=server_'+str(index)
                    if mode=='naive_time':common='account=*;time=2026-10-26T12:00:00;msgid=server_'+str(index)
                    if mode.startswith('batch'):
                        batch='batch_'+str(index)
                        await put('@label='+label+' :'+('imposter!user@host' if mode=='batch_wrong_origin' else 'server')+' BATCH +'+batch+' '+('wrong-type' if mode=='batch_wrong_type' else 'labeled-response')+'\r\n')
                        echo='@batch='+batch+';'+common+' :'+prefix+' PRIVMSG '+target+' :'+echoed+'\r\n'
                        if mode!='batch_empty':await put(echo)
                        if mode=='batch_duplicate':await put(echo)
                        if mode=='batch_drop':return
                        if mode=='batch_held':state['held'].set();await state['release'].wait()
                        await put(':server BATCH -'+('wrong' if mode=='batch_wrong_end' else batch)+'\r\n')
                    else:
                        tag=('' if mode=='missing_label' else 'label='+label+';')+common
                        await put('@'+tag+' :'+prefix+' PRIVMSG '+target+' :'+echoed+'\r\n')
            except (asyncio.IncompleteReadError,asyncio.TimeoutError,ConnectionError):pass
            finally:
                writer.close()
                try:await writer.wait_closed()
                except OSError:pass
                state['writers'].discard(writer);state['tasks'].discard(asyncio.current_task())
        listener=await asyncio.start_server(server,'127.0.0.1',0,ssl=tls);port=listener.sockets[0].getsockname()[1]
        async def build(mode,resume=None,capabilities=None,connected=True):
            counter[0]+=1;state['mode']=mode;state['writes']=[];state['held'].clear();state['release'].clear()
            if resume is None:
                root=directory/str(counter[0]);root.mkdir(mode=0o700)
                config={'version':1,'connectors':[{'id':'irc','platform':'irc'}],'bindings':[{
                    'id':'owner','connector':'irc','sender':'owner-account','chat':'#haos','scope':'irc.fixture.invalid:6697',
                    'thread':'','identity':'owner','capabilities':capabilities or ['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
            else:root,config=resume
            policy=lambda:GatewayPolicy(config)
            native=NativeInbox(root/'native.db',Redactor())
            value={'server':'irc.fixture.invalid','port':6697,'nickname':'haos-bot','channel':'#haos'}
            if mode.startswith('sasl_'):value.update(sasl_username='bot-account',sasl_password='private-sasl-fixture')
            native.redactor=credential_redactor({'connectors':{'irc':value}},policy())
            if mode=='legacy_schema':
                native.db.execute('CREATE TABLE irc_delivery_intents(delivery_id TEXT,attempt INTEGER,connector TEXT,identity TEXT,binding_digest TEXT,content_digest TEXT,state TEXT,chunk_count INTEGER,receipts TEXT,updated_at REAL,PRIMARY KEY(delivery_id,attempt))')
                native.db.execute('INSERT INTO irc_delivery_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (digest('legacy_intent'),1,'irc','b'*64,'c'*64,'d'*64,'uncertain',1,'[]',123))
            adapter=ingress(durable_adapter(IRCAdapter(PlatformConfig(enabled=True,extra=value))))
            adapter._haos_native=SimpleNamespace(connector='irc',policy=policy,inbox=native)
            adapter.set_durable_message_handler(lambda _:(_ for _ in ()).throw(AssertionError('own echo became incoming mission')))
            boundary=transport(adapter,value);boundary._handshake_seconds=2
            publisher=Publisher(adapter);publisher._echo_seconds=2
            async def open_local(host,remote_port,**kwargs):
                assert (host,remote_port)==('irc.fixture.invalid',6697)
                assert kwargs['ssl'].verify_mode==ssl.CERT_REQUIRED and kwargs['ssl'].check_hostname is True
                return await asyncio.open_connection('127.0.0.1',port,**kwargs)
            boundary._open=open_local
            if connected:assert await boundary.connect()
            else:
                try:await boundary.connect()
                except ConnectionError:pass
                else:raise AssertionError('missing delivery capability accepted')
            async def idle():return None
            worker=asyncio.create_task(boundary.receive() if connected else idle());resources.append((publisher,boundary,worker,native))
            binding=config['bindings'][0]
            metadata={'haos_scope':binding['scope'],'haos_binding':{'binding_id':'owner','binding_digest':digest(binding)},
                'haos_delivery_id':digest([root.name,'reply']),'haos_delivery_attempt':1,'notify':True}
            return adapter,publisher,metadata,(root,config)
        async def shutdown(resource):
            publisher,boundary,worker,native=resource
            await publisher.close();await boundary.disconnect();worker.cancel();await asyncio.gather(worker,return_exceptions=True);native.close()
        async def until(predicate):
            async with asyncio.timeout(3):
                while not predicate():await asyncio.sleep(.01)
        try:
            adapter,publisher,metadata,resume=await build('direct')
            receipt=await adapter.send('#haos','**hello** owner',metadata=metadata)
            assert delivery_result(receipt)['status']=='delivered' and receipt.message_id.startswith('irc_echo_')
            assert receipt.raw_response['recipient_receipt_verified'] is False and state['writes']==['hello owner']
            assert publisher.db.execute('SELECT state FROM irc_delivery_intents').fetchone()[0]=='confirmed'
            cases.append('actual_pinned_native_send_uses_markdown_builder_and_verified_correlated_server_echo_not_local_millisecond_id')
            cached=await adapter.send('#haos','**hello** owner',metadata=metadata)
            assert cached.message_id==receipt.message_id and state['writes']==['hello owner']
            cases.append('same_confirmed_outbox_attempt_returns_durable_receipt_without_another_write')
            await shutdown(resources.pop());adapter,publisher,reopened,_=await build('direct',resume)
            assert reopened==metadata
            cached=await adapter.send('#haos','**hello** owner',metadata=metadata)
            assert cached.message_id==receipt.message_id and not state['writes']
            cases.append('actual_private_journal_reopen_preserves_confirmation_without_another_native_send')
            adapter,publisher,metadata,_=await build('batch_held')
            task=asyncio.create_task(adapter.send('#haos','held batch',metadata=metadata))
            await state['held'].wait();await asyncio.sleep(.03)
            assert not task.done() and publisher.db.execute('SELECT state FROM irc_delivery_intents').fetchone()[0]=='writing'
            state['release'].set();assert delivery_result(await task)['status']=='delivered'
            cases.append('real_tls_echo_inside_batch_does_not_confirm_before_withheld_batch_end')
            for mode in ['drop','silent','ack','wrong_sender','wrong_channel','modified_body','missing_msgid','missing_account',
                    'naive_time','missing_label','batch_empty','batch_wrong_type','batch_duplicate','batch_drop','batch_wrong_end','batch_wrong_origin','sasl_account_mismatch','sasl_secret_msgid']:
                adapter,publisher,metadata,_=await build(mode)
                receipt=await adapter.send('#haos','bounded owner reply',metadata=metadata)
                assert delivery_result(receipt)=={'status':'uncertain'},mode
                assert state['writes']==['bounded owner reply']
                assert publisher.db.execute('SELECT state FROM irc_delivery_intents').fetchone()[0]=='uncertain'
                if mode=='sasl_secret_msgid':assert 'private-sasl-fixture' not in '\n'.join(publisher.db.iterdump())
                cases.append('actual_tls_'+mode+'_cannot_fabricate_native_delivery_or_trigger_resend')
                if mode=='silent':
                    assert delivery_result(await adapter.send('#haos','bounded owner reply',metadata=metadata))=={'status':'uncertain'}
                    assert state['writes']==['bounded owner reply']
                    cases.append('same_uncertain_native_outbox_attempt_is_never_resent_while_connection_remains_live')
            adapter,publisher,metadata,_=await build('case_variants')
            receipt=await adapter.send('#haos','case-insensitive channel reply',metadata=metadata)
            assert receipt.success and state['writes']==['case-insensitive channel reply']
            cases.append('native_server_echo_accepts_standard_channel_and_own_nickname_case_variants_without_changing_owner_route')
            adapter,publisher,metadata,_=await build('sasl_good')
            receipt=await adapter.send('#haos','authenticated bot reply',metadata=metadata)
            assert receipt.success is True and state['writes']==['authenticated bot reply']
            cases.append('actual_tls_sasl_account_and_correlated_own_account_echo_are_required_together')
            adapter,publisher,metadata,_=await build('direct')
            invalid=[None,{},dict(metadata,unknown=True),dict(metadata,notify=False),dict(metadata,thread_id='unapproved'),
                dict(metadata,haos_scope='other.fixture.invalid:6697'),dict(metadata,haos_delivery_attempt=True),
                dict(metadata,haos_delivery_attempt=0),dict(metadata,haos_delivery_attempt=6),dict(metadata,haos_delivery_id='invented'),
                dict(metadata,haos_binding={'binding_id':'forged','binding_digest':'a'*64}),
                dict(metadata,haos_binding={'binding_id':'owner','binding_digest':'a'*64}),
                dict(metadata,haos_binding={**metadata['haos_binding'],'extra':True})]
            for item in invalid:
                try:await adapter.send('#haos','bounded reply',metadata=item)
                except PermissionError:pass
                else:raise AssertionError('unapproved native IRC outbox metadata admitted')
            assert not state['writes'] and publisher.db.execute('SELECT COUNT(*) FROM irc_delivery_intents').fetchone()[0]==0
            cases.append('missing_forged_or_extra_outbox_authority_and_invalid_attempts_never_dispatch')
            for chat,content in [('#other','bounded reply'),('#haos','x'*32001),('#haos','🦊'*8001),('#haos','\0injection'),('#haos','\x01DCC SEND unapproved\x01')]:
                try:await adapter.send(chat,content,metadata=metadata)
                except PermissionError:pass
                else:raise AssertionError('unbounded or redirected native IRC reply admitted')
            assert not state['writes']
            cases.append('redirected_targets_and_byte_bounded_or_control_injected_payloads_never_dispatch')
            adapter,publisher,metadata,_=await build('direct',capabilities=['create'])
            try:await adapter.send('#haos','read not approved',metadata=metadata)
            except PermissionError:pass
            else:raise AssertionError('IRC creation grant allowed private mission replies')
            assert not state['writes'];cases.append('current_exact_owner_route_without_read_permission_cannot_send')
            adapter,publisher,metadata,_=await build('silent')
            task=asyncio.create_task(adapter.send('#haos','cancelled reply',metadata=metadata))
            await until(lambda:len(state['writes'])==1);await publisher.close();await asyncio.gather(task,return_exceptions=True)
            assert task.done() and not publisher.active and publisher.db.execute('SELECT state FROM irc_delivery_intents').fetchone()[0]=='uncertain'
            assert state['writes']==['cancelled reply']
            cases.append('close_after_real_dispatch_cancels_joins_and_retains_uncertain_intent_without_resend')
            adapter,publisher,metadata,core_resume=await build('silent')
            config=core_resume[1];policy=GatewayPolicy(config);store=MissionStore(directory/'mission-outbox.db');engine=GatewayEngine(store)
            await engine.receive(policy,'irc',{'platform':'irc','sender':'owner-account','chat':'#haos','scope':'irc.fixture.invalid:6697',
                'thread':'','message_id':digest('original-owner-request'),'is_bot':False,'text':'local queued fixture mission'},None)
            delivery=engine.next_delivery(policy,ready_connectors=['irc']);metadata=delivery_metadata(delivery,'irc')
            receipt=await adapter.send(delivery['chat'],delivery['content'],reply_to=delivery['reply_to'],metadata=metadata)
            engine.acknowledge(policy,delivery['id'],{**delivery_result(receipt),'attempt':delivery['attempt']})
            assert engine.next_delivery(policy,ready_connectors=['irc']) is None and len(state['writes'])==1
            store.close();store=MissionStore(directory/'mission-outbox.db');engine=GatewayEngine(store)
            assert engine.next_delivery(policy,ready_connectors=['irc']) is None
            assert tuple(store.db.execute('SELECT state,attempt FROM gateway_outbox').fetchone())==('uncertain',1)
            await shutdown(resources.pop());adapter,publisher,_,_=await build('silent',core_resume)
            assert delivery_result(await adapter.send(delivery['chat'],delivery['content'],reply_to=delivery['reply_to'],metadata=metadata))=={'status':'uncertain'}
            assert not state['writes']
            cases.append('actual_uncertain_native_journal_reopen_cannot_repeat_the_same_mission_outbox_attempt')
            reconcile(store,policy,{'delivery_id':delivery['id'],'attempt':1,'decision':'retry','owner_uid':1000,
                'note_sha256':'a'*64,'receipt':None,'confirmed_not_delivered':True})
            retried=engine.next_delivery(policy,time.time()+1,ready_connectors=['irc'])
            assert retried['attempt']==2 and store.db.execute("SELECT COUNT(*) FROM events WHERE kind='owner.gateway-reconciled'").fetchone()[0]==1
            await shutdown(resources.pop());adapter,publisher,_,_=await build('direct',core_resume)
            receipt=await adapter.send(retried['chat'],retried['content'],reply_to=retried['reply_to'],metadata=delivery_metadata(retried,'irc'))
            assert delivery_result(receipt)['status']=='delivered' and state['writes']
            engine.acknowledge(policy,retried['id'],{**delivery_result(receipt),'attempt':retried['attempt']})
            assert tuple(store.db.execute('SELECT state,attempt FROM gateway_outbox').fetchone())==('delivered',2)
            store.close();cases.append('real_mission_outbox_uncertainty_survives_reopen_and_requires_audited_owner_decision_before_new_actual_native_attempt')
            for capability in sorted(DELIVERY_CAPS):
                adapter,publisher,metadata,_=await build('no_cap_'+capability,connected=False)
                assert not adapter.is_connected and not state['writes'] and publisher.db.execute('SELECT COUNT(*) FROM irc_delivery_intents').fetchone()[0]==0
                cases.append('actual_tls_missing_'+capability+'_cannot_enable_native_delivery')
            adapter,publisher,metadata,_=await build('legacy_schema')
            receipt=await adapter.send('#haos','additive migration reply',metadata=metadata)
            assert receipt.success is True
            assert tuple(publisher.db.execute('SELECT state,updated_at,receipt FROM irc_delivery_intents WHERE delivery_id=?',(digest('legacy_intent'),)).fetchone())==('uncertain',123,'')
            inspection=outgoing(adapter._haos_native.inbox)
            current=next(row for row in inspection if row['delivery_id']==metadata['haos_delivery_id'])
            assert current['server_echo_receipt']==receipt.message_id and current['recipient_receipt_verified'] is False
            assert 'server_1' not in json.dumps(inspection) and 'additive migration reply' not in json.dumps(inspection)
            cases.append('actual_native_send_after_additive_legacy_schema_migration_preserves_old_intent_and_exposes_only_safe_owner_proof')
            adapter,publisher,metadata,_=await build('direct')
            publisher.db.execute("CREATE TRIGGER fixture_intent_fault BEFORE INSERT ON irc_delivery_intents BEGIN SELECT RAISE(ABORT,'disposable intent storage unavailable'); END")
            try:await adapter.send('#haos','unrecorded reply',metadata=metadata)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('native IRC sent without durable intent storage')
            assert not state['writes']
            cases.append('actual_sqlite_intent_failure_prevents_every_native_socket_side_effect')
            adapter,publisher,metadata,_=await build('direct')
            publisher.db.execute("CREATE TRIGGER fixture_confirmation_fault BEFORE UPDATE ON irc_delivery_intents WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT,'disposable confirmation storage unavailable'); END")
            receipt=await adapter.send('#haos','confirmation cannot commit',metadata=metadata)
            assert delivery_result(receipt)=={'status':'uncertain'} and state['writes']==['confirmation cannot commit']
            assert publisher.db.execute('SELECT state FROM irc_delivery_intents').fetchone()[0]=='uncertain'
            cases.append('actual_sqlite_confirmation_failure_never_fabricates_success_or_resends_accepted_message')
            adapter,publisher,metadata,_=await build('direct')
            receipt=await adapter.send('#haos','🦊'*300,metadata=metadata)
            assert receipt.success and len(state['writes'])>1 and ''.join(state['writes'])=='🦊'*300
            assert len(json.loads(publisher.db.execute('SELECT receipts FROM irc_delivery_intents').fetchone()[0]))==len(state['writes'])
            cases.append('actual_native_utf8_chunker_preserves_order_and_requires_distinct_server_ids_for_all_chunks')
            adapter,publisher,metadata,(_,config)=await build('direct')
            task=asyncio.create_task(adapter.send('#haos','🦊'*300,metadata=metadata))
            def first_confirmed():
                row=publisher.db.execute('SELECT receipts FROM irc_delivery_intents').fetchone()
                return row is not None and len(json.loads(row[0]))==1
            await until(first_confirmed)
            config['bindings']=[]
            assert delivery_result(await task)=={'status':'uncertain'} and len(state['writes'])==1
            cases.append('current_owner_revocation_after_first_confirmed_chunk_prevents_next_native_write')
        finally:
            for resource in resources:await shutdown(resource)
            for writer in list(state['writers']):writer.close()
            listener.close();await listener.wait_closed()
            if state['tasks']:await asyncio.gather(*list(state['tasks']),return_exceptions=True)
            if original_ca is None:os.environ.pop('SSL_CERT_FILE',None)
            else:os.environ['SSL_CERT_FILE']=original_ca
    with tempfile.TemporaryDirectory(prefix='haos-irc-delivery-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_native_send_tls_and_private_sqlite':True,
        'public_gateway_enabled':True,'server_echo_is_not_recipient_delivery_proof':True,
        'fixture_only_loopback_target_and_disposable_ca':True,'external_account_message_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
