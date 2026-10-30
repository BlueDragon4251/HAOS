"""Prepared A2A identity contracts; no public activation or native transport claim."""
import pytest
import json
from haos.gateway import GatewayPolicy
from haos.gateway_a2a import PreparedA2APolicy,credentials,validate_binding,scope


def account():return {'peer_tokens':{'alice':'private_fixture_peer_alice_'+'a'*32},'port':8448,
    'tls':{'public_url':'https://a2a.fixture.invalid/a2a','private_key':'private fixture TLS bytes'},'agent_name':'HAOS'}


def binding():return {'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-owner-device','scope':scope(account(),'alice'),
    'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':123}


def test_public_a2a_policy_keeps_independent_exact_owner_grants():
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[binding()]}
    assert PreparedA2APolicy(config).bindings['owner']==binding()
    assert GatewayPolicy(config).bindings['owner']==binding()
    changed=PreparedA2APolicy({**config,'bindings':[]})
    with pytest.raises(PermissionError):changed.authorize('a2a',{'platform':'a2a','sender':'alice','chat':'ctx-owner-device',
        'scope':scope(account(),'alice'),'thread':'','message_id':'source-fixture','text':'untrusted peer message','is_bot':False})


@pytest.mark.parametrize('change',[{'peer_tokens':{}},{'peer_tokens':{'all':'a'*64}},{'peer_tokens':{'ip:127.0.0.1':'a'*64}},
    {'peer_tokens':{'alice':'short'}},{'peer_tokens':{'alice':'a'*64,'bob':'a'*64}},
    {'peer_tokens':{'alice':'a'*64+',bob:another-token'}},{'port':443},{'port':True},{'agent_name':'bad\nname'},
    {'bearer_token':'shared-localhost-authority'},{'plugin':'arbitrary'},{'agents':[{'profile':'owner'}]}])
def test_account_refuses_shared_or_ambiguous_peer_auth_arbitrary_plugins_and_bad_listener_before_TLS(change):
    with pytest.raises(ValueError):credentials({**account(),**change})


@pytest.mark.parametrize('change',[{'sender':'*'},{'sender':'ip:127.0.0.1'},{'sender':'anonymous'},{'chat':'https://other.invalid'},
    {'chat':'all'},{'scope':'global'},{'thread':'topic'},{'since':True},{'generation':None},{'capabilities':['owner']},
    {'capabilities':[{}]},{'capabilities':['read','read']}])
def test_binding_requires_exact_peer_context_server_and_fresh_independent_grant(change):
    with pytest.raises(ValueError):validate_binding({**binding(),**change})


@pytest.mark.parametrize('public_name',['agent_name','peer_name'])
def test_public_agent_and_peer_names_cannot_reflect_private_tokens(public_name):
    token='private_fixture_token_'+'a'*32
    value={**account(),'peer_tokens':{'alice':token}}
    if public_name=='agent_name':value['agent_name']=token
    else:value['peer_tokens']={token:token}
    with pytest.raises(ValueError,match='public A2A names'):credentials(value)


@pytest.mark.parametrize('metadata',[None,{}, {'haosQuestionEpoch':False},{'haosQuestionEpoch':'*'},
    {'haosQuestionEpoch':'a'*64,'plugin':'approve-everything'}])
def test_continuation_requires_closed_exact_question_pointer_before_optional_SDK_import(metadata):
    from haos.gateway_a2a_admission import approve,Refused
    from haos.redaction import Redactor
    b={**binding(),'capabilities':['create','read','answer']}
    policy=PreparedA2APolicy({'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[b]})
    request={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':{
        'messageId':'retained-answer','contextId':b['chat'],'role':'ROLE_USER','parts':[{'text':'once'}],
        'taskId':'task-'+'a'*16,'metadata':metadata}}}
    with pytest.raises(Refused) as error:approve(policy,'a2a',account(),'alice',json.dumps(request).encode(),Redactor())
    assert error.value.reason=='exact-question-epoch-required'


@pytest.mark.parametrize('caps',[['pause'],['resume'],['cancel'],['answer']])
def test_public_a2a_policy_rejects_unsupported_pause_or_control_without_read(caps):
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[{**binding(),'capabilities':caps}]}
    with pytest.raises(ValueError):GatewayPolicy(config)
