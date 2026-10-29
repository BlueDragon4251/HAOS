import pytest
from haos.gateway_dingtalk import scope
from haos.gateway_dingtalk_process import response
from test_gateway_dingtalk import account


def exact():return {'app_authenticated':True,'corp_identity_verified':False,'robot_identity_verified':False,
    'account_scope':scope(account()),'message_sent':False}


def test_no_send_result_proves_only_app_authentication_without_falsely_claiming_corporation_or_robot():
    assert response(exact(),account())==exact()
    assert response({'error':'rate-limited'},account())=={'error':'rate-limited'}


@pytest.mark.parametrize('change',[{'app_authenticated':1},{'corp_identity_verified':True},{'robot_identity_verified':True},
    {'message_sent':True},{'account_scope':'dingtalk:'+'a'*64},{'accessToken':'private-fixture-token'}])
def test_ambiguous_extra_secret_or_overstated_owner_account_results_are_refused(change):
    with pytest.raises(ValueError):response({**exact(),**change},account())


@pytest.mark.parametrize('value',[None,{},[],{'error':[]},{'error':'raw SDK error response'},
    {'error':'authentication-refused','private_body':'not admitted'}])
def test_worker_diagnostics_are_closed_finite_and_never_vendor_exception_bodies(value):
    with pytest.raises(ValueError):response(value,account())
