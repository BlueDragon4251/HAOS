"""Closed native A2A dispatch from retained sources, without the agent/plugin loop."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from types import MethodType
import threading

from .gateway import Conflict,digest
from .gateway_a2a_admission import security_context
from .gateway_a2a_tasks import Tasks,_SOURCE
from .gateway_matrix_profile import scope as private_scope

_DELIVERY=ContextVar('haos_private_a2a_delivery',default=None)


def build(value,peer,home,current,policy,tasks,receive):
    if not isinstance(tasks,Tasks) or tasks.peer!=peer or not callable(receive):
        raise PermissionError('private retained native A2A task index and fixed parent receiver required')
    from .gateway_line_profile import _directory
    home=Path(home);_directory(home)
    from gateway.config import PlatformConfig
    from plugins.platforms.a2a.adapter import A2AAdapter
    from plugins.platforms.a2a import protocol
    from .gateway_ingress import durable_adapter
    environment={'HERMES_SAFE_MODE':'1','A2A_PEER_TOKENS':peer+':'+value['peer_tokens'][peer],
        'A2A_BEARER_TOKEN':'','A2A_ALLOWED_USERS':peer,'A2A_TRUSTED_PEERS':peer,'A2A_ALLOW_ALL_USERS':'false',
        'A2A_HOST':value['tls']['bind_host'],'A2A_PORT':str(value['port']),'A2A_PUBLIC_URL':value['tls']['public_url'],
        'A2A_AGENT_NAME':value['agent_name'],'A2A_ADVERTISED_TOOLSETS':'haos_missions'}
    current()
    # A nonempty, fixed list with no routed-agent entry prevents the native
    # loader's empty-value fallback to unrelated CLI/profile configuration.
    with private_scope(home,environment):
        adapter=durable_adapter(A2AAdapter(PlatformConfig(enabled=True,extra={'agents':[None],'advertised_toolsets':['haos_missions']})))
    adapter.tasks=tasks;adapter._loop=asyncio.get_running_loop()
    adapter._haos_a2a_home=home;adapter._haos_a2a_environment=environment
    adapter._security_context=security_context({**value,'peer_tokens':{peer:value['peer_tokens'][peer]}})
    native_prepare=adapter._prepare_task.__func__;native_handle=adapter.handle_message.__func__
    native_send=adapter.send.__func__;native_finalize=adapter._finalize_task.__func__;native_resolve=adapter._resolve_task.__func__
    finalize_lock=threading.RLock();send_lock=asyncio.Lock();prepared={};finalized={};closing=[False]
    identity=deepcopy(adapter._security_context)

    def check():
        if closing[0]:raise PermissionError('private A2A native profile is closed')
        current()
        if (adapter._security_context!=identity or set(adapter._agents)!={''} or not adapter._agents['']['local']
                or adapter._agents['']['slug'] or adapter._agents['']['tenant'] or adapter.tasks is not tasks
                or adapter._haos_ingress is not accepted or adapter._message_handler is not accepted):
            raise PermissionError('native A2A identity, dispatch or profile route changed')

    def source(event):
        check();state=_SOURCE.get()
        if state is None or state[0] is not tasks:raise PermissionError('unretained A2A event has no dispatch context')
        proof=state[2];row=tasks.by_source(proof['source_key']);origin=proof['envelope'];native=event.source
        if (row is None or row['task_id']!=event.message_id or row['raw_id']!=proof['id'] or native is None
                or getattr(native.platform,'value',None)!='a2a' or native.user_id!=peer or native.chat_id!=origin['chat']
                or native.is_bot is not False or event.internal or event.media_urls or event.text!=origin['text']
                or getattr(event.message_type,'value',None)!='text' or event.raw_message is not None):
            raise PermissionError('native A2A event differs from its retained authenticated source')
        return proof,row

    def accepted(event):
        proof,row=source(event)
        if row['admitted_receipt']!=proof['source_key']:raise PermissionError('durable parent receipt must precede native admission')
        return True

    adapter.set_durable_message_handler(accepted);adapter.set_message_handler(accepted)

    async def handle(self,event):
        proof,row=source(event)
        receipt=await receive(event,proof,row['task_id']);check()
        tasks.admitted(row['task_id'],receipt)
        with private_scope(home,environment):await native_handle(self,event)
        check()
        if event._gateway_accepted is not True:raise PermissionError('native A2A input was not durably accepted')

    def prepare(self,params,authenticated_peer,agent=None):
        check();state=_SOURCE.get()
        if state is None or state[0] is not tasks or authenticated_peer!=peer or agent not in (None,self._agents['']):
            raise PermissionError('one exact independently approved native A2A request required')
        proof=state[2]
        if digest([proof['source_key'],digest([params,proof['envelope'],proof['binding_digest'],proof['credential_scope']])])!=proof['id']:
            raise PermissionError('native A2A parameters changed after original custody')
        if tasks.by_source(proof['source_key']) is not None:raise Conflict('recover the original A2A task instead of dispatching it twice')
        with private_scope(home,environment):terminal,pending=native_prepare(self,params,peer,agent=self._agents[''])
        if pending is not None:
            row=tasks.by_source(proof['source_key'])
            if row is None or row['task_id']!=pending['task_id'] or pending['context_id']!=proof['envelope']['chat']:
                raise Conflict('native A2A task changed its retained source route')
            prepared[pending['task_id']]=pending
        return terminal,pending

    def finalize(self,pending,state,reply):
        check();task_id=pending['task_id']
        with finalize_lock:
            if state==protocol.STATE_FAILED and reply in {'[client disconnected]','[agent did not reply in time]','[agent shutting down]'}:
                record=tasks.get(task_id)
                return record['state'],record['reply']
            if task_id in finalized:return finalized[task_id]
            with private_scope(home,environment):result=native_finalize(self,pending,state,reply)
            committed=tasks.get(task_id)
            if committed['state']!=result[0] or committed['reply']!=result[1]:raise Conflict('native A2A result has no matching committed task')
            finalized[task_id]=result;prepared.pop(task_id,None);return result

    def resolve(self,context_id,state,text):
        check();delivery=_DELIVERY.get()
        if delivery is None or delivery[0] is not self:raise PermissionError('no independent task-specific A2A delivery context')
        task_id=delivery[1];record=tasks.get(task_id)
        if record is None or record['peer']!=peer or record['context_id']!=context_id:
            raise PermissionError('A2A reply cannot resolve another context or peer')
        delivery[2]+=1
        return native_resolve(self,task_id,state,text)

    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from gateway.platforms.base import SendResult
        check()
        if (not isinstance(metadata,dict) or set(metadata)!={'notify','haos_task_id','source_key'} or metadata['notify'] is not True
                or reply_to not in (None,metadata['haos_task_id']) or not isinstance(content,str)
                or not content or len(content.encode())>32000 or tasks.redactor.text(content)!=content):
            raise PermissionError('exact credential-free retained-task A2A result required')
        task_id=metadata['haos_task_id'];row=tasks.by_source(metadata['source_key'])
        if row is None or row['task_id']!=task_id or row['context_id']!=chat_id or row['admitted_receipt']!=row['source_key']:
            raise PermissionError('result source has no matching durable native A2A task input')
        binding=policy().current_binding(row)
        if 'read' not in binding['capabilities']:raise PermissionError('independent A2A result-read grant required')
        async with send_lock:
            check();record=tasks.get(task_id)
            from plugins.platforms.a2a import security
            projected=security.redact_outbound(content);state=protocol.STATE_COMPLETED
            stripped=projected.lstrip()
            if stripped.upper().startswith(protocol.INPUT_REQUIRED_MARKER):
                state=protocol.STATE_INPUT_REQUIRED;projected=stripped[len(protocol.INPUT_REQUIRED_MARKER):].strip()
            cached=tasks.result_intent(task_id,content,state,projected)
            if cached:
                return SendResult(success=True,message_id=task_id,raw_response={'recipient_read_verified':False,'local_task_committed':True})
            if task_id not in prepared:
                future=self._add_pending(task_id,chat_id)
                prepared[task_id]={'task_id':task_id,'context_id':chat_id,'peer':peer,'future':future,
                    'created_iso':record['created_iso'],'started':record['created_at']}
            pending=prepared[task_id];delivery=[self,task_id,0];token=_DELIVERY.set(delivery)
            try:
                with private_scope(home,environment):result=await native_send(self,chat_id,content,reply_to=task_id,metadata={'notify':True})
            finally:_DELIVERY.reset(token)
            if (result.success is not True or delivery[2]!=1 or not pending['future'].done()
                    or pending['future'].result()!=(protocol.STATE_COMPLETED,content)):
                raise Conflict('native A2A sender did not resolve the exact retained task')
            self._finalize_task(pending,protocol.STATE_COMPLETED,content);check()
            tasks.confirm_result(task_id,content,state,projected)
            return SendResult(success=True,message_id=task_id,raw_response={'recipient_read_verified':False,'local_task_committed':True})

    from .gateway_a2a_result import Results
    results=Results(tasks)
    async def outcome(self,task_id,source_key,epoch,content,state):
        from gateway.platforms.base import SendResult
        check()
        async with send_lock:
            cached,desired,projected=results.begin(task_id,source_key,epoch,content,state)
            if not cached:
                record=tasks.get(task_id)
                if task_id not in prepared:
                    future=self._add_pending(task_id,record['context_id'])
                    prepared[task_id]={'task_id':task_id,'context_id':record['context_id'],'peer':peer,'future':future,
                        'created_iso':record['created_iso'],'started':record['created_at']}
                pending=prepared[task_id]
                if state==protocol.STATE_COMPLETED:
                    delivery=[self,task_id,0];token=_DELIVERY.set(delivery)
                    try:
                        with private_scope(home,environment):sent=await native_send(self,record['context_id'],content,reply_to=task_id,metadata={'notify':True})
                    finally:_DELIVERY.reset(token)
                    resolved=sent.success is True and delivery[2]==1
                else:resolved=native_resolve(self,task_id,state,content)
                if not resolved or not pending['future'].done() or pending['future'].result()!=(state,content):
                    raise Conflict('native A2A outcome did not resolve its exact retained task Future')
                # A later controller event may legitimately finish a task after
                # an input-required outcome. The immutable epochs remain separate.
                finalized.pop(task_id,None)
                self._finalize_task(pending,state,content);check()
                results.confirm(task_id,source_key,epoch,content,state)
            return SendResult(success=True,message_id=task_id,raw_response={'recipient_read_verified':False,'local_task_committed':True})

    async def connect(self,**_kwargs):raise PermissionError('A2A requires the separately bounded authenticated HTTPS server')
    native_emit=adapter._emit_terminal.__func__;native_sse=adapter._sse_write
    def emit(self,handler,task_id,context_id,state,reply,req_id=None):
        check();record=tasks.get(task_id)
        if record is None or record['context_id']!=context_id or record['state']!=state or record['reply']!=reply:
            raise Conflict('native A2A stream outcome has no matching committed local task')
        return native_emit(self,handler,task_id,context_id,state,reply,req_id=req_id)
    def sse(self,handler,chunk):
        check()
        if not isinstance(chunk,str) or len(chunk.encode())>1024*1024 or tasks.redactor.text(chunk)!=chunk:
            raise PermissionError('bounded credential-free native A2A stream frame required')
        return native_sse(handler,chunk)
    native_card=adapter._build_card.__func__
    def card(self,public_url=None,agent=None):
        check()
        result=native_card(self,public_url=value['tls']['public_url'],agent=self._agents[''])
        result['capabilities']['pushNotifications']=False
        return result
    def skills(self,agent=None):return protocol.skills_from_toolsets(['haos_missions'])
    async def close(self):
        closing[0]=True
        # Pending Futures may outlive a TCP connection. No synthetic failed
        # mission or terminal result is persisted merely because this closes.
        for _,future in tuple(self._pending.values()):future.cancel()
        self._pending.clear();self._pending_order.clear();prepared.clear();finalized.clear()
        with tasks.native._lock:
            for watchers in tasks.native._watchers.values():
                for future in watchers:future.cancel()
            tasks.native._watchers.clear()
    adapter.handle_message=MethodType(handle,adapter);adapter._prepare_task=MethodType(prepare,adapter)
    adapter._finalize_task=MethodType(finalize,adapter);adapter._resolve_oldest_for_context=MethodType(resolve,adapter)
    adapter.send=MethodType(send,adapter);adapter.send_outcome=MethodType(outcome,adapter)
    adapter.connect=MethodType(connect,adapter);adapter.close_profile=MethodType(close,adapter)
    adapter._advertised_skills=MethodType(skills,adapter);adapter._haos_a2a_check=check
    adapter._haos_a2a_source=source
    adapter._emit_terminal=MethodType(emit,adapter);adapter._sse_write=MethodType(sse,adapter)
    adapter._build_card=MethodType(card,adapter)
    check();return adapter
