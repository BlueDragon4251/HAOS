"""Continuous private native WS worker; parent durably admits every event before ACK."""
import asyncio
import base64
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import resource
import signal
import ssl
import sys
import threading

from .gateway_feishu_admission import MAX_EVENT,approve,normalize,Refused,finite
from .gateway_line_ingress import _object


def main():
    from .gateway_runtime import require_runtime_identity,SafeFormatter
    require_runtime_identity();parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('private WS parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(40)
    raw=sys.stdin.buffer.readline(32769)
    if len(raw)>32768 or not raw.endswith(b'\n'):raise ValueError('bounded private WS startup required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'connector','credentials','policy_sha256','parent_pid'}
            or type(request['parent_pid']) is not int or request['parent_pid']!=parent or os.getppid()!=parent
            or not isinstance(request['connector'],str) or not isinstance(request['policy_sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}',request['policy_sha256'])):raise ValueError('exact private WS startup required')
    from .gateway_feishu import credentials,authority,PreparedFeishuPolicy,DOMAINS
    value=credentials(request['credentials'],verify_tls=False)
    if value['connection_mode']!='websocket':raise PermissionError('explicit websocket account required')
    stopped=threading.Event();responses={};lock=threading.Lock();output_lock=threading.Lock();holder={};sequence=[0]
    output=sys.stdout.buffer;sys.stdout=sys.stderr
    def emit(value):
        encoded=(json.dumps(value,separators=(',',':'))+'\n').encode()
        with output_lock:output.write(encoded);output.flush()
    def current():
        if stopped.is_set():raise PermissionError('private socket stopping')
        return authority(request['connector'],value,request['policy_sha256'])
    current()
    from .gateway_line_profile import _directory
    from .gateway import digest
    base=Path('/var/lib/haos-gateway');_directory(base);home=base/('ws-'+digest([request['connector'],value]))
    try:home.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(home)
    from .redaction import Redactor
    redactor=Redactor([value['app_secret']]);handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor))
    logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
    def stop():
        stopped.set()
        with lock:
            for item in responses.values():item['ready'].set()
        adapter=holder.get('adapter');loop=getattr(adapter,'_ws_thread_loop',None)
        if loop is not None and not loop.is_closed():loop.call_soon_threadsafe(loop.stop)
    signal.signal(signal.SIGTERM,lambda *_:stop())
    def read_parent():
        try:
            while not stopped.is_set():
                line=sys.stdin.buffer.readline(4097)
                if not line or len(line)>4096 or not line.endswith(b'\n'):break
                data=json.loads(line,object_pairs_hook=_object,parse_constant=finite)
                if data=={'stop':True}:break
                if (not isinstance(data,dict) or type(data.get('seq')) is not int
                        or set(data) not in ({'seq','receipt'},{'seq','refused'})):break
                if 'receipt' in data and (not isinstance(data['receipt'],str) or not re.fullmatch('[0-9a-f]{64}',data['receipt'])):break
                if 'refused' in data and data['refused'] is not True:break
                with lock:
                    item=responses.get(data['seq'])
                    if item is None or item['reply'] is not None:break
                    item['reply']=data;item['ready'].set()
        except Exception:pass
        finally:stop()
    def capture(raw):
        current()
        from .sandbox import trusted_json
        policy=PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
        proof=approve(policy,request['connector'],value,raw)
        projection=normalize(policy,request['connector'],value,raw,proof,redactor)
        # Session tickets are known only inside this worker. Reject reflection
        # into any normalized goal/resource before the independent parent admits.
        if redactor.clean(projection)!=projection:raise Refused('credential-reflection')
        sequence[0]+=1;seq=sequence[0];item={'ready':threading.Event(),'reply':None}
        with lock:
            if responses:raise PermissionError('one private WS event at a time')
            responses[seq]=item
        try:
            emit({'kind':'event','seq':seq,'payload_base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()})
            if not item['ready'].wait(5):raise ConnectionError('durable parent receipt deadline exceeded')
            current();reply=item['reply']
            if reply is None or 'receipt' not in reply:raise PermissionError('parent refused independent source admission')
            return reply['receipt']
        finally:
            with lock:responses.pop(seq,None)
    from .gateway_feishu_ws_frames import Bridge,install as guard_frames
    class PipeBridge(Bridge):
        def __init__(self):self.current=current;self.capture=capture
        def _do_without_validation(self,raw):
            if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_EVENT:raise Refused('unsupported-content')
            self.commit(raw);return None
    async def prepare():
        from plugins.platforms.feishu import adapter as native
        from gateway.config import PlatformConfig
        from lark_oapi.core.enum import LogLevel
        if not native._load_lark_oapi():raise PermissionError('frozen SDK unavailable')
        from lark_oapi.ws.client import Client
        from .gateway_feishu_ws_http import Discovery
        adapter=native.FeishuAdapter(PlatformConfig(enabled=True));holder['adapter']=adapter
        client=Client(value['app_id'],value['app_secret'],domain=DOMAINS[value['domain']],log_level=LogLevel.WARNING,extra_ua_tags=['channel'])
        def exited(kind):holder['failure']=kind;stop()
        guard_frames(client,current,PipeBridge(),on_exit=exited)
        receive=client._receive_message_loop
        async def linked():
            current()
            if client._conn is None:raise ConnectionError('verified private socket required before readiness')
            signal.alarm(0);emit({'kind':'ready'})
            await receive()
        client._receive_message_loop=linked
        discovery=Discovery(value,current,redactor);discovery.install(client)
        original=client._get_conn_url
        def discover():
            try:return original()
            except Exception as error:
                holder['failure']=getattr(error,'kind','transport-unavailable');raise
        client._get_conn_url=discover
        connect=client._connect
        async def checked_connect():
            try:return await connect()
            except Exception as error:
                import lark_oapi.ws.client as sdk
                from lark_oapi.ws.exception import ClientException,ServerException
                from websockets.exceptions import InvalidStatus
                if isinstance(error,ssl.SSLError):holder['failure']='tls-refused'
                elif isinstance(error,(ClientException,ServerException)) and error.code in {sdk.AUTH_FAILED,sdk.FORBIDDEN}:
                    holder['failure']='authentication-refused'
                elif isinstance(error,InvalidStatus):
                    code=error.response.status_code
                    holder['failure']='authentication-refused' if code in {401,403} else 'rate-limited' if code==429 else 'redirect-refused' if 300<=code<400 else 'transport-unavailable'
                raise
        client._connect=checked_connect;adapter._ws_client=client
        return adapter,client,discovery,native
    from .gateway_matrix_profile import scope
    env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],'FEISHU_DOMAIN':value['domain'],
        'FEISHU_BOT_OPEN_ID':value['bot_open_id'],'FEISHU_ALLOW_ALL_USERS':'false','GATEWAY_ALLOW_ALL_USERS':'false'}
    threading.Thread(target=read_parent,name='private-feishu-parent',daemon=True).start()
    with scope(home,env):
        adapter,client,discovery,native=asyncio.run(prepare())
        with discovery.connection_scope():native._run_official_feishu_ws_client(client,adapter)
    stopped.set()
    from .gateway_feishu_process import ERRORS
    kind=holder.get('failure','transport-unavailable')
    emit({'kind':'stopped','error':kind if kind in ERRORS else 'authority-or-protocol-refused'})


if __name__=='__main__':
    try:main()
    except Exception:
        # Never emit exception strings, endpoint tickets or startup credentials.
        sys.stderr.write('private Feishu WS worker refused\n');raise SystemExit(1)
