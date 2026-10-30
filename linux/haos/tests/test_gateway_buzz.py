"""Prepared Buzz boundaries do not load optional Hermes or activate its registry."""
import pytest
from haos.gateway import GatewayPolicy
from haos.gateway_buzz import credentials,relay,channel,scope,PreparedBuzzPolicy


def account():return {'private_key':'1'*64,'public_key':'2'*64,'relay_url':'https://buzz.fixture.invalid',
    'channels':['01234567-89ab-4cde-8012-3456789abcde']}


def binding():return {'id':'owner','connector':'buzz','sender':'3'*64,'chat':account()['channels'][0],
    'scope':scope(account()),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1}


@pytest.mark.parametrize('url',['http://buzz.fixture.invalid','https://user:password@buzz.fixture.invalid',
    'https://buzz.fixture.invalid/','https://BUZZ.fixture.invalid','https://buzz.fixture.invalid?private=1',
    'https://buzz.fixture.invalid#fragment','https://buzz.fixture.invalid:443','https://buzz.fixture.invalid\\evil'])
def test_relay_is_an_exact_owner_selected_TLS_origin_without_ambient_credentials_or_ambiguous_aliases(url):
    with pytest.raises(ValueError):relay(url)


@pytest.mark.parametrize('change',[{'private_key':'0'*64},{'private_key':'f'*64},{'private_key':'short'},
    {'public_key':'npub-ambiguous'},{'channels':[]},{'channels':['all']},{'cli_path':'/tmp/agent-program'},
    {'plugin':'auto-authorize'},{'auth_tag':'["auth", null, true, "signature"]'}])
def test_account_rejects_weak_or_out_of_range_keys_implicit_channels_external_programs_and_untyped_owner_attestations(change):
    with pytest.raises(ValueError):credentials({**account(),**change})


def test_native_policy_requires_independent_exact_grants_and_never_activates_unknown_plugins():
    config={'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':[{**binding(),'allow_media':True}]}
    assert PreparedBuzzPolicy(config).bindings['owner']['allow_media'] is True
    assert GatewayPolicy(config).bindings==PreparedBuzzPolicy(config).bindings
    with pytest.raises(ValueError):GatewayPolicy({**config,'connectors':[{'id':'buzz','platform':'unreviewed-plugin'}]})
    denied=GatewayPolicy({**config,'bindings':[]})
    with pytest.raises(PermissionError):denied.authorize('buzz',{'platform':'buzz','sender':'3'*64,
        'chat':binding()['chat'],'scope':scope(account()),'thread':'','message_id':'4'*64,'is_bot':False,'text':'untrusted'})


@pytest.mark.parametrize('change',[{'sender':'*'},{'sender':'npub-wildcard'},{'chat':'all'},{'thread':'*'},
    {'scope':'global'},{'generation':None},{'since':True},{'allow_media':1},{'allow_voice':True,'capabilities':['read']},
    {'allow_outbound_media':True,'capabilities':['create']}])
def test_prepared_binding_cannot_widen_identity_thread_epoch_or_media_rights(change):
    config={'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':[{**binding(),**change}]}
    with pytest.raises(ValueError):PreparedBuzzPolicy(config)


@pytest.mark.parametrize('bindings',[None,'owner',[None],[binding()]*513])
def test_prepared_policy_preserves_generic_binding_shape_and_capacity_limits(bindings):
    with pytest.raises(ValueError):PreparedBuzzPolicy({'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':bindings})


def test_signed_source_parser_does_not_accept_duplicate_identity_keys_untyped_time_or_unbounded_metadata():
    from haos.gateway_buzz_crypto import wire
    import json
    event={'id':'a'*64,'pubkey':'b'*64,'created_at':1793332800,'kind':9,'tags':[['h',binding()['chat']]],'content':'untrusted','sig':'c'*128}
    assert wire(json.dumps(event).encode())==event
    invalid=[json.dumps({**event,'created_at':True}).encode(),json.dumps({**event,'tags':[['h','bad\npath']]}).encode(),
        json.dumps({**event,'tags':[['h','x'*4097]]}).encode(),json.dumps({**event,'content':'x'*32001}).encode(),
        json.dumps(event).encode()[:-1]+b',"pubkey":"'+b'd'*64+b'"}',b'x'*1048577]
    for raw in invalid:
        with pytest.raises(ValueError):wire(raw)
