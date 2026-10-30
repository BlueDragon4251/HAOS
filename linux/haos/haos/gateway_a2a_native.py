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
_OUTCOME=ContextVar('haos_private_a2a_outcome',default=None)


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
    from .gateway_a2a_inputs import Inputs
    inputs=Inputs(tasks)
    from .gateway_a2a_artifacts import Artifacts
    adapter._haos_a2a_artifacts=Artifacts(tasks)
    adapter._haos_a2a_home=home;adapter._haos_a2a_environment=environment
    adapter._security_context=security_context({**value,'peer_tokens':{peer:value['peer_tokens'][peer]}})
    if peer in value.get('callbacks',{}):
        from dataclasses import replace
        adapter._security_context=replace(adapter._security_context,push_secret=value['callbacks'][peer]['secret'])
    native_prepare=adapter._prepare_task.__func__;native_handle=adapter.handle_message.__func__
    native_send=adapter.send.__func__;native_finalize=adapter._finalize_task.__func__;native_resolve=adapter._resolve_task.__func__
    finalize_lock=threading.RLock();send_lock=asyncio.Lock();prepared={};finalized={};closing=[False]
    identity=deepcopy(adapter._security_context)
    from .gateway_a2a_callbacks import Configs
    from .gateway_a2a_callback_delivery import Delivery
    tasks.callbacks=Configs(tasks)
    callbacks=Delivery(adapter,tasks,tasks.callbacks,adapter._send_push_notification.__func__)
    tasks.callback_delivery=callbacks;callback_worker=[None];callback_failed=[False]
    def queue_callback(self,task_id,context_id,reply,state):callbacks.queue(task_id,context_id,reply,state)
    def callback_open(self,request,*,timeout):return callbacks.open(request,timeout=timeout)
    adapter._send_push_notification=MethodType(queue_callback,adapter)
    adapter._open_push_notification=MethodType(callback_open,adapter)

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
        proof=state[2];row=lookup(proof);origin=proof['envelope'];native=event.source
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

    receive_tasks=set();receive_by_task={};adapter._haos_receive_tasks=receive_tasks
    async def handle(self,event):
        task=asyncio.current_task();receive_tasks.add(task)
        receive_by_task.setdefault(event.message_id,set()).add(task)
        try:await dispatch_received(self,event)
        finally:
            receive_tasks.discard(task);receive_by_task[event.message_id].discard(task)
            if not receive_by_task[event.message_id]:receive_by_task.pop(event.message_id)

    async def dispatch_received(self,event):
        proof,row=source(event)
        receipt=await receive(event,proof,row['task_id']);check()
        if 'target_task_id' in proof:inputs.admitted(proof,receipt)
        else:tasks.admitted(row['task_id'],receipt)
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
        if lookup(proof) is not None:raise Conflict('recover the original A2A task instead of dispatching it twice')
        if 'target_task_id' in proof:
            row=inputs.prepare(proof);task_id=row['task_id'];record=tasks.get(task_id)
            # A continuation retains the actual original native TaskStore ID.
            # Its working state describes processing a queued clarification,
            # not a completed mission or confirmation of the remote answer.
            tasks.set_state(task_id,protocol.STATE_WORKING)
            with private_scope(home,environment):
                from gateway.platforms.event import MessageEvent,MessageType
                future=self._add_pending(task_id,row['context_id'])
                pending={'task_id':task_id,'context_id':row['context_id'],'peer':peer,'future':future,
                    'created_iso':record['created_iso'],'started':__import__('time').time()}
                event=MessageEvent(text=proof['envelope']['text'],message_type=MessageType.TEXT,message_id=task_id,
                    source=self.build_source(chat_id=row['context_id'],chat_name='a2a:'+peer,chat_type='dm',user_id=peer,user_name=peer))
                prepared[task_id]=pending;finalized.pop(task_id,None)
                asyncio.run_coroutine_threadsafe(self.handle_message(event),self._loop)
            return None,pending
        projected=params
        if proof.get('resources'):
            from .gateway_a2a_media import projection
            projected,resources=projection(value,peer,params,tasks.redactor,binding=policy().current_binding(proof))
            if resources!=proof['resources']:raise Conflict('A2A file projection changed after retained original admission')
        with private_scope(home,environment):terminal,pending=native_prepare(self,projected,peer,agent=self._agents[''])
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
            if (_OUTCOME.get()!=(self,task_id) and tasks.db.execute(
                    "SELECT 1 FROM a2a_result_epochs WHERE task_id=? AND state='writing'",(task_id,)).fetchone()):
                raise Conflict('native A2A outcome receipt is not committed')
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
        check()
        async with send_lock:
            # The frozen native sender only resolves a Future; it never yields
            # or performs I/O. Keep HTTP finalizers behind the complete durable
            # outcome+epoch commit so question metadata cannot race its proof.
            with finalize_lock:
                token=_OUTCOME.set((self,task_id))
                try:return await finish_outcome(self,task_id,source_key,epoch,content,state)
                finally:_OUTCOME.reset(token)

    async def finish_outcome(self,task_id,source_key,epoch,content,state):
        from gateway.platforms.base import SendResult
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
    async def cancel_prevented(self,source):
        from .gateway_a2a_controls import source_receipt
        check();row=tasks.entry(source['task_id'])
        if row is None or any(row[k]!=source[k] for k in ['task_id','source_key','raw_id','binding_digest','credential_scope']):
            raise Conflict('pre-admission cancellation changed native source')
        if source_receipt(tasks,row)!={'cancel_requested':True,'source_prevented':True}:
            raise PermissionError('root must prove prevention before native task cancellation')
        receivers={task for task in receive_by_task.get(row['task_id'],set()) if task is not asyncio.current_task()}
        for task in receivers:task.cancel()
        await asyncio.gather(*receivers,return_exceptions=True)
        async with send_lock:
            with finalize_lock:
                check();source_receipt(tasks,row);record=tasks.get(row['task_id'])
                body='Cancelled by root before mission admission.'
                if record['state']==protocol.STATE_CANCELED and record['reply']==body:return
                if record['state'] in protocol.TERMINAL_STATES:raise Conflict('pre-admission source already has another terminal outcome')
                if tasks.db.execute("SELECT 1 FROM a2a_result_epochs WHERE task_id=? AND state='writing'",(row['task_id'],)).fetchone():
                    raise Conflict('pre-admission task has an uncertain result transition')
                task_id=row['task_id']
                if task_id not in prepared:
                    prepared[task_id]={'task_id':task_id,'context_id':record['context_id'],'peer':peer,
                        'future':self._add_pending(task_id,record['context_id']),'created_iso':record['created_iso'],'started':record['created_at']}
                pending=prepared[task_id]
                if not native_resolve(self,task_id,protocol.STATE_CANCELED,body) or pending['future'].result()!=(protocol.STATE_CANCELED,body):
                    raise Conflict('pre-admission cancellation did not resolve its actual native Future')
                finalized.pop(task_id,None);self._finalize_task(pending,protocol.STATE_CANCELED,body);check()
    native_emit=adapter._emit_terminal.__func__;native_sse=adapter._sse_write
    def emit(self,handler,task_id,context_id,state,reply,req_id=None):
        with finalize_lock:
            check();record=tasks.get(task_id)
            if record is None or record['context_id']!=context_id or record['state']!=state or record['reply']!=reply:
                raise Conflict('native A2A stream outcome has no matching committed local task')
            if state==protocol.STATE_COMPLETED:
                parts=self._haos_a2a_artifacts.parts(task_id)
                if parts:
                    payload=protocol.artifact_update(task_id,context_id,'')
                    payload['artifactUpdate']['artifact']['parts']=parts
                    self._sse_write(handler,protocol.sse_data(payload,req_id))
            return native_emit(self,handler,task_id,context_id,state,reply,req_id=req_id)
    def sse(self,handler,chunk):
        check()
        if not isinstance(chunk,str) or len(chunk.encode())>1024*1024 or tasks.redactor.text(chunk)!=chunk:
            raise PermissionError('bounded credential-free native A2A stream frame required')
        if chunk.startswith('data:'):
            import json
            from .gateway_a2a_question import decorate
            payload=json.loads(chunk[5:].strip());state=_SOURCE.get()
            if state is not None and state[0] is tasks and 'target_task_id' in state[2]:
                native_task=payload.get('result',{}).get('task')
                if isinstance(native_task,dict) and native_task.get('status',{}).get('state')==protocol.STATE_SUBMITTED:
                    payload['result']['task']=protocol.TaskStore.to_task(tasks.get(state[2]['target_task_id']))
            chunk='data: '+json.dumps(self._haos_a2a_artifacts.decorate(decorate(self,payload)),ensure_ascii=False)+'\n\n'
            if len(chunk.encode())>1024*1024 or tasks.redactor.text(chunk)!=chunk:
                raise PermissionError('private or excessive native A2A stream metadata')
        return native_sse(handler,chunk)
    native_card=adapter._build_card.__func__
    def card(self,public_url=None,agent=None):
        check()
        result=native_card(self,public_url=value['tls']['public_url'],agent=self._agents[''])
        bindings=[row for row in policy().bindings.values() if row['connector']==tasks.connector]
        result['capabilities']['pushNotifications']=bool(peer in value.get('callbacks',{}) and any(row['sender']==peer and row.get('allow_callback') is True for row in bindings))
        if any(row.get('allow_media') for row in bindings):result['defaultInputModes']+=['application/octet-stream','image/png','image/jpeg']
        if any(row.get('allow_voice') for row in bindings):result['defaultInputModes']+=['audio/flac','audio/ogg','audio/wav','audio/mpeg','audio/mp4','audio/amr']
        if any(row.get('allow_video') for row in bindings):result['defaultInputModes']+=['video/mp4','video/3gpp','video/3gpp2']
        if any(row.get('allow_outbound_media') for row in bindings):result['defaultOutputModes'].append('application/octet-stream')
        return result
    def skills(self,agent=None):return protocol.skills_from_toolsets(['haos_missions'])
    async def close(self):
        closing[0]=True
        callbacks.stop()
        if callback_worker[0] is not None:
            callback_worker[0].cancel();await asyncio.gather(callback_worker[0],return_exceptions=True);callback_worker[0]=None
        receivers={task for task in receive_tasks if task is not asyncio.current_task()}
        for task in receivers:task.cancel()
        await asyncio.gather(*receivers,return_exceptions=True)
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
    adapter._haos_a2a_cancel_prevented=MethodType(cancel_prevented,adapter)
    adapter._haos_a2a_receiving=lambda task_id:bool(receive_by_task.get(task_id))
    def lookup(proof):
        return inputs.lookup(proof) if 'target_task_id' in proof else tasks.by_source(proof['source_key'])
    def envelope(proof):
        return inputs.envelope(proof) if 'target_task_id' in proof else dict(proof['envelope'])
    adapter._advertised_skills=MethodType(skills,adapter);adapter._haos_a2a_check=check
    adapter._haos_a2a_source=source
    adapter._haos_a2a_lookup=lookup;adapter._haos_a2a_envelope=envelope;adapter._haos_a2a_inputs=inputs
    adapter._haos_a2a_final_lock=finalize_lock
    adapter._emit_terminal=MethodType(emit,adapter);adapter._sse_write=MethodType(sse,adapter)
    adapter._build_card=MethodType(card,adapter)
    def callback_health():return {**callbacks.health(),'worker_failed':callback_failed[0]}
    adapter._haos_a2a_callback_health=callback_health
    check()
    if peer in value.get('callbacks',{}):
        callback_worker[0]=asyncio.create_task(callbacks.run())
        def callback_finished(task):
            if not task.cancelled() and task.exception() is not None:callback_failed[0]=True
        callback_worker[0].add_done_callback(callback_finished)
    return adapter
