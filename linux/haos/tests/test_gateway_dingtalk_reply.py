"""Closed reply protocol guards; real SDK/TLS/UID tests are separate probes."""
from copy import deepcopy
import pytest

from haos.gateway_dingtalk_reply_process import response
from haos.gateway_dingtalk_reply_http import Boundary
from haos.redaction import Redactor


def acceptance():
    return {'state': 'confirmed', 'acceptance_id': 'haos-dingtalk-' + 'a' * 64,
            'remote_message_id': None, 'recipient_read_verified': False}


def test_local_vendor_acceptance_is_explicitly_not_remote_identity_or_read_proof():
    assert response(acceptance()) == acceptance()
    assert response({'state': 'uncertain'}) == {'state': 'uncertain'}


@pytest.mark.parametrize('change', [
    {'acceptance_id': 'sdk-random-uuid'}, {'remote_message_id': 'invented-remote-id'},
    {'recipient_read_verified': True}, {'recipient_read_verified': 0}, {'extra': 'unreviewed'},
    {'state': True}, {'acceptance_id': None}, {'acceptance_id': 'haos-dingtalk-' + 'a' * 65},
])
def test_reply_result_refuses_invented_remote_delivery_evidence(change):
    with pytest.raises(ValueError):
        response({**acceptance(), **change})


@pytest.mark.parametrize('change', [{'retry_after': True}, {'retry_after': -1}, {'retry_after': 86401},
    {'error': 'raw-private-provider-error'}, {'error': None}, {'state': 'confirmed'},
    {'extra': 'unreviewed'}, {'error': 'authentication-refused', 'retry_after': 60}])
def test_refusal_cannot_smuggle_raw_errors_unbounded_deadlines_or_new_protocol_fields(change):
    value = {'state': 'rejected', 'error': 'rate-limited', 'retry_after': 60}
    with pytest.raises(ValueError):
        response({**value, **change})


def target():
    return {'url': 'https://oapi.dingtalk.com/robot/sendBySession?session=private-reply-test-capability',
            'payload': {'msgtype': 'markdown', 'markdown': {'title': 'Hermes', 'text': 'Approved reply.'}},
            'intent_sha256': 'a' * 64}


@pytest.mark.parametrize('url', ['https://other.invalid/robot/sendBySession?session=private-reply-test-capability',
    'http://oapi.dingtalk.com/robot/sendBySession?session=private-reply-test-capability',
    'https://oapi.dingtalk.com/robot/sendBySession?session=short',
    'https://oapi.dingtalk.com/robot/sendBySession?session=private-reply-test-capability&extra=1'])
def test_reply_boundary_has_no_arbitrary_or_unreviewed_bearer_destination(url):
    with pytest.raises(PermissionError):
        Boundary({**target(), 'url': url}, 2000000000000, lambda: None, Redactor())


def test_reply_payload_is_immutable_and_private_capability_cannot_reflect_into_output():
    exact = target(); boundary = Boundary(exact, 2000000000000, lambda: None, Redactor())
    exact['payload']['markdown']['text'] = 'Changed after approval.'
    assert boundary.target['payload']['markdown']['text'] == 'Approved reply.'
    leaking = target(); leaking['payload']['markdown']['text'] = 'private-reply-test-capability'
    with pytest.raises(PermissionError):
        Boundary(leaking, 2000000000000, lambda: None, Redactor())
