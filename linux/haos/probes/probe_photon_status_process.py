"""Actual UID/SQLite/WAL/lease status read, with no optional runtime installed."""
import json
import os
from pathlib import Path
import subprocess
import sys


DRIVER = '''import json,os,sys
from pathlib import Path
sys.path.insert(0,'/usr/lib/haos')
from haos.gateway_photon_status import read
params={'connector':'phone','credential_scope':'a'*64,'account_scope':'photon:'+'b'*64}
path=Path('/var/lib/haos-gateway/native-inbox.db')
if len(sys.argv)>1:
 try:read(path,params,lambda:None)
 except PermissionError:pass
 else:raise AssertionError('foreign identity entered Photon status reader')
 print(json.dumps({'denied_before_optional_SDK':True}));raise SystemExit(3)
from haos.gateway_raw import NativeInbox
from haos.gateway_photon_custody import Originals
from haos.redaction import Redactor
from haos.gateway_matrix_profile import acquire_lease
cases=[];checks=[]
value=read(path,params,lambda:checks.append(True))
assert value['status']=='not-started' and value['updated_at'] is None and not path.exists() and len(checks)==2
cases.append('actual_private_UID_absent_status_never_creates_a_journal')
inbox=NativeInbox(path,Redactor([]));db=inbox.db
db.execute('CREATE TABLE photon_profile_status(id TEXT PRIMARY KEY,account_scope TEXT,credential_scope TEXT,connector TEXT,status TEXT,updated_at REAL)')
db.execute('CREATE TABLE photon_account_budget(account_scope TEXT PRIMARY KEY,next_attempt REAL)')
db.execute('INSERT INTO photon_profile_status VALUES(?,?,?,?,?,?)',('current',params['account_scope'],'a'*64,'phone','authentication-refused',10))
db.execute('INSERT INTO photon_profile_status VALUES(?,?,?,?,?,?)',('foreign-key',params['account_scope'],'c'*64,'phone','upstream-observed',100))
db.execute('INSERT INTO photon_profile_status VALUES(?,?,?,?,?,?)',('foreign-account','photon:'+'c'*64,'a'*64,'phone','upstream-observed',100))
db.execute('INSERT INTO photon_profile_status VALUES(?,?,?,?,?,?)',('foreign-connector',params['account_scope'],'a'*64,'other','upstream-observed',100))
db.execute('INSERT INTO photon_account_budget VALUES(?,?)',(params['account_scope'],180))
db.execute('INSERT INTO photon_account_budget VALUES(?,?)',('photon:'+'c'*64,900))
profiles=path.parent/'profiles';profiles.mkdir(mode=0o700)
profile=profiles/('photon-'+'b'*64);profile.mkdir(mode=0o700)
originals=Originals(profile/'originals.db',Redactor([]),lambda:None)
before=[tuple(row) for row in db.execute('SELECT * FROM photon_profile_status')],[tuple(row) for row in db.execute('SELECT * FROM photon_account_budget')]
value=read(path,params,lambda:None)
assert value['status']=='authentication-refused' and value['updated_at']==10 and value['next_attempt']==180
assert value['observed_only'] and not value['live_transport_verified'] and not value['network_requested'] and not value['private_credentials_returned']
assert before==([tuple(row) for row in db.execute('SELECT * FROM photon_profile_status')],[tuple(row) for row in db.execute('SELECT * FROM photon_account_budget')])
cases.append('actual_WAL_snapshot_selects_exact_account_credential_connector_without_mutation')
rotated=read(path,{**params,'credential_scope':'d'*64},lambda:None)
assert rotated['status']=='not-started' and rotated['updated_at'] is None and rotated['next_attempt']==180
cases.append('rotated_key_without_profile_cannot_hide_persisted_account_retry_budget')
lease=acquire_lease(profile)
try:assert read(path,params,lambda:None)==value
finally:os.close(lease)
cases.append('actual_kernel_profile_lease_does_not_block_readonly_status_or_require_service_stop')
def denied(reason,expected=ValueError):
 try:read(path,params,lambda:None)
 except expected:pass
 else:raise AssertionError(reason)
db.execute("UPDATE photon_profile_status SET status='must-not-return-private-data' WHERE id='current'")
denied('private malformed status returned')
assert db.execute("SELECT status FROM photon_profile_status WHERE id='current'").fetchone()[0]=='must-not-return-private-data'
db.execute("UPDATE photon_profile_status SET status='authentication-refused' WHERE id='current'")
db.execute('DELETE FROM photon_account_budget WHERE account_scope=?',(params['account_scope'],))
denied('missing budget became ready status')
assert db.execute('SELECT 1 FROM photon_account_budget WHERE account_scope=?',(params['account_scope'],)).fetchone() is None
db.execute('INSERT INTO photon_account_budget VALUES(?,?)',(params['account_scope'],180))
db.execute('UPDATE photon_account_budget SET next_attempt=? WHERE account_scope=?',(float('inf'),params['account_scope']))
denied('unbounded retry budget returned')
db.execute('UPDATE photon_account_budget SET next_attempt=180 WHERE account_scope=?',(params['account_scope'],))
db.execute('ALTER TABLE photon_account_budget RENAME TO retained_damaged_budget')
denied('incomplete journal interpreted as a fresh account')
assert db.execute("SELECT 1 FROM sqlite_master WHERE name='photon_account_budget'").fetchone() is None
db.execute('ALTER TABLE retained_damaged_budget RENAME TO photon_account_budget')
cases.append('malformed_status_missing_budget_and_partial_schema_refused_without_repair_or_private_payload')
for selected in [path,path.with_name(path.name+'-wal'),path.with_name(path.name+'-shm')]:
 assert selected.exists();selected.chmod(0o644)
 denied('unsafe native status custody accepted',PermissionError)
 assert selected.stat().st_mode&0o777==0o644;selected.chmod(0o600)
cases.append('actual_kernel_database_WAL_and_SHM_permissions_checked_without_repair')
alias=path.with_name('alias.db');os.link(path,alias)
try:denied('hardlinked status accepted',PermissionError);assert alias.exists()
finally:alias.unlink()
link=path.with_name('symlink.db');link.symlink_to(path)
try:read(link,params,lambda:None)
except (PermissionError,OSError):pass
else:raise AssertionError('symlink status accepted')
assert link.is_symlink()
cases.append('actual_hardlink_and_symlink_status_paths_refused_and_preserved')
db.execute("UPDATE photon_profile_status SET id=? WHERE id='current'",('1'*64,))
originals.db.execute('CREATE TABLE photon_health_profiles(id TEXT PRIMARY KEY,account_scope TEXT,credential_scope TEXT)')
originals.db.execute('INSERT INTO photon_health_profiles VALUES(?,?,?)',('1'*64,params['account_scope'],params['credential_scope']))
assert read(path,params,lambda:None)==value
saved=db.execute('SELECT * FROM photon_profile_status WHERE id=?',('1'*64,)).fetchone()
db.execute('DELETE FROM photon_profile_status WHERE id=?',('1'*64,));denied('lost known status became fresh account')
try:read(path,{**params,'credential_scope':'d'*64},lambda:None)
except ValueError:pass
else:raise AssertionError('key rotation concealed lost status provenance')
assert db.execute('SELECT 1 FROM photon_profile_status WHERE id=?',('1'*64,)).fetchone() is None
db.execute('INSERT INTO photon_profile_status VALUES(?,?,?,?,?,?)',tuple(saved))
cases.append('actual_cross_journal_provenance_exposes_lost_status_even_after_key_rotation_without_recreation')
originals.close();source=profile/'originals.db';retained=profile/'originals.retained-fixture'
source.rename(retained);denied('known missing original journal became not started')
assert not source.exists() and retained.exists();retained.rename(source)
originals=Originals(source,Redactor([]),lambda:None)
cases.append('actual_missing_original_journal_is_reported_without_creating_a_replacement')
inbox.close();retained_native=path.with_name('native.retained-fixture');path.rename(retained_native)
denied('missing central native journal concealed retained original provenance')
assert not path.exists() and retained_native.exists();retained_native.rename(path)
inbox=NativeInbox(path,Redactor([]));db=inbox.db
cases.append('actual_missing_central_status_journal_is_refused_beside_retained_originals_without_creation')
originals.db.execute('ALTER TABLE photon_originals RENAME TO retained_original_schema')
import sqlite3
denied('missing original schema was hidden from recorded status',sqlite3.Error)
assert not originals.db.execute("SELECT 1 FROM sqlite_master WHERE name='photon_originals'").fetchone()
assert originals.db.execute("SELECT 1 FROM sqlite_master WHERE name='retained_original_schema'").fetchone()
originals.db.execute('ALTER TABLE retained_original_schema RENAME TO photon_originals')
cases.append('actual_incomplete_original_schema_is_refused_without_repair_by_readonly_status')
def withdrawn():raise PermissionError('owner selection withdrawn')
try:read(path,params,withdrawn)
except PermissionError:pass
else:raise AssertionError('withdrawn owner selection read status')
inbox.close();originals.close()
assert not any(name.startswith(('plugins.','httpx','aiohttp','google.')) for name in sys.modules)
cases.append('withdrawn_authority_denied_and_optional_network_SDKs_never_imported')
print(json.dumps({'passed':len(cases),'cases':cases,'actual_UID_SQLite_WAL_kernel_lease_and_filesystem':True,'optional_SDK_or_Hermes_imported':False,'network_requested':False}))
'''


