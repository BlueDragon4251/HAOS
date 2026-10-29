"""One native DingTalk reply under the private gateway UID, never generic HTTP."""
import asyncio
import ctypes
import json
import logging
import os
from pathlib import Path
import re
import resource
import signal
import sys


def main():
    from .gateway_runtime import require_runtime_identity, SafeFormatter
    require_runtime_identity()
    if sys.version_info[:2] != (3, 11):
        raise PermissionError('pinned private CPython 3.11 required')
    parent = os.getppid(); libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
        raise PermissionError('private reply parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64)); resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    signal.signal(signal.SIGALRM, lambda *_: os._exit(124)); signal.alarm(30)
    from .gateway_dingtalk_admission import finite
    from .gateway_line_ingress import _object
    raw = sys.stdin.buffer.readline(2097153)
    if len(raw) > 2097152 or not raw.endswith(b'\n'):
        raise ValueError('bounded private reply startup required')
    request = json.loads(raw, object_pairs_hook=_object, parse_constant=finite)
    if (not isinstance(request, dict) or set(request) != {'action', 'connector', 'credentials', 'policy_sha256', 'parent_pid', 'resource'}
            or request['action'] != 'resource' or type(request['parent_pid']) is not int or request['parent_pid'] != parent
            or os.getppid() != parent or not isinstance(request['connector'], str)
            or not isinstance(request['policy_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', request['policy_sha256'])):
        raise ValueError('closed native DingTalk reply startup required')
    if sys.stdin.buffer.read(1):
        raise ValueError('unexpected private reply payload')
    from .gateway_dingtalk import credentials, authority, PreparedDingTalkPolicy, scope as account_scope
    from .redaction import Redactor
    from .sandbox import trusted_json
    value = credentials(request['credentials'])
    def current():
        authority(request['connector'], value, request['policy_sha256'])
    def policy():
        current(); return PreparedDingTalkPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    current()
    from .gateway_line_profile import _directory
    base = Path('/var/lib/haos-gateway'); _directory(base)
    home = base / ('dingtalk-resource-' + account_scope(value).split(':', 1)[1])
    try:
        home.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _directory(home)
    redactor = Redactor([value['client_secret']]); handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(redactor)); logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    from .gateway_dingtalk_http import Failure
    from .gateway_dingtalk_download import ContentFailure
    from .gateway_dingtalk_resource import fetch,ERRORS
    result={'error':'transport-unavailable'}
    try:
        from importlib.metadata import version
        if ({name:version(name) for name in ('dingtalk-stream','alibabacloud-dingtalk','alibabacloud-tea-openapi')}
                != {'dingtalk-stream':'0.24.3','alibabacloud-dingtalk':'2.2.42','alibabacloud-tea-openapi':'0.4.6'}):
            result={'error':'sdk-unavailable'}
        else:
            from .gateway_matrix_profile import scope
            with scope(home,{'HERMES_SAFE_MODE':'1'}):result=asyncio.run(fetch(request,value,current,redactor))
    except (Failure,ContentFailure) as error:
        result={'error':error.kind if error.kind in ERRORS else 'authority-or-protocol-refused'}
        if error.retry_after:result['retry_after']=error.retry_after
    except PermissionError:result={'error':'authority-or-protocol-refused'}
    except Exception:pass
    sys.stdout.write(json.dumps(result)+'\n');sys.stdout.flush()


if __name__=='__main__':
    try:main()
    except Exception:
        sys.stderr.write('private native DingTalk resource worker refused\n');raise SystemExit(1)
