"""Root authorizer for the existing GUI stack, never a general desktop bridge."""
import json
import os
from pathlib import Path
import pwd
import select
import signal
import socket
import struct
import subprocess

from .application_authority import ApplicationAuthority,ActionNonces
from .application_launcher import ApplicationLauncher
from .applications import unique_object
from .enrollment import protected_directory


def peer_controller(peer,uid):
    _,actual_uid,_=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    if type(uid) is not int or uid<=0 or actual_uid!=uid:
        raise PermissionError('separate mission controller kernel identity required')


def handle(peer,authority,uid):
    ActionNonces.require_root()
    peer_controller(peer,uid)
    peer.settimeout(1);data=bytearray()
    while b'\n' not in data:
        part=peer.recv(1024)
        if not part or len(data)+len(part)>8192:raise ValueError('application request budget exceeded')
        data.extend(part)
    frame,rest=data.split(b'\n',1)
    if rest:raise PermissionError('multiple application frames denied')
    value=json.loads(frame,object_pairs_hook=unique_object)
    if value=={'method':'health'}:
        result={'available':True,'isolation':'private-wayland-rootfs-network','external_network':False}
    else:result=authority.dispatch(value)
    reply=json.dumps({'ok':True,'result':result}).encode()+b'\n'
    if len(reply)>1500000:raise ValueError('application reply budget exceeded')
    peer.settimeout(2);peer.sendall(reply)


def controller_alive():
    result=subprocess.run(['/usr/bin/systemctl','is-active','--quiet','haos-controller.service'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    return result.returncode==0


def main():
    ActionNonces.require_root()
    if os.environ.get('LISTEN_PID')!=str(os.getpid()) or os.environ.get('LISTEN_FDS')!='1':
        raise PermissionError('system-owned application socket activation required')
    listener=socket.socket(fileno=3)
    if listener.family!=socket.AF_UNIX or listener.getsockname()!='/run/haos-applications-control/control.sock':
        raise PermissionError('unexpected independent application listener')
    account=pwd.getpwnam('haos-control')
    base=Path('/var/lib/haos-applications');protected_directory(base)
    launcher=ApplicationLauncher(state=base/'instances')
    nonces=ActionNonces(base/'actions.db')
    authority=ApplicationAuthority(launcher,nonces,Path('/var/lib/haos-control/missions.db'),account.pw_uid)
    stop=False
    def finish(_signal,_frame):
        nonlocal stop
        stop=True
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,finish)
    try:
        authority.reconcile(restart=True)
        while not stop:
            # Runs even with Herald disconnected, without waiting on the model.
            authority.reconcile(restart=not controller_alive())
            ready,_,_=select.select([listener],[],[],0.5)
            if not ready:continue
            peer,_=listener.accept()
            with peer:
                try:handle(peer,authority,account.pw_uid)
                except Exception as exc:
                    # Only a fixed error class, never caller input/credentials,
                    # app stderr, titles, pixels or paths in the journal/reply.
                    print(json.dumps({'event':'application.denied','reason':type(exc).__name__}),flush=True)
                    try:peer.sendall(b'{"ok":false,"result":null}\n')
                    except OSError:pass
    finally:
        authority.reconcile(restart=True)
        nonces.close();listener.close()


if __name__=='__main__':main()
