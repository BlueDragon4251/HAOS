"""Bounded native Matrix gap pagination into retained, independently gated input."""
import asyncio
from contextvars import ContextVar
import math

from .gateway import Conflict,digest
from .gateway_matrix_sync import dispatch_page

_READING=ContextVar('haos_matrix_history_read',default=None)


def approved(adapter,gap):
    native=adapter._haos_native;policy=native.policy();authority=gap['authority']
    if authority.get('connector')!=native.connector:return False
    return any(binding['connector']==native.connector and binding['chat']==gap['room_id']
        and type(binding.get('since')) is int and binding.get('generation')
        and digest(binding) in authority.get('binding_digests',[]) for binding in policy.bindings.values())


def install_reads(adapter,boundary):
    previous=boundary.allow_room_read
    def allow(room):
        state=_READING.get()
        if state is not None and state['adapter'] is adapter and state['gap']['room_id']==room:
            return approved(adapter,state['gap'])
        return previous(room)
    boundary.allow_room_read=allow


async def recover_one(adapter,client,journal):
    """One bounded HTTP page per call; no automatic send, join or grant creation."""
    from mautrix.types import RoomID,PaginationDirection
    from mautrix.errors import MatrixRequestError,MatrixResponseError
    lock=getattr(adapter,'_haos_matrix_history_lock',None)
    if lock is None:lock=adapter._haos_matrix_history_lock=asyncio.Lock()
    async with lock:
        gap=journal.history_gap()
        if gap is None:return False
        if not approved(adapter,gap):
            journal.history_status(gap,'revoked');return False
        token=_READING.set({'adapter':adapter,'gap':gap})
        try:
            page=await asyncio.wait_for(client.get_messages(RoomID(gap['room_id']),
                direction=PaginationDirection.BACKWARD,from_token=gap['resume_token'],limit=100),45)
            if page.start!=gap['resume_token']:raise ValueError('Matrix history response changed its requested start')
            events=[]
            for event in page.events:
                value=event.serialize()
                if value.get('room_id') not in {None,gap['room_id']}:raise ValueError('Matrix history changed its retained room')
                value['room_id']=gap['room_id'];events.append(value)
            # Snapshot remains the one captured with the original limited sync
            # page. Reconfiguration while reading never renews its authority.
            key=journal.capture_history(gap,page.end,events)
        except MatrixRequestError as error:
            delay=getattr(error,'retry_after',5)
            if type(delay) not in {int,float} or not math.isfinite(delay):delay=5
            journal.history_status(gap,'pending',error='rate-limited' if error.http_status==429 else 'source-unavailable',
                retry_after=min(86400,max(1,delay)))
            return False
        except PermissionError:
            journal.history_status(gap,'revoked');return False
        except (ValueError,KeyError,TypeError,Conflict,MatrixResponseError):
            journal.history_status(gap,'pending',error='invalid-page',retry_after=60);return False
        except (ConnectionError,asyncio.TimeoutError):
            journal.history_status(gap,'pending',error='transport-unavailable',retry_after=5);return False
        finally:_READING.reset(token)
        return await dispatch_page(adapter,client,journal,key)
