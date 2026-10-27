"""Authenticated local-owner activation of the fixed offline speech runtime."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
import time

from .policy import atomic_json
from .sandbox import trusted_json
from .speech import verify_model
from .speech_model import MODEL_ROOT,FILES,REVISION

CONFIG=Path('/etc/haos/speech.json')
ENGINE=Path('/etc/haos-speech')
LOCK=Path('/run/haos-speech-setup.lock')
CODE=Path('/usr/lib/haos')
UNITS=('haos-speech.socket','haos-speech.service')
VERSIONS={'faster-whisper':'1.2.1','ctranslate2':'4.7.1','av':'17.0.0'}
SETTINGS='stt:\n  provider: local\n  local:\n    device: cpu\n    compute_type: int8\nsecurity:\n  allow_lazy_installs: false\n'


def require_root():
    if os.geteuid()!=0:raise PermissionError('speech setup requires authenticated local owner authority')


def directory(path):
    path=Path(path)
    try:info=path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o755);path.chmod(0o755);info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise PermissionError('protected root-owned speech directory required')
    return path


@contextmanager
def locked():
    require_root()
    fd=os.open(LOCK,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o077:
            raise PermissionError('private owner speech lock required')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PermissionError('another owner speech operation is active') from None
        yield
    finally:os.close(fd)


def runtime_ready():
    require_root()
    try:
        for path in [CODE,CODE/'hermes',CODE/'hermes/.venv',CODE/'hermes/.venv/bin']:
            info=path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:return False
        executable=CODE/'hermes/.venv/bin/python';info=executable.resolve(strict=True).stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:return False
        account=pwd.getpwnam('haos-speech')
        if account.pw_uid<=0 or account.pw_gid<=0 or any(row.pw_uid==account.pw_uid and row.pw_name!='haos-speech' for row in pwd.getpwall()):return False
        script='import importlib.metadata,json,os,sys; print(json.dumps({"python":list(sys.version_info[:2]),"uid":os.geteuid(),"gid":os.getegid(),"groups":os.getgroups(),"packages":{name:importlib.metadata.version(name) for name in '+repr(list(VERSIONS))+'}}))'
        result=subprocess.run([str(executable),'-E','-s','-c',script],capture_output=True,text=True,timeout=15,
            user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd=str(CODE),env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
        return result.returncode==0 and len(result.stdout)<=4096 and json.loads(result.stdout)=={'python':[3,11],'uid':account.pw_uid,'gid':account.pw_gid,'groups':[],'packages':VERSIONS}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):return False


def service_status(unit):
    result=subprocess.run(['/usr/bin/systemctl','show','--property=LoadState,ActiveState,MainPID,ControlPID,Result,ExecMainStatus',unit],
        check=True,capture_output=True,text=True,timeout=15)
    if len(result.stdout)>4096:raise ValueError('speech service status exceeds bound')
    values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    allowed={'LoadState','ActiveState','MainPID','ControlPID','Result','ExecMainStatus'}
    required={'LoadState','ActiveState'} if unit.endswith('.socket') else allowed
    if not required<=set(values)<=allowed or any(not value or len(value)>128 or any(ord(c)<32 or ord(c)>126 for c in value) for value in values.values()):
        raise ValueError('invalid speech service status')
    return values


def stop():
    require_root()
    subprocess.run(['/usr/bin/systemctl','stop',*UNITS],check=True,capture_output=True,timeout=30)
    for unit in UNITS:
        value=service_status(unit)
        if (value['LoadState'] not in {'loaded','masked'} or value['ActiveState']!='inactive'
                or value.get('MainPID','0')!='0' or value.get('ControlPID','0')!='0'):
            raise PermissionError('speech workers must be fully stopped before model configuration')


def model_ready():
    try:
        verify_model(MODEL_ROOT)
        if any(path.stat().st_mode&0o005!=0o005 for path in [MODEL_ROOT.parent,MODEL_ROOT]):return False
        return all((MODEL_ROOT/name).stat().st_mode&0o004 for name in FILES)
    except (OSError,ValueError):return False


def enabled_config(value):
    return (isinstance(value,dict) and set(value)=={'version','enabled','model'}
        and type(value['version']) is int and value['version']==1 and value['enabled'] is True and value['model']=='tiny')


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def status():
    require_root()
    enabled=False
    if CONFIG.exists() or CONFIG.is_symlink():
        enabled=enabled_config(trusted_json(CONFIG))
        if not enabled:raise ValueError('unsupported owner speech configuration; preserve and inspect existing data')
    return {'enabled':enabled,'runtime_ready':runtime_ready(),'model_ready':bool(model_ready()),
        'model':'tiny','model_revision':REVISION,'model_download_bytes':sum(size for size,_ in FILES.values()),
        'services':{unit:service_status(unit) for unit in UNITS},'sender_approval_is_separate':True}


def enable():
    from .owner import audit
    with locked():
        if not runtime_ready():raise PermissionError('rebuild the pinned HAOS voice runtime before activating speech')
        if CONFIG.exists() or CONFIG.is_symlink():
            if not enabled_config(trusted_json(CONFIG)):
                raise PermissionError('existing speech configuration requires owner inspection')
        if any(service_status(unit)['LoadState']!='loaded' for unit in UNITS):
            raise PermissionError('install the speech units and inspect any administrator mask before activation')
        audit('speech.enable-requested',{'model_revision':REVISION})
        stop()
        directory(MODEL_ROOT.parent);directory(MODEL_ROOT)
        from .speech_download import public_model
        try:public_model(MODEL_ROOT)
        except Exception:raise RuntimeError('reviewed public speech model download unavailable; inspect network, disk and retained files') from None
        if not model_ready():raise PermissionError('reviewed speech model integrity or consumer permissions invalid')
        directory(ENGINE)
        settings=ENGINE/'config.yaml'
        if settings.exists() or settings.is_symlink():
            info=settings.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o022
                    or settings.read_text()!=SETTINGS):raise PermissionError('existing speech engine settings require owner inspection')
        else:
            fd,temporary=tempfile.mkstemp(dir=ENGINE,prefix='.haos-speech-')
            try:
                os.fchmod(fd,0o644)
                with os.fdopen(fd,'w') as output:output.write(SETTINGS);output.flush();os.fsync(output.fileno())
                os.replace(temporary,settings);sync_directory(ENGINE)
            finally:Path(temporary).unlink(missing_ok=True)
        directory(CONFIG.parent)
        atomic_json(CONFIG,{'version':1,'enabled':True,'model':'tiny'},mode=0o644)
        subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True,capture_output=True,timeout=15)
        subprocess.run(['/usr/bin/systemctl','enable','--now','haos-speech.socket'],check=True,capture_output=True,timeout=30)
        audit('speech.enabled',{'model_revision':REVISION})
        return status()


def disable():
    from .owner import audit
    with locked():
        audit('speech.disable-requested',{})
        stop()
        subprocess.run(['/usr/bin/systemctl','disable','haos-speech.socket'],check=True,capture_output=True,timeout=15)
        if CONFIG.exists() or CONFIG.is_symlink():
            trusted_json(CONFIG)
            retained=CONFIG.with_name('speech-disabled-'+str(time.time_ns())+'.json')
            os.rename(CONFIG,retained);sync_directory(CONFIG.parent)
        audit('speech.disabled',{'models_and_sender_grants_preserved':True})
        return status()
