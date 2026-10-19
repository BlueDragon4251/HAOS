"""Actual async controller/GUI ledger and observation socket in disposable CI."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0,sys.argv[1])
from haos.controller import Controller
from haos.remote_control import client
from haos.remote_policy import RemotePolicy
from haos.sandbox import trusted_json
from haos.store import MissionStore


async def main():
    if os.geteuid()==0 or os.environ.get('HAOS_DISPOSABLE_CI')!='1':raise PermissionError('unprivileged disposable controller required')
    config=trusted_json(Path(sys.argv[3]));path=Path(sys.argv[2]);store=MissionStore(path);path.chmod(0o600)
    row=store.create('offline-fixture','remote-application','Actual providerless remote application fixture')
    foreign=store.create('offline-fixture','private-mission','Unshared private fixture mission')
    store.claim();store.session(row['id'],'offline-session','offline-stored');store.dispatching(row['id'])
    controller=Controller(store,'ws://offline.invalid',set());controller.current=row['id']
    controller.viewer_uid=config['viewer_uid'];controller.remote_policy=lambda:RemotePolicy(trusted_json(Path(config['policy'])))
    async def observe(reader,writer):await client(controller,reader,writer)
    server=await asyncio.start_unix_server(observe,path=config['socket'],limit=8192)
    os.chown(config['socket'],-1,config['viewer_gid']);os.chmod(config['socket'],0o660)
    reader=asyncio.StreamReader(limit=1500000)
    transport,_=await asyncio.get_running_loop().connect_read_pipe(lambda:asyncio.StreamReaderProtocol(reader),sys.stdin)
    print(json.dumps({'mission':row['id'],'foreign':foreign['id']}),flush=True)
    try:
        async with server:
            while line:=await reader.readline():
                value=json.loads(line)
                if value['method']=='submit':
                    controller.gui.application_seen_at=time.time()
                    admitted=controller.gui.submit(row['id'],{'session':'offline-session','id':value['id'],'action':value['action']})
                    result={'admission':admitted,'dispatch':controller.gui.application_poll(row['id'])}
                elif value['method']=='ack':result=controller.gui.application_acknowledge(value['id'],result=value['result'])
                elif value['method']=='cancel':result=store.request_cancel(row['id'],'offline-fixture')
                elif value['method']=='audit':result={'events':store.events(row['id'])}
                else:raise PermissionError('closed disposable fixture command required')
                print(json.dumps(result),flush=True)
    finally:transport.close();store.close()


if __name__=='__main__':asyncio.run(main())
