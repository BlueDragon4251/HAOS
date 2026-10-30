"""Real Root/backend/private UID recovery; only systemctl state is a fixture."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


def main():
    if (os.geteuid() != 0 or os.getpid() != 1 or os.environ.get('HAOS_DISPOSABLE_PHOTON_OWNER_PROCESS') != '1'
            or not Path('/.dockerenv').exists() or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag & os.ST_RDONLY):
        raise PermissionError('fresh explicit readonly disposable Photon Owner namespace required')
    code = Path('/usr/lib/haos'); code.mkdir(mode=0o755)
    subprocess.run([sys.executable, '/repo/linux/haos/runtime/install_package.py', '/repo/linux/haos/haos', str(code / 'haos')], check=True)
    runtime = code / 'hermes/.venv'; subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(runtime)], check=True)
    (runtime / 'lib/python3.11/site-packages/fixture.pth').write_text('/usr/lib/haos\n')
    with Path('/etc/passwd').open('a') as stream:
        stream.write('haos-gateway:x:65534:65534:Disposable gateway fixture:/nonexistent:/usr/sbin/nologin\n')
    sys.path.insert(0, str(code))
    from haos.gateway import digest
    from haos.gateway_photon import scope
    from haos.photon_owner_process import command
    value = {'project_id': 'fixture-project', 'project_secret': secrets.token_urlsafe(32), 'phone': 'shared', 'services': ['iMessage']}
    binding = {'id': 'phone-owner', 'connector': 'phone', 'identity': 'owner', 'sender': '+15550100001',
        'chat': 'any;-;+15550100001', 'thread': '', 'scope': scope(value), 'capabilities': ['create', 'read'],
        'generation': secrets.token_hex(32), 'since': int(time.time() * 1000) - 10000}
    config = {'version': 1, 'publication': secrets.token_hex(32), 'connectors': [{'id': 'phone', 'platform': 'photon'}], 'bindings': [binding]}
    etc = Path('/etc/haos'); etc.mkdir(mode=0o755)
    def publish():
        (etc / 'gateways.json').write_text(json.dumps(config)); (etc / 'gateways.json').chmod(0o644)
        secret = etc / 'gateway-credentials'; secret.write_text(json.dumps({'publication': config['publication'], 'connectors': {'phone': value}})); secret.chmod(0o600)
    publish()
    state = Path('/var/lib/haos-gateway'); state.mkdir(mode=0o700); os.chown(state, 65534, 65534)
    systemctl = Path('/usr/bin/systemctl'); systemctl.write_text('''#!/usr/local/bin/python3
import pathlib,sys
with pathlib.Path('/run/fixture-systemctl.log').open('a') as stream:stream.write(' '.join(sys.argv[1:])+'\\n')
if sys.argv[1]=='stop':raise SystemExit(0)
if sys.argv[1]=='show':print('LoadState=loaded\\nActiveState='+('active' if pathlib.Path('/run/fixture-active').exists() else 'inactive')+'\\nMainPID=0\\nControlPID=0')
else:raise SystemExit(2)
'''); systemctl.chmod(0o755)
    helper = Path('/root/photon-owner-parent.py'); helper.write_text('''import json,os,sys,subprocess
sys.path.insert(0,'/usr/lib/haos')
from haos import photon_owner_setup as owner
request=json.load(sys.stdin);action=request['action'];params=request.get('params',{})
try:
 if action=='status':value=owner.status('phone')
 elif action=='profiles':value=owner.profiles()
 elif action=='sources':value=owner.sources(params['profile'])
 elif action=='purge':value=owner.purge(**params)
 elif action=='cli':
  import argparse
  from haos.photon_owner_cli import arguments
  from haos.gateway_setup import owner_gateway
  parser=argparse.ArgumentParser();arguments(parser.add_subparsers(dest='gateway_action',required=True))
  value=owner_gateway(parser.parse_args(params['argv']))
 elif action=='hold':
  from haos.photon_owner_process import command
  child=subprocess.Popen(command(),stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,user=65534,group=65534,extra_groups=[],cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin'},umask=0o077)
  open('/run/held-worker.pid','w').write(str(child.pid));child.wait();raise SystemExit(0)
 else:raise ValueError('fixture action')
 print(json.dumps(value))
except PermissionError:print(json.dumps({'error':'root-backend-authority-refused'}))
'''); helper.chmod(0o700)
    actor = code / 'source-fixture.py'; actor.write_text('''import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from haos.gateway_photon import PreparedPhotonPolicy,scope
from haos.gateway_photon_custody import Originals
from haos.gateway_photon_cursor import Cursor
from haos.gateway_photon_health import Ledger
from haos.gateway_raw import NativeInbox
from haos.redaction import Redactor
from haos.gateway_matrix_profile import acquire_lease
request=json.load(sys.stdin);value=request['value'];root=Path('/var/lib/haos-gateway')
profile=root/'profiles'/('photon-'+scope(value).split(':')[1])
def current():return PreparedPhotonPolicy(json.loads(Path('/etc/haos/gateways.json').read_text()))
if request['action'].startswith('schema-'):
 import sqlite3
 db=sqlite3.connect(profile/'originals.db')
 if request['action']=='schema-break':db.execute('ALTER TABLE photon_originals RENAME TO retained_originals_for_inspection');db.commit()
 result={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 assert 'retained_originals_for_inspection' in result and 'photon_originals' not in result
 print(json.dumps({'missing_original_schema_preserved':True}));db.close();raise SystemExit(0)
profiles=root/'profiles';profiles.mkdir(mode=0o700,exist_ok=True);profile.mkdir(mode=0o700,exist_ok=True)
store=Originals(profile/'originals.db',Redactor([]),current);cursor=Cursor(store,value,current)
if request['action']=='create':
 now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');binding=current().bindings['phone-owner']
 raw=json.dumps({'phone':'shared','cursor':'1','event':{'type':'message.received','sequence':1,'occurredAt':now,'chatGuid':binding['chat'],
  'message':{'guid':'spc-owner-fixture','isFromMe':False,'dateCreated':now,'sender':{'address':binding['sender'],'service':'iMessage'},'chatGuids':[binding['chat']],
   'content':{'text':'private owner fixture message','attachments':[]}}}}).encode()
 key=store.retain(current(),'phone',value,raw);assert cursor.advance('9')=='0'
 inbox=NativeInbox(root/'native-inbox.db',Redactor([]));ledger=Ledger(inbox,'phone',value,'fixture-profile',current);ledger.update('rate-limited',180)
 print(json.dumps({'id':key,'profile':profile.name}));inbox.close()
else:
 row=store.db.execute('SELECT * FROM photon_originals').fetchone()
 print(json.dumps({'raw_bytes':len(row['raw']),'safe':cursor.resume(),'audit_count':store.db.execute('SELECT COUNT(*) FROM photon_source_owner_events').fetchone()[0]}))
store.close()
'''); actor.chmod(0o644)
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'SUDO_UID': '1000'}
    def call(action, params=None):
        result = subprocess.run([sys.executable, str(helper)], input=json.dumps({'action': action, 'params': params or {}}), text=True,
            capture_output=True, env=env, timeout=20, cwd=str(code))
        assert result.returncode == 0 and not result.stderr, result.stderr
        assert value['project_secret'] not in result.stdout and 'private owner fixture message' not in result.stdout
        return json.loads(result.stdout)
    def source(action):
        result = subprocess.run([str(runtime / 'bin/python'), '-E', '-s', str(actor)], input=json.dumps({'action': action, 'value': value}),
            text=True, capture_output=True, user=65534, group=65534, extra_groups=[], env=env, cwd=str(code), timeout=15, umask=0o077)
        assert result.returncode == 0 and not result.stderr, result.stderr
        return json.loads(result.stdout)
    cases = []
    initial = call('status'); assert initial['result']['status'] == 'not-started' and not (state / 'native-inbox.db').exists()
    assert not Path('/run/fixture-systemctl.log').exists()
    cases.append('actual_Root_status_handoff_contains_fingerprints_only_and_does_not_stop_service_or_create_journal')
    assert call('profiles')['profiles'] == []
    created = source('create'); profile = created['profile']
    status = call('status')['result']; assert status['status'] == 'rate-limited' and status['next_attempt'] > time.time() + 150
    assert call('cli', {'argv': ['photon-recovery', 'status', '--connector', 'phone']})['result'] == status
    calls = Path('/run/fixture-systemctl.log').read_text()
    # A separate minimal lease holder gives a readiness handshake without SDK.
    hold_code = "from pathlib import Path;from haos.gateway_matrix_profile import acquire_lease;import sys,os;fd=acquire_lease(Path(sys.argv[1]));print('held',flush=True);sys.stdin.read();os.close(fd)"
    holder = subprocess.Popen([str(runtime / 'bin/python'), '-E', '-s', '-c', hold_code, str(state / 'profiles' / profile)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, user=65534, group=65534, extra_groups=[], env=env, cwd=str(code), umask=0o077)
    try:
        assert holder.stdout.readline() == 'held\n'
        assert call('status')['result'] == status and Path('/run/fixture-systemctl.log').read_text() == calls
        assert call('sources', {'profile': profile}) == {'error': 'authority-refused'}
    finally:
        holder.stdin.close(); assert holder.wait(timeout=5) == 0
    cases.append('actual_active_kernel_profile_lease_allows_nonstopping_status_but_denies_recovery')
    assert call('profiles')['profiles'] == [profile]
    assert call('cli', {'argv': ['photon-recovery', 'profiles']})['profiles'] == [profile]
    view = call('sources', {'profile': profile})['sources'][0]
    chosen = {'profile': profile, 'identity': view['id'], 'snapshot': view['snapshot_sha256'], 'note': 'fixture inspected old source', 'confirmed': True}
    assert call('purge', chosen) == {'error': 'authority-refused'}
    cases.append('actual_Root_and_private_worker_refuse_disposal_of_currently_approved_original')
    config['bindings'] = []; config['publication'] = secrets.token_hex(32); publish()
    view = call('sources', {'profile': profile})['sources'][0]; chosen['snapshot'] = view['snapshot_sha256']
    assert view['purge_allowed'] and not view['current_grant']
    receipt = call('purge', chosen); assert receipt['tombstones_retained'] and not receipt['message_sent']
    assert call('purge', chosen) == receipt
    assert source('inspect') == {'raw_bytes': 0, 'safe': '9', 'audit_count': 1}
    assert call('cli', {'argv': ['photon-recovery', 'purge-source', '--profile', profile, '--id', chosen['identity'],
        '--snapshot-sha256', chosen['snapshot'], '--note', chosen['note'], '--confirm-inspected']}) == receipt
    assert call('status')['result']['next_attempt'] == status['next_attempt']
    audit = [json.loads(line) for line in Path('/var/lib/haos-owner/audit.jsonl').read_text().splitlines()]
    assert any(row['kind'] == 'gateway.photon-source-disposal-intent' and row['owner_uid'] == '1000' for row in audit)
    assert any(row['kind'] == 'gateway.photon-owner-purge-source' and row.get('receipt') == receipt['receipt'] for row in audit)
    cases.append('actual_Root_intent_private_SQL_disposal_idempotent_audit_and_cursor_recovery_preserve_account_budget')
    cases.append('actual_nested_CLI_parser_and_Root_gateway_dispatch_reach_real_status_inventory_and_disposal_backend')
    Path('/run/fixture-active').touch()
    assert call('sources', {'profile': profile}) == {'error': 'root-backend-authority-refused'}
    Path('/run/fixture-active').unlink()
    cases.append('Root_mutation_and_inspection_require_quiescent_service_using_explicit_systemctl_state_fixture')
    assert source('schema-break') == {'missing_original_schema_preserved': True}
    assert call('sources', {'profile': profile}) == {'error': 'storage-unavailable'}
    assert source('schema-inspect') == {'missing_original_schema_preserved': True}
    cases.append('actual_missing_original_schema_is_refused_without_creating_a_fresh_empty_table_or_repairing_retained_data')
    for uid, groups in [(0, []), (65533, []), (65534, [0])]:
        result = subprocess.run(command(), input='{}', text=True, capture_output=True, user=uid, group=uid, extra_groups=groups,
            env=env, cwd=str(code), timeout=10)
        assert result.returncode != 0 and not result.stdout
    foreign = '''from haos import photon_owner_setup as owner
from haos.photon_owner_process import command
import subprocess
for action in [owner.profiles,lambda:owner.sources('photon-'+'a'*64),lambda:owner.status('phone'),lambda:owner.purge('x','x','x','fixture',confirmed=True)]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('private identity gained Root Owner backend')
r=subprocess.run(command(),input='{}',text=True,capture_output=True,timeout=10)
assert r.returncode!=0 and 'actual authenticated Root parent' in r.stderr
print('denied')
'''
    result = subprocess.run([str(runtime / 'bin/python'), '-E', '-s', '-c', foreign], text=True, capture_output=True, user=65534,
        group=65534, extra_groups=[], env=env, cwd=str(code), timeout=15)
    assert result.returncode == 0 and result.stdout == 'denied\n', result.stderr
    cases.append('actual_Root_foreign_UID_supplementary_Root_group_and_unprivileged_parent_cannot_impersonate_Owner_worker')
    hold_parent = subprocess.Popen([sys.executable, str(helper)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, env=env, cwd=str(code))
    hold_parent.stdin.write(json.dumps({'action': 'hold'}) + '\n'); hold_parent.stdin.close()
    try:
        deadline = time.monotonic() + 5
        while not Path('/run/held-worker.pid').exists():
            assert time.monotonic() < deadline; time.sleep(.01)
        pid = int(Path('/run/held-worker.pid').read_text())
        while True:
            proc = Path('/proc/' + str(pid) + '/status').read_text()
            if 'NoNewPrivs:\t1' in proc: break
            assert time.monotonic() < deadline; time.sleep(.01)
        assert 'Uid:\t65534\t65534\t65534\t65534' in proc
        hold_parent.kill(); hold_parent.wait(timeout=5)
        while Path('/proc/' + str(pid) + '/status').exists():
            text = Path('/proc/' + str(pid) + '/status').read_text()
            if 'State:\tZ' in text: break
            assert time.monotonic() < deadline; time.sleep(.01)
    finally:
        if hold_parent.poll() is None: hold_parent.kill(); hold_parent.wait(timeout=5)
    cases.append('actual_private_UID_NoNewPrivileges_and_kernel_parent_death_guard_stop_orphan_Owner_worker')
    assert not any(name.startswith(('plugins.', 'httpx', 'aiohttp')) for name in sys.modules)
    print(json.dumps({'passed': len(cases), 'cases': cases, 'actual_Root_backend_private_UID_SQLite_and_kernel': True,
        'substitution': 'explicit systemctl service-state executable only; no actual systemd/OS acceptance',
        'network_requested': False, 'optional_SDK_or_Hermes_imported': False, 'live_Photon_verified': False}, indent=2))


if __name__ == '__main__': main()
