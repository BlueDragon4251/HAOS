import os
from pathlib import Path
import time
import uuid

import pytest

from haos.application_launcher import ApplicationLauncher, canonical_id, grant_digest, launch_command, running_mission,guardian_unit,drop_ledger_identity,create_rootfs
from haos.application_session import ApplicationSession,session_action
from haos.applications import validate_application
from haos.store import MissionStore


def grant():
    return {'id':'mission-terminal','class':'terminal','executable':'/usr/bin/foot','sha256':'a'*64,
            'argv':['/usr/bin/bash','--noprofile','--norc'],'memory_mib':512,'runtime_seconds':60}


def test_application_runs_as_a_bounded_distinct_uid_without_host_home_network_or_devices():
    mission, request = str(uuid.uuid4()), str(uuid.uuid4())
    command = launch_command(grant(), mission, request, Path('/run/haos-applications')/request)
    properties = dict(a.removeprefix('--property=').split('=',1) for a in command if a.startswith('--property='))
    assert properties['DynamicUser']=='yes' and properties['User'] not in {'root','hermes','haos-agent','haos-control'}
    assert properties['BindsTo']==properties['After']=='haos-applications.service'
    assert properties['RootDirectory']==str(Path('/run/haos-applications')/request)
    assert properties['BindReadOnlyPaths'].startswith('/usr:/usr /etc/fonts:/etc/fonts ')
    assert properties['BindPaths']==f'/run/haos-app-{request.replace("-", "")}:/home/mission'
    assert properties['PrivateNetwork']=='yes' and properties['PrivateDevices']=='yes'
    assert properties['RestrictAddressFamilies']=='AF_UNIX' and properties['RestrictNamespaces']=='yes'
    assert properties['NoNewPrivileges']=='yes' and properties['CapabilityBoundingSet']==properties['AmbientCapabilities']==''
    assert properties['MemoryMax']=='512M' and properties['MemorySwapMax']=='0'
    assert properties['TasksMax']=='64' and properties['RuntimeMaxSec']=='60'
    assert properties['KillMode']=='control-group' and properties['ExitType']=='cgroup' and properties['Delegate']=='no'
    assert properties['Restart']=='no' and properties['StandardOutput']=='journal' and properties['StandardError']=='null'
    assert not any(a.startswith('--setenv') for a in command)
    assert command[-3:]==['/usr/bin/python3','-I','/session.py']
    assert properties['LoadCredential']==f'launch:/run/haos-applications/{request}/launch.json'
    assert all(value not in command for value in grant()['argv'])


@pytest.mark.parametrize('bad',['../owner','ROOT','',True,'00000000000000000000000000000000'])
def test_root_unit_identity_cannot_select_another_service_or_directory(bad):
    with pytest.raises((ValueError,TypeError,AttributeError)):
        canonical_id(bad)


@pytest.mark.skipif(os.geteuid()==0,reason='actual negative unprivileged authority')
def test_unprivileged_application_cannot_use_launch_inspection_or_termination(tmp_path):
    with pytest.raises(PermissionError):
        ApplicationLauncher(state=tmp_path/'state',runtime=tmp_path/'run')
    launcher=object.__new__(ApplicationLauncher)
    for method,args in [(launcher.start,('terminal',str(uuid.uuid4()),str(uuid.uuid4()))),(launcher.record,(str(uuid.uuid4()),)),(launcher.stop,(str(uuid.uuid4()),)),
                        (launcher.unit_state,(str(uuid.uuid4()),)),(launcher.execute,(str(uuid.uuid4()),str(uuid.uuid4()),{'operation':'state'}))]:
        with pytest.raises(PermissionError):
            method(*args,**({'ledger_uid':os.geteuid()} if method in {launcher.start,launcher.execute} else {}))
    assert not list(tmp_path.iterdir())


@pytest.fixture
def ledger(tmp_path):
    if os.geteuid()==0: pytest.skip('ledger belongs to an actual separate unprivileged UID')
    path=tmp_path/'missions.db';store=MissionStore(path);path.chmod(0o600);tmp_path.chmod(0o700)
    mission=store.create('owner-fixture','test-app','providerless authority fixture')
    store.claim();store.session(mission['id'],'offline-authority-scope','offline-stored');store.dispatching(mission['id'])
    yield store,path,mission['id']
    store.close()


