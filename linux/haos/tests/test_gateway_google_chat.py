"""Independent pre-native Google Chat route/epoch authority; no account traffic."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import time
import pytest
from haos.gateway import GatewayPolicy
from haos.gateway_google_chat import credentials,scope,PreparedGoogleChatPolicy
from haos.gateway_google_chat_admission import approve,Refused


def account():
    project='haos-fixture';email='gateway@'+project+'.iam.gserviceaccount.com'
    return {'service_account':{'type':'service_account','project_id':project,'private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n',
        'client_email':email,'client_id':'123456789','auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')},
        'bot_user':'users/999','inbound':{'mode':'pubsub','subscription':'projects/'+project+'/subscriptions/haos-private'}}


def binding():return {'id':'owner','connector':'google','sender':'users/123','chat':'spaces/space1','thread':'spaces/space1/threads/thread1',
    'scope':scope(account()),'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-60)*1000),'require_mention':True}


def policy(**change):return PreparedGoogleChatPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],
    'bindings':[{**binding(),**change}]})


def event():return {'type':'MESSAGE','space':{'name':'spaces/space1','spaceType':'SPACE'},'message':{
    'name':'spaces/space1/messages/msg1','thread':{'name':'spaces/space1/threads/thread1'},
    'sender':{'name':'users/123','type':'HUMAN','email':'mutable-display@example.invalid'},
    'createTime':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'text':'<users/999> /status','argumentText':'/status',
    'annotations':[{'type':'USER_MENTION','userMention':{'user':{'name':'users/999'}}}]}}


def admitted(data=None,selected=None):return approve(selected or policy(),'google',account(),json.dumps(data or event()).encode())


def test_stable_resource_authority_does_not_derive_rights_from_email_or_public_native_registry():
    data=event();first=admitted(data);data['message']['sender']['email']='owner@example.invalid';second=admitted(data)
    assert first['envelope']==second['envelope'] and first['raw_sha256']!=second['raw_sha256']
    assert first['envelope']['sender']=='users/123' and first['envelope']['thread']=='spaces/space1/threads/thread1'
    with pytest.raises(ValueError):GatewayPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[]})


@pytest.mark.parametrize('path,value',[
    (['message','sender','name'],'users/124'),(['message','sender','name'],'owner@example.invalid'),
    (['message','sender','name'],'users/999'),(['message','sender','type'],'BOT'),
    (['message','thread','name'],'spaces/space2/threads/thread1'),(['message','thread','name'],'spaces/space1/threads/thread2'),
    (['message','name'],'spaces/space2/messages/msg1'),(['message','name'],'display-name'),
    (['message','createTime'],'2020-01-01T00:00:00Z'),(['message','createTime'],'2099-01-01T00:00:00Z'),
    (['message','createTime'],'2026-10-30T12:00:00+00:00'),(['message','annotations'],[]),
    (['message','annotations'],[{'type':'USER_MENTION','userMention':{'user':{'name':'users/111'}}}]),
    (['message','attachment'],[{'contentType':'image/png','attachmentDataRef':{'resourceName':'private-blob'}}]),
    (['message','attachment'],[{'contentType':'audio/ogg'}]),(['message','attachment'],[{'contentType':'video/mp4'}]),
    (['message','space'],{'name':'spaces/space2'}),(['type'],'ADDED_TO_SPACE'),(['space','spaceType'],'UNKNOWN')])
def test_unknown_or_cross_space_sources_pregrant_replay_and_unapproved_resources_are_refused_before_native_work(path,value):
    data=event();target=data
    for key in path[:-1]:target=target[key]
    target[path[-1]]=value
    with pytest.raises(Refused):admitted(data)


def test_workspace_addons_same_identity_and_exact_thread_remain_admitted_but_flat_relay_email_does_not_grant():
    data=event();wrapped={'chat':{'messagePayload':{'space':data['space'],'message':data['message']}}}
    assert admitted(wrapped)['envelope']==admitted(data)['envelope']
    with pytest.raises(Refused):admitted({'sender_email':'owner@example.invalid','space_name':'spaces/space1','text':'/status'})


@pytest.mark.parametrize('change',[
    {'sender':'owner@example.invalid'},{'thread':'spaces/other/threads/thread1'},{'scope':'global'},{'since':True},
    {'generation':None},{'allow_media':1},{'allow_voice':True,'capabilities':['read']},
    {'allow_outbound_media':True,'capabilities':['create']}])
def test_owner_grants_cannot_widen_resource_scope_time_or_media_capabilities(change):
    with pytest.raises(ValueError):policy(**change)


@pytest.mark.parametrize('field,value', [('token_uri','https://other.invalid/token'),('project_id','foreign-project'),
    ('client_email','foreign@haos-fixture.iam.gserviceaccount.com.evil.invalid'),('universe_domain','other.invalid'),('private_key','short')])
def test_service_account_cannot_redirect_key_use_or_borrow_another_project(field,value):
    selected=account();selected['service_account'][field]=value
    with pytest.raises(ValueError):credentials(selected)


def test_rotation_scope_binds_account_and_expected_bot_but_not_key_generation():
    selected=account();old=scope(selected);selected['service_account']['private_key_id']='b'*40
    assert scope(selected)==old
    selected['bot_user']='users/998';assert scope(selected)!=old


def test_real_google_dotted_message_resource_is_admitted_without_allowing_path_aliases():
    data=event();data['message']['name']='spaces/space1/messages/lfQmhKmhYI4.lfQmhKmhYI4'
    assert admitted(data)['envelope']['message_id']==data['message']['name']
    for name in ['spaces/space1/messages/../other','spaces/space1/messages/a..b','spaces/space1/messages/a%2Fb']:
        data['message']['name']=name
        with pytest.raises(Refused):admitted(data)
