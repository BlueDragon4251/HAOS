"""Unprivileged TLS observer; keys only via root's systemd credential delivery."""
import asyncio
import os
from pathlib import Path
import signal

from .credentials import private_credential
from .remote_control import request
from .remote_http import Viewer,tls_context
from .remote_policy import load


async def serve():
    policy=load()
    credentials=Path(os.environ['CREDENTIALS_DIRECTORY'])
    paths=[credentials/name for name in ('server-cert','server-key','client-ca')]
    for path in paths:private_credential(path)
    context=tls_context(*map(str,paths))
    viewer=Viewer(load,request);stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
    server=await asyncio.start_server(viewer.client,policy.value['bind'],policy.value['port'],ssl=context,
        ssl_handshake_timeout=3,ssl_shutdown_timeout=1,limit=8192,backlog=16)
    async with server:await stop.wait()


if __name__=='__main__':asyncio.run(serve())