def test_actual_wal_ledger_requires_a_live_dispatched_mission_and_preserves_cancel(ledger):
    store,path,mission=ledger
    running_mission(path,mission,os.geteuid())
    store.request_cancel(mission,'owner-fixture')
    with pytest.raises(PermissionError): running_mission(path,mission,os.geteuid())


@pytest.mark.parametrize('change',["state='queued'","state='blocked'","phase='session-created'","session_id=NULL","deadline=1"])
def test_inactive_pre_dispatch_ambiguous_or_expired_ledger_cannot_authorize_gui(ledger,change):
    store,path,mission=ledger;store.db.execute('UPDATE missions SET '+change+' WHERE id=?',(mission,))
    with pytest.raises(PermissionError): running_mission(path,mission,os.geteuid())


def test_mutable_alias_and_public_ledger_are_not_authority(ledger):
    _,path,mission=ledger;alias=path.with_name('alias.db');alias.symlink_to(path)
    with pytest.raises(PermissionError): running_mission(alias,mission,os.geteuid())
    path.chmod(0o644)
    with pytest.raises(PermissionError): running_mission(path,mission,os.geteuid())


@pytest.mark.parametrize('action',[{'operation':'shell','command':'id'}, {'operation':'capture','path':'/etc/haos'},
    {'operation':'key','key':'Control+V'},{'operation':'key','key':'Super'},
    {'operation':'type','text':'\n'},{'operation':'type','text':'a'*4097}])
def test_session_denies_commands_global_shortcuts_clipboard_files_and_unbounded_text(action):
    session=object.__new__(ApplicationSession)
    class Live:
        def poll(self): return None
    session.compositor=Live()
    with pytest.raises((ValueError,PermissionError)):
        session.execute(action)


def test_real_keyboard_protocol_budget_is_checked_before_partial_input():
    assert session_action({'operation':'type','text':'a'*512})['text']=='a'*512
    for text in ('a'*513,'é'*257,'x\x7f'):
        with pytest.raises(ValueError): session_action({'operation':'type','text':text})


def test_multiple_private_windows_cannot_authorize_implicit_dialog_focus():
    session=object.__new__(ApplicationSession)
    class Live:
        def poll(self): return None
    session.compositor=Live();session.wlrctl='/usr/bin/wlrctl'
    calls=[]
    def helper(argv):
        calls.append(argv);return b'editor: document\neditor: dialog\n'
    session.helper=helper
    with pytest.raises(PermissionError):session.execute({'operation':'focus'})
    assert calls==[['/usr/bin/wlrctl','toplevel','list']]


@pytest.mark.parametrize('argument',['--password','--api-key=value','--access-token',
    'https://user:pass@example.invalid/', 'Bearer '+'A'*32, 'sk-'+'A'*32])
def test_application_manifest_cannot_be_used_as_a_credential_argv_channel(argument):
    with pytest.raises(PermissionError):validate_application(dict(grant(),argv=[argument]))


def test_application_authority_identity_includes_limits_and_fixed_arguments():
    approval=grant();digest=grant_digest(approval)
    assert grant_digest(dict(reversed(list(approval.items()))))==digest
    for delta in ({'memory_mib':128},{'runtime_seconds':1},{'argv':['--different-private-context']},{'class':'utility'}):
        assert grant_digest(dict(approval,**delta))!=digest


@pytest.mark.parametrize('value',['herald-os.service','haos-hermes.service','../../owner','',None,'haos-app-fixture-'+'a'*32+'.service'])
def test_an_agent_cannot_choose_a_different_or_fake_application_guardian(value):
    with pytest.raises(PermissionError):guardian_unit(value)


@pytest.mark.parametrize('uid,gid',[(0,1000),(1000,0),(-1,1000),(True,1000),(1000,True)])
def test_ledger_identity_may_never_retain_root_or_ambiguous_ids(uid,gid):
    with pytest.raises(PermissionError):drop_ledger_identity(uid,gid)


def test_real_rootfs_directory_traversal_survives_private_production_umask(tmp_path):
    parent=tmp_path/'private-broker';parent.mkdir(mode=0o700)
    root=parent/'instance';original=os.umask(0o077)
    try:create_rootfs(root)
    finally:os.umask(original)
    assert parent.stat().st_mode&0o777==0o700
    for path in (root,root/'home',root/'home/mission',root/'usr',root/'etc/fonts',root/'run',root/'proc'):
        assert path.is_dir() and path.stat().st_mode&0o777==0o755
    assert not (root/'etc/passwd').exists() and not (root/'etc/haos').exists()
    with pytest.raises(FileExistsError):create_rootfs(root)
