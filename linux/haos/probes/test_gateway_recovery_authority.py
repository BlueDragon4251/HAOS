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
@pytest.mark.parametrize('platform',['discord','mattermost'])
def test_native_ingress_recovery_uses_actual_private_gateway_uid(uid_fixture_path,decision,platform):
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
    if platform=='mattermost':
        config['connectors'][0]['platform']='mattermost'
        config['bindings'][0].update(sender='u'*26,chat='c'*26,scope='s'*26)
    source=config['bindings'][0]
    inbox=NativeInbox(database,Redactor())
    key=inbox.admit(GatewayPolicy(config),'bot',{'platform':platform,'sender':source['sender'],'chat':source['chat'],
        'scope':source['scope'],'thread':'','message_id':'m'*26 if platform=='mattermost' else '101','is_bot':False,'text':'private incoming fixture'},
        {'content':'private incoming fixture'})
    if platform=='mattermost':
        from types import SimpleNamespace
        from haos.gateway_mattermost import transport_status
        transport_status(SimpleNamespace(_haos_native=SimpleNamespace(inbox=inbox,connector='bot')),'authentication-refused')
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
    metadata=unresolved(inbox)
    assert len(metadata['ingress'])==1
    if d['policy']['connectors'][0]['platform']=='mattermost':
        assert metadata['transport'][0]['status']=='authentication-refused'
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
@pytest.mark.parametrize('platform',['telegram','slack','mattermost'])
def test_outbox_recovery_runs_as_real_unprivileged_ledger_uid(uid_fixture_path, decision,platform):
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
    if platform=='slack':
        config['connectors'][0]['platform']='slack'
        config['bindings'][0].update(sender='U42',chat='D42',scope='T999')
    if platform=='mattermost':
        config['connectors'][0]['platform']='mattermost'
        config['bindings'][0].update(sender='u'*26,chat='c'*26,scope='s'*26)
    policy = GatewayPolicy(config)
    engine = GatewayEngine(store)
    source=config['bindings'][0]
    mission = asyncio.run(engine.receive(policy, "first", {"platform": platform,"sender":source['sender'],"chat":source['chat'],
        "scope":source['scope'],"thread":"","message_id":"1","is_bot":False,"text":"Local UID fixture"},None))
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
                           "note_sha256": "a" * 64, "receipt": ("1792800000.000042" if platform=='slack' else "m"*26 if platform=='mattermost' else "42") if decision == "delivered" else None,
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


def test_matrix_sync_journal_is_private_to_actual_gateway_uid_and_unreadable_to_agent(uid_fixture_path):
    from haos.gateway_matrix_sync import SyncJournal
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700);path=state/'sync.db'
    journal=SyncJournal(path,'a'*64)
    journal.capture({'next_batch':'retained','to_device':{'events':[]}}, {'fixture_snapshot_only':True})
    journal.close()
    os.chown(state,65534,65534)
    for file in state.iterdir():file.chmod(0o600);os.chown(file,65534,65534)
    canary=root/'owner-secret';canary.write_text('disposable-root-only-owner-canary');canary.chmod(0o600)
    code='''
import json,os,sys
from pathlib import Path
from haos.gateway_matrix_sync import SyncJournal
d=json.load(sys.stdin)
assert os.geteuid()==d['uid'] and os.getegid()==d['uid'] and os.getgroups()==[]
try: Path(d['canary']).read_bytes()
except PermissionError: pass
else: raise AssertionError('unprivileged identity could read owner data')
if d['uid']==65533:
    try: SyncJournal(d['path'],'a'*64)
    except PermissionError: pass
    else: raise AssertionError('agent identity opened private Matrix protocol data')
else:
    journal=SyncJournal(d['path'],'a'*64)
    try:
        assert journal.cursor=='retained'
        journal.capture({'next_batch':'next','to_device':{'events':[]}}, {},from_batch='retained')
        assert journal.cursor=='next'
    finally: journal.close()
print(json.dumps({'actual_uid':os.geteuid(),'owner_secret_denied':True}))
'''
    for uid in (65533,65534):
        result=subprocess.run([sys.executable,'-c',code],input=json.dumps({'uid':uid,'path':str(path),'canary':str(canary)}),
            text=True,capture_output=True,timeout=15,user=uid,group=uid,extra_groups=[],umask=0o077,cwd=root,
            env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(modules),'PYTHONDONTWRITEBYTECODE':'1'})
        assert result.returncode==0,'actual Matrix journal UID isolation failed'
        assert json.loads(result.stdout)=={'actual_uid':uid,'owner_secret_denied':True}
        assert 'disposable-root-only-owner-canary' not in result.stdout+result.stderr


