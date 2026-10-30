"""Bounded public retry timing; never relay arbitrary provider error headers."""
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
import math
import re
import time


def retry_seconds(value, *, now=None):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        return None
    value = value.strip()
    if re.fullmatch(r'[0-9]{1,10}', value):
        return min(86400, int(value))
    try:
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            return None
        delay = math.ceil(stamp.timestamp() - (time.time() if now is None else now))
        return min(86400, max(0, delay))
    except (TypeError, ValueError, OverflowError):
        return None


def error_retry_seconds(error, redactor=None):
    response = getattr(error, 'response', None)
    if isinstance(response, dict):
        headers = response.get('ResponseMetadata', {}).get('HTTPHeaders', {})
    else:
        headers = getattr(response, 'headers', None) or getattr(error, 'headers', None) or {}
    if not isinstance(headers, Mapping):
        return None
    value = headers.get('retry-after') or headers.get('Retry-After')
    if redactor is not None and isinstance(value, str) and redactor.text(value) != value:
        return None
    return retry_seconds(value)
