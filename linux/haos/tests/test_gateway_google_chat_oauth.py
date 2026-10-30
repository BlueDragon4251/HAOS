"""Private SQLite PKCE/identity contracts; no JWT verification or OAuth exchange."""
import json
import sqlite3
import time
from urllib.parse import urlencode
import pytest

from haos.gateway import digest,Conflict
from haos.gateway_google_chat_oauth import OAuthStore,client,callback,REDIRECT_URI
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,policy


def configuration():return {'installed':{'client_id':'123456789-private-fixture.apps.googleusercontent.com','project_id':'haos-fixture',
    'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
    'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','client_secret':'private-client-fixture-not-a-real-secret','redirect_uris':['http://localhost']}}


def opened(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'oauth.sqlite',Redactor([]));selected=policy(allow_outbound_media=True);store=OAuthStore(inbox)
    return inbox,store,selected


def begin(store,selected,**options):
    return store.begin(selected,'google',account(),configuration(),'owner',digest(selected.bindings['owner']),
        owner_uid=1000,note_sha256='a'*64,confirmed=True,**options)


def returned(row,**options):return REDIRECT_URI+'/?'+urlencode({'code':'local-private-auth-code-fixture','state':row['state'],**options})


def test_real_FULL_SQLite_pending_custody_contains_independent_PKCE_nonce_state_and_inventory_hides_all_private_bytes(tmp_path):
    inbox,store,selected=opened(tmp_path);first=begin(store,selected);second=begin(store,selected)
    assert first['id']!=second['id'] and first['state']!=second['state'] and first['nonce']!=first['state'] and len(first['verifier'])>=43
    assert first['expires_at']-first['created_at']==600 and first['subject']=='users/123'
    assert inbox.db.execute('PRAGMA synchronous').fetchone()[0]==2
    view=store.inventory();encoded=json.dumps(view)
    for secret in [first['verifier'],first['state'],first['nonce'],configuration()['installed']['client_secret']]:assert secret not in encoded
    assert not view['network_requested'] and not view['private_bytes_returned'] and len(view['sessions'])==2
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_oauth_events').fetchone()[0]==2;inbox.close()


@pytest.mark.parametrize('field,value',[
    ('client_id','foreign@example.invalid'),('project_id','foreign-project'),('auth_uri','https://foreign.invalid/auth'),
    ('token_uri','https://foreign.invalid/token'),('auth_provider_x509_cert_url','https://foreign.invalid/certs'),
    ('redirect_uris',['https://foreign.invalid/callback']),('client_secret','bad\nvalue'),('extra','unexpected')])
def test_desktop_client_cannot_borrow_another_project_redirect_keys_or_add_ambient_configuration(field,value):
    configuration_value=configuration();configuration_value['installed'][field]=value
    with pytest.raises(ValueError):client(configuration_value,account())


@pytest.mark.parametrize('case',['code-only','foreign-host','foreign-port','duplicate-state','duplicate-code','missing-state','wrong-state','unicode-state','foreign-query'])
def test_full_callback_requires_exact_loopback_complete_state_and_unique_code_before_any_exchange(case):
    state='a'*43;value=REDIRECT_URI+'/?'+urlencode({'code':'local-code-fixture','state':state})
    if case=='code-only':value='local-code-fixture'
    elif case=='foreign-host':value=value.replace('localhost','foreign.invalid')
    elif case=='foreign-port':value=value.replace(':1/',':2/')
    elif case=='duplicate-state':value+='&state='+state
    elif case=='duplicate-code':value+='&code=other'
    elif case=='missing-state':value=REDIRECT_URI+'/?code=local-code-fixture'
    elif case=='wrong-state':value=value.replace(state,'b'*43)
    elif case=='unicode-state':value=REDIRECT_URI+'/?'+urlencode({'code':'local-code-fixture','state':'é'*43})
    elif case=='foreign-query':value+='&token_uri=https%3A%2F%2Fforeign.invalid'
    with pytest.raises(PermissionError):callback(value,state)


def test_exchange_intent_and_owner_audit_commit_before_returning_code_and_cannot_repeat_after_reopen(tmp_path):
    inbox,store,selected=opened(tmp_path);row=begin(store,selected)
    private,code=store.exchange(selected,'google',account(),row['id'],returned(row),owner_uid=1000)
    assert private['id']==row['id'] and code=='local-private-auth-code-fixture'
    with sqlite3.connect(tmp_path/'oauth.sqlite') as other:
        assert other.execute('SELECT status FROM google_chat_oauth_pending').fetchone()[0]=='exchanging'
        assert other.execute("SELECT COUNT(*) FROM google_chat_oauth_events WHERE event='exchanging'").fetchone()[0]==1
    inbox.close();inbox=NativeInbox(tmp_path/'oauth.sqlite',Redactor([]));store=OAuthStore(inbox)
    with pytest.raises(PermissionError):store.exchange(selected,'google',account(),row['id'],returned(row),owner_uid=1000)
    inbox.close()


