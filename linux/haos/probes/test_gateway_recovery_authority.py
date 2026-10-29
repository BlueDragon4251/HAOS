"""Real Unix UID/SQLite recovery in private fixtures; no transport is contacted."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import select

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


@pytest.mark.parametrize('platform',['homeassistant','ntfy','irc'])
@pytest.mark.parametrize('journal_exists',[False,True])
def test_actual_recovery_main_dispatches_auth_recheck_with_real_uid_nss_and_default_private_path(uid_fixture_path,platform,journal_exists):
    root=uid_fixture_path;root.chmod(0o755)
    # The child gets an actual kernel chroot and its own real passwd database;
    # host accounts/configuration are never changed and UID calls are not mocked.
    (root/'etc').mkdir(mode=0o755)
    (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/false\nhaos-gateway:x:65534:65534:gateway:/:/bin/false\n')
    (root/'var/lib/haos-gateway').mkdir(parents=True,mode=0o700)
    state=root/'var/lib/haos-gateway';database=state/'native-inbox.db'
    config={'version':1,'connectors':[{'id':'test','platform':platform}],'bindings':[]}
    if journal_exists:
        inbox=NativeInbox(database,Redactor())
        if platform in {'homeassistant','irc'}:
            inbox.db.execute(f'CREATE TABLE {platform}_profile_status(identity TEXT PRIMARY KEY,connector TEXT,status TEXT,updated_at REAL,next_attempt REAL,gap_since REAL)')
            inbox.db.execute(f"INSERT INTO {platform}_profile_status VALUES('fixture','test','authentication-refused',123,0,42)")
        else:
            inbox.db.execute('CREATE TABLE ntfy_subscription(identity TEXT PRIMARY KEY,connector TEXT,cursor TEXT,status TEXT,next_attempt REAL)')
            inbox.db.execute("INSERT INTO ntfy_subscription VALUES('fixture','test','retained-cursor','authentication-denied',0)")
        inbox.close()
    os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    code='''
import json,os,pwd,sys
from haos import gateway_raw_recovery
from haos import gateway_homeassistant_profile
pwd.getpwnam('nobody')
os.chroot(sys.argv[1]);os.chdir('/')
os.setgroups([]);os.setgid(65534);os.setuid(65534)
assert os.geteuid()==65534 and pwd.getpwnam('haos-gateway').pw_uid==65534
gateway_raw_recovery.main()
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    request={'action':'retry-'+platform+'-auth',
        'policy':config,'params':{'connector':'test','owner_uid':1000,'note_sha256':'a'*64}}
    child=subprocess.run([sys.executable,'-c',code,str(root)],input=json.dumps(request),
        text=True,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(Path(__file__).resolve().parents[1])})
    assert child.returncode==0,child.stderr
    report=json.loads(child.stdout)
    assert report['network_requested'] is False and report['authentication_blocks_cleared']==int(journal_exists)
    if not journal_exists:assert not database.exists() and report['native_journal_created'] is False
    else:
        import sqlite3
        connection=sqlite3.connect(database)
        try:
            if platform in {'homeassistant','irc'}:
                assert tuple(connection.execute(f'SELECT status,gap_since FROM {platform}_profile_status').fetchone())==('created',42)
                assert connection.execute(f'SELECT owner_uid FROM {platform}_owner_events').fetchone()[0]==1000
            else:
                assert tuple(connection.execute('SELECT status,cursor FROM ntfy_subscription').fetchone())==('ready','retained-cursor')
        finally:connection.close()


@pytest.mark.parametrize('change',['withdraw','generation'])
@pytest.mark.parametrize('platform',['slack','telegram','discord'])
def test_native_delivery_callback_observes_atomic_owner_policy_changes_as_real_gateway_uid(uid_fixture_path,change,platform):
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    config={'version':1,'connectors':[{'id':'bot','platform':'slack'}],'bindings':[{
        'id':'owner','connector':'bot','sender':'U42','chat':'C123','scope':'T999','thread':'',
        'identity':'principal','capabilities':['create','read'],'generation':'a'*64}]}
    config['connectors'][0]['platform']=platform
    if platform=='telegram':config['bindings'][0].update(sender='42',chat='-10042',scope='',thread='7')
    if platform=='discord':config['bindings'][0].update(sender='42',chat='123',scope='999')
    from haos.policy import atomic_json
    from haos.gateway import digest
    path=root/'gateways.json';atomic_json(path,config,mode=0o640,gid=65534)
    canary=root/'owner-secret';canary.write_text('disposable-root-owner-canary');canary.chmod(0o600)
    binding=config['bindings'][0]
    payload={'policy':str(path),'canary':str(canary),'platform':platform,'chat':binding['chat'],
        'metadata':{'haos_scope':binding['scope'],'thread_id':binding['thread'],
        'haos_binding':{'binding_id':'owner','binding_digest':digest(binding)}}}
    code='''
import json,os,sys
from pathlib import Path
from types import SimpleNamespace
from haos.gateway import GatewayPolicy
from haos.gateway_delivery_authority import current_delivery
from haos.sandbox import trusted_json
d=json.loads(sys.stdin.readline())
assert os.geteuid()==65534 and os.getegid()==65534 and os.getgroups()==[]
try:Path(d['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('gateway UID read owner secret')
current=lambda:GatewayPolicy(trusted_json(Path(d['policy'])))
adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='bot',policy=current))
check=current_delivery(adapter,d['platform'],d['chat'],d['metadata']);check()
print('admitted',flush=True)
assert sys.stdin.readline().strip()=='owner-updated'
try:check()
except PermissionError:print('revoked',flush=True)
else:raise AssertionError('native operation inherited atomically changed owner authority')
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    child=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,user=65534,group=65534,extra_groups=[],umask=0o077,cwd=root,
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(modules)})
    try:
        child.stdin.write(json.dumps(payload)+'\n');child.stdin.flush()
        assert select.select([child.stdout],[],[],5)[0], 'gateway UID did not admit initial valid owner grant'
        assert child.stdout.readline().strip()=='admitted'
        if change=='withdraw':config['bindings']=[]
        else:config['bindings'][0]['generation']='b'*64
        atomic_json(path,config,mode=0o640,gid=65534)
        output,error=child.communicate('owner-updated\n',timeout=10)
        assert child.returncode==0,error
        assert output.strip()=='revoked'
        assert 'disposable-root-owner-canary' not in output+error
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)


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
@pytest.mark.parametrize('platform',['telegram','slack','mattermost','homeassistant','irc'])
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
    if platform=='homeassistant':
        config['connectors'][0]['platform']='homeassistant'
        config['bindings'][0].update(sender='a'*32,chat='sensor.owner',homeassistant_shared_notifications=True)
    if platform=='irc':
        config['connectors'][0]['platform']='irc'
        config['bindings'][0].update(sender='owner-account',chat='#haos',scope='irc.fixture.invalid:6697',generation='a'*64,since=1)
    from haos.gateway_irc_ingress import PreparedIRCPolicy
    policy = PreparedIRCPolicy(config) if platform=='irc' else GatewayPolicy(config)
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
                           "note_sha256": "a" * 64, "receipt": ("irc_echo_"+"b"*64 if platform=='irc' else "haos_"+"b"*32 if platform=='homeassistant' else "1792800000.000042" if platform=='slack' else "m"*26 if platform=='mattermost' else "42") if decision == "delivered" else None,
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
    from haos.gateway_irc_ingress import PreparedIRCPolicy
    policy=PreparedIRCPolicy(d['policy']) if d['policy']['connectors'][0]['platform']=='irc' else GatewayPolicy(d['policy'])
    result=reconcile(store,policy,d['request'])
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


@pytest.mark.parametrize('storage_failure',[False,True])
def test_prepared_homeassistant_auth_retry_uses_real_private_uid_and_atomic_audit(uid_fixture_path,storage_failure):
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700);database=state/'native.db'
    from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy
    config={'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
        'id':'owner','connector':'ha','sender':'a'*32,'chat':'input_text.owner','scope':'','thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    inbox=NativeInbox(database,Redactor())
    inbox.admit(PreparedHomeAssistantPolicy(config),'ha',{'platform':'homeassistant','sender':'a'*32,'chat':'input_text.owner',
        'scope':'','thread':'','message_id':'c'*64,'is_bot':False,'text':'retained private event'},
        {'event':'retained private event'})
    inbox.db.execute('CREATE TABLE homeassistant_profile_status(identity TEXT PRIMARY KEY,connector TEXT,status TEXT,updated_at REAL,next_attempt REAL,gap_since REAL)')
    inbox.db.execute("INSERT INTO homeassistant_profile_status VALUES('auth','ha','authentication-refused',123,12345,42)")
    inbox.db.execute("INSERT INTO homeassistant_profile_status VALUES('limited','ha','rate-limited',123,12345,42)")
    inbox.db.execute('CREATE TABLE homeassistant_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
    if storage_failure:
        inbox.db.execute("CREATE TRIGGER owner_audit_fault BEFORE INSERT ON homeassistant_owner_events BEGIN SELECT RAISE(ABORT,'disposable audit failure'); END")
    inbox.close();os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    canary=root/'owner-secret';canary.write_text('root-only-disposable-ha-canary');canary.chmod(0o600)
    code='''
import json,os,sqlite3,sys
from pathlib import Path
from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_homeassistant_auth,unresolved
from haos.redaction import Redactor
request=json.load(sys.stdin)
assert os.geteuid()==request['uid'] and os.getegid()==request['uid'] and os.getgroups()==[]
try:Path(request['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged identity read owner secret')
if request['uid']==65533:
    try:NativeInbox(Path(request['database']),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private gateway protocol journal')
else:
    inbox=NativeInbox(Path(request['database']),Redactor())
    try:
        metadata=unresolved(inbox)
        assert len(metadata['ingress'])==1 and len(metadata['transport'])==2
        assert all(row['gap_since']==42 and not row['unseen_remote_history_recovered'] for row in metadata['transport'])
        params={'connector':'ha','owner_uid':1000,'note_sha256':'d'*64}
        policy=PreparedHomeAssistantPolicy(request['policy'])
        if request['storage_failure']:
            try:retry_homeassistant_auth(inbox,policy,params)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('audit storage failure was swallowed')
            assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity='auth'").fetchone())==('authentication-refused',12345,42)
            assert inbox.db.execute('SELECT COUNT(*) FROM homeassistant_owner_events').fetchone()[0]==0
        else:
            assert retry_homeassistant_auth(inbox,policy,params)=={'connector':'ha','authentication_blocks_cleared':1,'network_requested':False}
            assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity='auth'").fetchone())==('created',0,42)
            assert tuple(inbox.db.execute('SELECT owner_uid,decision,note_sha256 FROM homeassistant_owner_events').fetchone())==(1000,'retry-auth','d'*64)
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity='limited'").fetchone())==('rate-limited',12345,42)
        assert json.loads(inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0])=={'event':'retained private event'}
        assert inbox.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
        assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
    finally:inbox.close()
'''
    for uid in (65533,65534):
        child=subprocess.run([sys.executable,'-c',code],input=json.dumps({'database':str(database),'canary':str(canary),
            'policy':config,'storage_failure':storage_failure,'uid':uid}),text=True,capture_output=True,timeout=15,
            user=uid,group=uid,extra_groups=[],umask=0o077,cwd=str(root),
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(modules)})
        assert child.returncode==0,child.stderr


@pytest.mark.parametrize('storage_failure',[False,True])
def test_prepared_irc_auth_retry_uses_real_private_uid_and_atomic_audit(uid_fixture_path,storage_failure):
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700);database=state/'native.db'
    from haos.gateway_irc_ingress import PreparedIRCPolicy
    config={'version':1,'connectors':[{'id':'ha','platform':'irc'}],'bindings':[{
        'id':'owner','connector':'ha','sender':'a'*32,'chat':'#owner','scope':'irc.fixture.invalid:6697','thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    inbox=NativeInbox(database,Redactor())
    inbox.admit(PreparedIRCPolicy(config),'ha',{'platform':'irc','sender':'a'*32,'chat':'#owner',
        'scope':'irc.fixture.invalid:6697','thread':'','message_id':'c'*64,'is_bot':False,'text':'retained private event'},
        {'event':'retained private event'})
    inbox.db.execute('CREATE TABLE irc_profile_status(identity TEXT PRIMARY KEY,connector TEXT,status TEXT,updated_at REAL,next_attempt REAL,gap_since REAL)')
    inbox.db.execute("INSERT INTO irc_profile_status VALUES('auth','ha','authentication-refused',123,12345,42)")
    inbox.db.execute("INSERT INTO irc_profile_status VALUES('limited','ha','rate-limited',123,12345,42)")
    inbox.db.execute('CREATE TABLE irc_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
    if storage_failure:
        inbox.db.execute("CREATE TRIGGER owner_audit_fault BEFORE INSERT ON irc_owner_events BEGIN SELECT RAISE(ABORT,'disposable audit failure'); END")
    inbox.close();os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    canary=root/'owner-secret';canary.write_text('root-only-disposable-ha-canary');canary.chmod(0o600)
    code='''
import json,os,sqlite3,sys
from pathlib import Path
from haos.gateway_irc_ingress import PreparedIRCPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_irc_auth,unresolved
from haos.redaction import Redactor
request=json.load(sys.stdin)
assert os.geteuid()==request['uid'] and os.getegid()==request['uid'] and os.getgroups()==[]
try:Path(request['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('unprivileged identity read owner secret')
if request['uid']==65533:
    try:NativeInbox(Path(request['database']),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private gateway protocol journal')
else:
    inbox=NativeInbox(Path(request['database']),Redactor())
    try:
        metadata=unresolved(inbox)
        assert len(metadata['ingress'])==1 and len(metadata['transport'])==2
        assert all(row['gap_since']==42 and not row['unseen_remote_history_recovered'] for row in metadata['transport'])
        params={'connector':'ha','owner_uid':1000,'note_sha256':'d'*64}
        policy=PreparedIRCPolicy(request['policy'])
        if request['storage_failure']:
            try:retry_irc_auth(inbox,policy,params)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('audit storage failure was swallowed')
            assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity='auth'").fetchone())==('authentication-refused',12345,42)
            assert inbox.db.execute('SELECT COUNT(*) FROM irc_owner_events').fetchone()[0]==0
        else:
            assert retry_irc_auth(inbox,policy,params)=={'connector':'ha','authentication_blocks_cleared':1,'network_requested':False}
            assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity='auth'").fetchone())==('created',0,42)
            assert tuple(inbox.db.execute('SELECT owner_uid,decision,note_sha256 FROM irc_owner_events').fetchone())==(1000,'retry-auth','d'*64)
        assert tuple(inbox.db.execute("SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE identity='limited'").fetchone())==('rate-limited',12345,42)
        assert json.loads(inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0])=={'event':'retained private event'}
        assert inbox.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
        assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
    finally:inbox.close()
'''
    for uid in (65533,65534):
        child=subprocess.run([sys.executable,'-c',code],input=json.dumps({'database':str(database),'canary':str(canary),
            'policy':config,'storage_failure':storage_failure,'uid':uid}),text=True,capture_output=True,timeout=15,
            user=uid,group=uid,extra_groups=[],umask=0o077,cwd=str(root),
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(modules)})
        assert child.returncode==0,child.stderr


@pytest.mark.parametrize('storage_failure',[False,True])
def test_prepared_line_auth_identity_recheck_uses_real_gateway_uid_and_atomic_owner_audit(uid_fixture_path,storage_failure):
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700);database=state/'native.db'
    from haos.gateway_line_ingress import PreparedLINEPolicy
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    inbox=NativeInbox(database,Redactor())
    source={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'retained private LINE input'}
    inbox.admit(PreparedLINEPolicy(config),'line',source,{'event':'retained private LINE input'})
    inbox.db.execute('CREATE TABLE line_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
    future=4102444800
    for identity,status,deadline in [('auth','authentication-refused',future),('identity','identity-refused',0),('limited','rate-limited',future),('revoked','revoked',future)]:
        inbox.db.execute('INSERT INTO line_profile_status VALUES(?,?,?,?,?,?)',(identity,'line','fixture',status,123,deadline))
    inbox.db.execute('CREATE TABLE line_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
    if storage_failure:inbox.db.execute("CREATE TRIGGER audit_fault BEFORE INSERT ON line_owner_events BEGIN SELECT RAISE(ABORT,'disposable audit failure'); END")
    inbox.close();os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    canary=root/'owner-secret';canary.write_text('private-disposable-root-canary');canary.chmod(0o600)
    code='''
import json,os,sqlite3,sys
from pathlib import Path
from haos.gateway_line_ingress import PreparedLINEPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_line_auth,unresolved
from haos.redaction import Redactor
request=json.load(sys.stdin)
assert os.geteuid()==request['uid'] and os.getegid()==request['uid'] and os.getgroups()==[]
try:Path(request['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('private owner data readable by unprivileged identity')
if request['uid']==65533:
    try:NativeInbox(Path(request['database']),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private LINE gateway journal')
else:
    inbox=NativeInbox(Path(request['database']),Redactor())
    try:
        metadata=unresolved(inbox)
        assert len(metadata['transport'])==4 and all(row['platform']=='line' and not row['external_tls_ingress_verified'] for row in metadata['transport'])
        policy=PreparedLINEPolicy(request['policy']);params={'connector':'line','owner_uid':1000,'note_sha256':'e'*64}
        if request['storage_failure']:
            try:retry_line_auth(inbox,policy,params)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('LINE owner audit failure was swallowed')
            assert tuple(inbox.db.execute("SELECT status,next_attempt FROM line_profile_status WHERE identity='auth'").fetchone())==('authentication-refused',4102444800)
            assert inbox.db.execute("SELECT status FROM line_profile_status WHERE identity='identity'").fetchone()[0]=='identity-refused'
            assert inbox.db.execute('SELECT COUNT(*) FROM line_owner_events').fetchone()[0]==0
        else:
            assert retry_line_auth(inbox,policy,params)=={'connector':'line','authentication_blocks_cleared':2,'network_requested':False}
            assert tuple(inbox.db.execute("SELECT status,next_attempt FROM line_profile_status WHERE identity='auth'").fetchone())==('created',4102444800)
            assert tuple(inbox.db.execute("SELECT status,next_attempt FROM line_profile_status WHERE identity='identity'").fetchone())==('created',0)
            assert tuple(inbox.db.execute('SELECT owner_uid,decision,changed,note_sha256 FROM line_owner_events').fetchone())==(1000,'retry-auth',2,'e'*64)
            assert retry_line_auth(inbox,policy,params)['authentication_blocks_cleared']==0
        for identity,status in [('limited','rate-limited'),('revoked','revoked')]:
            assert tuple(inbox.db.execute('SELECT status,next_attempt FROM line_profile_status WHERE identity=?',(identity,)).fetchone())==(status,4102444800)
        assert json.loads(inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0])=={'event':'retained private LINE input'}
        assert inbox.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
        assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
    finally:inbox.close()
'''
    for uid in (65533,65534):
        child=subprocess.run([sys.executable,'-c',code],input=json.dumps({'database':str(database),'canary':str(canary),
            'policy':config,'storage_failure':storage_failure,'uid':uid}),text=True,capture_output=True,timeout=15,
            user=uid,group=uid,extra_groups=[],umask=0o077,cwd=str(root),
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(modules)})
        assert child.returncode==0,child.stderr


@pytest.mark.parametrize('storage_failure',[False,True])
def test_prepared_sms_auth_identity_recheck_uses_real_gateway_uid_and_atomic_owner_audit(uid_fixture_path,storage_failure):
    root=uid_fixture_path;root.chmod(0o755)
    modules=root/'modules';modules.mkdir(mode=0o755)
    shutil.copytree(Path(__file__).resolve().parents[1]/'haos',modules/'haos',ignore=shutil.ignore_patterns('__pycache__'))
    for path in (modules/'haos').rglob('*.py'):path.chmod(0o644)
    (modules/'haos').chmod(0o755)
    state=root/'state';state.mkdir(mode=0o700);database=state/'native.db'
    from haos.gateway_sms import PreparedSMSPolicy
    config={'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{
        'id':'owner','connector':'sms','sender':'+12025550101','chat':'+12025550101','scope':'AC'+'a'*32+':+12025550100','thread':'',
        'identity':'owner','capabilities':['create','read'],'generation':'b'*64,'since':1}]}
    inbox=NativeInbox(database,Redactor())
    source={'platform':'sms','sender':'+12025550101','chat':'+12025550101','scope':'AC'+'a'*32+':+12025550100','thread':'',
        'message_id':'MM'+'c'*32,'is_bot':False,'text':'retained private SMS input'}
    inbox.admit(PreparedSMSPolicy(config),'sms',source,{'event':'retained private SMS input'})
    inbox.db.execute('CREATE TABLE sms_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
    future=4102444800
    for identity,status,deadsms in [('auth','authentication-refused',future),('identity','identity-refused',0),('limited','rate-limited',future),('revoked','revoked',future)]:
        inbox.db.execute('INSERT INTO sms_profile_status VALUES(?,?,?,?,?,?)',(identity,'sms','fixture',status,123,deadsms))
    inbox.db.execute('CREATE TABLE sms_owner_events(connector TEXT,created_at REAL,owner_uid INTEGER,decision TEXT,changed INTEGER,policy_sha256 TEXT,note_sha256 TEXT)')
    if storage_failure:inbox.db.execute("CREATE TRIGGER audit_fault BEFORE INSERT ON sms_owner_events BEGIN SELECT RAISE(ABORT,'disposable audit failure'); END")
    inbox.close();os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    canary=root/'owner-secret';canary.write_text('private-disposable-root-canary');canary.chmod(0o600)
    code='''
import json,os,sqlite3,sys
from pathlib import Path
from haos.gateway_sms import PreparedSMSPolicy
from haos.gateway_raw import NativeInbox
from haos.gateway_raw_recovery import retry_sms_auth,unresolved
from haos.redaction import Redactor
request=json.load(sys.stdin)
assert os.geteuid()==request['uid'] and os.getegid()==request['uid'] and os.getgroups()==[]
try:Path(request['canary']).read_bytes()
except PermissionError:pass
else:raise AssertionError('private owner data readable by unprivileged identity')
if request['uid']==65533:
    try:NativeInbox(Path(request['database']),Redactor())
    except PermissionError:pass
    else:raise AssertionError('agent opened private SMS gateway journal')
else:
    inbox=NativeInbox(Path(request['database']),Redactor())
    try:
        metadata=unresolved(inbox)
        assert len(metadata['transport'])==4 and all(row['platform']=='sms' and not row['external_tls_ingress_verified'] for row in metadata['transport'])
        policy=PreparedSMSPolicy(request['policy']);params={'connector':'sms','owner_uid':1000,'note_sha256':'e'*64}
        if request['storage_failure']:
            try:retry_sms_auth(inbox,policy,params)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('SMS owner audit failure was swallowed')
            assert tuple(inbox.db.execute("SELECT status,next_attempt FROM sms_profile_status WHERE identity='auth'").fetchone())==('authentication-refused',4102444800)
            assert inbox.db.execute("SELECT status FROM sms_profile_status WHERE identity='identity'").fetchone()[0]=='identity-refused'
            assert inbox.db.execute('SELECT COUNT(*) FROM sms_owner_events').fetchone()[0]==0
        else:
            assert retry_sms_auth(inbox,policy,params)=={'connector':'sms','authentication_blocks_cleared':2,'network_requested':False}
            assert tuple(inbox.db.execute("SELECT status,next_attempt FROM sms_profile_status WHERE identity='auth'").fetchone())==('created',4102444800)
            assert tuple(inbox.db.execute("SELECT status,next_attempt FROM sms_profile_status WHERE identity='identity'").fetchone())==('created',0)
            assert tuple(inbox.db.execute('SELECT owner_uid,decision,changed,note_sha256 FROM sms_owner_events').fetchone())==(1000,'retry-auth',2,'e'*64)
            assert retry_sms_auth(inbox,policy,params)['authentication_blocks_cleared']==0
        for identity,status in [('limited','rate-limited'),('revoked','revoked')]:
            assert tuple(inbox.db.execute('SELECT status,next_attempt FROM sms_profile_status WHERE identity=?',(identity,)).fetchone())==(status,4102444800)
        assert json.loads(inbox.db.execute('SELECT payload FROM native_inbox').fetchone()[0])=={'event':'retained private SMS input'}
        assert inbox.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='pending'
        assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
    finally:inbox.close()
'''
    for uid in (65533,65534):
        child=subprocess.run([sys.executable,'-c',code],input=json.dumps({'database':str(database),'canary':str(canary),
            'policy':config,'storage_failure':storage_failure,'uid':uid}),text=True,capture_output=True,timeout=15,
            user=uid,group=uid,extra_groups=[],umask=0o077,cwd=str(root),
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(modules)})
        assert child.returncode==0,child.stderr


@pytest.mark.parametrize('uid,groups,admitted',[(0,[],False),(65533,[],False),(65534,[],True),(65534,[65534],True),(65534,[65533],False)])
def test_actual_runtime_startup_identity_uses_kernel_uid_gid_groups_and_private_nss_before_credentials(uid_fixture_path,uid,groups,admitted):
    root=uid_fixture_path;root.chmod(0o755);(root/'etc').mkdir(mode=0o755)
    (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/false\nhaos-gateway:x:65534:65534:gateway:/:/bin/false\n')
    code='''
import asyncio,json,os,pwd,sys
from haos.gateway_runtime import require_runtime_identity,serve
request=json.loads(sys.argv[2]);pwd.getpwnam('nobody')
os.chroot(sys.argv[1]);os.chdir('/')
os.setgroups(request['groups']);os.setgid(request['uid']);os.setuid(request['uid'])
assert os.geteuid()==request['uid'] and os.getegid()==request['uid'] and os.getgroups()==request['groups']
if request['admitted']:
    require_runtime_identity()
else:
    try:asyncio.run(serve())
    except PermissionError as error:assert 'service UID/GID' in str(error)
    else:raise AssertionError('wrong runtime identity read configuration or started gateway')
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    child=subprocess.run([sys.executable,'-c',code,str(root),json.dumps({'uid':uid,'groups':groups,'admitted':admitted})],
        text=True,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1',
            'PYTHONPATH':str(Path(__file__).resolve().parents[1])})
    assert child.returncode==0,child.stderr


@pytest.mark.parametrize('uids,gids',[([0,65534,0],[65534]*3),([65534,65534,0],[65534]*3),
    ([65534]*3,[0,65534,0]),([65534]*3,[65534,65534,0])])
def test_gateway_runtime_refuses_actual_retained_real_or_saved_root_ids(uid_fixture_path,uids,gids):
    root=uid_fixture_path;root.chmod(0o755);(root/'etc').mkdir(mode=0o755)
    (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/false\nhaos-gateway:x:65534:65534:gateway:/:/bin/false\n')
    code='''
import asyncio,json,os,pwd,sys
from haos.gateway_runtime import serve
request=json.loads(sys.argv[2]);pwd.getpwnam('nobody')
os.chroot(sys.argv[1]);os.chdir('/')
os.setgroups([]);os.setresgid(*request['gids']);os.setresuid(*request['uids'])
assert list(os.getresuid())==request['uids'] and list(os.getresgid())==request['gids']
assert os.geteuid()==65534 and os.getegid()==65534 and os.getgroups()==[]
try:asyncio.run(serve())
except PermissionError as error:assert 'service UID/GID' in str(error)
else:raise AssertionError('gateway retained restorable root authority')
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    child=subprocess.run([sys.executable,'-c',code,str(root),json.dumps({'uids':uids,'gids':gids})],text=True,
        capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1',
            'PYTHONPATH':str(Path(__file__).resolve().parents[1])})
    assert child.returncode==0,child.stderr


@pytest.mark.parametrize('journal_exists',[False,True])
def test_media_cache_owner_worker_real_uid_nss_private_path_and_audited_revocation(uid_fixture_path,journal_exists):
    root=uid_fixture_path;root.chmod(0o755)
    (root/'etc').mkdir(mode=0o755)
    (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/false\nhaos-gateway:x:65534:65534:gateway:/:/bin/false\n')
    state=root/'var/lib/haos-gateway';state.mkdir(parents=True,mode=0o700);database=state/'native-inbox.db'
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'identity':'owner','capabilities':['create'],'allow_media':True,'generation':'b'*64,'since':1}]}
    identity=None
    if journal_exists:
        from haos.gateway_media_relay import MediaCache
        inbox=NativeInbox(database,Redactor())
        event={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
            'message_id':'c'*64,'is_bot':False,'text':'Inspect retained document'}
        identity=MediaCache(inbox).put(GatewayPolicy(config),'line',event,b'private gateway media','document')['id'];inbox.close()
    os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    code='''
import os,pwd,sys
from haos import gateway_raw_recovery,gateway_media_relay,gateway_line_ingress
pwd.getpwnam('nobody')
os.chroot(sys.argv[1]);os.chdir('/')
os.setgroups([]);os.setgid(int(sys.argv[2]));os.setuid(int(sys.argv[2]))
gateway_raw_recovery.main()
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    def request(action,params,policy,uid=65534):
        return subprocess.run([sys.executable,'-c',code,str(root),str(uid)],input=json.dumps({'action':action,'policy':policy,'params':params}),
            text=True,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
                'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(Path(__file__).resolve().parents[1])})
    denied=request('media-cache',{},config,65533);assert denied.returncode!=0 and 'unprivileged gateway UID' in denied.stderr
    listing=request('media-cache',{},config);assert listing.returncode==0,listing.stderr
    metadata=json.loads(listing.stdout)
    if not journal_exists:
        assert metadata['uploads']==[] and metadata['native_journal_created'] is False and not database.exists()
        return
    assert metadata['stored_bytes']==len(b'private gateway media') and metadata['uploads'][0]['purge_allowed'] is False
    params={'id':identity,'owner_uid':1000,'note_sha256':'e'*64,'confirmed':True}
    active=request('purge-media-cache',params,config);assert active.returncode!=0 and 'withdraw or change' in active.stderr
    config['bindings']=[]
    purged=request('purge-media-cache',params,config);assert purged.returncode==0,purged.stderr
    assert json.loads(purged.stdout)['removed_payload_bytes']==len(b'private gateway media')
    import sqlite3
    with sqlite3.connect(database) as observer:
        assert observer.execute('SELECT state,data FROM native_media_cache').fetchone()==('purged',None)
        assert observer.execute('SELECT owner_uid,note_sha256 FROM native_media_owner_events').fetchone()==(1000,'e'*64)
    assert database.stat().st_uid==65534 and database.stat().st_mode&0o077==0


@pytest.mark.parametrize('journal_exists',[False,True])
def test_controller_media_worker_real_uid_private_default_ledger_and_no_root_creation(uid_fixture_path,journal_exists):
    root=uid_fixture_path;root.chmod(0o755)
    (root/'etc').mkdir(mode=0o755)
    (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/false\nhaos-control:x:65532:65532:controller:/:/bin/false\n')
    state=root/'var/lib/haos-control';state.mkdir(parents=True,mode=0o700);database=state/'missions.db'
    identity=None
    if journal_exists:
        from haos.gateway_media import describe
        import base64
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
            'identity':'owner','capabilities':['create'],'allow_media':True,'generation':'b'*64,'since':1}]}
        policy=GatewayPolicy(config);store=MissionStore(database);engine=GatewayEngine(store)
        event={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
            'message_id':'c'*64,'is_bot':False,'text':'Inspect retained document'}
        payload=b'private controller media'
        identity=engine.media.begin(policy,{'connector':'line','envelope':event,'descriptor':describe(payload,'document')})['id']
        engine.media.chunk(policy,{'id':identity,'offset':0,'data':base64.b64encode(payload).decode()});store.close()
    os.chown(state,65532,65532)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65532,65532)
    code='''
import os,pwd,sys
from haos import gateway_recovery,gateway_media
pwd.getpwnam('nobody')
os.chroot(sys.argv[1]);os.chdir('/')
os.setgroups([]);os.setgid(int(sys.argv[2]));os.setuid(int(sys.argv[2]))
gateway_recovery.main()
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    def request(action,params,uid=65532):
        return subprocess.run([sys.executable,'-c',code,str(root),str(uid)],input=json.dumps({'action':action,
            'policy':{'version':1,'connectors':[],'bindings':[]},'params':params}),text=True,capture_output=True,timeout=15,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(Path(__file__).resolve().parents[1])})
    for uid in [0,65533]:
        denied=request('media-list',{},uid);assert denied.returncode!=0 and 'without root as the ledger service' in denied.stderr
    listing=request('media-list',{})
    if not journal_exists:
        assert listing.returncode!=0 and not database.exists()
        return
    assert listing.returncode==0,listing.stderr
    assert json.loads(listing.stdout)['stored_bytes']==len(b'private controller media')
    params={'ids':[identity],'owner_uid':1000,'note_sha256':'e'*64,'confirmed':False}
    refused=request('purge-media',params);assert refused.returncode!=0
    assert json.loads(request('media-list',{}).stdout)['stored_bytes']==len(b'private controller media')
    params['confirmed']=True;purged=request('purge-media',params);assert purged.returncode==0,purged.stderr
    assert json.loads(purged.stdout)['removed_payload_bytes']==len(b'private controller media')
    import sqlite3
    with sqlite3.connect(database) as observer:
        assert observer.execute('SELECT state FROM gateway_media_uploads').fetchone()[0]=='purged'
        assert observer.execute('SELECT actor,note FROM gateway_media_purge_audit').fetchone()==('owner:1000','inspection sha256:'+'e'*64)
    assert database.stat().st_uid==65532 and all(p.stat().st_uid==65532 for p in state.iterdir())


@pytest.mark.parametrize('uid',[65532,65533,65534])
def test_email_owner_account_and_forms_reject_actual_service_uids_before_any_helper_or_network(uid):
    assert os.geteuid()==0
    code='''
import os,sys
sys.path.insert(0,sys.argv[2])
from haos.gateway_setup import owner_email_account
from haos import initial_setup
os.setgroups([]);os.setgid(int(sys.argv[1]));os.setuid(int(sys.argv[1]))
for call in [lambda:owner_email_account('email'),lambda:initial_setup.inspect_email_gateway_account('email'),
    lambda:initial_setup.configure_email_gateway('email',{},trust_authentication_results=True),
    lambda:initial_setup.email_gateway_sources(),
    lambda:initial_setup.recover_email_gateway({},'approve-email-retry','fixture',True,confirmed_not_delivered=True)]:
    try:call()
    except PermissionError:pass
    else:raise AssertionError('service UID reached an owner-only email operation')
assert 'plugins.platforms.email.adapter' not in sys.modules
'''
    result=subprocess.run([sys.executable,'-c',code,str(uid),str(Path(__file__).resolve().parents[1])],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('operation',['upload','reply'])
@pytest.mark.parametrize('uid',[0,65533,65534])
def test_actual_feishu_multipart_recovery_main_checks_real_uid_and_preserves_other_parts(uid_fixture_path,operation,uid):
    import time
    import sqlite3
    from types import SimpleNamespace
    from haos.gateway import digest
    from haos.gateway_feishu import scope
    from haos.gateway_feishu_delivery import Publisher
    from haos.gateway_feishu_media_delivery import MediaPublisher
    from haos.gateway_feishu_media_recovery import outgoing,TABLES
    root=uid_fixture_path;root.chmod(0o755);(root/'etc').mkdir(mode=0o755)
    (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/false\nhaos-gateway:x:65534:65534:gateway:/:/bin/false\n')
    (root/'var/lib/haos-gateway').mkdir(parents=True,mode=0o700)
    state=root/'var/lib/haos-gateway';database=state/'native-inbox.db'
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-recovery-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],
        'generation':'d'*64,'since':123,'allow_outbound_media':True}
    config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]}
    inbox=NativeInbox(database,Redactor())
    adapter=SimpleNamespace(_haos_native=SimpleNamespace(connector='feishu',inbox=inbox),_haos_feishu_value=value)
    Publisher(adapter);publisher=MediaPublisher(adapter);now=time.time()
    for table in TABLES.values():
        for part in (0,1):inbox.db.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('a'*64,part,1,'feishu',publisher.scope,'b'*64,'uncertain','','','',now,now))
    selected=next(x for x in outgoing(inbox) if x['operation']==operation and x['part']==0)
    inbox.close();os.chown(state,65534,65534)
    for path in state.iterdir():path.chmod(0o600);os.chown(path,65534,65534)
    request={'action':'approve-feishu-part-retry','policy':config,'params':{
        'connector':'feishu','delivery_id':'a'*64,'part':0,'operation':operation,'attempt':1,
        'snapshot_sha256':selected['snapshot_sha256'],'owner_uid':1000,'note_sha256':'c'*64,
        'confirmed':True,'confirmed_not_accepted':True}}
    code='''
import io,json,os,pwd,sys
from haos import gateway_raw_recovery,gateway_feishu_media_recovery
from haos.gateway_feishu import PreparedFeishuPolicy
PreparedFeishuPolicy(json.loads(sys.argv[3]));pwd.getpwnam('nobody')
os.chroot(sys.argv[1]);os.chdir('/')
os.setgroups([]);os.setgid(int(sys.argv[2]));os.setuid(int(sys.argv[2]))
assert os.geteuid()==int(sys.argv[2]) and os.getgroups()==[]
gateway_raw_recovery.main()
assert 'gateway.config' not in sys.modules and 'plugins' not in sys.modules
'''
    child=subprocess.run([sys.executable,'-c',code,str(root),str(uid),json.dumps(config)],input=json.dumps(request),
        text=True,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(Path(__file__).resolve().parents[1])})
    if uid==65534:
        assert child.returncode==0,child.stderr
        report=json.loads(child.stdout);assert report['network_requested'] is False and report['controller_reconciliation_still_required'] is True
    else:assert child.returncode!=0 and 'PermissionError' in child.stderr and not child.stdout
    db=sqlite3.connect(database)
    try:
        released=[]
        for name,table in TABLES.items():
            released.extend((name,part) for part,state in db.execute(f'SELECT part,state FROM {table}') if state=='owner-retry-approved')
        assert released==([(operation,0)] if uid==65534 else [])
        if uid==65534:assert db.execute('SELECT owner_uid FROM feishu_media_owner_events').fetchone()[0]==1000
    finally:db.close()
