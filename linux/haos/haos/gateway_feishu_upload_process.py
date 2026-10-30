"""Bounded binary pipe to one fixed private SDK upload worker."""
import asyncio
import hashlib
import json
import os

from .gateway_feishu import credentials,authority
from .gateway_feishu_process import command
from .gateway_feishu_upload_http import target
from .gateway_feishu_upload import response
from .gateway_line_ingress import _object


async def upload(value,connector,current,item,data):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value,verify_tls=False);current();identity=authority(connector,value)
    if not isinstance(item,dict) or not isinstance(item.get('output'),dict):raise ValueError('exact private upload intent required')
    output=target({key:part for key,part in item['output'].items() if key!='id'})
    if not isinstance(data,bytes) or len(data)!=output['size'] or hashlib.sha256(data).hexdigest()!=output['sha256']:
        raise ValueError('sealed output bytes and current offer must agree')
    header=(json.dumps({'connector':connector,'credentials':value,'policy_sha256':identity,
        'parent_pid':os.getpid(),'upload':item},separators=(',',':'))+'\n').encode()
    if len(header)>2097152:raise ValueError('bounded private upload header required')
    process=None;tasks=[]
    async def collect(stream):
        result=bytearray()
        while chunk:=await stream.read(4096):
            result.extend(chunk)
            if len(result)>16384:raise ValueError('bounded private upload result exceeded')
        return bytes(result)
    async def feed():
        try:
            process.stdin.write(header);await process.stdin.drain()
            for offset in range(0,len(data),65536):
                current();authority(connector,value,identity)
                process.stdin.write(data[offset:offset+65536]);await process.stdin.drain()
        finally:process.stdin.close()
    try:
        async with asyncio.timeout(35):
            args=command();args[-1]='haos.gateway_feishu_upload_worker'
            spawn=asyncio.create_task(asyncio.create_subprocess_exec(*args,cwd='/usr/lib/haos',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=16384,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'}))
            try:process=await asyncio.shield(spawn)
            except BaseException:process=await spawn;raise
            stdout=asyncio.create_task(collect(process.stdout));stderr=asyncio.create_task(collect(process.stderr))
            ended=asyncio.create_task(process.wait());feeder=asyncio.create_task(feed());tasks=[stdout,stderr,ended,feeder]
            while not ended.done():
                current();authority(connector,value,identity)
                for task in [stdout,stderr,feeder]:
                    if task.done() and task.exception() is not None:task.result()
                await asyncio.wait({ended},timeout=.1)
            raw=await stdout;await stderr;await feeder
            if ended.result()!=0:raise ConnectionError('private upload worker unavailable')
            current();authority(connector,value,identity)
            return response(json.loads(raw,object_pairs_hook=_object),output)
    finally:
        if process is not None:
            if process.returncode is None:
                try:process.kill()
                except ProcessLookupError:pass
            await process.wait()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
