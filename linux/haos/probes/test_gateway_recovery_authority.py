"""Real Unix UID/SQLite recovery in private fixtures; no transport is contacted."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.gateway import GatewayEngine, GatewayPolicy
from haos.store import MissionStore
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor


@pytest.fixture
def uid_fixture_path():
    assert os.geteuid() == 0, "run this explicit UID fixture as root"
    # Pytest's own /tmp/pytest-of-root ancestors are private. Expose only this
    # separately created fixture tree to its deliberately demoted child.
    with tempfile.TemporaryDirectory(prefix="haos-gateway-uid-", dir="/tmp") as directory:
        yield Path(directory)


@pytest.mark.parametrize('decision',['retry','discard'])
def test_native_ingress_recovery_uses_actual_private_gateway_uid(uid_fixture_path,decision):
    root=uid_fixture_path; root.chmod(0o755)
    modules=root/'modules'; modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700)
    database=state/'native.db'
    config={'version':1,'connectors':[{'id':'bot','platform':'discord'}],'bindings':[
        {'id':'paired','connector':'bot','sender':'42','chat':'123','scope':'999','thread':'',
         'identity':'principal','capabilities':['create','read'],'generation':'a'*64}]}
    inbox=NativeInbox(database,Redactor())
    key=inbox.admit(GatewayPolicy(config),'bot',{'platform':'discord','sender':'42','chat':'123',
        'scope':'999','thread':'','message_id':'101','is_bot':False,'text':'private incoming fixture'},
        {'content':'private incoming fixture'})
    inbox.db.execute("UPDATE native_inbox SET state='failed',attempt=8")
    inbox.close()
    os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    canary=root/'owner-secret';canary.write_text('root-only-disposable-canary');canary.chmod(0o600)
    payload={'path':str(database),'canary':str(canary),'policy':config,'request':{
        'ingress_id':key,'attempt':8,'state':'failed','decision':decision,'owner_uid':1000,'note_sha256':'b'*64}}
    code='''
import json,os,sys
from pathlib import Path
from haos.gateway import GatewayPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import reconcile,unresolved
from haos.redaction import Redactor
d=json.load(sys.stdin)
assert os.geteuid()==65534 and os.getegid()==65534 and os.getgroups()==[]
try: Path(d['canary']).read_bytes()
except PermissionError: pass
else: raise AssertionError('gateway UID read owner secret')
inbox=NativeInbox(Path(d['path']),Redactor())
try:
    assert len(unresolved(inbox)['ingress'])==1
    result=reconcile(inbox,GatewayPolicy(d['policy']),d['request'])
    row=inbox.db.execute('SELECT payload FROM native_inbox').fetchone()
    assert json.loads(row[0])['content']=='private incoming fixture'
    event=inbox.db.execute('SELECT owner_uid,decision FROM native_owner_events').fetchone()
    assert tuple(event)==(1000,d['request']['decision'])
finally: inbox.close()
print(json.dumps({'uid':os.geteuid(),'owner_secret_denied':True,'result':result}))
'''
    completed=subprocess.run([sys.executable,'-c',code],input=json.dumps(payload),text=True,capture_output=True,
        timeout=15,user=65534,group=65534,extra_groups=[],umask=0o077,cwd=root,
        env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(modules),'PYTHONDONTWRITEBYTECODE':'1'})
    assert completed.returncode==0,'actual unprivileged native ingress recovery failed'
    report=json.loads(completed.stdout)
    assert report['uid']==65534 and report['owner_secret_denied']
    assert report['result']['state']==('pending' if decision=='retry' else 'discarded')
    assert 'root-only-disposable-canary' not in completed.stdout+completed.stderr


@pytest.mark.parametrize("decision", ["retry", "delivered", "discard"])
def test_outbox_recovery_runs_as_real_unprivileged_ledger_uid(uid_fixture_path, decision):
    tmp_path = uid_fixture_path
    assert os.geteuid() == 0, "run this explicit UID fixture as root"
    tmp_path.chmod(0o755)
    modules = tmp_path / "modules"
    modules.mkdir(mode=0o755)
    source = Path(__file__).resolve().parents[1] / "haos"
    shutil.copytree(source, modules / "haos", ignore=shutil.ignore_patterns("__pycache__"))
    for path in (modules / "haos").rglob("*.py"):
        path.chmod(0o644)
    (modules / "haos").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "missions.db"
    store = MissionStore(path)
    config = {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}],
              "bindings": [{"id": "device", "connector": "first", "sender": "42", "chat": "42", "scope": "",
                            "thread": "", "identity": "principal", "capabilities": ["create", "read"]}]}
    policy = GatewayPolicy(config)
    engine = GatewayEngine(store)
    mission = asyncio.run(engine.receive(policy, "first", {"platform": "telegram", "sender": "42", "chat": "42",
        "scope": "", "thread": "", "message_id": "1", "is_bot": False, "text": "Local UID fixture"}, None))
    delivery = engine.next_delivery(policy)
    engine.acknowledge(policy, delivery["id"], {"attempt": 1, "status": "uncertain"})
    store.close()
    os.chown(state, 65534, 65534)
    for item in state.iterdir():
        item.chmod(0o600)
        os.chown(item, 65534, 65534)
    canary = tmp_path / "owner-secret"
    canary.write_text("private-disposable-canary")
    canary.chmod(0o600)
    payload = {"path": str(path), "canary": str(canary), "policy": config,
               "request": {"delivery_id": delivery["id"], "attempt": 1, "decision": decision, "owner_uid": 1000,
                           "note_sha256": "a" * 64, "receipt": "42" if decision == "delivered" else None,
                           "confirmed_not_delivered": decision == "retry"}}
    code = '''
import json,os,sys
from pathlib import Path
from haos.gateway import GatewayPolicy
from haos.gateway_recovery import private_store,reconcile,unresolved
d=json.load(sys.stdin)
assert os.geteuid()==65534 and os.getegid()==65534 and os.getgroups()==[]
try:
    Path(d['canary']).read_bytes()
except PermissionError:
    secret_denied=True
else:
    raise AssertionError('owner canary was readable')
store=private_store(Path(d['path']))
try:
    assert len(unresolved(store)['deliveries'])==1
    result=reconcile(store,GatewayPolicy(d['policy']),d['request'])
finally:
    store.close()
print(json.dumps({'actual_uid':os.geteuid(),'owner_secret_denied':secret_denied,'result':result}))
'''
    completed = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), text=True,
                               capture_output=True, timeout=15, user=65534, group=65534, extra_groups=[], umask=0o077,
                               cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(modules), "PYTHONDONTWRITEBYTECODE": "1"})
    assert completed.returncode == 0, "actual unprivileged recovery failed"
    report = json.loads(completed.stdout)
    assert report["actual_uid"] == 65534 and report["owner_secret_denied"]
    assert report["result"]["state"] == {"retry": "pending", "delivered": "delivered", "discard": "revoked"}[decision]
    assert "private-disposable-canary" not in completed.stdout + completed.stderr
    store = MissionStore(path)
    try:
        assert store.get(mission["mission_id"])["attempt"] == 0
        event = next(e for e in store.events(mission["mission_id"]) if e["kind"] == "owner.gateway-reconciled")
        assert event["payload"]["actor"] == "owner:1000"
        assert store.db.execute("SELECT attempt FROM gateway_outbox").fetchone()[0] == 1
    finally:
        store.close()
