#!/usr/bin/env python3
"""Actual installed Node provenance, kernel roles, early withdrawal/parent death.

The initial private resume RPC is intentionally held before SDK/cloud startup.
No external account, service connection or messaging delivery is exercised.
"""
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, '/usr/lib/haos')


def identity(uid, *, groups=(), saved_uid=None, saved_gid=None, nnp=True):
    os.setgroups(list(groups)); os.setresgid(uid, uid, uid if saved_gid is None else saved_gid)
    os.setresuid(uid, uid, uid if saved_uid is None else saved_uid)
    if nnp and ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError('actual NoNewPrivileges setup failed')


def role(uid, *, groups=(), saved_uid=None, saved_gid=None):
    code = '''import json,sys,os,ctypes
sys.path.insert(0,"/usr/lib/haos")
from haos.gateway_photon_process import command
value=json.loads(sys.argv[1]);uid=value["uid"]
os.setgroups(value["groups"])
os.setresgid(uid,uid,uid if value["saved_gid"] is None else value["saved_gid"])
os.setresuid(uid,uid,uid if value["saved_uid"] is None else value["saved_uid"])
assert ctypes.CDLL(None).prctl(38,1,0,0,0)==0
try: print(json.dumps({"allowed":True,"args":command()}))
except PermissionError: print(json.dumps({"allowed":False}))
'''
    # exec resets saved IDs to the effective IDs. Construct the actual saved-ID
    # case inside the actor, then invoke the production guard without an exec.
    value = {'uid': uid, 'groups': list(groups), 'saved_uid': saved_uid, 'saved_gid': saved_gid}
    completed = subprocess.run(['/usr/local/bin/python3', '-I', '-c', code, json.dumps(value)],
        env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, check=True, timeout=10)
    return json.loads(completed.stdout)


async def worker(mode, directory):
    from haos.gateway_photon_process import Child
    import secrets
    root = Path(directory); token = secrets.token_hex(32); granted = [True]; observed = asyncio.Event()
    def current():
        if not granted[0]: raise PermissionError('fixture owner authority withdrawn')
    child = Child({'project_id': 'fixture-project', 'project_secret': secrets.token_urlsafe(32),
        'phone': 'shared', 'services': ['iMessage']}, root, root / 'policy.sock', root / 'control.sock', token, current)
    async def hold(reader, writer):
        try:
            header = await reader.readuntil(b'\r\n\r\n')
            peer = struct.unpack('3i', writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            assert peer == (child.pid, os.geteuid(), os.getegid())
            assert header.startswith(b'POST /resume HTTP/1.1\r\n')
            assert b'X-Hermes-Sidecar-Token: ' + token.encode() in header
            observed.set()
            if mode == 'parent-death':
                print(json.dumps({'node_pid': child.pid, 'parent_pid': os.getpid()}), flush=True)
                os._exit(0)  # Actual hard supervisor loss, no Python cleanup.
            await asyncio.sleep(20)
        except (ConnectionError, asyncio.IncompleteReadError): pass
        finally: writer.close()
    listener = await asyncio.start_unix_server(hold, path=str(root / 'policy.sock'))
    (root / 'policy.sock').chmod(0o600)
    starting = asyncio.create_task(child.start())
    try:
        await asyncio.wait_for(observed.wait(), 8)
        pid = child.pid; assert pid is not None
        status = Path(f'/proc/{pid}/status').read_text()
        assert '\nNoNewPrivs:\t1\n' in status
        assert [int(v) for v in next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1:]] == [65534] * 4
        granted[0] = False
        try: await asyncio.wait_for(starting, 4)
        except PermissionError: pass
        else: raise AssertionError('withdrawn early SDK startup was accepted')
        assert child.pid is None and not Path(f'/proc/{pid}').exists()
        assert not (root / 'control.sock').exists()
        print(json.dumps({'early_withdrawal_stopped_actual_Node': True, 'SDK_started': False}), flush=True)
    finally:
        starting.cancel(); await asyncio.gather(starting, return_exceptions=True)
        await child.stop(); listener.close(); await listener.wait_closed()