def main():
    if (os.geteuid() != 0 or os.getpid() != 1 or os.environ.get('HAOS_DISPOSABLE_PHOTON_STATUS_PROCESS') != '1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag & os.ST_RDONLY):
        raise PermissionError('fresh explicit readonly Photon status namespace required')
    code = Path('/usr/lib/haos'); code.mkdir(mode=0o755)
    subprocess.run([sys.executable, '/repo/linux/haos/runtime/install_package.py', '/repo/linux/haos/haos', str(code / 'haos')], check=True)
    with Path('/etc/passwd').open('a') as stream:
        stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    state = Path('/var/lib/haos-gateway'); state.mkdir(mode=0o700); os.chown(state, 65534, 65534)
    driver = code / 'status-fixture.py'; driver.write_text(DRIVER); driver.chmod(0o644)
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    for uid, groups in [(0, ()), (65533, ()), (65534, (0,))]:
        result = subprocess.run([sys.executable, '-E', '-s', str(driver), 'denied'], capture_output=True, text=True,
            user=uid, group=uid, extra_groups=list(groups), env=env, timeout=15)
        assert result.returncode == 3 and json.loads(result.stdout) == {'denied_before_optional_SDK': True}, result.stderr
    result = subprocess.run([sys.executable, '-E', '-s', str(driver)], capture_output=True, text=True,
        user=65534, group=65534, extra_groups=[], env=env, timeout=20, umask=0o077)
    assert result.returncode == 0 and not result.stderr, result.stderr
    value = json.loads(result.stdout); value['foreign_Root_agent_and_supplementary_Root_group_denied'] = True
    print(json.dumps(value, indent=2))


if __name__ == '__main__': main()
