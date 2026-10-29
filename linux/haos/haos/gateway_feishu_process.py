"""Bounded private Feishu worker lifetime, without a generic HTTP or command interface."""
import asyncio
import json
import os
from pathlib import Path
import stat

from .gateway_feishu import credentials,authority,scope
from .gateway_line_ingress import _object

ERRORS=frozenset({'authority-or-protocol-refused','sdk-unavailable','tls-refused','transport-unavailable',
    'authentication-refused','identity-refused','rate-limited','server-refused','redirect-refused',
    'response-too-large','truncated-response','invalid-response','invalid-token'})


def command():
    root=Path('/usr/lib/haos');python=root/'hermes/.venv/bin/python'
    for path in [root,root/'haos',root/'hermes',root/'hermes/.venv',python.parent]:
        value=path.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid!=0 or value.st_mode&0o022:
            raise PermissionError('root-owned private Feishu runtime required')
    value=python.resolve(strict=True).lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_uid!=0 or value.st_mode&0o022:
        raise PermissionError('root-owned private Feishu interpreter required')
    return [str(python),'-E','-s','-m','haos.gateway_feishu_worker']


def response(result,value):
    if isinstance(result,dict) and set(result)=={'error'}:
        if not isinstance(result['error'],str) or result['error'] not in ERRORS:
            raise ValueError('finite private Feishu error required')
        return result
    if (not isinstance(result,dict) or set(result)!={'bot_identity_verified','tenant_identity_verified',
            'bot_open_id','account_scope','message_sent'} or result['bot_identity_verified'] is not True
            or result['tenant_identity_verified'] is not False or result['message_sent'] is not False
            or result['bot_open_id']!=value['bot_open_id'] or result['account_scope']!=scope(value)):
        raise ValueError('exact no-send private Feishu identity result required')
    return result


async def account(value,connector,current):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value,verify_tls=False);current();identity=authority(connector,value)
    request=(json.dumps({'action':'account','connector':connector,'credentials':value,
        'policy_sha256':identity,'parent_pid':os.getpid()},ensure_ascii=False)+'\n').encode()
    if len(request)>32768:raise ValueError('bounded private Feishu request required')
    process=None;tasks=[]
    async def collect(stream):
        data=bytearray()
        while chunk:=await stream.read(4096):
            data.extend(chunk)
            if len(data)>16384:raise ValueError('bounded private Feishu result exceeded')
        return bytes(data)
    async def feed():
        try:process.stdin.write(request);await process.stdin.drain()
        finally:process.stdin.close()
    try:
        async with asyncio.timeout(35):
            spawn=asyncio.create_task(asyncio.create_subprocess_exec(*command(),cwd='/usr/lib/haos',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=16384,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'}))
            try:process=await asyncio.shield(spawn)
            except BaseException:process=await spawn;raise
            output=asyncio.create_task(collect(process.stdout));errors=asyncio.create_task(collect(process.stderr))
            ended=asyncio.create_task(process.wait());feeder=asyncio.create_task(feed());tasks=[output,errors,ended,feeder]
            while not ended.done():
                current();authority(connector,value,identity)
                for task in [output,errors,feeder]:
                    if task.done() and task.exception() is not None:task.result()
                await asyncio.wait({ended},timeout=.1)
            raw=await output;await errors;await feeder
            if ended.result()!=0:raise ConnectionError('private Feishu account worker unavailable')
            current();authority(connector,value,identity)
            return response(json.loads(raw,object_pairs_hook=_object),value)
    finally:
        if process is not None:
            if process.returncode is None:
                try:process.kill()
                except ProcessLookupError:pass
            await process.wait()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
