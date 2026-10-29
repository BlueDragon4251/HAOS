import pytest
from haos.gateway import GatewayPolicy
from haos.gateway_feishu import credentials,scope,validate_binding,PreparedFeishuPolicy


def account():return {'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-fixture',
    'domain':'feishu','tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}


def binding():return {'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,
    'scope':scope(account()),'thread':'','identity':'personal','capabilities':['create','read'],
    'generation':'d'*64,'since':123,'require_mention':True}


def test_feishu_remains_private_until_transport_delivery_recovery_and_gui_are_connected():
    policy={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding()]}
    with pytest.raises(ValueError):GatewayPolicy(policy)
    assert PreparedFeishuPolicy(policy).bindings['owner']==binding()
    assert credentials(account())==account()


@pytest.mark.parametrize('change',[{'app_id':'https://other.invalid'},{'app_id':'*'},{'app_secret':'short'},
    {'app_secret':'private\nsecretvalue'},{'app_secret':' private-fixture-secret'},{'domain':'https://open.feishu.cn'},
    {'domain':'other'},{'tenant_key':'*'},{'bot_open_id':'ou_*'},{'connection_mode':'plugin'},{'connection_mode':[]},{'connection_mode':{}},
    {'extra':{'plugin':'external'}},{'verification_token':'unused-private-secret'}])
def test_private_feishu_account_refuses_ambiguous_identity_unused_secrets_and_caller_endpoints(change):
    with pytest.raises(ValueError):credentials({**account(),**change})


def test_feishu_scope_binds_exact_brand_app_tenant_and_bot_but_not_rotatable_secret():
    value=account()
    assert scope({**value,'app_secret':'rotated-private-fixture'})==scope(value)
    for change in [{'domain':'lark'},{'tenant_key':'another_tenant'},{'app_id':'cli_fedcba9876543210'},{'bot_open_id':'ou_'+'f'*32}]:
        assert scope({**value,**change})!=scope(value)


@pytest.mark.parametrize('change',[{'sender':'on_'+'b'*32},{'sender':'display-name'},{'chat':'*'},{'chat':'ou_'+'c'*32},
    {'scope':'global'},{'thread':'om_'+'a'*32},{'thread':'*'},{'generation':None},{'since':True},
    {'require_mention':'false'},{'allow_media':'true'},{'allow_voice':True,'capabilities':['read']},
    {'allow_outbound_media':True,'capabilities':['create']}])
def test_private_feishu_grants_refuse_aliases_wildcards_wrong_native_thread_or_media_authority(change):
    with pytest.raises(ValueError):validate_binding({**binding(),**change})


def test_feishu_native_topic_is_explicit_and_media_requires_separate_flags():
    value={**binding(),'thread':'omt_'+'e'*32,'allow_media':True,'allow_voice':True,'allow_video':True,'allow_outbound_media':True}
    validate_binding(value)
    assert not any(binding().get(key,False) for key in ['allow_media','allow_voice','allow_video','allow_outbound_media'])


@pytest.mark.parametrize('missing',['verification_token','encrypt_key','tls','port'])
def test_webhook_mode_requires_all_actual_secrets_and_private_HTTPS_settings(missing):
    value={**account(),'connection_mode':'webhook','verification_token':'private-token-fixture',
        'encrypt_key':'private-encryption-fixture','port':8648,'tls':{}}
    del value[missing]
    with pytest.raises(ValueError):credentials(value)


def test_shared_webhook_TLS_material_never_accepts_an_unreviewed_route():
    from haos.gateway_line_tls import material
    with pytest.raises(ValueError,match='reviewed webhook TLS path'):material({},webhook_path='/unreviewed')
