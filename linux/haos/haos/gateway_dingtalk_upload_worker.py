"""One original-bound native upload, under the isolated private gateway UID."""
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
        raise PermissionError('private upload parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64)); resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    signal.signal(signal.SIGALRM, lambda *_: os._exit(124)); signal.alarm(30)
    from .gateway_dingtalk_admission import finite
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_upload import MAX_INPUT
    raw = sys.stdin.buffer.readline(MAX_INPUT+1)
    if len(raw) > MAX_INPUT or not raw.endswith(b'\n'):
        raise ValueError('bounded private upload startup required')
    request = json.loads(raw, object_pairs_hook=_object, parse_constant=finite)
    if (not isinstance(request, dict) or set(request) != {'action', 'connector', 'credentials', 'policy_sha256', 'parent_pid', 'upload', 'data_base64'}
            or request['action'] != 'upload' or type(request['parent_pid']) is not int or request['parent_pid'] != parent
            or os.getppid() != parent or not isinstance(request['connector'], str)
            or not isinstance(request['policy_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', request['policy_sha256'])):
        raise ValueError('closed native DingTalk upload startup required')
    if sys.stdin.buffer.read(1):
        raise ValueError('unexpected private upload payload')
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
    home = base / ('dingtalk-upload-' + account_scope(value).split(':', 1)[1])
    try:
        home.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _directory(home)
    redactor = Redactor([value['client_secret']]); handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(redactor)); logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    from .gateway_dingtalk_upload import specification
    from .gateway_dingtalk_upload_http import Upload,invoke
    from .gateway_dingtalk_http import Boundary,sdk_scope,QuietLogger
    import base64,hashlib
    checked=specification(value,policy(),request['connector'],request['upload'],redactor)
    encoded=request['data_base64']
    if not isinstance(encoded,str) or not 1<=len(encoded)<=4*((8*1024*1024+2)//3):
        raise ValueError('bounded sealed output encoding required')
    data=base64.b64decode(encoded,validate=True)
    if (base64.b64encode(data).decode()!=encoded or len(data)!=checked['target']['size']
            or hashlib.sha256(data).hexdigest()!=checked['target']['sha256']):
        raise PermissionError('sealed output bytes changed')
    def approved():
        if specification(value,policy(),request['connector'],request['upload'],redactor)!=checked:
            raise PermissionError('native upload approval changed')
    result={'state':'rejected','error':'authority-or-protocol-refused','retry_after':0}
    operation=None;owner=None
    try:
        from importlib.metadata import version
        if ({name:version(name) for name in ('dingtalk-stream','alibabacloud-dingtalk','alibabacloud-tea-openapi')}
                != {'dingtalk-stream':'0.24.3','alibabacloud-dingtalk':'2.2.42','alibabacloud-tea-openapi':'0.4.6'}):
            result={'state':'rejected','error':'sdk-unavailable','retry_after':0}
        else:
            from .gateway_matrix_profile import scope
            with scope(home,{'HERMES_SAFE_MODE':'1'}):
                from gateway.config import PlatformConfig
                from plugins.platforms.dingtalk import adapter as native
                adapter=native.DingTalkAdapter(PlatformConfig(enabled=True,extra={
                    'client_id':value['client_id'],'client_secret':value['client_secret'],
                    'robot_code':value['robot_code'],'card_template_id':''}))
                owner=Boundary(value,approved,redactor);adapter._stream_client=owner.client()
                async def upload():
                    nonlocal operation
                    logger=native.logger;native.logger=QuietLogger()
                    try:
                        with sdk_scope(),owner.operation('token',adapter._stream_client):
                            token=await native.DingTalkAdapter._get_access_token(adapter)
                        if token is None or token not in owner.tokens:
                            return {'state':'rejected','error':owner.failure or 'invalid-token','retry_after':owner.retry_after}
                        operation=Upload(owner,token,checked['target'],data,approved)
                        return invoke(adapter._stream_client,operation)
                    finally:native.logger=logger
                result=asyncio.run(upload())
    except Exception:
        if operation is not None and operation.write_started:result={'state':'uncertain'}
    finally:
        if operation is not None:operation.close()
        if owner is not None:owner.close()
    sys.stdout.write(json.dumps(result)+'\n');sys.stdout.flush()


if __name__=='__main__':
    try:main()
    except Exception:
        sys.stderr.write('private native DingTalk upload worker refused\n');raise SystemExit(1)
