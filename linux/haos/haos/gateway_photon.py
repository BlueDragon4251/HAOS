"""Prepared Photon identity and grants; public activation awaits full integration."""
import re

from .gateway import CAPABILITIES, GatewayPolicy, SUPPORTED, digest

PHONE = re.compile(r'\+[1-9][0-9]{6,14}\Z')
OPAQUE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
GUID = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z')


def peer(value):
    # Spectrum uses the actual Apple address as sender.id. Never infer it
    # from a missing sender, a display label, a phone alias or a chat GUID.
    if not isinstance(value, str) or not (PHONE.fullmatch(value) or
            len(value) <= 254 and re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}', value)):
        raise ValueError('exact Photon E.164 or Apple email address required')
    return value


def chat(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('exact native Photon chat GUID required')
    if value.startswith('any;-;'):
        peer(value[6:])
    elif not re.fullmatch(r'(?:any|iMessage);\+;[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('exact native Photon DM or group GUID required')
    return value


def message_id(value):
    if not isinstance(value, str) or not GUID.fullmatch(value):
        raise ValueError('exact native Photon message GUID required')
    return value


def credentials(value):
    fields = {'project_id', 'project_secret', 'phone', 'services'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('dedicated Photon project, private secret, SDK phone mode and explicit services required')
    if not isinstance(value['project_id'], str) or not OPAQUE.fullmatch(value['project_id']):
        raise ValueError('exact Photon project ID required')
    secret = value['project_secret']
    if not isinstance(secret, str) or not 16 <= len(secret) <= 4096 or any(not 33 <= ord(c) <= 126 for c in secret):
        raise ValueError('bounded private Photon project secret required')
    if value['phone'] != 'shared' and (not isinstance(value['phone'], str) or not PHONE.fullmatch(value['phone'])):
        raise ValueError('explicit shared SDK mode or exact dedicated E.164 line required')
    services = value['services']
    if (not isinstance(services, list) or not services or any(not isinstance(s, str) or s not in {'iMessage', 'SMS', 'RCS'} for s in services)
            or len(set(services)) != len(services)):
        raise ValueError('explicit native iMessage/SMS/RCS service approvals required')
    return {**value, 'services': list(services)}


def scope(value):
    # In shared mode the pinned SDK exposes no receiving number. Do not invent
    # line-specific authority from the number printed during dashboard setup.
    return 'photon:' + digest([value['project_id'], value['phone']])


def wire_mime(attachment):
    """Exact immutable-source CAF alias used by the pinned iMessage mapper."""
    mime = attachment['mimeType']
    uti = attachment.get('uti')
    if mime.lower() == 'application/octet-stream' and (
            isinstance(uti, str) and uti.lower() == 'com.apple.coreaudio-format'
            or attachment['fileName'].lower().endswith('.caf')):
        return 'audio/x-caf'
    return mime


def validate_binding(binding):
    peer(binding.get('sender')); chat(binding.get('chat'))
    if binding.get('thread') != '':
        message_id(binding.get('thread'))
    if (not isinstance(binding.get('scope'), str) or not re.fullmatch(r'photon:[a-f0-9]{64}', binding['scope'])
            or not isinstance(binding.get('generation'), str) or not re.fullmatch(r'[a-f0-9]{64}', binding['generation'])
            or type(binding.get('since')) is not int or not 0 < binding['since'] < 2**53):
        raise ValueError('exact project/phone scope and fresh timed Photon owner grant required')
    caps = binding.get('capabilities')
    if not isinstance(caps, list) or not caps or any(not isinstance(c, str) or c not in CAPABILITIES for c in caps) or len(set(caps)) != len(caps):
        raise ValueError('explicit Photon mission capabilities required')
    for flag in ['all_threads', 'allow_media', 'allow_voice', 'allow_video', 'allow_outbound_media']:
        if flag in binding and type(binding[flag]) is not bool:
            raise ValueError('separate boolean Photon media/thread approvals required')
        if binding.get(flag) is True and flag != 'all_threads' and ('read' if flag == 'allow_outbound_media' else 'create') not in caps:
            raise ValueError('Photon media approval requires corresponding mission capability')
    if binding.get('all_threads') is True and binding['thread']:
        raise ValueError('one exact Photon thread or explicit whole-chat threads required')


class PreparedPhotonPolicy(GatewayPolicy):
    platforms = frozenset(SUPPORTED | {'photon'})

    def __init__(self, value):
        super().__init__(value)
        routes = {}
        for row in self.bindings.values():
            if self.connectors[row['connector']]['platform'] != 'photon':
                continue
            validate_binding(row)
            key = tuple(row[k] for k in ['connector', 'sender', 'chat', 'scope'])
            previous = routes.setdefault(key, [])
            if previous and (row.get('all_threads') is True or any(r.get('all_threads') is True for r in previous)):
                raise ValueError('overlapping Photon whole-chat thread approval')
            previous.append(row)
        self._photon_policy_fingerprint = digest([self.publication, self.connectors, self.bindings])

    def authorize(self, connector, envelope):
        checked_policy(self)
        try:
            return super().authorize(connector, envelope)
        except PermissionError:
            # Reuse every normal envelope/connector/identity validation first.
            # Only an exact project/sender/chat whole-thread grant adds a route.
            if not isinstance(envelope, dict) or envelope.get('platform') != 'photon':
                raise
            for row in self.bindings.values():
                if row['connector'] == connector and row.get('all_threads') is True and all(
                        row[key] == envelope.get(key) for key in ['sender', 'chat', 'scope']):
                    if (self.connectors.get(connector, {}).get('platform') != 'photon' or envelope.get('is_bot') is not False
                            or set(envelope) != {'platform', 'sender', 'chat', 'scope', 'thread', 'message_id', 'is_bot', 'text'}):
                        raise PermissionError('Photon source denied')
                    message_id(envelope['message_id'])
                    if envelope['thread']:
                        message_id(envelope['thread'])
                    return row
            raise


def checked_policy(policy):
    if (not isinstance(policy, PreparedPhotonPolicy) or getattr(policy, '_photon_policy_fingerprint', None)
            != digest([policy.publication, policy.connectors, policy.bindings])):
        raise PermissionError('unchanged independently validated Photon policy required')
    return policy
