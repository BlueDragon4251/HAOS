"""Disposable actual-UID SMS process kill/reopen with installed public code and TLS."""
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
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_SMS_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Docker namespace required; never run on installed HAOS')
    media_mode=os.environ.get('HAOS_SMS_PROCESS_MEDIA')=='1'
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    upstream=Path(os.environ.get('HAOS_SMS_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (upstream/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':
        raise PermissionError('exact pinned public Hermes source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-sms-public-code-'))
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
    directory=Path(tempfile.mkdtemp(prefix='haos-sms-process-'));directory.chmod(0o755)
    now=datetime.datetime.now(datetime.timezone.utc)
    ca_key=ec.generate_private_key(ec.SECP256R1());ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable SMS process CA')])
    ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
        .add_extension(x509.KeyUsage(True,False,False,False,False,True,True,False,False),True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),False).sign(ca_key,hashes.SHA256()))
    leaf_key=ec.generate_private_key(ec.SECP256R1())
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'sms.fixture.invalid')]))
        .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
        .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('sms.fixture.invalid'),x509.DNSName('localhost'),
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
from haos.gateway import digest
from haos.gateway_sms import PreparedSMSPolicy
from haos.gateway_publication import validate_snapshot
def build(value,**context):return build_adapter('sms',value,sms_context=context)
from haos.gateway_runtime import build_adapter,require_runtime_identity,adapter_envelope
from haos.gateway_delivery import delivery_result
from haos.gateway_raw import NativeInbox
from haos.gateway_relay import RelayInbox
from haos.gateway_media_relay import event_media,MediaCache
from haos.redaction import Redactor
assert os.getgroups()==[]
if os.geteuid()==65534:require_runtime_identity()
request=json.loads(sys.stdin.readline())
try:Path(request['owner_canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged identity read owner material')
if request['action']=='agent':
    assert os.geteuid()==65533
    assert set(request)=={'action','state','owner_canary'}
    for name in ['native.db','relay.db']:
        try:Path(request['state'],name).read_bytes()
        except PermissionError:pass
        else:raise AssertionError('agent read private SMS journal')
    try:NativeInbox(Path(request['state'],'native.db'),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private SMS journal')
    print(json.dumps({'uid':os.geteuid(),'private_journals_denied':True,'credential_payload_absent':True}));sys.exit(0)
assert os.geteuid()==65534
validate_snapshot(request['policy'],{'connectors':{'sms':request['credentials']}})
async def exercise():
    root=Path(request['state']);inbox=NativeInbox(root/'native.db',Redactor())
    relay=RelayInbox(root/'relay.db',Redactor())
    before=inbox.db.execute('SELECT state FROM sms_delivery_intents').fetchone() if request['action']=='recover' else None
    parent=root/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
    policy=lambda:PreparedSMSPolicy(request['policy'])
    adapter=build(request['credentials'],parent=parent,connector='sms',policy=policy,inbox=inbox)
    adapter._haos_sms_rest._fixture_origin=request['api']+'/accounts/'
    adapter._haos_sms_publisher._target=request['api']+'/push'
    def receive(event):relay.admit(policy(),'sms',adapter_envelope(event,'sms'),media=event_media(event,'sms'));return True
    adapter.set_durable_message_handler(receive)
    try:
        assert await adapter.connect() and adapter.native_health()['status']=='listening-tls'
        if request['action']=='send':
            print(json.dumps({'listening':True,'uid':os.geteuid()}),flush=True)
            assert await asyncio.to_thread(sys.stdin.readline)=='SEND\\n'
        binding=request['policy']['bindings'][0]
        metadata={'haos_scope':binding['scope'],'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},
            'haos_delivery_id':digest('private-sms-process-obligation'),'haos_delivery_attempt':1,'notify':True}
        if request['media_mode']:
            from plugins.platforms.line.adapter import _FALLBACK_PNG_PREVIEW
            output=adapter._haos_sms_output
            item=output.put(binding,metadata['haos_delivery_id'],digest('process-output-fixture'),_FALLBACK_PNG_PREVIEW,'image','image/png')
            metadata['haos_output']={'items':[{'kind':'image','url':output.url(item),'duration':0}],'text':'private process reply'}
        receipt=await adapter.send(binding['chat'],'private process reply',metadata=metadata)
        result=delivery_result(receipt)
        assert result=={'status':'uncertain'}
        after=inbox.db.execute('SELECT state FROM sms_delivery_intents').fetchone()[0]
        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
        media_ids=json.loads(relay.db.execute('SELECT media FROM inbox').fetchone()[0])
        assert len(media_ids)==1 and MediaCache(inbox).get(policy(),media_ids[0])['data']==b'private retained process document'
        print(json.dumps({'uid':os.geteuid(),'prior_state':before[0] if before else None,'state':after,
            'result':result,'private_owner_denied':True,'kernel_lease_reacquired':True,'retained_relay_count':1}),flush=True)
    finally:await adapter.close_profile();relay.close();inbox.close()
asyncio.run(exercise())
''')
    script.chmod(0o644)
    state={'pushes':0,'lookups':0,'seen':asyncio.Event(),'release':asyncio.Event()};cases=[]
    async def exercise():
        user='+12025550101';account='AC'+'a'*32;number='+12025550100';destination=account+':'+number
        auth='Basic '+base64.b64encode((account+':'+'c'*32).encode()).decode()
        async def info(request):
            assert request.headers['Authorization']==auth
            state['lookups']+=1;return web.json_response({'sid':account,'status':'active'})
        async def phones(request):
            assert request.headers['Authorization']==auth and request.query['PhoneNumber']==number
            return web.json_response({'incoming_phone_numbers':[{'account_sid':account,'phone_number':number,'capabilities':{'sms':True,'mms':True}}]})
        async def resource(request):
            assert request.headers['Authorization']==auth
            from email.utils import formatdate
            return web.json_response({'sid':'MM'+'d'*32,'account_sid':account,'from':user,'to':number,'body':'',
                'direction':'inbound','status':'received','num_media':'1','date_created':formatdate(time.time()-5,usegmt=True)})
        async def media(request):
            assert request.headers['Authorization']==auth
            return web.json_response({'media_list':[{'sid':'ME'+'e'*32,'parent_sid':'MM'+'d'*32,'account_sid':account,
                'content_type':'application/pdf'}],'next_page_uri':None})
        async def push(request):
            assert request.headers['Authorization']==auth
            payload=await request.post()
            assert payload['From']==number and payload['To']==user and payload['Body']=='private process reply'
            if media_mode:
                assert len(payload.getall('MediaUrl'))==1 and payload['MediaUrl'].startswith('https://sms.fixture.invalid/sms/output/')
            else:assert set(payload)=={'From','To','Body'}
            with sqlite3.connect('file:'+str(private/'native.db')+'?mode=ro',uri=True) as observer:
                assert observer.execute('SELECT state FROM sms_delivery_intents').fetchone()==('writing',)
            state['pushes']+=1;state['seen'].set();await state['release'].wait()
            return web.json_response({'sid':'SM'+'f'*32,'account_sid':account,'from':number,'to':user,
                'body':'private process reply','status':'queued','num_media':'1' if media_mode else '0'},status=201)
        async def content(request):
            assert request.headers['Authorization']==auth
            return web.Response(body=b'private retained process document')
        app=web.Application();app.router.add_get('/accounts/{account}.json',info)
        app.router.add_get('/accounts/{account}/IncomingPhoneNumbers.json',phones)
        app.router.add_get('/accounts/{account}/Messages/{message}.json',resource)
        app.router.add_get('/accounts/{account}/Messages/{message}/Media.json',media)
        app.router.add_get('/accounts/{account}/Messages/{message}/Media/{media}',content)
        app.router.add_post('/push',push)
        runner=web.AppRunner(app,access_log=None,shutdown_timeout=2);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=tls);await site.start()
        api='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        import socket
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        request={'state':str(private),'owner_canary':str(owner),'api':api,'media_mode':media_mode,
            'credentials':{'account_sid':account,'auth_token':'c'*32,'from_number':number,'port':port,
                'tls':{'public_url':'https://sms.fixture.invalid/webhooks/twilio','certificate':chain,'private_key':private_key,
                    'bind_host':'127.0.0.1','public_listener':False}},
            'policy':{'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{
                'id':'owner','connector':'sms','sender':user,'chat':user,'scope':destination,
                'thread':'','identity':'owner','capabilities':['create','read'],'allow_media':True,'allow_outbound_media':media_mode,'generation':'a'*64,
                'since':int((time.time()-60)*1000)}]}}
        async def invoke(uid,action):
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),str(script),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=uid,group=uid,extra_groups=[],umask=0o077,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(code),
                    'PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1','HERMES_HOME':str(private/'unused-home')})
            payload=({'action':action,'state':str(private),'owner_canary':str(owner)} if action=='agent' else {**request,'action':action})
            child.stdin.write((json.dumps(payload)+'\n').encode());await child.stdin.drain()
            return child
        children=[]
        try:
            first=await invoke(65534,'send');children.append(first)
            ready=await asyncio.wait_for(first.stdout.readline(),20)
            if not ready:
                stdout,stderr=await first.communicate();raise AssertionError('actual SMS worker failed: '+stderr.decode()[-2500:])
            assert json.loads(ready)=={'listening':True,'uid':65534}
            from urllib.parse import urlencode
            fields={'AccountSid':account,'MessageSid':'MM'+'d'*32,'From':user,'To':number,'Body':'','NumMedia':'1'}
            body=urlencode(fields).encode()
            material=request['credentials']['tls']['public_url']+''.join(k+fields[k] for k in sorted(fields))
            signature=base64.b64encode(hmac.new(('c'*32).encode(),material.encode(),hashlib.sha1).digest()).decode()
            async with ClientSession(connector=TCPConnector(ssl=ssl.create_default_context())) as client:
                async with client.post(f'https://localhost:{port}/webhooks/twilio',data=body,headers={'X-Twilio-Signature':signature,'Content-Type':'application/x-www-form-urlencoded'}) as response:
                    assert response.status==200
            async with asyncio.timeout(10):
                while True:
                    with sqlite3.connect('file:'+str(private/'native.db')+'?mode=ro',uri=True) as observer:
                        row=observer.execute('SELECT state FROM native_inbox').fetchone()
                    if row==('committed',):break
                    await asyncio.sleep(.02)
            cases.append('actual_gateway_uid_verifies_https_hmac_and_native_https_document_download_before_private_media_relay_commit')
            first.stdin.write(b'SEND\n');await first.stdin.drain()
            await asyncio.wait_for(state['seen'].wait(),10)
            assert state['pushes']==1 and first.returncode is None
            if media_mode:
                import ast
                source=ast.parse((upstream/'plugins/platforms/line/adapter.py').read_text())
                declaration=next(node for node in source.body if isinstance(node,ast.Assign)
                    and any(isinstance(target,ast.Name) and target.id=='_FALLBACK_PNG_PREVIEW' for target in node.targets))
                expected_preview=bytes.fromhex(ast.literal_eval(declaration.value.args[0]))
                with sqlite3.connect('file:'+str(private/'native.db')+'?mode=ro',uri=True) as observer:
                    token=observer.execute('SELECT token FROM line_output_media').fetchone()[0]
                async with ClientSession(connector=TCPConnector(ssl=ssl.create_default_context())) as client:
                    async with client.get(f'https://localhost:{port}/sms/output/'+token) as response:
                        assert response.status==200 and await response.read()==expected_preview
                cases.append('actual_gateway_uid_serves_only_private_byte_backed_output_over_verified_https_before_crash')
            first.kill();await asyncio.wait_for(first.wait(),5);assert first.returncode==-9
            cases.append('actual_gateway_uid_native_verified_https_push_has_durable_intent_before_real_sigkill')
            agent=await invoke(65533,'agent');children.append(agent)
            stdout,stderr=await asyncio.wait_for(agent.communicate(),10)
            assert agent.returncode==0,stderr.decode()[-2500:]
            assert json.loads(stdout)=={'uid':65533,'private_journals_denied':True,'credential_payload_absent':True}
            cases.append('actual_agent_uid_receives_no_credential_payload_and_cannot_read_private_native_relay_or_owner_credentials_after_crash')
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
        'agent_fixture_received_no_credentials':True,
        'incoming_document_bytes_verified_after_process_restart':True,'outgoing_native_media_process_case':media_mode,
        'fixture_only_disposable_ca_and_loopback_targets':True,
        'external_connections_or_recipient_acceptance':False,'installed_haos_accepted':False},indent=2))


if __name__=='__main__':main()
