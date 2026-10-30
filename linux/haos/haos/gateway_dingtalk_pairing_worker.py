"""Owner-launched, bounded gateway-UID observation; no agent or outbound messages."""
import asyncio
import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


def main():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()
    if sys.version_info[:2]!=(3,11):raise PermissionError('pinned private CPython 3.11 required')
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('observation parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024*1024,64*1024*1024))
    signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(75)
    from .gateway_dingtalk_admission import finite
    from .gateway_line_ingress import _object
    raw=sys.stdin.buffer.read(32769)
    if len(raw)>32768:raise ValueError('bounded owner observation frame required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'connector','credentials','policy_sha256','parent_pid','observation'}
            or type(request['parent_pid']) is not int or request['parent_pid']!=parent or os.getppid()!=parent):
        raise ValueError('exact owner observation request required')
    from .gateway_dingtalk import credentials,authority,PreparedDingTalkPolicy
    from .gateway_dingtalk_pairing import challenge,candidate,Candidates
    from .gateway_dingtalk_ws_process import Session
    from .gateway_raw import NativeInbox
    DATABASE=Path('/var/lib/haos-gateway/native-inbox.db')
    from .redaction import Redactor
    from .sandbox import trusted_json
    value=credentials(request['credentials']);observation=challenge(request['observation'])
    def current():authority(request['connector'],value,request['policy_sha256'])
    current()
    policy=lambda:PreparedDingTalkPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    # The private profile preserves already-approved traffic while the regular
    # service is stopped. Observation never invokes its agent dispatch loop.
    inbox=NativeInbox(DATABASE,Redactor([value['client_secret']]));store=Candidates(inbox)
    async def observe():
        adapter=None;observed=[];session=None
        try:
            if any(b['connector']==request['connector'] for b in policy().bindings.values()):
                from .gateway_dingtalk_profile import build
                try:(DATABASE.parent/'profiles').mkdir(mode=0o700)
                except FileExistsError:pass
                adapter=build(value,parent=DATABASE.parent/'profiles',connector=request['connector'],policy=policy,inbox=inbox)
            def capture(raw):
                current();item=candidate(value,observation,raw)
                if item is not None:
                    proof=store.retain(request['connector'],item);current();observed.append((item,proof));return proof
                if adapter is None:raise PermissionError('unknown sender is not authorized')
                from .gateway_dingtalk_ingress import capture as retain_original
                return retain_original(adapter,raw)
            session=Session(value,request['connector'],current,capture,observation=observation)
            async with asyncio.timeout(max(.01,(observation['until']-time.time()*1000)/1000)):
                await session.start()
                while not session.observation_ack.done():
                    current()
                    if not session.active:raise ConnectionError('observation connection ended')
                    await asyncio.wait({session.observation_ack},timeout=.1)
                if len(observed)!=1:raise PermissionError('exactly one retained observation required')
                item,proof=observed[0]
                return {'observed':True,'candidate':item,'observation_receipt_sha256':proof,
                    'sender_grants_changed':False,'external_delivery_verified':False}
        except TimeoutError:
            return {'observed':False,'error':'observation-timeout','sender_grants_changed':False,'message_sent':False,'mission_created':False}
        finally:
            if session is not None:await session.close()
            if adapter is not None:await adapter.close_profile()
    try:result=asyncio.run(observe());current()
    finally:inbox.close()
    encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
    if len(encoded.encode())>16384:raise ValueError('bounded observation metadata required')
    print(encoded)


if __name__=='__main__':
    try:main()
    except Exception:
        sys.stderr.write('private DingTalk pairing observation refused\n');raise SystemExit(1)
