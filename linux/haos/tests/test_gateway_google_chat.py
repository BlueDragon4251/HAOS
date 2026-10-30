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


def test_whole_space_threads_require_explicit_owner_choice_and_keep_sender_account_space_boundaries():
    selected=policy(thread='',all_threads=True)
    first=admitted(selected=selected)
    data=event();data['message']['thread']['name']='spaces/space1/threads/next'
    assert admitted(data,selected)['envelope']['thread']=='spaces/space1/threads/next'
    for changes in [{'sender':'users/456'},{'scope':'google-chat:'+'b'*64},{'chat':'spaces/another'},
            {'thread':'spaces/other/threads/next'},{'thread':'*'}]:
        with pytest.raises((PermissionError,ValueError)):
            selected.authorize('google',{**first['envelope'],**changes})
    with pytest.raises(Refused):admitted(selected=policy(thread='',all_threads=False))
    with pytest.raises(ValueError):policy(all_threads=True)
    with pytest.raises(ValueError):policy(thread='',all_threads='true')


def test_whole_space_grant_cannot_shadow_a_separate_specific_thread_identity_in_either_order():
    exact=binding();wide={**exact,'id':'wide','thread':'','all_threads':True,'identity':'different'}
    for rows in [[exact,wide],[wide,exact]]:
        with pytest.raises(ValueError,match='overlap'):
            PreparedGoogleChatPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':rows})


def test_real_controller_queues_mission_and_status_replies_to_actual_source_threads_under_explicit_space_consent(tmp_path):
    import asyncio
    from haos.controller import Controller
    from haos.store import MissionStore
    store=MissionStore(tmp_path/'missions.sqlite');selected=policy(thread='',all_threads=True)
    controller=Controller(store,'ws://127.0.0.1:9119/api/ws',{1000})
    source=admitted(selected=selected)['envelope'];source={**source,'text':'Create a local plan'}
    first=asyncio.run(controller.gateway.receive(selected,'google',source,controller))
    other={**source,'thread':'spaces/space1/threads/second','message_id':'spaces/space1/messages/query2','text':'/status '+first['mission_id']}
    assert asyncio.run(controller.gateway.receive(selected,'google',other,controller))['mission_id']==first['mission_id']
    assert len(store.list())==1
    routes=store.db.execute('SELECT id,thread,reply_to FROM gateway_routes ORDER BY thread').fetchall()
    assert len(routes)==2 and len({r['id'] for r in routes})==2
    assert {(r['thread'],r['reply_to']) for r in routes}=={(source['thread'],source['message_id']),(other['thread'],other['message_id'])}
    pending=store.db.execute('SELECT r.thread FROM gateway_outbox o JOIN gateway_routes r ON r.id=o.route_id').fetchall()
    assert {r[0] for r in pending}=={source['thread'],other['thread']}
    assert asyncio.run(controller.gateway.receive(selected,'google',other,controller))['mission_id']==first['mission_id']
    assert store.db.execute('SELECT COUNT(*) FROM gateway_routes').fetchone()[0]==2
    store.close()


def test_current_delivery_all_threads_keeps_exact_chat_scope_and_hash_and_rejects_revocation():
    from types import SimpleNamespace
    from haos.gateway import digest
    from haos.gateway_delivery_authority import current_delivery
    selected=policy(thread='',all_threads=True);row=selected.bindings['owner']
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='google',policy=lambda:selected))
    metadata={'haos_binding':{'binding_id':'owner','binding_digest':digest(row)},'haos_scope':row['scope'],'thread_id':'spaces/space1/threads/second'}
    check=current_delivery(adapter,'google_chat',row['chat'],metadata);check()
    with pytest.raises(PermissionError):current_delivery(adapter,'google_chat','spaces/other',metadata)
    with pytest.raises(PermissionError):current_delivery(adapter,'google_chat',row['chat'],{**metadata,'thread_id':'spaces/other/threads/second'})
    selected.bindings['owner']['all_threads']=False
    with pytest.raises(PermissionError):check()


