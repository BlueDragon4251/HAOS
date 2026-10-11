"""Actual bounded systemd application units on an explicitly disposable CI runner.

Only unique /run and /usr/lib fixture trees and their own transient units change.
No host display, disk, account, production policy or owner files are imported.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    if (os.geteuid()!=0 or os.environ.get('GITHUB_ACTIONS')!='true'
            or os.environ.get('HAOS_DISPOSABLE_CI')!='1'
            or Path('/proc/1/comm').read_text().strip()!='systemd'):
        raise PermissionError('actual systemd on an explicit disposable GitHub runner required')
    account=pwd.getpwnam(os.environ['SUDO_USER'])
    if account.pw_uid<1000: raise PermissionError('separate unprivileged controller fixture required')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from haos.application_launcher import ApplicationLauncher
    from haos.applications import ApplicationRegistry,executable_digest
    root=Path(tempfile.mkdtemp(prefix='haos-app-unit-',dir='/run'));root.chmod(0o755)
    code=Path(tempfile.mkdtemp(prefix='haos-app-unit-',dir='/usr/lib'));code.chmod(0o755)
    launcher=None;requests=[];pids=[]
    try:
        module=code/'haos';module.mkdir(mode=0o755)
        for source in (Path(__file__).resolve().parents[1]/'haos').glob('*.py'):
            shutil.copyfile(source,module/source.name);(module/source.name).chmod(0o644)
        source=module/'application_session.py'
        initialization=code/'fixture.bashrc'
        initialization.write_text('printf HAOS_REAL_SHELL_READY > .fixture-ready\n');initialization.chmod(0o644)
        ledger_dir=root/'ledger';ledger_dir.mkdir(mode=0o700);os.chown(ledger_dir,account.pw_uid,account.pw_gid)
        ledger=ledger_dir/'missions.db'
        def controller(program):
            def identity():
                os.setgroups([]);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
            return subprocess.run(['/usr/bin/python3','-I','-c',program,str(code),str(ledger)],
                preexec_fn=identity,env={'PATH':'/usr/bin:/bin'},check=True,capture_output=True,text=True,timeout=5)
        result=controller("import sys,os;sys.path.insert(0,sys.argv[1]);from pathlib import Path;from haos.store import MissionStore;"
            "s=MissionStore(Path(sys.argv[2]));m=s.create('offline-fixture','app','actual systemd application component');"
            "s.claim();s.session(m['id'],'offline-fixture','offline-fixture-stored');s.dispatching(m['id']);"
            "os.chmod(sys.argv[2],0o600);print(m['id']);s.close()")
        mission=result.stdout.strip();assert str(uuid.UUID(mission))==mission
        registry=ApplicationRegistry(root/'applications.json')
        approval={'id':'fixture-terminal','class':'terminal','executable':'/usr/bin/foot',
            'sha256':executable_digest('/usr/bin/foot'),'argv':['--app-id','haos-private-unit-fixture',
                '--font','monospace:size=16','/usr/bin/bash','--noprofile','--rcfile',str(initialization),'-i'],
            'memory_mib':512,'runtime_seconds':60}
        registry.register(approval)
        launcher=ApplicationLauncher(registry,root/'state',root/'rootfs',source)
        def execute(request,action):
            return launcher.execute(request,mission,action,ledger=ledger,ledger_uid=account.pw_uid)
        def denied(call):
            try: call()
            except (PermissionError,ValueError): return
            raise AssertionError('unauthorized application action accepted')
        homes=[];units=[]
        for index in range(2):
            request=str(uuid.uuid4());requests.append(request)
            assert launcher.start('fixture-terminal',mission,request,ledger=ledger,ledger_uid=account.pw_uid)['state']=='submitted'
            denied(lambda:launcher.start('fixture-terminal',mission,request,ledger=ledger,ledger_uid=account.pw_uid))
            unit=launcher.record(request)['unit'];units.append(unit)
            home=Path('/run')/unit;homes.append(home)
            deadline=time.monotonic()+15
            while True:
                state=launcher.unit_state(request)
                if state['ActiveState']=='failed':
                    journal=subprocess.run(['/usr/bin/journalctl','--unit='+unit+'.service','--output=cat','--no-pager','-n','30'],
                        capture_output=True,text=True,check=True,timeout=3).stdout
                    phases=[]
                    for line in journal.splitlines():
                        if len(line)>512: continue
                        try: value=json.loads(line)
                        except ValueError: continue
                        if (isinstance(value,dict) and set(value)<={'event','stage','error'}
                                and value.get('event')=='application.session'
                                and value.get('stage') in {'credential','hardening','identity','compositor','keyboard','application','control','failed'}
                                and value.get('error') in {None,'ValueError','KeyError','PermissionError','RuntimeError',
                                    'TimeoutError','OSError','JSONDecodeError','FileNotFoundError','TypeError','unexpected-error'}):
                            phases.append(value)
                    raise AssertionError('real systemd unit startup failed: '+json.dumps({'exit':state['ExecMainStatus'],'phases':phases}))
                if (home/'control.sock').exists() and (home/'.fixture-ready').exists():
                    break
                assert time.monotonic()<deadline,'actual private unit/interactive shell readiness'
                time.sleep(0.025)
            pid=int(state['MainPID']);pids.append(pid)
            status=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
            assert int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'
            assert 61184<=int(status['Uid'].split()[0])<=65519
            assert os.readlink(f'/proc/{pid}/ns/net')!=os.readlink('/proc/self/ns/net')
            assert not Path(f'/proc/{pid}/root/etc/haos').exists()
            assert not Path(f'/proc/{pid}/root/run/haos-control').exists()
            assert state['ControlGroup'].endswith('/'+unit+'.service') and '..' not in state['ControlGroup'].split('/')
            cgroup=Path('/sys/fs/cgroup')/state['ControlGroup'].lstrip('/')
            assert int((cgroup/'memory.max').read_text())==512*1024*1024
            assert (cgroup/'memory.swap.max').read_text().strip()=='0'
            assert (cgroup/'pids.max').read_text().strip()=='64'
            quota,period=map(int,(cgroup/'cpu.max').read_text().split());assert 0<quota<=period
            assert execute(request,{'operation':'state'})['windows']==1
            assert execute(request,{'operation':'focus'})['focused']
            before=execute(request,{'operation':'capture'})
            assert execute(request,{'operation':'type','text':f'printf HAOS_REAL_UNIT_{index} > verified.txt'})['applied']
            assert execute(request,{'operation':'key','key':'Enter'})['applied']
            deadline=time.monotonic()+5
            while not (home/'verified.txt').exists() or (home/'verified.txt').read_text()!=f'HAOS_REAL_UNIT_{index}':
                assert time.monotonic()<deadline,'real systemd terminal input/result'
                time.sleep(0.025)
            after=execute(request,{'operation':'capture'})
            for image in (before,after):
                pixels=base64.b64decode(image['base64'],validate=True)
                assert hashlib.sha256(pixels).hexdigest()==image['sha256'] and len(pixels)==image['bytes']
            assert before['sha256']!=after['sha256']
            denied(lambda:launcher.execute(request,str(uuid.uuid4()),{'operation':'state'},ledger=ledger,ledger_uid=account.pw_uid))
            denied(lambda:execute(request,{'operation':'key','key':'Control+V'}))
        assert homes[0]!=homes[1] and homes[0].stat().st_uid!=homes[1].stat().st_uid
        assert os.readlink(f'/proc/{pids[0]}/ns/net')!=os.readlink(f'/proc/{pids[1]}/ns/net')
        # A descendant deliberately escapes its POSIX process group. The real
        # service cgroup, not a process-group assumption, must still terminate it.
        execute(requests[0],{'operation':'type','text':'setsid /usr/bin/sleep 120 &'})
        execute(requests[0],{'operation':'key','key':'Enter'})
        state=launcher.unit_state(requests[0]);group=Path('/sys/fs/cgroup')/state['ControlGroup'].lstrip('/')
        deadline=time.monotonic()+3
        while True:
            descendants=[int(v) for v in (group/'cgroup.procs').read_text().split()]
            sleeps=[pid for pid in descendants if Path(f'/proc/{pid}/comm').read_text().strip()=='sleep']
            if sleeps: break
            assert time.monotonic()<deadline,'real escaped process-group child';time.sleep(0.025)
        assert launcher.stop(requests[0])['state']=='stopped'
        assert not group.exists() or 'populated 0' in (group/'cgroup.events').read_text()
        assert all(not Path(f'/proc/{pid}').exists() for pid in descendants)
        assert execute(requests[1],{'operation':'state'})['running'],'unrelated private application survives'
        registry.revoke('fixture-terminal');denied(lambda:execute(requests[1],{'operation':'state'}))
        registry.register(dict(approval,memory_mib=128))
        denied(lambda:execute(requests[1],{'operation':'state'}))
        launcher.stop(requests[1])
        print(json.dumps({'scope':'actual disposable systemd application units; providerless',
            'source_commit':os.environ.get('GITHUB_SHA'),'actual_root_launcher':True,
            'actual_dynamic_uids_distinct':True,'actual_private_rootfs_and_networks':True,
            'actual_cgroup_cpu_memory_tasks_limits':True,'actual_window_input_and_capture':True,
            'foreign_mission_and_clipboard_denied':True,'durable_start_replay_denied':True,
            'escaped_child_cgroup_cleanup':True,'other_application_survives_cleanup':True,
            'owner_revoked_application_controls_denied':True,
            'changed_limits_same_elf_controls_denied':True,
            'installed_haos_verified':False,'real_hermes_model_verified':False}),flush=True)
    finally:
        if launcher:
            for request in requests:
                try: launcher.stop(request)
                except (OSError,ValueError,PermissionError,subprocess.SubprocessError):
                    # Only units admitted by this fixture can be stopped here.
                    record=launcher.record(request)
                    subprocess.run(['/usr/bin/systemctl','stop',record['unit']+'.service'],timeout=10,check=False)
        shutil.rmtree(root);shutil.rmtree(code)


if __name__=='__main__': main()
