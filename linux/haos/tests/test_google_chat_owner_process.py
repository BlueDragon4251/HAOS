"""Closed Owner result schemas and preserved pre-recovery journal migration."""
from copy import deepcopy
import sqlite3
import pytest

from haos.gateway import digest
from haos.google_chat_owner_process import response
from haos.gateway_google_chat_recovery import sources,outgoing,approve_retry
from haos.gateway_google_chat_text import TextLedger
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from test_gateway_google_chat import account,policy
from test_gateway_google_chat_recovery import opened,reply_group,reply_request


def test_real_recovery_snapshots_and_decisions_pass_closed_payload_free_root_response_schema(tmp_path):
    inbox,selected,value,group=reply_group(tmp_path);inventory=outgoing(inbox,selected,'google',value)
    assert response(inventory,'outgoing','google')==inventory
    result=approve_retry(inbox,selected,'google',value,reply_request(inventory['outgoing'][0]))
    assert response(result,'approve-retry','google')==result
    inbox.close()
    original=tmp_path/'original';original.mkdir();store,selected,key,profile=opened(original)
    inventory=sources(store,selected,profile);assert response(inventory,'sources','google')==inventory
    assert response({'profiles':[profile],'history_truncated':False,'network_requested':False,'private_bytes_returned':False},'source-profiles','google')['profiles']==[profile]
    store.close()


@pytest.mark.parametrize('path,change',[
    (['network_requested'],True),(['private_bytes_returned'],True),(['outgoing',0,'body'],'private content'),
    (['outgoing',0,'connector'],'foreign'),(['outgoing',0,'current_grant'],'yes'),(['outgoing',0,'recipient_read_verified'],True),
    (['outgoing',0,'confirmed_parts'],2),(['outgoing',0,'parts',1,'state'],'confirmed'),
    (['outgoing',0,'parts',1,'retry_generation'],True),(['outgoing',0,'parts',0,'receipt'],'spaces/foreign/messages/receipt'),
    (['outgoing',0,'snapshot_sha256'],'0'*64)])
def test_root_rejects_unknown_fields_fabricated_receipts_cross_connector_private_or_changed_snapshots(tmp_path,path,change):
    inbox,selected,value,group=reply_group(tmp_path);inventory=outgoing(inbox,selected,'google',value);target=deepcopy(inventory)
    current=target
    for part in path[:-1]:current=current[part]
    current[path[-1]]=change
    with pytest.raises((ValueError,PermissionError)):response(target,'outgoing','google')
    inbox.close()


def test_previous_private_text_journal_migrates_without_discarding_unknown_or_confirmed_writes(tmp_path):
    tmp_path.chmod(0o700);inbox=NativeInbox(tmp_path/'legacy.sqlite',Redactor([]))
    inbox.db.execute('CREATE TABLE google_chat_text_writes(id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,parent TEXT NOT NULL,body TEXT NOT NULL,client_id TEXT NOT NULL,request_id TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,created_at REAL NOT NULL)')
    for identity,state in [('a'*64,'writing'),('b'*64,'confirmed')]:
        inbox.db.execute('INSERT INTO google_chat_text_writes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (identity,'owner','c'*64,'d'*64,'spaces/room','{"text":"original"}','client-'+identity[:56],'preserved-request',state,'spaces/room/messages/old' if state=='confirmed' else '',1))
    before=[tuple(row) for row in inbox.db.execute('SELECT * FROM google_chat_text_writes ORDER BY id')]
    TextLedger(inbox,'google',account(),policy,lambda:None)
    after=[tuple(row) for row in inbox.db.execute('SELECT * FROM google_chat_text_writes ORDER BY id')]
    assert [row[:-1] for row in after]==before and all(row[-1]==0 for row in after)
    assert inbox.db.execute('PRAGMA synchronous').fetchone()[0]==2;inbox.close()


def oauth_url_result():
    from urllib.parse import urlencode
    from haos.gateway_google_chat_oauth import SCOPES,REDIRECT_URI
    params={'response_type':'code','client_id':'123456789-private-fixture.apps.googleusercontent.com','redirect_uri':REDIRECT_URI,
        'scope':' '.join(SCOPES),'state':'a'*43,'nonce':'b'*43,'access_type':'offline','prompt':'consent','include_granted_scopes':'false',
        'code_challenge':'c'*43,'code_challenge_method':'S256'}
    return {'id':'d'*64,'authorization_url':'https://accounts.google.com/o/oauth2/auth?'+urlencode(params),'subject':'users/123',
        'expires_at':1793360000,'network_requested':False,'message_sent':False,'private_verifier_or_credentials_returned':False}


def test_owner_authorization_response_is_closed_and_bound_to_root_selected_client_and_stable_subject():
    value=oauth_url_result();request={'client':{'installed':{'client_id':'123456789-private-fixture.apps.googleusercontent.com'}},'subject':'users/123'}
    assert response(value,'oauth-begin','google',request=request)==value
    for changes in [{'subject':'users/124'},{'client':{'installed':{'client_id':'other-client'}}}]:
        with pytest.raises(ValueError):response(value,'oauth-begin','google',request={**request,**changes})


@pytest.mark.parametrize('case',['foreign','verifier','token','private-flag','bare-code','duplicate-state'])
def test_root_refuses_authorization_urls_with_foreign_targets_or_secret_material_and_callback_ambiguity(case):
    value=oauth_url_result()
    if case=='foreign':value['authorization_url']=value['authorization_url'].replace('accounts.google.com','foreign.invalid')
    elif case=='verifier':value['authorization_url']+='&code_verifier=private-fixture-verifier'
    elif case=='token':value['token']='private-fixture-access'
    elif case=='private-flag':value['private_verifier_or_credentials_returned']=True
    elif case=='bare-code':value['authorization_url']='local-code-fixture'
    elif case=='duplicate-state':value['authorization_url']+='&state='+('a'*43)
    with pytest.raises(ValueError):response(value,'oauth-begin','google')


@pytest.mark.parametrize('field,change',[
    ('client_secret','private-material'),('client_id','private-material'),('project_id','../foreign'),
    ('auth_uri','https://foreign.invalid/auth'),('token_uri','https://foreign.invalid/token'),
    ('auth_provider_x509_cert_url','https://foreign.invalid/certs'),('redirect_uris',['https://foreign.invalid/callback'])])
def test_root_refuses_private_or_foreign_client_values_even_when_capsule_snapshot_is_self_consistent(tmp_path,field,change):
    from test_gateway_google_chat_oauth import opened as oauth_opened,begin,returned
    from haos.gateway_google_chat_oauth import quarantine
    from haos.gateway_google_chat_oauth_quarantine import view
    inbox,store,selected=oauth_opened(tmp_path);pending=begin(store,selected)
    store.exchange(selected,'google',account(),pending['id'],returned(pending),owner_uid=1000)
    quarantine(store,pending,{'refresh_token':'private-rejected-fixture'},'identity-refused')
    row=view(inbox.db.execute('SELECT * FROM google_chat_oauth_quarantine').fetchone(),account())
    value={'quarantines':[row],'history_truncated':False,'network_requested':False,'private_credentials_returned':False}
    assert response(value,'oauth-quarantines','google')==value
    row['public_client']['installed'][field]=change
    row['snapshot_sha256']=digest({k:v for k,v in row.items() if k!='snapshot_sha256'})
    with pytest.raises(ValueError):response(value,'oauth-quarantines','google')
    inbox.close()
