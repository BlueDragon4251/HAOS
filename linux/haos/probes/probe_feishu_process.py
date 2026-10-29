"""Actual private Feishu UID/process/TLS boundaries in a fresh disposable namespace."""
import json
import os
from pathlib import Path
import shutil
import socket
import http.client
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_FEISHU_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists() or Path('/etc/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit disposable Feishu Docker namespace required; never installed HAOS')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    install='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,install,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,install,'/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_FEISHU_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':
        raise PermissionError('pinned public source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-feishu-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,install,str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/feishu_fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable private Feishu identity:/nonexistent:/usr/sbin/nologin\n')
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-feishu-process-'));work.chmod(0o755)
    sys.path[:0]=['/deps',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    create(work,'open.feishu.cn')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    # Fixed production domain is resolved to loopback ONLY in this network-none container.
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 open.feishu.cn\n')
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-process-fixture',
        'domain':'feishu','tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    policy={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[
        {'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':123,'require_mention':True}]}
    config=Path('/etc/haos');config.mkdir(mode=0o755);policy_path=config/'gateways.json'
    def publish(data):
        PreparedFeishuPolicy(data)
        path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(policy_path)
    publish(policy)
    owner=work/'owner-secret';owner.write_text('root-only-owner-canary');owner.chmod(0o600)
    private=base/'secret';private.write_text(value['app_secret']);private.chmod(0o600);os.chown(private,65534,65534)
    marker=work/'request-started';state={'mode':'ok'};seen=[];entered=threading.Event();release=threading.Event();closed=threading.Event()
    write_entered=threading.Event();write_release=threading.Event();write_closed=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def reply(self,status,body):
            raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/reply'):
                assert self.path=='/open-apis/im/v1/messages/om_'+'f'*32+'/reply'
                assert self.headers['Authorization']=='Bearer fixture-private-process-token'
                assert body['reply_in_thread'] is False and body['msg_type']=='text'
                assert len(body['uuid'])==32 and set(body)=={'content','msg_type','reply_in_thread','uuid'}
                assert json.loads(body['content'])['text'] in {'Actual private native reply.','Uncertain private native reply.'}
                seen.append('reply')
                if state['mode']=='blockwrite':
                    write_entered.set();write_release.wait(20)
                    try:self.reply(200,{'code':0,'data':{'message_id':'om_'+'d'*32,'chat_id':policy['bindings'][0]['chat']}})
                    except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
                    finally:write_closed.set()
                    return
                if state['mode']=='ratewrite':return self.reply(200,{'code':99991400,'msg':'fixture native rate limit'})
                if state['mode']=='dropwrite':
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();self.close_connection=True;return
                return self.reply(200,{'code':0,'data':{'message_id':'om_'+'d'*32,'chat_id':policy['bindings'][0]['chat']}})
            assert self.path=='/open-apis/auth/v3/tenant_access_token/internal'
            assert body=={'app_id':value['app_id'],'app_secret':value['app_secret']};seen.append('auth')
            self.reply(200,{'code':0,'tenant_access_token':'fixture-private-process-token','expire':7200})
        def do_GET(self):
            assert self.path=='/open-apis/bot/v3/info' and self.headers['Authorization']=='Bearer fixture-private-process-token'
            seen.append('bot');mode=state['mode']
            if mode=='block':
                pid=state['parent_pid']
                workers=[]
                for proc in Path('/proc').iterdir():
                    if not proc.name.isdecimal():continue
                    try:status=(proc/'status').read_text()
                    except FileNotFoundError:continue  # An unrelated process can exit during enumeration.
                    fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
                    if fields.get('PPid','').strip()==str(pid):
                        assert fields['Uid'].split()==['65534']*4
                        workers.append(int(proc.name))
                state['worker_pids']=workers
                marker.write_text('ready');marker.chmod(0o644);entered.set();release.wait(20)
            if mode in {'401','429'}:return self.reply(int(mode),{'code':0})
            bot='ou_'+'f'*32 if mode=='wrong-bot' else value['bot_open_id']
            try:self.reply(200,{'code':0,'bot':{'open_id':bot}})
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            finally:
                if mode=='block':closed.set()
    server=ThreadingHTTPServer(('127.0.0.1',443),Handler);server.daemon_threads=True
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(work/'certificate.pem',work/'key.pem')
    server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    parent=work/'parent.py'
    parent.write_text('''
import asyncio,json,os,sys
from pathlib import Path
from haos.gateway_feishu_process import account
request=json.loads(sys.stdin.readline())
assert os.getgroups()==[]
try:Path(request['owner']).read_bytes()
except PermissionError:pass
else:raise AssertionError('private gateway read root owner secret')
if request['mode']=='agent':
    assert set(request)=={'mode','owner','private','marker','channel'}
    for path in [request['private'],request['channel']]:
        try:Path(path).read_bytes()
        except PermissionError:continue
        raise AssertionError('agent read private credential/process channel')
    try:asyncio.run(account({},'feishu',lambda:None))
    except PermissionError:pass
    else:raise AssertionError('agent invoked private SDK worker')
    print(json.dumps({'agent_denied':True}));sys.exit(0)
async def run():
    if request['mode'] in {'profile','crashreply','resume-reply'}:
        from haos.gateway_feishu_profile import build
        from haos.gateway_feishu import PreparedFeishuPolicy
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.gateway_runtime import adapter_envelope
        from haos.redaction import Redactor
        from haos.sandbox import trusted_json
        policy=lambda:PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
        base=Path('/var/lib/haos-gateway');parent=base/'profiles';parent.mkdir(mode=0o700,exist_ok=True)
        inbox=NativeInbox(base/'profile-native.db',Redactor());relay=RelayInbox(base/'profile-relay.db',Redactor())
        adapter=build(request['credentials'],parent=parent,connector='feishu',policy=policy,inbox=inbox)
        def receive(event):relay.admit(policy(),'feishu',adapter_envelope(event,'feishu'));return True
        adapter.set_durable_message_handler(receive)
        try:
            try:build(request['credentials'],parent=parent,connector='feishu',policy=policy,inbox=inbox)
            except PermissionError:pass
            else:raise AssertionError('duplicate private profile lease admitted')
            assert await adapter.connect(),adapter.native_health()
            if request['mode']!='profile':
                from haos.gateway import digest
                from haos.gateway_delivery import delivery_result
                binding=policy().bindings['owner']
                metadata={'haos_binding':{'binding_id':'owner','binding_digest':digest(binding)},'haos_scope':binding['scope'],
                    'thread_id':binding['thread'],'haos_delivery_id':'e'*64,'haos_delivery_attempt':1}
                if request['mode']=='crashreply':
                    # Wait for the REAL persisted pause to expire; no clock or journal edits.
                    while adapter._haos_feishu_publisher.health()['next_attempt']>__import__('time').time():await asyncio.sleep(.2)
                    print(json.dumps({'crash_write_ready':True}),flush=True)
                    await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,metadata=metadata)
                    raise AssertionError('fixture must kill gateway before withheld write response')
                unknown=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,
                    metadata={**metadata,'haos_delivery_attempt':2})
                assert delivery_result(unknown)=={'status':'uncertain'}
                row=inbox.db.execute('SELECT state FROM feishu_delivery_intents WHERE delivery_id=?',('e'*64,)).fetchone()
                assert row['state']=='uncertain'
                confirmed=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,
                    metadata={**metadata,'haos_delivery_id':'a'*64})
                assert confirmed.success and confirmed.message_id=='om_'+'d'*32
                return {'crash_state_preserved':True,'no_resend':True,'confirmed_receipt_preserved':True}
            print(json.dumps({'profile_listening':True,'lease_denied':True}),flush=True)
            async with asyncio.timeout(20):
                while relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]!=1:await asyncio.sleep(.05)
            print(json.dumps({'profile_admitted':True,'sender':relay.next(policy())['envelope']['sender']}),flush=True)
            from haos.gateway import digest,Conflict
            from haos.gateway_feishu_delivery import Publisher
            from haos.gateway_delivery import delivery_result
            binding=policy().bindings['owner']
            metadata={'haos_binding':{'binding_id':'owner','binding_digest':digest(binding)},'haos_scope':binding['scope'],
                'thread_id':binding['thread'],'haos_delivery_id':'a'*64,'haos_delivery_attempt':1}
            async def phase(name):
                async with asyncio.timeout(20):
                    while not Path(request['command']).exists() or Path(request['command']).read_text()!=name:await asyncio.sleep(.05)
            await phase('confirmed')
            first=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,metadata=metadata)
            assert first.success and first.message_id=='om_'+'d'*32
            again=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,metadata=metadata)
            assert again.success and again.message_id==first.message_id
            try:await adapter.send(binding['chat'],'Changed body must fail.',reply_to='om_'+'f'*32,metadata=metadata)
            except Conflict:pass
            else:raise AssertionError('confirmed delivery changed its body')
            print(json.dumps({'reply_confirmed':True,'duplicate_suppressed':True,'changed_body_denied':True}),flush=True)
            await phase('uncertain')
            metadata={**metadata,'haos_delivery_id':'b'*64}
            unknown=await adapter.send(binding['chat'],'Uncertain private native reply.',reply_to='om_'+'f'*32,metadata=metadata)
            assert delivery_result(unknown)=={'status':'uncertain'}
            await adapter._haos_feishu_publisher.close()
            adapter._haos_feishu_publisher=Publisher(adapter)
            again=await adapter.send(binding['chat'],'Uncertain private native reply.',reply_to='om_'+'f'*32,
                metadata={**metadata,'haos_delivery_attempt':2})
            assert delivery_result(again)=={'status':'uncertain'}
            print(json.dumps({'reply_uncertain':True,'new_attempt_denied':True}),flush=True)
            await phase('rate-limited')
            metadata={**metadata,'haos_delivery_id':'c'*64,'haos_delivery_attempt':1}
            limited=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,metadata=metadata)
            assert delivery_result(limited)=={'status':'retry','retry_after':60}
            await adapter._haos_feishu_publisher.close();adapter._haos_feishu_publisher=Publisher(adapter)
            limited=await adapter.send(binding['chat'],'Actual private native reply.',reply_to='om_'+'f'*32,
                metadata={**metadata,'haos_delivery_id':'d'*64})
            decision=delivery_result(limited)
            assert decision['status']=='retry' and 1<=decision['retry_after']<=60
            assert adapter._haos_feishu_publisher.health()['status']=='rate-limited'
            print(json.dumps({'account_rate_limit_persisted':True,'other_delivery_deferred':True}),flush=True)
            async with asyncio.timeout(20):
                while adapter.native_health()['status']!='revoked':await asyncio.sleep(.05)
            await adapter.disconnect()
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
            return {'profile_revoked':True,'listener_stopped':adapter._haos_feishu_runner is None}
        finally:await adapter.close_profile();inbox.close();relay.close()
    task=asyncio.create_task(account(request['credentials'],'feishu',lambda:None))
    if request['mode']=='cancel':
        async with asyncio.timeout(20):
            while not Path(request['marker']).exists():await asyncio.sleep(.05)
        task.cancel()
        try:await task
        except asyncio.CancelledError:return {'cancelled':True}
        raise AssertionError('cancelled worker returned success')
    try:return await task
    except PermissionError:return {'withdrawn':True}
print(json.dumps(asyncio.run(run())))
''');parent.chmod(0o644)
    python=str(runtime/'bin/python');cases=[];children=[]
    def start(mode='account',uid=65534,**extra):
        request={'mode':mode,'credentials':value,'owner':str(owner),'private':str(private),'marker':str(marker),**extra}
        if mode=='agent':request.pop('credentials')
        def identity():os.setgroups([]);os.setgid(uid);os.setuid(uid)
        child=subprocess.Popen([python,'-E','-s',str(parent)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HERMES_SAFE_MODE':'1'},preexec_fn=identity)
        children.append(child);state['parent_pid']=child.pid;child.stdin.write((json.dumps(request)+'\n').encode());child.stdin.close();child.stdin=None
        return child
    def finish(child):
        out,err=child.communicate(timeout=40)
        assert child.returncode==0,err.decode()[-1500:]
        assert value['app_secret'].encode() not in out+err and b'fixture-private-process-token' not in out+err
        return json.loads(out)
    try:
        result=finish(start());assert 'bot_identity_verified' in result,(result,seen)
        assert result['bot_identity_verified'] and not result['tenant_identity_verified'] and not result['message_sent']
        assert result['account_scope']==scope(value) and seen==['auth','bot']
        cases.append('actual_gateway_uid_private_native_SDK_authenticates_verified_TLS_fixed_domain_without_sending')
        cases.append('no_secret_in_worker_result_and_tenant_is_not_falsely_claimed_verified')
        result=finish(start('agent',65533,channel='/proc/1/fd/0'));assert result=={'agent_denied':True} and seen==['auth','bot']
        cases.append('actual_agent_uid_cannot_read_private_credentials_owner_data_or_invoke_worker')
        for mode,kind in [('wrong-bot','identity-refused'),('401','authentication-refused'),('429','rate-limited')]:
            state['mode']=mode;assert finish(start())=={'error':kind}
            cases.append('actual_private_worker_'+mode+'_refused_without_false_success')
        for mode in ['cancel','revoke']:
            state['mode']='block';entered.clear();release.clear();closed.clear();marker.unlink(missing_ok=True)
            child=start('cancel' if mode=='cancel' else 'account')
            assert entered.wait(20)
            worker_pids=state['worker_pids']
            assert len(worker_pids)==1
            if mode=='revoke':publish({**policy,'bindings':[]})
            result=finish(child)
            assert result==({'cancelled':True} if mode=='cancel' else {'withdrawn':True})
            assert all(not Path('/proc',str(pid)).exists() for pid in worker_pids)
            release.set();assert closed.wait(5);publish(policy)
            cases.append('actual_'+mode+'_kills_and_joins_private_credential_bearing_worker')
        for attack in ['wrong-scope','own-bot','writable-policy','pending-publication']:
            altered=json.loads(json.dumps(policy))
            if attack=='wrong-scope':altered['bindings'][0]['scope']='feishu:'+'e'*64
            if attack=='own-bot':altered['bindings'][0]['sender']=value['bot_open_id']
            publish(altered)
            if attack=='writable-policy':policy_path.chmod(0o660)
            if attack=='pending-publication':(config/'gateway-publication.json').write_text('{}')
            before=len(seen);assert finish(start())=={'withdrawn':True} and len(seen)==before
            (config/'gateway-publication.json').unlink(missing_ok=True);publish(policy)
            cases.append('actual_root_'+attack+'_refused_before_private_SDK_network')
        state['mode']='block';entered.clear();release.clear();closed.clear();marker.unlink(missing_ok=True)
        child=start();assert entered.wait(20);worker_pids=state['worker_pids'];assert len(worker_pids)==1
        before=len(seen)
        assert finish(start('agent',65533,channel='/proc/'+str(worker_pids[0])+'/fd/0'))=={'agent_denied':True}
        assert len(seen)==before
        cases.append('actual_agent_uid_cannot_read_live_private_worker_input_channel_and_receives_no_credential_payload')
        child.terminate();child.communicate(timeout=10);assert child.returncode==-15
        deadline=time.monotonic()+5;reaped=False
        while time.monotonic()<deadline:
            pid,status=os.waitpid(worker_pids[0],os.WNOHANG)
            if pid:
                assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;reaped=True;break
            time.sleep(.02)
        assert reaped and not Path('/proc',str(worker_pids[0])).exists()
        release.set();assert closed.wait(5)
        cases.append('actual_parent_death_kernel_guard_SIGKILLs_credential_worker_and_disposable_init_reaps_it')
        state['mode']='ok';publish(policy)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));profile_port=reserve.getsockname()[1]
        value.update(connection_mode='webhook',verification_token='private-profile-verification-fixture',
            encrypt_key='private-profile-encryption-fixture',port=profile_port,
            tls={'public_url':'https://open.feishu.cn/feishu/webhook','certificate':(work/'certificate.pem').read_text(),
                'private_key':(work/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False})
        command=work/'send-command'
        child=start('profile',command=str(command))
        ready=json.loads(child.stdout.readline());assert ready=={'profile_listening':True,'lease_denied':True},ready
        cases.append('actual_gateway_uid_builds_leased_native_profile_and_binds_reviewed_verified_HTTPS_after_no_send_account_check')
        stamp=str(int(time.time()*1000)-1000)
        event={'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1',
            'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp,'token':value['verification_token']},
            'event':{'sender':{'sender_id':{'open_id':policy['bindings'][0]['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
                'message':{'message_id':'om_'+'f'*32,'chat_id':policy['bindings'][0]['chat'],'chat_type':'p2p',
                    'create_time':stamp,'message_type':'text','content':json.dumps({'text':'Actual private profile source.'})}}}
        raw=json.dumps(event).encode();stamp=str(int(time.time()));nonce='fixture_profile_nonce'
        import hashlib
        signature=hashlib.sha256((stamp+nonce+value['encrypt_key']).encode()+raw).hexdigest()
        head={'Content-Type':'application/json','x-lark-request-timestamp':stamp,'x-lark-request-nonce':nonce,'x-lark-signature':signature}
        trust=ssl.create_default_context(cafile=str(work/'ca.pem'))
        for attempt in range(2):
            connection=http.client.HTTPSConnection('localhost',profile_port,context=trust,timeout=10)
            try:
                connection.request('POST','/feishu/webhook',body=raw,headers=head)
                response=connection.getresponse();body=response.read(4096);assert response.status==200,(response.status,body)
            finally:connection.close()
            if attempt==0:
                admitted=json.loads(child.stdout.readline());assert admitted=={'profile_admitted':True,'sender':policy['bindings'][0]['sender']}
        cases.append('actual_gateway_uid_HTTPS_profile_durably_replays_native_message_into_relay_and_suppresses_remote_duplicate')
        before=seen.count('reply');command.write_text('confirmed');command.chmod(0o644)
        result=json.loads(child.stdout.readline());assert result=={'reply_confirmed':True,'duplicate_suppressed':True,'changed_body_denied':True}
        assert seen.count('reply')==before+1
        cases.append('actual_private_worker_native_reply_confirmation_is_durable_duplicate_suppressed_and_changed_body_denied')
        state['mode']='dropwrite';command.write_text('uncertain');command.chmod(0o644)
        result=json.loads(child.stdout.readline());assert result=={'reply_uncertain':True,'new_attempt_denied':True}
        assert seen.count('reply')==before+2
        cases.append('actual_native_reply_connection_drop_remains_uncertain_across_publisher_reopen_and_new_attempt_without_second_write')
        state['mode']='ratewrite';command.write_text('rate-limited');command.chmod(0o644)
        result=json.loads(child.stdout.readline());assert result=={'account_rate_limit_persisted':True,'other_delivery_deferred':True}
        assert seen.count('reply')==before+3
        cases.append('actual_native_HTTP_200_rate_code_persists_account_backoff_across_publisher_reopen_and_other_delivery_without_new_API_write')
        publish({**policy,'bindings':[]});result=finish(child)
        assert result=={'profile_revoked':True,'listener_stopped':True}
        cases.append('actual_root_publication_withdrawal_stops_private_HTTPS_listener_and_preserves_one_durable_input')
        publish(policy)
        state['mode']='blockwrite';write_entered.clear();write_release.clear();write_closed.clear()
        child=start('crashreply');before=seen.count('reply')
        ready=child.stdout.readline()
        if not ready:finish(child);raise AssertionError('crash fixture exited before real pause expiry')
        assert json.loads(ready)=={'crash_write_ready':True}
        if not write_entered.wait(35):
            if child.poll() is None:child.kill()
            output,error=child.communicate(timeout=10)
            from haos.redaction import Redactor
            safe=Redactor([value['app_secret'],value['verification_token'],value['encrypt_key'],value['tls']['private_key']])
            raise AssertionError('private crash fixture never reached write: '+safe.text(error.decode()[-5000:]))

        assert seen.count('reply')==before+1
        import sqlite3
        with sqlite3.connect('file:/var/lib/haos-gateway/profile-native.db?mode=ro',uri=True) as journal:
            state_before_kill=journal.execute('SELECT state FROM feishu_delivery_intents WHERE delivery_id=?',('e'*64,)).fetchone()
            assert state_before_kill==('writing',)
        cases.append('actual_readonly_journal_observes_committed_write_intent_before_withheld_native_API_response')
        workers=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdecimal():continue
            try:status=(proc/'status').read_text()
            except FileNotFoundError:continue
            fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
            if fields.get('PPid','').strip()==str(child.pid):
                assert fields['Uid'].split()==['65534']*4;workers.append(int(proc.name))
        assert len(workers)==1
        child.kill();child.communicate(timeout=10);assert child.returncode==-9
        deadline=time.monotonic()+5;reaped=False
        while time.monotonic()<deadline:
            pid,status=os.waitpid(workers[0],os.WNOHANG)
            if pid:
                assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;reaped=True;break
            time.sleep(.02)
        assert reaped and not Path('/proc',str(workers[0])).exists()
        write_release.set();assert write_closed.wait(5)
        cases.append('actual_SIGKILL_of_gateway_during_native_reply_triggers_kernel_worker_death_and_reaping')
        state['mode']='ok'
        result=finish(start('resume-reply'))
        assert result=={'crash_state_preserved':True,'no_resend':True,'confirmed_receipt_preserved':True}
        assert seen.count('reply')==before+1
        cases.append('actual_private_gateway_process_restart_quarantines_inflight_reply_and_preserves_confirmed_receipt_without_new_API_write')
        # Root must never invoke this gateway-only worker directly, even with valid input.
        before=len(seen)
        direct=subprocess.run([python,'-E','-s','-m','haos.gateway_feishu_worker'],input=b'{}\n',capture_output=True,
            cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin'},timeout=10)
        assert direct.returncode!=0 and len(seen)==before
        cases.append('actual_root_identity_is_refused_before_worker_reads_or_network')
    finally:
        release.set();write_release.set()
        for child in children:
            if child.poll() is None:child.kill();child.communicate(timeout=10)
        server.shutdown();server.server_close();thread.join(timeout=5)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65533,65534],
        'actual_native_SDK_verified_TLS_private_process_and_kernel_termination':True,
        'fixed_API_domain_redirected_only_by_disposable_container_hosts':True,
        'owner_publication_and_account_are_fixtures':True,'public_feishu_enabled':False,
        'external_messages_live_account_or_installed_acceptance':False},indent=2))


if __name__=='__main__':main()
