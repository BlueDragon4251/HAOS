"""Disposable actual-UID LINE process kill/reopen with installed public code and TLS."""
import asyncio
import base64
import hashlib
import hmac
import sqlite3
import time
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
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_LINE_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Docker namespace required; never run on installed HAOS')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    upstream=Path(os.environ.get('HAOS_LINE_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (upstream/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':
        raise PermissionError('exact pinned public Hermes source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-line-public-code-'))
    shutil.copytree(upstream,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py',str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv'
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    site=runtime/'lib/python3.11/site-packages';(site/'frozen_fixture_deps.pth').write_text('/sdk\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path[:0]=['/deps',str(code)]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    from aiohttp import web,ClientSession,TCPConnector
    directory=Path(tempfile.mkdtemp(prefix='haos-line-process-'));directory.chmod(0o755)
    now=datetime.datetime.now(datetime.timezone.utc)
    ca_key=ec.generate_private_key(ec.SECP256R1());ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable LINE process CA')])
    ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
        .add_extension(x509.KeyUsage(True,False,False,False,False,True,True,False,False),True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),False).sign(ca_key,hashes.SHA256()))
    leaf_key=ec.generate_private_key(ec.SECP256R1())
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'line.fixture.invalid')]))
        .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
        .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('line.fixture.invalid'),x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),False).sign(ca_key,hashes.SHA256()))
    chain=leaf.public_bytes(serialization.Encoding.PEM).decode()
    private_key=leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    cert=directory/'server.pem';cert.write_text(chain)
    key=directory/'server.key';key.write_text(private_key);key.chmod(0o600)
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write(b'\n'+ca.public_bytes(serialization.Encoding.PEM))
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(cert,key)
    private=directory/'gateway';private.mkdir(mode=0o700);os.chown(private,65534,65534)
    owner=directory/'owner-secret';owner.write_text('disposable-root-owner-canary');owner.chmod(0o600)
    script=directory/'worker.py'
    script.write_text('''
import asyncio,json,os,sys
from pathlib import Path
from haos.gateway import digest,GatewayPolicy
from haos.gateway_runtime import build_adapter,require_runtime_identity,adapter_envelope
from haos.gateway_delivery import delivery_result
from haos.gateway_raw import NativeInbox
from haos.gateway_relay import RelayInbox
from haos.gateway_publication import validate_snapshot
from haos.redaction import Redactor
assert os.getgroups()==[]
if os.geteuid()==65534:require_runtime_identity()
request=json.loads(sys.stdin.readline())
try:Path(request['owner_canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged identity read owner material')
if request['action']=='agent':
    assert os.geteuid()==65533
    for name in ['native.db','relay.db']:
        try:Path(request['state'],name).read_bytes()
        except PermissionError:pass
        else:raise AssertionError('agent read private LINE journal')
    try:NativeInbox(Path(request['state'],'native.db'),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private LINE journal')
    print(json.dumps({'uid':os.geteuid(),'private_journals_denied':True}));sys.exit(0)
assert os.geteuid()==65534
validate_snapshot(request['policy'],{'connectors':{'line':request['credentials']}})
async def exercise():
    root=Path(request['state']);inbox=NativeInbox(root/'native.db',Redactor())
    relay=RelayInbox(root/'relay.db',Redactor())
    before=inbox.db.execute('SELECT state FROM line_delivery_intents').fetchone() if request['action']=='recover' else None
    parent=root/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
    policy=lambda:GatewayPolicy(request['policy'])
    adapter=build_adapter('line',request['credentials'],line_context={'parent':parent,'connector':'line','policy':policy,'inbox':inbox})
    adapter._haos_line_identity._target=request['api']+'/info'
    adapter._haos_line_publisher._target=request['api']+'/push'
    def receive(event):relay.admit(policy(),'line',adapter_envelope(event,'line'));return True
    adapter.set_durable_message_handler(receive)
    try:
        assert await adapter.connect() and adapter.native_health()['status']=='listening-tls'
        if request['action']=='send':
            print(json.dumps({'listening':True,'uid':os.geteuid()}),flush=True)
            assert await asyncio.to_thread(sys.stdin.readline)=='SEND\\n'
        binding=request['policy']['bindings'][0]
        metadata={'haos_scope':binding['scope'],'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},
            'haos_delivery_id':digest('private-line-process-obligation'),'haos_delivery_attempt':1,'notify':True}
        receipt=await adapter.send(binding['chat'],'private process reply',metadata=metadata)
        result=delivery_result(receipt)
        assert result=={'status':'uncertain'}
        after=inbox.db.execute('SELECT state FROM line_delivery_intents').fetchone()[0]
        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
        print(json.dumps({'uid':os.geteuid(),'prior_state':before[0] if before else None,'state':after,
            'result':result,'private_owner_denied':True,'kernel_lease_reacquired':True,'retained_relay_count':1}),flush=True)
    finally:await adapter.close_profile();relay.close();inbox.close()
asyncio.run(exercise())
''')
    script.chmod(0o644)
    state={'pushes':0,'lookups':0,'seen':asyncio.Event(),'release':asyncio.Event()};cases=[]
    async def exercise():
        user='U'+'a'*32;destination='U'+'d'*32
        async def info(request):
            assert request.headers['Authorization']=='Bearer private-line-process-access'
            state['lookups']+=1;return web.json_response({'userId':destination})
        async def push(request):
            assert request.headers['Authorization']=='Bearer private-line-process-access'
            assert await request.json()=={'to':user,'messages':[{'type':'text','text':'private process reply'}]}
            with sqlite3.connect('file:'+str(private/'native.db')+'?mode=ro',uri=True) as observer:
                assert observer.execute('SELECT state FROM line_delivery_intents').fetchone()==('writing',)
            state['pushes']+=1;state['seen'].set();await state['release'].wait()
            return web.json_response({'sentMessages':[{'id':'1234'}]},headers={'X-Line-Request-Id':'12345678-1234-1234-1234-123456789abc'})
        app=web.Application();app.router.add_get('/info',info);app.router.add_post('/push',push)
        runner=web.AppRunner(app,access_log=None,shutdown_timeout=2);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=tls);await site.start()
        api='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        import socket
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        request={'state':str(private),'owner_canary':str(owner),'api':api,
            'credentials':{'channel_secret':'c'*32,'channel_access_token':'private-line-process-access','destination':destination,'port':port,
                'tls':{'public_url':'https://line.fixture.invalid/line/webhook','certificate':chain,'private_key':private_key,
                    'bind_host':'127.0.0.1','public_listener':False}},
            'policy':{'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
                'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,
                'thread':'','identity':'owner','capabilities':['create','read'],'generation':'a'*64,
                'since':int((time.time()-60)*1000)}]}}
        async def invoke(uid,action):
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),str(script),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=uid,group=uid,extra_groups=[],umask=0o077,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(code),
                    'PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1','HERMES_HOME':str(private/'unused-home')})
            child.stdin.write((json.dumps({**request,'action':action})+'\n').encode());await child.stdin.drain()
            return child
        children=[]
        try:
            first=await invoke(65534,'send');children.append(first)
            ready=await asyncio.wait_for(first.stdout.readline(),20)
            if not ready:
                stdout,stderr=await first.communicate();raise AssertionError('actual LINE worker failed: '+stderr.decode()[-2500:])
            assert json.loads(ready)=={'listening':True,'uid':65534}
            body=json.dumps({'destination':destination,'events':[{'type':'message','mode':'active','timestamp':int(time.time()*1000),
                'webhookEventId':'01K8'+'A'*22,'source':{'type':'user','userId':user},
                'message':{'type':'text','id':'1234','text':'private retained process mission'}}]}).encode()
            signature=base64.b64encode(hmac.new(('c'*32).encode(),body,hashlib.sha256).digest()).decode()
            async with ClientSession(connector=TCPConnector(ssl=ssl.create_default_context())) as client:
                async with client.post(f'https://localhost:{port}/line/webhook',data=body,headers={'X-Line-Signature':signature}) as response:
                    assert response.status==200
            async with asyncio.timeout(10):
                while True:
                    with sqlite3.connect('file:'+str(private/'native.db')+'?mode=ro',uri=True) as observer:
                        row=observer.execute('SELECT state FROM native_inbox').fetchone()
                    if row==('committed',):break
                    await asyncio.sleep(.02)
            cases.append('actual_unprivileged_gateway_installed_public_profile_accepts_verified_https_hmac_and_commits_native_relay')
            first.stdin.write(b'SEND\n');await first.stdin.drain()
            await asyncio.wait_for(state['seen'].wait(),10)
            assert state['pushes']==1 and first.returncode is None
            first.kill();await asyncio.wait_for(first.wait(),5);assert first.returncode==-9
            cases.append('actual_gateway_uid_native_verified_https_push_has_durable_intent_before_real_sigkill')
            agent=await invoke(65533,'agent');children.append(agent)
            stdout,stderr=await asyncio.wait_for(agent.communicate(),10)
            assert agent.returncode==0,stderr.decode()[-2500:]
            assert json.loads(stdout)=={'uid':65533,'private_journals_denied':True}
            cases.append('actual_agent_uid_cannot_read_private_native_relay_or_owner_credentials_after_crash')
            second=await invoke(65534,'recover');children.append(second)
            stdout,stderr=await asyncio.wait_for(second.communicate(),20)
            assert second.returncode==0,stderr.decode()[-2500:]
            assert json.loads(stdout)=={'uid':65534,'prior_state':'writing','state':'uncertain','result':{'status':'uncertain'},
                'private_owner_denied':True,'kernel_lease_reacquired':True,'retained_relay_count':1}
            assert state['pushes']==1 and state['lookups']==2
            cases.append('new_gateway_process_reacquires_kernel_lease_retains_committed_input_and_never_resends_uncertain_native_push')
        finally:
            state['release'].set()
            for child in children:
                if child.returncode is None:child.kill();await child.wait()
            await runner.cleanup()
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uid_cases':[0,65533,65534],
        'actual_sigkill':True,'tls_verification_disabled':False,'public_gateway_enabled':True,
        'fixture_only_disposable_ca_and_loopback_targets':True,
        'external_connections_or_recipient_acceptance':False,'installed_haos_accepted':False},indent=2))


if __name__=='__main__':main()
