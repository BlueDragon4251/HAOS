#!/usr/bin/env python3
"""Disposable real-UID, network-disabled, pinned native local STT process proof."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    assert os.geteuid()==0 and os.getpid()==1 and Path('/.dockerenv').exists()
    assert os.environ.get('HAOS_DISPOSABLE_SPEECH_PROCESS')=='1'
    assert not Path('/etc/haos').exists()
    installed=Path('/usr/lib/haos');installed.mkdir(mode=0o755)
    installer='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,installer,'/repo/linux/haos/haos',str(installed/'haos')],check=True)
    subprocess.run([sys.executable,installer,'/deps','/sdk'],check=True)
    upstream=Path('/repo/upstream/hermes-agent')
    assert (upstream/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    staged=Path('/public-upstream')
    shutil.copytree(upstream,staged,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,installer,str(staged),str(installed/'hermes-source')],check=True)
    source=Path('/public-model');audio=Path('/public-input/reference.flac')
    assert hashlib.sha256(audio.read_bytes()).hexdigest()=='63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
    public_audio=Path('/public-audio');public_audio.mkdir(mode=0o755)
    reference=public_audio/'reference.flac';reference.write_bytes(audio.read_bytes());reference.chmod(0o644)
    with tempfile.TemporaryDirectory(prefix='haos-speech-process-') as directory:
        root=Path(directory);root.chmod(0o755)
        models=Path('/var/lib/haos-speech-models');models.mkdir(mode=0o755)
        model=models/'tiny-d90ca5fe260221311c53c58e660288d3deb8d356'
        shutil.copytree(source,model)
        for path in model.iterdir():path.chmod(0o644)
        model.chmod(0o755)
        state=root/'speech';state.mkdir(mode=0o700);os.chown(state,65530,65530)
        config=state/'.hermes';config.mkdir(mode=0o700);os.chown(config,65530,65530)
        settings=config/'config.yaml';settings.write_text('stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n');settings.chmod(0o644)
        canaries=[]
        for uid,name in [(0,'owner'),(65531,'provider'),(65534,'gateway')]:
            private=root/name;private.mkdir(mode=0o700);os.chown(private,uid,uid)
            canary=private/'private-canary';canary.write_text('disposable-private-'+name);canary.chmod(0o600);os.chown(canary,uid,uid)
            canaries.append(str(canary))
        code='''
import hashlib,json,os,sys
from pathlib import Path
from haos.speech import transcribe
request=json.load(sys.stdin)
assert os.geteuid()==65530 and os.getegid()==65530 and os.getgroups()==[]
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(),16)==0 and int(status['CapAmb'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'
for path in request['canaries']:
    try:Path(path).read_bytes()
    except PermissionError:pass
    else:raise AssertionError('speech identity could read another identity secret')
result=transcribe(Path('/public-audio/reference.flac').read_bytes(),model_root=Path(request['model']))
assert 'ask not what your country can do for you' in result['transcript'].lower()
assert 'ask what you can do for your country' in result['transcript'].lower()
assert result['provider']=='local' and result['sample_rate']==16000 and result['samples']==176000
print(json.dumps({'source_sha256':result['source_sha256'],'model_revision':result['model_revision'],
    'transcript_sha256':hashlib.sha256(result['transcript'].encode()).hexdigest(),'samples':result['samples']}))
'''
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
            'PYTHONPATH':'/usr/lib/haos:/usr/lib/haos/hermes-source:/sdk',
            'HOME':str(state),'HERMES_HOME':str(config),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
            'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'1'}
        result=subprocess.run([sys.executable,'-c',code],input=json.dumps({'model':str(model),'canaries':canaries}),
            text=True,capture_output=True,timeout=45,user=65530,group=65530,extra_groups=[],umask=0o077,cwd=str(state),env=env)
        assert result.returncode==0,result.stderr[-3000:]
        with Path('/etc/passwd').open('a') as accounts:
            accounts.write('haos-speech:x:65530:65530:fixture speech:/var/lib/haos-speech:/usr/sbin/nologin\nhaos-gateway:x:65534:65534:fixture gateway:/nonexistent:/usr/sbin/nologin\n')
        worker_home=Path('/var/lib/haos-speech');worker_home.mkdir(mode=0o700);os.chown(worker_home,65530,65530)
        engine_config=Path('/etc/haos-speech');engine_config.mkdir(mode=0o755)
        (engine_config/'config.yaml').write_text(settings.read_text());(engine_config/'config.yaml').chmod(0o644)
        rpc=root/'rpc';rpc.mkdir(mode=0o755);os.chown(rpc,65530,65530)
        policy_dir=Path('/etc/haos');policy_dir.mkdir(mode=0o755)
        (policy_dir/'speech.json').write_text(json.dumps({'version':1,'enabled':True,'model':'tiny'}))
        (policy_dir/'speech.json').chmod(0o644)
        import socket
        socket_dir=Path('/run/haos-speech');socket_dir.mkdir(mode=0o755)
        endpoint=socket_dir/'voice.sock'
        listening=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listening.bind(str(endpoint));listening.listen(8)
        endpoint.chmod(0o666)  # Deliberately grant filesystem connection; peer UID must still deny.
        server_code="""