def test_google_rate_delay_preserves_longer_provider_deadlines_and_rejects_malformed_hints():
    from types import SimpleNamespace
    from haos.gateway_google_chat_retry import retry_after
    assert retry_after(SimpleNamespace(resp={'retry-after':'300'}))==300
    assert retry_after(SimpleNamespace(resp={'retry-after':'1'}))==60
    assert retry_after(SimpleNamespace(resp={'retry-after':'999999999'}))==86400
    for value in ['-10','not-a-date','NaN','Inf','x'*129]:assert retry_after(SimpleNamespace(resp={'retry-after':value}))==60


def test_private_token_response_captures_credentials_before_sdk_parsing_and_maps_errors_without_response_text():
    from types import SimpleNamespace
    from haos.gateway_google_chat_http import token_response,TokenError
    from haos.redaction import Redactor
    token='public-local-token-fixture';redactor=Redactor([]);url='https://oauth2.googleapis.com/token'
    valid=json.dumps({'access_token':token,'token_type':'Bearer','expires_in':3600}).encode()
    assert token_response(url,SimpleNamespace(status=200),valid,redactor=redactor)[1]==valid
    assert redactor.text(token)=='[REDACTED]'
    for raw in [b'not-json',b'{}',json.dumps({'access_token':token,'token_type':'Bearer','expires_in':'private-reflection-fixture'}).encode()]:
        with pytest.raises(TokenError) as caught:token_response(url,SimpleNamespace(status=200),raw)
        assert 'private-reflection-fixture' not in str(caught.value) and token not in str(caught.value)
        assert caught.value.reason=='invalid-token-response'
    with pytest.raises(TokenError) as caught:
        token_response(url,SimpleNamespace(status=400),json.dumps({'error':'invalid_grant','error_description':token}).encode())
    assert caught.value.reason=='invalid_grant' and token not in str(caught.value)


@pytest.mark.parametrize('nested',[
    {'name':'spaces/space1'}, {'name':'spaces/space1','displayName':'Different descriptive projection'},
    {'name':'spaces/space1','type':'ROOM'}, {'name':'spaces/space1','spaceType':'SPACE'}])
def test_partial_nested_space_projection_preserves_same_resource_type_authority(nested):
    data=event();data['message']['space']=nested
    assert admitted(data)['envelope']==admitted()['envelope']


@pytest.mark.parametrize('change',[
    {'type':'DM'}, {'spaceType':'DIRECT_MESSAGE'}, {'type':'ROOM','spaceType':'DIRECT_MESSAGE'},
    {'name':'spaces/foreign'}, {'type':[]}, {'type':'UNKNOWN'}])
def test_conflicting_nested_space_resource_or_kind_is_not_resolved_by_precedence(change):
    data=event();data['message']['space']={'name':'spaces/space1',**change}
    with pytest.raises(Refused):admitted(data)


def test_deprecated_room_type_can_describe_a_consistent_modern_group_chat_but_DM_cannot():
    data=event();data['space'].update(spaceType='GROUP_CHAT',type='ROOM');data['message']['space']={'name':'spaces/space1','type':'ROOM'}
    assert admitted(data)['envelope']['chat']=='spaces/space1'
    data['space']['type']='DM'
    with pytest.raises(Refused):admitted(data)


def test_legacy_space_alias_keeps_original_custody_semantic_hash_and_bytes_unchanged(tmp_path):
    from haos.gateway import digest
    from haos.gateway_google_chat_custody import Originals
    from haos.redaction import Redactor
    tmp_path.chmod(0o700);store=Originals(tmp_path/'originals.sqlite',Redactor([]))
    data=event();data['space']={'name':'spaces/space1','type':'ROOM'};raw=json.dumps(data).encode();selected=policy()
    identity=store.retain(selected,'google',account(),raw,lambda:None)
    before=tuple(store.db.execute('SELECT * FROM google_chat_originals').fetchone())
    assert store.db.execute('SELECT semantic_sha256 FROM google_chat_originals').fetchone()[0]==digest([data['message'],data['space']])
    assert store.load(identity,selected,'google',account(),lambda:None)[0]==raw
    assert tuple(store.db.execute('SELECT * FROM google_chat_originals').fetchone())==before
    store.close()
