"""Actual UID/SQLite/lease/filesystem status read without optional SDK imports."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_HEALTH_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh explicit readonly status namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    state=Path('/var/lib/haos-gateway');state.mkdir(mode=0o700);os.chown(state,65534,65534)
    driver=Path('/usr/lib/haos/status-fixture.py');driver.write_text('''import json,os,sys,time
from pathlib import Path
sys.path.insert(0,'/usr/lib/haos')
from haos.gateway_google_chat_health import read
params={'connector':'google','credential_scope':'a'*64,'account_scope':'google-chat:'+'b'*64}
path=Path('/var/lib/haos-gateway/native-inbox.db')
if len(sys.argv)>1:
 try:read(path,params,lambda:None)
 except PermissionError:pass
 else:raise AssertionError('foreign UID entered native status reader')
 assert not any(name.startswith(('google.','googleapiclient','plugins.')) for name in sys.modules)
 print(json.dumps({'denied_before_optional_SDK':True}));raise SystemExit(3)
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from haos.gateway_matrix_profile import acquire_lease
cases=[];checks=[]
value=read(path,params,lambda:checks.append(True))
assert value['status']=='not-started' and not path.exists() and value['updated_at'] is None and len(checks)==2
cases.append('actual_private_UID_absent_status_is_explicit_and_never_creates_a_journal')
inbox=NativeInbox(path,Redactor([]));db=inbox.db
db.execute('CREATE TABLE google_chat_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
db.execute('CREATE TABLE google_chat_profile_budget(scope TEXT PRIMARY KEY,not_before REAL)')
db.execute('INSERT INTO google_chat_profile_status VALUES(?,?,?,?,?,?)',('current','google','a'*64,'authentication-refused',10,20))
db.execute('INSERT INTO google_chat_profile_status VALUES(?,?,?,?,?,?)',('foreign','google','c'*64,'connected-pull',100,900))
db.execute('INSERT INTO google_chat_profile_budget VALUES(?,?)',(params['account_scope'],180))
db.execute('INSERT INTO google_chat_profile_budget VALUES(?,?)',('google-chat:'+'c'*64,900))
before=[tuple(row) for row in db.execute('SELECT * FROM google_chat_profile_status')],list(db.execute('SELECT * FROM google_chat_profile_budget'))
value=read(path,params,lambda:None)
assert value['status']=='authentication-refused' and value['updated_at']==10 and value['next_attempt']==180
assert value['observed_only'] and not value['live_transport_verified'] and not value['network_requested']
assert before==([tuple(row) for row in db.execute('SELECT * FROM google_chat_profile_status')],list(db.execute('SELECT * FROM google_chat_profile_budget')))
cases.append('actual_SQLite_WAL_snapshot_selects_exact_credential_epoch_and_account_budget_without_mutation_reset_or_foreign_status')
profile=path.parent/'profile';profile.mkdir(mode=0o700);lease=acquire_lease(profile)
try:assert read(path,params,lambda:None)==value
finally:os.close(lease)
cases.append('actual_kernel_profile_lease_does_not_block_read_only_status_or_require_service_stop')
db.execute("UPDATE google_chat_profile_status SET status='must-not-return-private-data' WHERE identity='current'")
try:read(path,params,lambda:None)
except ValueError:pass
else:raise AssertionError('private malformed status returned')
assert db.execute("SELECT status FROM google_chat_profile_status WHERE identity='current'").fetchone()[0]=='must-not-return-private-data'
db.execute("UPDATE google_chat_profile_status SET status='authentication-refused' WHERE identity='current'")
cases.append('malformed_private_status_is_refused_without_returning_or_repairing_its_payload')
for selected in [path,path.with_name(path.name+'-wal')]:
 assert selected.exists();selected.chmod(0o644)
 try:read(path,params,lambda:None)
 except PermissionError:pass
 else:raise AssertionError('unsafe native status custody accepted')
 assert selected.stat().st_mode&0o777==0o644;selected.chmod(0o600)
cases.append('actual_kernel_database_and_WAL_permissions_are_checked_without_automatic_custody_repair')
alias=path.with_name('alias.db');os.link(path,alias)
try:
 try:read(path,params,lambda:None)
 except PermissionError:pass
 else:raise AssertionError('hardlinked status accepted')
 assert alias.exists()
finally:alias.unlink()
link=path.with_name('symlink.db');link.symlink_to(path)
try:read(link,params,lambda:None)
except (PermissionError,OSError):pass
else:raise AssertionError('symlink status accepted')
assert link.is_symlink();inbox.close()
cases.append('actual_hardlink_and_symlink_status_paths_are_refused_and_preserved')
assert not any(name.startswith(('google.','googleapiclient','plugins.')) for name in sys.modules)
print(json.dumps({'passed':len(cases),'cases':cases,'actual_UID_SQLite_WAL_kernel_lease_and_filesystem':True,'optional_Google_SDK_or_Hermes_imported':False}))
''');driver.chmod(0o644)
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    for uid,groups in [(0,()),(65533,()),(65534,(0,))]:
        result=subprocess.run([sys.executable,'-E','-s',str(driver),'denied'],capture_output=True,text=True,user=uid,group=uid,
            extra_groups=list(groups),env=env,timeout=15)
        assert result.returncode==3 and json.loads(result.stdout)=={'denied_before_optional_SDK':True},result.stderr
    result=subprocess.run([sys.executable,'-E','-s',str(driver)],capture_output=True,text=True,user=65534,group=65534,extra_groups=[],env=env,timeout=20,umask=0o077)
    assert result.returncode==0 and not result.stderr,result.stderr
    value=json.loads(result.stdout);value['foreign_Root_agent_and_supplementary_Root_group_denied_before_optional_imports']=True
    print(json.dumps(value,indent=2))


if __name__=='__main__':main()
