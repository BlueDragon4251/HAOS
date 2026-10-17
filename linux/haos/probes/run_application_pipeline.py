"""Real persistent GUI queue → kernel-authenticated Root → actual Wayland app.

An explicitly providerless disposable CI fixture; never a model/gateway proof.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    if (os.geteuid()!=0 or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('HAOS_DISPOSABLE_CI')!='1'
            or Path('/proc/1/comm').read_text().strip()!='systemd'):
        raise PermissionError('explicit disposable systemd CI runner required')
    account=pwd.getpwnam(os.environ['SUDO_USER'])
    if account.pw_uid<1000:raise PermissionError('separate unprivileged controller required')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from haos.application_launcher import ApplicationLauncher
    from haos.application_authority import ApplicationAuthority,ActionNonces
    from haos.application_server import handle
    from haos.applications import ApplicationRegistry,executable_digest
    root=Path(tempfile.mkdtemp(prefix='haos-app-pipeline-',dir='/run'));root.chmod(0o755)
    code=Path(tempfile.mkdtemp(prefix='haos-app-pipeline-',dir='/usr/lib'));code.chmod(0o755)
    controller=None;launcher=None;nonces=None;listener=None;instances=[]
    guardian='haos-app-fixture-'+uuid.uuid4().hex+'.service'
    def identity():os.setgroups([]);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
    try:
        module=code/'haos';module.mkdir(mode=0o755)
        for source in (Path(__file__).resolve().parents[1]/'haos').glob('*.py'):
            shutil.copyfile(source,module/source.name);(module/source.name).chmod(0o644)
        fixture=code/'controller.py';shutil.copyfile(Path(__file__).with_name('application-controller-fixture.py'),fixture);fixture.chmod(0o644)
        initialization=code/'fixture.bashrc';initialization.write_text('printf HAOS_REAL_SHELL_READY > .fixture-ready\n');initialization.chmod(0o644)
        ledger_dir=root/'ledger';ledger_dir.mkdir(mode=0o700);os.chown(ledger_dir,account.pw_uid,account.pw_gid)
        ledger=ledger_dir/'missions.db'
        controller=subprocess.Popen(['/usr/bin/python3','-I',str(fixture),str(code),str(ledger)],
            preexec_fn=identity,env={'PATH':'/usr/bin:/bin','HAOS_DISPOSABLE_CI':'1'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        def read():
            ready,_,_=select.select([controller.stdout],[],[],15)
            assert ready,'real controller fixture reply deadline'
            line=controller.stdout.readline();assert line and len(line.encode())<1500000
            return json.loads(line)
        mission=read()['mission']
        def control(value):
            controller.stdin.write(json.dumps(value)+'\n');controller.stdin.flush();return read()
        registry=ApplicationRegistry(root/'applications.json')
        registry.register({'id':'fixture-terminal','class':'terminal','executable':'/usr/bin/foot','sha256':executable_digest('/usr/bin/foot'),
            'argv':['--font','monospace:size=16','/usr/bin/bash','--noprofile','--rcfile',str(initialization),'-i'],
            'memory_mib':512,'runtime_seconds':60})
        subprocess.run(['/usr/bin/systemd-run','--quiet','--unit='+guardian,'--property=Type=exec',
            '--property=User='+account.pw_name,'--property=NoNewPrivileges=yes','--property=CapabilityBoundingSet=',
            '--property=RuntimeMaxSec=180','--property=MemoryMax=16M','--property=TasksMax=1','/usr/bin/sleep','180'],check=True,timeout=5)
        launcher=ApplicationLauncher(registry,root/'instances',root/'rootfs',module/'application_session.py',guardian=guardian)
        nonces=ActionNonces(root/'actions.db');authority=ApplicationAuthority(launcher,nonces,ledger,account.pw_uid)
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.settimeout(5)
        path=root/'control.sock';listener.bind(str(path));os.chown(path,0,account.pw_gid);os.chmod(path,0o660);listener.listen(4)
        def transport(value,*,denied=False,as_root=False):
            client=subprocess.Popen(['/usr/bin/python3','-I','-c',
                "import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from haos.application_client import request;print(json.dumps(request(json.loads(sys.argv[3]),Path(sys.argv[2]))))",
                str(code),str(path),json.dumps(value)],preexec_fn=None if as_root else identity,
                env={'PATH':'/usr/bin:/bin'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            peer,_=listener.accept()
            with peer:
                try:handle(peer,authority,account.pw_uid)
                except PermissionError:
                    assert denied,'unexpected root authority denial'
                    peer.sendall(b'{"ok":false,"result":null}\n')
            out,error=client.communicate(timeout=15)
            if denied:assert client.returncode!=0;return None
            assert client.returncode==0,'real kernel application transport failed: '+error[:512]
            return json.loads(out)
        assert transport({'method':'health'})['available']
        transport({'method':'health'},denied=True,as_root=True)
        def action(value,*,reattach=False):
            key=str(uuid.uuid4());queued=control({'method':'submit','id':key,'action':value})
            assert queued['admission']['state']=='pending' and queued['dispatch']=={'id':key,'mission':mission,'action':value}
            if reattach:
                assert control({'method':'reattach'})['attached']
                assert control({'method':'result','id':key})['state']=='dispatched'
            result=transport(queued['dispatch'])
            transport(queued['dispatch'],denied=True)
            assert control({'method':'ack','id':key,'result':result})['accepted']
            return result
        catalog=action({'operation':'app.catalog'})
        assert catalog=={'programs':[{'program':'fixture-terminal','class':'terminal','approved_sha256':executable_digest('/usr/bin/foot'),
            'memory_mib':512,'runtime_seconds':60}]}
        assert str(initialization) not in json.dumps(catalog) and '--rcfile' not in json.dumps(catalog)
        result=action({'operation':'app.start','program':'fixture-terminal'},reattach=True)
        instance=result['instance'];instances.append(instance)
        home=Path('/run')/launcher.record(instance)['unit'];deadline=time.monotonic()+15
        while not (home/'.fixture-ready').exists() or not (home/'control.sock').exists():
            assert time.monotonic()<deadline,'actual application readiness';time.sleep(0.025)
        while launcher.execute(instance,mission,{'operation':'state'},ledger=ledger,ledger_uid=account.pw_uid)['windows']!=1:
            assert time.monotonic()<deadline,'actual application mapping';time.sleep(0.025)
        assert action({'operation':'app.focus','instance':instance})['focused']
        before=action({'operation':'app.capture','instance':instance})
        assert action({'operation':'app.type','instance':instance,'text':'printf HAOS_REAL_QUEUE > queue-result.txt'})['applied']
        assert action({'operation':'app.key','instance':instance,'key':'Enter'})['applied']
        deadline=time.monotonic()+5
        while not (home/'queue-result.txt').exists() or (home/'queue-result.txt').read_text()!='HAOS_REAL_QUEUE':
            assert time.monotonic()<deadline,'real queued terminal result';time.sleep(0.025)
        after=action({'operation':'app.capture','instance':instance})
        for image in (before,after):
            data=base64.b64decode(image['base64'],validate=True)
            assert len(data)==image['bytes'] and hashlib.sha256(data).hexdigest()==image['sha256']
        assert before['sha256']!=after['sha256']
        assert action({'operation':'app.type','instance':instance,'text':'cp queue-result.txt exports/queue-result.txt'})['applied']
        assert action({'operation':'app.key','instance':instance,'key':'Enter'})['applied']
        deadline=time.monotonic()+5
        while not (home/'exports/queue-result.txt').exists() or (home/'exports/queue-result.txt').read_text()!='HAOS_REAL_QUEUE':
            assert time.monotonic()<deadline,'real queued output export completion';time.sleep(0.025)
        exported=action({'operation':'app.export','instance':instance,'file':'queue-result.txt'})
        assert base64.b64decode(exported['base64'],validate=True)==b'HAOS_REAL_QUEUE'
        assert exported['bytes']==len(b'HAOS_REAL_QUEUE') and exported['sha256']==hashlib.sha256(b'HAOS_REAL_QUEUE').hexdigest()
        assert control({'method':'reattach'})['attached']
        assert action({'operation':'app.state','instance':instance})['running']
        audit=control({'method':'audit'})
        assert 'HAOS_REAL_QUEUE' not in json.dumps(audit) and after['base64'] not in json.dumps(audit) and exported['base64'] not in json.dumps(audit)
        assert audit['action_count']==11 and sum(e['kind']=='gui.succeeded' for e in audit['events'])==11
        assert sum(e['kind']=='gui.succeeded' and e['payload']['operation'] not in {'app.catalog','app.export'} for e in audit['events'])==9
        assert {e['payload']['operation'] for e in audit['events'] if e['kind']=='gui.succeeded'}=={
            'app.catalog','app.start','app.focus','app.capture','app.type','app.key','app.export','app.state'}
        assert control({'method':'cancel'})['cancel_requested']
        assert authority.reconcile()==[instance]
        assert launcher.record(instance)['state']=='stopped'
        print(json.dumps({'scope':'actual disposable persistent GUI queue and root/kernel application pipeline; providerless',
            'source_commit':os.environ.get('GITHUB_SHA'),'actual_unprivileged_persistent_gui_queue':True,
            'actual_root_server_and_client_kernel_identity':True,'non_controller_root_peer_denied':True,
            'actual_matching_wal_dispatch_authority':True,'root_action_replays_denied':True,
            'actual_owner_program_discovery_without_arguments':True,
            'actual_terminal_input_result_and_capture':True,'native_reattach_preserves_application':True,
            'actual_private_output_export_bytes_and_hash':True,'export_bytes_absent_from_persistent_audit':True,
            'audit_has_no_typed_contents_or_pixels':True,'cancel_reconciles_entire_application':True,
            'production_broker_service_verified':False,'installed_haos_verified':False,'hermes_model_verified':False}),flush=True)
    finally:
        if launcher:
            for instance in instances:launcher.stop(instance)
        if controller:
            controller.stdin.close()
            try:controller.wait(timeout=5)
            except subprocess.TimeoutExpired:controller.kill();controller.wait(timeout=3)
            controller.stdout.close()
        if nonces:nonces.close()
        if listener:listener.close()
        shutil.rmtree(root);shutil.rmtree(code)
        subprocess.run(['/usr/bin/systemctl','stop',guardian],check=False,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
