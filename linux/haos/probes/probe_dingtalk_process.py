"""Real UID/TLS/native SDK no-send action in a guarded offline namespace."""
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_DINGTALK_PROCESS')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline DingTalk process namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755);installer='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,installer,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,installer,'/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_DINGTALK_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':raise PermissionError('pinned public source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-dingtalk-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,installer,str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/dingtalk_fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-dingtalk-process-'));work.chmod(0o755)
    sys.path[:0]=['/deps',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    create(work,'api.dingtalk.com')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 api.dingtalk.com\n')
    value={'client_id':'ding_private_fixture_app','client_secret':'private-dingtalk-process-fixture',
        'corp_id':'ding_fixture_corporation','robot_code':'ding_fixture_robot'}
    config=Path('/etc/haos');config.mkdir(mode=0o755)
    policy={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[{
        'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1}]}
    def publish(data):
        PreparedDingTalkPolicy(data);path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(config/'gateways.json')
    publish(policy)
    account=base/'account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    canary=work/'owner-secret';canary.write_text('root-only-disposable-owner-evidence');canary.chmod(0o600)
    entered=threading.Event();release=threading.Event();seen=[];state={'mode':'ok'}
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def do_POST(self):
            assert self.path=='/v1.0/oauth2/accessToken'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body=={'appKey':value['client_id'],'appSecret':value['client_secret']}
            assert self.headers.get('Accept-Encoding')=='identity';seen.append('token')
            mode=state['mode']
            if mode=='block':entered.set();release.wait(30)
            status=int(mode) if mode in {'401','429'} else 200
            data=json.dumps({'accessToken':'private-dingtalk-process-token','expireIn':7200}).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(50000 if mode=='dribble' else len(data)));self.end_headers()
            try:
                if mode=='dribble':
                    entered.set()
                    for _ in range(50000):self.wfile.write(b' ');self.wfile.flush();time.sleep(.1)
                else:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
    server=Server(('127.0.0.1',443),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(work/'certificate.pem',work/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    script=work/'gateway_fixture.py';script.write_text('''
import asyncio,json,os,sys
from pathlib import Path
from haos.gateway_dingtalk import authority
from haos.gateway_dingtalk_process import account
async def main():
    mode=sys.argv[2]
    if mode=='denied':
        try:await account({},'dingtalk',lambda:None)
        except PermissionError:print(json.dumps({'identity_denied':True}));return
        else:raise AssertionError('wrong UID invoked private SDK worker')
    assert os.geteuid()==65534 and os.getegid()==65534 and os.getgroups()==[]
    try:Path(sys.argv[3]).read_bytes()
    except PermissionError:pass
    else:raise AssertionError('gateway read owner canary')
    value=json.loads(Path(sys.argv[1]).read_text())
    task=asyncio.create_task(account(value,'dingtalk',lambda:authority('dingtalk',value)))
    if mode=='cancel':
        await asyncio.get_running_loop().run_in_executor(None,sys.stdin.readline);task.cancel()
    try:result=await task
    except (asyncio.CancelledError,PermissionError):
        assert mode in {'cancel','revoke'};print(json.dumps({'stopped':True}));return
    except RuntimeError:
        assert mode=='deadline';print(json.dumps({'hard_deadline':True}));return
    if mode in {'401','429'}:assert result=={'error':'authentication-refused' if mode=='401' else 'rate-limited'}
    else:assert result['app_authenticated'] and result['corp_identity_verified'] is False and result['robot_identity_verified'] is False and result['message_sent'] is False
    print(json.dumps(result))
asyncio.run(main())
''');script.chmod(0o644)
    children=[];cases=[]
    def start(mode,uid=65534):
        child=subprocess.Popen([str(runtime/'bin/python'),'-E','-s',str(script),str(account),mode,str(canary)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,user=uid,group=uid,extra_groups=[],umask=0o077,
            cwd=code,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HERMES_SAFE_MODE':'1'})
        children.append(child);return child
    def finish(child,timeout=40):
        out,err=child.communicate(timeout=timeout);assert child.returncode==0,err[-2000:]
        assert value['client_secret'].encode() not in out+err and b'private-dingtalk-process-token' not in out+err
        return json.loads(out)
    def worker(parent):
        matches=[]
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():continue
            try:
                fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                uid=int(next(line for line in (entry/'status').read_text().splitlines() if line.startswith('Uid:')).split()[1])
            except (FileNotFoundError,ProcessLookupError):continue
            if int(fields[1])==parent and uid==65534:matches.append(int(entry.name))
        assert len(matches)==1,matches;return matches[0]
    def gone(pid):
        deadline=time.monotonic()+5
        while Path('/proc',str(pid)).exists():
            assert time.monotonic()<deadline,'private SDK worker survived termination';time.sleep(.02)
    try:
        for uid in [0,65533]:
            before=len(seen);assert finish(start('denied',uid))=={'identity_denied':True} and len(seen)==before
            cases.append('actual_'+str(uid)+'_UID_denied_before_credentials_or_private_SDK_request')
        for mode in ['ok','401','429']:
            state['mode']=mode;before=len(seen);result=finish(start(mode));assert len(seen)==before+1
            if mode=='ok':assert result['account_scope']==scope(value)
            cases.append('actual_gateway_UID_native_Hermes_and_SDK_verified_TLS_'+mode+'_no_send_result_without_secret_or_false_corporation_robot_claim')
        for mode in ['cancel','revoke']:
            state['mode']='block';entered.clear();release.clear();publish(policy);child=start(mode);assert entered.wait(30)
            pid=worker(child.pid)
            agent_code='''
import json,sys
from pathlib import Path
for path in json.load(sys.stdin):
    try:Path(path).read_bytes()
    except (PermissionError,FileNotFoundError):pass
    else:raise AssertionError('agent read private gateway credential or worker input')
print('denied')
'''
            agent=subprocess.run([sys.executable,'-c',agent_code],input=json.dumps([str(account),str(canary),'/proc/'+str(pid)+'/fd/0']),
                text=True,capture_output=True,user=65533,group=65533,extra_groups=[],timeout=5)
            assert agent.returncode==0 and agent.stdout=='denied\n',agent.stderr
            start_time=time.monotonic()
            if mode=='cancel':child.stdin.write(b'cancel\n');child.stdin.flush()
            else:publish({**policy,'bindings':[]})
            assert finish(child,5)=={'stopped':True} and time.monotonic()-start_time<5
            gone(pid);release.set();cases.append('actual_'+mode+'_kills_and_joins_private_credential_bearing_worker_while_agent_cannot_read_input_or_owner_data')
        publish(policy);state['mode']='block';entered.clear();release.clear();child=start('ok');assert entered.wait(30);pid=worker(child.pid)
        child.kill();child.communicate(timeout=5);release.set()
        deadline=time.monotonic()+5
        while True:
            result,status=os.waitpid(pid,os.WNOHANG)
            if result:assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;break
            assert time.monotonic()<deadline,'orphan private SDK worker was not killed by parent death';time.sleep(.02)
        cases.append('actual_parent_SIGKILL_triggers_kernel_worker_parent_death_SIGKILL_and_reaping')
        state['mode']='dribble';entered.clear();child=start('deadline');assert entered.wait(30)
        pid=worker(child.pid);assert finish(child,35)=={'hard_deadline':True};gone(pid)
        cases.append('actual_native_SDK_dribbling_HTTP_cannot_outlive_real_30_second_worker_alarm')
    finally:
        release.set()
        for child in children:
            if child.poll() is None:child.kill();child.communicate(timeout=5)
        server.shutdown();server.server_close();thread.join(timeout=5)
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_UIDs':[0,65533,65534],
        'actual_Hermes_SDK_TLS_parent_lifetime_and_kernel_permissions':True,'API_domain_loopback_only_in_fixture_hosts':True,
        'owner_publication_and_service_manager_are_fixtures':True,'live_or_installed_dingtalk_acceptance':False,
        'real_external_account_messages_or_installed_acceptance':False},indent=2))


if __name__=='__main__':main()
