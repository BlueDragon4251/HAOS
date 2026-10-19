"""Actual private Wayland application gate, inside an explicitly disposable container.

This proves the session engine, not the installed systemd/agent integration.
The container supplies offline transport, read-only rootfs and cgroup bounds.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import tempfile
import time


def main():
    if os.geteuid() != 0 or os.environ.get('HAOS_DISPOSABLE_APPLICATION_TEST') != '1':
        raise PermissionError('explicit disposable application container required')
    if not Path('/.dockerenv').is_file() or Path('/proc/1/comm').read_text().strip() != 'python3':
        raise PermissionError('run only as the isolated disposable container entrypoint')
    home = Path('/home/mission')
    if not stat.S_ISDIR(home.lstat().st_mode) or home.lstat().st_uid != 1000 or stat.S_IMODE(home.lstat().st_mode) != 0o700:
        raise PermissionError('private disposable mission tmpfs required')
    mounts = Path('/proc/self/mountinfo').read_text().splitlines()
    if not any(line.split()[4] == '/home/mission' and ' - tmpfs ' in line for line in mounts):
        raise PermissionError('never run application tests against a real home directory')
    if not os.statvfs('/').f_flag & os.ST_RDONLY or set(p.name for p in Path('/sys/class/net').iterdir()) != {'lo'}:
        raise PermissionError('read-only offline disposable rootfs required')
    session_source = Path('/usr/lib/haos/haos/application_session.py')
    # A mapped terminal surface precedes its interactive shell. This fixed
    # startup marker is written by the real shell, not the test supervisor; it
    # certifies readiness only, never the result of the typed command below.
    shell_init=home/'fixture.bashrc'
    shell_init.write_text("printf HAOS_SHELL_READY > .fixture-shell-ready\n")
    shell_init.chmod(0o644)
    descriptor = base64.b64encode(json.dumps({'executable':'/usr/bin/foot',
        'argv':['--font','monospace:size=16','--app-id','haos-approved-terminal','--title','HAOS Disposable Mission',
                '/usr/bin/bash','--noprofile','--rcfile',str(shell_init),'-i']}).encode()).decode()
    def identity():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024*1024,64*1024*1024))
        os.setgroups([]); os.setgid(1000); os.setuid(1000)
    diagnostics = tempfile.TemporaryFile()
    worker = subprocess.Popen(['/usr/bin/python3','-I',str(session_source),descriptor],
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}, preexec_fn=identity,
        stdout=subprocess.DEVNULL, stderr=diagnostics)
    control = home / 'control.sock'
    def request(action):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(5); peer.connect(str(control))
            pid, uid, _ = struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            assert pid == worker.pid and uid == 1000, 'real session peer identity'
            peer.sendall(json.dumps(action).encode()+b'\n'); data=bytearray()
            while b'\n' not in data:
                block=peer.recv(65536); assert block; data.extend(block); assert len(data)<1500000
            return json.loads(data.split(b'\n',1)[0])
    try:
        deadline=time.monotonic()+15
        while not control.exists():
            assert worker.poll() is None and time.monotonic()<deadline, 'actual private compositor startup'
            time.sleep(0.05)
        status = dict(line.split(':',1) for line in Path(f'/proc/{worker.pid}/status').read_text().splitlines() if ':' in line)
        assert int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'
        limits=Path(f'/proc/{worker.pid}/limits').read_text()
        assert 'Max file size' in limits and '67108864' in next(line for line in limits.splitlines() if line.startswith('Max file size'))
        while True:
            state=request({'operation':'state'})['result']
            if state['running'] and state['windows']>0: break
            assert time.monotonic()<deadline, 'actual application toplevel startup'; time.sleep(0.05)
        assert request({'operation':'focus'})['result']['focused'], 'actual application keyboard focus'
        while not (home/'.fixture-shell-ready').exists() or (home/'.fixture-shell-ready').read_text()!='HAOS_SHELL_READY':
            assert worker.poll() is None and time.monotonic()<deadline, 'actual interactive shell readiness'
            time.sleep(0.025)
        before=request({'operation':'capture'})['result']
        request({'operation':'type','text':'printf HAOS_REAL_APPLICATION > result.txt'})
        request({'operation':'key','key':'Enter'})
        deadline=time.monotonic()+5
        # File creation precedes the shell's actual write. Verify completed
        # content within the original deadline, retaining the final assertion.
        while not (home/'result.txt').exists() or (home/'result.txt').read_text()!='HAOS_REAL_APPLICATION':
            if time.monotonic()>=deadline:
                # Only this fixed, credentialless fixture. Retain the failing
                # condition and deadline while exposing partial/lost input.
                value=(home/'result.txt').read_text() if (home/'result.txt').exists() else '<absent>'
                raise AssertionError('real terminal input completion: '+repr(value[:256]))
            time.sleep(0.025)
        assert (home/'result.txt').read_text()=='HAOS_REAL_APPLICATION'
        assert stat.S_IMODE((home/'result.txt').stat().st_mode)==0o600
        after=request({'operation':'capture'})['result']
        for pixels in (before,after):
            data=base64.b64decode(pixels['base64'],validate=True)
            assert data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9') and len(data)==pixels['bytes']
            assert hashlib.sha256(data).hexdigest()==pixels['sha256']
        assert before['sha256']!=after['sha256']
        request({'operation':'type','text':'cp result.txt exports/result.txt'})
        request({'operation':'key','key':'Enter'})
        deadline=time.monotonic()+5
        while not (home/'exports/result.txt').exists() or (home/'exports/result.txt').read_text()!='HAOS_REAL_APPLICATION':
            assert time.monotonic()<deadline,'actual private application export completion';time.sleep(0.025)
        exported=request({'operation':'export','file':'result.txt'})['result']
        assert base64.b64decode(exported['base64'],validate=True)==b'HAOS_REAL_APPLICATION'
        assert exported['bytes']==len(b'HAOS_REAL_APPLICATION') and exported['sha256']==hashlib.sha256(b'HAOS_REAL_APPLICATION').hexdigest()
        (home/'exports/alias.txt').symlink_to(home/'result.txt')
        assert 'error' in request({'operation':'export','file':'alias.txt'})
        os.link(home/'exports/result.txt',home/'exports/linked.txt')
        assert 'error' in request({'operation':'export','file':'linked.txt'})
        (home/'exports/linked.txt').unlink()
        for action in ({'operation':'key','key':'Control+V'},{'operation':'key','key':'Super'},
                       {'operation':'type','text':'\n'},{'operation':'capture','path':'/etc/haos'},
                       {'operation':'shell','command':'id'},{'operation':'export','file':'../result.txt'},
                       {'operation':'export','file':'.fixture-shell-ready'}):
            assert 'error' in request(action), 'unauthorized private application action'
        peer_probe='''import socket,sys
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(2);s.connect(sys.argv[1]);s.sendall(b'{"operation":"state"}\\n')
try: reply=s.recv(100)
except ConnectionResetError: reply=b''
assert reply==b''
'''
        subprocess.run(['/usr/bin/python3','-I','-c',peer_probe,str(control)],preexec_fn=identity,
                       env={'PATH':'/usr/bin:/bin'},check=True,timeout=5)
        ptrace_probe='''import ctypes,errno,sys
libc=ctypes.CDLL(None,use_errno=True)
assert libc.ptrace(16,int(sys.argv[1]),None,None)==-1 and ctypes.get_errno()==errno.EPERM
'''
        subprocess.run(['/usr/bin/python3','-I','-c',ptrace_probe,str(worker.pid)],preexec_fn=identity,
                       env={'PATH':'/usr/bin:/bin'},check=True,timeout=5)
        print(json.dumps({'schema':1,'scope':'disposable private application session component',
            'source_commit':os.environ.get('GITHUB_SHA'),
            'source_sha256':hashlib.sha256(session_source.read_bytes()).hexdigest(),
            'real_application_toplevel':True,'real_application_focus':True,'actual_shell_readiness_verified':True,
            'real_keyboard_result_verified':True,
            'real_capture_integrity':True,'real_capture_changed':True,
            'real_keyboard_output_export_hash_and_bytes_verified':True,
            'export_paths_symlinks_hardlinks_and_hidden_profiles_denied':True,
            'clipboard_and_global_modifiers_denied':True,'paths_and_shell_controls_denied':True,
            'unprivileged_app_control_peer_denied':True,'root_broker_peer_pid_verified':True,
            'application_effective_capabilities_zero':True,'application_no_new_privileges':True,
            'actual_64m_file_limit_and_bounded_terminal_shm':True,
            'same_uid_control_process_ptrace_denied':True,
            'installed_systemd_launch_verified':False,'hermes_model_execution_verified':False}),flush=True)
    finally:
        try:
            if worker.poll() is None:
                worker.terminate()
                try: worker.wait(timeout=5)
                except subprocess.TimeoutExpired: worker.kill();worker.wait(timeout=3)
        finally:
            if worker.returncode:
                diagnostics.seek(0)
                # Only the deliberately credentialless fixed fixture's Python
                # exception, never application content or production journals.
                print(diagnostics.read(4096).decode(errors='replace'), flush=True)
            diagnostics.close()


if __name__=='__main__':
    main()