@pytest.mark.parametrize('case',['owner','expired','grant','account','state','audit'])
def test_exchange_refuses_stale_owner_epoch_account_state_expiry_and_failed_audit_without_advancing_pending(tmp_path,case):
    inbox,store,selected=opened(tmp_path);row=begin(store,selected);value=account();uid=1000;url=returned(row);error=(PermissionError,Conflict)
    if case=='owner':uid=1001
    elif case=='expired':
        inbox.db.execute('UPDATE google_chat_oauth_pending SET created_at=?,expires_at=?',(time.time()-700,time.time()-101))
    elif case=='grant':selected.bindings.clear()
    elif case=='account':value['service_account']['private_key_id']='b'*40
    elif case=='state':url=returned(row,state='b'*43)
    elif case=='audit':
        inbox.db.execute("CREATE TRIGGER fail_exchange_audit BEFORE INSERT ON google_chat_oauth_events BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
        error=sqlite3.IntegrityError
    with pytest.raises(error):store.exchange(selected,'google',value,row['id'],url,owner_uid=uid)
    assert not inbox.db.in_transaction and inbox.db.execute('SELECT status FROM google_chat_oauth_pending').fetchone()[0]=='awaiting';inbox.close()


@pytest.mark.parametrize('change',[{'sub':'124'},{'sub':'owner@example.invalid'},{'aud':'other-client'},{'azp':'other-client'},
    {'nonce':'b'*43},{'nonce':'é'*43},{'iss':'https://foreign.invalid'},{'iss':[]},{'exp':1},{'iat':True}])
def test_post_signature_claim_constraints_require_exact_stable_user_nonce_and_client_without_email_alias_authority(tmp_path,change):
    inbox,store,selected=opened(tmp_path);row=begin(store,selected);now=int(time.time())
    claims={'iss':'https://accounts.google.com','aud':configuration()['installed']['client_id'],'sub':'123','nonce':row['nonce'],'iat':now,'exp':now+3600,
        'email':'mutable-name@example.invalid','email_verified':True}
    assert store.identity(row,claims)=='users/123'
    with pytest.raises(PermissionError):store.identity(row,{**claims,**change})
    inbox.close()


def test_serialized_claim_or_token_payload_cannot_be_used_as_a_verified_grant(tmp_path):
    inbox,store,selected=opened(tmp_path);row=begin(store,selected)
    with pytest.raises(PermissionError):store.complete(selected,'google',account(),row['id'],{'subject':'users/123','credential_json':'{}'},owner_uid=1000)
    assert inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_user_tokens'").fetchone() is None
    assert inbox.db.execute('SELECT status FROM google_chat_oauth_pending').fetchone()[0]=='awaiting';inbox.close()


def test_pending_live_capacity_and_failed_begin_audit_are_bounded_and_atomic(tmp_path):
    inbox,store,selected=opened(tmp_path)
    inbox.db.execute("CREATE TRIGGER fail_begin_audit BEFORE INSERT ON google_chat_oauth_events BEGIN SELECT RAISE(ABORT,'fixture disk full'); END")
    with pytest.raises(sqlite3.IntegrityError):begin(store,selected)
    assert not inbox.db.in_transaction and inbox.db.execute('SELECT COUNT(*) FROM google_chat_oauth_pending').fetchone()[0]==0
    inbox.db.execute('DROP TRIGGER fail_begin_audit')
    for _ in range(32):begin(store,selected)
    with pytest.raises(Conflict):begin(store,selected)
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_oauth_pending').fetchone()[0]==32;inbox.close()


@pytest.mark.parametrize('field,value',[('token_uri','https://foreign.invalid/token'),('scopes',['openid']),('client_id','other-client'),
    ('refresh_token','bad\nvalue'),('universe_domain','foreign.invalid'),('extra','unexpected')])
def test_saved_sdk_credentials_cannot_redirect_refresh_or_borrow_another_client_or_scope(field,value):
    from datetime import datetime,timezone,timedelta
    from haos.gateway_google_chat_oauth import validate_token,SCOPES,TOKEN_URI
    configuration_value=configuration();payload={'token':'local-access-fixture','refresh_token':'local-refresh-fixture','token_uri':TOKEN_URI,
        'client_id':configuration_value['installed']['client_id'],'client_secret':configuration_value['installed']['client_secret'],
        'scopes':list(SCOPES),'expiry':(datetime.now(timezone.utc)+timedelta(hours=1)).replace(tzinfo=None).isoformat()+'Z','universe_domain':'googleapis.com','account':''}
    assert validate_token(payload,configuration_value)==payload
    with pytest.raises((PermissionError,ValueError)):validate_token({**payload,field:value},configuration_value)


def test_pending_owner_code_exchange_waits_for_persisted_same_client_budget_without_advancing_its_intent(tmp_path):
    from haos.gateway_google_chat_oauth_tokens import Deferred
    from haos.gateway_google_chat import scope
    inbox,store,selected=opened(tmp_path);row=begin(store,selected);deadline=time.time()+300
    inbox.db.execute('CREATE TABLE google_chat_oauth_budget(scope TEXT PRIMARY KEY,not_before REAL NOT NULL)')
    key=digest([scope(account()),row['subject'],configuration()['installed']['client_id']])
    inbox.db.execute('INSERT INTO google_chat_oauth_budget VALUES(?,?)',(key,deadline))
    with pytest.raises(Deferred) as error:store.exchange(selected,'google',account(),row['id'],returned(row),owner_uid=1000)
    assert error.value.status=='rate-limited' and error.value.retry_after>=299
    assert inbox.db.execute('SELECT status FROM google_chat_oauth_pending').fetchone()[0]=='awaiting'
    assert inbox.db.execute('SELECT not_before FROM google_chat_oauth_budget').fetchone()[0]==deadline
    assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_oauth_events').fetchone()[0]==1;inbox.close()


def test_rejected_issued_credentials_are_custodied_only_for_disposal_and_never_become_active_user_tokens(tmp_path):
    from haos.gateway_google_chat_oauth import quarantine
    inbox,store,selected=opened(tmp_path);row=begin(store,selected)
    store.exchange(selected,'google',account(),row['id'],returned(row),owner_uid=1000)
    result=quarantine(store,row,{'access_token':'rejected-private-access-fixture','refresh_token':'rejected-private-refresh-fixture'},'identity-refused')
    assert result['private_tokens_retained'] and not result['api_use_authorized'] and not result['remote_revocation_verified']
    assert not result['network_requested'] and not result['private_credentials_returned']
    assert inbox.db.execute('SELECT status FROM google_chat_oauth_pending').fetchone()[0]=='refused'
    assert inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_user_tokens'").fetchone() is None
    row=inbox.db.execute('SELECT * FROM google_chat_oauth_quarantine').fetchone()
    assert row['state']=='rejected' and row['tokens_sha256']==digest(row['tokens'])
    assert 'client_secret' not in row['public_client'] and json.loads(row['tokens'])['refresh_token']=='rejected-private-refresh-fixture'
    inbox.close()


def test_quarantine_audit_failure_preserves_exchange_fence_without_a_partial_rejected_token_record(tmp_path):
    from haos.gateway_google_chat_oauth import quarantine
    inbox,store,selected=opened(tmp_path);row=begin(store,selected)
    store.exchange(selected,'google',account(),row['id'],returned(row),owner_uid=1000)
    inbox.db.execute("CREATE TRIGGER deny_quarantine_audit BEFORE INSERT ON google_chat_oauth_events BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
    with pytest.raises(sqlite3.IntegrityError):quarantine(store,row,{'refresh_token':'rejected-private-refresh-fixture'},'identity-refused')
    assert not inbox.db.in_transaction
    assert inbox.db.execute('SELECT status FROM google_chat_oauth_pending').fetchone()[0]=='exchanging'
    exists=inbox.db.execute("SELECT 1 FROM sqlite_master WHERE name='google_chat_oauth_quarantine'").fetchone()
    assert exists is None or inbox.db.execute('SELECT COUNT(*) FROM google_chat_oauth_quarantine').fetchone()[0]==0;inbox.close()


def test_pre_read_reconciliation_scope_credentials_remain_disposable_but_cannot_authorize_new_file_client():
    from haos.gateway_google_chat_oauth import validate_token,CHAT_SCOPE,TOKEN_URI
    from datetime import datetime,timezone,timedelta
    conf=configuration();payload={'token':'local-access-fixture','refresh_token':'local-refresh-fixture','token_uri':TOKEN_URI,
        'client_id':conf['installed']['client_id'],'client_secret':conf['installed']['client_secret'],'scopes':[CHAT_SCOPE,'openid'],
        'expiry':(datetime.now(timezone.utc)+timedelta(hours=1)).replace(tzinfo=None).isoformat()+'Z','universe_domain':'googleapis.com','account':''}
    assert validate_token(payload,conf,legacy_for_disposal=True)==payload
    with pytest.raises(PermissionError):validate_token(payload,conf)


def test_rejected_token_snapshot_contains_only_metadata_and_detects_changed_capsule_bytes(tmp_path):
    from haos.gateway_google_chat_oauth import quarantine
    from haos.gateway_google_chat_oauth_quarantine import view
    inbox,store,selected=opened(tmp_path);row=begin(store,selected)
    store.exchange(selected,'google',account(),row['id'],returned(row),owner_uid=1000)
    quarantine(store,row,{'refresh_token':'rejected-private-refresh-fixture'},'identity-refused')
    record=inbox.db.execute('SELECT * FROM google_chat_oauth_quarantine').fetchone();snapshot=view(record,account())
    assert snapshot['has_refresh_token'] and not snapshot['actual_user_verified'] and not snapshot['api_use_authorized']
    assert snapshot['snapshot_sha256']==digest({k:v for k,v in snapshot.items() if k!='snapshot_sha256'})
    assert 'rejected-private-refresh-fixture' not in json.dumps(snapshot) and 'client_secret' not in json.dumps(snapshot)
    inbox.db.execute("UPDATE google_chat_oauth_quarantine SET tokens='{}'")
    with pytest.raises(Conflict):view(inbox.db.execute('SELECT * FROM google_chat_oauth_quarantine').fetchone(),account())
    inbox.close()
