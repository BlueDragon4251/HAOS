import pytest

from haos.gateway_line_profile import credentials


def values():
    return {'channel_secret':'a'*32,'channel_access_token':'private-fixture-access','destination':'U'+'d'*32,'port':8646}


@pytest.mark.parametrize('change',[{'channel_secret':'bad'},{'channel_secret':'A'*32},
    {'channel_access_token':''},{'channel_access_token':'private\nfixture'},{'channel_access_token':'x'*8193},
    {'destination':'bot-name'},{'destination':'C'+'d'*32},{'port':True},{'port':443},{'port':65536},
    {'host':'0.0.0.0'},{'tls_verify':False},{'standalone_sender':True}])
def test_private_line_profile_rejects_ambiguous_credentials_identity_and_listener_options_without_sdk(change):
    value=values();value.update(change)
    with pytest.raises(ValueError):credentials(value)


def test_private_line_profile_requires_exact_fields_and_returns_its_own_copy():
    value=values();canonical=credentials(value)
    assert canonical==value and canonical is not value
    del value['channel_secret']
    with pytest.raises(ValueError):credentials(value)


@pytest.mark.parametrize('context',[None,{}, {'parent':'/tmp'},
    {'parent':'/tmp','connector':'line','policy':None,'inbox':None,'plugin':'unknown'}])
def test_common_factory_refuses_line_without_exact_private_context_before_optional_imports(context):
    from haos.gateway_runtime import build_adapter
    with pytest.raises(ValueError):build_adapter('line',{},line_context=context)
