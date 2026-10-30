"""Durable public app identity for private Google journals; never an API credential."""
import json
import os
from pathlib import Path
import secrets
import stat

from .gateway import Conflict,digest
from .gateway_google_chat import PROJECT,EMAIL,credentials,resource

NAME='account-identity.json'


def descriptor(value):
    account=credentials(value)
    return validate({'version':1,'project_id':account['service_account']['project_id'],
        'service_account_email':account['service_account']['client_email'],'bot_user':account['bot_user']})


def validate(value):
    if (not isinstance(value,dict) or set(value)!={'version','project_id','service_account_email','bot_user'}
            or type(value['version']) is not int or value['version']!=1
            or not isinstance(value['project_id'],str) or not PROJECT.fullmatch(value['project_id'])
            or not isinstance(value['service_account_email'],str) or not EMAIL.fullmatch(value['service_account_email'])
            or not value['service_account_email'].endswith('@'+value['project_id']+'.iam.gserviceaccount.com')):
        raise ValueError('closed public Google app identity required; no credentials or external paths')
    resource(value['bot_user'],'user');return dict(value)


def account_scope(value):
    value=validate(value)
    return 'google-chat:'+digest([value['project_id'],value['service_account_email'],value['bot_user']])


def _directory(profile):
    from .gateway_runtime import require_runtime_identity
    from .gateway_line_profile import _directory as private_directory
    require_runtime_identity();profile=Path(profile);private_directory(profile)
    return profile


def load(profile):
    profile=_directory(profile)
    fd=os.open(profile/NAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        own=os.fstat(fd)
        if (not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_gid!=os.getegid()
                or stat.S_IMODE(own.st_mode)!=0o600 or own.st_nlink!=1 or not 1<=own.st_size<=2048):
            raise PermissionError('private immutable Google identity descriptor metadata required')
        data=os.read(fd,2049)
        if len(data)!=own.st_size or os.read(fd,1):raise Conflict('Google public identity changed during read')
    finally:os.close(fd)
    from .gateway_line_ingress import _object
    value=validate(json.loads(data,object_pairs_hook=_object))
    if data!=_encoded(value) or profile.name!='google-chat-'+digest(account_scope(value)):
        raise Conflict('Google public identity or private profile association changed; preserve and inspect')
    return value


def _encoded(value):return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()


def remember(profile,account):
    """After the profile lease/current Root validation; preserve existing records."""
    profile=_directory(profile);value=descriptor(account)
    if profile.name!='google-chat-'+digest(account_scope(value)):
        raise PermissionError('public Google identity must match its original private profile')
    try:previous=load(profile)
    except FileNotFoundError:pass
    else:
        if previous!=value:raise Conflict('retained Google identity differs; never replace historical custody')
        return value
    directory=os.open(profile,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    temporary='.account-identity-'+secrets.token_hex(16)
    fd=None;created=False
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=directory)
        created=True;data=_encoded(value);offset=0
        while offset<len(data):
            written=os.write(fd,data[offset:])
            if written<=0:raise OSError('incomplete private Google identity metadata write')
            offset+=written
        os.fsync(fd);os.close(fd);fd=None
        try:os.link(temporary,NAME,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
        except FileExistsError:pass
        os.unlink(temporary,dir_fd=directory);created=False;os.fsync(directory)
    finally:
        if fd is not None:os.close(fd)
        if created:
            try:os.unlink(temporary,dir_fd=directory)
            except FileNotFoundError:pass
        os.close(directory)
    if load(profile)!=value:raise Conflict('Google identity was concurrently changed; preserve and inspect')
    return value
