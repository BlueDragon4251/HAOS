"""Owner-owned device grants, checked independently by viewer and controller."""
import hashlib
import ipaddress
import re
import time
import uuid

from .sandbox import trusted_json
from pathlib import Path

POLICY=Path('/etc/haos/remote-viewer.json')


def mission_id(value):
    if not isinstance(value,str) or str(uuid.UUID(value))!=value:
        raise PermissionError('explicit canonical mission identity required')
    return value


class RemotePolicy:
    def __init__(self,value):
        if not isinstance(value,dict) or set(value)!={'version','bind','port','requests_per_minute','bytes_per_minute','devices'} or type(value['version']) is not int or value['version']!=1:
            raise ValueError('closed remote observation policy required')
        if not isinstance(value['bind'],str) or '%' in value['bind']:
            raise ValueError('literal unscoped IP bind address required')
        ipaddress.ip_address(value['bind'])
        if (type(value['port']) is not int or not 1024<=value['port']<=65535
                or type(value['requests_per_minute']) is not int or not 1<=value['requests_per_minute']<=120
                or type(value['bytes_per_minute']) is not int or not 65536<=value['bytes_per_minute']<=32*1024*1024
                or not isinstance(value['devices'],list) or len(value['devices'])>16):
            raise ValueError('bounded remote listener and devices required')
        self.devices={};identities=set();self.value=value
        for device in value['devices']:
            if (not isinstance(device,dict) or set(device)!={'id','certificate_sha256','expires_at','missions','content','screenshots'}
                    or not isinstance(device['id'],str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',device['id'])
                    or not isinstance(device['certificate_sha256'],str) or not re.fullmatch(r'[a-f0-9]{64}',device['certificate_sha256'])
                    or type(device['expires_at']) not in {int,float} or not 0<device['expires_at']<2**40
                    or type(device['content']) is not bool or type(device['screenshots']) is not bool
                    or not isinstance(device['missions'],list) or not 1<=len(device['missions'])<=64
                    or len(set(device['missions']))!=len(device['missions'])):
                raise ValueError('explicit bounded remote device grant required')
            for mission in device['missions']:mission_id(mission)
            fingerprint=device['certificate_sha256']
            if fingerprint in self.devices or device['id'] in identities:
                raise ValueError('duplicate remote device identity')
            identities.add(device['id']);self.devices[fingerprint]=dict(device)

    def authorize(self,fingerprint,mission=None,*,now=None):
        device=self.devices.get(fingerprint)
        if not device or device['expires_at']<=(time.time() if now is None else now):
            raise PermissionError('remote device is unpaired, expired or revoked')
        if mission is not None and mission_id(mission) not in device['missions']:
            raise PermissionError('remote mission scope denied')
        return device


def load():
    return RemotePolicy(trusted_json(POLICY))


def certificate_identity(der):
    if not isinstance(der,bytes) or not 128<=len(der)<=16384:
        raise PermissionError('verified client certificate required')
    return hashlib.sha256(der).hexdigest()
