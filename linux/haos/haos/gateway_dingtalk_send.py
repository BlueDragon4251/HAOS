"""Prepared exact DingTalk native reply intents; no ambient outbound authority."""
import base64
from copy import deepcopy
import hashlib
import re
import time

from .gateway import digest
from .gateway_dingtalk import scope, identity
from .gateway_dingtalk_admission import approve, normalize, parse, session_webhook, milliseconds, MAX_EVENT
from .redaction import Redactor

MAX_TEXT = 4000


class ExpiredSession(PermissionError):
    def __init__(self):
        super().__init__('original DingTalk session reply route expired')


def specification(value, policy, connector, item, redactor, *, require_fresh=True):
    fields = {'binding_id', 'binding_digest', 'delivery_id', 'attempt', 'source_id',
              'source_sha256', 'source_base64', 'body'}
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError('exact private DingTalk reply intent required')
    if not isinstance(redactor, Redactor):
        raise PermissionError('private DingTalk credential redaction required')
    for key in ('binding_digest', 'delivery_id', 'source_sha256'):
        if not isinstance(item[key], str) or not re.fullmatch('[0-9a-f]{64}', item[key]):
            raise ValueError('opaque immutable DingTalk reply proof required')
    identity(item['source_id'])
    if type(item['attempt']) is not int or not 1 <= item['attempt'] <= 5:
        raise ValueError('bounded DingTalk outbox attempt required')
    if not isinstance(item['source_base64'], str) or not 1 <= len(item['source_base64']) <= 4 * ((MAX_EVENT + 2) // 3):
        raise ValueError('bounded private original DingTalk reply source required')
    try:
        raw = base64.b64decode(item['source_base64'], validate=True)
    except (ValueError, UnicodeError):
        raise ValueError('canonical private DingTalk source encoding required') from None
    if (not 1 <= len(raw) <= MAX_EVENT or base64.b64encode(raw).decode() != item['source_base64']
            or hashlib.sha256(raw).hexdigest() != item['source_sha256']):
        raise ValueError('DingTalk reply source bytes changed')
    binding = policy.current_binding({'binding_id': item['binding_id'], 'binding_digest': item['binding_digest']})
    if (policy.connectors.get(connector, {}).get('platform') != 'dingtalk' or binding['connector'] != connector
            or binding['scope'] != scope(value) or binding['sender'] == value['robot_code']
            or 'read' not in binding['capabilities']):
        raise PermissionError('exact current DingTalk reply/read grant required')
    approval = approve(policy, connector, value, raw)
    projection = normalize(policy, connector, value, raw, approval, redactor)
    if (approval['binding_id'] != item['binding_id'] or approval['binding_digest'] != item['binding_digest']
            or projection['envelope']['message_id'] != item['source_id']):
        raise PermissionError('DingTalk reply differs from independently approved original')
    data = parse(raw); url, _token = session_webhook(data.get('sessionWebhook'))
    expiry = milliseconds(data.get('sessionWebhookExpiredTime'))
    if type(require_fresh) is not bool:
        raise ValueError('explicit private reply freshness decision required')
    # The private journal may compare an already-confirmed intent after expiry.
    # Worker admission defaults to fresh; HTTP Boundary always enforces expiry
    # independently immediately before writing, regardless of this comparison.
    if require_fresh and expiry <= time.time() * 1000:
        raise ExpiredSession()
    body = item['body']
    if (not isinstance(body, str) or not 1 <= len(body.strip()) <= MAX_TEXT or len(body) > MAX_TEXT
            or len(body.encode()) > 4 * MAX_TEXT or '\0' in body):
        raise ValueError('one bounded native DingTalk reply chunk required')
    if redactor.text(body) != body:
        raise PermissionError('private DingTalk credential reflection refused')
    result = deepcopy(item)
    result.update(chat_id=binding['chat'], thread_id=binding['thread'], session_webhook=url,
                  session_expires_at=expiry)
    return result


def wire_target(adapter, blueprint):
    from plugins.platforms.dingtalk.adapter import DingTalkAdapter
    if not isinstance(adapter, DingTalkAdapter) or adapter._card_template_id or adapter._card_sdk:
        raise PermissionError('exact native session reply codec required')
    body = blueprint['body']
    if not isinstance(body, str) or not 1 <= len(body) <= MAX_TEXT or len(body) > adapter.MAX_MESSAGE_LENGTH:
        raise ValueError('one immutable native DingTalk text chunk required')
    text = DingTalkAdapter._normalize_markdown(body)
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 128000:
        raise ValueError('bounded native DingTalk markdown required')
    return {'url': session_webhook(blueprint['session_webhook'])[0], 'payload': {
        'msgtype': 'markdown', 'markdown': {'title': 'Hermes', 'text': text}},
        'intent_sha256': digest([blueprint['delivery_id'], blueprint['binding_digest'],
                                  blueprint['source_sha256'], blueprint['source_id'], body])}


async def invoke_native(adapter, blueprint, transport, current):
    """Private worker only: actual native formatter/sender, one closed HTTP witness."""
    from types import MethodType
    from plugins.platforms.dingtalk import adapter as native
    from .gateway_dingtalk_reply_http import Boundary
    from .gateway_dingtalk_http import QuietLogger
    current()
    if not isinstance(transport, Boundary) or wire_target(adapter, blueprint) != transport.target:
        raise PermissionError('exact independently prepared native DingTalk reply required')
    previous_http = adapter._http_client; previous_reaction = adapter._fire_done_reaction
    previous_logger = native.logger
    def no_reaction(_self, chat_id):
        current()
        if chat_id != blueprint['chat_id']:
            raise PermissionError('native DingTalk reaction source changed')
        # Native sender's final-reply callback has no reaction permission.
    adapter._http_client = transport
    adapter._fire_done_reaction = MethodType(no_reaction, adapter); native.logger = QuietLogger()
    try:
        result = await native.DingTalkAdapter.send(adapter, blueprint['chat_id'], blueprint['body'],
            reply_to=blueprint['source_id'], metadata={'session_webhook': blueprint['session_webhook']})
        current()
    finally:
        adapter._http_client = previous_http; adapter._fire_done_reaction = previous_reaction
        native.logger = previous_logger
    if transport.state == 'confirmed' and result.success is True:
        if not isinstance(transport.acceptance_id, str) or not re.fullmatch('haos-dingtalk-[0-9a-f]{64}', transport.acceptance_id):
            raise PermissionError('exact local DingTalk vendor-acceptance proof required')
        return {'state': 'confirmed', 'acceptance_id': transport.acceptance_id,
                'remote_message_id': None, 'recipient_read_verified': False}
    if transport.state == 'rejected':
        if transport.error not in {'authentication-refused', 'rate-limited', 'native-refused', 'expired-session'}:
            raise PermissionError('finite native DingTalk refusal required')
        return {'state': 'rejected', 'error': transport.error, 'retry_after': transport.retry_after}
    if transport.write_started:
        return {'state': 'uncertain'}
    return {'state': 'rejected', 'error': 'authority-or-protocol-refused', 'retry_after': 0}
