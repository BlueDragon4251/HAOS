import os
import uuid

import pytest

from haos.application_authority import ActionNonces,ApplicationAuthority


@pytest.mark.skipif(os.geteuid()==0,reason='requires actual unprivileged process')
def test_an_agent_cannot_create_or_use_independent_root_action_authority(tmp_path):
    with pytest.raises(PermissionError):ActionNonces(tmp_path/'root-actions.db')
    nonces=object.__new__(ActionNonces)
    for call in (lambda:nonces.admit(str(uuid.uuid4()),str(uuid.uuid4()),{'operation':'app.start','program':'approved'}),
                 lambda:nonces.settle(str(uuid.uuid4()),'succeeded'),nonces.close):
        with pytest.raises(PermissionError):call()
    with pytest.raises(PermissionError):ApplicationAuthority(None,None,tmp_path/'missions.db',os.geteuid())
    authority=object.__new__(ApplicationAuthority)
    for call in (lambda:authority.dispatch({}),authority.reconcile):
        with pytest.raises(PermissionError):call()
    assert not list(tmp_path.iterdir())
