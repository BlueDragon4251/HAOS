import base64
import hashlib
import os
from pathlib import Path

import pytest

from haos.application_session import read_export,session_action
from haos.application_protocol import action,receipt
from haos.gui_tool import save_application_artifact


def output(tmp_path):
    directory=tmp_path/'exports';directory.mkdir(mode=0o700)
    path=directory/'result.txt';path.write_bytes(b'actual private file bytes');path.chmod(0o600)
    return directory,path


def test_real_output_file_is_exact_hashed_bytes(tmp_path):
    _,path=output(tmp_path);value=read_export(tmp_path,'result.txt')
    assert base64.b64decode(value['base64'])==path.read_bytes()
    assert value['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert value['mime']=='application/octet-stream'


def test_export_is_private_verified_workspace_artifact_without_history_bytes(tmp_path):
    _,path=output(tmp_path);value=read_export(tmp_path,'result.txt')
    result=save_application_artifact(value,tmp_path/'agent-artifacts')
    saved=Path(result['path'])
    assert saved.read_bytes()==path.read_bytes() and saved.stat().st_mode&0o777==0o600
    assert saved.parent.stat().st_mode&0o777==0o700 and saved.name.endswith('.bin')
    assert 'base64' not in result and saved.name!='result.txt'
    with pytest.raises(ValueError):save_application_artifact(value|{'sha256':'0'*64},tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()
    public=tmp_path/'public';public.mkdir(mode=0o755);public.chmod(0o755)
    with pytest.raises(PermissionError):save_application_artifact(value,public)
    linked=tmp_path/'link';linked.symlink_to(saved.parent,target_is_directory=True)
    with pytest.raises(OSError):save_application_artifact(value,linked)


@pytest.mark.parametrize('name',['../owner','/etc/shadow','.hidden','a/b','a\n','x'*65,'../exports/file'])
def test_no_arbitrary_path_or_hidden_profile_export_is_accepted(name):
    with pytest.raises(PermissionError):session_action({'operation':'export','file':name})


def test_output_symlink_hardlink_public_permissions_and_size_are_denied(tmp_path):
    directory,path=output(tmp_path)
    (directory/'alias.txt').symlink_to(path)
    with pytest.raises(OSError):read_export(tmp_path,'alias.txt')
    os.link(path,directory/'hardlink.txt')
    with pytest.raises(PermissionError):read_export(tmp_path,'result.txt')
    (directory/'hardlink.txt').unlink();path.chmod(0o644)
    with pytest.raises(PermissionError):read_export(tmp_path,'result.txt')
    path.chmod(0o600);path.write_bytes(b'x'*1048577)
    with pytest.raises(PermissionError):read_export(tmp_path,'result.txt')


def test_output_directory_cannot_be_redirected(tmp_path):
    directory,_=output(tmp_path);directory.rename(tmp_path/'outside');directory.symlink_to(tmp_path/'outside')
    with pytest.raises(OSError):read_export(tmp_path,'result.txt')


def test_export_protocol_verifies_real_bytes_without_host_paths(tmp_path):
    import uuid
    _,path=output(tmp_path);instance=str(uuid.uuid4())
    assert action({'operation':'app.export','instance':instance,'file':'result.txt'})['file']=='result.txt'
    value={'instance':instance,**read_export(tmp_path,'result.txt')}
    assert receipt('app.export',value)==value
    for delta in ({'bytes':True},{'sha256':'a'*64},{'file':'../owner'},{'path':'/etc/haos'}):
        with pytest.raises((ValueError,PermissionError)):receipt('app.export',dict(value,**delta))
