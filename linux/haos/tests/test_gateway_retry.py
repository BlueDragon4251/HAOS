import pytest

from haos.gateway_retry import retry_after


@pytest.mark.parametrize('value,expected',[
    ('19',19),('0',1),('9999999999',86400),
    ('Thu, 01 Jan 1970 00:17:00 GMT',20),('Thu, 01 Jan 1970 00:00:00 GMT',1),
    ('Thu, 01 Jan 1970 00:17:00',5),('NaN',5),('inf',5),('-1',5),
    ('19\r\nSet-Cookie: private',5),(None,5),('1.5',5),
])
def test_gateway_retry_accepts_both_http_forms_and_rejects_untrusted_headers(value,expected):
    assert retry_after(value,now=1000)==expected


def test_gateway_retry_cannot_publish_reflected_numeric_credentials_as_timing():
    assert retry_after('12345678',private_values=['12345678'])==5
    assert retry_after('12345678',default=60,private_values=['12345678'])==60


@pytest.mark.parametrize('value',[0,-1,86401,True,1.5])
def test_gateway_retry_rejects_unbounded_or_non_integer_default(value):
    with pytest.raises(ValueError):retry_after(None,default=value)
