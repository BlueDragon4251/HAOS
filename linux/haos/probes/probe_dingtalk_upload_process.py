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
            or os.environ.get('HAOS_DISPOSABLE_DINGTALK_UPLOAD_PROCESS')!='1' or Path('/usr/lib/haos').exists()
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
    value['reply_mode']='robot'
    config=Path('/etc/haos');config.mkdir(mode=0o755)
    policy={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[{
        'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'allow_outbound_media':True,'allow_voice':True,'allow_video':True,'generation':'a'*64,'since':1}]}
    def publish(data):
        PreparedDingTalkPolicy(data);path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(config/'gateways.json')
    publish(policy)
    account=base/'account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    canary=work/'owner-secret';canary.write_text('root-only-disposable-owner-evidence');canary.chmod(0o600)
    import base64,hashlib
    from haos.gateway import digest
    from email.parser import BytesParser
    from email.policy import default
    other=work/'upload';other.mkdir();create(other,'oapi.dingtalk.com')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(other/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 oapi.dingtalk.com\n')
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6p9sAAAAASUVORK5CYII=')
    binding=policy['bindings'][0];now=int(time.time()*1000)
    original={'msgId':'native-source-fixture','createAt':now-1000,'senderId':binding['sender'],
        'senderStaffId':'native-approved-staff','senderCorpId':value['corp_id'],'chatbotCorpId':value['corp_id'],
        'robotCode':value['robot_code'],'conversationId':binding['chat'],'conversationType':'1',
        'msgtype':'text','text':{'content':'Approved sealed output source.'}}
    raw=json.dumps(original).encode()
    item={'binding_id':'owner','binding_digest':digest(binding),'delivery_id':'b'*64,'attempt':1,
        'source_id':original['msgId'],'source_sha256':hashlib.sha256(raw).hexdigest(),'source_base64':base64.b64encode(raw).decode(),
        'output':{'id':'c'*64,'kind':'image','name':'result-0.png','mime':'image/png','size':len(png),'sha256':hashlib.sha256(png).hexdigest()}}
    payload=base/'upload-fixture.json'
    payload.write_text(json.dumps({'value':value,'item':item,'data':base64.b64encode(png).decode(),'canary':str(canary)}))
    payload.chmod(0o600);os.chown(payload,65534,65534)
    entered=threading.Event();release=threading.Event();seen=[];tokens=[];failures=[];state={'mode':'ok'}
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        def handle_error(self,*_args):
            import traceback
            error=sys.exc_info();failures.append({'mode':state['mode'],'type':error[0].__name__,'line':traceback.extract_tb(error[2])[-1].lineno})
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def do_POST(self):
            data=self.rfile.read(int(self.headers['Content-Length']))
            assert self.headers.get('Cookie') is None and self.headers['Accept-Encoding']=='identity'
            if self.path=='/v1.0/oauth2/accessToken':
                assert json.loads(data)=={'appKey':value['client_id'],'appSecret':value['client_secret']}
                tokens.append('native-token')
                result={'accessToken':'private-process-upload-token','expireIn':7200};mode='ok'
            else:
                assert self.path=='/media/upload?access_token=private-process-upload-token'
                assert self.headers['Host']=='oapi.dingtalk.com'
                message=BytesParser(policy=default).parsebytes(b'Content-Type: '+self.headers['Content-Type'].encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+data)
                parts=list(message.iter_parts());assert len(parts)==2
                assert parts[0].get_param('name',header='content-disposition')=='type' and parts[0].get_payload(decode=True)==b'image'
                assert parts[1].get_param('name',header='content-disposition')=='media' and parts[1].get_filename()=='result-0.png'
                assert parts[1].get_content_type()=='image/png' and parts[1].get_payload(decode=True)==png
                mode=state['mode'];seen.append(mode)
                if mode in {'cancel','revoke','orphan'}:
                    waiter=release;entered.set();assert waiter.wait(20)
                if mode=='drop':self.close_connection=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                result={'errcode':0,'errmsg':'ok','type':'image','media_id':'$fixtureNativeUploadedImage','created_at':int(time.time()*1000)}
            data=json.dumps(result).encode();status=int(mode) if mode in {'401','429','302'} else 200
            try:
                self.send_response(status);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(50000 if mode=='deadline' else len(data)))
                self.send_header('Connection','close');self.send_header('Set-Cookie','fixture-only=never-forwarded')
                if mode=='429':self.send_header('Retry-After','120')
                if mode=='302':self.send_header('Location','https://unreviewed.invalid/never')
                self.end_headers()
                if mode=='deadline':
                    entered.set()
                    for _ in range(50000):self.wfile.write(b' ');self.wfile.flush();time.sleep(.1)
                else:self.wfile.write(data);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
    server=Server(('127.0.0.1',443),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(work/'certificate.pem',work/'key.pem')
    upload_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);upload_tls.load_cert_chain(other/'certificate.pem',other/'key.pem')
    def choose(sock,name,_context):
        if name=='oapi.dingtalk.com':sock.context=upload_tls
    tls.set_servername_callback(choose);server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    script=work/'gateway_fixture.py';script.write_text('''
import asyncio,base64,json,sys
from pathlib import Path
from haos.gateway_runtime import require_runtime_identity
require_runtime_identity()
from haos.gateway_dingtalk import authority
from haos.gateway_dingtalk_upload_process import upload
payload=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2];value=payload['value']
try:Path(payload['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway read owner secret')
publication=authority('dingtalk',value)
def current():authority('dingtalk',value,publication)
async def main():
    task=asyncio.create_task(upload(value,'dingtalk',current,payload['item'],base64.b64decode(payload['data'])))
    if mode=='cancel':
        await asyncio.to_thread(sys.stdin.readline);task.cancel()
    try:result=await task
    except asyncio.CancelledError:
        assert mode=='cancel';result={'cancelled':True}
    except PermissionError:
        assert mode=='revoke';result={'revoked':True}
    except ConnectionError:
        assert mode=='deadline';result={'deadline':True}
    print(json.dumps(result),flush=True)
asyncio.run(main())
''');script.chmod(0o644)
    cases=[];children=[]
    def start(mode,uid=65534):
        child=subprocess.Popen([str(runtime/'bin/python'),'-E','-s',str(script),str(payload),mode],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,user=uid,group=uid,extra_groups=[],
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(base),'HERMES_SAFE_MODE':'1'},text=True)
        children.append(child);return child
    def workers(parent):
        result=[]
        for path in Path('/proc').iterdir():
            if not path.name.isdecimal():continue
            try:
                fields=dict(line.split(':',1) for line in (path/'status').read_text().splitlines() if ':' in line)
                if int(fields['PPid'])==parent and fields['Uid'].split()[0]=='65534':result.append(int(path.name))
            except (FileNotFoundError,ProcessLookupError):pass
        return result
    try:
        for uid in [0,65533]:
            child=start('ok',uid);out,err=child.communicate(timeout=10)
            assert child.returncode!=0 and not out and not seen
            cases.append('actual_'+str(uid)+'_UID_denied_before_private_upload')
        from copy import deepcopy
        saved=json.loads(payload.read_text())
        for case in ['create-only','no-output-consent','wrong-source-hash','changed-bytes','session-mode','staff-alias-authority','oversize-bytes']:
            selected=deepcopy(policy);given=deepcopy(saved)
            if case=='create-only':selected['bindings'][0]['capabilities']=['create'];selected['bindings'][0]['allow_outbound_media']=False
            if case=='no-output-consent':selected['bindings'][0]['allow_outbound_media']=False
            if case=='wrong-source-hash':given['item']['source_sha256']='0'*64
            if case=='changed-bytes':given['data']=base64.b64encode(png+b'changed').decode()
            if case=='oversize-bytes':given['data']=base64.b64encode(bytes(8*1024*1024+1)).decode()
            if case=='session-mode':given['value'].pop('reply_mode')
            if case=='staff-alias-authority':selected['bindings'][0]['sender']='native-approved-staff'
            given['item']['binding_digest']=digest(selected['bindings'][0])
            publish(selected);payload.write_text(json.dumps(given));payload.chmod(0o600);os.chown(payload,65534,65534)
            before=len(seen);before_tokens=len(tokens);child=start('refused-source');out,err=child.communicate(timeout=15)
            assert child.returncode!=0 and not out and len(seen)==before and len(tokens)==before_tokens
            cases.append('actual_private_UID_'+case+'_refused_before_token_or_upload')
        publish(policy);payload.write_text(json.dumps(saved));payload.chmod(0o600);os.chown(payload,65534,65534)
        for mode in ['ok','401','429','302','drop']:
            state['mode']=mode;before=len(seen);child=start(mode);out,err=child.communicate(timeout=35)
            assert child.returncode==0,(out,err);result=json.loads(out)
            assert len(seen)==before+1 and not workers(child.pid)
            if mode=='ok':assert result['state']=='confirmed' and result['media_id']=='$fixtureNativeUploadedImage'
            elif mode in {'401','429'}:assert result=={'state':'rejected','error':'authentication-refused' if mode=='401' else 'rate-limited','retry_after':120 if mode=='429' else 0}
            else:assert result=={'state':'uncertain'}
            assert value['client_secret'] not in err and 'private-process-upload-token' not in err
            cases.append('actual_gateway_UID_Hermes_token_Stream_SDK_multipart_verified_TLS_'+mode+'_finite_result_one_upload_no_hidden_retry')
        for mode in ['cancel','revoke','orphan','deadline']:
            publish(policy);state['mode']=mode;entered.clear();release=threading.Event();before=len(seen);child=start(mode)
            assert entered.wait(20);active=workers(child.pid);assert len(active)==1
            began=time.monotonic()
            if mode=='orphan':
                child.kill();child.wait(timeout=5);pid=active[0];deadline=time.monotonic()+5
                while True:
                    found,status=os.waitpid(pid,os.WNOHANG)
                    if found:assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==9;break
                    assert time.monotonic()<deadline;time.sleep(.02)
            else:
                if mode=='cancel':child.stdin.write('cancel\n');child.stdin.flush()
                if mode=='revoke':publish({**policy,'bindings':[]})
                out,err=child.communicate(timeout=35 if mode=='deadline' else 5)
                assert child.returncode==0 and json.loads(out)=={ {'cancel':'cancelled','revoke':'revoked','deadline':'deadline'}[mode]:True},(out,err)
                assert not workers(child.pid)
                if mode=='deadline':assert 20<time.monotonic()-began<35
            release.set();assert len(seen)==before+1
            cases.append('actual_private_upload_'+mode+'_kernel_worker_terminated_and_joined_without_another_upload')
        assert not failures,failures
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_UIDs':[0,65533,65534],
            'API_and_upload_domains_distinct_verified_TLS_origins':True,'network_none_fixture_hosts_only':True,
            'policy_source_output_and_owner_are_fixtures':True,'public_dingtalk_enabled':False,
            'parent_journal_controller_artifact_handoff_outbound_message_live_or_installed_acceptance':False}))
    finally:
        release.set()
        for child in children:
            if child.poll() is None:child.kill();child.wait(timeout=5)
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':main()
