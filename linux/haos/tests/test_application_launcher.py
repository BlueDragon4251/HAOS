import base64
import json
import os
from pathlib import Path
import time
import uuid

import pytest

from haos.application_launcher import ApplicationLauncher, canonical_id, launch_command, running_mission
from haos.application_session import ApplicationSession
from haos.store import MissionStore


def grant():
    return {'id':'mission-terminal','class':'terminal','executable':'/usr/bin/foot','sha256':'a'*64,
            'argv':['/usr/bin/bash','--noprofile','--norc'],'memory_mib':512,'runtime_seconds':60}


def test_application_runs_as_a_bounded_distinct_uid_without_host_home_network_or_devices():
    mission, request = str(uuid.uuid4()), str(uuid.uuid4())
    command = launch_command(grant(), mission, request, Path('/run/haos-applications')/request)
    properties = dict(a.removeprefix('--property=').split('=',1) for a in command if a.startswith('--property='))
    assert properties['DynamicUser']=='yes' and properties['User'] not in {'root','hermes','haos-agent','haos-control'}
    assert properties['RootDirectory']==str(Path('/run/haos-applications')/request)
    assert properties['BindReadOnlyPaths'].startswith('/usr:/usr /etc/fonts:/etc/fonts ')
    assert properties['BindPaths']==f'/run/haos-app-{request.replace("-", "")}:/home/mission'
    assert properties['PrivateNetwork']=='yes' and properties['PrivateDevices']=='yes'
    assert properties['RestrictAddressFamilies']=='AF_UNIX' and properties['RestrictNamespaces']=='yes'
    assert properties['NoNewPrivileges']=='yes' and properties['CapabilityBoundingSet']==properties['AmbientCapabilities']==''
    assert properties['MemoryMax']=='512M' and properties['MemorySwapMax']=='0'
    assert properties['TasksMax']=='64' and properties['RuntimeMaxSec']=='60'
    assert properties['KillMode']=='control-group' and properties['ExitType']=='cgroup' and properties['Delegate']=='no'
    assert properties['Restart']=='no' and properties['StandardOutput']==properties['StandardError']=='null'
    assert not any(a.startswith('--setenv') for a in command)
    assert command[-4:-1]==['/usr/bin/python3','-I','/session.py']
    assert json.loads(base64.b64decode(command[-1]))=={'executable':'/usr/bin/foot','argv':grant()['argv']}


@pytest.mark.parametrize('bad',['../owner','ROOT','',True,'00000000000000000000000000000000'])
def test_root_unit_identity_cannot_select_another_service_or_directory(bad):
    with pytest.raises((ValueError,TypeError,AttributeError)):
        canonical_id(bad)


@pytest.mark.skipif(os.geteuid()==0,reason='actual negative unprivileged authority')
def test_unprivileged_application_cannot_use_launch_inspection_or_termination(tmp_path):
    with pytest.raises(PermissionError):
        ApplicationLauncher(state=tmp_path/'state',runtime=tmp_path/'run')
    launcher=object.__new__(ApplicationLauncher)
    for method,args in [(launcher.start,('terminal',str(uuid.uuid4()),str(uuid.uuid4()))),(launcher.record,(str(uuid.uuid4()),)),(launcher.stop,(str(uuid.uuid4()),))]:
        with pytest.raises(PermissionError):
            method(*args,**({'ledger_uid':os.geteuid()} if method==launcher.start else {}))
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
