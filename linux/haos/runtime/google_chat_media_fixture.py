"""Disposable Root fixture for the real socket-activated local speech service."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time


class SpeechFixture:
    def __init__(self,interpreter,*,model=False):
        if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
                or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_PROFILE_PROCESS')!='1'):
            raise PermissionError('explicit disposable Google media namespace required')
        self.process=None
        with Path('/etc/passwd').open('a') as stream:
            stream.write('haos-speech:x:65530:65530:Disposable speech:/var/lib/haos-speech:/usr/sbin/nologin\n')
        with Path('/etc/group').open('a') as stream:stream.write('haos-gateway:x:65534:\n')
        state=Path('/var/lib/haos-speech');state.mkdir(mode=0o700);os.chown(state,65530,65530)
        config=Path('/etc/haos-speech');config.mkdir(mode=0o755)
        settings=config/'config.yaml';settings.write_text('stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n');settings.chmod(0o644)
        public=Path('/etc/haos');public.mkdir(mode=0o755)
        policy=public/'speech.json';policy.write_text(json.dumps({'version':1,'enabled':True,'model':'tiny'}));policy.chmod(0o644)
        if model:
            models=Path('/var/lib/haos-speech-models');models.mkdir(mode=0o755)
            destination=models/'tiny-d90ca5fe260221311c53c58e660288d3deb8d356'
            shutil.copytree('/public-model',destination)
            destination.chmod(0o755)
            for path in destination.iterdir():path.chmod(0o644)
        directory=Path('/run/haos-speech');directory.mkdir(mode=0o755)
        endpoint=directory/'voice.sock'
        listening=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listening.bind(str(endpoint));listening.listen(8)
        os.chown(endpoint,0,65534);endpoint.chmod(0o660)
        activation="""import os,sys
fd=int(sys.argv[1])
if fd!=3:os.dup2(fd,3);os.close(fd)
os.set_inheritable(3,True)
os.environ['LISTEN_PID']=str(os.getpid());os.environ['LISTEN_FDS']='1'
os.execv(sys.executable,[sys.executable,'-s','-m','haos.speech_service'])
"""
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
            'HOME':str(state),'HERMES_HOME':str(config),'HERMES_SAFE_MODE':'1',
            'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'1'}
        try:
            self.process=subprocess.Popen([str(interpreter),'-s','-c',activation,str(listening.fileno())],
                pass_fds=(listening.fileno(),),user=65530,group=65530,extra_groups=[],cwd='/usr/lib/haos',
                env=env,umask=0o077,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
        finally:listening.close()
        deadline=time.monotonic()+15
        try:
            while True:
                assert self.process.poll() is None,'actual private speech service exited'
                assert time.monotonic()<deadline,'private speech service readiness deadline'
                try:
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
                        peer.settimeout(.2);peer.connect(str(endpoint));line=peer.makefile('rb').readline()
                    assert json.loads(line)=={'ok':False,'error':'speech peer denied'}
                    break
                except (TimeoutError,ConnectionError):time.sleep(.02)
        except BaseException:self.close();raise

    def children(self):
        values=[]
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():continue
            try:fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
            except (FileNotFoundError,ProcessLookupError):continue
            if int(fields[1])==self.process.pid:values.append(int(entry.name))
        return values

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
            self.process.stderr.close();self.process=None
