"""Private IPC contracts; actual UID/TLS/worker lifetime has a separate process probe."""
import base64
import hashlib
import pytest
from haos.gateway_dingtalk_ws_process import event,Session
from test_gateway_dingtalk import account


def envelope(raw=b'original bytes'):
    return {'kind':'event','seq':1,'payload_base64':base64.b64encode(raw).decode(),
        'sha256':hashlib.sha256(raw).hexdigest()}


def test_private_event_preserves_exact_original_bytes():
    raw=b'{"source":"original 1"}'
    assert event(envelope(raw),1)==raw


@pytest.mark.parametrize('change',[{'seq':True},{'seq':0},{'seq':2},{'kind':'ready'},
    {'sha256':'0'*64},{'sha256':True},{'payload_base64':'!!!!'},
    {'payload_base64':'Zh=='},{'extra':'unreviewed'},{'payload_base64':None}])
def test_private_event_refuses_replay_ambiguity_mutation_and_noncanonical_bytes(change):
    with pytest.raises((ValueError,TypeError)):event({**envelope(),**change},1)


def test_private_event_refuses_empty_and_oversized_sources():
    for raw in [b'',b'x'*(1024*1024+1)]:
        with pytest.raises(ValueError):event(envelope(raw),1)


def test_private_session_requires_both_independent_parent_callbacks():
    for current,capture in [(None,lambda _:None),(lambda:None,None)]:
        with pytest.raises(PermissionError):Session(account(),'dingtalk',current,capture)


def test_inactive_generation_cannot_admit_events():
    session=Session(account(),'dingtalk',lambda:None,lambda _:None)
    with pytest.raises(PermissionError):session.check()
