"""Unprivileged persistent real GUI queue fixture, not a model/provider emulator."""
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0,sys.argv[1])
from haos.store import MissionStore
from haos.controller import Controller

if os.geteuid()==0 or os.environ.get('HAOS_DISPOSABLE_CI')!='1':
    raise PermissionError('separate disposable controller identity required')
path=Path(sys.argv[2]);store=MissionStore(path);path.chmod(0o600)
row=store.create('offline-fixture','application-pipeline','providerless real application pipeline fixture')
store.claim();store.session(row['id'],'offline-session','offline-stored');store.dispatching(row['id'])
controller=Controller(store,'ws://offline.invalid',set());controller.current=row['id']
print(json.dumps({'mission':row['id']}),flush=True)
try:
    for line in sys.stdin:
        value=json.loads(line)
        if value['method']=='submit':
            controller.gui.application_seen_at=time.time()
            result=controller.gui.submit(row['id'],{'session':'offline-session','id':value['id'],'action':value['action']})
            result={'admission':result,'dispatch':controller.gui.application_poll(row['id'])}
        elif value['method']=='ack':result=controller.gui.application_acknowledge(value['id'],result=value['result'])
        elif value['method']=='reattach':result=controller.gui.attach({'epoch':str(uuid.uuid4())})
        elif value['method']=='result':result=controller.gui.result(row['id'],{'session':'offline-session','id':value['id']})
        elif value['method']=='cancel':result=store.request_cancel(row['id'],'offline-fixture')
        elif value['method']=='audit':
            result={'events':store.events(row['id']),'action_count':store.db.execute('SELECT COUNT(*) FROM gui_actions').fetchone()[0]}
        else:raise PermissionError('closed fixture command required')
        print(json.dumps(result),flush=True)
finally:store.close()
