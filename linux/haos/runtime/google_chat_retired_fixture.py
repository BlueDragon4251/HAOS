"""Actual Root historical worker after native private-UID OAuth enrollment."""
import json
import os
from pathlib import Path
import subprocess


def exercise(*,runtime,code,env,publication,secret,database,requests,configuration):
    if os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists():raise PermissionError('disposable Root OAuth namespace required')
    cases=[];helper=Path('/root/historical-google-parent.py')
    helper.write_text('''import json,sys
sys.path.insert(0,'/usr/lib/haos')
from haos import google_chat_retired_setup as owner
v=json.load(sys.stdin);action=v['action'];params=v.get('params',{})
try:
 if action=='profiles':result=owner.profiles()
 elif action=='tokens':result=owner.tokens(**params)
 elif action=='quarantines':result=owner.quarantines(**params)
 elif action=='dispose':result=owner.dispose(**params)
 elif action=='revoke':result=owner.revoke(**params)
 elif action=='hold':
  import subprocess
  from haos.google_chat_retired_process import command
  child=subprocess.Popen(command(),stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,user=65534,group=65534,extra_groups=[],cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin'},umask=0o077)
  open('/run/historical-held-worker.pid','w').write(str(child.pid));child.wait();raise SystemExit(0)
 else:raise ValueError('closed fixture action')
 print(json.dumps(result))
except PermissionError:print(json.dumps({'error':'root-backend-authority-refused'}))
''');helper.chmod(0o700)
    def call(action,params=None):
        child=subprocess.run(['/usr/local/bin/python3',str(helper)],input=json.dumps({'action':action,'params':params or {}}),
            capture_output=True,text=True,timeout=50,cwd=str(code),env=env)
        assert child.returncode==0,child.stderr
        assert not child.stderr and all(value not in child.stdout for value in [configuration['installed']['client_secret'],'owner-private-access-fixture','owner-private-refresh-fixture'])
        return json.loads(child.stdout)
    # The actual canonical Root configuration and service-account credentials
    # are removed from the active publication before any historical action.
    publication.write_text(json.dumps({'version':1,'connectors':[],'bindings':[]}));publication.chmod(0o644)
    secret.write_text(json.dumps({'connectors':{}}));secret.chmod(0o600)
    before=list(requests);items=call('profiles')
    assert len(items['profiles'])==1 and items['identity_missing']==[] and not items['network_requested'] and requests==before
    account=items['profiles'][0];assert account['profile']==database.parent.name
    assert account['identity']['project_id']=='haos-fixture' and not any('key' in k or 'secret' in k for k in account['identity'])
    tokens=call('tokens',{'profile':account['profile']})
    assert tokens['account']==account and len(tokens['result']['tokens'])==1 and requests==before
    row=tokens['result']['tokens'][0];assert row['current_file_grants']==0 and not row['private_credentials_returned'] and row['status']=='active'
    cases.append('actual_Root_historical_worker_lists_private_public_identity_and_tokens_after_connector_and_service_account_credentials_are_removed_without_fabricating_active_grants_or_requesting_network')
    # An absent active config is pinned as an absence snapshot, not synthesized
    # into an authorized active connector or used as an account credential.
    publication.unlink();secret.unlink()
    assert call('tokens',{'profile':account['profile']})['result']['tokens'][0]['id']==row['id'] and requests==before
    cases.append('actual_Root_historical_token_metadata_remains_available_with_active_config_and_all_service_account_credentials_absent')
    quarantined=call('quarantines',{'profile':account['profile']})
    assert quarantined['account']==account and len(quarantined['result']['quarantines'])==1 and requests==before
    capsule=quarantined['result']['quarantines'][0]
    assert not capsule['api_use_authorized'] and not capsule['actual_user_verified'] and capsule['state']=='rejected'
    cases.append('actual_Root_historical_rejected_token_inventory_without_service_account_credentials_exposes_only_nonactive_capsule_metadata_and_never_grants_API_use')
    site=runtime/'lib/python3.11/site-packages/fixture.pth';installed=site.read_text()
    site.write_text('/usr/lib/haos\n')
    try:
        assert call('profiles')['profiles']==[account]
        assert call('quarantines',{'profile':account['profile']})['result']['quarantines'][0]['id']==capsule['id']
        assert call('tokens',{'profile':account['profile']})['result']['tokens'][0]['id']==row['id'] and requests==before
    finally:site.write_text(installed)
    cases.append('actual_fixed_Root_private_UID_historical_metadata_with_real_retained_OAuth_tokens_runs_without_optional_SDK_or_Hermes_source_on_runtime_path_and_without_network')
    from haos.google_chat_retired_process import command
    for uid,groups in [(0,()),(65533,()),(65534,(0,))]:
        child=subprocess.run(command(),input='{}',capture_output=True,text=True,timeout=15,user=uid,group=uid,extra_groups=list(groups),cwd=str(code),env=env)
        assert child.returncode!=0 and not child.stdout
    child=subprocess.run(command(),input='{}',capture_output=True,text=True,timeout=15,user=65534,group=65534,extra_groups=[],cwd=str(code),env=env)
    assert child.returncode!=0 and 'live authenticated Root' in child.stderr
    denied='''from haos import google_chat_retired_setup as owner
for action in [lambda:owner.profiles(),lambda:owner.tokens('bad'),lambda:owner.revoke({}, {}, 'fixture',confirmed=True)]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('private UID entered Root historical backend')
print('denied')
'''
    child=subprocess.run([str(runtime/'bin/python'),'-E','-s','-c',denied],capture_output=True,text=True,timeout=15,user=65534,group=65534,extra_groups=[],cwd=str(code),env=env)
    assert child.returncode==0 and child.stdout=='denied\n',child.stderr
    cases.append('actual_historical_worker_denies_Root_agent_supplementary_Root_group_and_PID1_parent_and_private_UID_cannot_call_Root_backend')
    # A real private holder defeats the declared inactive service fixture.
    lockcode="from pathlib import Path;import time;from haos.gateway_matrix_profile import acquire_lease;fd=acquire_lease(Path('"+str(database.parent)+"'));print('locked',flush=True);time.sleep(30)"
    held=subprocess.Popen([str(runtime/'bin/python'),'-E','-s','-c',lockcode],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        user=65534,group=65534,extra_groups=[],cwd=str(code),env=env,text=True,umask=0o077)
    try:
        assert held.stdout.readline()=='locked\n'
        assert call('tokens',{'profile':account['profile']})=={'error':'authority-refused'} and requests==before
    finally:held.terminate();held.wait(timeout=5)
    identity_file=database.parent/'account-identity.json';saved_identity=identity_file.read_bytes()
    try:
        invalid=json.loads(saved_identity);invalid['bot_user']='users/998';identity_file.write_text(json.dumps(invalid))
        assert call('tokens',{'profile':account['profile']})=={'error':'authority-refused'} and requests==before
        assert identity_file.read_bytes()!=saved_identity
    finally:identity_file.write_bytes(saved_identity)
    cases.append('actual_historical_worker_kernel_profile_flock_and_changed_private_identity_block_status_or_withdrawal_without_network_or_automatic_identity_repair')
    import time
    parent=subprocess.Popen(['/usr/local/bin/python3',str(helper)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        cwd=str(code),env=env,text=True)
    parent.stdin.write(json.dumps({'action':'hold'}));parent.stdin.close()
    deadline=time.monotonic()+5
    while not Path('/run/historical-held-worker.pid').exists():
        assert time.monotonic()<deadline;time.sleep(.02)
    worker=int(Path('/run/historical-held-worker.pid').read_text())
    while 'NoNewPrivs:\t1' not in Path('/proc/'+str(worker)+'/status').read_text():
        assert time.monotonic()<deadline;time.sleep(.02)
    parent.terminate();parent.wait(timeout=5);deadline=time.monotonic()+5
    while True:
        status=Path('/proc/'+str(worker)+'/status')
        if not status.exists() or '\nState:\tZ' in status.read_text():break
        assert time.monotonic()<deadline;time.sleep(.02)
    cases.append('actual_historical_private_worker_PR_SET_PDEATHSIG_and_NoNewPrivs_stop_the_worker_when_its_authenticated_Root_parent_dies')
    params={'account':account,'row':row,'note':'explicit historical fixture withdrawal','confirmed':True}
    assert call('revoke',{**params,'confirmed':False})=={'error':'root-backend-authority-refused'} and requests==before
    stale={**account,'identity_sha256':'f'*64}
    assert call('revoke',{**params,'account':stale})=={'error':'root-backend-authority-refused'} and requests==before
    manifest=publication.parent/'gateway-publication.json';manifest.write_text('{}');manifest.chmod(0o600)
    assert call('tokens',{'profile':account['profile']})=={'error':'root-backend-authority-refused'} and requests==before
    manifest.unlink()
    cases.append('actual_Root_historical_withdrawal_requires_explicit_confirmation_exact_app_snapshot_and_no_pending_publication_before_any_HTTP')
    disposal={'account':account,'row':capsule,'note':'explicit rejected historical fixture disposal','confirmed':True}
    assert call('dispose',{**disposal,'confirmed':False})=={'error':'root-backend-authority-refused'} and requests==before
    changed={**capsule,'snapshot_sha256':'e'*64}
    assert call('dispose',{**disposal,'row':changed})=={'error':'authority-refused'} and requests==before
    disposed=call('dispose',disposal)['result']
    assert disposed['remote_revocation_verified'] and disposed['network_requested'] and not disposed['api_use_authorized'] and not disposed['message_sent']
    assert requests==before+['revoke']
    replay=call('dispose',disposal)['result']
    assert replay['receipt']==disposed['receipt'] and replay['remote_revocation_verified'] and not replay['network_requested']
    assert requests==before+['revoke']
    with __import__('sqlite3').connect(database) as db:
        assert db.execute('SELECT tokens,state FROM google_chat_oauth_quarantine').fetchone()==('{}','revoked-remote')
    cleaned=call('quarantines',{'profile':account['profile']})['result']['quarantines'][0]
    assert cleaned['stored_bytes']==0 and not cleaned['api_use_authorized'] and cleaned['remote_revocation_verified']
    cases.append('actual_Root_historical_rejected_token_disposal_requires_exact_snapshot_confirmation_then_one_fixed_TLS_revocation_before_private_capsule_compaction_and_replay_never_reposts_or_authorizes_API_use')
    before=list(requests)
    result=call('revoke',params);revoked=result['result']
    assert revoked['locally_revoked'] and revoked['remote_revocation_verified'] and revoked['network_requested'] and not revoked['message_sent']
    assert requests==before+['revoke']
    replay=call('revoke',params)['result']
    assert replay['receipt']==revoked['receipt'] and not replay['network_requested'] and replay['remote_revocation_verified']
    assert requests==before+['revoke']
    import sqlite3
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT status FROM google_chat_user_tokens').fetchone()[0]=='revoked-remote'
        assert db.execute("SELECT state FROM google_chat_oauth_revocations").fetchone()[0]=='confirmed'
        assert db.execute("SELECT owner_uid FROM google_chat_oauth_token_owner_events WHERE event='revoked-local'").fetchone()[0]==1000
    assert call('tokens',{'profile':account['profile']})['result']['tokens'][0]['status']=='revoked-remote'
    assert not publication.exists() and not secret.exists()
    audit=Path('/var/lib/haos-owner/audit.jsonl').read_text()
    assert 'google-chat-historical-revoke-token' in audit and 'owner-private-refresh-fixture' not in audit
    cases.append('actual_Root_to_private_UID_historical_revocation_without_service_account_key_commits_local_denial_before_one_fixed_Google_TLS_POST_and_replay_returns_original_audited_receipt_without_new_IO')
    return cases
