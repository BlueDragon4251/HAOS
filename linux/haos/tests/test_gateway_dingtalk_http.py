import json
import pytest
from haos.gateway_dingtalk_http import Boundary,Requests,endpoint,Failure,QuietLogger
from haos.redaction import Redactor
from test_gateway_dingtalk import account


@pytest.mark.parametrize('url',['ws://wss-open-connection.dingtalk.com/connect',
    'wss://dingtalk.com.attacker.invalid/connect','wss://wss-open-connection.dingtalk.com:444/connect',
    'wss://user:password@wss-open-connection.dingtalk.com/connect','wss://wss-open-connection.dingtalk.com/other',
    'wss://wss-open-connection.dingtalk.com/connect?ticket=unreviewed','wss://wss-open-connection.dingtalk.com/connect#fragment',
    'wss://wss-open-connection.dingtalk.com/connect\n',[],None])
def test_fixed_vendor_wss_discovery_refuses_unreviewed_transports_hosts_options_and_types(url):
    with pytest.raises(Failure):endpoint(url)


def test_private_SDK_HTTP_facade_cannot_be_used_without_a_reviewed_operation_or_with_extra_transport_options():
    with pytest.raises(PermissionError):Requests.post('https://api.dingtalk.com/v1.0/oauth2/accessToken',data=b'{}')
    with pytest.raises(PermissionError):Requests.post('https://api.dingtalk.com/v1.0/oauth2/accessToken',verify=False)


def test_closed_boundary_requires_current_private_identity_and_registers_escaped_secret_spellings():
    value={**account(),'client_secret':'private-secret-quote"slash\\fixture'};redactor=Redactor()
    boundary=Boundary(value,lambda:None,redactor)
    for spelling in [value['client_secret'],json.dumps(value['client_secret'])[1:-1],repr(value['client_secret'])[1:-1]]:
        assert redactor.text(spelling)!=spelling
    with pytest.raises(PermissionError):Boundary(value,None,redactor)
    with pytest.raises(PermissionError):Boundary(value,lambda:None,object())
    assert QuietLogger().error('private literal %s',value['client_secret']) is None
    boundary.close()
