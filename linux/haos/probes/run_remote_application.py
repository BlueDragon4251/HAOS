"""Real mTLS viewer service → different controller UID → actual private app pixels."""
import base64
import configparser
import hashlib
import json
import os
from pathlib import Path
import pwd
import select
import shutil
import socket
import ssl
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
    source=Path(__file__).resolve().parents[1];sys.path.insert(0,str(source))
    from haos.application_launcher import ApplicationLauncher
    from haos.application_authority import ApplicationAuthority,ActionNonces
    from haos.applications import ApplicationRegistry,executable_digest
    from haos.remote_policy import certificate_identity
    prefix='haos-rv-'+uuid.uuid4().hex[:20];viewer_name=prefix
    code=Path('/usr/lib')/prefix;root=Path('/run')/prefix
    code.mkdir(mode=0o755);root.mkdir(mode=0o755)
    controller=None;launcher=None;nonces=None;instances=[];created_user=False;viewer_started=False
    viewer_unit=prefix+'.service';guardian='haos-app-fixture-'+uuid.uuid4().hex+'.service'
    try:
        subprocess.run(['/usr/sbin/useradd','--system','--user-group','--no-create-home','--shell','/usr/sbin/nologin',viewer_name],check=True,timeout=5)
        created_user=True;viewer=pwd.getpwnam(viewer_name)
        assert viewer.pw_uid not in {0,account.pw_uid}
        def controller_identity():os.setgroups([viewer.pw_gid]);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
        def viewer_identity():os.setgroups([]);os.setgid(viewer.pw_gid);os.setuid(viewer.pw_uid)
        module=code/'haos';shutil.copytree(source/'haos',module,ignore=shutil.ignore_patterns('__pycache__'))
        module.chmod(0o755)
        for path in module.glob('*.py'):path.chmod(0o644)
        for name in ('remote-controller-fixture.py','remote-viewer-service-fixture.py'):
            shutil.copyfile(source/'probes'/name,code/name);(code/name).chmod(0o644)
        init=code/'fixture.bashrc';init.write_text('printf HAOS_REMOTE_READY > .fixture-ready\n');init.chmod(0o644)
        ledger_dir=root/'ledger';ledger_dir.mkdir(mode=0o700);os.chown(ledger_dir,account.pw_uid,account.pw_gid)
        socket_dir=root/'observation';socket_dir.mkdir(mode=0o750);os.chown(socket_dir,account.pw_uid,viewer.pw_gid)
        ledger=ledger_dir/'missions.db';sock=socket_dir/'viewer.sock';policy=root/'policy.json';config=root/'fixture.json'
        config.write_text(json.dumps({'viewer_uid':viewer.pw_uid,'viewer_gid':viewer.pw_gid,'controller_uid':account.pw_uid,
            'socket':str(sock),'policy':str(policy)}));config.chmod(0o644)
        controller=subprocess.Popen(['/usr/bin/python3','-I',str(code/'remote-controller-fixture.py'),str(code),str(ledger),str(config)],
            preexec_fn=controller_identity,env={'PATH':'/usr/bin:/bin','HAOS_DISPOSABLE_CI':'1','PYTHONDONTWRITEBYTECODE':'1'},
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        def read():
            ready,_,_=select.select([controller.stdout],[],[],15);assert ready,'real remote controller reply deadline'
            line=controller.stdout.readline();assert line and len(line.encode())<1500000,'real bounded remote controller reply'
            return json.loads(line)
        first=read();mission=first['mission'];foreign=first['foreign']
        def queue(value):controller.stdin.write(json.dumps(value)+'\n');controller.stdin.flush();return read()
        pki=root/'pki';pki.mkdir(mode=0o700)
        def openssl(*args):subprocess.run(['/usr/bin/openssl',*args],cwd=pki,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        openssl('req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1',
            '-subj','/CN=HAOS Disposable CA','-keyout','ca.key','-out','ca.pem')
        for name,extended in [('server','serverAuth'),('phone','clientAuth'),('unpaired','clientAuth')]:
            openssl('req','-new','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-subj','/CN=Disposable '+name,
                '-keyout',name+'.key','-out',name+'.csr')
            (pki/(name+'.ext')).write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage='+extended+'\nsubjectAltName=IP:127.0.0.1\n')
            openssl('x509','-req','-in',name+'.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial','-days','1',
                '-extfile',name+'.ext','-out',name+'.pem');(pki/(name+'.key')).chmod(0o600)
        fingerprint=certificate_identity(ssl.PEM_cert_to_DER_cert((pki/'phone.pem').read_text()))
        with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        value={'version':1,'bind':'127.0.0.1','port':port,'requests_per_minute':120,'bytes_per_minute':32*1024*1024,
            'devices':[{'id':'fixture-phone','certificate_sha256':fingerprint,'expires_at':time.time()+180,
                'missions':[mission],'content':True,'screenshots':True}]}
        def publish():
            temp=root/'policy.next';temp.write_text(json.dumps(value));os.chown(temp,0,viewer.pw_gid);temp.chmod(0o640)
            os.replace(temp,policy)
        publish()
        parsed=configparser.ConfigParser(interpolation=None);parsed.optionxform=str;parsed.read(source/'haos-remote-viewer.service')
        original=dict(parsed['Service']);properties={key:val for key,val in original.items()
            if key not in {'ExecStart','User','Group','WorkingDirectory','Environment','LoadCredential'}}
        properties.update({'User':viewer_name,'Group':viewer_name,'WorkingDirectory':str(code),'RuntimeMaxSec':'180'})
        command=['/usr/bin/systemd-run','--quiet','--unit='+prefix,'--setenv=GITHUB_ACTIONS=true','--setenv=HAOS_DISPOSABLE_CI=1',
            '--setenv=PYTHONDONTWRITEBYTECODE=1',*['--property='+key+'='+val for key,val in properties.items()],
            '--property=LoadCredential=server-cert:'+str(pki/'server.pem'),'--property=LoadCredential=server-key:'+str(pki/'server.key'),
            '--property=LoadCredential=client-ca:'+str(pki/'ca.pem'),'/usr/bin/python3','-I',str(code/'remote-viewer-service-fixture.py'),str(config)]
        subprocess.run(command,check=True,timeout=5);viewer_started=True
        def viewer_diagnostics():
            status=subprocess.check_output(['/usr/bin/systemctl','show',viewer_unit,
                '--property=ActiveState,Result,ExecMainStatus'],text=True,timeout=3)
            journal=subprocess.check_output(['/usr/bin/journalctl','--unit='+viewer_unit,'--output=cat','--no-pager','-n','10'],text=True,timeout=3)
            fixed=[]
            for line in journal.splitlines():
                if len(line)>256:continue
                try:item=json.loads(line)
                except ValueError:continue
                if isinstance(item,dict) and set(item)=={'event','error'} and item['event']=='remote.fixture.failed' and item['error'] in {
                        'PermissionError','FileNotFoundError','ValueError','OSError','SSLError','KeyError','RuntimeError'}:fixed.append(item)
            return {'unit':dict(line.split('=',1) for line in status.splitlines() if '=' in line),'fixed_errors':fixed}
        deadline=time.monotonic()+15
        while True:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=0.2):break
            except OSError:assert time.monotonic()<deadline,'actual hardened remote TLS listener: '+json.dumps(viewer_diagnostics());time.sleep(0.025)
        pid=int(subprocess.check_output(['/usr/bin/systemctl','show',viewer_unit,'--value','--property=MainPID'],text=True).strip());assert pid>1
        fields=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        assert fields['Uid'].split()==[str(viewer.pw_uid)]*4 and fields['NoNewPrivs'].strip()=='1'
        assert all(int(fields[key].strip(),16)==0 for key in ('CapEff','CapPrm','CapInh','CapAmb'))
        for key,val in original.items():
            if key not in {'ExecStart','User','Group','WorkingDirectory','Environment','LoadCredential'}:assert properties[key]==val
        denied=subprocess.run(['/usr/bin/python3','-I','-c','from pathlib import Path;import sys;Path(sys.argv[1]).read_bytes()',str(pki/'server.key')],
            preexec_fn=viewer_identity,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        assert denied.returncode!=0,'viewer must not read owner credential source'
        def fetch(target,*,certificate='phone',expected=200):
            tls=ssl.create_default_context(cafile=str(pki/'ca.pem'));tls.minimum_version=ssl.TLSVersion.TLSv1_3
            if certificate:tls.load_cert_chain(str(pki/(certificate+'.pem')),str(pki/(certificate+'.key')))
            with socket.create_connection(('127.0.0.1',port),timeout=5) as connection:
                with tls.wrap_socket(connection,server_hostname='127.0.0.1') as peer:
                    assert peer.version()=='TLSv1.3';peer.sendall(f'GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n'.encode())
                    data=bytearray()
                    while block:=peer.recv(65536):data.extend(block);assert len(data)<6*1024*1024
            header,body=data.split(b'\r\n\r\n',1);assert int(header.split()[1])==expected
            assert b'Cache-Control: no-store' in header and b'frame-ancestors' in header
            return body
        assert [r['id'] for r in json.loads(fetch('/api/missions'))]==[mission]
        program="import sys,json,asyncio;sys.path.insert(0,sys.argv[1]);from haos.remote_control import request;asyncio.run(request(json.load(sys.stdin),path=sys.argv[2],controller_uid=int(sys.argv[3])))"
        for identity in (None,controller_identity):
            denied=subprocess.run(['/usr/bin/python3','-I','-c',program,str(code),str(sock),str(account.pw_uid)],
                preexec_fn=identity,input=json.dumps({'method':'missions.list','device':fingerprint,'params':{}}),
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True,timeout=5,env={'PATH':'/usr/bin:/bin'})
            assert denied.returncode!=0,'non-viewer kernel observation peer accepted'
        fetch('/api/mission/'+foreign,expected=403);fetch('/api/missions',certificate='unpaired',expected=403)
        try:fetch('/api/missions',certificate=None)
        except (ssl.SSLError,ConnectionError,ValueError):pass
        else:raise AssertionError('missing client certificate was accepted')
        registry=ApplicationRegistry(root/'applications.json')
        registry.register({'id':'fixture-terminal','class':'terminal','executable':'/usr/bin/foot','sha256':executable_digest('/usr/bin/foot'),
            'argv':['--font','monospace:size=16','/usr/bin/bash','--noprofile','--rcfile',str(init),'-i'],'memory_mib':512,'runtime_seconds':90})
        subprocess.run(['/usr/bin/systemd-run','--quiet','--unit='+guardian,'--property=Type=exec','--property=User='+account.pw_name,
            '--property=NoNewPrivileges=yes','--property=CapabilityBoundingSet=','--property=RuntimeMaxSec=180','/usr/bin/sleep','180'],check=True,timeout=5)
        launcher=ApplicationLauncher(registry,root/'instances',root/'rootfs',module/'application_session.py',guardian=guardian)
        nonces=ActionNonces(root/'actions.db');authority=ApplicationAuthority(launcher,nonces,ledger,account.pw_uid)
        def action(request):
            key=str(uuid.uuid4());queued=queue({'method':'submit','id':key,'action':request})
            assert queued['dispatch']=={'id':key,'mission':mission,'action':request}
            result=authority.dispatch(queued['dispatch']);assert queue({'method':'ack','id':key,'result':result})['accepted'];return result
        launch=action({'operation':'app.start','program':'fixture-terminal'});instance=launch['instance'];instances.append(instance)
        home=Path('/run')/launcher.record(instance)['unit'];deadline=time.monotonic()+15
        while not (home/'.fixture-ready').exists() or not (home/'control.sock').exists():
            assert time.monotonic()<deadline,'actual remote application readiness';time.sleep(0.025)
        while action({'operation':'app.state','instance':instance})['windows']!=1:
            assert time.monotonic()<deadline,'actual remote mapped application';time.sleep(0.025)
        assert action({'operation':'app.focus','instance':instance})['focused']
        before=action({'operation':'app.capture','instance':instance})
        def frame(expected):
            snapshot=json.loads(fetch('/api/applications/'+mission));app=snapshot['applications'][0]
            assert snapshot['mission_active'] and app['instance']==instance and app['program']=='fixture-terminal'
            assert app['capture_sha256']==expected['sha256'] and app['jpeg']==expected['base64']
            assert hashlib.sha256(base64.b64decode(app['jpeg'],validate=True)).hexdigest()==expected['sha256']
        frame(before)
        assert action({'operation':'app.type','instance':instance,'text':'printf HAOS_REMOTE_ACTUAL_TASK > result.txt'})['applied']
        assert action({'operation':'app.key','instance':instance,'key':'Enter'})['applied']
        deadline=time.monotonic()+5
        while not (home/'result.txt').exists() or (home/'result.txt').read_text()!='HAOS_REMOTE_ACTUAL_TASK':
            assert time.monotonic()<deadline,'actual remotely observed task file';time.sleep(0.025)
        after=action({'operation':'app.capture','instance':instance});assert before['sha256']!=after['sha256'];frame(after)
        value['devices'][0]['screenshots']=False;publish();fetch('/api/applications/'+mission,expected=403)
        value['devices'][0]['screenshots']=True;value['devices'][0]['content']=False;publish()
        assert 'goal' not in json.loads(fetch('/api/mission/'+mission))
        value['devices'][0]['expires_at']=time.time()-1;publish();fetch('/api/missions',expected=403)
        value['devices'][0]['expires_at']=time.time()+180;publish()
        assert queue({'method':'cancel'})['cancel_requested']
        assert json.loads(fetch('/api/applications/'+mission))['applications'][0]['jpeg'] is None
        assert authority.reconcile()==[instance]
        value['devices']=[];publish();fetch('/api/missions',expected=403)
        audit=queue({'method':'audit'})
        assert 'HAOS_REMOTE_ACTUAL_TASK' not in json.dumps(audit) and after['base64'] not in json.dumps(audit)
        assert any(e['kind']=='remote.observed' for e in audit['events'])
        print(json.dumps({'scope':'real production TLS viewer properties and separate kernel identities with actual private application frames; disposable providerless CI',
            'source_commit':os.environ['GITHUB_SHA'],'viewer_service_sha256':hashlib.sha256((source/'haos-remote-viewer.service').read_bytes()).hexdigest(),
            'actual_separate_viewer_and_controller_uids':True,'actual_tls13_verified_server_and_client_certificates':True,
            'all_production_viewer_hardening_properties_preserved':True,'actual_viewer_zero_capabilities_and_nnp':True,
            'actual_private_systemd_credential_delivery':True,'viewer_cannot_read_owner_key_source':True,
            'actual_persisted_missions_over_authenticated_kernel_unix':True,'foreign_mission_unpaired_and_missing_certificate_denied':True,
            'actual_root_and_controller_uid_observation_clients_denied':True,
            'actual_wayland_app_input_result_and_two_changed_frames_over_tls':True,
            'actual_consent_expiry_revocation_and_cancel_privacy':True,'actual_cancel_stops_application_cgroup':True,
            'observation_audit_excludes_content_and_pixels':True,'installed_haos_verified':False,'real_browser_device_verified':False,
            'continuous_video_verified':False,'hermes_model_verified':False}),flush=True)
    finally:
        if launcher:
            for instance in instances:launcher.stop(instance)
        if viewer_started:subprocess.run(['/usr/bin/systemctl','stop',viewer_unit],check=False,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['/usr/bin/systemctl','stop',guardian],check=False,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if controller:
            controller.stdin.close()
            try:controller.wait(timeout=5)
            except subprocess.TimeoutExpired:controller.kill();controller.wait(timeout=3)
        if nonces:nonces.close()
        for directory in (root,code):
            if directory.exists():shutil.rmtree(directory)
        if created_user:
            subprocess.run(['/usr/sbin/userdel',viewer_name],check=True,timeout=5)
            subprocess.run(['/usr/sbin/groupdel',viewer_name],check=False,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
