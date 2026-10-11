"""Private application Wayland session, executed only inside the launcher's rootfs.

All children share one bounded mission cgroup and private network/filesystem.
The control socket accepts kernel-authenticated root broker peers, never an app.
No host Wayland, clipboard, environment, credential or input device is imported.
"""
import base64
import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

KEYS = {'Tab': 'Tab', 'Enter': 'Return', 'Backspace': 'BackSpace', 'Delete': 'Delete',
        'ArrowUp': 'Up', 'ArrowDown': 'Down', 'ArrowLeft': 'Left', 'ArrowRight': 'Right',
        'Home': 'Home', 'End': 'End', 'Escape': 'Escape'}
FRAME_LIMIT = 8192


def diagnostic(stage, error=None):
    if stage not in {'credential','hardening','identity','compositor','keyboard','application','control','failed'}:
        raise ValueError('invalid private session diagnostic')
    value={'event':'application.session','stage':stage}
    if error is not None:
        known={'ValueError','KeyError','PermissionError','RuntimeError','TimeoutError','OSError',
               'JSONDecodeError','FileNotFoundError','TypeError'}
        value['error']=error if error in known else 'unexpected-error'
    # Only these fixed lifecycle codes reach the journal. Every application and
    # compositor/helper child's stdout/stderr is separately disconnected.
    print(json.dumps(value),flush=True)


def session_action(action):
    if not isinstance(action, dict):
        raise ValueError('application action must be an object')
    op=action.get('operation')
    fields={'operation'} | ({'text'} if op=='type' else {'key'} if op=='key' else set())
    if set(action)!=fields or op not in {'state','focus','type','key','capture'}:
        raise PermissionError('application capability denied')
    if op=='type' and (not isinstance(action['text'],str) or not 1<=len(action['text'].encode())<=512
                      or any(ord(c)<32 or ord(c)==127 for c in action['text'])):
        # wtype has a real per-key protocol roundtrip/delay. Bound each action
        # to the existing three-second helper deadline, rather than admitting
        # 4096 characters that inevitably produce partial input on that budget.
        raise ValueError('bounded plain application text required')
    if op=='key' and action['key'] not in KEYS:
        raise PermissionError('application shortcut denied')
    return dict(action)


def root_program(path):
    value = Path(path)
    if not str(value).startswith('/usr/') or '..' in value.parts:
        raise PermissionError('installed application helper required')
    for parent in (value, *value.parents):
        info = parent.lstat()
        if info.st_uid != 0 or info.st_mode & 0o6022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError('untrusted application helper identity')
    if not stat.S_ISREG(value.stat().st_mode) or not value.stat().st_mode & 0o111:
        raise PermissionError('application helper is not executable')
    with value.open('rb') as stream:
        if value.stat().st_nlink != 1 or stream.read(4) != b'\x7fELF':
            raise PermissionError('an exact installed ELF helper is required')
    return str(value)


