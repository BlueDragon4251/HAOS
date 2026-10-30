"""Closed private native reply subprocess; bounded pipes, lifetime and revocation."""
import asyncio
import json
import os
import re

from .gateway_dingtalk import credentials, authority
from .gateway_dingtalk_admission import finite
from .gateway_dingtalk_process import command
from .gateway_dingtalk_http import ERRORS as SDK_ERRORS
from .gateway_line_ingress import _object

from .gateway_dingtalk_reply_process import response


async def media_reply(value, connector, current, item):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity(); value = credentials(value); current(); identity = authority(connector, value)
    request = (json.dumps({'action': 'media-reply', 'connector': connector, 'credentials': value,
        'policy_sha256': identity, 'parent_pid': os.getpid(), 'media_reply': item}, ensure_ascii=False) + '\n').encode()
    if len(request) > 2097152:
        raise ValueError('bounded private DingTalk reply request required')
    process = None; tasks = []
    async def collect(stream):
        data = bytearray()
        while chunk := await stream.read(4096):
            data.extend(chunk)
            if len(data) > 16384:
                raise ValueError('bounded private DingTalk reply result exceeded')
        return bytes(data)
    async def feed():
        try:
            process.stdin.write(request); await process.stdin.drain()
        finally:
            process.stdin.close()
    try:
        async with asyncio.timeout(35):
            args = command(); args[-1] = 'haos.gateway_dingtalk_media_reply_worker'
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(*args, cwd='/usr/lib/haos',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=16384, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                    'PYTHONDONTWRITEBYTECODE': '1', 'HERMES_SAFE_MODE': '1'}))
            try:
                process = await asyncio.shield(spawn)
            except BaseException:
                process = await spawn; raise
            output = asyncio.create_task(collect(process.stdout)); errors = asyncio.create_task(collect(process.stderr))
            ended = asyncio.create_task(process.wait()); feeder = asyncio.create_task(feed())
            tasks = [output, errors, ended, feeder]
            while not ended.done():
                current(); authority(connector, value, identity)
                for task in (output, errors, feeder):
                    if task.done() and task.exception() is not None:
                        task.result()
                await asyncio.wait({ended}, timeout=.1)
            raw = await output; await errors; await feeder
            if ended.result() != 0:
                raise ConnectionError('private native DingTalk reply worker unavailable')
            current(); authority(connector, value, identity)
            return response(json.loads(raw, object_pairs_hook=_object, parse_constant=finite))
    finally:
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
