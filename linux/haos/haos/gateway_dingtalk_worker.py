"""One-shot private native DingTalk token action; never sends messages."""
import asyncio
import ctypes
import json
import os
from pathlib import Path
import re
import resource
import signal
import sys


def main():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()
    if sys.version_info[:2]!=(3,11):raise PermissionError('pinned private CPython 3.11 required')
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('private parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
    signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(30)
    from .gateway_dingtalk_admission import finite
    from .gateway_line_ingress import _object
    raw=sys.stdin.buffer.read(32769)
    if len(raw)>32768 or not raw.endswith(b'\n'):raise ValueError('bounded private DingTalk account frame required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'action','connector','credentials','policy_sha256','parent_pid'}
            or request['action']!='account' or type(request['parent_pid']) is not int or request['parent_pid']!=parent
            or os.getppid()!=parent or not isinstance(request['connector'],str)
            or not isinstance(request['policy_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',request['policy_sha256'])):
        raise ValueError('closed no-send DingTalk account action required')
    from .gateway_dingtalk import credentials,authority,scope
    value=credentials(request['credentials'])
    def current():authority(request['connector'],value,request['policy_sha256'])
    current()
    from importlib.metadata import version,PackageNotFoundError
    try:ready=version('dingtalk-stream')=='0.24.3' and version('alibabacloud-dingtalk')=='2.2.42' and version('alibabacloud-tea-openapi')=='0.4.6'
    except PackageNotFoundError:ready=False
    if not ready:
        print(json.dumps({'error':'sdk-unavailable'}));return
    from .gateway_dingtalk_http import Boundary,Failure,sdk_scope
    from .redaction import Redactor
    from .gateway_runtime import SafeFormatter
    import logging
    redactor=Redactor([value['client_secret']]);handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor))
    logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
    boundary=Boundary(value,current,redactor)
    try:
        from .gateway_line_profile import _directory
        from .gateway_matrix_profile import scope as private_scope
        home=Path('/var/lib/haos-gateway');_directory(home)
        with private_scope(home,{'HERMES_SAFE_MODE':'1'}):
            from gateway.config import PlatformConfig
            from plugins.platforms.dingtalk.adapter import DingTalkAdapter
            adapter=DingTalkAdapter(PlatformConfig(enabled=True,extra={
                'client_id':value['client_id'],'client_secret':value['client_secret'],'card_template_id':''}))
            client=boundary.client();adapter._stream_client=client
            with sdk_scope(),boundary.operation('token',client):token=asyncio.run(adapter._get_access_token())
        current()
        if token is None:result={'error':boundary.failure or 'transport-unavailable'}
        else:
            if token not in boundary.tokens:raise Failure('invalid-token')
            result={'app_authenticated':True,'corp_identity_verified':False,'robot_identity_verified':False,
                'account_scope':scope(value),'message_sent':False}
    except Failure as error:result={'error':error.kind}
    except PermissionError:result={'error':'authority-or-protocol-refused'}
    except Exception:result={'error':'transport-unavailable'}
    finally:boundary.close()
    sys.stdout.write(json.dumps(result)+'\n');sys.stdout.flush()


if __name__=='__main__':
    try:main()
    except Exception:
        print('haos.dingtalk.account.unavailable',file=sys.stderr);raise SystemExit(1)
