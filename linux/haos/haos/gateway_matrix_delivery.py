"""Prepared exact-route native Matrix text delivery; never retry an unclear send.

Encrypted recipient/key-distribution approval is intentionally not inferred from
inbound device approval. Encrypted sends require a separately installed private
RecipientGuard. This component does not enable Matrix in installed owner setup.
"""
from contextvars import ContextVar
from types import MethodType

from .gateway_matrix_policy import opaque

_SENDING=ContextVar('haos_matrix_send',default=None)


class _StopNativeRetry(BaseException):
    """Exit pinned native broad Exception retry without losing cancellation."""


def install(adapter,boundary):
    from gateway.platforms.base import SendResult
    original_send=type(adapter).send

    def current(route):
        binding=adapter._haos_native.policy().current_binding(route['binding_route'])
        if (binding['connector']!=adapter._haos_native.connector or binding['chat']!=route['chat']
                or binding['scope']!='' or binding['thread']!=route['thread'] or 'read' not in binding['capabilities']):
            raise PermissionError('Matrix outgoing route differs from its current owner grant')
        return binding

    def allowed(method,path):
        route=_SENDING.get()
        if route is None or route['adapter'] is not adapter:return False
        current(route)
        return (route['message_active'] and method=='PUT' and len(path)==5
            and path[:4]==('rooms',route['chat'],'send','m.room.message') and opaque(path[4]))

    def read(room):
        route=_SENDING.get()
        if route is None or route['adapter'] is not adapter or room!=route['chat']:return False
        current(route);return True

    async def one(self,chat,content):
        import asyncio
        from mautrix.types import RoomID,EventType
        from mautrix.errors import MatrixRequestError,MNotFound
        route=_SENDING.get()
        if route is None or route['adapter'] is not self:raise PermissionError('Matrix send has no private owner route')
        try:
            binding=current(route)
            relation=content.get('m.relates_to') or {}
            if (chat!=route['chat'] or content.get('msgtype')!='m.text'
                    or not isinstance(content.get('body'),str) or not content['body']
                    or (relation.get('event_id') if relation.get('rel_type')=='m.thread' else '')!=route['thread']):
                raise PermissionError('native Matrix text changed the approved room or thread')
            # Fetch current encryption state: absent/failed metadata is never
            # interpreted as permission to downgrade an encrypted room.
            try:await self._client.get_state_event(RoomID(chat),EventType.ROOM_ENCRYPTION)
            except MNotFound:encrypted=False
            else:encrypted=True
            guard=getattr(self,'_haos_matrix_recipients',None)
            if encrypted and guard is None or not encrypted and not binding['allow_plaintext']:
                raise PermissionError('Matrix outgoing encryption policy refused')
            # Prevent native outbound @room/user notification expansion.
            content['m.mentions']={}
            current(route)
            route['message_active']=True;route['attempts']+=1
            if encrypted:
                identity=await asyncio.wait_for(guard.send_text(route['binding_route'],chat,content),timeout=45)
            else:
                # Explicit plaintext approval plus current absent encryption;
                # a stale SDK cache cannot implicitly distribute group keys.
                identity=str(await asyncio.wait_for(self._client.send_message_event(
                    RoomID(chat),EventType.ROOM_MESSAGE,content,disable_encryption=True),timeout=45))
            if not opaque(identity,'$'):raise ValueError('Matrix send returned no valid event receipt')
            route['receipts'].append(identity)
            return identity
        except MatrixRequestError as error:
            route['error']=('refused',error.http_status,getattr(error,'retry_after',5))
            raise _StopNativeRetry() from None
        except PermissionError:
            route['error']=('refused',403,5);raise _StopNativeRetry() from None
        except Exception:
            route['error']=('uncertain',None,5);raise _StopNativeRetry() from None
        finally:route['message_active']=False

    async def send(self,chat_id,content,reply_to=None,metadata=None):
        metadata=metadata or {}
        if not isinstance(metadata,dict):
            return SendResult(success=False,error='Matrix owner route refused',error_kind='forbidden',raw_response={'haos_delivery':'refused'})
        route={'adapter':self,'chat':chat_id,'thread':metadata.get('thread_id') or '',
            'binding_route':metadata.get('haos_binding'),'receipts':[],'attempts':0,
            'message_active':False,'error':None}
        try:
            if (reply_to is not None and not opaque(reply_to,'$') or metadata.get('haos_scope')!='' or not opaque(chat_id,'!')
                    or route['thread'] and not opaque(route['thread'],'$')
                    or not isinstance(content,str) or not 1<=len(content)<=1048576):
                raise PermissionError('Matrix outgoing text has no exact approved route')
            current(route)
        except (PermissionError,KeyError,TypeError):
            return SendResult(success=False,error='Matrix owner route refused',error_kind='forbidden',raw_response={'haos_delivery':'refused'})
        token=_SENDING.set(route)
        try:
            try:return await original_send(self,chat_id,content,reply_to=reply_to,metadata={'thread_id':route['thread']})
            except _StopNativeRetry:
                kind,status,delay=route['error']
                if route['receipts'] or kind=='uncertain' or status not in {400,401,403,404,413,429}:
                    return SendResult(success=False,error='Matrix delivery outcome uncertain',error_kind='unknown')
                return SendResult(success=False,error='Matrix request refused',
                    error_kind='rate_limited' if status==429 else 'too_long' if status==413 else 'forbidden',
                    retry_after=delay,raw_response={'haos_delivery':'refused'})
        finally:_SENDING.reset(token)

    boundary.allow_write=allowed;boundary.allow_room_read=read
    adapter._send_room_message=MethodType(one,adapter)
    adapter.send=MethodType(send,adapter)
    return adapter
