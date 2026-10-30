import pytest
from haos.gateway import GatewayPolicy
from haos.gateway_dingtalk import credentials,scope,validate_binding,PreparedDingTalkPolicy


def account():return {'client_id':'ding_private_fixture_app','client_secret':'private-dingtalk-fixture',
    'corp_id':'ding_fixture_corporation','robot_code':'ding_fixture_robot'}


def binding():return {'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
    'scope':scope(account()),'thread':'','identity':'personal','capabilities':['create','read'],
    'generation':'a'*64,'since':123,'require_mention':True}


def test_public_dingtalk_policy_preserves_exact_timed_independent_grants():
    value={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[binding()]}
    assert credentials(account())==account() and PreparedDingTalkPolicy(value).bindings['owner']==binding()
    assert GatewayPolicy(value).bindings['owner']==binding()


@pytest.mark.parametrize('change',[{'client_id':'https://other.invalid'},{'client_secret':'short'},
    {'client_secret':' private app secret'},{'corp_id':'*'},{'robot_code':'display name'},
    {'url':'https://other.invalid'},{'plugin':'unreviewed'},{'token':'unused-private-credential'}])
def test_prepared_identity_refuses_arbitrary_endpoints_extra_auth_and_ambiguous_values(change):
    with pytest.raises(ValueError):credentials({**account(),**change})


@pytest.mark.parametrize('change',[{'sender':'*'},{'sender':'Owner display name'},{'chat':'https://other.invalid'},
    {'scope':'global'},{'thread':'unreviewed-topic'},{'generation':None},{'since':True},
    {'require_mention':'false'},{'allow_voice':True,'capabilities':['read']},{'allow_outbound_media':True,'capabilities':['create']},
    {'capabilities':None},{'capabilities':[{}]},{'allow_media':1}])
def test_exact_grants_refuse_alias_routes_untimed_approval_and_mismatched_rights(change):
    with pytest.raises(ValueError):validate_binding({**binding(),**change})


def test_scope_preserves_private_secret_rotation_but_binds_the_exact_app_corporation_and_robot():
    value=account();assert scope({**value,'client_secret':'changed-private-fixture'})==scope(value)
    for key in ['client_id','corp_id','robot_code']:assert scope({**value,key:'ding_other_fixture_identity'})!=scope(value)


@pytest.mark.parametrize('change',[{'scope':'dingtalk:'+'0'*64},{'sender':account()['robot_code']},
    {'allow_outbound_media':True}])
def test_public_snapshot_checks_saved_corporation_robot_and_explicit_reply_route(change):
    from haos.gateway_publication import validate_snapshot
    value={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[{**binding(),**change}]}
    with pytest.raises(ValueError):validate_snapshot(value,{'connectors':{'dingtalk':account()}})
