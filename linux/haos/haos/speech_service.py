"""Private local-only speech RPC and one-shot native worker, without account keys."""
import asyncio
import base64
import hashlib
import json
import os
import pwd
import re
import resource
import signal
import socket
import struct
import sys

from .speech import MAX_AUDIO_BYTES,SpeechRefused,transcribe

MAX_FRAME=MAX_AUDIO_BYTES*4//3+4096
MAX_REPLY=96*1024
_HASH=re.compile('[0-9a-f]{64}\\Z')


def request_bytes(value):
    if (not isinstance(value,dict) or set(value)!={'data','sha256'} or not isinstance(value['data'],str)
            or not 1<=len(value['data'])<=MAX_AUDIO_BYTES*4//3+4
            or not isinstance(value['sha256'],str) or not _HASH.fullmatch(value['sha256'])):
        raise SpeechRefused('exact bounded audio bytes and checksum required')
    try:data=base64.b64decode(value['data'],validate=True)
    except Exception:raise SpeechRefused('canonical base64 voice required') from None
    if (not 1<=len(data)<=MAX_AUDIO_BYTES or base64.b64encode(data).decode()!=value['data']
            or hashlib.sha256(data).hexdigest()!=value['sha256']):
        raise SpeechRefused('voice byte count or checksum mismatch')
    return data


def worker():
    account=pwd.getpwnam('haos-speech')
    if os.geteuid()==0 or os.geteuid()!=account.pw_uid or sys.version_info[:2]!=(3,11):raise PermissionError('private pinned speech identity required')
    resource.setrlimit(resource.RLIMIT_CPU,(45,45));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))
    raw=sys.stdin.buffer.read(MAX_FRAME+1)
    if len(raw)>MAX_FRAME:raise SpeechRefused('voice frame exceeds bound')
    data=request_bytes(json.loads(raw))
    # Native diagnostics stay out of the RPC reply; there are no credentials here.
    import logging
    logging.disable(logging.CRITICAL)
    result=transcribe(data)
    sys.stdout.write(json.dumps({'ok':True,'result':result})+'\n');sys.stdout.flush()


async def kill(process):
    if process.returncode is None:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    await process.wait()


async def invoke(request):
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
        'HOME':'/var/lib/haos-speech','HERMES_HOME':'/etc/haos-speech',
        'PYTHONPATH':os.environ.get('PYTHONPATH','/usr/lib/haos:/usr/lib/haos/hermes'),'PYTHONSAFEPATH':'1',
        'HERMES_SAFE_MODE':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'1'}
    spawning=asyncio.create_task(asyncio.create_subprocess_exec(sys.executable,'-s','-m','haos.speech_service','--worker',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        env=env,start_new_session=True,limit=MAX_REPLY+1))
    try:process=await asyncio.shield(spawning)
    except asyncio.CancelledError:
        process=await spawning
        await kill(process)
        raise
    async def write():
        process.stdin.write(json.dumps(request).encode());await process.stdin.drain()
        process.stdin.close();await process.stdin.wait_closed()
    async def bounded(stream,limit):
        data=await stream.read(limit+1)
        # A short read is not EOF. Keep draining until EOF or the strict limit.
        while len(data)<=limit:
            part=await stream.read(limit+1-len(data))
            if not part:break
            data+=part
        if len(data)>limit:raise SpeechRefused('local speech worker output exceeds bound')
        return data
    tasks=[]
    try:
        async with asyncio.timeout(60):
            tasks=[asyncio.create_task(write()),asyncio.create_task(bounded(process.stdout,MAX_REPLY)),
                asyncio.create_task(bounded(process.stderr,16384))]
            values=await asyncio.gather(*tasks)
            if await process.wait()!=0:raise SpeechRefused('local speech worker refused audio')
            result=json.loads(values[1])
            if (not isinstance(result,dict) or set(result)!={'ok','result'} or result['ok'] is not True
                    or result['result'].get('source_sha256')!=request['sha256']):
                raise SpeechRefused('local speech worker receipt invalid')
            return result
    finally:
        await kill(process)
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)


