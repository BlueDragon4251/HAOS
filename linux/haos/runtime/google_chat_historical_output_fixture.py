"""Real Root/private-UID output ownership after native SDK publication."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess


def exercise(*,mode,runtime,code,env,publication,secret,policy,value,native_database,database,requests):
    if os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists() or mode not in {'removed','rotated','legacy','unassociated'}:
        raise PermissionError('explicit disposable historical output scene required')
    helper=Path('/root/historical-output-parent.py');helper.write_text('''import json,sys
sys.path.insert(0,'/usr/lib/haos')
from haos import google_chat_retired_setup as owner
v=json.load(sys.stdin);action=v['action'];params=v.get('params',{})
try:
 if action=='profiles':result=owner.profiles()
 elif action=='outputs':result=owner.outputs(**params)
 elif action=='purge':result=owner.purge_output(**params)
 elif action=='unassociated':result=owner.unassociated_outputs()
 elif action=='purge-unassociated':result=owner.purge_unassociated_output(**params)
 else:raise ValueError('closed fixture action')
 print(json.dumps(result))
except PermissionError:print(json.dumps({'error':'root-backend-authority-refused'}))
''');helper.chmod(0o700)
    def call(action,params=None):
        child=subprocess.run(['/usr/local/bin/python3',str(helper)],input=json.dumps({'action':action,'params':params or {}}),capture_output=True,text=True,
            timeout=50,cwd=str(code),env=env)
        assert child.returncode==0 and not child.stderr,child.stderr
        assert all(value not in child.stdout for value in ['owner-private-refresh-fixture','owner-private-access-fixture','private-native-upload-reference-fixture'])
        return json.loads(child.stdout)
    before=list(requests);account=next(row for row in call('profiles')['profiles'] if row['profile']==database.parent.name)
    current=call('outputs',{'profile':account['profile']});assert not current['active_authorization_returned']
    item=current['result']['outputs'][0];assert item['current_grant'] and not item['purge_allowed']
    assert call('purge',{'account':account,'row':item,'note':'active output must not be deleted','confirmed':True})=={'error':'root-backend-authority-refused'}
    with sqlite3.connect(native_database) as db:
        original=db.execute('SELECT id,data,state FROM google_chat_output_files').fetchone();assert original[2]=='retained' and original[1]
        if mode=='legacy':db.execute('DELETE FROM google_chat_output_owners')
    if mode=='unassociated':
        return unassociated(call=call,account=account,publication=publication,secret=secret,native_database=native_database,
            database=database,requests=requests,runtime=runtime)
    if mode=='rotated':
        changed=deepcopy(value);changed['service_account']['private_key_id']='b'*40
        secret.write_text(json.dumps({'connectors':{'google':changed}}));secret.chmod(0o600)
        policy['bindings']=[];publication.write_text(json.dumps(policy));publication.chmod(0o644)
    else:publication.unlink();secret.unlink()
    site=runtime/'lib/python3.11/site-packages/fixture.pth';installed=site.read_text();site.write_text('/usr/lib/haos\n')
    try:
        result=call('outputs',{'profile':account['profile']});assert result['account']==account and not result['active_authorization_returned']
        item=result['result']['outputs'][0]
        assert item['id']==original[0] and item['purge_allowed'] and not item['current_grant'] and item['stored_bytes']==len(original[1])
        with sqlite3.connect(native_database) as db:
            assert db.execute('SELECT id,data,state FROM google_chat_output_files').fetchone()==original
            assert db.execute('SELECT connector,account_scope FROM google_chat_output_owners').fetchone()==('google',item['account_scope'])
        assert requests==before
        params={'account':account,'row':item,'note':'explicit historical local output disposal','confirmed':True}
        assert call('purge',{**params,'confirmed':False})=={'error':'root-backend-authority-refused'}
        changed_item={**item,'snapshot_sha256':'f'*64}
        assert call('purge',{**params,'row':changed_item})=={'error':'authority-refused'}
        disposed=call('purge',params)['result']
        assert disposed['tombstones_retained'] and not disposed['network_requested'] and not disposed['remote_deletion_verified']
        assert call('purge',params)['result']==disposed and requests==before
        with sqlite3.connect(native_database) as db:
            assert db.execute('SELECT state,length(data) FROM google_chat_output_files').fetchone()==('purged',0)
            assert db.execute('SELECT COUNT(*) FROM google_chat_output_owners').fetchone()[0]==1
            assert db.execute('SELECT owner_uid FROM google_chat_output_owner_events').fetchone()[0]==1000
        audit=Path('/var/lib/haos-owner/audit.jsonl').read_text();assert 'google-chat-historical-purge-output' in audit
    finally:site.write_text(installed)
    return {'mode':mode,'receipt':disposed,'active_grant_refused':True,'actual_Root_private_UID_with_optional_SDK_and_Hermes_source_hidden':True,
        'original_retained_bytes_preserved_until_explicit_decision':True,'ownership_tombstone_and_Owner_audit_preserved':True,'no_network_or_remote_deletion':True}


def unassociated(*,call,account,publication,secret,native_database,database,requests,runtime):
    before=list(requests)
    with sqlite3.connect(native_database) as db:
        original=db.execute('SELECT id,data,state FROM google_chat_output_files').fetchone()
        db.execute('DELETE FROM google_chat_output_owners');db.execute('DELETE FROM google_chat_file_writes')
    active=call('unassociated')['result']['outputs'][0]
    assert active['current_grant'] and not active['purge_allowed']
    assert call('purge-unassociated',{'row':active,'note':'active original grant must block orphan disposal','confirmed':True})=={'error':'root-backend-authority-refused'}
    publication.unlink();secret.unlink()
    # The global orphan path also works when old public identity metadata was
    # never retained. It neither invents an identity nor edits the profile.
    marker=database.parent/'account-identity.json';marker.unlink()
    site=runtime/'lib/python3.11/site-packages/fixture.pth';installed=site.read_text();site.write_text('/usr/lib/haos\n')
    try:
        view=call('unassociated');assert not view['app_association_inferred'] and not view['active_authorization_returned']
        item=view['result']['outputs'][0];assert item['id']==original[0] and item['purge_allowed']
        with sqlite3.connect(native_database) as db:
            assert db.execute('SELECT id,data,state FROM google_chat_output_files').fetchone()==original
            assert db.execute('SELECT COUNT(*) FROM google_chat_output_owners').fetchone()[0]==0
        params={'row':item,'note':'explicit global unassociated output disposal','confirmed':True}
        assert call('purge-unassociated',{**params,'confirmed':False})=={'error':'root-backend-authority-refused'}
        changed={**item,'snapshot_sha256':'f'*64}
        assert call('purge-unassociated',{**params,'row':changed})=={'error':'authority-refused'}
        receipt=call('purge-unassociated',params)['result']
        assert receipt['tombstones_retained'] and not receipt['network_requested'] and not receipt['remote_deletion_verified']
        assert call('purge-unassociated',params)['result']==receipt and requests==before
        with sqlite3.connect(native_database) as db:
            assert db.execute('SELECT state,length(data) FROM google_chat_output_files').fetchone()==('purged',0)
            assert db.execute('SELECT COUNT(*) FROM google_chat_output_owners').fetchone()[0]==0
            assert db.execute('SELECT owner_uid FROM google_chat_output_owner_events').fetchone()[0]==1000
        assert not marker.exists()
        return {'mode':'unassociated','receipt':receipt,'no_app_association_invented':True,
            'actual_Root_private_UID_without_optional_SDK_Hermes_or_account_identity_metadata':True,
            'active_original_grant_refused':True,'bytes_preserved_until_explicit_global_Owner_decision':True,'no_network_or_remote_deletion':True}
    finally:site.write_text(installed)
