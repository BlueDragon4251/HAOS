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
    if (not isinstance(request, dict) or set(request) != {'action', 'connector', 'credentials', 'policy_sha256', 'parent_pid', 'reply'}
            or request['action'] != 'reply' or type(request['parent_pid']) is not int or request['parent_pid'] != parent
            or os.getppid() != parent or not isinstance(request['connector'], str)
            or not isinstance(request['policy_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', request['policy_sha256'])):
        raise ValueError('closed native DingTalk reply startup required')
    if sys.stdin.buffer.read(1):
        raise ValueError('unexpected private reply payload')
    from .gateway_dingtalk import credentials, authority, PreparedDingTalkPolicy, scope as account_scope
    from .gateway_dingtalk_send import specification, wire_target, invoke_native, ExpiredSession
    from .gateway_dingtalk_reply_http import Boundary
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
    home = base / ('dingtalk-reply-' + account_scope(value).split(':', 1)[1])
    try:
        home.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _directory(home)
    redactor = Redactor([value['client_secret']]); handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(redactor)); logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    result = {'state': 'rejected', 'error': 'authority-or-protocol-refused', 'retry_after': 0}
    boundary = None;robot_started=False
    try:
        from importlib.metadata import version
        if ({name: version(name) for name in ('dingtalk-stream', 'alibabacloud-dingtalk', 'alibabacloud-tea-openapi')}
                != {'dingtalk-stream': '0.24.3', 'alibabacloud-dingtalk': '2.2.42', 'alibabacloud-tea-openapi': '0.4.6'}):
            result = {'state': 'rejected', 'error': 'sdk-unavailable', 'retry_after': 0}
        else:
            blueprint = specification(value, policy(), request['connector'], request['reply'], redactor)
            from .gateway_matrix_profile import scope
            with scope(home, {'HERMES_SAFE_MODE': '1'}):
                from gateway.config import PlatformConfig
                from plugins.platforms.dingtalk.adapter import DingTalkAdapter
                from .gateway_ingress import durable_adapter
                adapter = durable_adapter(DingTalkAdapter(PlatformConfig(enabled=True, extra={
                    'client_id': value['client_id'], 'client_secret': value['client_secret'],
                    'robot_code': value['robot_code'], 'card_template_id': ''})))
                if value.get('reply_mode','session')=='robot':
                    from .gateway_dingtalk_robot_reply import invoke
                    adapter._haos_robot_credentials=value
                    def approved_robot():
                        if specification(value,policy(),request['connector'],request['reply'],redactor)!=blueprint:
                            raise PermissionError('DingTalk stable reply intent changed')
                    robot_started=True
                    result=asyncio.run(invoke(adapter,blueprint,approved_robot,redactor))
                    sys.stdout.write(json.dumps(result)+'\n');sys.stdout.flush();return
                exact = wire_target(adapter, blueprint)
                def approved():
                    latest = specification(value, policy(), request['connector'], request['reply'], redactor)
                    if latest != blueprint or wire_target(adapter, latest) != exact:
                        raise PermissionError('DingTalk immutable reply proof changed')
                boundary = Boundary(exact, blueprint['session_expires_at'], approved, redactor)
                async def send():
                    try:
                        return await invoke_native(adapter, blueprint, boundary, approved)
                    finally:
                        await boundary.close()
                result = asyncio.run(send())
    except ExpiredSession:
        result = {'state': 'uncertain'} if boundary is not None and boundary.write_started else {
            'state': 'rejected', 'error': 'expired-session', 'retry_after': 0}
    except Exception:
        if robot_started or boundary is not None and boundary.write_started:
            result = {'state': 'uncertain'}
    # Never return a native SDK random UUID as a remote message ID, or leak an
    # exception string, bearer URL, app secret, callback body or HTTP response.
    sys.stdout.write(json.dumps(result) + '\n'); sys.stdout.flush()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('private native DingTalk reply worker refused\n'); raise SystemExit(1)
