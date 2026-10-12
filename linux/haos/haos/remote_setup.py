"""Fixed owner-authenticated TLS provisioning and explicit device/mission grants."""
import grp
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

from .enrollment import protected_directory
from .policy import atomic_json
from .remote_policy import POLICY,RemotePolicy,load
from .remote_http import tls_context

PRIVATE=Path('/etc/haos/remote-private')
UNIT='haos-remote-viewer.service'


def root_file(path,*,secret=False):
    path=Path(path)
    if not path.is_absolute():raise PermissionError('absolute protected TLS input required')
    protected_directory(path.parent)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        metadata=os.fstat(fd)
        if (metadata.st_uid!=0 or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1
                or metadata.st_mode&(0o077 if secret else 0o022) or not 1<=metadata.st_size<=32768):
            raise PermissionError('protected owner TLS input required')
        data=os.read(fd,32769)
        if len(data)>32768:raise ValueError('TLS input size limit exceeded')
        return data
    finally:os.close(fd)


def write_private(path,data):
    protected_directory(path.parent)
    fd,temporary=tempfile.mkstemp(prefix='.remote-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600);stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:Path(temporary).unlink(missing_ok=True)


def require_stopped():
    result=subprocess.run(['/usr/bin/systemctl','show',UNIT,'--property=ActiveState,MainPID,ControlPID'],check=True,capture_output=True,text=True,timeout=5)
    fields=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if fields!={'ActiveState':'inactive','MainPID':'0','ControlPID':'0'}:
        raise PermissionError('stop the remote viewer before replacing TLS identity or bind policy')


def persist(value):
    RemotePolicy(value)
    protected_directory(POLICY.parent)
    atomic_json(POLICY,value,mode=0o640,gid=grp.getgrnam('haos-viewer').gr_gid)


def owner_remote(args):
    if os.geteuid()!=0:raise PermissionError('authenticated owner remote setup required')
    protected_directory(POLICY.parent)
    fd=os.open(POLICY.with_suffix('.lock'),os.O_CREAT|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    try:
        metadata=os.fstat(fd)
        if metadata.st_uid!=0 or metadata.st_mode&0o077 or metadata.st_nlink!=1 or not stat.S_ISREG(metadata.st_mode):
            raise PermissionError('root-private remote authority lock required')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return owner_remote_locked(args)
    finally:os.close(fd)


def owner_remote_locked(args):
    from .owner import audit
    action=args.remote_action
    if action in {'start','stop'}:
        if action=='start':load()
        subprocess.run(['/usr/bin/systemctl',action,UNIT],check=True,timeout=15)
        audit('remote.'+action,{})
        return {'action':action}
    if action=='configure':
        require_stopped()
        if POLICY.exists():raise PermissionError('remote listener already configured; stop and inspect before manual identity replacement')
        value={'version':1,'bind':args.bind,'port':args.port,'requests_per_minute':args.requests_per_minute,
            'bytes_per_minute':args.bytes_per_minute,'devices':[]}
        RemotePolicy(value)
        cert=root_file(args.server_cert);key=root_file(args.server_key,secret=True);ca=root_file(args.client_ca)
        PRIVATE.mkdir(mode=0o700,exist_ok=True);protected_directory(PRIVATE)
        if PRIVATE.stat().st_mode&0o077:raise PermissionError('root-private TLS storage required')
        for filename,data in [('server.pem',cert),('server-key.pem',key),('clients-ca.pem',ca)]:write_private(PRIVATE/filename,data)
        tls_context(str(PRIVATE/'server.pem'),str(PRIVATE/'server-key.pem'),str(PRIVATE/'clients-ca.pem'))
        persist(value)
        audit('remote.configured',{'bind':args.bind,'port':args.port})
        return {'configured':True,'started':False,'devices':0}
    policy=load();value=policy.value
    if action=='status':return {'policy':value,'transport':'TLS1.3 with mandatory paired client certificates','rights':'observation only'}
    if action=='pair':
        cert=root_file(args.certificate)
        # Validate purpose/chain before persisting a fingerprint. Public cert
        # input stays in a protected file; no device private key is imported.
        result=subprocess.run(['/usr/bin/openssl','verify','-purpose','sslclient','-CAfile',str(PRIVATE/'clients-ca.pem'),str(args.certificate)],
            capture_output=True,timeout=5,check=False)
        if result.returncode:raise PermissionError('device client certificate does not match owner CA')
        der=subprocess.run(['/usr/bin/openssl','x509','-outform','DER'],input=cert,capture_output=True,check=True,timeout=5).stdout
        if not 128<=len(der)<=16384:raise ValueError('bounded device certificate required')
        device={'id':args.id,'certificate_sha256':hashlib.sha256(der).hexdigest(),'expires_at':time.time()+args.hours*3600,
            'missions':args.mission,'content':args.share_content,'screenshots':args.share_screenshots}
        if type(args.hours) is not int or not 1<=args.hours<=24:raise ValueError('device grant must last 1-24 hours')
        if any(d['id']==args.id for d in value['devices']):raise PermissionError('revoke an existing device before replacing its grant')
        value['devices'].append(device);persist(value)
        audit('remote.paired',{'device':args.id,'missions':args.mission,'expires_at':device['expires_at'],
            'content':args.share_content,'screenshots':args.share_screenshots})
        return {'paired':args.id,'expires_at':device['expires_at'],'rights':'observation only'}
    if action=='revoke':
        if not any(d['id']==args.id for d in value['devices']):raise KeyError('unknown paired device')
        value['devices']=[d for d in value['devices'] if d['id']!=args.id];persist(value)
        audit('remote.revoked',{'device':args.id})
        return {'revoked':args.id,'next_request_denied':True}
    raise PermissionError('unknown owner remote operation')
