"""Actual private Feishu UID/process/TLS boundaries in a fresh disposable namespace."""
import json
import os
from pathlib import Path
import shutil
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
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def reply(self,status,body):
            raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_POST(self):
            assert self.path=='/open-apis/auth/v3/tenant_access_token/internal'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
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
            self.reply(200,{'code':0,'bot':{'open_id':bot}})
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
        # Root must never invoke this gateway-only worker directly, even with valid input.
        before=len(seen)
        direct=subprocess.run([python,'-E','-s','-m','haos.gateway_feishu_worker'],input=b'{}\n',capture_output=True,
            cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin'},timeout=10)
        assert direct.returncode!=0 and len(seen)==before
        cases.append('actual_root_identity_is_refused_before_worker_reads_or_network')
    finally:
        release.set()
        for child in children:
            if child.poll() is None:child.kill();child.communicate(timeout=10)
        server.shutdown();server.server_close();thread.join(timeout=5)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_uids':[0,65533,65534],
        'actual_native_SDK_verified_TLS_private_process_and_kernel_termination':True,
        'fixed_API_domain_redirected_only_by_disposable_container_hosts':True,
        'owner_publication_and_account_are_fixtures':True,'public_feishu_enabled':False,
        'external_messages_live_account_or_installed_acceptance':False},indent=2))


if __name__=='__main__':main()
