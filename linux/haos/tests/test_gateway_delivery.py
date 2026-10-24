from types import SimpleNamespace

import pytest

from haos.gateway_delivery import delivery_result
from haos.redaction import Redactor


def receipt():
    return SimpleNamespace(success=False, message_id=None, raw_response=None, retryable=False,
        retry_after=None, error_kind='unknown')


def test_retryable_does_not_establish_that_the_remote_message_was_not_delivered():
    value = receipt(); value.retryable=True; value.error_kind='transient'
    assert delivery_result(value) == {'status':'uncertain'}
    value.raw_response={'haos_delivery':'not-dispatched'}
    assert delivery_result(value) == {'status':'retry','retry_after':5}
    value.raw_response['partial_overflow']=True
    assert delivery_result(value) == {'status':'uncertain'}


@pytest.mark.parametrize('identity', [None, '', True, 'x'*257, 'line\nfeed', 'fixture-private-gateway-token'])
def test_invalid_or_reflected_private_receipt_never_crosses_into_the_controller(identity):
    value=receipt(); value.success=True; value.message_id=identity
    assert delivery_result(value, Redactor(['fixture-private-gateway-token'])) == {'status':'uncertain'}


@pytest.mark.parametrize('delay,expected', [(float('inf'),5),(float('nan'),5),(True,5),(-3,1),(120,120),(100000,86400),(10**400,86400)])
def test_reviewed_rate_refusal_produces_a_bounded_durable_retry(delay,expected):
    value=receipt(); value.error_kind='rate_limited'; value.retry_after=delay
    assert delivery_result(value) == {'status':'uncertain'}
    value.raw_response={'haos_delivery':'refused'}
    assert delivery_result(value) == {'status':'retry','retry_after':expected}
