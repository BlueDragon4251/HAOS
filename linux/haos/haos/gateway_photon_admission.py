"""Independent Photon authority before actual SDK mapping or attachment RPCs."""
from datetime import datetime
import hashlib
import re
import time

from .gateway import digest
from .gateway_dingtalk_admission import parse, Refused as JSONRefused
from .gateway_photon import checked_policy, credentials, scope, peer, chat, message_id, validate_binding, wire_mime

MAX_ATTACHMENT = 8 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024


class Refused(PermissionError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Photon source or content is not approved')


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z', value):
        raise ValueError('exact native Photon UTC timestamp required')
    return datetime.fromisoformat(value[:-1] + '+00:00').timestamp() * 1000


def approve(policy, connector, value, raw):
    policy = checked_policy(policy); value = credentials(value)
    if policy.connectors.get(connector, {}).get('platform') != 'photon':
        raise Refused('unapproved-route')
    try:
        data = parse(raw)
        if set(data) != {'event', 'phone', 'cursor'} or data['phone'] != value['phone']:
            raise Refused('wrong-account')
        event = data['event']
        if not isinstance(event, dict) or event.get('type') != 'message.received':
            raise Refused('unsupported-event')
        seq = event.get('sequence')
        if type(seq) is not int or not 1 <= seq < 2**53 or data['cursor'] != str(seq):
            raise Refused('invalid-cursor')
        msg = event['message']
        if not isinstance(msg, dict) or msg.get('isFromMe') is not False or msg.get('isAutoReply', False) is not False:
            raise Refused('self-or-automated')
        for flag in ['isCorrupt', 'isServiceMessage', 'isSpam', 'isSystemMessage']:
            if msg.get(flag, False) is not False:
                raise Refused('unsupported-event')
        sender = msg.get('sender')
        if not isinstance(sender, dict) or sender.get('service') not in value['services']:
            raise Refused('unsupported-service')
        sender_id = peer(sender.get('address'))
        if sender_id == value['phone']:
            raise Refused('self-or-automated')
        guids = msg.get('chatGuids')
        if not isinstance(guids, list) or len(guids) != 1:
            raise Refused('ambiguous-chat')
        chat_id = chat(guids[0])
        if event.get('chatGuid', chat_id) != chat_id:
            raise Refused('ambiguous-chat')
        if chat_id.startswith('any;-;') and chat_id[6:] != sender_id:
            raise Refused('ambiguous-sender')
        mid = message_id(msg.get('guid'))
        origin = msg.get('threadOriginatorGuid'); target = msg.get('replyTargetGuid')
        if origin is not None:
            message_id(origin)
        if target is not None:
            message_id(target)
        thread = origin or target or ''
        envelope = {'platform': 'photon', 'sender': sender_id, 'chat': chat_id, 'scope': scope(value),
            'thread': thread, 'message_id': mid, 'is_bot': False, 'text': ''}
        try:
            binding = policy.authorize(connector, envelope)
        except PermissionError:
            raise Refused('unapproved-route') from None
        validate_binding(binding)
        created = timestamp(msg.get('dateCreated')); occurred = timestamp(event.get('occurredAt'))
        if not binding['since'] < min(created, occurred) <= max(created, occurred) <= time.time() * 1000 + 300000:
            raise Refused('pre-grant')
        content = msg.get('content')
        if not isinstance(content, dict) or not isinstance(content.get('text'), str) or len(content['text'].encode()) > 65536:
            raise Refused('unsupported-content')
        attachments = content.get('attachments')
        if not isinstance(attachments, list) or len(attachments) > 4:
            raise Refused('unsupported-content')
        total = 0; ids = set()
        for attachment in attachments:
            if not isinstance(attachment, dict):
                raise Refused('unsupported-content')
            aid = message_id(attachment.get('guid'))
            if aid in ids:
                raise Refused('ambiguous-attachment')
            ids.add(aid)
            size = attachment.get('totalBytes'); mime = attachment.get('mimeType'); name = attachment.get('fileName')
            if (type(size) is not int or not 0 < size <= MAX_ATTACHMENT or not isinstance(mime, str)
                    or not re.fullmatch(r'[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+', mime)
                    or not isinstance(name, str) or not 1 <= len(name.encode()) <= 255
                    or any(ord(c) < 32 for c in name) or '/' in name or '\\' in name
                    or attachment.get('uti') is not None and (not isinstance(attachment['uti'], str) or len(attachment['uti']) > 256)):
                raise Refused('unsupported-content')
            total += size
            if total > MAX_TOTAL:
                raise Refused('unsupported-content')
            if binding.get('allow_media') is not True:
                raise Refused('unapproved-media')
            if wire_mime(attachment).startswith('audio/') and binding.get('allow_voice') is not True:
                raise Refused('unapproved-voice')
            if mime.startswith('video/') and binding.get('allow_video') is not True:
                raise Refused('unapproved-video')
            # The pinned native mapper eagerly parses vCards. Until its bounded
            # binary-preserving path is connected, never download one implicitly.
            if mime in {'text/vcard', 'text/x-vcard', 'text/directory', 'application/vcard', 'application/x-vcard'} or name.lower().endswith('.vcf'):
                raise Refused('unsupported-contact')
        if not content['text'].replace('\ufffc', '').strip() and not attachments:
            raise Refused('unsupported-content')
        if 'create' not in binding['capabilities'] and attachments:
            raise Refused('unapproved-media')
    except Refused:
        raise
    except (JSONRefused, ValueError, KeyError, TypeError, OverflowError):
        raise Refused('unsupported-content') from None
    policy.current_binding({'binding_id': binding['id'], 'binding_digest': digest(binding)})
    return {'envelope': envelope, 'binding_id': binding['id'], 'binding_digest': digest(binding),
        'credential_scope': digest([connector, value]), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
        'received_at': occurred / 1000, 'created_at': created / 1000, 'native_cursor': data['cursor'],
        'attachment_ids': sorted(ids), 'attachment_bytes': total}
