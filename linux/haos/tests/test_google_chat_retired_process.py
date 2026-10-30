"""Historical Owner responses must never turn metadata into active delegation."""
from copy import deepcopy
import pytest

from haos.gateway import digest
from haos.gateway_google_chat_identity import descriptor,account_scope
from haos.gateway_google_chat_oauth import SCOPES,client,client_for_identity,route
from haos.google_chat_retired_process import response
from test_gateway_google_chat import account,policy
from test_gateway_google_chat_oauth import configuration


def selected():
    identity=descriptor(account());row={'profile':'google-chat-'+digest(account_scope(identity)),
        'identity':identity,'identity_sha256':digest(identity)}
    return {**row,'snapshot_sha256':digest(row)}


def token_view():
    app=selected();public=configuration();public['installed'].pop('client_secret')
    row={'id':'a'*64,'account_scope':account_scope(app['identity']),'subject':'users/123','client_sha256':'b'*64,
        'status':'active','updated_at':1,'generation':1,'public_client':public,'transport_status':'ready','next_attempt':0,
        'scopes':list(SCOPES),'scope_upgrade_required':False,'current_file_grants':0,'private_credentials_returned':False}
    row['snapshot_sha256']=digest(row)
    return {'active_authorization_returned':False,'account':app,'result':{'tokens':[row],'history_truncated':False,'network_requested':False,'private_credentials_returned':False}}


def test_historical_public_client_validation_never_satisfies_full_account_enrollment_or_current_route_gate():
    identity=selected()['identity'];assert client_for_identity(configuration(),identity)==configuration()
    with pytest.raises(ValueError):client(configuration(),identity)
    selected_policy=policy(allow_outbound_media=True);binding=selected_policy.bindings['owner']
    with pytest.raises(ValueError):route(selected_policy,'google',identity,'owner',digest(binding))


def test_historical_inventory_is_bound_to_exact_profile_public_identity_and_reports_no_active_file_grants():
    value=token_view();assert response(value,'tokens',request={'profile':value['account']['profile']})==value
    with pytest.raises(ValueError):response(value,'tokens',request={'profile':'google-chat-'+'f'*64})


@pytest.mark.parametrize('case',['active-grant','foreign-scope','foreign-project','client-secret','credential','changed-profile','changed-bot','network','private-flag'])
def test_even_self_consistent_historical_snapshots_cannot_return_secrets_foreign_accounts_or_active_authorization(case):
    value=token_view();row=value['result']['tokens'][0]
    if case=='active-grant':row['current_file_grants']=1
    elif case=='foreign-scope':row['account_scope']='google-chat:'+'f'*64
    elif case=='foreign-project':row['public_client']['installed']['project_id']='foreign-project'
    elif case=='client-secret':row['public_client']['installed']['client_secret']='private-fixture-material'
    elif case=='credential':row['credential']='private-fixture-material'
    elif case=='changed-profile':value['account']['profile']='google-chat-'+'f'*64
    elif case=='changed-bot':value['account']['identity']['bot_user']='users/998'
    elif case=='network':value['result']['network_requested']=True
    else:value['result']['private_credentials_returned']=True
    row['snapshot_sha256']=digest({k:v for k,v in row.items() if k!='snapshot_sha256'})
    app=value['account'];app['identity_sha256']=digest(app['identity']);app['snapshot_sha256']=digest({k:v for k,v in app.items() if k!='snapshot_sha256'})
    with pytest.raises(ValueError):response(value,'tokens')


@pytest.mark.parametrize('case',['duplicates','too-many','secret-field','missing-duplicate','not-opaque'])
def test_historical_profile_lists_are_bounded_unique_and_payload_free(case):
    app=selected();value={'profiles':[app],'identity_missing':[],'history_truncated':False,'network_requested':False,'private_credentials_returned':False}
    if case=='duplicates':value['profiles'].append(deepcopy(app))
    elif case=='too-many':value['profiles']*=129
    elif case=='secret-field':value['profiles'][0]['private_key']='private-fixture-material'
    elif case=='missing-duplicate':value['identity_missing']=[app['profile']]
    else:value['identity_missing']=['../private']
    with pytest.raises(ValueError):response(value,'profiles')


