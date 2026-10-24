"""Conservative translation of reviewed adapter receipts to durable obligations."""
import math


def delivery_result(receipt, redactor=None):
    from .redaction import Redactor
    redactor = redactor or Redactor()
    raw = receipt.raw_response if isinstance(receipt.raw_response, dict) else {}
    if raw.get('partial_overflow'):
        return {'status': 'uncertain'}
    if receipt.success is True:
        identity = receipt.message_id
        if isinstance(identity, (str, int)) and not isinstance(identity, bool):
            identity = str(identity)
            if (1 <= len(identity) <= 256 and not any(ord(char) < 32 for char in identity)
                    and redactor.text(identity) == identity):
                return {'status': 'delivered', 'message_id': identity}
        return {'status': 'uncertain'}
    known_refusal = raw.get('haos_delivery') == 'refused'
    known_no_dispatch = raw.get('haos_delivery') == 'not-dispatched'
    if (known_refusal and receipt.error_kind == 'rate_limited') or (known_no_dispatch and receipt.retryable is True):
        delay = receipt.retry_after
        if (not isinstance(delay, (int, float)) or isinstance(delay, bool)
                or isinstance(delay, float) and not math.isfinite(delay)):
            delay = 5
        return {'status': 'retry', 'retry_after': min(86400, max(1, delay))}
    if known_refusal and receipt.error_kind in {'forbidden', 'not_found', 'bad_format', 'too_long'}:
        return {'status': 'failed'}
    # retryable alone says nothing about whether a remote side effect happened.
    return {'status': 'uncertain'}
