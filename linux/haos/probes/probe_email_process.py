"""Disposable real-UID native mail worker probe, revocation, cancellation and deadline."""
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import time


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_EMAIL_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists() or Path('/etc/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable mail Docker namespace required; never run on installed HAOS')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_EMAIL_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':raise PermissionError('pinned public mail runtime required')
    staged=Path(tempfile.mkdtemp(prefix='haos-email-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py',str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/mail_fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable private mail identity:/nonexistent:/usr/sbin/nologin\n')
    state=Path('/var/lib/haos-gateway');state.mkdir(mode=0o700);os.chown(state,65534,65534)
    directory=Path(tempfile.mkdtemp(prefix='haos-email-process-'));directory.chmod(0o755)
    sys.path[:0]=['/deps',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    create(directory,'mail.fixture.invalid')
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write(b'\n'+(directory/'ca.pem').read_bytes())
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(directory/'certificate.pem',directory/'key.pem')
    owner=directory/'owner-secret';owner.write_text('private-root-owner-canary');owner.chmod(0o600)
    secret=state/'account-secret';secret.write_text('private-email-fixture');secret.chmod(0o600);os.chown(secret,65534,65534)
    script=directory/'parent.py'
    script.write_text('''
import asyncio,hashlib,json,os,sys
from pathlib import Path
request=json.loads(sys.stdin.readline())
assert os.getgroups()==[]
try:Path(request['owner_canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged identity read owner data')
if request['action']=='agent':
    assert os.geteuid()==65533 and set(request)=={'action','owner_canary','private_secret','worker_pid','parent_pid'}
    for path in [request['private_secret'],'/proc/'+str(request['worker_pid'])+'/fd/0','/proc/'+str(request['parent_pid'])+'/environ']:
        try:Path(path).read_bytes()
        except PermissionError:continue
        raise AssertionError('agent accessed private credential or process channel')
    print(json.dumps({'agent_private_data_denied':True,'credential_payload_absent':True}));sys.exit(0)
assert os.geteuid()==65534
from haos.gateway_email_process import probe,headers,search
if request['action'] in {'revoke','cancel','deadline'}:
    original_spawn=asyncio.create_subprocess_exec
    async def observed_spawn(*args,**kwargs):
        process=await original_spawn(*args,**kwargs)
        print(json.dumps({'actual_worker_pid':process.pid}),flush=True)
        return process
    asyncio.create_subprocess_exec=observed_spawn
async def exercise():
    operation=(headers(request['credentials'],'email',lambda:None,9,77) if request['action']=='headers'
        else search(request['credentials'],'email',lambda:None,{'uid_validity':77,'after':0,'through':9}) if request['action']=='search'
        else probe(request['credentials'],'email',lambda:None))
    job=asyncio.create_task(operation)
    if request['action']=='cancel':
        assert await asyncio.to_thread(sys.stdin.readline)=='CANCEL\\n'
        job.cancel()
        try:await job
        except asyncio.CancelledError:print(json.dumps({'cancelled_and_joined':True}))
        else:raise AssertionError('mail cancellation ignored')
        return
    try:result=await job
    except PermissionError:result={'owner_revocation_refused':True}
    except ConnectionError:result={'private_worker_unavailable':True}
    if 'content' in result:result['content_sha256']=hashlib.sha256(result.pop('content')).hexdigest()
    print(json.dumps(result))
asyncio.run(exercise())
''');script.chmod(0o644)
    config=Path('/etc/haos');config.mkdir(mode=0o755)
    active=asyncio.Event();closed=asyncio.Event();mode=['success'];verbs=[];cases=[]
    header=b'From: owner@example.invalid\r\nMessage-ID: <mail-9@example.invalid>\r\nDate: Fri, 1 Jan 1999 00:00:00 +0000\r\nAuthentication-Results: mx.example.invalid; dmarc=pass\r\n\r\n'
    async def imap(reader,writer):
        active.set()
        try:
            if mode[0]=='stall':
                assert await reader.read()==b'';return
            writer.write(b'* OK disposable private IMAP\r\n');await writer.drain()
            while line:=await reader.readline():
                pieces=line.split();tag,verb=pieces[:2];verbs.append(('imap',verb.decode()))
                if verb==b'CAPABILITY':writer.write(b'* CAPABILITY IMAP4rev1\r\n'+tag+b' OK capabilities\r\n')
                elif verb==b'LOGIN':writer.write(tag+b' OK authenticated\r\n')
                elif verb==b'EXAMINE':writer.write(b'* 0 EXISTS\r\n* OK [UIDVALIDITY 77] stable\r\n* OK [UIDNEXT '+(b'10' if mode[0] in {'headers','search'} else b'3')+b'] next\r\n'+tag+b' OK [READ-ONLY] selected\r\n')
                elif verb==b'UID':
                    if mode[0]=='search':
                        assert b'UID SEARCH UID 1:9 SINCE 31-Dec-1969' in line
                        writer.write(b'* SEARCH 9 1 3\r\n'+tag+b' OK searched\r\n')
                    else:
                        assert b'UID FETCH 9 (UID INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER])' in line
                        writer.write(b'* 1 FETCH (UID 9 INTERNALDATE "28-Oct-2026 13:00:00 +0200" RFC822.SIZE 1000 BODY[HEADER] {'+str(len(header)).encode()+b'}\r\n'+header+b')\r\n'+tag+b' OK fetched\r\n')
                else:raise AssertionError('mail worker attempted unsupported remote command')
                await writer.drain()
        except (ConnectionError,ssl.SSLError):pass
        finally:
            closed.set();writer.close()
            try:await writer.wait_closed()
            except (ConnectionError,ssl.SSLError):pass
    async def smtp(reader,writer):
        try:
            writer.write(b'220 localhost private SMTP fixture\r\n');await writer.drain()
            while line:=await reader.readline():
                verb=line.split()[0].upper();verbs.append(('smtp',verb.decode()))
                if verb==b'EHLO':writer.write(b'250-localhost\r\n250 AUTH PLAIN\r\n')
                elif verb==b'AUTH':
                    assert base64.b64decode(line.split()[2])==b'\0haos@example.invalid\0private-email-fixture'
                    writer.write(b'235 2.7.0 authenticated\r\n')
                else:raise AssertionError('mail probe attempted message delivery')
                await writer.drain()
        except (ConnectionError,ssl.SSLError):pass
        finally:
            writer.close()
            try:await writer.wait_closed()
            except (ConnectionError,ssl.SSLError):pass
    async def exercise():
        imap_server=await asyncio.start_server(imap,'127.0.0.1',0,ssl=tls)
        smtp_server=await asyncio.start_server(smtp,'127.0.0.1',0,ssl=tls)
        value={'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'localhost',
            'imap_port':imap_server.sockets[0].getsockname()[1],'imap_security':'tls','smtp_host':'localhost',
            'smtp_port':smtp_server.sockets[0].getsockname()[1],'smtp_security':'tls','authserv_id':'mx.example.invalid'}
        from haos.gateway_email import scope
        policy={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[{
            'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid','scope':scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
        def publish():
            temporary=config/'next.json';temporary.write_text(json.dumps(policy));temporary.chmod(0o644);temporary.replace(config/'gateways.json')
        publish()
        async def invoke(uid,action,**extra):
            child=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),str(script),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=uid,group=uid,extra_groups=[],umask=0o077,cwd=str(code),
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
            request={'action':action,'owner_canary':str(owner)}
            request.update(extra if action=='agent' else {'credentials':value})
            child.stdin.write((json.dumps(request)+'\n').encode());await child.stdin.drain();return child
        children=[]
        async def worker(child):
            line=await asyncio.wait_for(child.stdout.readline(),10)
            if not line:
                stdout,stderr=await child.communicate()
                raise AssertionError('private mail parent failed before real worker observation: '+stderr.decode()[-2000:])
            value=json.loads(line)
            assert set(value)=={'actual_worker_pid'} and type(value['actual_worker_pid']) is int
            return value['actual_worker_pid']
        async def finish(child):
            stdout,stderr=await asyncio.wait_for(child.communicate(),40)
            assert child.returncode==0,stderr.decode()[-2500:]
            return json.loads(stdout)
        try:
            child=await invoke(65534,'probe');children.append(child);result=await finish(child)
            assert result=={'imap_authenticated':True,'smtp_authenticated':True,'uid_validity':77,'uid_next':3,'smtp_message_sent':False}
            cases.append('actual_gateway_uid_private_worker_imports_root_owned_runtime_and_authenticates_native_verified_tls_without_sending')
            mode[0]='headers';header_child=await invoke(65534,'headers');children.append(header_child)
            result=await finish(header_child)
            assert result['uid']==9 and result['uid_validity']==77 and result['uid_next']==10
            assert result['content_sha256']==__import__('hashlib').sha256(header).hexdigest() and result['size']==1000
            cases.append('actual_gateway_uid_worker_transfers_exact_bounded_header_bytes_with_same_connection_uidvalidity_and_internaldate')
            mode[0]='search';search_child=await invoke(65534,'search');children.append(search_child)
            assert await finish(search_child)=={'uid_validity':77,'uid_next':10,'after':0,'through':9,'uids':[1,3,9]}
            cases.append('actual_gateway_uid_worker_search_uses_current_root_grant_date_and_returns_all_sorted_bounded_uid_resources')
            mode[0]='success'
            denied=await asyncio.create_subprocess_exec(str(runtime/'bin/python'),'-E','-s','-m','haos.gateway_email_worker',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                user=65533,group=65533,extra_groups=[],cwd=str(code),
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
            children.append(denied);before=len(verbs)
            stdout,stderr=await asyncio.wait_for(denied.communicate(b'{}'),10)
            assert denied.returncode!=0 and not stdout and b'gateway runtime requires its unprivileged service UID/GID' in stderr
            assert len(verbs)==before
            cases.append('actual_agent_uid_cannot_invoke_the_private_worker_even_with_direct_installed_module_execution')
            for action in ['revoke','cancel','deadline']:
                active.clear();closed.clear();mode[0]='stall';started=time.monotonic()
                child=await invoke(65534,action);children.append(child)
                pid=await worker(child);await asyncio.wait_for(active.wait(),10)
                assert Path('/proc',str(pid)).stat().st_uid==65534
                if action=='revoke':
                    agent=await invoke(65533,'agent',private_secret=str(secret),worker_pid=pid,parent_pid=child.pid);children.append(agent)
                    assert await finish(agent)=={'agent_private_data_denied':True,'credential_payload_absent':True}
                    cases.append('actual_agent_uid_receives_no_credentials_and_cannot_read_private_secret_stdin_or_process_environment')
                    policy['bindings'][0]['generation']='c'*64;publish()
                    assert await finish(child)=={'owner_revocation_refused':True}
                    cases.append('actual_root_policy_change_kills_and_joins_blocked_native_worker_during_imap_greeting')
                elif action=='cancel':
                    child.stdin.write(b'CANCEL\n');await child.stdin.drain()
                    assert await finish(child)=={'cancelled_and_joined':True}
                    cases.append('actual_parent_cancellation_kills_and_joins_blocked_private_worker_before_returning')
                else:
                    assert await finish(child)=={'private_worker_unavailable':True}
                    elapsed=time.monotonic()-started;assert 25<elapsed<38,elapsed
                    cases.append('actual_worker_hard_deadline_terminates_blocking_native_constructor_and_parent_joins_it')
                assert not Path('/proc',str(pid)).exists()
                await asyncio.wait_for(closed.wait(),5)
                assert not any(verb in {'MAIL','RCPT','DATA','STORE','EXPUNGE','CLOSE'} for protocol,verb in verbs)
        finally:
            for child in children:
                if child.returncode is None:child.kill();await child.wait()
            imap_server.close();smtp_server.close();await imap_server.wait_closed();await smtp_server.wait_closed()
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65533,65534],
        'actual_private_subprocess_and_kernel_termination':True,'actual_native_clients_and_verified_tls':True,
        'loopback_account_and_root_publication_are_fixtures':True,'public_email_gateway_enabled':False,
        'external_email_accounts_or_delivery_or_installed_acceptance':False},indent=2))


if __name__=='__main__':main()
