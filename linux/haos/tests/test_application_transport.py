import os
import socket
from pathlib import Path

import pytest

from haos.application_client import request
from haos.application_server import peer_controller,handle


def test_application_peer_identity_comes_from_the_actual_kernel_not_payload():
    first,second=socket.socketpair()
    try:
        if os.geteuid()>0:peer_controller(first,os.geteuid())
        for uid in (0,os.geteuid()+1,-1,True):
            with pytest.raises(PermissionError):peer_controller(first,uid)
    finally:first.close();second.close()


@pytest.mark.skipif(os.geteuid()==0,reason='actual unprivileged negative server identity')
def test_agent_owned_socket_cannot_impersonate_the_independent_root_server(tmp_path):
    path=tmp_path/'root.sock';listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        listener.bind(str(path));path.chmod(0o660)
        with pytest.raises(PermissionError):request({'method':'health'},path)
        first,second=socket.socketpair()
        try:
            with pytest.raises(PermissionError):handle(first,None,os.geteuid())
        finally:first.close();second.close()
    finally:listener.close()
