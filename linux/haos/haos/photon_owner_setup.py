"""Root Owner entry points; recorded status never stops the gateway service."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess


def saved(connector):
    from .initial_setup import require_root
    require_root()
    from .photon_owner_process import policy
    from .gateway_photon import credentials, scope
    from .sandbox import trusted_json
    selected, snapshot = policy(); path = Path('/etc/haos/gateway-credentials'); own = path.lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid != 0 or own.st_mode & 0o077 or own.st_nlink != 1:
        raise PermissionError('Root-private Photon credential store required')
    private = trusted_json(path)
    if (selected is None or not isinstance(private, dict) or set(private) != {'connectors', 'publication'}
            or private['publication'] != selected.publication or not isinstance(private['connectors'], dict)
            or set(private['connectors']) != set(selected.connectors) or selected.connectors.get(connector, {}).get('platform') != 'photon'):
        raise PermissionError('exact matched saved Photon connector required')
    value = credentials(private['connectors'][connector])
    if any(name != connector and row['platform'] == 'photon' and scope(credentials(private['connectors'][name])) == scope(value)
            for name, row in selected.connectors.items()): raise PermissionError('Photon account cannot belong to multiple connectors')
    return value, snapshot


def _invoke(action, chosen, *, expected=None):
    from .initial_setup import require_root, quiesce_for_setup
    require_root()
    from .photon_owner_process import command, params, policy, response
    from .gateway_setup import stopped_gateway
    from .google_chat_owner_setup import _runtime_state
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .owner import audit
    owner_uid = int(os.environ.get('SUDO_UID', '0'))
    chosen = params(action, chosen, owner_uid)
    if action != 'status': quiesce_for_setup(gateway_only=True); stopped_gateway()
    _, publication = policy()
    if expected is not None and publication != expected: raise PermissionError('saved Photon account changed before status read')
    account = pwd.getpwnam('haos-gateway')
    if account.pw_uid == 0 or account.pw_gid == 0: raise PermissionError('separate private Photon gateway identity required')
    _runtime_state(account)
    request = {'action': action, 'policy_sha256': publication, 'parent_pid': os.getpid(), 'owner_uid': owner_uid, 'params': chosen}
    if action == 'auth-retry':
        audit('gateway.photon-auth-retry-intent', {'connector': chosen['connector'], 'account_scope': chosen['account_scope'],
            'credential_scope': chosen['credential_scope'], 'inspection_sha256': chosen['inspection_sha256'], 'note_sha256': chosen['note_sha256']})
    elif action == 'purge-source':
        audit('gateway.photon-source-disposal-intent', {'profile': chosen['profile'], 'id': chosen['id'],
            'snapshot_sha256': chosen['snapshot_sha256'], 'note_sha256': chosen['note_sha256']})
    try:
        result = subprocess.run(command(), input=json.dumps(request, ensure_ascii=False) + '\n', text=True, capture_output=True, timeout=45,
            user=account.pw_uid, group=account.pw_gid, extra_groups=[], umask=0o077, cwd='/usr/lib/haos',
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'HERMES_SAFE_MODE': '1'})
    except subprocess.TimeoutExpired: raise RuntimeError('Photon-Verwaltung: Zeitlimit; privaten Worker und Journal prüfen.') from None
    if result.returncode or len(result.stdout.encode()) > 262144:
        raise RuntimeError('Photon-Verwaltung: privater Worker fehlgeschlagen; Runtime und Journal prüfen.')
    checked = response(json.loads(result.stdout, object_pairs_hook=_object, parse_constant=finite), action, chosen)
    if policy()[1] != publication: raise PermissionError('Root publication changed during Photon Owner action')
    audit('gateway.photon-owner-' + action, {'profile': chosen.get('profile'), 'connector': chosen.get('connector'),
        'network_requested': False, 'message_sent': False, **({'receipt': checked['receipt']} if 'receipt' in checked else {})})
    return checked


def status(connector):
    from .initial_setup import require_root
    require_root()
    from .gateway import digest
    from .gateway_photon import scope
    value, publication = saved(connector)
    return _invoke('status', {'connector': connector, 'credential_scope': digest([value['project_id'], value['project_secret'], value['phone']]),
        'account_scope': scope(value)}, expected=publication)


def profiles(): return _invoke('profiles', {})


def retry_auth(connector, observed, note, *, confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_photon_auth_retry import inspection
    from .gateway_photon_health import credential_keys
    from .gateway_photon import scope
    from .gateway_photon_status import checked
    value, publication = saved(connector); keys = credential_keys(value)
    chosen = {'connector': connector, 'credential_scope': keys[0], 'account_scope': scope(value)}
    checked(observed, chosen)
    if confirmed is not True or not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
        raise PermissionError('aktuellen Photon-Anmeldefehler prüfen, begründen und einen erneuten Versuch ausdrücklich bestätigen')
    return _invoke('auth-retry', {**chosen, 'credential_aliases': keys, 'inspection_sha256': inspection(observed),
        'owner_uid': int(os.environ.get('SUDO_UID', '0')), 'note_sha256': hashlib.sha256(note.strip().encode()).hexdigest(),
        'confirmed': True}, expected=publication)


def sources(profile):
    from .gateway_photon_recovery import profile_name
    return _invoke('sources', {'profile': profile_name(profile)})


def purge(profile, identity, snapshot, note, *, confirmed=False):
    from .initial_setup import require_root
    require_root()
    if confirmed is not True or not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
        raise PermissionError('Photon-Original prüfen, Begründung angeben und Bereinigung ausdrücklich bestätigen')
    return _invoke('purge-source', {'profile': profile, 'id': identity, 'snapshot_sha256': snapshot,
        'note_sha256': hashlib.sha256(note.strip().encode()).hexdigest(), 'owner_uid': int(os.environ.get('SUDO_UID', '0')), 'confirmed': True})
