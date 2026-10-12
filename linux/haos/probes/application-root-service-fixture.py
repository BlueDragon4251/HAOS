"""Production authority under actual PID-1 hardening in a disposable CI unit."""
import json
import os
from pathlib import Path
import select
import signal
import socket
import sys

sys.path.insert(0,str(Path(__file__).parent))
if os.geteuid()==0:
    fields=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    print(json.dumps({'event':'root-fixture.entry-capabilities',
        'masks':{key:fields[key].strip() for key in ('CapEff','CapPrm','CapBnd','CapAmb')}}),flush=True)
from haos.application_authority import ApplicationAuthority,ActionNonces
from haos.application_launcher import ApplicationLauncher
from haos.application_server import handle
from haos.applications import ApplicationRegistry
from haos.sandbox import trusted_json

if (os.geteuid()!=0 or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('HAOS_DISPOSABLE_CI')!='1'
        or os.environ.get('LISTEN_PID')!=str(os.getpid()) or os.environ.get('LISTEN_FDS')!='1'):
    raise PermissionError('explicit actual socket-activated disposable root unit required')
config=trusted_json(Path(sys.argv[1]))
launcher=ApplicationLauncher(ApplicationRegistry(Path(config['registry'])),Path(config['state'])/'instances',
    Path(config['runtime']),Path(__file__).parent/'haos/application_session.py',guardian=config['guardian'])
nonces=ActionNonces(Path(config['state'])/'actions.db')
authority=ApplicationAuthority(launcher,nonces,Path(config['ledger']),config['controller_uid'])
listener=socket.socket(fileno=3)
if listener.getsockname()!=config['socket']:raise PermissionError('own fixture listener required')
stop=False
def finish(_signal,_frame):
    global stop
    stop=True
signal.signal(signal.SIGTERM,finish)
try:
    authority.reconcile(restart=True)
    while not stop:
        authority.reconcile()
        ready,_,_=select.select([listener],[],[],0.2)
        if not ready:continue
        peer,_=listener.accept()
        with peer:
            try:handle(peer,authority,config['controller_uid'])
            except Exception:
                try:peer.sendall(b'{"ok":false,"result":null}\n')
                except OSError:pass
finally:
    authority.reconcile(restart=True);nonces.close();listener.close()
