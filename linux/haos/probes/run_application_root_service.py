"""Real production root-service properties, socket roles, app input and kill gate."""
import base64
import configparser
import hashlib
import json
import os
from pathlib import Path
import pwd
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
        raise PermissionError('explicit disposable systemd runner required')
    account=pwd.getpwnam(os.environ['SUDO_USER']);assert account.pw_uid>=1000
    source=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(source))
    from haos.applications import ApplicationRegistry,executable_digest
    prefix='haos-app-fixture-'+uuid.uuid4().hex
    code=Path('/usr/lib')/prefix;state=Path('/var/lib')/prefix;runtime=Path('/run')/prefix
    control=Path('/run')/(prefix+'-control');ledger_dir=Path('/run')/(prefix+'-ledger')
    code.mkdir(mode=0o755);state.mkdir(mode=0o700);ledger_dir.mkdir(mode=0o700)
    os.chown(ledger_dir,account.pw_uid,account.pw_gid)
    controller=None;instances=[];unit=prefix+'.service';started=False
    def identity():os.setgroups([]);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
    try:
        shutil.copytree(source/'haos',code/'haos',ignore=shutil.ignore_patterns('__pycache__'))
        (code/'haos').chmod(0o755)
        for file in (code/'haos').glob('*.py'):file.chmod(0o644)
        for name in ('application-root-service-fixture.py','application-controller-fixture.py'):
            shutil.copyfile(source/'probes'/name,code/name);(code/name).chmod(0o644)
        initialization=code/'fixture.bashrc';initialization.write_text('printf HAOS_REAL_SHELL > .fixture-ready\n');initialization.chmod(0o644)
        ledger=ledger_dir/'missions.db'
        controller=subprocess.Popen(['/usr/bin/python3','-I',str(code/'application-controller-fixture.py'),str(code),str(ledger)],
            preexec_fn=identity,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','HAOS_DISPOSABLE_CI':'1'},
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        mission=json.loads(controller.stdout.readline())['mission']
        def queue(value):
            controller.stdin.write(json.dumps(value)+'\n');controller.stdin.flush()
            value=controller.stdout.readline();assert value,'actual persistent controller fixture exited'
            return json.loads(value)
        registry=ApplicationRegistry(state/'applications.json')
        registry.register({'id':'fixture-terminal','class':'terminal','executable':'/usr/bin/foot',
            'sha256':executable_digest('/usr/bin/foot'),'argv':['--font','monospace:size=16','/usr/bin/bash','--noprofile','--rcfile',str(initialization),'-i'],
            'memory_mib':512,'runtime_seconds':90})
        sock=control/'control.sock'
        config=state/'fixture.json';config.write_text(json.dumps({'registry':str(registry.path),'state':str(state),
            'runtime':str(runtime),'ledger':str(ledger),'controller_uid':account.pw_uid,'guardian':unit,'socket':str(sock)}));config.chmod(0o600)
        parsed=configparser.ConfigParser(interpolation=None);parsed.optionxform=str;parsed.read(source/'haos-applications.service')
        original=dict(parsed['Service'])
        properties={key:value for key,value in original.items() if key not in {'ExecStart','WorkingDirectory','Environment','StateDirectory','RuntimeDirectory'}}
        properties.update({'WorkingDirectory':str(code),'StateDirectory':prefix,'RuntimeDirectory':prefix,'RuntimeMaxSec':'180'})
        command=['/usr/bin/systemd-run','--quiet','--unit='+prefix,
            '--socket-property=ListenStream='+str(sock),'--socket-property=SocketUser=root',
            '--socket-property=SocketGroup='+account.pw_name,'--socket-property=SocketMode=0660','--socket-property=DirectoryMode=0755',
            '--setenv=GITHUB_ACTIONS=true','--setenv=HAOS_DISPOSABLE_CI=1','--setenv=PYTHONDONTWRITEBYTECODE=1',
            *['--property='+key+'='+value for key,value in properties.items()],'/usr/bin/python3','-I',
            str(code/'application-root-service-fixture.py'),str(config)]
        subprocess.run(command,check=True,timeout=5);started=True
        deadline=time.monotonic()+10
        while not sock.exists():assert time.monotonic()<deadline,'actual root socket activation';time.sleep(0.025)
        def transport(value,*,denied=False):
            program="import sys,json;sys.path.insert(0,sys.argv[1]);from pathlib import Path;from haos.application_client import request;print(json.dumps(request(json.load(sys.stdin),path=Path(sys.argv[2]))))"
            result=subprocess.run(['/usr/bin/python3','-I','-c',program,str(code),str(sock)],preexec_fn=identity,
                input=json.dumps(value),capture_output=True,text=True,timeout=15,env={'PATH':'/usr/bin:/bin'})
            if denied:assert result.returncode!=0;return None
            assert result.returncode==0,'actual hardened root transport failed'
            return json.loads(result.stdout)
        assert transport({'method':'health'})['available']
        broker=subprocess.run(['/usr/bin/systemctl','show',unit,'--property=MainPID'],capture_output=True,text=True,check=True).stdout
        pid=int(broker.strip().split('=',1)[1]);assert pid>1
        fields=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        assert fields['Uid'].split()==['0']*4 and fields['NoNewPrivs'].strip()=='1'
        assert int(fields['CapEff'].strip(),16)==sum(1<<bit for bit in (1,5,6,7)), json.dumps({
            'fixed_root_capability_diagnostics':{key:fields[key].strip() for key in ('CapEff','CapPrm','CapBnd','CapAmb')}})
        assert os.readlink(f'/proc/{pid}/ns/net')!=os.readlink('/proc/self/ns/net')
        for key,value in original.items():
            if key not in {'ExecStart','WorkingDirectory','Environment','StateDirectory','RuntimeDirectory'}:assert properties[key]==value
        with socket.socket(socket.AF_UNIX) as peer:
            peer.connect(str(sock));peer.sendall(b'{"method":"health"}\n');assert json.loads(peer.recv(256))['ok'] is False
        def action(value):
            key=str(uuid.uuid4());queued=queue({'method':'submit','id':key,'action':value})
            assert queued['dispatch']=={'id':key,'mission':mission,'action':value}
            result=transport(queued['dispatch']);transport(queued['dispatch'],denied=True)
            assert queue({'method':'ack','id':key,'result':result})['accepted'];return result
        assert action({'operation':'app.catalog'})['programs'][0]['program']=='fixture-terminal'
        launch=action({'operation':'app.start','program':'fixture-terminal'});instance=launch['instance'];instances.append(instance)
        record=json.loads((state/'instances'/(instance+'.json')).read_text());home=Path('/run')/record['unit']
        def startup_diagnostics():
            app_unit=record['unit']+'.service'
            status=subprocess.run(['/usr/bin/systemctl','show',app_unit,'--property=LoadState,ActiveState,MainPID,Result,ExecMainStatus'],
                capture_output=True,text=True,check=True,timeout=3).stdout
            journal=subprocess.run(['/usr/bin/journalctl','--unit='+app_unit,'--output=cat','--no-pager','-n','30'],
                capture_output=True,text=True,check=True,timeout=3).stdout
            phases=[]
            for line in journal.splitlines():
                if len(line)>512:continue
                try:item=json.loads(line)
                except ValueError:continue
                if (isinstance(item,dict) and set(item)<={'event','stage','error'} and item.get('event')=='application.session'
                        and item.get('stage') in {'credential','hardening','identity','compositor','keyboard','application','control','failed'}
                        and item.get('error') in {None,'ValueError','KeyError','PermissionError','RuntimeError','TimeoutError','OSError',
                            'JSONDecodeError','FileNotFoundError','TypeError','unexpected-error'}):phases.append(item)
            return {'fixed_unit_status':dict(line.split('=',1) for line in status.splitlines() if '=' in line),'fixed_session_phases':phases}
        deadline=time.monotonic()+15
        while not (home/'.fixture-ready').exists() or not (home/'control.sock').exists():
            assert time.monotonic()<deadline,'actual hardened broker application readiness: '+json.dumps(startup_diagnostics())
            time.sleep(0.025)
        while action({'operation':'app.state','instance':instance})['windows']!=1:
            assert time.monotonic()<deadline,'actual hardened broker mapped window';time.sleep(0.05)
        assert action({'operation':'app.focus','instance':instance})['focused']
        before=action({'operation':'app.capture','instance':instance})
        assert action({'operation':'app.type','instance':instance,'text':'printf HAOS_ROOT_SERVICE_RESULT > hardened-result.txt'})['applied']
        assert action({'operation':'app.key','instance':instance,'key':'Enter'})['applied']
        deadline=time.monotonic()+5
        while not (home/'hardened-result.txt').exists():assert time.monotonic()<deadline,'actual hardened application result';time.sleep(0.025)
        assert (home/'hardened-result.txt').read_text()=='HAOS_ROOT_SERVICE_RESULT'
        after=action({'operation':'app.capture','instance':instance})
        assert before['sha256']!=after['sha256']
        for frame in (before,after):assert hashlib.sha256(base64.b64decode(frame['base64'],validate=True)).hexdigest()==frame['sha256']
        subprocess.run(['/usr/bin/systemctl','kill','--signal=SIGKILL',unit],check=True,timeout=5)
        deadline=time.monotonic()+5
        while home.exists():assert time.monotonic()<deadline,'actual PID1 hardened broker-loss app cleanup';time.sleep(0.025)
        print(json.dumps({'scope':'actual production root-service hardening in a disposable socket-activated CI fixture',
            'source_commit':os.environ['GITHUB_SHA'],'root_service_source_sha256':hashlib.sha256((source/'haos-applications.service').read_bytes()).hexdigest(),
            'actual_root_capabilities_exactly_four':True,'actual_root_no_new_privileges_and_private_network':True,
            'all_production_service_hardening_properties_preserved':True,'actual_root_and_controller_kernel_socket_roles':True,
            'actual_uid_dropped_wal_authorization_under_strict_filesystem':True,'actual_owner_catalog_and_nonce_replay_denial':True,
            'actual_real_terminal_input_result_and_capture':True,'actual_pid1_broker_sigkill_application_cleanup':True,
            'installed_haos_verified':False,'hermes_model_verified':False}),flush=True)
    finally:
        if started:
            subprocess.run(['/usr/bin/systemctl','stop',prefix+'.socket',unit],check=False,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for instance in instances:
            subprocess.run(['/usr/bin/systemctl','stop','haos-app-'+instance.replace('-','')+'.service'],check=False,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if controller:
            controller.stdin.close()
            try:controller.wait(timeout=5)
            except subprocess.TimeoutExpired:controller.kill();controller.wait(timeout=3)
        for directory in (code,state,runtime,control,ledger_dir):
            if directory.exists():shutil.rmtree(directory)


if __name__=='__main__':main()
