"""Actual private UID identity metadata migration/custody without optional SDK."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_IDENTITY_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh explicit readonly disposable namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    directory=Path(tempfile.mkdtemp(prefix='haos-google-identity-'));directory.chmod(0o755)
    parent=directory/'private';parent.mkdir(mode=0o700);os.chown(parent,65534,65534)
    owner=directory/'owner-canary';owner.write_text('Root-only fixture data');owner.chmod(0o600)
    driver=directory/'driver.py';driver.write_text('''import json,os,sys
from pathlib import Path
from copy import deepcopy
from haos.gateway_google_chat_identity import remember,load,descriptor,account_scope,NAME
from haos.gateway import digest,Conflict
v=json.load(sys.stdin);parent=Path(v['parent'])
if os.geteuid()!=65534 or os.getgroups():
 try:remember(parent,{})
 except PermissionError:pass
 else:raise AssertionError('foreign UID or supplementary group accepted')
 assert 'google.auth' not in sys.modules and 'googleapiclient' not in sys.modules
 print(json.dumps({'denied_before_optional_SDK':True}));raise SystemExit(3)
import subprocess
# Generate ephemeral test material inside this disposable UID namespace;
# no literal key block or private payload belongs in repository/evidence.
def test_key():
 result=subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048'],capture_output=True,timeout=10)
 assert result.returncode==0
 return result.stdout.decode()
project='haos-fixture';email='gateway@'+project+'.iam.gserviceaccount.com'
account={'service_account':{'type':'service_account','project_id':project,'private_key_id':'a'*40,
 'private_key':test_key(),'client_email':email,'client_id':'123456789',
 'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
 'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
 'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},'bot_user':'users/999',
 'inbound':{'mode':'pubsub','subscription':'projects/'+project+'/subscriptions/haos-private'}}
public=descriptor(account);profile=parent/('google-chat-'+digest(account_scope(public)));profile.mkdir(mode=0o700)
# Existing real SQLite custody remains untouched by legacy metadata migration.
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
import hashlib
journal=NativeInbox(profile/'existing.sqlite',Redactor([]));journal.db.execute('CREATE TABLE preserved(value TEXT)');journal.db.execute("INSERT INTO preserved VALUES('existing private custody')");journal.close()
before=hashlib.sha256((profile/'existing.sqlite').read_bytes()).hexdigest()
assert remember(profile,account)==public==load(profile)
assert hashlib.sha256((profile/'existing.sqlite').read_bytes()).hexdigest()==before
path=profile/NAME;snapshot=(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns)
assert path.stat().st_uid==65534 and path.stat().st_gid==65534 and path.stat().st_mode&0o777==0o600
assert b'PRIVATE KEY' not in snapshot[0] and b'private_key' not in snapshot[0] and b'subscription' not in snapshot[0]
cases=['actual_private_UID_creates_atomic_public_identity_for_existing_SQLite_profile_without_changing_journal_and_without_private_key_or_transport_material']
for change in ['key','subscription']:
 selected=deepcopy(account)
 if change=='key':selected['service_account'].update(private_key_id='b'*40,private_key=test_key())
 else:selected['inbound']['subscription']='projects/'+project+'/subscriptions/other'
 assert remember(profile,selected)==public
 assert (path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns)==snapshot
cases.append('actual_private_UID_key_rotation_and_transport_change_preserve_public_app_identity_bytes_inode_and_timestamp')
changed=deepcopy(account);changed['bot_user']='users/998'
try:remember(profile,changed)
except PermissionError:pass
else:raise AssertionError('foreign public app associated with old profile')
assert path.read_bytes()==snapshot[0];cases.append('actual_private_UID_refuses_other_app_for_existing_profile_without_replacing_metadata')
for mode in ['widened','hardlink','symlink','truncated','changed']:
 if mode=='widened':path.chmod(0o644)
 elif mode=='hardlink':os.link(path,profile/'extra-link')
 elif mode=='symlink':path.unlink();path.symlink_to(v['owner'])
 elif mode=='truncated':path.write_bytes(b'{')
 else:path.write_text(json.dumps({**public,'bot_user':'users/998'}))
 saved=path.lstat();content=None if mode=='symlink' else path.read_bytes()
 for action in [lambda:load(profile),lambda:remember(profile,account)]:
  try:action()
  except (OSError,ValueError,PermissionError,Conflict):pass
  else:raise AssertionError('damaged or unsafe identity was accepted: '+mode)
 assert path.lstat().st_ino==saved.st_ino
 if content is not None:assert path.read_bytes()==content
 # Restore only this disposable test's known synthetic metadata between cases.
 if mode=='hardlink':(profile/'extra-link').unlink()
 if mode=='symlink':path.unlink()
 path.write_bytes(snapshot[0]);path.chmod(0o600)
 cases.append('actual_private_UID_'+mode+'_identity_refused_and_preserved_without_automatic_repair')
link=parent/'linked-profile';link.symlink_to(profile,target_is_directory=True)
try:load(link)
except PermissionError:pass
else:raise AssertionError('symlinked private directory accepted')
cases.append('actual_private_UID_symlinked_profile_directory_refused_before_metadata_read')
# Deterministic filename collision; real O_EXCL/file behavior is not mocked.
import haos.gateway_google_chat_identity as identity_module
other=deepcopy(account);other['bot_user']='users/998'
other_profile=parent/('google-chat-'+digest(account_scope(descriptor(other))));other_profile.mkdir(mode=0o700)
collision=other_profile/('.account-identity-'+'a'*32);collision.write_bytes(b'pre-existing disposable private data')
original_random=identity_module.secrets.token_hex
identity_module.secrets.token_hex=lambda _count:'a'*32
try:
 try:remember(other_profile,other)
 except FileExistsError:pass
 else:raise AssertionError('exclusive metadata creation overwrote an existing temporary name')
finally:identity_module.secrets.token_hex=original_random
assert collision.read_bytes()==b'pre-existing disposable private data' and not (other_profile/NAME).exists()
cases.append('actual_O_EXCL_collision_preserves_preexisting_private_file_and_does_not_publish_descriptor')
assert 'google.auth' not in sys.modules and 'googleapiclient' not in sys.modules
print(json.dumps({'cases':cases,'passed':len(cases),'optional_SDK_imported':False}))
''');driver.chmod(0o644)
    request=json.dumps({'parent':str(parent),'owner':str(owner)}).encode();env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(code),'PYTHONDONTWRITEBYTECODE':'1','LANG':'C.UTF-8'}
    for uid,groups in [(0,()),(65533,()),(65534,(0,))]:
        result=subprocess.run([sys.executable,'-s',str(driver)],input=request,capture_output=True,timeout=15,user=uid,group=uid,extra_groups=list(groups),env=env,umask=0o077)
        assert result.returncode==3 and json.loads(result.stdout)=={'denied_before_optional_SDK':True},result.stderr.decode()[-1200:]
    result=subprocess.run([sys.executable,'-s',str(driver)],input=request,capture_output=True,timeout=15,user=65534,group=65534,extra_groups=[],env=env,umask=0o077)
    assert result.returncode==0,result.stderr.decode()[-1500:]
    response=json.loads(result.stdout);response['cases'].insert(0,'actual_Root_agent_UID_and_supplementary_Root_group_denied_before_optional_SDK');response['passed']=len(response['cases'])
    response['actual_UIDs_filesystem_SQLite_and_immutable_public_identity']=True
    response['live_Google_authentication_or_retired_Owner_UI_acceptance']=False
    print(json.dumps(response,indent=2))


if __name__=='__main__':main()
