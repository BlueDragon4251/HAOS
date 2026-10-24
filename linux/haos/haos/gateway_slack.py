"""Private native Slack Socket Mode capture and exact HAOS source admission."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import re

_CURRENT = ContextVar('haos_slack_owner_source',default=None)
_TS = re.compile(r'[1-9][0-9]{0,15}\.[0-9]{6}\Z')


@contextmanager
def secret_scope(mapping, home):
    from agent.secret_scope import set_secret_scope,reset_secret_scope
    token=set_secret_scope(mapping,profile_home=home)
    try:yield
    finally:reset_secret_scope(token)


def envelope(adapter,event,body):
    if (not isinstance(event,dict) or not isinstance(body,dict)
            or event.get('type') not in {'message','app_mention'}
            or event.get('subtype') not in {None,'','thread_broadcast','me_message'}
            or event.get('files') or event.get('attachments') or event.get('bot_id')
            or not isinstance(event.get('text'),str) or not event['text'].strip()
            or not isinstance(event.get('ts'),str) or not _TS.fullmatch(event['ts'])
            or not isinstance(event.get('user'),str) or not event['user']
            or not isinstance(event.get('channel'),str) or not event['channel']):
        return None
    team=adapter._event_team_id(event,body)
    if not team or event.get('team',team)!=team or body.get('team_id',team)!=team:
        return None
    thread=event.get('thread_ts') or ''
    if thread==event['ts']:thread=''
    if thread and (not isinstance(thread,str) or not _TS.fullmatch(thread)):return None
    source=adapter.build_source(chat_id=event['channel'],user_id=event['user'],scope_id=team,
        thread_id=thread or None,is_bot=False,message_id=event['ts'],
        chat_type='dm' if event.get('channel_type')=='im' else 'group')
    return {'platform':'slack','sender':str(source.user_id),'chat':str(source.chat_id),
        'scope':str(source.scope_id or ''),'thread':str(source.thread_id or ''),
        'message_id':event['ts'],'is_bot':False,'text':event['text']}


def capture(adapter,body):
    if getattr(adapter,'_haos_stopping',False):
        raise ConnectionError('private gateway ingress is stopping; leave input unconfirmed')
    source=envelope(adapter,body.get('event'),body) if isinstance(body,dict) else None
    if source is None:return False
    native=adapter._haos_native
    if source['scope'] not in adapter._team_clients:return False
    try:policy=native.policy();policy.authorize(native.connector,source)
    except (PermissionError,ValueError):return False
    native.inbox.admit(policy,native.connector,source,body,received_at=float(source['message_id']))
    return True


def install_socket(adapter,handler):
    if getattr(handler,'_haos_capture_installed',False):return
    original=handler.handle
    async def handle(client,request):
        from slack_sdk.socket_mode.response import SocketModeResponse
        with secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
            if request.type!='events_api' or not capture(adapter,request.payload):
                # Explicitly refused/unsupported sources have no HAOS authority.
                await client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
                return
            # This actual SDK ACK happens only after capture committed. Native
            # async listener completion is independent; retained input can replay.
            await original(client,request)
    listeners=handler.client.socket_mode_request_listeners
    found=False
    for index,listener in enumerate(listeners):
        if listener==original:listeners[index]=handle;found=True
    if not found:raise RuntimeError('pinned Slack Socket Mode listener seam changed')
    handler.handle=handle
    handler._haos_capture_installed=True


async def dispatch(adapter,original,event,body=None):
    if getattr(adapter,'_haos_stopping',False):return False
    source=envelope(adapter,event,body or {})
    if source is None:return
    native=adapter._haos_native
    key=native.inbox.key(native.connector,source)
    return await dispatch_stored(adapter,original,key)


async def dispatch_stored(adapter,original,key):
    if getattr(adapter,'_haos_stopping',False):return False
    native=adapter._haos_native
    row=native.inbox.claim(key,native.policy())
    if row is None:return False
    tasks=getattr(adapter,'_haos_receive_tasks',None)
    if tasks is None:tasks=adapter._haos_receive_tasks=set()
    task=asyncio.current_task();tasks.add(task)
    token=_CURRENT.set({'adapter':adapter,'source':row['envelope'],'accepted':False,
        'one_to_one_dm':row['payload']['event'].get('channel_type')=='im'})
    try:
        body=row['payload'];event=body['event']
        decoded=envelope(adapter,event,body)
        if decoded is None or any(decoded[name]!=row['envelope'][name] for name in
                ('platform','sender','chat','scope','thread','message_id','is_bot')):
            raise ValueError('Slack stored input changed its owner source')
        with secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
            await original(adapter,event,body)
        native.policy().current_binding(row)
        accepted=_CURRENT.get()['accepted']
        native.inbox.complete(key,accepted)
        return accepted
    except BaseException:
        native.inbox.retry(key);raise
    finally:_CURRENT.reset(token);tasks.discard(task)


def allowed(adapter,user,channel):
    state=_CURRENT.get()
    return (state is not None and state['adapter'] is adapter
        and state['source']['sender']==user and state['source']['chat']==channel)


async def channel_allowed(adapter,**kwargs):
    state=_CURRENT.get()
    return (allowed(adapter,kwargs['user_id'],kwargs['channel_id'])
        and state['source']['scope']==kwargs['team_id']
        and state['source']['thread']==(kwargs['event_thread_ts'] if kwargs['is_thread_reply'] else '')
        and (state['one_to_one_dm'] or kwargs['is_mentioned']))


def admitted(adapter,accepted):
    state=_CURRENT.get()
    if state is not None and state['adapter'] is adapter:state['accepted']=accepted is True


def block_rejected(original,error):
    from slack_sdk.errors import SlackApiError
    return (isinstance(error,SlackApiError) and error.response.status_code in {200,400}
        and error.response.get('ok') is False and original(error))


async def send_native(adapter,original,chat_id,content,reply_to=None,metadata=None):
    from gateway.platforms.base import SendResult
    metadata=dict(metadata or {})
    team=metadata.get('slack_team_id');thread=metadata.get('thread_id') or ''
    if (not isinstance(team,str) or team!=metadata.get('haos_scope') or team not in adapter._team_clients
            or not isinstance(chat_id,str) or not re.fullmatch('[CGD][A-Z0-9]+',chat_id)
            or thread and (not isinstance(thread,str) or not _TS.fullmatch(thread))):
        return SendResult(success=False,error='exact authenticated Slack workspace/channel/thread required',
            error_kind='forbidden',raw_response={'haos_delivery':'refused'})
    if not adapter._app:
        return SendResult(success=False,error='Slack transport unavailable',retryable=True,
            raw_response={'haos_delivery':'not-dispatched'})
    metadata['thread_ts']=thread
    with secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
        # Explicit owner thread only. Native reply_to otherwise synthesizes a
        # new thread for a top-level message, changing its approved context.
        result=await original(adapter,chat_id,content,None,metadata)
    if result.success is True:
        if (not isinstance(result.message_id,str) or not _TS.fullmatch(result.message_id)
                or not callable(getattr(result.raw_response,'get',None)) or result.raw_response.get('channel')!=chat_id):
            return SendResult(success=False,error='Slack returned no valid exact-route delivery identity',error_kind='unknown')
    return result


class NativeDedup:
    """The durable source-scoped HAOS journal owns replay, not volatile team+ts."""
    def is_duplicate(self,*args,**kwargs):return False
    def contains(self,*args,**kwargs):return False
    def clear(self):pass
