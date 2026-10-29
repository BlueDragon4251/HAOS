"""Disposable private Feishu account-read worker; no sends or caller HTTP options."""
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
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:
        raise PermissionError('private Feishu parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    signal.signal(signal.SIGALRM,lambda *_args:os._exit(124));signal.alarm(30)
    from .gateway_line_ingress import _object
    from .gateway_feishu_http import finite,Boundary,Failure,sdk_scope
    raw=sys.stdin.buffer.readline(2097153)
    if len(raw)>2097152 or not raw.endswith(b'\n'):raise ValueError('bounded private Feishu header required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!=({'action','connector','credentials','policy_sha256','parent_pid'}|({request['action']} if request.get('action') in {'reply','resource'} else set()))
            or not isinstance(request['action'],str) or request['action'] not in {'account','reply','resource'} or type(request['parent_pid']) is not int or request['parent_pid']!=parent
            or os.getppid()!=parent or not isinstance(request['connector'],str)
            or not isinstance(request['policy_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',request['policy_sha256'])):
        raise ValueError('closed private Feishu account read required')
    if request['action']=='account' and len(raw)>32768:raise ValueError('bounded no-send account header required')
    from .gateway_feishu import credentials,authority,scope as account_scope,DOMAINS
    value=credentials(request['credentials'],verify_tls=False)
    def current():return authority(request['connector'],value,request['policy_sha256'])
    current()
    if sys.stdin.buffer.read(1):raise ValueError('unexpected private Feishu payload')
    from .gateway_line_profile import _directory
    base=Path('/var/lib/haos-gateway');_directory(base);home=base/('feishu-'+account_scope(value).split(':',1)[1])
    try:home.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(home)
    from .gateway_matrix_profile import scope
    from .redaction import Redactor
    redactor=Redactor([value['app_secret'],value.get('verification_token',''),value.get('encrypt_key',''),value.get('tls',{}).get('private_key','')])
    import logging
    from .gateway_runtime import SafeFormatter
    handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor))
    logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
    if request['action']=='resource':
        from .gateway_feishu_resource import fetch
        try:result=fetch(request,value,home,current,redactor)
        except Failure as error:
            from .gateway_feishu_process import ERRORS
            result={'error':error.kind if error.kind in ERRORS else 'authority-or-protocol-refused'}
        except PermissionError:result={'error':'authority-or-protocol-refused'}
        except Exception:result={'error':'transport-unavailable'}
        sys.stdout.write(json.dumps(result)+'\n');return
    if request['action']=='reply':
        result=send_reply(request,value,home,current,redactor)
        sys.stdout.write(json.dumps(result)+'\n');return
    boundary=Boundary(value,current,
        lambda purpose,target:purpose=='account' and target=={},redactor)
    result={'error':'transport-unavailable'}
    try:
        with scope(home,{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu import adapter as native
            if not native._load_lark_oapi():raise Failure('sdk-unavailable')
            with sdk_scope():
                client=native._build_lark_client(value['app_id'],value['app_secret'],DOMAINS[value['domain']])
                with boundary.operation(client._config,'account',{}):
                    response=client.request(native._tenant_get_request('/open-apis/bot/v3/info'))
                    body=json.loads(response.raw.content,object_pairs_hook=_object,parse_constant=finite)
                    bot=body.get('bot')
                    if body['code']!=0:raise Failure('authentication-refused')
                    if not isinstance(bot,dict) or bot.get('open_id')!=value['bot_open_id']:
                        raise Failure('identity-refused')
                    # This API proves the bot's open ID, not the separately supplied tenant.
                    current();result={'bot_identity_verified':True,'tenant_identity_verified':False,
                        'bot_open_id':value['bot_open_id'],'account_scope':account_scope(value),'message_sent':False}
    except Failure as error:
        from .gateway_feishu_process import ERRORS
        result={'error':error.kind if error.kind in ERRORS else 'authority-or-protocol-refused'}
    except PermissionError:result={'error':'authority-or-protocol-refused'}
    except Exception:result={'error':'transport-unavailable'}
    sys.stdout.write(json.dumps(result)+'\n')


def send_reply(request,value,home,current,redactor):
    from .gateway_feishu_send import specification,wire_target,bind_single_native_send
    from .gateway_feishu_reply_http import ReplyBoundary
    from .gateway_feishu_http import sdk_scope
    from .gateway_feishu import PreparedFeishuPolicy,DOMAINS,MESSAGE_ID
    from .gateway_matrix_profile import scope
    from .sandbox import trusted_json
    import asyncio
    def policy():
        current();return PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    item=specification(value,policy(),request['connector'],request['reply'],redactor)
    operation=None
    try:
        with scope(home,{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu import adapter as native
            from gateway.config import PlatformConfig
            if not native._load_lark_oapi():return {'state':'rejected','error':'sdk-unavailable'}
            adapter=native.FeishuAdapter(PlatformConfig(enabled=True));exact=wire_target(adapter,item)
            bind_single_native_send(adapter,exact)
            def authorize(purpose,target):
                latest=specification(value,policy(),request['connector'],request['reply'],redactor)
                return purpose=='reply' and latest==item and target==exact
            boundary=ReplyBoundary(value,current,authorize,redactor)
            with sdk_scope():
                client=native._build_lark_client(value['app_id'],value['app_secret'],DOMAINS[value['domain']]);adapter._client=client
                with boundary.operation(client._config,'reply',exact) as operation:
                    result=asyncio.run(native.FeishuAdapter.send(adapter,item['chat_id'],item['body'],
                        reply_to=item['source_id'],metadata={'thread_id':item['thread_id']}))
                    current();body=operation.get('reply_response',{});data=body.get('data')
                    if (result.success and isinstance(data,dict) and body.get('code')==0
                            and isinstance(result.message_id,str) and MESSAGE_ID.fullmatch(result.message_id)
                            and data.get('message_id')==result.message_id and data.get('chat_id')==item['chat_id']
                            and (not item['thread_id'] or data.get('thread_id')==item['thread_id'])):
                        return {'state':'confirmed','message_id':result.message_id}
                    if operation.get('write_started') and type(body.get('code')) is int and body['code']!=0:
                        return {'state':'rejected','error':'rate-limited' if body['code']==99991400 else 'native-refused'}
    except Exception:pass  # Never release private SDK/response/exception text.
    if operation is not None:
        if operation.get('authentication_refused'):return {'state':'rejected','error':'authentication-refused'}
        code=operation.get('http_status')
        if code in {401,403,429}:return {'state':'rejected','error':'rate-limited' if code==429 else 'authentication-refused'}
        if not operation.get('write_started'):return {'state':'rejected','error':'transport-unavailable'}
    return {'state':'uncertain'}


if __name__=='__main__':main()