def main():
    if os.geteuid() != 0 or os.getpid() != 1 or os.environ.get('HAOS_DISPOSABLE_PHOTON_PROCESS') != '1':
        raise PermissionError('fresh disposable PID-1 process fixture required')
    root = Path('/usr/lib/haos'); root.mkdir(mode=0o755)
    shutil.copytree('/input/photon', root / 'photon'); shutil.copytree('/input/hermes', root / 'hermes')
    # The checkout is intentionally private to its developer. Exercise the
    # actual installed layout, not broaden its permissions for service users.
    shutil.copytree('/repo/linux/haos/haos', root / 'haos', ignore=shutil.ignore_patterns('__pycache__'), copy_function=shutil.copyfile)
    for entry in (root / 'haos').rglob('*'): entry.chmod(0o755 if entry.is_dir() else 0o644)
    (root / 'haos').chmod(0o755)
    fixtures = root / 'fixtures'; fixtures.mkdir(mode=0o755)
    worker_file = fixtures / 'probe_photon_process.py'; shutil.copyfile(__file__, worker_file); worker_file.chmod(0o644)
    resume_file = fixtures / 'probe_photon_resume.mjs'
    shutil.copyfile('/repo/linux/haos/runtime/probe_photon_resume.mjs', resume_file); resume_file.chmod(0o644)
    passwd = Path('/etc/passwd')
    assert 'haos-gateway:' not in passwd.read_text()
    with passwd.open('a') as output: output.write('haos-gateway:x:65534:65534:fixture:/nonexistent:/usr/sbin/nologin\n')
    cases = []
    permitted = role(65534)
    assert permitted['allowed'] is True and permitted['args'] == ['/usr/lib/haos/photon/node', '--no-addons', '--disable-proto=throw', '--use-system-ca', '--max-old-space-size=192', '/usr/lib/haos/photon/photon_sidecar.mjs']
    cases.append('actual_private_UID_GID_accepts_only_verified_fixed_Node_command')
    for label, uid, options in [('root', 0, {}), ('agent', 65532, {}), ('supplementary-root', 65534, {'groups': [0]}),
            ('saved-root-uid', 65534, {'saved_uid': 0}), ('saved-root-gid', 65534, {'saved_gid': 0})]:
        assert role(uid, **options) == {'allowed': False}, label
        cases.append('actual_kernel_' + label + '_cannot_use_gateway_command')
    metadata = root / 'photon/source.json'; original = metadata.read_bytes()
    for key, value in [('spectrum_version', 'unreviewed'), ('hermes_commit', '0' * 40), ('schema', 999)]:
        changed = json.loads(original); changed[key] = value; metadata.write_text(json.dumps(changed))
        assert role(65534) == {'allowed': False}; metadata.write_bytes(original)
        cases.append('actual_installed_' + key + '_drift_refused')
    launcher = root / 'photon/photon_sidecar.mjs'; code = launcher.read_bytes(); launcher.write_bytes(code + b'\n// fixture tamper\n')
    assert role(65534) == {'allowed': False}; launcher.write_bytes(code)
    cases.append('actual_source_bytes_cannot_change_behind_trusted_metadata')
    launcher.chmod(0o666); assert role(65534) == {'allowed': False}; launcher.chmod(0o644)
    cases.append('actual_writable_program_refused')
    link = root / 'photon/fixture-link'; os.link(launcher, link)
    assert role(65534) == {'allowed': False}; link.unlink()
    cases.append('actual_hardlinked_program_refused')
    os.chown(launcher, 65532, 65532); assert role(65534) == {'allowed': False}; os.chown(launcher, 0, 0)
    cases.append('actual_foreign_owned_program_refused')
    assert role(65534)['allowed'] is True
    no_nnp_home = Path(tempfile.mkdtemp(prefix='hp-', dir='/tmp')); os.chown(no_nnp_home, 65534, 65534)
    no_nnp = '''import asyncio,secrets,sys
from pathlib import Path
sys.path.insert(0,"/usr/lib/haos")
from haos.gateway_photon_process import Child
root=Path(sys.argv[1]);child=Child({"project_id":"fixture-project","project_secret":secrets.token_urlsafe(32),"phone":"shared","services":["iMessage"]},root,root/"policy.sock",root/"control.sock",secrets.token_hex(32),lambda:None)
async def run():
 try:await child.start()
 except PermissionError as error:assert "NoNewPrivileges" in str(error)
 else:raise AssertionError("unhardened child start accepted")
 assert child.process is None
asyncio.run(run())
'''
    subprocess.run(['/usr/local/bin/python3', '-I', '-c', no_nnp, str(no_nnp_home)],
        preexec_fn=lambda: identity(65534, nnp=False), env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
        check=True, capture_output=True, text=True, timeout=10)
    cases.append('actual_missing_NoNewPrivileges_refused_before_any_child_or_credentials_handoff')
    sessions = []
    for mode in ['withdrawal', 'parent-death']:
        home = Path(tempfile.mkdtemp(prefix='hp-', dir='/tmp')); os.chown(home, 65534, 65534); home.chmod(0o700); sessions.append(home)
        completed = subprocess.run(['/usr/local/bin/python3', '-I', str(worker_file), '--worker', mode, str(home)],
            preexec_fn=lambda: identity(65534), env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, check=True, timeout=15)
        value = json.loads(completed.stdout)
        if mode == 'withdrawal':
            assert value == {'early_withdrawal_stopped_actual_Node': True, 'SDK_started': False}
            cases.append('actual_production_Node_bootstrap_is_stopped_on_owner_withdrawal_before_SDK_init')
        else:
            pid = value['node_pid']; deadline = time.monotonic() + 4
            while Path(f'/proc/{pid}').exists():
                try: os.waitpid(pid, os.WNOHANG)
                except ChildProcessError: pass
                assert time.monotonic() < deadline, 'actual Node survived parent pipe loss'
                time.sleep(0.01)
            cases.append('actual_parent_hard_exit_kills_production_Node_bootstrap_before_SDK_init')
    # The actual public SDK stream probe can execute from immutable installed
    # modules as this private identity, without a provider connection.
    home = sessions[0]; receipt = home / 'native-resume.json'
    completed = subprocess.run([permitted['args'][0], *permitted['args'][1:-1], str(resume_file),
        '/usr/lib/haos/hermes/plugins/platforms/photon/sidecar', str(receipt)], preexec_fn=lambda: identity(65534),
        env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(receipt.read_text())['passed'] == 6
    cases.append('actual_official_Node_private_UID_flags_and_readonly_SDK_resume_probe_pass')
    result = {'schema': 1, 'passed': len(cases), 'cases': cases, 'actual_node': '24.19.0',
        'scope': 'actual verified installed programs, kernel identities, NoNewPrivileges, production bootstrap and Unix peer, early withdrawal and parent death',
        'substitution': 'initial resume RPC held before SDK/cloud initialization',
        'live_Photon_verified': False, 'native_gRPC_verified': False, 'OS_release_artifact': False}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--worker': asyncio.run(worker(sys.argv[2], sys.argv[3]))
    else: main()
