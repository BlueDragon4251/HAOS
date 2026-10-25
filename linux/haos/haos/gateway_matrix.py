"""Private Matrix identity/crypto safeguards; public HAOS gateway stays disabled."""
import os
from pathlib import Path
import stat
from types import MethodType


def private_store(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute private Matrix profile path required')
    parent=path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.geteuid() or parent.st_mode&0o077:
        raise PermissionError('Matrix profile parent must belong privately to this identity')
    try:path.mkdir(mode=0o700)
    except FileExistsError:pass
    own=path.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077:
        raise PermissionError('Matrix profile must belong privately to this identity')
    # Never delete, deserialize or silently migrate an existing recovery file.
    if os.path.lexists(path/'crypto_store.pickle'):
        raise PermissionError('legacy Matrix recovery material requires explicit owner migration; retained unchanged')
    for name in ('crypto.db','crypto.db-wal','crypto.db-shm'):
        try:info=(path/name).lstat()
        except FileNotFoundError:continue
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid()
                or info.st_mode&0o077 or info.st_nlink!=1):
            raise PermissionError('Matrix crypto files must be private regular single-link identity files')
    return path


def protect_crypto(adapter, store_dir, *, recovery_key=None):
    """Scope one actual native adapter; no global patches or implicit owner reset.

    A later approved factory must supply a stable isolated identity profile and
    retain these hooks around actual native auth/setup, before any sync dispatch.
    """
    expected_user,expected_device=adapter._user_id,adapter._device_id
    if (not isinstance(expected_user,str) or not expected_user.startswith('@') or ':' not in expected_user
            or not 1<=len(expected_user.encode())<=255 or any(ord(c)<32 or ord(c)==127 for c in expected_user)
            or not isinstance(expected_device,str) or not 1<=len(expected_device.encode())<=255
            or any(ord(c)<32 or ord(c)==127 for c in expected_device)):
        raise ValueError('explicit Matrix user and stable device identity required')
    if recovery_key is not None and (not isinstance(recovery_key,str) or not 1<=len(recovery_key)<=4096):
        raise ValueError('bounded private Matrix recovery material required')
    path=Path(store_dir)
    original_auth=adapter._connect_authenticate
    original_setup=adapter._connect_setup_e2ee
    adapter._e2ee_mode='required';adapter._encryption=True
    adapter._haos_cross_signing_verified=False

    def resolve(self):
        self._store_dir=private_store(path)
        return self._store_dir

    async def authenticate(self,client,api):
        if not await original_auth(client,api):return False
        # The native builder may substitute the configured device when whoami
        # omits one. Configuration alone is not a proof of token ownership.
        proof=await client.whoami()
        if (str(proof.user_id)!=expected_user or str(proof.device_id or '')!=expected_device
                or str(client.mxid)!=expected_user or str(client.device_id or '')!=expected_device
                or getattr(self,'_device_id_unverified',False)):
            return await self._abort_connect(api)
        return True

    async def retain_device(self,store,device_id):
        if str(device_id or '')!=expected_device:
            raise PermissionError('Matrix device differs from the approved identity')
        previous=await store.get_device_id()
        if previous and str(previous)!=expected_device:
            raise PermissionError('Matrix device changed; explicit owner migration required; stored keys preserved')
        return False

    async def retain_pickle(self,store,_db,_account,_key):
        # A wrong key must fail. Guessing old keys and rewriting stored sessions
        # is an independent owner migration, not an automatic login operation.
        await store.get_account()
        return True

    def matches(keys,client,olm):
        if keys is None:return False
        actual={str(k):str(v) for k,v in (keys.keys or {}).items()}
        return (str(keys.user_id)==expected_user and str(keys.device_id)==expected_device
            and str(client.mxid)==expected_user and str(client.device_id)==expected_device
            and actual.get('ed25519:'+expected_device)==str(olm.account.signing_key)
            and actual.get('curve25519:'+expected_device)==str(olm.account.identity_key))

    async def verify(self,client,olm):
        if (str(client.mxid)!=expected_user or str(client.device_id or '')!=expected_device
                or getattr(self,'_device_id_unverified',False)):return False
        keys=await self._query_own_device_keys(client)
        if keys is None:
            # Initial publication only. Existing mismatched remote keys are never
            # deleted or replaced to force an otherwise-failed enrollment.
            await olm.share_keys()
            keys=await self._query_own_device_keys(client)
        return matches(keys,client,olm)

    async def cross_sign(self,olm,_client):
        if recovery_key is not None:
            try:await olm.verify_with_recovery_key(recovery_key)
            except Exception:
                raise PermissionError('Matrix recovery verification failed; owner material retained') from None
            self._haos_cross_signing_verified=True
        # No auto-bootstrap, recovery-file overwrite or fabricated verification.

    async def setup(self,client,api,state_store):
        self._resolve_store_dir()
        if str(client.mxid)!=expected_user or str(client.device_id or '')!=expected_device:
            return await self._abort_connect(api)
        result=await original_setup(client,api,state_store)
        if result:
            from mautrix.types import TrustState
            crypto=client.crypto
            if crypto is None:raise PermissionError('required Matrix encryption is unavailable')
            crypto.share_keys_min_trust=TrustState.VERIFIED
            crypto.send_keys_min_trust=TrustState.VERIFIED
            async def no_unsolicited_keys(_device,_request):return False
            crypto.allow_key_share=no_unsolicited_keys
        return result

    for name,method in {'_resolve_store_dir':resolve,'_connect_authenticate':authenticate,
            '_reset_crypto_store_if_device_changed':retain_device,'_migrate_legacy_crypto_pickle':retain_pickle,
            '_verify_device_keys_on_server':verify,'_verify_or_bootstrap_cross_signing':cross_sign,
            '_connect_setup_e2ee':setup}.items():
        setattr(adapter,name,MethodType(method,adapter))
    return adapter
