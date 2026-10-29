"""No-send result contracts; identity and subprocess lifetime use real-UID probes."""
import pytest
from haos.gateway_feishu import scope
from haos.gateway_feishu_process import response
from test_gateway_feishu import account


def result():
    value=account()
    return {'bot_identity_verified':True,'tenant_identity_verified':False,
        'bot_open_id':value['bot_open_id'],'account_scope':scope(value),'message_sent':False}


def test_exact_private_account_result_never_claims_tenant_or_delivery():
    assert response(result(),account())==result()
    assert response({'error':'rate-limited'},account())=={'error':'rate-limited'}


@pytest.mark.parametrize('change',[{'tenant_identity_verified':True},{'message_sent':True},
    {'bot_identity_verified':1},{'bot_open_id':'ou_'+'f'*32},{'account_scope':'another-account'},
    {'token':'must-not-cross-boundary'},{'error':'raw SDK response with credentials'},
])
def test_private_account_result_refuses_false_acceptance_and_extra_credentials(change):
    with pytest.raises(ValueError):response({**result(),**change},account())


@pytest.mark.parametrize('value',[None,{},[],{'error':True},{'error':'unbounded-diagnostic'}])
def test_private_process_requires_finite_bounded_response(value):
    with pytest.raises(ValueError):response(value,account())
