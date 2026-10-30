"""Prepared A2A identity contracts; no public activation or native transport claim."""
import pytest
from haos.gateway import GatewayPolicy
from haos.gateway_a2a import PreparedA2APolicy,credentials,validate_binding,scope


def account():return {'peer_tokens':{'alice':'private_fixture_peer_alice_'+'a'*32},'port':8448,
    'tls':{'public_url':'https://a2a.fixture.invalid/a2a','private_key':'private fixture TLS bytes'},'agent_name':'HAOS'}


def binding():return {'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-owner-device','scope':scope(account(),'alice'),
    'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':123}


def test_prepared_a2a_policy_is_not_a_public_gateway_or_automatic_peer_grant():
    config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[binding()]}
    assert PreparedA2APolicy(config).bindings['owner']==binding()
    with pytest.raises(ValueError):GatewayPolicy(config)
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