class ApplicationSession:
    def __init__(self, executable, arguments, home=Path('/home/mission')):
        if os.geteuid() == 0:
            raise PermissionError('application sessions cannot run as root')
        self.home = Path(home)
        info = self.home.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or self.home.resolve() != self.home:
            raise PermissionError('a private canonical application home is required')
        self.executable = root_program(executable)
        if (not isinstance(arguments, list) or len(arguments) > 32
                or any(not isinstance(v, str) or len(v.encode()) > 1024 or any(ord(c) < 32 for c in v) for v in arguments)):
            raise ValueError('bounded owner arguments required')
        self.arguments = list(arguments)
        self.labwc, self.wtype, self.wlrctl, self.grim, self.wayland_info = [root_program('/usr/bin/' + name)
            for name in ('labwc','wtype','wlrctl','grim','wayland-info')]
        self.runtime = self.home / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.env = {'HOME': str(self.home), 'XDG_RUNTIME_DIR': str(self.runtime), 'PATH': '/usr/bin:/bin',
                    'LANG': 'C.UTF-8', 'WLR_BACKENDS': 'headless', 'WLR_RENDERER': 'pixman',
                    'WLR_LIBINPUT_NO_DEVICES': '1', 'WLR_HEADLESS_OUTPUTS': '1'}
        self.compositor = self.application = self.keyboard = None

    def start(self):
        diagnostic('compositor')
        config = self.home / 'config'
        config.mkdir(mode=0o700)
        self.env['XDG_CONFIG_HOME']=str(config)
        (config / 'rc.xml').write_text('<labwc_config><keyboard><default/></keyboard><mouse><default/></mouse></labwc_config>')
        # An empty explicit autostart prevents installed desktop launchers from
        # creating unrelated applications even in this private compositor.
        (config / 'autostart').write_text('')
        if self.executable=='/usr/bin/foot':
            # foot's default sparse 512 MiB memfd is subject to RLIMIT_FSIZE
            # despite not consuming that much physical memory. Retain the
            # launcher's 64 MiB file bound and give this supported application
            # a private 32 MiB rendering pool, rather than loosening the unit.
            terminal=config/'foot';terminal.mkdir(mode=0o700)
            (terminal/'foot.ini').write_text('[tweak]\nmax-shm-pool-size-mb=32\n')
        self.compositor = subprocess.Popen([self.labwc, '--config-dir', str(config)], env=self.env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while True:
            displays = [p for p in self.runtime.glob('wayland-*') if stat.S_ISSOCK(p.lstat().st_mode)]
            if len(displays) == 1:
                self.env['WAYLAND_DISPLAY'] = displays[0].name
                break
            if self.compositor.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('private application compositor unavailable')
            time.sleep(0.025)
        # A headless seat initially has no wl_keyboard capability. A short-lived
        # injector can send keys before the application has bound wl_keyboard.
        # Keep one idle private virtual device alive; verify the actual seat
        # capability before allowing any application to connect. No key is sent
        # by this fixed helper. The enclosing cgroup bounds its lifetime.
        self.keyboard=subprocess.Popen([self.wtype,'-s','3600000'],env=self.env,cwd=self.home,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        while True:
            listing=self.helper([self.wayland_info]).decode('utf-8',errors='replace')
            if re.search(r'(?m)^\s*capabilities:.*\bkeyboard\b',listing): break
            if self.keyboard.poll() is not None or time.monotonic()>=deadline:
                raise RuntimeError('private application keyboard seat unavailable')
            time.sleep(0.025)
        diagnostic('keyboard')
        self.application = subprocess.Popen([self.executable, *self.arguments], cwd=self.home,
                                           env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        diagnostic('application')

    def helper(self, arguments, limit=65536):
        process = subprocess.Popen(arguments, env=self.env, cwd=self.home, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        output = bytearray()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 3
        try:
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError('application helper deadline exceeded')
                for key, _ in selector.select(0.025):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(data)
                        if len(output) > limit:
                            raise ValueError('application helper output budget exceeded')
            if process.wait(timeout=max(0.01, deadline - time.monotonic())):
                raise RuntimeError('private application helper failed')
            return bytes(output)
        finally:
            selector.close()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)

    def execute(self, action):
        action=session_action(action)
        op=action['operation']
        if not self.compositor or self.compositor.poll() is not None:
            raise RuntimeError('application compositor stopped')
        if op in {'state', 'focus'}:
            listing = self.helper([self.wlrctl, 'toplevel', 'list'])
            # Titles/content are never written to a durable action or system log.
            lines = listing.decode('utf-8', errors='replace').splitlines()
            if len(lines) > 32:
                raise ValueError('application window budget exceeded')
            if op == 'focus':
                # A private session cannot target an owner or another mission's
                # window. Multiple windows require explicit future selection;
                # do not silently send input to a different dialog.
                if len(lines) != 1:
                    raise PermissionError('one unambiguous private application window required')
                self.helper([self.wlrctl, 'toplevel', 'focus'])
                self.helper([self.wlrctl, 'toplevel', 'find', 'state:focused'])
                return {'focused': True}
            return {'running': self.application.poll() is None, 'windows': len(lines),
                    'application_exitcode':self.application.returncode,
                    'window_state_sha256': hashlib.sha256(listing).hexdigest()}
        if op == 'type':
            if self.keyboard.poll() is not None:
                raise RuntimeError('private application keyboard stopped')
            self.helper([self.wtype, '--', action['text']])
            return {'applied': True}
        if op == 'key':
            if self.keyboard.poll() is not None:
                raise RuntimeError('private application keyboard stopped')
            if action.get('key') not in KEYS:
                raise PermissionError('application shortcut denied')
            self.helper([self.wtype, '-k', KEYS[action['key']]])
            return {'applied': True}
        pixels = self.helper([self.grim, '-t', 'jpeg', '-'], limit=1024*1024)
        if not pixels.startswith(b'\xff\xd8') or not pixels.endswith(b'\xff\xd9'):
            raise ValueError('invalid private compositor capture')
        return {'mime': 'image/jpeg', 'sha256': hashlib.sha256(pixels).hexdigest(),
                'bytes': len(pixels), 'base64': base64.b64encode(pixels).decode('ascii')}

    def close(self):
        for process in (self.application, self.keyboard, self.compositor):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        # The outer systemd cgroup owns and kills *all* remaining descendants,
        # including children that create a different POSIX process group.


def serve(session):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(session.home / 'control.sock'))
    os.chmod(session.home / 'control.sock', 0o600)
    listener.listen(4)
    listener.settimeout(0.5)
    try:
        while session.compositor.poll() is None and session.application.poll() is None:
            try:
                peer, _ = listener.accept()
            except socket.timeout:
                continue
            with peer:
                peer.settimeout(1)
                _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != 0:
                    continue
                data = bytearray()
                try:
                    while b'\n' not in data:
                        block = peer.recv(1024)
                        if not block:
                            raise ValueError('incomplete application frame')
                        data.extend(block)
                        if len(data) > FRAME_LIMIT:
                            raise ValueError('application frame budget exceeded')
                    frame, rest = data.split(b'\n', 1)
                    if rest:
                        raise ValueError('multiple application frames denied')
                    result = {'result': session.execute(json.loads(frame))}
                except (ValueError, PermissionError, RuntimeError, TimeoutError, OSError):
                    result = {'error': 'application action denied or unavailable'}
                peer.sendall(json.dumps(result).encode() + b'\n')
        if session.compositor.poll() is not None:
            # Fixed lifecycle diagnostics only; never application stderr, titles
            # or caller text. A compositor exit is not a successful app receipt.
            raise RuntimeError('private application compositor stopped')
    finally:
        listener.close()


def main():
    diagnostic('credential')
    if len(sys.argv)==1:
        directory=Path(os.environ['CREDENTIALS_DIRECTORY'])
        path=directory/'launch'
        if not directory.is_absolute() or not str(directory).startswith('/run/credentials/') or path.resolve()!=path:
            raise PermissionError('system-owned application launch credential required')
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size>16384:
            raise PermissionError('invalid application launch credential')
        manifest=json.loads(path.read_bytes())
    elif len(sys.argv)==2:
        # The offline component fixture uses only fixed nonsensitive arguments.
        # Actual systemd launches always use the private credential above.
        manifest=json.loads(base64.b64decode(sys.argv[1],validate=True))
    else:
        raise ValueError('owner-approved application launch descriptor required')
    if not isinstance(manifest,dict) or set(manifest)!={'executable','argv'}:
        raise ValueError('invalid application launch descriptor')
    diagnostic('hardening')
    # Same-UID applications must not ptrace/inject the trusted control process.
    # This also protects its descriptors after an application replaces a socket
    # pathname. Root still verifies the kernel server PID, not the path alone.
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0 or libc.prctl(4,0,0,0,0)!=0 or libc.prctl(3,0,0,0,0)!=0:
        raise PermissionError('application control process hardening unavailable')
    # This descriptor is provided only by the independently authorizing launcher.
    diagnostic('identity')
    session = ApplicationSession(manifest['executable'], manifest['argv'])
    def finish(_signum, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, finish)
    try:
        session.start()
        diagnostic('control')
        serve(session)
    finally:
        session.close()


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        diagnostic('failed',type(exc).__name__)
        raise
