#!/usr/bin/env python3
"""Actual local TLS, IRCv3 handshake, native codec and private SQLite fixtures."""
import asyncio
import base64
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayPolicy
    from haos.gateway_irc_ingress import PreparedIRCPolicy,install as ingress
    from haos.gateway_irc_transport import install,Rejected
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
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
        ca_key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable IRC fixture CA')])
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
        state={'mode':'good','commands':[],'writers':set(),'tasks':set()};counter=[0]
        def frame(account='owner-account',identity='message_1'):
            return f'@account={account};time={datetime.now(timezone.utc).isoformat()};msgid={identity} :owner-nick!user@host PRIVMSG #haos :haos-bot: hello owner\r\n'
        async def server(reader,writer):
            state['writers'].add(writer);task=asyncio.current_task();state['tasks'].add(task)
            mode=state['mode']
            async def put(value):
                if mode=='tagged_controls' and isinstance(value,str):
                    value=''.join((line if line.startswith('@') else '@time='+datetime.now(timezone.utc).isoformat()+' '+line)+'\r\n'
                        for line in value.split('\r\n') if line)
                writer.write(value.encode() if isinstance(value,str) else value);await writer.drain()
            async def get():
                value=(await asyncio.wait_for(reader.readuntil(b'\r\n'),2)).decode().strip()
                redacted=('<private PASS>' if value.startswith('PASS ') else '<private SASL payload>'
                    if value.startswith('AUTHENTICATE ') and value not in {'AUTHENTICATE PLAIN','AUTHENTICATE +'} else value)
                state['commands'].append(redacted);return value
            try:
                assert await get()=='CAP LS 302'
                line=await get()
                if line.startswith('PASS '):
                    assert mode=='server_password' and line=='PASS disposable-private-server-password'
                    line=await get()
                assert line.startswith('NICK ')
                assert (await get()).startswith('USER ')
                if mode=='early_registration':await put(':server 001 haos-bot :welcome\r\n')
                elif mode=='server_password_refused':await put(':server 464 haos-bot :access refused\r\n')
                elif mode=='unknown_case_mapping':await put(':server 005 haos-bot CASEMAPPING=vendor-sensitive :unsupported\r\n')
                elif mode=='duplicate_control_tags':await put('@time=one;time=two :server CAP haos-bot LS :account-tag server-time message-tags\r\n')
                elif mode=='no_account_capability':await put(':server CAP haos-bot LS :server-time message-tags\r\n')
                elif mode=='eof':return
                elif mode=='oversized':await put(b'x'*8192)
                elif mode=='bad_utf8':await put(b'\xff\r\n')
                elif mode=='incomplete_frame':await put(b':server CAP haos-bot LS :account-tag');return
                elif mode=='timeout':await asyncio.sleep(3)
                else:
                    await put(':server CAP haos-bot LS * :account-tag server-time\r\n')
                    sasl=mode.startswith('sasl_')
                    offered=(' sasl=EXTERNAL' if mode=='sasl_missing_mechanism' else ' sasl=PLAIN,EXTERNAL') if sasl and mode!='sasl_no_capability' else ''
                    await put(':server CAP haos-bot LS :message-tags'+offered+'\r\n')
                    requested='account-tag message-tags'+(' sasl' if sasl else '')+' server-time'
                    assert await get()=='CAP REQ :'+requested
                    if mode=='cap_nak':await put(':server CAP haos-bot NAK :account-tag message-tags server-time\r\n')
                    elif mode=='partial_ack':await put(':server CAP haos-bot ACK :account-tag server-time\r\n')
                    else:
                        await put(':server CAP haos-bot ACK :'+requested+'\r\n')
                        if sasl:
                            assert await get()=='AUTHENTICATE PLAIN'
                            if mode=='sasl_early_registration':
                                await put(':server 001 haos-bot :premature registration\r\n');await reader.read();return
                            await put('AUTHENTICATE '+('unexpected' if mode=='sasl_wrong_challenge' else '+')+'\r\n')
                            if mode=='sasl_wrong_challenge':await reader.read();return
                            chunks=[]
                            while True:
                                auth=await get();assert auth.startswith('AUTHENTICATE ')
                                chunk=auth.split(' ',1)[1];assert len(chunk)<=400
                                if chunk!='+':chunks.append(chunk)
                                if len(chunk)<400:break
                            decoded=base64.b64decode(''.join(chunks),validate=True)
                            assert decoded==('bot-account\0bot-account\0'+sasl_password(mode)).encode()
                            if mode=='sasl_exact_chunk':assert chunks and len(chunks[-1])==400 and chunk=='+'
                            if mode=='sasl_chunked':assert len(chunks)>1
                            if mode=='sasl_refused':
                                await put(':server 904 haos-bot :SASL refused\r\n');await reader.read();return
                            if mode!='sasl_missing_account_confirmation':
                                account='other-account' if mode=='sasl_wrong_account' else 'bot-account'
                                await put(':server 900 haos-bot haos-bot!user@host '+account+' :logged in\r\n')
                            await put(':server 903 haos-bot :SASL success\r\n')
                        assert await get()=='CAP END'
                        await put(':server 001 '+('other-bot' if mode=='changed_nickname' else 'haos-bot')+' :welcome\r\n')
                        if mode!='changed_nickname':
                            assert await get()=='JOIN #haos'
                            await put(':haos-bot!bot@server JOIN :'+('#wrong' if mode=='wrong_join' else '#haos')+'\r\n')
                            if mode in {'good','tagged_controls'}:
                                await put('PING :local-keepalive\r\n')
                                assert await get()=='PONG :local-keepalive'
                                await put(frame('unknown-account','unknown'))
                                await put(frame())
                            elif mode=='cap_loss':await put(':server CAP haos-bot DEL :account-tag\r\n')
                            elif mode=='live_eof':return
                            elif mode=='kick':await put(':server KICK #haos haos-bot :removed\r\n')
                            elif mode=='part':await put(':haos-bot!bot@server PART #haos :left\r\n')
                            elif mode=='nick_change':await put(':haos-bot!bot@server NICK :unexpected\r\n')
                            elif mode=='sasl_live_logout':await put(':server 901 haos-bot haos-bot!user@host :logged out\r\n')
                await reader.read()
            except (ConnectionError,asyncio.IncompleteReadError,asyncio.TimeoutError):pass
            finally:
                writer.close()
                try:await writer.wait_closed()
                except OSError:pass
                state['writers'].discard(writer);state['tasks'].discard(task)
        listener=await asyncio.start_server(server,'127.0.0.1',0,ssl=tls)
        port=listener.sockets[0].getsockname()[1]
        resources=[]
        def sasl_password(mode):return 'x'*276 if mode=='sasl_exact_chunk' else 'y'*900 if mode=='sasl_chunked' else 'disposable-private-sasl-password'
        def build(mode):
            state['mode']=mode;state['commands']=[];counter[0]+=1
            home=directory/str(counter[0]);home.mkdir(mode=0o700)
            config={'version':1,'connectors':[{'id':'irc','platform':'irc'}],'bindings':[{
                'id':'owner','connector':'irc','sender':'owner-account','chat':'#haos','scope':'irc.fixture.invalid:6697',
                'thread':'','identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
            policy=lambda:GatewayPolicy(config)
            native=NativeInbox(home/'native.db',Redactor());relay=RelayInbox(home/'relay.db',Redactor())
            value={'server':'irc.fixture.invalid','port':6697,'nickname':'haos-bot','channel':'#haos'}
            if mode=='server_password':value['server_password']='disposable-private-server-password'
            if mode.startswith('sasl_'):value.update(sasl_username='bot-account',sasl_password=sasl_password(mode))
            adapter=ingress(durable_adapter(IRCAdapter(PlatformConfig(enabled=True,extra=value))))
            adapter._haos_native=SimpleNamespace(connector='irc',policy=policy,inbox=native)
            accepted=[]
            def receive(event):
                source=adapter_envelope(event,'irc');relay.admit(policy(),'irc',source);accepted.append(source);return True
            adapter.set_durable_message_handler(receive)
            boundary=install(adapter,value);boundary._handshake_seconds=2
            async def open_local(host,remote_port,**kwargs):
                assert host=='irc.fixture.invalid' and remote_port==6697
                assert kwargs['server_hostname']=='irc.fixture.invalid'
                assert kwargs['ssl'].verify_mode==ssl.CERT_REQUIRED and kwargs['ssl'].check_hostname is True
                return await asyncio.open_connection('127.0.0.1',port,**kwargs)
            boundary._open=open_local;resources.append((boundary,native,relay))
            return boundary,adapter,config,accepted
        async def refused(action):
            try:await action()
            except (ConnectionError,PermissionError,asyncio.TimeoutError,ssl.SSLCertVerificationError):return
            raise AssertionError('unapproved IRC TLS/protocol route admitted')
        try:
            boundary,adapter,config,accepted=build('good')
            assert await boundary.connect() and boundary.confirmed and adapter.is_connected
            worker=asyncio.create_task(boundary.receive())
            deadline=time.monotonic()+2
            while not accepted and time.monotonic()<deadline:await asyncio.sleep(.01)
            assert len(accepted)==1 and accepted[0]['sender']=='owner-account'
            assert 'PONG :local-keepalive' in state['commands']
            cases.append('actual_verified_tls_multiline_cap_negotiation_join_keepalive_and_native_account_admission')
            await refused(lambda:boundary.write('PRIVMSG #other :unauthorized'))
            await refused(lambda:adapter._send_raw('PRIVMSG #other :unauthorized'))
            await refused(lambda:adapter.send('#haos','unreviewed reply'))
            cases.append('raw_and_native_standalone_send_remain_denied_before_outbox_implementation')
            config['bindings']=[]
            await refused(lambda:worker)
            assert not boundary.confirmed and not adapter.is_connected and boundary.writer is None
            cases.append('owner_withdrawal_closes_idle_actual_tls_subscription_without_new_remote_input')
            boundary,adapter,config,accepted=build('tagged_controls');assert await boundary.connect()
            worker=asyncio.create_task(boundary.receive());deadline=time.monotonic()+2
            while not accepted and time.monotonic()<deadline:await asyncio.sleep(.01)
            assert len(accepted)==1 and 'PONG :local-keepalive' in state['commands']
            worker.cancel()
            try:await worker
            except asyncio.CancelledError:pass
            cases.append('real_server_time_tags_on_capabilities_registration_join_and_ping_preserve_native_admission')
            for mode in ['server_password_refused','unknown_case_mapping','duplicate_control_tags','early_registration','no_account_capability','eof','oversized','bad_utf8','incomplete_frame',
                    'timeout','cap_nak','partial_ack','changed_nickname','wrong_join']:
                boundary,adapter,config,accepted=build(mode)
                await refused(boundary.connect)
                assert not boundary.confirmed and not accepted and boundary.writer is None
                if mode=='server_password_refused':
                    assert boundary.status=='authentication-refused'
                    before=list(state['commands']);await refused(boundary.connect);assert state['commands']==before
                cases.append('actual_tls_'+mode+'_never_admits_messages')
            for mode in ['cap_loss','live_eof','kick','part','nick_change']:
                boundary,adapter,config,accepted=build(mode);assert await boundary.connect()
                await refused(boundary.receive)
                assert not boundary.confirmed and boundary.writer is None and not accepted
                cases.append('actual_tls_'+mode+'_closes_confirmed_subscription')
            boundary,adapter,config,accepted=build('server_password')
            assert await boundary.connect() and '<private PASS>' in state['commands']
            assert not any('disposable-private-server-password' in x for x in state['commands'])
            await boundary.disconnect()
            cases.append('private_server_password_crosses_only_verified_tls_and_is_absent_from_fixture_log')
            for attribute,value in [('server','other.fixture.invalid'),('port',6667),('channel','#other'),
                    ('use_tls',False),('server_password','changed'),('nickserv_password','unapproved'),('nickname','other-bot')]:
                boundary,adapter,config,accepted=build('idle');assert await boundary.connect()
                worker=asyncio.create_task(boundary.receive());await asyncio.sleep(.01)
                setattr(adapter,attribute,value)
                await refused(lambda:worker)
                assert boundary.status=='revoked' and boundary.writer is None and not accepted
                cases.append('live_private_'+attribute+'_mutation_revokes_actual_tls_connection')
            boundary,adapter,config,accepted=build('eof')
            async def wrong_hostname(host,remote_port,**kwargs):
                kwargs['server_hostname']='wrong.fixture.invalid'
                return await asyncio.open_connection('127.0.0.1',port,**kwargs)
            boundary._open=wrong_hostname
            await refused(boundary.connect)
            assert not accepted and boundary.writer is None
            assert not state['commands']
            cases.append('real_tls_hostname_mismatch_refused_before_irc_credentials_or_frames')
            boundary,adapter,config,accepted=build('eof')
            os.environ.pop('SSL_CERT_FILE',None)
            await refused(boundary.connect)
            assert not accepted and boundary.writer is None
            assert not state['commands']
            cases.append('real_tls_untrusted_ca_refused_before_irc_credentials_or_frames')
            os.environ['SSL_CERT_FILE']=str(ca_path)
            boundary,adapter,config,accepted=build('sasl_live_logout');assert await boundary.connect()
            await refused(boundary.receive)
            assert boundary.status=='authentication-refused' and not accepted and boundary.writer is None
            before=list(state['commands']);await refused(boundary.connect);assert state['commands']==before
            cases.append('actual_tls_sasl_logout_closes_socket_and_refuses_implicit_reauthentication')
            for mode in ['sasl_good','sasl_chunked','sasl_exact_chunk']:
                boundary,adapter,config,accepted=build(mode);assert await boundary.connect()
                assert boundary._sasl_stage=='complete' and '<private SASL payload>' in state['commands']
                assert not any(sasl_password(mode) in x for x in state['commands'])
                await refused(lambda:boundary.write('AUTHENTICATE PLAIN'))
                await boundary.disconnect();cases.append('actual_tls_'+mode+'_private_account_authenticated_before_registration')
            for mode in ['sasl_refused','sasl_wrong_account','sasl_missing_account_confirmation','sasl_wrong_challenge',
                    'sasl_missing_mechanism','sasl_no_capability','sasl_early_registration']:
                boundary,adapter,config,accepted=build(mode);await refused(boundary.connect)
                assert not accepted and not boundary.confirmed and boundary.writer is None
                assert 'CAP END' not in state['commands'] and not any(x.startswith('JOIN ') for x in state['commands'])
                if mode in {'sasl_refused','sasl_wrong_account','sasl_missing_account_confirmation','sasl_wrong_challenge','sasl_missing_mechanism'}:
                    assert boundary.status=='authentication-refused'
                    before=list(state['commands']);await refused(boundary.connect);assert state['commands']==before
                cases.append('actual_tls_'+mode+'_never_authorizes_registration_or_messages')
            boundary,adapter,config,accepted=build('eof');adapter.use_tls=False
            await refused(boundary.connect);assert boundary.writer is None
            cases.append('native_plaintext_configuration_refused_before_connection')
        finally:
            for boundary,native,relay in resources:await boundary.disconnect();native.close();relay.close()
            for writer in list(state['writers']):writer.close()
            listener.close();await listener.wait_closed()
            if state['tasks']:await asyncio.gather(*list(state['tasks']),return_exceptions=True)
            if original_ca is None:os.environ.pop('SSL_CERT_FILE',None)
            else:os.environ['SSL_CERT_FILE']=original_ca
    with tempfile.TemporaryDirectory(prefix='haos-irc-tls-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_local_tls_ircv3_and_pinned_native_codec':True,
        'fixture_only_loopback_destination_and_disposable_ca':True,'public_gateway_enabled':True,
        'live_server_account_nickserv_sasl_delivery_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