class Server:
    def __init__(self,gateway_uid):
        if type(gateway_uid) is not int or gateway_uid<=0 or gateway_uid==os.geteuid():
            raise PermissionError('separate unprivileged speech and gateway identities required')
        self.gateway_uid=gateway_uid;self.slot=asyncio.Semaphore(1);self.pending=0

    async def client(self,reader,writer):
        work=None;disconnect=None;counted=False
        try:
            peer=writer.get_extra_info('socket')
            _pid,uid,_gid=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=self.gateway_uid:raise PermissionError('speech peer denied')
            if self.pending>=4:raise SpeechRefused('local speech queue full')
            self.pending+=1;counted=True
            raw=await asyncio.wait_for(reader.readline(),10)
            if len(raw)>MAX_FRAME or not raw.endswith(b'\n'):raise SpeechRefused('bounded voice frame required')
            request=json.loads(raw);request_bytes(request)
            await asyncio.wait_for(self.slot.acquire(),5)
            try:
                work=asyncio.create_task(invoke(request));disconnect=asyncio.create_task(reader.read(1))
                done,_=await asyncio.wait({work,disconnect},return_when=asyncio.FIRST_COMPLETED)
                if disconnect in done:raise SpeechRefused('voice caller disconnected or sent another frame')
                result=await work
            finally:
                if work and not work.done():work.cancel()
                if work:await asyncio.gather(work,return_exceptions=True)
                self.slot.release()
        except PermissionError:result={'ok':False,'error':'speech peer denied'}
        except (ValueError,KeyError,TimeoutError,ConnectionError,asyncio.LimitOverrunError):
            result={'ok':False,'error':'local voice unavailable; inspect input, model, duration and service status'}
        except Exception:result={'ok':False,'error':'local speech service unavailable'}
        finally:
            if disconnect:disconnect.cancel();await asyncio.gather(disconnect,return_exceptions=True)
            if counted:self.pending-=1
        try:
            writer.write(json.dumps(result).encode()+b'\n');await writer.drain()
        except ConnectionError:pass
        finally:
            writer.close()
            try:await writer.wait_closed()
            except ConnectionError:pass


async def serve():
    if (sys.version_info[:2]!=(3,11) or os.geteuid()==0 or os.geteuid()!=pwd.getpwnam('haos-speech').pw_uid
            or os.environ.get('LISTEN_PID')!=str(os.getpid()) or os.environ.get('LISTEN_FDS')!='1'):
        raise PermissionError('private socket-activated speech identity required')
    from pathlib import Path
    from .sandbox import trusted_json
    config=trusted_json(Path('/etc/haos/speech.json'))
    if (set(config)!={'version','enabled','model'} or type(config['version']) is not int
            or config['version']!=1 or config['enabled'] is not True or config['model']!='tiny'):
        raise PermissionError('explicit fixed local speech setup required')
    inherited=socket.socket(fileno=3)
    if (inherited.family!=socket.AF_UNIX or inherited.type&socket.SOCK_STREAM!=socket.SOCK_STREAM
            or inherited.getsockname()!='/run/haos-speech/voice.sock'):
        raise PermissionError('fixed private speech socket required')
    handler=Server(pwd.getpwnam('haos-gateway').pw_uid)
    async with await asyncio.start_unix_server(handler.client,sock=inherited,limit=MAX_FRAME+1) as server:
        await server.serve_forever()


if __name__=='__main__':
    try:
        if sys.argv[1:]==['--worker']:worker()
        elif sys.argv[1:]==[]:asyncio.run(serve())
        else:raise PermissionError('fixed speech invocation required')
    except Exception:
        # Neither vendor exception bodies nor audio/transcripts go to the journal.
        print('haos.speech.unavailable',file=sys.stderr);raise SystemExit(1)
