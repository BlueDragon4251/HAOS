"""Actual-root owner publication with fixture service control; UID RPC tested separately."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def exercise():
    assert os.geteuid()==0 and os.getpid()==1 and Path('/.dockerenv').exists()
    from haos import speech_setup as setup
    from haos.speech_model import FILES,MODEL_ROOT
    original=setup.subprocess.run
    runtime=Path('/usr/lib/haos/hermes/.venv')
    original(['/usr/local/bin/python3','-m','venv','--without-pip',str(runtime)],check=True)
    site=runtime/'lib/python3.11/site-packages'
    (site/'fixture_frozen_sdk.pth').write_text('/sdk\n/usr/lib/haos/hermes-source\n')
    state={'haos-speech.socket':'inactive','haos-speech.service':'inactive'};calls=[]
    def execute(args,**kwargs):
        if args[0]!='/usr/bin/systemctl':return original(args,**kwargs)
        calls.append(args)
        if args[1]=='show':
            unit=args[-1];value={'LoadState':'loaded','ActiveState':state[unit],'Result':'success'}
            if unit.endswith('.service'):value.update(MainPID='0',ControlPID='0',ExecMainStatus='0')
            return SimpleNamespace(stdout=''.join(key+'='+value+'\n' for key,value in value.items()),returncode=0)
        if args[1]=='stop':
            for unit in args[2:]:state[unit]='inactive'
        if args[1]=='enable':state['haos-speech.socket']='active'
        return SimpleNamespace(stdout='',returncode=0)
    cases=[]
    with patch.object(setup.subprocess,'run',execute):
        assert setup.runtime_ready() and setup.model_ready()
        before={name:(MODEL_ROOT/name).stat().st_ino for name in FILES}
        active=setup.enable()
        assert active['enabled'] and active['model_ready'] and active['runtime_ready']
        config=json.loads(setup.CONFIG.read_text());assert config=={'version':1,'enabled':True,'model':'tiny'}
        assert setup.CONFIG.stat().st_uid==0 and setup.CONFIG.stat().st_mode&0o777==0o644
        assert (setup.ENGINE/'config.yaml').read_text()==setup.SETTINGS
        assert before=={name:(MODEL_ROOT/name).stat().st_ino for name in FILES}
        cases.append('actual_root_owner_activation_checks_real_frozen_sdk_and_model_then_publishes_closed_readable_config_without_redownload')
        disabled=setup.disable()
        assert not disabled['enabled'] and disabled['model_ready'] and not setup.CONFIG.exists()
        archives=list(setup.CONFIG.parent.glob('speech-disabled-*.json'))
        assert len(archives)==1 and json.loads(archives[0].read_text())==config
        assert before=={name:(MODEL_ROOT/name).stat().st_ino for name in FILES}
        cases.append('actual_root_owner_disable_archives_configuration_and_preserves_all_model_data')
        with patch.dict(setup.VERSIONS,{'av':'unreviewed-version'}):
            assert not setup.runtime_ready()
            try:setup.enable()
            except PermissionError:pass
            else:raise AssertionError('unexpected native runtime version activated')
        assert not setup.CONFIG.exists() and len(list(setup.CONFIG.parent.glob('speech-disabled-*.json')))==1
        assert any(row[1:]==['enable','--now','haos-speech.socket'] for row in calls)
        cases.append('actual_sdk_metadata_version_mismatch_refuses_owner_activation_without_mutating_retained_settings')
    return cases
