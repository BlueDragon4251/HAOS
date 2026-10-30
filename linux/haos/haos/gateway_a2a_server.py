"""Bounded TLS front door around the actual frozen A2A HTTP request handler."""
import asyncio
from collections import Counter
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
import io
import json
import re
import socket
import threading
from urllib.parse import urlsplit

from .gateway import Conflict
from .gateway_a2a_admission import parse,security_context,SEND,Refused
from .gateway_a2a import opaque
from .gateway_matrix_profile import scope as private_scope


class Server:
    def __init__(self,value,connector,adapters,current,policy,capture,*,cancel=None):
        if (not adapters or set(adapters)!=set(value['peer_tokens']) or not callable(current) or not callable(policy)
                or not callable(capture) or cancel is not None and not callable(cancel)):
            raise PermissionError('fixed native A2A peers and independent parent custody required')
        self.value=value;self.connector=connector;self.adapters=adapters;self.current=current;self.policy=policy
        self.capture=capture;self.cancel=cancel;self.loop=asyncio.get_running_loop();self.httpd=None;self.thread=None;self.watcher=None;self.sockets=set();self.socket_lock=threading.Lock();self.workers=set();self.pending=set();self.closing=None;self.closing_owner=None
        self.security=security_context(value);self.closed=False
        from plugins.platforms.a2a.protocol import RateLimiter
        self.limiter=RateLimiter();self.connections=threading.BoundedSemaphore(16);self.peer_lock=threading.Lock();self.peers=Counter()

    def parent(self,coroutine,timeout=15):
        future=asyncio.run_coroutine_threadsafe(coroutine,self.loop)
        with self.socket_lock:
            if self.closed:future.cancel();raise PermissionError('private A2A parent request closed')
            self.pending.add(future)
        try:return future.result(timeout=timeout)
        except BaseException:future.cancel();raise
        finally:
            with self.socket_lock:self.pending.discard(future)

    def control(self,adapter,method,params):
        from plugins.platforms.a2a import protocol
        allowed={'GetTask','tasks/get','SubscribeToTask','tasks/subscribe','CancelTask','tasks/cancel','ListTasks','tasks/list'}
        if method not in allowed:raise Refused('unsupported-method')
        if method in {'ListTasks','tasks/list'}:
            if not set(params)<={'contextId','pageSize','pageToken','includeArtifacts','status','state'}:raise Refused('unsupported-content')
            if ('pageSize' in params and (type(params['pageSize']) is not int or not 1<=params['pageSize']<=100)
                    or 'includeArtifacts' in params and type(params['includeArtifacts']) is not bool):raise Refused('unsupported-content')
            if 'pageToken' in params:
                token=params['pageToken']
                if not isinstance(token,str) or token and (not token.isascii() or not token.isdecimal() or len(token)>5 or int(token)>65536):raise Refused('unsupported-content')
            if 'contextId' in params:opaque(params['contextId'])
            states=protocol.TERMINAL_STATES|{protocol.STATE_SUBMITTED,protocol.STATE_WORKING,protocol.STATE_INPUT_REQUIRED}
            if any(not isinstance(params[k],str) or params[k] not in states for k in ['state','status'] if k in params):raise Refused('unsupported-content')
            if 'state' in params and 'status' in params and params['state']!=params['status']:raise Refused('unsupported-content')
            return None
        if set(params) not in ({'id'},{'taskId'},{'id','taskId'}):raise Refused('unsupported-content')
        task_id=params.get('id',params.get('taskId'))
        if 'id' in params and 'taskId' in params and params['id']!=params['taskId']:raise Refused('unsupported-content')
        if not isinstance(task_id,str) or not re.fullmatch('task-[0-9a-f]{16}',task_id):raise Refused('unknown-task')
        try:row=adapter.tasks.get(task_id)
        except PermissionError:raise Refused('unknown-task') from None
        if row is None:raise Refused('unknown-task')
        source=adapter.tasks.entry(task_id)
        binding=adapter.tasks.authorize(source)
        capability='cancel' if method in {'CancelTask','tasks/cancel'} else 'read'
        if capability not in binding['capabilities']:raise Refused('unapproved-route')
        if capability=='cancel' and row['state'] not in protocol.TERMINAL_STATES:
            if self.cancel is None:raise Refused('cancel-unavailable')
            result=self.parent(self.cancel(adapter,dict(source)))
            if result!={'cancel_requested':True}:raise Refused('cancel-unavailable')
        return row

    def handler(self):
        from plugins.platforms.a2a.adapter import A2ARequestHandler
        from plugins.platforms.a2a import protocol
        broker=self;hostname=urlsplit(self.value['tls']['public_url']).hostname
        class Handler(A2ARequestHandler):
            @property
            def adapter(self):return self._adapter
            def log_message(self,*_args):pass
            def _request_public_url(self):return broker.value['tls']['public_url']
            def end_headers(self):
                broker.current()
                if broker.closed:raise PermissionError('private A2A listener closed')
                self._sent_headers=True;super().end_headers()
            def _json(self,code,payload):
                broker.current()
                if broker.closed:raise PermissionError('private A2A listener closed')
                if self.command=='GET' and isinstance(payload,dict) and 'served_agents' in payload:
                    payload={key:part for key,part in payload.items() if key!='served_agents'}
                if len(json.dumps(payload).encode())>1024*1024:
                    code=200;payload=protocol.jsonrpc_error(payload.get('id'),protocol.ERR_INVALID_PARAMS,'response limit; request a smaller task page')
                return super()._json(code,payload)
            def do_GET(self):
                self._sent_headers=False;self.close_connection=True
                try:
                    self.guard()
                    routes={'/a2a':'/','/a2a/health':'/health',
                        '/.well-known/agent-card.json':'/.well-known/agent-card.json','/.well-known/agent.json':'/.well-known/agent.json',
                        '/a2a/.well-known/agent-card.json':'/.well-known/agent-card.json','/a2a/.well-known/agent.json':'/.well-known/agent.json'}
                    if self.path not in routes:return self._json(404,{'error':'not found'})
                    peer=broker.security.authenticate(self.headers.get('Authorization'),self._client_ip())
                    self._adapter=broker.adapters.get(peer,next(iter(broker.adapters.values())))
                    self.path=routes[self.path]
                    with private_scope(self.adapter._haos_a2a_home,self.adapter._haos_a2a_environment):super().do_GET()
                except Exception:
                    if not self._sent_headers:self._json(503,{'error':'private A2A server unavailable'})
            def guard(self):
                broker.current()
                if broker.closed:raise PermissionError('private A2A listener closed')
                self.connection.settimeout(5)
                if (self.headers.get_all('Host') not in ([hostname],[hostname+':443'])
                        or len(self.headers)>32 or self.headers.get_all('Transfer-Encoding')
                        or len(self.headers.get_all('Authorization',[]))>1):raise Refused('unsupported-content')
            def do_POST(self):
                self._sent_headers=False;self.close_connection=True;peer=None;leased=False;req_id=None
                try:
                    self.guard()
                    if self.path not in {'/a2a','/a2a/'}:return self._error(404,None,protocol.ERR_METHOD_NOT_FOUND,'not found')
                    peer=broker.security.authenticate(self.headers.get('Authorization'),self._client_ip())
                    if peer is None:return self._error(401,None,protocol.ERR_UNAUTHORIZED,'unauthorized')
                    self._adapter=broker.adapters[peer]
                    with broker.peer_lock:
                        if broker.peers[peer]>=4:return self._error(429,None,protocol.ERR_RATE_LIMITED,'peer connection limit')
                        broker.peers[peer]+=1;leased=True
                    if not broker.limiter.allow(peer):return self._error(429,None,protocol.ERR_RATE_LIMITED,'rate limit exceeded')
                    lengths=self.headers.get_all('Content-Length',[])
                    if (len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                            or len(lengths[0])>7 or not 1<=int(lengths[0])<=1024*1024
                            or self.headers.get_content_type()!='application/json'
                            or self.headers.get_content_charset('utf-8').lower() not in {'utf-8','utf8'}):raise Refused('unsupported-content')
                    raw=self.rfile.read(int(lengths[0]))
                    if len(raw)!=int(lengths[0]):raise Refused('unsupported-content')
                    request=parse(raw)
                    if (set(request)!={'jsonrpc','id','method','params'} or request['jsonrpc']!='2.0'
                            or type(request['id']) not in {str,int} or type(request['id']) is int and not -(2**53)<request['id']<2**53
                            or isinstance(request['id'],str) and not 1<=len(request['id'])<=128
                            or not isinstance(request['method'],str) or not isinstance(request['params'],dict)):
                        raise Refused('unsupported-content')
                    version=(self.headers.get('A2A-Version') or '').strip()
                    if version and version not in {'1.0','1.0.0'}:raise Refused('unsupported-version')
                    req_id=request['id'];method=request['method'];proof=None
                    if method in SEND:
                        proof=broker.parent(broker.capture(peer,raw))
                        existing=self.adapter.tasks.by_source(proof['source_key'])
                        if existing is not None:
                            binding=self.adapter.tasks.authorize(existing)
                            record=self.adapter.tasks.get(existing['task_id'])
                            task=protocol.TaskStore.to_task(record,include_artifacts='read' in binding['capabilities'])
                            if 'read' not in binding['capabilities']:
                                task=protocol.build_task(record['task_id'],record['context_id'],record['state'])
                            if method in {'SendStreamingMessage','message/stream'}:
                                self.adapter._sse_headers(self)
                                self.adapter._sse_write(self,protocol.sse_data(protocol.stream_task(task),req_id))
                                return self.adapter._sse_write(self,protocol.sse_done())
                            return self._json(200,protocol.jsonrpc_result(req_id,protocol.send_message_response(task) if method=='SendMessage' else task))
                    else:
                        broker.control(self.adapter,method,request['params'])
                        if method in {'ListTasks','tasks/list'}:
                            request['params']['pageSize']=min(request['params'].get('pageSize',8),8)
                            raw=json.dumps(request,separators=(',',':')).encode()
                    # The exact authenticated bytes are handed to the real native
                    # HTTP parser/RPC dispatcher. No caller-selectable adapter.
                    self.rfile=io.BytesIO(raw)
                    with ExitStack() as stack:
                        stack.enter_context(private_scope(self.adapter._haos_a2a_home,self.adapter._haos_a2a_environment))
                        if proof is not None:stack.enter_context(self.adapter.tasks.source(broker.connector,proof))
                        super().do_POST()
                except Refused as error:
                    if not self._sent_headers:
                        code=protocol.ERR_TASK_NOT_FOUND if error.reason=='unknown-task' else protocol.ERR_METHOD_NOT_FOUND if error.reason in {'unsupported-method','cancel-unavailable'} else protocol.ERR_INVALID_PARAMS
                        self._error(200,req_id,code,error.reason)
                except (PermissionError,Conflict):
                    if not self._sent_headers:self._error(403,req_id,protocol.ERR_UNAUTHORIZED,'source or operation not approved')
                except Exception:
                    if not self._sent_headers:self._error(503,req_id,protocol.ERR_INVALID_PARAMS,'private A2A operation unavailable')
                finally:
                    if leased:
                        with broker.peer_lock:broker.peers[peer]-=1
        return Handler

    def start(self,tls):
        broker=self;self.current()
        if self.httpd is not None or self.closed:raise PermissionError('private A2A listener cannot be reused')
        class Bounded(ThreadingHTTPServer):
            daemon_threads=True;allow_reuse_address=False;request_queue_size=16
            address_family=socket.AF_INET6 if broker.value['tls']['bind_host']=='::' else socket.AF_INET
            def process_request(self,request,address):
                if broker.closed:request.close();return
                if not broker.connections.acquire(blocking=False):request.close();return
                with broker.socket_lock:broker.sockets.add(request)
                try:super().process_request(request,address)
                except BaseException:
                    broker.connections.release()
                    with broker.socket_lock:broker.sockets.discard(request)
                    request.close();raise
            def process_request_thread(self,request,address):
                plain=request;wrapped=None
                with broker.socket_lock:broker.workers.add(threading.current_thread())
                try:
                    wrapped=tls.wrap_socket(request,server_side=True,do_handshake_on_connect=False)
                    with broker.socket_lock:broker.sockets.discard(plain);broker.sockets.add(wrapped)
                    if broker.closed:raise PermissionError('private A2A listener closed')
                    wrapped.settimeout(3);wrapped.do_handshake()
                    super().process_request_thread(wrapped,address)
                except Exception:
                    request.close()
                    if wrapped is not None:wrapped.close()
                finally:
                    with broker.socket_lock:broker.sockets.discard(plain);broker.sockets.discard(wrapped);broker.workers.discard(threading.current_thread())
                    broker.connections.release()
            def handle_error(self,*_args):pass
        self.httpd=Bounded((self.value['tls']['bind_host'],self.value['port']),self.handler())
        listener=self.httpd
        self.thread=threading.Thread(target=lambda:listener.serve_forever(poll_interval=.1),name='private-a2a-https',daemon=True);self.thread.start()
        self.watcher=asyncio.create_task(self.watch())
        self.current()

    async def watch(self):
        try:
            while not self.closed:self.current();await asyncio.sleep(.1)
        except asyncio.CancelledError:raise
        except Exception:await self.close()

    async def close(self):
        self.closed=True
        if self.closing is None:
            self.closing_owner=asyncio.current_task();self.closing=asyncio.create_task(self.cleanup())
        try:await asyncio.shield(self.closing)
        except asyncio.CancelledError:
            if asyncio.current_task() is not self.watcher:await self.closing
            raise

    async def cleanup(self):
        if self.watcher is not None and self.watcher is not self.closing_owner:
            self.watcher.cancel();await asyncio.gather(self.watcher,return_exceptions=True)
        self.watcher=None
        server=self.httpd;self.httpd=None
        if server is not None:
            await asyncio.to_thread(server.shutdown);server.server_close()
        with self.socket_lock:
            for future in tuple(self.pending):future.cancel()
            self.pending.clear()
            for connection in tuple(self.sockets):
                try:connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                connection.close()
            self.sockets.clear()
        for adapter in self.adapters.values():await adapter.close_profile()
        deadline=asyncio.get_running_loop().time()+3
        while True:
            with self.socket_lock:active=bool(self.workers)
            if not active:break
            if asyncio.get_running_loop().time()>=deadline:raise RuntimeError('private A2A HTTP workers did not terminate')
            await asyncio.sleep(.02)
        if self.thread is not None:
            await asyncio.to_thread(self.thread.join,3)
            if self.thread.is_alive():raise RuntimeError('private A2A listener did not terminate')
            self.thread=None
