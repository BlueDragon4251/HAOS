"""Controller/gateway local speech capability: bounded bytes, never caller paths."""
import asyncio
import base64
import grp
import hashlib
import json
from pathlib import Path
import pwd
import socket
import stat
import struct

from .speech import MAX_AUDIO_BYTES,MAX_SAMPLES,MAX_TRANSCRIPT,SpeechRefused
from .speech_model import REVISION

SOCKET=Path('/run/haos-speech/voice.sock')


def result(value,source):
    if (not isinstance(value,dict) or set(value)!={'transcript','source_sha256','samples','sample_rate','model_revision','provider'}
            or value['source_sha256']!=source or value['model_revision']!=REVISION or value['provider']!='local'
            or type(value['samples']) is not int or not 1<=value['samples']<=MAX_SAMPLES
            or type(value['sample_rate']) is not int or value['sample_rate']!=16000
            or not isinstance(value['transcript'],str) or not 1<=len(value['transcript'].strip())<=MAX_TRANSCRIPT
            or '\x00' in value['transcript']):
        raise SpeechRefused('local speech receipt does not match reviewed audio/model bounds')
    value['transcript'].encode('utf-8')
    return dict(value)


def trusted_endpoint(path=SOCKET):
    directory=path.parent.lstat();info=path.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid!=0 or directory.st_mode&0o022
            or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1
            or info.st_gid!=grp.getgrnam('haos-gateway').gr_gid or info.st_mode&0o007 or info.st_mode&0o110):
        raise PermissionError('fixed root-bound private speech socket required')


async def transcribe(data,current):
    return await _exchange(data,current)


async def opus(data,current):
    return await _exchange(data,current,operation='opus')


async def amr(data,current):
    return await _exchange(data,current,operation='amr')


async def thumbnail(data,current):
    return await _exchange(data,current,operation='thumbnail')


async def _exchange(data,current,operation=None):
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_AUDIO_BYTES or not callable(current):
        raise SpeechRefused('bounded approved audio bytes required')
    from .audio_opus import MAX_REPLY as OPUS_REPLY
    from .media_thumbnail import MAX_REPLY as THUMBNAIL_REPLY
    reply_limit=THUMBNAIL_REPLY if operation=='thumbnail' else OPUS_REPLY if operation in {'opus','amr'} else 96*1024
    current();trusted_endpoint()
    checksum=hashlib.sha256(data).hexdigest()
    async def exchange():
        reader,writer=await asyncio.open_unix_connection(str(SOCKET),limit=reply_limit+1)
        try:
            peer=writer.get_extra_info('socket')
            _pid,uid,_gid=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            # A socket activated by PID1 retains its root creator credentials.
            # The root-owned, nonreplaceable filesystem endpoint is required too.
            if uid not in {0,pwd.getpwnam('haos-speech').pw_uid}:raise PermissionError('untrusted speech endpoint identity')
            current()
            request={'data':base64.b64encode(data).decode(),'sha256':checksum}
            if operation is not None:request['operation']=operation
            writer.write(json.dumps(request).encode()+b'\n')
            await writer.drain();raw=await reader.readline()
            if not raw.endswith(b'\n') or len(raw)>reply_limit:raise SpeechRefused('bounded local speech receipt required')
            reply=json.loads(raw)
            if not isinstance(reply,dict) or set(reply)!={'ok','result'} or reply['ok'] is not True:
                raise SpeechRefused('local transcription unavailable; inspect local model and service status')
            if operation=='opus':
                from .audio_opus import result as encoded_result
                return encoded_result(reply['result'],checksum)
            if operation=='amr':
                from .audio_amr import result as encoded_result
                return encoded_result(reply['result'],checksum)
            if operation=='thumbnail':
                from .media_thumbnail import result as preview_result
                return preview_result(reply['result'],checksum)
            return result(reply['result'],checksum)
        finally:
            writer.close()
            try:await writer.wait_closed()
            except ConnectionError:pass
    task=asyncio.create_task(exchange())
    try:
        async with asyncio.timeout(65):
            while not task.done():
                current()
                await asyncio.wait({task},timeout=.1)
            current()
            return await task
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
