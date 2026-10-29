"""Private continuous SDK worker with durable parent receipts and bounded shutdown."""
import asyncio
import base64
import hashlib
import json
import os
import re

from .gateway_dingtalk import credentials,authority
from .gateway_dingtalk_admission import MAX_EVENT,finite
from .gateway_dingtalk_process import command,ERRORS
from .gateway_line_ingress import _object


def event(value,expected):
    if (not isinstance(value,dict) or set(value)!={'kind','seq','payload_base64','sha256'}
            or value['kind']!='event' or type(value['seq']) is not int or value['seq']!=expected
            or not isinstance(value['payload_base64'],str) or len(value['payload_base64'])>4*((MAX_EVENT+2)//3)
            or not isinstance(value['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['sha256'])):
        raise ValueError('exact sequential private event required')
    raw=base64.b64decode(value['payload_base64'],validate=True)
    if (not 1<=len(raw)<=MAX_EVENT or base64.b64encode(raw).decode()!=value['payload_base64']
            or hashlib.sha256(raw).hexdigest()!=value['sha256']):
        raise ValueError('canonical private event bytes required')
    return raw


class Session:
    def __init__(self,value,connector,current,capture):
        if not callable(current) or not callable(capture):raise PermissionError('independent parent admission required')
        self.value=credentials(value)
        self.connector=connector;self.current=current;self.capture=capture
        self.process=None;self.tasks=[];self.active=False;self.ready=None;self.failure=None

    def check(self):
        if not self.active:raise PermissionError('private WS generation inactive')
        self.current();authority(self.connector,self.value,self.identity)

    async def start(self):
        from .gateway_runtime import require_runtime_identity
        require_runtime_identity()
        if self.process is not None:raise PermissionError('private WS session cannot be reused')
        self.current();self.identity=authority(self.connector,self.value);self.active=True
        self.ready=asyncio.get_running_loop().create_future()
        request=(json.dumps({'connector':self.connector,'credentials':self.value,
            'policy_sha256':self.identity,'parent_pid':os.getpid()},separators=(',',':'))+'\n').encode()
        if len(request)>32768:raise ValueError('bounded private WS startup required')
        try:
            args=command();args[-1]='haos.gateway_dingtalk_ws_worker'
            spawn=asyncio.create_task(asyncio.create_subprocess_exec(*args,cwd='/usr/lib/haos',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                limit=2*MAX_EVENT,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
                    'PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'}))
            try:self.process=await asyncio.shield(spawn)
            except BaseException:self.process=await spawn;raise
            self.process.stdin.write(request);await self.process.stdin.drain()
            self.tasks=[asyncio.create_task(self.read()),asyncio.create_task(self.discard()),asyncio.create_task(self.watch())]
            await asyncio.wait_for(asyncio.shield(self.ready),45)
            self.check()
        except BaseException:
            await self.close();raise
        return self

    async def read(self):
        sequence=1
        try:
            while self.active:
                raw=await self.process.stdout.readline()
                if not raw or len(raw)>2*MAX_EVENT or not raw.endswith(b'\n'):
                    raise ConnectionError('bounded private WS protocol ended')
                value=json.loads(raw,object_pairs_hook=_object,parse_constant=finite);self.check()
                if value=={'kind':'ready'}:
                    if self.ready.done():raise ValueError('duplicate private WS readiness')
                    self.ready.set_result(True);continue
                if isinstance(value,dict) and set(value)=={'kind','error'} and value['kind']=='stopped':
                    if not isinstance(value['error'],str) or value['error'] not in ERRORS:raise ValueError('finite private WS failure required')
                    self.failure=value['error'];break
                if not self.ready.done():raise PermissionError('private event before verified connection')
                payload=event(value,sequence);sequence+=1
                try:
                    self.check();receipt=self.capture(payload);self.check()
                    if not isinstance(receipt,str) or not re.fullmatch('[0-9a-f]{64}',receipt):
                        raise PermissionError('explicit durable parent receipt required')
                    reply={'seq':value['seq'],'receipt':receipt}
                except Exception:
                    reply={'seq':value['seq'],'refused':True}
                self.check();self.process.stdin.write((json.dumps(reply,separators=(',',':'))+'\n').encode())
                await self.process.stdin.drain()
        except asyncio.CancelledError:raise
        except Exception:self.failure='authority-or-protocol-refused'
        finally:
            self.active=False
            if not self.ready.done():self.ready.set_exception(ConnectionError('private WS startup refused'))
            if self.process.returncode is None:
                try:self.process.kill()
                except ProcessLookupError:pass

    async def discard(self):
        # Never retain or forward SDK stderr (including tickets or event bodies).
        while await self.process.stderr.read(4096):pass

    async def watch(self):
        try:
            while self.active and self.process.returncode is None:
                self.check();await asyncio.sleep(.1)
        except asyncio.CancelledError:raise
        except Exception:self.failure='authority-or-protocol-refused'
        finally:
            self.active=False
            if self.process.returncode is None:
                try:self.process.kill()
                except ProcessLookupError:pass
            await self.process.wait()

    async def close(self):
        self.active=False
        if self.process is not None:
            if self.process.returncode is None:
                try:
                    self.process.stdin.write(b'{"stop":true}\n');await self.process.stdin.drain()
                    self.process.stdin.close()
                    await asyncio.wait_for(self.process.wait(),2)
                except (Exception,asyncio.CancelledError):
                    if self.process.returncode is None:
                        try:self.process.kill()
                        except ProcessLookupError:pass
            await self.process.wait()
        for task in self.tasks:
            if not task.done():task.cancel()
        if self.tasks:await asyncio.gather(*self.tasks,return_exceptions=True)
        if self.ready is not None and self.ready.done() and not self.ready.cancelled():self.ready.exception()
