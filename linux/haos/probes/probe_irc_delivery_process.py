"""Disposable actual-UID IRC process kill/reopen with installed public code and TLS."""
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
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_IRC_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Docker namespace required; never run on installed HAOS')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    upstream=Path(os.environ.get('HAOS_IRC_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (upstream/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':
        raise PermissionError('exact pinned public Hermes source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-irc-public-code-'))
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
    directory=Path(tempfile.mkdtemp(prefix='haos-irc-process-'));directory.chmod(0o755)
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
    private=directory/'gateway';private.mkdir(mode=0o700);os.chown(private,65534,65534)
    owner=directory/'owner-secret';owner.write_text('disposable-root-owner-canary');owner.chmod(0o600)
    script=directory/'worker.py'
    script.write_text('''
import asyncio,json,os,pwd,sys
from pathlib import Path
from haos.gateway import digest
from haos.gateway_irc_ingress import PreparedIRCPolicy
from haos.gateway_runtime import build_adapter,delivery_result
from haos.gateway_delivery import delivery_result
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
request=json.load(sys.stdin)
assert os.getgroups()==[]
try:Path(request['owner_canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged identity read private owner material')
if request['action']=='agent':
    assert os.geteuid()==65533
    try:Path(request['state'],'native.db').read_bytes()
    except PermissionError:pass
    else:raise AssertionError('agent read private IRC journal')
    try:NativeInbox(Path(request['state'],'native.db'),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private IRC journal')
    print(json.dumps({'uid':os.geteuid(),'private_journal_denied':True}));sys.exit(0)
assert os.geteuid()==65534 and pwd.getpwnam('haos-gateway').pw_uid==65534
async def exercise():
    root=Path(request['state']);inbox=NativeInbox(root/'native.db',Redactor([request['credentials']['server_password']]))
    before=inbox.db.execute("SELECT state FROM irc_delivery_intents").fetchone() if request['action']=='recover' else None
    parent=root/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
    policy=lambda:PreparedIRCPolicy(request['policy'])
    adapter=build_adapter('irc',request['credentials'],irc_context={'parent':parent,'connector':'irc','policy':policy,'inbox':inbox})
    adapter.set_durable_message_handler(lambda event:False)
    try:
        assert await adapter.connect()
        binding=request['policy']['bindings'][0]
        metadata={'haos_scope':binding['scope'],'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},
            'haos_delivery_id':digest('private-process-obligation'),'haos_delivery_attempt':1,'notify':True}
        receipt=await adapter.send('#haos','private process reply',metadata=metadata)
        result=delivery_result(receipt)
        assert result=={'status':'uncertain'}
        after=inbox.db.execute('SELECT state FROM irc_delivery_intents').fetchone()[0]
        print(json.dumps({'uid':os.geteuid(),'prior_state':before[0] if before else None,'state':after,
            'result':result,'private_owner_denied':True,'kernel_lease_reacquired':True}),flush=True)
    finally:await adapter.close_profile();inbox.close()
asyncio.run(exercise())
'''.replace('from haos.gateway_runtime import build_adapter,delivery_result','from haos.gateway_runtime import build_adapter'))
    script.chmod(0o644)
    state={'writes':0,'connections':0,'seen':asyncio.Event(),'writers':set(),'tasks':set()}
    cases=[]
    async def exercise():
        async def server(reader,writer):
            state['connections']+=1;state['writers'].add(writer);state['tasks'].add(asyncio.current_task())
            async def get():return (await asyncio.wait_for(reader.readuntil(b'\r\n'),10)).decode().rstrip('\r\n')
            async def put(text):writer.write(text.encode());await writer.drain()
            try:
                assert await get()=='CAP LS 302';assert await get()=='PASS disposable-irc-process-password'
                assert await get()=='NICK haos-bot';assert (await get()).startswith('USER haos-bot ')
                caps='account-tag batch echo-message labeled-response message-tags server-time'
                await put(':server CAP haos-bot LS :'+caps+'\r\n');assert await get()=='CAP REQ :'+caps
                await put(':server CAP haos-bot ACK :'+caps+'\r\n');assert await get()=='CAP END'
                await put(':server 001 haos-bot :welcome\r\n');assert await get()=='JOIN #haos'
                await put(':haos-bot!bot@server JOIN :#haos\r\n')
                while True:
                    raw=await get();assert raw.startswith('@label=haos_') and raw.endswith('PRIVMSG #haos :private process reply')
                    state['writes']+=1;state['seen'].set()
                    # Deliberately no echo: a killed writer cannot know whether
                    # the provider published this request.
            except (ConnectionError,asyncio.IncompleteReadError,asyncio.TimeoutError):pass
            finally:
                writer.close()
                try:await writer.wait_closed()
                except OSError:pass
                state['writers'].discard(writer);state['tasks'].discard(asyncio.current_task())
        listener=await asyncio.start_server(server,'127.0.0.1',0,ssl=tls);port=listener.sockets[0].getsockname()[1]
        request={'state':str(private),'owner_canary':str(owner),
            'credentials':{'server':'localhost','port':port,'nickname':'haos-bot','channel':'#haos','server_password':'disposable-irc-process-password'},
            'policy':{'version':1,'connectors':[{'id':'irc','platform':'irc'}],'bindings':[{
                'id':'owner','connector':'irc','sender':'owner-account','chat':'#haos','scope':f'localhost:{port}',
                'thread':'','identity':'owner','capabilities':['create','read'],'generation':'a'*64,
                'since':int((datetime.datetime.now(datetime.timezone.utc).timestamp()-60)*1000)}]}}
        async def invoke(uid,action):
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),str(script),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=uid,group=uid,extra_groups=[],umask=0o077,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(code),
                    'PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1','HERMES_HOME':str(private/'unused-home')})
            child.stdin.write(json.dumps({**request,'action':action}).encode());await child.stdin.drain();child.stdin.close()
            return child
        children=[]
        try:
            first=await invoke(65534,'send');children.append(first)
            try:await asyncio.wait_for(state['seen'].wait(),20)
            except asyncio.TimeoutError:
                if first.returncode is not None:
                    stdout,stderr=await first.communicate();raise AssertionError('actual IRC worker failed: '+stderr.decode()[-2500:])
                raise
            assert state['writes']==1 and first.returncode is None
            first.kill();await asyncio.wait_for(first.wait(),5);assert first.returncode==-9
            cases.append('actual_gateway_uid_installed_frozen_sdk_and_system_trusted_tls_write_precedes_real_sigkill')
            agent=await invoke(65533,'agent');children.append(agent)
            stdout,stderr=await asyncio.wait_for(agent.communicate(),10)
            assert agent.returncode==0,stderr.decode()[-2500:]
            assert json.loads(stdout)=={'uid':65533,'private_journal_denied':True}
            cases.append('actual_agent_uid_cannot_read_or_open_the_crashed_gateway_private_journal_or_owner_secret')
            before=state['writes'];second=await invoke(65534,'recover');children.append(second)
            stdout,stderr=await asyncio.wait_for(second.communicate(),20)
            assert second.returncode==0,stderr.decode()[-2500:]
            report=json.loads(stdout)
            assert report=={'uid':65534,'prior_state':'writing','state':'uncertain','result':{'status':'uncertain'},
                'private_owner_denied':True,'kernel_lease_reacquired':True}
            assert state['writes']==before==1 and state['connections']==2
            cases.append('new_actual_gateway_process_reacquires_kernel_lease_and_preserves_writing_intent_as_uncertain_without_resend')
        finally:
            for child in children:
                if child.returncode is None:child.kill();await child.wait()
            for writer in list(state['writers']):writer.close()
            listener.close();await listener.wait_closed()
            if state['tasks']:await asyncio.gather(*list(state['tasks']),return_exceptions=True)
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uid_cases':[0,65533,65534],
        'actual_sigkill':True,'tls_verification_disabled':False,'public_gateway_enabled':False,
        'external_connections_or_recipient_acceptance':False,'installed_haos_accepted':False},indent=2))


if __name__=='__main__':main()
