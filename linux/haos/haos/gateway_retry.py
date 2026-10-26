"""Bounded gateway Retry-After, without exposing reflected credentials."""
from .provider_retry import retry_seconds
from .redaction import Redactor


def retry_after(value, *, default=5, private_values=(), now=None):
    if type(default) is not int or not 1<=default<=86400:
        raise ValueError('bounded positive default retry delay required')
    if isinstance(value,str) and Redactor(private_values).text(value)!=value:
        return default
    parsed=retry_seconds(value,now=now)
    return max(1,parsed) if parsed is not None else default
