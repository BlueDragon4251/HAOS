"""Private WS discovery admits only branded endpoints, never caller transport options."""
import io
import logging
import pytest
from haos.gateway_feishu_http import Failure
from haos.gateway_feishu_ws_http import Discovery,QuietLogger
from haos.redaction import Redactor
from test_gateway_feishu import account


def endpoint():return 'wss://msg-frontier.feishu.cn/ws/v2?device_id=fixture-device&service_id=1&ticket=private-session-fixture-ticket'


def test_private_session_ticket_is_redacted_without_poisoning_public_routing_ids_or_goal_digits():
    redactor=Redactor();guard=Discovery(account(),lambda:None,redactor)
    assert guard.endpoint(endpoint())==endpoint()
    assert redactor.text(endpoint())!=endpoint()
    assert redactor.text('private-session-fixture-ticket')!='private-session-fixture-ticket'
    assert redactor.text('Mission 1 for fixture-device')=='Mission 1 for fixture-device'


@pytest.mark.parametrize('url',[
    'ws://msg-frontier.feishu.cn/ws/v2?device_id=device&service_id=1',
    'wss://msg-frontier.larksuite.com/ws/v2?device_id=device&service_id=1',
    'wss://feishu.cn.attacker.invalid/ws/v2?device_id=device&service_id=1',
    'wss://notfeishu.cn/ws/v2?device_id=device&service_id=1',
    'wss://user@msg-frontier.feishu.cn/ws/v2?device_id=device&service_id=1',
    'wss://msg-frontier.feishu.cn:444/ws/v2?device_id=device&service_id=1',
    endpoint()+'#fragment',endpoint()+'&service_id=2',endpoint().replace('service_id=1','service_id=01'),
    endpoint().replace('service_id=1','service_id=-1'),endpoint().replace('device_id=fixture-device','device_id='),
    endpoint().replace('/ws/v2','/../private'),endpoint().replace('/ws/v2','/ws/%2e%2e'),
    endpoint()+'&extra=%ZZ',endpoint()+'&extra=%00',None,True,
])
def test_unapproved_brand_userinfo_port_path_fragment_query_or_endpoint_type_refused(url):
    guard=Discovery(account(),lambda:None,Redactor())
    with pytest.raises(Failure):guard.endpoint(url)


def test_socket_options_cannot_disable_tls_route_to_proxy_or_change_authoritative_uri():
    guard=Discovery(account(),lambda:None,Redactor());guard.url=endpoint()
    with pytest.raises(Failure):guard.connect(endpoint())
    with guard.connection_scope():
        for options in [{'ssl':None},{'proxy':'http://other.invalid'},{'max_size':None},{'additional_headers':{'Authorization':'Bearer unapproved'}},
            {'ping_interval':0},{'ping_timeout':True}]:
            with pytest.raises(Failure):guard.connect(endpoint(),**options)
        with pytest.raises(Failure):guard.connect(endpoint()+'&another=route')
        with pytest.raises(Failure):
            with guard.connection_scope():raise AssertionError('nested private connection allowed')


def test_native_diagnostics_never_forward_original_arguments_or_exception_text():
    stream=io.StringIO();logger=logging.Logger('fixture-private-ws',logging.DEBUG);handler=logging.StreamHandler(stream);logger.addHandler(handler)
    private=QuietLogger(logger,{})
    private.info('endpoint %s',endpoint())
    try:raise RuntimeError('private-session-fixture-ticket')
    except RuntimeError:private.exception('private-session-fixture-ticket')
    assert 'private Feishu transport diagnostic' in stream.getvalue()
    assert 'private-session-fixture-ticket' not in stream.getvalue() and 'wss://' not in stream.getvalue()
