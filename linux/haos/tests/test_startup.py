import json
from types import SimpleNamespace

import pytest

from haos.startup import StartupDiagnosis,stack_identity


def frame(filename,function='load',previous=None):
    return SimpleNamespace(f_code=SimpleNamespace(co_filename=filename,co_name=function),
        f_lineno=42,f_back=previous,f_locals={'secret':'must-never-leave'})


def test_diagnosis_only_exports_installed_code_identity():
    value=stack_identity(frame('/workspace/customer-secret.py',previous=frame('/usr/lib/haos/serve.py')))
    assert value==[{'module':'serve.py','function':'load','line':42}]
    assert 'must-never-leave' not in json.dumps(value)


@pytest.mark.parametrize('path',['/usr/lib/haos/../secret.py','/home/agent/secret.py','/usr/lib/haos/user token.py'])
def test_private_or_noncanonical_stack_paths_are_excluded(path):
    assert stack_identity(frame(path))==[]


def test_only_fixed_startup_phases_can_be_logged(capsys):
    diagnosis=StartupDiagnosis(9119)
    with pytest.raises(ValueError):diagnosis.mark('secret-goal')
    assert not capsys.readouterr().out
    diagnosis.mark('web-import')
    assert json.loads(capsys.readouterr().out)=={'event':'backend.startup','stage':'web-import'}
