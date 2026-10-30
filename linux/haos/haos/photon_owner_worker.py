"""One actual Root-parent handoff, private gateway UID, no keys or SDK imports."""
import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import sqlite3
import sys


def main():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()
    if sys.version_info[:2] != (3, 11): raise PermissionError('pinned private Python 3.11 required')
    parent = os.getppid()
    if parent <= 1: raise PermissionError('actual live authenticated Root parent required')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent: raise PermissionError('Owner parent lifetime guard required')
    if libc.prctl(38, 1, 0, 0, 0) != 0: raise PermissionError('private Photon worker must deny privilege changes')
    def root_parent():
        if os.getppid() != parent: raise PermissionError('authenticated Owner parent lost')
        fields = next(line for line in Path('/proc/' + str(parent) + '/status').read_text().splitlines() if line.startswith('Uid:')).split()[1:]
        if fields != ['0'] * 4: raise PermissionError('actual authenticated Root parent required')
    root_parent(); resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    signal.signal(signal.SIGALRM, lambda *_: os._exit(124)); signal.alarm(40)
    from .gateway import Conflict
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .photon_owner_process import ACTIONS, HEX, params, policy, response
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536: raise ValueError('bounded credential-free Photon request required')
    request = json.loads(raw, object_pairs_hook=_object, parse_constant=finite)
    if (not isinstance(request, dict) or set(request) != {'action', 'policy_sha256', 'parent_pid', 'owner_uid', 'params'}
            or not isinstance(request['action'], str) or request['action'] not in ACTIONS or type(request['parent_pid']) is not int
            or request['parent_pid'] != parent or type(request['owner_uid']) is not int or not 0 <= request['owner_uid'] < 2**32 - 1
            or not isinstance(request['policy_sha256'], str) or not HEX.fullmatch(request['policy_sha256'])):
        raise PermissionError('closed authenticated Photon Owner request required')
    action = request['action']; chosen = params(action, request['params'], request['owner_uid'])
    def current():
        root_parent(); selected, fingerprint = policy()
        if fingerprint != request['policy_sha256']: raise PermissionError('Root gateway policy changed during Photon Owner action')
        return selected
    store = None; lease = None
    try:
        selected = current()
        from .gateway_line_profile import _directory
        from .gateway_photon_recovery import profile_name, sources, purge_source
        profiles = Path('/var/lib/haos-gateway/profiles')
        if action == 'status':
            if selected is None or selected.connectors.get(chosen['connector'], {}).get('platform') != 'photon':
                raise PermissionError('saved current Photon connector required for recorded status')
            from .gateway_photon_status import read
            result = {'result': read(Path('/var/lib/haos-gateway/native-inbox.db'), chosen, current), 'active_authorization_returned': False}
        elif action == 'profiles':
            rows = []; count = 0
            if profiles.exists():
                _directory(profiles)
                for profile in sorted(profiles.iterdir(), key=lambda item: item.name):
                    if not profile.name.startswith('photon-'): continue
                    profile_name(profile.name); _directory(profile); count += 1
                    if count > 65536: raise Conflict('Photon historical profile capacity exceeded')
                    if count <= 128: rows.append(profile.name)
            result = {'profiles': rows, 'history_truncated': count > 128, 'network_requested': False, 'private_bytes_returned': False}
        else:
            from .gateway_matrix_profile import acquire_lease
            from .gateway_photon_recovery import open_retained
            _directory(profiles); profile = profiles / chosen['profile']; _directory(profile)
            lease = acquire_lease(profile)
            store = open_retained(profile, current)
            result = sources(store, selected, chosen['profile'], current) if action == 'sources' else purge_source(store, selected, chosen, current)
        current(); print(json.dumps(response(result, action, chosen), ensure_ascii=False))
    except (PermissionError, Conflict): print(json.dumps({'error': 'authority-refused'}))
    except (ImportError, ModuleNotFoundError): print(json.dumps({'error': 'runtime-unavailable'}))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError): print(json.dumps({'error': 'storage-unavailable'}))
    finally:
        try:
            if store is not None: store.close()
        finally:
            if lease is not None: os.close(lease)


if __name__ == '__main__': main()
