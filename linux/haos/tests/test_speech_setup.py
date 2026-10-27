from types import SimpleNamespace

import pytest

from haos import speech_setup as setup


@pytest.mark.parametrize('action',[setup.status,setup.enable,setup.disable])
def test_speech_owner_actions_refuse_nonroot_before_service_or_files(monkeypatch,action):
    monkeypatch.setattr(setup.os,'geteuid',lambda:65533)
    def forbidden(*args,**kwargs):raise AssertionError('unauthorized owner action reached OS')
    monkeypatch.setattr(setup.subprocess,'run',forbidden)
    with pytest.raises(PermissionError):action()


def test_socket_status_accepts_real_socket_property_subset_and_checks_service_pids(monkeypatch):
    monkeypatch.setattr(setup.os,'geteuid',lambda:0)
    def execute(args,**kwargs):
        if args[1]=='stop':return SimpleNamespace(returncode=0)
        if args[-1].endswith('.socket'):return SimpleNamespace(stdout='LoadState=loaded\nActiveState=inactive\nResult=success\n')
        return SimpleNamespace(stdout='LoadState=loaded\nActiveState=inactive\nResult=success\nMainPID=123\nControlPID=0\nExecMainStatus=0\n')
    monkeypatch.setattr(setup.subprocess,'run',execute)
    assert setup.service_status('haos-speech.socket')['ActiveState']=='inactive'
    with pytest.raises(PermissionError,match='fully stopped'):setup.stop()


@pytest.mark.parametrize('value',[{'version':True,'enabled':True,'model':'tiny'},
    {'version':1,'enabled':1,'model':'tiny'},{'version':1,'enabled':True,'model':'arbitrary/path'},
    {'version':1,'enabled':True,'model':'tiny','command':'unreviewed'}])
def test_owner_speech_config_is_closed_typed_local_model(value):
    assert not setup.enabled_config(value)


def test_enable_refuses_missing_runtime_without_mutating_owner_configuration(monkeypatch,tmp_path):
    from contextlib import contextmanager
    config=tmp_path/'speech.json';config.write_text('retained configuration')
    @contextmanager
    def lock():yield
    monkeypatch.setattr(setup,'locked',lock);monkeypatch.setattr(setup,'CONFIG',config)
    monkeypatch.setattr(setup,'runtime_ready',lambda:False)
    with pytest.raises(PermissionError,match='pinned HAOS voice runtime'):setup.enable()
    assert config.read_text()=='retained configuration'
