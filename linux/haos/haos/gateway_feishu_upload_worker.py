"""One bounded private native upload process; never sends a message."""
import ctypes
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import resource
import signal
import sys


def main():
    from .gateway_runtime import require_runtime_identity,SafeFormatter
    require_runtime_identity();parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('private upload parent guard required')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(30)
    from .gateway_line_ingress import _object
    from .gateway_feishu_http import finite,Failure,sdk_scope
    header=sys.stdin.buffer.readline(2097153)
    if len(header)>2097152 or not header.endswith(b'\n'):raise ValueError('bounded private upload header required')
    request=json.loads(header,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'connector','credentials','policy_sha256','parent_pid','upload'}
            or type(request['parent_pid']) is not int or request['parent_pid']!=parent or os.getppid()!=parent
            or not isinstance(request['connector'],str) or not isinstance(request['policy_sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}',request['policy_sha256'])):raise ValueError('exact private upload request required')
    from .gateway_feishu import credentials,authority,PreparedFeishuPolicy,DOMAINS
    from .sandbox import trusted_json
    value=credentials(request['credentials'],verify_tls=False)
    def current():return authority(request['connector'],value,request['policy_sha256'])
    def policy():current();return PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    from .redaction import Redactor
    redactor=Redactor([value['app_secret'],value.get('verification_token',''),value.get('encrypt_key',''),value.get('tls',{}).get('private_key','')])
    handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor));logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
    from .gateway_feishu_upload import specification
    blueprint=specification(value,policy(),request['connector'],request['upload'],redactor);exact=blueprint['target']
    data=sys.stdin.buffer.read(exact['size']+1)
    if len(data)!=exact['size'] or hashlib.sha256(data).hexdigest()!=exact['sha256']:
        raise ValueError('sealed private output bytes changed')
    if any(secret.encode() in data for secret in redactor.secrets):raise PermissionError('private upload credential reflection refused')
    from .gateway_line_profile import _directory
    base=Path('/var/lib/haos-gateway');_directory(base);home=base/'uploads'
    try:home.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(home)
    from .gateway_matrix_profile import scope
    from .gateway_feishu_upload_http import UploadBoundary
    operation=None;result={'state':'rejected','error':'transport-unavailable'}
    try:
        with scope(home,{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu import adapter as native
            if not native._load_lark_oapi():raise Failure('sdk-unavailable')
            if exact['kind']=='file':
                file_type,_=native.FeishuAdapter._resolve_outbound_file_routing(file_path=exact['name'],requested_message_type='file')
                if file_type!=exact['file_type']:raise PermissionError('upload routing differs from pinned native codec')
            def authorize(purpose,target):
                latest=specification(value,policy(),request['connector'],request['upload'],redactor)
                return purpose=='upload' and latest==blueprint and target==exact
            boundary=UploadBoundary(value,current,authorize,redactor)
            with sdk_scope():
                client=native._build_lark_client(value['app_id'],value['app_secret'],DOMAINS[value['domain']])
                stream=io.BytesIO(data);stream.name=exact['name']
                with boundary.operation(client._config,'upload',exact) as operation:
                    if exact['kind']=='image':
                        body=native.FeishuAdapter._build_image_upload_body(image_type='message',image=stream)
                        response=client.im.v1.image.create(native.FeishuAdapter._build_image_upload_request(body))
                    else:
                        body=native.FeishuAdapter._build_file_upload_body(file_type=exact['file_type'],file_name=exact['name'],file=stream,duration=exact['duration_ms'])
                        response=client.im.v1.file.create(native.FeishuAdapter._build_file_upload_request(body))
                    current();wire=operation.get('upload_response',{})
                    key=operation.get('accepted_key');field='image_key' if exact['kind']=='image' else 'file_key'
                    if response.success() and key is not None and getattr(response.data,field,None)==key:
                        result={'state':'confirmed','kind':exact['kind'],'key':key}
                    elif type(wire.get('code')) is int and wire['code']!=0:
                        result={'state':'rejected','error':'rate-limited' if wire['code']==99991400 else 'native-refused'}
                    else:result={'state':'uncertain'}
    except Exception as error:
        known=operation is None or not operation.get('write_started') or operation.get('http_status') in {401,403,429}
        kind=getattr(error,'kind','authority-or-protocol-refused')
        from .gateway_feishu_process import ERRORS
        result={'state':'rejected','error':kind if kind in ERRORS else 'authority-or-protocol-refused'} if known else {'state':'uncertain'}
    sys.stdout.write(json.dumps(result)+'\n')


if __name__=='__main__':
    try:main()
    except Exception:
        sys.stderr.write('private Feishu upload worker refused\n');raise SystemExit(1)
