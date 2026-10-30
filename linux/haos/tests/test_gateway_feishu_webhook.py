"""Malformed authentication must fail before any optional SDK import or I/O."""
import pytest
from haos.gateway_feishu_webhook import headers
from haos.gateway_feishu_admission import Refused
from haos.gateway_feishu_listener import Limits


def valid():return {'X-Lark-Request-Timestamp':'1793275200','X-Lark-Request-Nonce':'fixture_nonce_1','X-Lark-Signature':'a'*64}


def test_exact_signed_header_fields_are_normalized_without_losing_duplicate_detection():
    assert headers(valid())=={key.lower():item for key,item in valid().items()}
    with pytest.raises(Refused):headers([*valid().items(),('x-lark-signature','a'*64)])


@pytest.mark.parametrize('change',[{'X-Lark-Request-Timestamp':True},{'X-Lark-Request-Timestamp':'01793275200'},
    {'X-Lark-Request-Timestamp':'1e9'},{'X-Lark-Request-Timestamp':'-1'},
    {'X-Lark-Request-Nonce':'short'},{'X-Lark-Request-Nonce':'nonce\r\ninjected'},
    {'X-Lark-Signature':'a'*63},{'X-Lark-Signature':'A'*64},{'X-Lark-Signature':None}])
def test_ambiguous_signature_time_nonce_or_header_value_refused(change):
    with pytest.raises(Refused):headers({**valid(),**change})


@pytest.mark.parametrize('value',[None,True,['one'],[('one',)],[(True,'value')],[(1,2,3)],{}])
def test_malformed_header_container_is_finite_refusal(value):
    with pytest.raises(Refused):headers(value)


def test_header_enumeration_stops_at_bounded_limit_without_exhausting_attacker_iterator():
    consumed=[]
    def values():
        for number in range(10000):consumed.append(number);yield 'unused-'+str(number),'value'
    with pytest.raises(Refused):headers(values())
    assert len(consumed)==65


def test_listener_limits_bound_active_reads_global_work_and_address_cardinality():
    limits=Limits();assert limits.admit('fixture-source')
    limits.active=8;assert not limits.admit('fixture-source');limits.active=0
    limits.tokens=0;assert not limits.admit('fixture-source');limits.tokens=64
    import time
    limits.addresses={str(number):(16.,time.monotonic()) for number in range(256)}
    assert not limits.admit('untracked-new-source')
    assert len(limits.addresses)==256
