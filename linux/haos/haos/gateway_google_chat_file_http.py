"""Prepared actual user-authenticated SDK; all custody stays on its event loop."""
import asyncio
import threading
from types import MethodType

from .gateway import Conflict
from .gateway_google_chat_oauth_tokens import TokenVault,Deferred


class OnLoop:
    def __init__(self):self.loop=asyncio.get_running_loop();self.thread=threading.get_ident();self.closed=threading.Event()

    def call(self,operation):
        if self.closed.is_set() or self.loop.is_closed() or not self.loop.is_running():raise PermissionError('Google file capability ended')
        if threading.get_ident()==self.thread:return operation()
        async def checked():
            if self.closed.is_set():raise PermissionError('Google file capability ended')
            return operation()
        coroutine=checked()
        try:future=asyncio.run_coroutine_threadsafe(coroutine,self.loop)
        except RuntimeError:
            coroutine.close();raise PermissionError('Google file capability event loop ended') from None
        try:return future.result(timeout=5)
        except BaseException:future.cancel();raise


class FileAPI:
    @classmethod
    async def open(cls,store,policy,connector,account,route,current,*,http=None,certificate_request=None):
        from .gateway_google_chat_oauth_refresh import access
        guard=OnLoop()
        def before():return guard.call(current)
        try:
            sdk,snapshot=await access(store,policy,connector,account,route,before,http=http,certificate_request=certificate_request)
            result=cls();result.guard=guard;result.store=store;result.policy=policy;result.connector=connector;result.account=account
            result.route=dict(route);result.check=current;result.snapshot=snapshot;result.credentials=sdk;result.vault=TokenVault(store)
            def deny_refresh(_credentials,_request):raise Deferred('user-refresh-required')
            # This exact instance can refresh only through the separate FULL
            # refresh journal, never inside AuthorizedHttp's request path.
            sdk.refresh=MethodType(deny_refresh,sdk)
            from google_auth_httplib2 import AuthorizedHttp
            from googleapiclient.discovery import build
            from .gateway_google_chat_http import single_request_http
            wire=http if http is not None else single_request_http(result.current,redactor=store.inbox.redactor)
            result.http=AuthorizedHttp(sdk,http=wire,max_refresh_attempts=0)
            result.service=build('chat','v1',http=result.http,cache_discovery=False,static_discovery=True)
            result.current();return result
        except BaseException:guard.closed.set();raise

    def current(self):
        def checked():
            self.check();current=self.vault.load(self.policy(),self.connector,self.account,self.route)
            row=current['row'];expected=self.snapshot['row']
            if row['id']!=expected['id'] or row['generation']!=expected['generation'] or row['client_sha256']!=expected['client_sha256']:
                raise PermissionError('Google file user credentials changed during the operation')
            return current
        return self.guard.call(checked)

    def failure(self,error):
        from googleapiclient.errors import HttpError
        if not isinstance(error,HttpError) or error.resp.status not in {401,403,429}:return
        from .gateway_google_chat_retry import retry_after
        status='rate-limited' if error.resp.status==429 else 'authentication-refused'
        delay=retry_after(error) if status=='rate-limited' else 0
        def retain():
            self.check();self.vault.api_failure(self.snapshot,status,retry_after=delay)
        self.guard.call(retain)

    def execute(self,request):
        self.current()
        try:
            result=request.execute(http=self.http,num_retries=0);self.current();return result
        except BaseException as error:
            self.failure(error);raise

    def close(self):
        self.guard.closed.set()
        if hasattr(self.http,'close'):self.http.close()