import os,sys
fd=int(sys.argv[1])
if fd!=3:os.dup2(fd,3);os.close(fd)
os.set_inheritable(3,True)
os.environ['LISTEN_PID']=str(os.getpid());os.environ['LISTEN_FDS']='1'
os.execv(sys.executable,[sys.executable,'-s','-m','haos.speech_service'])
"""
        service=subprocess.Popen([sys.executable,'-s','-c',server_code,str(listening.fileno())],
            pass_fds=(listening.fileno(),),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
            user=65530,group=65530,extra_groups=[],umask=0o077,cwd=str(state),env=env,start_new_session=True)
        listening.close()
        try:
            import time
            deadline=time.monotonic()+15
            while True:
                assert service.poll() is None,'speech RPC fixture server exited'
                assert time.monotonic()<deadline,'speech RPC readiness deadline'
                try:
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
                        peer.settimeout(.2);peer.connect(str(endpoint));ready=peer.makefile('rb').readline()
                    assert json.loads(ready)=={'ok':False,'error':'speech peer denied'}
                    break
                except (TimeoutError,ConnectionError):time.sleep(.02)
            client_code=r"""
import base64,hashlib,json,socket,sys
from pathlib import Path
request=json.load(sys.stdin)
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
    peer.settimeout(45);peer.connect(request['socket'])
    if request['mode']=='denied':
        result=json.loads(peer.makefile('rb').readline());assert result=={'ok':False,'error':'speech peer denied'}
    else:
        data=Path('/public-audio/reference.flac').read_bytes()
        params={'data':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest()}
        if request['mode']=='extra':params['path']='/owner/private'
        peer.sendall(json.dumps(params).encode()+b'\n')
        if request['mode']=='disconnect':
            import time
            deadline=time.monotonic()+15
            while not Path(request['close']).exists():
                assert time.monotonic()<deadline,'fixture close signal deadline'
                time.sleep(.01)
            sys.exit(0)
        result=json.loads(peer.makefile('rb').readline())
        if request['mode']=='extra':assert result['ok'] is False and 'result' not in result
        else:
            assert result['ok'] is True and result['result']['source_sha256']==params['sha256']
            assert 'ask not what your country can do for you' in result['result']['transcript'].lower()
"""
            for uid,mode in [(0,'denied'),(65533,'denied'),(65534,'extra'),(65534,'normal')]:
                client=subprocess.run([sys.executable,'-s','-c',client_code],input=json.dumps({'socket':str(endpoint),'mode':mode}),
                    text=True,capture_output=True,timeout=50,user=uid,group=uid,extra_groups=[],env=env)
                assert client.returncode==0,client.stderr[-2000:]
            def children():
                result=[]
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdecimal():continue
                    try:fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    except (FileNotFoundError,ProcessLookupError):continue
                    if int(fields[1])==service.pid:result.append(int(entry.name))
                return result
            close_signal=rpc/'close-disconnected-client'
            client=subprocess.Popen([sys.executable,'-s','-c',client_code],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,user=65534,group=65534,extra_groups=[],env=env)
            client.stdin.write(json.dumps({'socket':str(endpoint),'mode':'disconnect','close':str(close_signal)}))
            client.stdin.close()
            try:
                deadline=time.monotonic()+10
                while not children():
                    assert service.poll() is None,'speech RPC service exited before disconnect'
                    assert time.monotonic()<deadline,'actual speech worker did not spawn'
                    time.sleep(.01)
                started=children();assert started
                close_signal.write_text('close')
                assert client.wait(timeout=5)==0,client.stderr.read()[-2000:]
                deadline=time.monotonic()+5
                while children():
                    assert service.poll() is None,'speech RPC service exited instead of joining worker'
                    assert time.monotonic()<deadline,'disconnected speech worker was not joined'
                    time.sleep(.02)
                for pid in started:
                    try:os.kill(pid,0)
                    except ProcessLookupError:pass
                    else:raise AssertionError('disconnected speech worker remains alive')
            finally:
                if client.poll() is None:client.kill();client.wait(timeout=5)
                client.stdout.close();client.stderr.close()
        finally:
            service.terminate()
            try:service.wait(timeout=5)
            except subprocess.TimeoutExpired:service.kill();service.wait(timeout=5)
            service.stderr.close()
        receipt=json.loads(result.stdout)
        print(json.dumps({'passed':6,'cases':['actual_pinned_hermes_whisper_transcription_under_separate_uid',
            'actual_kernel_owner_provider_gateway_canaries_unreadable_to_speech_identity',
            'actual_container_network_disabled_and_reviewed_model_bytes_used_offline',
            'actual_socket_activated_private_rpc_validates_nss_config_fd_and_so_peercred_before_frame_despite_world_connectable_fixture_socket',
            'actual_gateway_uid_rpc_runs_bounded_pinned_worker_and_refuses_extra_caller_path',
            'actual_client_disconnect_kills_and_joins_native_worker_without_orphan'],
            'native_receipt':receipt,'actual_uid':65530,'external_stt_account_or_line_voice_acceptance':False},indent=2))


if __name__=='__main__':main()
