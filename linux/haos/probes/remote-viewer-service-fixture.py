"""Run the production TLS server under real PID-1 hardening with fixture paths."""
import asyncio
from functools import partial
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parent))
from haos import remote_server
from haos.remote_control import request
from haos.remote_policy import RemotePolicy
from haos.sandbox import trusted_json

if os.geteuid()==0 or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('HAOS_DISPOSABLE_CI')!='1':
    raise PermissionError('separate actual unprivileged disposable viewer unit required')
config=trusted_json(Path(sys.argv[1]))
if os.geteuid()!=config['viewer_uid']:raise PermissionError('actual separate viewer UID required')
# Only root-owned disposable paths differ. TLS/credential validation, request
# handling, fresh scope checks and kernel Unix authentication are production code.
remote_server.load=lambda:RemotePolicy(trusted_json(Path(config['policy'])))
remote_server.request=partial(request,path=config['socket'],controller_uid=config['controller_uid'])
try:asyncio.run(remote_server.serve())
except Exception as error:
    print(json.dumps({'event':'remote.fixture.failed','error':type(error).__name__}),flush=True)
    raise SystemExit(1)
