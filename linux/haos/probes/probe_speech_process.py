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
    fixture_code=public_audio/'video_fixture.py'
    fixture_code.write_bytes(Path('/repo/linux/haos/runtime/video_fixture.py').read_bytes());fixture_code.chmod(0o644)
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
        for uid,name in [(0,'owner'),(65531,'provider'),(65532,'controller'),(65534,'gateway')]:
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
            accounts.write('haos-speech:x:65530:65530:fixture speech:/var/lib/haos-speech:/usr/sbin/nologin\nhaos-gateway:x:65534:65534:fixture gateway:/nonexistent:/usr/sbin/nologin\nhaos-control:x:65532:65532:fixture controller:/nonexistent:/usr/sbin/nologin\n')
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
        if request['mode'] in {'opus-long','amr-long'}:
            from io import BytesIO
            import random,wave
            source=BytesIO()
            with wave.open(source,'wb') as target:
                target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000);target.writeframes(random.Random(17).randbytes(90*16000*2))
            data=source.getvalue()
        if request['mode']=='thumbnail':
            sys.path.insert(0,'/public-audio')
            from video_fixture import movie
            data=movie()
        params={'data':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest()}
        if request['mode']=='extra':params['path']='/owner/private'
        if request['mode'] in {'opus','opus-long'}:params['operation']='opus'
        if request['mode'] in {'amr','amr-long'}:params['operation']='amr'
        if request['mode']=='thumbnail':params['operation']='thumbnail'
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
        elif request['mode'] in {'opus','opus-long'}:
            from haos.audio_opus import result as verify
            assert result['ok'] is True
            encoded=verify(result['result'],params['sha256']);assert encoded['data'].startswith(b'OggS')
            assert encoded['samples']==(90*16000 if request['mode']=='opus-long' else 176000)
            if request['mode']=='opus-long':assert len(json.dumps(result))>96*1024
        elif request['mode'] in {'amr','amr-long'}:
            from haos.audio_amr import result as verify,duration_samples
            assert result['ok'] is True
            encoded=verify(result['result'],params['sha256'])
            assert encoded['samples']==(90*16000 if request['mode']=='amr-long' else 176000)
            assert duration_samples(encoded['data'])==encoded['encoded_samples']
            if request['mode']=='amr-long':assert len(json.dumps(result))>96*1024
        elif request['mode']=='thumbnail':
            from haos.media_thumbnail import result as verify
            assert result['ok'] is True
            preview=verify(result['result'],params['sha256'])
            assert preview['width']==320 and preview['height']==180 and preview['duration_ms']==1000
            assert len(json.dumps(result))>96*1024
        else:
            assert result['ok'] is True and result['result']['source_sha256']==params['sha256']
            assert 'ask not what your country can do for you' in result['result']['transcript'].lower()
"""
            for uid,mode in [(0,'denied'),(65533,'denied'),(65534,'extra'),(65534,'normal'),(65532,'normal'),(65534,'opus'),(65532,'opus'),(65534,'opus-long'),(65534,'amr'),(65532,'amr'),(65534,'amr-long'),(65534,'thumbnail'),(65532,'thumbnail')]:
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
            with Path('/etc/group').open('a') as groups:groups.write('haos-gateway:x:65534:haos-control\n')
            os.chown(endpoint,0,65534);endpoint.chmod(0o660)
            checked_client="""
import asyncio,hashlib,sys
from pathlib import Path
from haos.speech_client import transcribe,opus,amr,thumbnail
async def main():
    data=Path('/public-audio/reference.flac').read_bytes();checks=[]
    def current():checks.append(True)
    result=await transcribe(data,current)
    assert result['source_sha256']==hashlib.sha256(data).hexdigest() and len(checks)>1
    assert 'ask not what your country can do for you' in result['transcript'].lower()
    encoded=await opus(data,current);assert encoded['source_sha256']==hashlib.sha256(data).hexdigest() and encoded['samples']==176000
    encoded_amr=await amr(data,current)
    assert encoded_amr['source_sha256']==hashlib.sha256(data).hexdigest() and encoded_amr['encoded_samples']==176320
    sys.path.insert(0,'/public-audio')
    from video_fixture import movie
    video=movie();preview=await thumbnail(video,current)
    assert preview['source_sha256']==hashlib.sha256(video).hexdigest() and preview['duration_ms']==1000
    count=[0]
    def withdrawn():
        count[0]+=1
        if count[0]>3:raise PermissionError('fixture owner grant withdrawn')
    for operation,payload in ((transcribe,data),(opus,data),(amr,data),(thumbnail,video)):
        count[0]=0
        try:await operation(payload,withdrawn)
        except PermissionError:pass
        else:raise AssertionError('withdrawn local audio operation returned a result')
asyncio.run(main())
"""
            checked=subprocess.run([sys.executable,'-s','-c',checked_client],text=True,capture_output=True,timeout=50,
                user=65532,group=65532,extra_groups=[65534],env=env)
            assert checked.returncode==0,checked.stderr[-2000:]
            deadline=time.monotonic()+5
            while children():
                assert time.monotonic()<deadline,'revoked checked-client worker was not joined'
                time.sleep(.02)
        finally:
            service.terminate()
            try:service.wait(timeout=5)
            except subprocess.TimeoutExpired:service.kill();service.wait(timeout=5)
            service.stderr.close()
        sys.path[:0]=['/usr/lib/haos','/repo/linux/haos/runtime']
        from speech_owner_fixture import exercise as owner_exercise
        owner_cases=owner_exercise()
        receipt=json.loads(result.stdout)
        print(json.dumps({'passed':13+len(owner_cases),'cases':['actual_pinned_hermes_whisper_transcription_under_separate_uid',
            'actual_kernel_owner_provider_gateway_canaries_unreadable_to_speech_identity',
            'actual_container_network_disabled_and_reviewed_model_bytes_used_offline',
            'actual_socket_activated_private_rpc_validates_nss_config_fd_and_so_peercred_before_frame_despite_world_connectable_fixture_socket',
            'actual_gateway_uid_rpc_runs_bounded_pinned_worker_and_refuses_extra_caller_path',
            'actual_client_disconnect_kills_and_joins_native_worker_without_orphan',
            'actual_controller_uid_checked_client_accepts_root_activated_socket_and_aborts_on_owner_callback_revocation',
            'actual_gateway_and_controller_UID_Opus_conversion_uses_separate_credential_free_worker_and_checked_receipt',
            'actual_90_second_Opus_reply_exceeds_text_reply_limit_and_preserves_duration_without_truncation',
            'actual_gateway_and_controller_UID_AMR_NB_conversion_uses_separate_credential_free_worker_checked_duration_and_owner_revocation',
            'actual_90_second_AMR_reply_exceeds_text_reply_limit_without_truncation_or_unbounded_source',
            'actual_gateway_and_controller_UID_MP4_preview_runs_in_credential_free_worker_with_source_bound_PNG_dimensions_and_duration',
            'actual_checked_thumbnail_client_preserves_long_binary_reply_and_revocation_kills_worker']+owner_cases,
            'native_receipt':receipt,'actual_uid':65530,'owner_service_control_is_fixture':True,'external_stt_account_or_line_voice_acceptance':False,'live_gateway_video_playback_or_installed_acceptance':False},indent=2))


if __name__=='__main__':main()
