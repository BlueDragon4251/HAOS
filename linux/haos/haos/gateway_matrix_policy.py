"""Exact Matrix device grants use the independent HAOS policy/mission engine."""
import base64

from .gateway import GatewayPolicy,SUPPORTED,digest


def opaque(value,prefix=None):
    return (isinstance(value,str) and 1<=len(value.encode())<=255
        and not any(ord(c)<32 or ord(c)==127 for c in value)
        and (prefix is None or value.startswith(prefix)))


def public_key(value):
    if not isinstance(value,str) or not 1<=len(value)<=44:return False
    try:data=base64.b64decode(value+'='*((-len(value))%4),validate=True)
    except (ValueError,TypeError):return False
    return len(data)==32 and base64.b64encode(data).decode().rstrip('=')==value


def validate_binding(binding):
    if (not opaque(binding['sender'],'@') or ':' not in binding['sender']
            or not opaque(binding['chat'],'!') or binding['scope']!=''
            or binding['thread'] and not opaque(binding['thread'],'$')):
        raise ValueError('Matrix requires exact user, room and optional root-event IDs within its connector identity')
    if type(binding.get('allow_plaintext')) is not bool or type(binding.get('require_mention')) is not bool:
        raise ValueError('Matrix grants require explicit encryption and mention policies')
    devices=binding.get('matrix_devices')
    if not isinstance(devices,list) or len(devices)>16 or not devices and not binding['allow_plaintext']:
        raise ValueError('Matrix encrypted grants require explicitly approved device fingerprints')
    identities=set()
    for device in devices:
        if (not isinstance(device,dict) or set(device)!={'device_id','ed25519','curve25519'}
                or not opaque(device['device_id']) or device['device_id']=='*'
                or not public_key(device['ed25519']) or not public_key(device['curve25519'])
                or device['device_id'] in identities):
            raise ValueError('Matrix device approval requires one exact device ID and both canonical public keys')
        identities.add(device['device_id'])


class PreparedMatrixPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'matrix'})


def snapshot(policy,connector):
    if connector not in policy.connectors or policy.connectors[connector]['platform']!='matrix':
        raise PermissionError('Matrix capture requires its exact prepared connector')
    return {'connector':connector,'binding_digests':[digest(binding) for binding in policy.bindings.values()
        if binding['connector']==connector]}


def authorize_original(policy,connector,envelope,original_ms,authority,crypto):
    import time
    binding=policy.authorize(connector,envelope)
    if (not isinstance(authority,dict) or authority.get('connector')!=connector
            or not isinstance(authority.get('binding_digests'),list)
            or digest(binding) not in authority['binding_digests']):
        raise PermissionError('Matrix original belongs to another owner grant generation')
    if (type(original_ms) is not int or original_ms<=0 or original_ms>time.time()*1000+300000
            or type(binding.get('since')) is not int or not binding.get('generation')
            or original_ms<=binding['since']):
        raise PermissionError('Matrix original predates its explicit owner grant')
    if crypto is None:
        if not binding['allow_plaintext']:raise PermissionError('Matrix grant requires encrypted verified-device input')
    else:
        if (crypto.get('sender')!=envelope['sender'] or crypto.get('room')!=envelope['chat']
                or crypto.get('event_id')!=envelope['message_id'] or not any(
                    device['device_id']==crypto.get('device_id') and device['ed25519']==crypto.get('ed25519')
                    and device['curve25519']==crypto.get('curve25519') for device in binding['matrix_devices'])):
            raise PermissionError('Matrix encrypted source does not match an owner-approved device')
    return binding
