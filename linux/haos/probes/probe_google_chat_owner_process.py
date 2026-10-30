"""Real Root/backend/private-UID recovery; explicit systemctl state fixture only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or os.environ.get('HAOS_DISPOSABLE_GOOGLE_CHAT_OWNER_PROCESS')!='1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh explicit readonly disposable namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755)
    subprocess.run([sys.executable,'/repo/linux/haos/runtime/install_package.py','/repo/linux/haos/haos',str(code/'haos')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/fixture.pth').write_text('/usr/lib/haos\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path.insert(0,str(code))
    from haos.gateway_google_chat import scope
    from haos.gateway import digest
    from haos.google_chat_owner_process import command
    project='haos-fixture';email='gateway@'+project+'.iam.gserviceaccount.com'
    value={'service_account':{'type':'service_account','project_id':project,'private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n','client_email':email,'client_id':'123456789',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},'bot_user':'users/999',
        'inbound':{'mode':'pubsub','subscription':'projects/'+project+'/subscriptions/haos-private'}}
    binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
        'scope':scope(value),'identity':'personal','capabilities':['read','create'],'generation':'a'*64,'since':int(time.time()*1000)-60000}
    policy={'version':1,'publication':'b'*64,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]}
    config=Path('/etc/haos');config.mkdir(mode=0o755);publication=config/'gateways.json';publication.write_text(json.dumps(policy));publication.chmod(0o644)
    secret=config/'gateway-credentials';secret.write_text(json.dumps({'publication':policy['publication'],'connectors':{'google':value}}));secret.chmod(0o600)
    state=Path('/var/lib/haos-gateway');state.mkdir(mode=0o700);os.chown(state,65534,65534)
    # The fixture provides only systemd's declared service state. Linux UID,
    # parent credentials, directory ownership, flock, SQLite and worker command
    # are all real. This is not an installed systemd/Owner-login acceptance.
    systemctl=Path('/usr/bin/systemctl');systemctl.write_text('''#!/usr/local/bin/python3
import pathlib,sys
with pathlib.Path('/run/fixture-systemctl.log').open('a') as stream:stream.write(' '.join(sys.argv[1:])+'\\n')
if sys.argv[1]=='stop':raise SystemExit(0)
if sys.argv[1]=='show':
 print('LoadState=loaded\\nActiveState='+('active' if pathlib.Path('/run/fixture-active').exists() else 'inactive')+'\\nMainPID=0\\nControlPID=0')
else:raise SystemExit(2)
''');systemctl.chmod(0o755)
    helper=Path('/root/google-owner-parent.py');helper.write_text('''import json,os,sys,subprocess
sys.path.insert(0,'/usr/lib/haos')
from haos import google_chat_owner_setup as owner
request=json.load(sys.stdin);action=request['action'];params=request.get('params',{})
try:
 if action=='inspect':value=owner.inspect('google',**params)
 elif action=='retry-auth':value=owner.retry_auth('google',**params)
 elif action=='purge-source':value=owner.purge_source('google',**params)
 elif action=='approve-reply':value=owner.approve_reply('google',**params)
 elif action=='hold':
  from haos.google_chat_owner_process import command
  child=subprocess.Popen(command(),stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,user=65534,group=65534,extra_groups=[],cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin'},umask=0o077)
  open('/run/held-worker.pid','w').write(str(child.pid));child.wait();raise SystemExit(0)
 else:raise ValueError('fixture action')
 print(json.dumps(value))
except PermissionError:print(json.dumps({'error':'root-backend-authority-refused'}))
''');helper.chmod(0o700)
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','SUDO_UID':'1000'}
    def call(action,params=None):
        result=subprocess.run([sys.executable,str(helper)],input=json.dumps({'action':action,'params':params or {}}),text=True,capture_output=True,
            env=env,timeout=20,cwd=str(code));assert result.returncode==0,result.stderr
        assert value['service_account']['private_key'] not in result.stdout and not result.stderr,result.stderr
        return json.loads(result.stdout)
    cases=[]
    assert call('inspect',{'action':'outgoing'})=={'outgoing':[],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
    assert not (state/'native-inbox.db').exists()
    cases.append('actual_fixed_installed_Root_backend_passes_closed_stdin_to_live_Root_parent_private_UID_worker_and_empty_inspection_does_not_create_native_journal_or_import_optional_SDK')
    for uid,gid,groups in [(0,0,[]),(65533,65533,[]),(65534,65534,[0])]:
        result=subprocess.run(command(),input='{}',text=True,capture_output=True,timeout=10,user=uid,group=gid,extra_groups=groups,cwd=str(code),env=env)
        assert result.returncode!=0 and not result.stdout and value['service_account']['private_key'] not in result.stderr
    # Correct private UID still cannot impersonate an authenticated Owner from
    # PID1 or another private parent, or call Root backend entry points.
    result=subprocess.run(command(),input='{}',text=True,capture_output=True,timeout=10,user=65534,group=65534,extra_groups=[],cwd=str(code),env=env)
    assert result.returncode!=0 and 'live authenticated Root' in result.stderr
    foreign='''import subprocess,sys
from haos.google_chat_owner_process import command
from haos import google_chat_owner_setup as owner
for action in [lambda:owner.inspect('google'),lambda:owner.retry_auth('google','fixture',confirmed=True),lambda:owner.purge_source('google',{},'fixture',confirmed=True),lambda:owner.approve_reply('google',{},'a'*64,'fixture',confirmed=True,confirmed_not_delivered=True)]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('private UID gained Root backend')
r=subprocess.run(command(),input='{}',text=True,capture_output=True,timeout=10)
assert r.returncode!=0 and 'actual authenticated Root parent' in r.stderr
print('denied')
'''
    result=subprocess.run([str(runtime/'bin/python'),'-E','-s','-c',foreign],text=True,capture_output=True,timeout=15,user=65534,group=65534,extra_groups=[],cwd=str(code),env=env)
    assert result.returncode==0 and result.stdout=='denied\n',result.stderr
    cases.append('actual_root_foreign_UID_supplementary_root_group_PID1_parent_and_unprivileged_parent_are_denied_and_private_UID_cannot_call_Root_backend')
    Path('/run/fixture-active').touch()
    assert call('inspect',{'action':'outgoing'})=={'error':'root-backend-authority-refused'}
    Path('/run/fixture-active').unlink()
    cases.append('Root_backend_requires_quiescent_service_before_private_handoff_using_explicit_systemctl_state_fixture')
    original_secret=secret.read_text();secret.chmod(0o644)
    assert call('inspect',{'action':'outgoing'})=={'error':'root-backend-authority-refused'}
    secret.chmod(0o600);mismatched=json.loads(original_secret);mismatched['publication']='c'*64
    secret.write_text(json.dumps(mismatched));secret.chmod(0o600)
    assert call('inspect',{'action':'outgoing'})=={'error':'root-backend-authority-refused'}
    secret.write_text(original_secret);secret.chmod(0o600)
    pending=config/'gateway-publication.json';pending.write_text('{}');pending.chmod(0o600)
    assert call('inspect',{'action':'outgoing'})=={'error':'root-backend-authority-refused'}
    pending.unlink()
    cases.append('actual_Root_backend_refuses_nonprivate_credential_file_mismatched_publication_and_pending_publication_before_private_handoff')
    seed='''import json,sys,time,hashlib
from pathlib import Path
from haos.gateway import digest
from haos.gateway_google_chat import PreparedGoogleChatPolicy,scope
from haos.gateway_google_chat_custody import Originals
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
request=json.load(sys.stdin);value=request['value'];policy=PreparedGoogleChatPolicy(request['policy']);binding=policy.bindings['owner']
state=Path('/var/lib/haos-gateway');profiles=state/'profiles';profiles.mkdir(mode=0o700);profile=profiles/('google-chat-'+digest(scope(value)));profile.mkdir(mode=0o700)
from datetime import datetime,timezone
raw=json.dumps({'type':'MESSAGE','space':{'name':binding['chat'],'spaceType':'SPACE'},'message':{'name':binding['chat']+'/messages/source1','sender':{'name':binding['sender'],'type':'HUMAN'},'thread':{'name':binding['thread']},'text':'<users/999> /status','annotations':[{'type':'USER_MENTION','userMention':{'user':{'name':'users/999'}}}],'createTime':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}}).encode()
store=Originals(profile/'originals.sqlite',Redactor([]));key=store.retain(policy,'google',value,raw,lambda:None);store.close()
inbox=NativeInbox(state/'native-inbox.db',Redactor([]))
inbox.db.execute('CREATE TABLE google_chat_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)')
inbox.db.execute('CREATE TABLE google_chat_profile_budget(scope TEXT PRIMARY KEY,not_before REAL NOT NULL)')
deadline=time.time()+300
inbox.db.execute('INSERT INTO google_chat_profile_status VALUES(?,?,?,?,?,?)',('a'*64,'google',digest(['google',value]),'authentication-refused',time.time(),deadline))
inbox.db.execute('INSERT INTO google_chat_profile_budget VALUES(?,?)',(scope(value),deadline))
from haos.gateway_google_chat_admission import approve
from haos.gateway_google_chat_text import TextLedger
import uuid
envelope={**approve(policy,'google',value,raw)['envelope'],'text':'/status'}
source=inbox.admit(policy,'google',envelope,{});assert inbox.claim(source,policy) is not None;inbox.complete(source,True)
inbox.db.execute('CREATE TABLE google_chat_native_projection(source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,raw_sha256 TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,envelope_sha256 TEXT NOT NULL)')
inbox.db.execute('INSERT INTO google_chat_native_projection VALUES(?,?,?,?,?,?)',(source,key,hashlib.sha256(raw).hexdigest(),digest(binding),digest(['google',value]),digest(envelope)))
TextLedger(inbox,'google',value,lambda:policy,lambda:None)
inbox.db.execute('CREATE TABLE google_chat_delivery_groups(id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,source_id TEXT NOT NULL,source_sha256 TEXT NOT NULL,context_sha256 TEXT NOT NULL,content_sha256 TEXT NOT NULL,parts INTEGER NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,connector TEXT NOT NULL)')
group='d'*64
inbox.db.execute('INSERT INTO google_chat_delivery_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(group,binding['id'],digest(binding),digest(value),envelope['message_id'],hashlib.sha256(raw).hexdigest(),'e'*64,'f'*64,2,'writing','','google'))
for index in range(2):
 identity=digest([group,source,index]);body=json.dumps({'text':'private answer '+str(index),'thread':{'name':binding['thread']}},sort_keys=True,separators=(',',':'))
 inbox.db.execute('INSERT INTO google_chat_text_writes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identity,binding['id'],digest(binding),digest(value),binding['chat'],body,'client-'+identity[:56],str(uuid.uuid5(uuid.NAMESPACE_URL,'haos-google-chat:'+identity)),'confirmed' if index==0 else 'writing',binding['chat']+'/messages/receipt0' if index==0 else '',time.time(),0))
inbox.close()
print(json.dumps({'profile':profile.name,'key':key,'deadline':deadline}))
'''
    result=subprocess.run([str(runtime/'bin/python'),'-E','-s','-c',seed],input=json.dumps({'value':value,'policy':policy}),text=True,capture_output=True,
        user=65534,group=65534,extra_groups=[],umask=0o077,cwd=str(code),env=env,timeout=15);assert result.returncode==0,result.stderr
    seeded=json.loads(result.stdout);rows=call('inspect',{'action':'sources'});assert len(rows['sources'])==1 and rows['sources'][0]['id']==seeded['key']
    assert call('inspect',{'action':'source-profiles'})['profiles']==[seeded['profile']]
    row=rows['sources'][0]
    assert call('purge-source',{'row':row,'note':'active source','confirmed':True})=={'error':'root-backend-authority-refused'}
    cases.append('actual_UID_owned_originals_are_inspected_as_payload_free_hashed_snapshots_and_active_grant_disposal_is_denied_by_Root_backend')
    group=call('inspect',{'action':'outgoing'})['outgoing'][0]
    assert group['confirmed_parts']==1 and group['current_grant'] and 'private answer' not in json.dumps(group)
    for kwargs in [{'part_id':group['parts'][0]['id'],'confirmed_not_delivered':True},
            {'part_id':group['parts'][1]['id'],'confirmed_not_delivered':False}]:
        expected='authority-refused' if kwargs['confirmed_not_delivered'] else 'root-backend-authority-refused'
        assert call('approve-reply',{'row':group,'note':'inspected uncertain reply','confirmed':True,**kwargs})=={'error':expected}
    params={'row':group,'part_id':group['parts'][1]['id'],'note':'inspected uncertain reply','confirmed':True,'confirmed_not_delivered':True}
    release=call('approve-reply',params);assert release['private_retry_approved'] and not release['network_requested'] and not release['message_sent']
    assert call('approve-reply',params)==release
    retained=call('inspect',{'action':'outgoing'})['outgoing'][0]
    assert retained['parts'][0]==group['parts'][0] and retained['parts'][1]['state']=='owner-retry-approved'
    assert retained['parts'][1]['retry_generation']==1
    cases.append('actual_Root_to_private_UID_reply_inspection_and_exact_part_decision_preserve_confirmed_sibling_and_durably_audit_one_idempotent_approval_without_network')
    auth=call('retry-auth',{'note':'inspected fixture account','confirmed':True});assert auth['authentication_blocks_cleared']==1 and not auth['network_requested']
    import sqlite3
    with sqlite3.connect(state/'native-inbox.db') as db:
        assert db.execute('SELECT status,next_attempt FROM google_chat_profile_status').fetchone()==('created',seeded['deadline'])
        assert db.execute('SELECT not_before FROM google_chat_profile_budget').fetchone()[0]==seeded['deadline']
        assert db.execute('SELECT owner_uid FROM google_chat_auth_owner_events').fetchone()[0]==1000
    cases.append('actual_Root_private_UID_auth_recheck_commits_private_Owner_audit_and_clears_only_auth_block_without_shortening_either_rate_deadline')
    policy['bindings']=[];publication.write_text(json.dumps(policy));publication.chmod(0o644)
    withdrawn=call('inspect',{'action':'sources'})['sources'][0];assert withdrawn['purge_allowed']
    result=call('purge-source',{'row':withdrawn,'note':'inspected withdrawn original','confirmed':True});assert result['tombstones_retained'] and not result['message_sent']
    assert call('purge-source',{'row':withdrawn,'note':'inspected withdrawn original','confirmed':True})==result
    with sqlite3.connect(state/'profiles'/seeded['profile']/'originals.sqlite') as db:
        assert db.execute('SELECT length(raw) FROM google_chat_originals').fetchone()[0]==0
        assert db.execute('SELECT owner_uid FROM google_chat_source_owner_events').fetchone()[0]==1000
    assert call('inspect',{'action':'sources'})['sources'][0]['state']=='purged'
    cases.append('real_Root_backend_private_UID_disposal_after_exact_withdrawn_snapshot_compacts_payload_bearing_original_and_proof_keeps_audit_and_is_idempotent')
    # Actual kernel flock prevents Owner recovery while another profile holder
    # still owns its identity, independently of the service state declaration.
    lockcode="from pathlib import Path;import time;from haos.gateway_matrix_profile import acquire_lease;fd=acquire_lease(Path('/var/lib/haos-gateway/profiles/"+seeded['profile']+"'));print('locked',flush=True);time.sleep(30)"
    held=subprocess.Popen([str(runtime/'bin/python'),'-E','-s','-c',lockcode],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        user=65534,group=65534,extra_groups=[],cwd=str(code),env=env)
    assert held.stdout.readline()=='locked\n'
    assert call('inspect',{'action':'sources'})=={'error':'authority-refused'}
    held.terminate();held.wait(timeout=5)
    cases.append('real_kernel_flock_refuses_Owner_recovery_while_private_profile_is_in_use_even_if_fixture_service_state_claims_inactive')
    parent=subprocess.Popen([sys.executable,str(helper)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,cwd=str(code),env=env)
    parent.stdin.write(json.dumps({'action':'hold'}));parent.stdin.close()
    for _ in range(100):
        if Path('/run/held-worker.pid').exists():break
        time.sleep(.02)
    worker=int(Path('/run/held-worker.pid').read_text())
    # Wait for PR_SET_PDEATHSIG to be installed while the worker blocks on stdin.
    for _ in range(100):
        status=Path('/proc/'+str(worker)+'/status').read_text()
        if 'NoNewPrivs:\t1' in status:break
        time.sleep(.02)
    else:raise AssertionError('worker lifetime guard was not installed')
    parent.terminate();parent.wait(timeout=5)
    for _ in range(100):
        path=Path('/proc/'+str(worker)+'/status')
        if not path.exists() or '\nState:\tZ' in path.read_text():break
        time.sleep(.02)
    else:raise AssertionError('private worker survived loss of authenticated Root parent')
    cases.append('actual_PR_SET_PDEATHSIG_kills_private_worker_after_authenticated_Root_parent_dies_instead_of_accepting_reparenting_to_PID1')
    audit=Path('/var/lib/haos-owner/audit.jsonl')
    if not audit.exists():
        from haos.owner import AUDIT
        audit=AUDIT
    assert audit.exists() and 'google-chat-owner-' in audit.read_text()
    assert value['service_account']['private_key'] not in audit.read_text()
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_Root_backend_private_UID_parent_credentials_flock_SQLite_and_parent_lifetime':True,
        'systemctl_service_state_is_explicit_fixture':True,'Google_account_external_delivery_GUI_installed_service_or_public_activation':False},indent=2))


if __name__=='__main__':main()
