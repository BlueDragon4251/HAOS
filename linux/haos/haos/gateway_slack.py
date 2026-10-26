"""Private native Slack Socket Mode capture and exact HAOS source admission."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import re
from types import SimpleNamespace

_CURRENT = ContextVar('haos_slack_owner_source',default=None)
_SENDING = ContextVar('haos_slack_delivery',default=None)
_TS = re.compile(r'[1-9][0-9]{0,15}\.[0-9]{6}\Z')


def validate_credentials(bot_token,app_token):
    for value,prefix in ((bot_token,'xoxb-'),(app_token,'xapp-')):
        if not isinstance(value,str) or not re.fullmatch(prefix+r'[A-Za-z0-9-]{11,4091}',value):
            raise ValueError('Slack requires a separate bot token and Socket Mode app token; token lists are not supported')


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
        and error.response.get('ok') is False
        and error.response.get('error') in {'invalid_blocks','msg_too_long','too_many_blocks'} and original(error))


async def send_native(adapter,original,chat_id,content,reply_to=None,metadata=None):
    from gateway.platforms.base import SendResult
    from .gateway_delivery_authority import current_delivery
    metadata=dict(metadata or {})
    try:current=current_delivery(adapter,'slack',chat_id,metadata)
    except PermissionError:
        return SendResult(success=False,error='current exact owner Slack grant required',error_kind='forbidden',
            raw_response={'haos_delivery':'refused'})
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
    state=SimpleNamespace(chat=chat_id,thread=thread,started=False,successful=0,ambiguous=False,
        error=None,refused=False,connect_failed=False,current=current)
    token=_SENDING.set(state)
    try:
        with secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
            # Explicit owner thread only; no synthetic reply_to thread.
            result=await original(adapter,chat_id,content,None,metadata)
    finally:_SENDING.reset(token)
    if result.success is True:
        if (not isinstance(result.message_id,str) or not _TS.fullmatch(result.message_id)
                or not callable(getattr(result.raw_response,'get',None)) or result.raw_response.get('channel')!=chat_id):
            return SendResult(success=False,error='Slack returned no valid exact-route delivery identity',error_kind='unknown')
    elif state.ambiguous or state.successful:
        return SendResult(success=False,error='Slack delivery outcome uncertain',error_kind='unknown')
    else:
        from slack_sdk.errors import SlackApiError
        error=state.error
        raw=dict(result.raw_response) if isinstance(result.raw_response,dict) else {}
        if state.refused:
            result.error_kind='forbidden';raw['haos_delivery']='refused'
        elif isinstance(error,SlackApiError):
            status=error.response.status_code
            code=error.response.get('error')
            if status==429 and error.response.get('ok') is False and code in {'ratelimited','rate_limited'}:
                result.error_kind='rate_limited';result.retry_after=adapter._retry_after_from_exc(error)
                raw['haos_delivery']='refused'
            elif status in {200,400,401,403,404} and error.response.get('ok') is False and code in {
                    'invalid_auth','not_authed','token_revoked','account_inactive','missing_scope',
                    'no_permission','restricted_action','not_in_channel','is_archived',
                    'channel_not_found','thread_not_found','invalid_blocks','invalid_arguments','msg_too_long'}:
                result.error_kind=('not_found' if code in {'channel_not_found','thread_not_found'} else
                    'too_long' if code=='msg_too_long' else 'bad_format' if code in {'invalid_blocks','invalid_arguments'} else 'forbidden')
                raw['haos_delivery']='refused'
        elif state.connect_failed or not state.started:
            result.retryable=True;raw['haos_delivery']='not-dispatched'
        result.raw_response=raw
    return result


_WEB_CLIENTS = {}


def install_web_client(client):
    """Private SDK subclass preserves copy/token semantics of Bolt's real clients."""
    client.retry_handlers=[]
    base=type(client)
    if getattr(base,'_haos_delivery_guard',False):return client
    if base not in _WEB_CLIENTS:
        from functools import wraps
        @wraps(base.api_call)
        async def call(self,api_method,*args,**kwargs):
            return await web_call(base.api_call,self,api_method,*args,**kwargs)
        _WEB_CLIENTS[base]=type('HAOS'+base.__name__,(base,),{
            '__module__':__name__,'_haos_delivery_guard':True,'api_call':call})
    client.__class__=_WEB_CLIENTS[base]
    return client


async def web_call(original,client,method,*args,**kwargs):
    import aiohttp
    from slack_sdk.errors import SlackApiError
    state=_SENDING.get()
    if state is not None:
        try:state.current()
        except PermissionError:
            state.refused=True;raise
        payload=kwargs.get('json')
        if (method!='chat.postMessage' or not isinstance(payload,dict) or payload.get('channel')!=state.chat
                or (payload.get('thread_ts') or '')!=state.thread or payload.get('reply_broadcast')):
            state.refused=True
            raise PermissionError('Slack send cannot change its approved channel/thread or perform another action')
        state.started=True
    try:
        result=await original(client,method,*args,**kwargs)
        if state is not None:state.successful+=1
        return result
    except Exception as error:
        if state is not None:
            state.error=error
            if isinstance(error,aiohttp.ClientConnectorError):state.connect_failed=True
            elif not isinstance(error,SlackApiError) or error.response.status_code>=500:
                state.ambiguous=True
        raise


class NativeDedup:
    """The durable source-scoped HAOS journal owns replay, not volatile team+ts."""
    def is_duplicate(self,*args,**kwargs):return False
    def contains(self,*args,**kwargs):return False
    def clear(self):pass
