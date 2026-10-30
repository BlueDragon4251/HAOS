"""Closed credential-free Owner handoff for Photon status and retained sources."""
from pathlib import Path
import math
import stat

from .gateway import digest
from .gateway_photon_recovery import HEX, NAME, profile_name

ACTIONS = frozenset({'status', 'profiles', 'sources', 'purge-source'})
ERRORS = frozenset({'authority-refused', 'storage-unavailable', 'runtime-unavailable'})


def policy():
    from .gateway_photon import PreparedPhotonPolicy
    from .gateway_publication import pending
    from .sandbox import trusted_json
    config = Path('/etc/haos'); own = config.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid != 0 or own.st_mode & 0o022 or pending(config):
        raise PermissionError('matched Root Photon policy publication required')
    try: raw = trusted_json(config / 'gateways.json')
    except FileNotFoundError: return None, digest({'gateways': 'absent', 'version': 1})
    return PreparedPhotonPolicy(raw), digest(raw)


def command():
    root = Path('/usr/lib/haos'); python = root / 'hermes/.venv/bin/python'
    for path in [root, root / 'haos', root / 'hermes', root / 'hermes/.venv', python.parent]:
        own = path.lstat()
        if not stat.S_ISDIR(own.st_mode) or own.st_uid != 0 or own.st_mode & 0o022:
            raise PermissionError('fixed Root-owned private Photon Owner runtime required')
    own = python.resolve(strict=True).lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid != 0 or own.st_mode & 0o022:
        raise PermissionError('fixed Root-owned Photon interpreter required')
    worker = root / 'haos/photon_owner_worker.py'; own = worker.lstat()
    if worker.resolve() != worker or not stat.S_ISREG(own.st_mode) or own.st_uid != 0 or own.st_mode & 0o022 or own.st_nlink != 1:
        raise PermissionError('fixed immutable Photon Owner worker required')
    return [str(python), '-E', '-s', '-m', 'haos.photon_owner_worker']


def params(action, value, owner_uid):
    if action not in ACTIONS or not isinstance(value, dict): raise ValueError('closed Photon Owner action required')
    if action == 'status':
        from .gateway_photon_status import selector
        return selector(value)
    if action == 'profiles':
        if value: raise ValueError('profile inventory takes no selector')
    elif action == 'sources':
        if set(value) != {'profile'}: raise ValueError('one retained Photon profile required')
        profile_name(value['profile'])
    else:
        if (set(value) != {'profile', 'id', 'snapshot_sha256', 'owner_uid', 'note_sha256', 'confirmed'}
                or value['confirmed'] is not True or type(value['owner_uid']) is not int or value['owner_uid'] != owner_uid
                or any(not isinstance(value[key], str) or not HEX.fullmatch(value[key]) for key in ['id', 'snapshot_sha256', 'note_sha256'])):
            raise PermissionError('closed inspected Photon Owner disposal required')
        profile_name(value['profile'])
    return dict(value)


def response(value, action, request):
    if action not in ACTIONS or not isinstance(value, dict): raise ValueError('closed Photon Owner response required')
    if set(value) == {'error'}:
        if not isinstance(value['error'], str) or value['error'] not in ERRORS: raise ValueError('finite Photon Owner diagnostic required')
        return value
    if action == 'status':
        if set(value) != {'result', 'active_authorization_returned'} or value['active_authorization_returned'] is not False:
            raise ValueError('Photon status cannot return active authorization')
        from .gateway_photon_status import checked
        checked(value['result'], request); return value
    if action == 'profiles':
        if (set(value) != {'profiles', 'history_truncated', 'network_requested', 'private_bytes_returned'}
                or not isinstance(value['profiles'], list) or len(value['profiles']) > 128
                or any(not isinstance(name, str) for name in value['profiles']) or len(value['profiles']) != len(set(value['profiles']))
                or type(value['history_truncated']) is not bool or value['network_requested'] is not False or value['private_bytes_returned'] is not False):
            raise ValueError('bounded retained Photon profile inventory required')
        for name in value['profiles']: profile_name(name)
    elif action == 'sources':
        if (set(value) != {'profile', 'sources', 'history_truncated', 'network_requested', 'private_bytes_returned'}
                or value['profile'] != request['profile'] or not isinstance(value['sources'], list) or len(value['sources']) > 128
                or type(value['history_truncated']) is not bool or value['network_requested'] is not False or value['private_bytes_returned'] is not False):
            raise ValueError('bounded payload-free Photon original inventory required')
        from .gateway_photon import message_id
        for row in value['sources']:
            fields = {'id', 'connector', 'message_id', 'binding_id', 'binding_digest', 'created_at', 'admitted_receipt', 'profile',
                'source_sha256', 'normalized_sha256', 'proof_sha256', 'actual_sha256', 'stored_bytes', 'current_grant', 'purge_allowed',
                'state', 'authentication_reverified', 'private_bytes_returned', 'snapshot_sha256'}
            if (not isinstance(row, dict) or set(row) != fields or row['profile'] != value['profile']
                    or any(not isinstance(row[key], str) or not HEX.fullmatch(row[key]) for key in ['id', 'binding_digest', 'source_sha256', 'proof_sha256', 'snapshot_sha256'])
                    or any(not isinstance(row[key], str) or not NAME.fullmatch(row[key]) for key in ['connector', 'binding_id'])
                    or any(row[key] != '' and (not isinstance(row[key], str) or not HEX.fullmatch(row[key])) for key in ['normalized_sha256', 'admitted_receipt'])
                    or row['actual_sha256'] is not None and (not isinstance(row['actual_sha256'], str) or not HEX.fullmatch(row['actual_sha256']))
                    or row['snapshot_sha256'] != digest({key: val for key, val in row.items() if key != 'snapshot_sha256'})
                    or type(row['created_at']) not in {int, float} or not math.isfinite(row['created_at']) or not 0 < row['created_at'] <= 253402300799
                    or type(row['stored_bytes']) is not int or not 0 <= row['stored_bytes'] <= 26 * 1024 * 1024
                    or any(type(row[key]) is not bool for key in ['current_grant', 'purge_allowed']) or row['current_grant'] == row['purge_allowed']
                    or row['state'] not in {'retained', 'purged', 'damaged'} or row['authentication_reverified'] is not False or row['private_bytes_returned'] is not False):
                raise ValueError('closed inspected Photon original snapshot required')
            message_id(row['message_id'])
    else:
        if (set(value) != {'id', 'receipt', 'network_requested', 'message_sent', 'tombstones_retained', 'other_copies_backups_and_WAL_erasure_not_claimed'}
                or value['id'] != request['id'] or not isinstance(value['receipt'], str) or not HEX.fullmatch(value['receipt'])
                or value['network_requested'] is not False or value['message_sent'] is not False or value['tombstones_retained'] is not True
                or value['other_copies_backups_and_WAL_erasure_not_claimed'] is not True):
            raise ValueError('closed non-dispatching Photon disposal receipt required')
    return value