@pytest.mark.parametrize('case',['wrong-id','message','fake-confirmed','bad-delay','private'])
def test_historical_withdrawal_response_cannot_change_selected_token_or_claim_messages_or_unconfirmed_remote_success(case):
    app=selected();result={'id':'a'*64,'receipt':'b'*64,'remote_status':'confirmed','remote_revocation_verified':True,
        'network_requested':True,'message_sent':False,'retry_after':0,'private_credentials_returned':False,'locally_revoked':True}
    value={'account':app,'result':result,'active_authorization_returned':False};request={'profile':app['profile'],'identity_sha256':app['identity_sha256'],'id':'a'*64}
    if case=='wrong-id':result['id']='f'*64
    elif case=='message':result['message_sent']=True
    elif case=='fake-confirmed':result['remote_revocation_verified']=False
    elif case=='bad-delay':result['retry_after']=True
    else:result['token']='private-fixture-material'
    with pytest.raises(ValueError):response(value,'revoke-token',request=request)


@pytest.mark.parametrize('error',[[],{},False,'private traceback'])
def test_historical_worker_errors_are_closed_finite_codes(error):
    with pytest.raises(ValueError):response({'error':error},'profiles')


def test_historical_status_reports_actual_published_grants_as_information_without_returning_api_authorization():
    value=token_view();selected_policy=policy(allow_outbound_media=True);row=value['result']['tokens'][0]
    row['current_file_grants']=1;row['snapshot_sha256']=digest({k:v for k,v in row.items() if k!='snapshot_sha256'})
    assert response(value,'tokens',policy=selected_policy)['active_authorization_returned'] is False
    with pytest.raises(ValueError):response(value,'tokens')
    value['active_authorization_returned']=True
    with pytest.raises(ValueError):response(value,'tokens',policy=selected_policy)


def repaired():
    app=selected()
    return {'account':app,'active_authorization_returned':False,'result':{'profile':app['profile'],'identity_sha256':app['identity_sha256'],
        'receipt':'e'*64,'public_identity_restored':True,'network_requested':False,'credentials_changed':False,'private_credentials_returned':False}}


def test_identity_repair_receipt_is_exact_original_public_metadata_without_new_credentials_or_api_authority():
    value=repaired();request={'profile':value['account']['profile'],'identity':value['account']['identity']}
    assert response(value,'restore-identity',request=request)==value
    with pytest.raises(ValueError):response(value,'restore-identity',request={**request,'profile':'google-chat-'+'f'*64})
    with pytest.raises(ValueError):response(value,'restore-identity',request={**request,'identity':{**request['identity'],'bot_user':'users/998'}})


@pytest.mark.parametrize('case',['network_requested','credentials_changed','private_credentials_returned','active_authorization_returned','foreign-profile','foreign-identity','private-field'])
def test_identity_repair_cannot_replace_original_identity_or_return_secrets_network_or_authorization(case):
    value=repaired();result=value['result']
    if case in {'network_requested','credentials_changed','private_credentials_returned'}:result[case]=True
    elif case=='active_authorization_returned':value[case]=True
    elif case=='foreign-profile':result['profile']='google-chat-'+'f'*64
    elif case=='foreign-identity':result['identity_sha256']='f'*64
    else:result['service_account']={'private_key':'must-not-return'}
    with pytest.raises(ValueError):response(value,'restore-identity')


@pytest.mark.parametrize('case',['foreign-scope','foreign-project','api-use','verified','private-client','private-payload'])
def test_historical_rejected_token_metadata_cannot_claim_verified_user_api_authority_or_private_client_material(case):
    # Actual capsule construction is covered by existing SQLite tests; this
    # response contract intentionally exercises independently forged metadata.
    app=selected();public=configuration();public['installed'].pop('client_secret')
    row={'id':'a'*64,'pending_id':'b'*64,'account_scope':account_scope(app['identity']),'subject_expected':'users/123',
        'client_sha256':'c'*64,'tokens_sha256':'d'*64,'state':'rejected','created_at':1,'origin':'enrollment','public_client':public,
        'stored_bytes':100,'has_refresh_token':True,'actual_user_verified':False,'api_use_authorized':False,
        'remote_revocation_verified':False,'private_credentials_returned':False}
    if case=='foreign-scope':row['account_scope']='google-chat:'+'f'*64
    elif case=='foreign-project':row['public_client']['installed']['project_id']='foreign-project'
    elif case=='api-use':row['api_use_authorized']=True
    elif case=='verified':row['actual_user_verified']=True
    elif case=='private-client':row['public_client']['installed']['client_secret']='private-fixture-material'
    else:row['tokens']={'refresh_token':'private-fixture-material'}
    row['snapshot_sha256']=digest(row)
    value={'account':app,'active_authorization_returned':False,'result':{'quarantines':[row],'history_truncated':False,'network_requested':False,'private_credentials_returned':False}}
    with pytest.raises(ValueError):response(value,'quarantines')