@pytest.mark.parametrize('storage_failure',[False,True])
def test_ntfy_auth_retry_is_audited_atomic_and_cursor_preserving_under_actual_gateway_uid(uid_fixture_path,storage_failure):
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700)
    database=state/'native.db'
    config={'version':1,'connectors':[{'id':'topic','platform':'ntfy'}],'bindings':[{
        'id':'owner','connector':'topic','sender':'private','chat':'private','scope':'','thread':'',
        'identity':'owner','capabilities':['create','read'],'trust_topic_publishers':True,'generation':'a'*64,'since':1}]}
    inbox=NativeInbox(database,Redactor())
    inbox.admit(GatewayPolicy(config),'topic',{'platform':'ntfy','sender':'private','chat':'private','scope':'','thread':'',
        'message_id':'retained-command','is_bot':False,'text':'preserved command'},{'body':'preserved command'})
    inbox.db.execute('CREATE TABLE ntfy_subscription(identity TEXT PRIMARY KEY,connector TEXT,cursor TEXT,status TEXT,next_attempt REAL)')
    inbox.db.execute("INSERT INTO ntfy_subscription VALUES('private-identity','topic','retained-cursor','authentication-denied',12345)")
    inbox.db.execute("INSERT INTO ntfy_subscription VALUES('other-identity','other','other-cursor','authentication-denied',12345)")
    inbox.db.execute('CREATE TABLE ntfy_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
    if storage_failure:
        inbox.db.execute("CREATE TRIGGER owner_audit_fault BEFORE INSERT ON ntfy_owner_events BEGIN SELECT RAISE(ABORT,'disposable audit storage failure'); END")
    inbox.close()
    os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    canary=root/'owner-secret';canary.write_text('root-only-disposable-canary');canary.chmod(0o600)
    code='''
import json,os,sqlite3,sys
from pathlib import Path
from haos.gateway import GatewayPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_ntfy_auth
from haos.redaction import Redactor
request=json.load(sys.stdin)
assert os.geteuid()==65534 and os.getegid()==65534 and os.getgroups()==[]
try: Path(request['canary']).read_bytes()
except PermissionError: pass
else: raise AssertionError('gateway UID read owner secret')
inbox=NativeInbox(Path(request['database']),Redactor())
try:
    policy=GatewayPolicy(request['policy'])
    params={'connector':'topic','owner_uid':1000,'note_sha256':'b'*64}
    if request['storage_failure']:
        try: retry_ntfy_auth(inbox,policy,params)
        except sqlite3.IntegrityError: pass
        else: raise AssertionError('audit failure was swallowed')
        assert tuple(inbox.db.execute("SELECT status,cursor,next_attempt FROM ntfy_subscription WHERE connector='topic'").fetchone())==('authentication-denied','retained-cursor',12345)
        assert inbox.db.execute('SELECT COUNT(*) FROM ntfy_owner_events').fetchone()[0]==0
    else:
        assert retry_ntfy_auth(inbox,policy,params)=={'connector':'topic','authentication_blocks_cleared':1,'network_requested':False}
        assert tuple(inbox.db.execute("SELECT status,cursor,next_attempt FROM ntfy_subscription WHERE connector='topic'").fetchone())==('ready','retained-cursor',0)
        assert retry_ntfy_auth(inbox,policy,params)['authentication_blocks_cleared']==0
        assert inbox.db.execute('SELECT COUNT(*) FROM ntfy_owner_events').fetchone()[0]==1
        assert tuple(inbox.db.execute('SELECT owner_uid,decision,note_sha256 FROM ntfy_owner_events').fetchone())==(1000,'retry-auth','b'*64)
    assert tuple(inbox.db.execute("SELECT status,cursor FROM ntfy_subscription WHERE connector='other'").fetchone())==('authentication-denied','other-cursor')
    assert json.loads(inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0])=={'body':'preserved command'}
    assert inbox.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
finally: inbox.close()
'''
    child=subprocess.run([sys.executable,'-c',code],input=json.dumps({'database':str(database),'canary':str(canary),
        'policy':config,'storage_failure':storage_failure}),text=True,capture_output=True,
        user=65534,group=65534,extra_groups=[],umask=0o077,cwd=str(root),
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(modules)})
    assert child.returncode==0,child.stderr
