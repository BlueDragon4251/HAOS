from types import SimpleNamespace
import pytest
from haos.provider_retry import retry_seconds, error_retry_seconds


@pytest.mark.parametrize('value,expected', [
    ('17', 17), (' 17 ', 17), ('0', 0), ('9999999999', 86400),
    ('Thu, 01 Jan 1970 00:17:00 GMT', 20), ('Thu, 01 Jan 1970 00:17:00', None),
    ('Thu, 01 Jan 1970 00:00:00 GMT', 0), ('-1', None), ('1.5', None),
    ('NaN', None), ('secret-fixture', None), ('17\r\nSet-Cookie: secret', None),
    ('１７', None), ('9' * 129, None), (None, None), (17, None),
])
def test_public_retry_timing_is_bounded_and_cannot_forward_private_headers(value, expected):
    assert retry_seconds(value, now=1000) == expected


def test_native_sdk_error_shapes_keep_only_public_retry_timing():
    assert error_retry_seconds(SimpleNamespace(response=SimpleNamespace(headers={'retry-after': '17'}))) == 17
    assert error_retry_seconds(SimpleNamespace(response={'ResponseMetadata': {'HTTPHeaders': {'retry-after': '21'}}})) == 21
    assert error_retry_seconds(SimpleNamespace(response={'Error': {'Message': 'private fixture'}})) is None


def test_native_retry_header_cannot_reflect_a_private_credential():
    from haos.redaction import Redactor
    error = SimpleNamespace(response=SimpleNamespace(headers={'Retry-After': '12345678'}))
    assert error_retry_seconds(error, Redactor(['12345678'])) is None
