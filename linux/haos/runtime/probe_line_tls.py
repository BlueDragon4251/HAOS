#!/usr/bin/env python3
"""Actual trusted TLS material validation and native LINE profile HTTPS admission."""
import asyncio
import base64
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    from haos.gateway_line_tls import material,context
    from haos.gateway import GatewayPolicy
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        from aiohttp import web,ClientSession,TCPConnector,ClientConnectorCertificateError
        now=datetime.now(timezone.utc)
        ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'disposable LINE fixture CA')])
        ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
            .add_extension(x509.KeyUsage(True,False,False,False,False,True,True,False,False),True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),False).sign(ca_key,hashes.SHA256()))
        ca_path=directory/'ca.pem';ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        def leaf(expired=False):
            return (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'line.fixture.invalid')]))
                .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-timedelta(days=2)).not_valid_after(now-timedelta(days=1) if expired else now+timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
                .add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('line.fixture.invalid')]),False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).sign(ca_key,hashes.SHA256()))
        private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        tls={'public_url':'https://line.fixture.invalid/line/webhook','certificate':leaf().public_bytes(serialization.Encoding.PEM).decode(),
            'private_key':private,'bind_host':'127.0.0.1','public_listener':False}
        previous_ca=os.environ.get('SSL_CERT_FILE');previous_dir=os.environ.get('SSL_CERT_DIR')
        os.environ['SSL_CERT_FILE']=str(ca_path);os.environ['SSL_CERT_DIR']=str(directory/'no-system-ca-dir')
        try:
            assert material(tls)==tls
            cases.append('actual_x509_chain_hostname_key_time_and_system_trust_validation_accepts_explicit_fixture_ca')
            for label,change in [('wrong_hostname',{'public_url':'https://other.fixture.invalid/line/webhook'}),
                    ('expired',{'certificate':leaf(True).public_bytes(serialization.Encoding.PEM).decode()}),
                    ('plaintext_public_url',{'public_url':'http://line.fixture.invalid/line/webhook'}),
                    ('public_ip_url',{'public_url':'https://127.0.0.1/line/webhook'}),
                    ('wrong_path',{'public_url':'https://line.fixture.invalid/plugins/line'}),
                    ('embedded_url_credential',{'public_url':'https://user:secret@line.fixture.invalid/line/webhook'}),
                    ('unapproved_public_bind',{'bind_host':'0.0.0.0'}),('false_public_consent',{'public_listener':1}),
                    ('invalid_private_key',{'private_key':'not a private key'}),('oversized_chain',{'certificate':'x'*16385})]:
                try:material({**tls,**change})
                except ValueError:pass
                else:raise AssertionError(label)
                cases.append('tls_'+label+'_refused_before_listener')
            other_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            other=other_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
            try:material({**tls,'private_key':other})
            except ValueError:pass
            else:raise AssertionError('certificate/private key mismatch accepted')
            cases.append('actual_mismatched_private_key_refused')
            if os.environ.get('HAOS_DISPOSABLE_LINE_OWNER')=='1':
                from line_owner_fixture import exercise as owner_exercise
                cases.extend(owner_exercise(directory,tls,{**tls,'certificate':leaf(True).public_bytes(serialization.Encoding.PEM).decode()}))
            os.environ['SSL_CERT_FILE']=str(directory/'missing-ca')
            try:material(tls)
            except ValueError:pass
            else:raise AssertionError('untrusted issuer accepted')
            os.environ['SSL_CERT_FILE']=str(ca_path)
            cases.append('untrusted_certificate_chain_refused')
            private_dir=directory/'material';private_dir.mkdir(mode=0o700)
            server=context(tls,private_dir);assert server.minimum_version>=ssl.TLSVersion.TLSv1_2
            files=sorted((private_dir/'tls').iterdir())
            assert len(files)==2 and all(path.stat().st_mode&0o077==0 and path.stat().st_nlink==1 for path in files)
            original=[path.read_bytes() for path in files];context(tls,private_dir)
            assert original==[path.read_bytes() for path in files]
            cases.append('actual_private_tls_material_is_atomic_single_link_mode_600_and_reused_without_overwrite')
            changed=files[0];changed.write_bytes(b'preserved-owner-recovery-canary')
            try:context(tls,private_dir)
            except PermissionError:pass
            else:raise AssertionError('conflicting retained TLS file overwritten')
            assert changed.read_bytes()==b'preserved-owner-recovery-canary'
            cases.append('conflicting_existing_tls_material_is_preserved_and_requires_owner_recovery')
            with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            user='U'+'a'*32;destination='U'+'d'*32
            config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
                'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'',
                'identity':'owner','capabilities':['create'],'generation':'a'*64,'since':1}]}
            inbox=NativeInbox(directory/'native.db',Redactor());relay=RelayInbox(directory/'relay.db',Redactor())
            parent=directory/'profiles';parent.mkdir(mode=0o700)
            accepted=[];requests=[]
            async def identity(request):requests.append(request.path);return web.json_response({'userId':destination})
            info=web.Application();info.router.add_get('/info',identity);runner=web.AppRunner(info,access_log=None)
            await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            expired_adapter=build_adapter('line',{'channel_secret':'c'*32,'channel_access_token':'private-tls-profile-access',
                'destination':destination,'port':port,'tls':{**tls,'certificate':leaf(True).public_bytes(serialization.Encoding.PEM).decode()}},
                line_context={'parent':parent,'connector':'line','policy':lambda:GatewayPolicy(config),'inbox':inbox})
            expired_adapter._haos_line_identity._target=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/info'
            try:
                assert await expired_adapter.connect() is False
                assert expired_adapter.native_health()['status']=='tls-refused' and requests==[]
                assert not expired_adapter.is_connected and expired_adapter._haos_line_runner is None
                cases.append('actual_expired_tls_profile_stays_inspectable_without_network_or_aborting_other_connector_builds')
            finally:await expired_adapter.close_profile()
            adapter=build_adapter('line',{'channel_secret':'c'*32,'channel_access_token':'private-tls-profile-access',
                'destination':destination,'port':port,'tls':tls},line_context={'parent':parent,'connector':'line','policy':lambda:GatewayPolicy(config),'inbox':inbox})
            adapter._haos_line_identity._target=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/info'
            def receive(event):
                source=adapter_envelope(event,'line');relay.admit(GatewayPolicy(config),'line',source);accepted.append(source);return True
            adapter.set_durable_message_handler(receive)
            try:
                assert await adapter.connect() and adapter.native_health()['status']=='listening-tls'
                payload={'destination':destination,'events':[{'type':'message','mode':'active','timestamp':int(datetime.now(timezone.utc).timestamp()*1000),
                    'webhookEventId':'01K8'+'A'*22,'source':{'type':'user','userId':user},'message':{'type':'text','id':'1234','text':'actual TLS webhook'}}]}
                body=json.dumps(payload).encode();signature=base64.b64encode(hmac.new(('c'*32).encode(),body,hashlib.sha256).digest()).decode()
                ca_context=ssl.create_default_context(cafile=str(ca_path))
                assert ca_context.check_hostname and ca_context.verify_mode==ssl.CERT_REQUIRED
                async with ClientSession(connector=TCPConnector(ssl=ca_context)) as client:
                    try:
                        async with client.post(f'https://127.0.0.1:{port}/line/webhook',data=body,headers={'X-Line-Signature':signature}):pass
                    except ClientConnectorCertificateError:pass
                    else:raise AssertionError('wrong hostname reached TLS callback')
                    assert not accepted
                    cases.append('actual_profile_https_refuses_wrong_client_hostname_before_signed_admission')
                    async with client.post(f'https://127.0.0.1:{port}/line/webhook',server_hostname='line.fixture.invalid',data=body,headers={'X-Line-Signature':signature}) as response:assert response.status==200
                async with asyncio.timeout(5):
                    while not accepted:await asyncio.sleep(.02)
                assert accepted[0]['text']=='actual TLS webhook' and accepted[0]['scope']==destination
                cases.append('actual_registered_native_profile_verified_https_hmac_private_relay_and_native_decode')
            finally:await adapter.close_profile();await runner.cleanup();inbox.close();relay.close()
        finally:
            if previous_ca is None:os.environ.pop('SSL_CERT_FILE',None)
            else:os.environ['SSL_CERT_FILE']=previous_ca
            if previous_dir is None:os.environ.pop('SSL_CERT_DIR',None)
            else:os.environ['SSL_CERT_DIR']=previous_dir
    with tempfile.TemporaryDirectory(prefix='haos-line-tls-') as td:asyncio.run(exercise(Path(td)))
    receipt={'passed':len(cases),'cases':cases,'actual_x509_verified_https_and_native_profile':True,
        'fixture_only_system_ca_loopback_and_identity_target':True,'tls_verification_disabled':False,
        'public_gateway_enabled':True,'actual_root_owner_lifecycle':os.environ.get('HAOS_DISPOSABLE_LINE_OWNER')=='1',
        'service_quiescence_and_audit_location_are_fixtures':True,
        'external_dns_router_line_acceptance_or_installed_acceptance':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
