"""Disposable PID-1 Docker fixture: actual gateway-UID SDK entry over real local TLS."""
import asyncio
import datetime
import ipaddress
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_MATRIX_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Docker namespace required; never run on installed HAOS')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable, '/repo/linux/haos/runtime/install_package.py', '/repo/linux/haos/haos', str(code/'haos')], check=True)
    runtime=code/'hermes/.venv'
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    subprocess.run([sys.executable, '/repo/linux/haos/runtime/install_package.py', '/deps', '/sdk'], check=True)
    site=runtime/'lib/python3.11/site-packages';(site/'frozen_fixture_deps.pth').write_text('/sdk\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/deps',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    directory=Path(tempfile.mkdtemp(prefix='haos-matrix-account-process-'));directory.chmod(0o755)
    now=datetime.datetime.now(datetime.timezone.utc)
    ca_key=ec.generate_private_key(ec.SECP256R1());ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable HAOS fixture CA')])
    ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(ca_key,hashes.SHA256()))
    leaf_key=ec.generate_private_key(ec.SECP256R1())
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]))
        .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(ca_key,hashes.SHA256()))
    cert=directory/'server.pem';key=directory/'server.key'
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM));key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write(b'\n'+ca.public_bytes(serialization.Encoding.PEM))
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(cert,key)
    from aiohttp import web
    from mautrix.crypto.account import OlmAccount
    from mautrix.types import UserID,DeviceID
    account=OlmAccount();bot,peer='@haos:fixture.invalid','@owner:fixture.invalid';token='disposable-local-process-token'
    signed=account.get_device_keys(UserID(peer),DeviceID('PHONE')).serialize()
    state={'status':200,'device':'HAOS','bad_signature':False,'calls':[]}
    async def api(request):
        assert request.headers['Authorization']=='Bearer '+token;state['calls'].append(request.path)
        if state['status']!=200:return web.json_response({'errcode':'M_UNKNOWN_TOKEN' if state['status']==401 else 'M_LIMIT_EXCEEDED','error':token,'retry_after_ms':19000},status=state['status'])
        if request.path.endswith('/account/whoami'):return web.json_response({'user_id':bot,'device_id':state['device']})
        assert request.path.endswith('/keys/query') and request.method=='POST'
        assert (await request.json())['device_keys']=={peer:[]}
        value=json.loads(json.dumps(signed))
        if state['bad_signature']:value['signatures'][peer]['ed25519:PHONE']='A'*86
        return web.json_response({'device_keys':{peer:{'PHONE':value}},'failures':{}})
    cases=[]
    async def exercise():
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();listener=web.TCPSite(runner,'127.0.0.1',0,ssl_context=tls);await listener.start()
        port=listener._server.sockets[0].getsockname()[1]
        request={'credentials':{'token':token,'homeserver':f'https://localhost:{port}','user_id':bot,'device_id':'HAOS'},'sender':peer}
        async def invoke(uid):
            command=[str(runtime/'bin/python'),'-E','-s','-m','haos.gateway_matrix_account']
            environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'}
            assert token not in repr(command) and token not in repr(environment)
            child=await asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=uid,group=uid,extra_groups=[],umask=0o077,cwd=str(code),env=environment)
            stdout,stderr=await asyncio.wait_for(child.communicate(json.dumps(request).encode()),70)
            assert token.encode() not in stdout and token.encode() not in stderr
            return child.returncode,stdout,stderr
        try:
            before=len(state['calls']);status,stdout,stderr=await invoke(0)
            assert status!=0 and len(state['calls'])==before;cases.append('actual_root_process_is_refused_before_network_or_secret_use')
            status,stdout,stderr=await invoke(65533)
            assert status!=0 and len(state['calls'])==before;cases.append('actual_agent_uid_cannot_invoke_gateway_account_helper')
            status,stdout,stderr=await invoke(65534)
            assert status==0,(stdout,stderr)
            value=json.loads(stdout);assert value=={'devices':[{'device_id':'PHONE','ed25519':str(account.signing_key),'curve25519':str(account.identity_key)}],
                'signature_checked':True,'owner_approval_required':True},value
            assert len(state['calls'])==before+2;cases.append('actual_gateway_uid_frozen_sdk_entry_verifies_system_trusted_local_tls_and_public_device_signature')
            state['device']='FOREIGN';before=len(state['calls']);status,stdout,stderr=await invoke(65534)
            assert status==0 and set(json.loads(stdout))=={'error'} and len(state['calls'])==before+1
            cases.append('actual_helper_wrong_device_cannot_reach_device_query');state['device']='HAOS'
            for code_value in [401,429]:
                state['status']=code_value;before=len(state['calls']);status,stdout,stderr=await invoke(65534)
                assert status==0 and set(json.loads(stdout))=={'error'} and len(state['calls'])==before+1
                cases.append('actual_helper_single_redacted_account_refusal_'+str(code_value))
            state['status']=200;state['bad_signature']=True;before=len(state['calls']);status,stdout,stderr=await invoke(65534)
            assert status==0 and set(json.loads(stdout))=={'error'} and len(state['calls'])==before+2
            cases.append('actual_helper_native_signature_failure_yields_no_approval_candidate')
        finally:await runner.cleanup()
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uid_cases':[0,65533,65534],'tls_verification_disabled':False,
        'external_connections':False,'installed_haos_accepted':False,'live_account_accepted':False},indent=2))


if __name__=='__main__':main()
