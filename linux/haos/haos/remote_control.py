"""Separate kernel-authenticated observation socket; no general control rights."""
import asyncio
import json
import os
import socket
import struct
import time

from .applications import unique_object
from .remote_policy import mission_id

SOCKET='/run/haos-viewer-control/viewer.sock'
REPLY_LIMIT=6*1024*1024
METHODS={'missions.list','missions.get','missions.events','applications.snapshot'}
PUBLIC={'id','state','created_at','updated_at','attempts','timeout_seconds','cancel_requested'}


def project_mission(row,device):
    return row if device['content'] else {k:v for k,v in row.items() if k in PUBLIC}


def observe(controller,request):
    if not isinstance(request,dict) or set(request)!={'method','device','params'} or request['method'] not in METHODS or not isinstance(request['params'],dict):
        raise PermissionError('read-only remote capability required')
    policy=controller.remote_policy();params=request['params'];method=request['method']
    device=policy.authorize(request['device'])
    if method=='missions.list':
        if params:raise PermissionError('remote listing parameters denied')
        result=[]
        for mid in device['missions']:
            try:result.append(project_mission(controller.store.get(mid),device))
            except KeyError:pass
        return result
    if set(params)!=({'id','after'} if method=='missions.events' else {'id'}):
        raise PermissionError('closed remote mission request required')
    mid=mission_id(params['id']);policy.authorize(request['device'],mid)
    row=controller.store.get(mid)
    if method=='missions.get':result=project_mission(row,device)
    elif method=='missions.events':
        after=params['after']
        if type(after) is not int or not 0<=after<2**63:raise ValueError('bounded event cursor required')
        result=controller.store.events(mid,after)
        if not device['content']:result=[{k:v for k,v in event.items() if k!='payload'} for event in result]
    else:
        if not device['screenshots']:raise PermissionError('owner has not shared application captures')
        result=controller.gui.application_snapshot(mid)
    # Viewing is itself attributable, without copying goals, pixels or tokens.
    key=(device['id'],mid,method);now=time.time()
    if now-controller.remote_observed.get(key,0)>=600:
        if len(controller.remote_observed)>=4096:controller.remote_observed.clear()
        controller.store._event(mid,'remote.observed',{'device':device['id'],'method':method})
        controller.remote_observed[key]=now
    return result


async def client(controller,reader,writer):
    try:
        _,uid,_=struct.unpack('3i',writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if controller.viewer_uid is None or uid!=controller.viewer_uid:
            raise PermissionError('separate remote viewer kernel identity required')
        line=await asyncio.wait_for(reader.readline(),3)
        if not line.endswith(b'\n') or len(line)>8192:raise PermissionError('bounded observation frame required')
        result=observe(controller,json.loads(line,object_pairs_hook=unique_object))
        reply=json.dumps({'ok':True,'result':result}).encode()+b'\n'
        if len(reply)>REPLY_LIMIT:raise ValueError('remote observation exceeds bandwidth bound')
    except Exception:
        reply=b'{"ok":false,"result":null}\n'
    try:
        writer.write(reply);await asyncio.wait_for(writer.drain(),3)
    finally:
        writer.close();await writer.wait_closed()


async def request(value,*,path=SOCKET,controller_uid=None):
    if controller_uid is None:
        import pwd
        controller_uid=pwd.getpwnam('haos-control').pw_uid
    # Mode/ownership alone never authenticate the listener. Actual kernel
    # server UID is checked before any mission/device identifiers are sent.
    reader,writer=await asyncio.wait_for(asyncio.open_unix_connection(path,limit=REPLY_LIMIT),3)
    try:
        _,uid,_=struct.unpack('3i',writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=controller_uid or uid==0:raise PermissionError('actual unprivileged controller required')
        data=json.dumps(value).encode()+b'\n'
        if len(data)>8192:raise ValueError('bounded remote control frame required')
        writer.write(data);await asyncio.wait_for(writer.drain(),3)
        line=await asyncio.wait_for(reader.readline(),3)
        if not line.endswith(b'\n') or len(line)>REPLY_LIMIT:raise ValueError('bounded observation reply required')
        reply=json.loads(line,object_pairs_hook=unique_object)
        if set(reply)!={'ok','result'} or reply['ok'] is not True:raise PermissionError('remote observation denied')
        return reply['result']
    finally:
        writer.close();await writer.wait_closed()
