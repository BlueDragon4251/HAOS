"""Private per-grant outbound Matrix keys; no inferred room-wide device trust."""
import asyncio
from contextvars import ContextVar
from types import MethodType

from .gateway import digest
from .gateway_matrix_policy import opaque

_KEYS=ContextVar('haos_matrix_outbound_keys',default=None)


class RecipientGuard:
    def __init__(self,adapter,client,boundary):
        from mautrix.crypto import OlmMachine
        from mautrix.types import TrustState
        if not isinstance(client.crypto,OlmMachine):raise PermissionError('actual Matrix encryption identity required')
        if adapter._client is not client or boundary._client is not client or client.crypto.client is not client:
            raise PermissionError('Matrix outgoing crypto belongs to another private profile')
        if getattr(client.crypto,'_haos_recipient_guard',None) is not None:
            raise PermissionError('Matrix crypto already has a private outgoing identity')
        self.adapter,self.client=adapter,client
        self.sessions={};self.locks={}
        crypto=client.crypto;crypto._haos_recipient_guard=self
        original_find=crypto._find_olm_sessions
        original_share=crypto._encrypt_and_share_group_session
        previous_write=boundary.allow_write

        def state():
            value=_KEYS.get()
            if value is None or value['guard'] is not self:raise PermissionError('Matrix key distribution has no owner grant')
            self.current(value);return value

        def check_device(value,user,device,identity):
            pin=value['devices'].get(str(device))
            if (str(user)!=value['binding']['sender'] or pin is None
                    or str(identity.user_id)!=str(user) or str(identity.device_id)!=str(device)
                    or str(identity.signing_key)!=pin['ed25519'] or str(identity.identity_key)!=pin['curve25519']
                    or identity.deleted or identity.trust==TrustState.BLACKLISTED):
                raise PermissionError('Matrix outbound device differs from explicit owner fingerprints')

        async def find(machine,session,user,device,identity):
            from mautrix.types import TrustState
            value=state()
            if str(user)==value['binding']['sender'] and str(device) not in value['devices']:
                from mautrix.crypto.encrypt_megolm import already_shared
                # Native ignored-device semantics: no key, withheld notice or
                # trust upgrade is sent to another device of this account.
                session.users_ignored.add((user,device));return already_shared
            check_device(value,user,device,identity)
            # This verification is the explicit owner fingerprint approval,
            # after native signed-key validation, not TOFU or remote claims.
            identity.trust=TrustState.VERIFIED
            return await original_find(session,user,device,identity)

        async def share(machine,session,devices):
            value=state();expected={(value['binding']['sender'],device) for device in value['devices']}
            actual=set()
            for user,entries in devices.items():
                for device,(_olm,identity) in entries.items():
                    check_device(value,user,device,identity);actual.add((str(user),str(device)))
            if actual!=expected:raise PermissionError('Matrix key distribution omitted or added an approved device')
            await original_share(session,devices)
            value['shared_ack']=actual

        def write(method,path):
            value=_KEYS.get()
            if value is None or value['guard'] is not self:return previous_write(method,path)
            self.current(value)
            if method!='PUT':return False
            if value['phase']=='keys':
                return len(path)==3 and path[:2]==('sendToDevice','m.room.encrypted') and opaque(path[2])
            return (value['phase']=='message' and len(path)==5
                and path[:4]==('rooms',value['binding']['chat'],'send','m.room.encrypted') and opaque(path[4]))

        crypto._find_olm_sessions=MethodType(find,crypto)
        crypto._encrypt_and_share_group_session=MethodType(share,crypto)
        boundary.allow_write=write
        adapter._haos_matrix_recipients=self

    def current(self,state):
        binding=self.adapter._haos_native.policy().current_binding(state['route'])
        if binding!=state['binding'] or binding['connector']!=self.adapter._haos_native.connector:
            raise PermissionError('Matrix outbound owner approval changed')
        return binding

    async def send_text(self,route,chat,content):
        from mautrix.types import RoomID,UserID,EventType,TrustState,EncryptionAlgorithm
        binding=self.adapter._haos_native.policy().current_binding(route)
        relation=content.get('m.relates_to',{}) if isinstance(content,dict) else {}
        if (binding['connector']!=self.adapter._haos_native.connector or binding['chat']!=chat
                or not binding['matrix_devices'] or 'read' not in binding['capabilities']
                or not isinstance(content,dict) or content.get('msgtype')!='m.text'
                or not isinstance(content.get('body'),str) or not 1<=len(content['body'])<=1048576
                or not isinstance(relation,dict)
                or (relation.get('event_id') if relation.get('rel_type')=='m.thread' else '')!=binding['thread']):
            raise PermissionError('Matrix encrypted result has no approved recipient devices')
        state={'guard':self,'route':route,'binding':binding,'devices':{d['device_id']:d for d in binding['matrix_devices']},
            'shared_ack':set(),'phase':'prepare'}
        lock=self.locks.setdefault(chat,asyncio.Lock())
        async with lock:
            token=_KEYS.set(state)
            try:
                self.current(state);client=self.client;crypto=client.crypto;room=RoomID(chat);peer=UserID(binding['sender'])
                info=await client.get_state_event(room,EventType.ROOM_ENCRYPTION)
                if info.algorithm!=EncryptionAlgorithm.MEGOLM_V1:raise PermissionError('Matrix room encryption algorithm is not supported')
                members=await client.get_joined_members(room)
                if peer not in members or client.mxid not in members:raise PermissionError('Matrix encrypted recipient is not currently joined')
                async def local_blacklist():
                    cached=await crypto.crypto_store.get_devices(peer) or {}
                    if any(identity.trust==TrustState.BLACKLISTED for device,identity in cached.items()
                            if str(device) in state['devices']):
                        raise PermissionError('Matrix outbound device remains explicitly blacklisted')
                await local_blacklist()
                response=await client.query_keys([peer])
                if response.failures or set(response.device_keys)!={peer} or not set(state['devices'])<=set(response.device_keys[peer]):
                    raise PermissionError('Matrix approved remote devices are missing or unavailable')
                for device,keys in response.device_keys[peer].items():
                    if str(device) not in state['devices']:continue
                    pin=state['devices'][str(device)];values={str(k):str(v) for k,v in keys.keys.items()}
                    if (str(keys.user_id)!=str(peer) or str(keys.device_id)!=str(device)
                            or values.get('ed25519:'+str(device))!=pin['ed25519']
                            or values.get('curve25519:'+str(device))!=pin['curve25519']):
                        raise PermissionError('Matrix server keys differ from explicit owner fingerprints')
                await local_blacklist()
                selected={device:keys for device,keys in response.device_keys[peer].items() if str(device) in state['devices']}
                devices=await crypto._process_fetched_keys(peer,selected,response)
                if set(devices)!=set(state['devices']):raise PermissionError('native Matrix device signature validation failed')
                for identity in devices.values():
                    if identity.trust==TrustState.BLACKLISTED:
                        raise PermissionError('Matrix outbound device remains explicitly blacklisted')
                    identity.trust=TrustState.VERIFIED
                await crypto.crypto_store.put_devices(peer,devices)
                self.current(state)
                session=await crypto.crypto_store.get_outbound_group_session(room)
                proof=(digest(binding),str(session.id)) if session is not None else None
                if (session is None or session.expired or not session.shared or self.sessions.get(chat)!=proof):
                    # Rotate only the ephemeral outbound group session. Account,
                    # inbound/recovery keys and existing owner data are retained.
                    await crypto.crypto_store.remove_outbound_group_session(room)
                    self.sessions.pop(chat,None);state['phase']='keys'
                    await crypto.share_group_session(room,[peer])
                    session=await crypto.crypto_store.get_outbound_group_session(room)
                    expected={(str(peer),device) for device in state['devices']}
                    if session is None or not session.shared or state['shared_ack']!=expected:
                        raise PermissionError('Matrix SDK did not confirm distribution to every approved device')
                    self.sessions[chat]=(digest(binding),str(session.id))
                self.current(state);cipher=await crypto.encrypt_megolm_event(room,EventType.ROOM_MESSAGE,content)
                state['phase']='message'
                identity=await client.send_message_event(room,EventType.ROOM_ENCRYPTED,cipher,disable_encryption=True)
                return str(identity)
            finally:_KEYS.reset(token)
