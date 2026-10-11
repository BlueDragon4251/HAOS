"""Controller-only bounded transport to the independent root application authority."""
import json
import os
from pathlib import Path
import socket
import stat
import struct

from .applications import unique_object

SOCKET=Path('/run/haos-applications-control/control.sock')


def request(value,path=SOCKET):
    if not isinstance(value,dict):raise ValueError('application authority request required')
    encoded=json.dumps(value,ensure_ascii=False).encode()+b'\n'
    if len(encoded)>8192:raise ValueError('application authority frame exceeds its budget')
    path=Path(path);info=path.lstat();parent=path.parent.lstat()
    if (path.resolve()!=path or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=0
            or stat.S_IMODE(info.st_mode)!=0o660 or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid!=0 or parent.st_mode&0o022):
        raise PermissionError('system-owned independent application socket required')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
        peer.settimeout(12);peer.connect(str(path))
        _,uid,_=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=0:raise PermissionError('independent application server kernel identity required')
        peer.sendall(encoded);data=bytearray()
        while b'\n' not in data:
            part=peer.recv(65536)
            if not part or len(data)+len(part)>1500000:raise ValueError('application authority reply exceeds its budget')
            data.extend(part)
    frame,rest=data.split(b'\n',1)
    if rest:raise ValueError('multiple application authority replies denied')
    reply=json.loads(frame,object_pairs_hook=unique_object)
    if not isinstance(reply,dict) or set(reply)!={'ok','result'} or reply['ok'] is not True:
        raise PermissionError('application authority denied or unavailable; reconcile action before retrying')
    return reply['result']
