"""Private Google Chat lifecycle around native codecs and independent journals.

Public factory/owner provisioning and media/OAuth remain separate activation
work. No native agent runner, setup-files command or plugin dispatcher is used.
"""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import time
from types import MethodType,SimpleNamespace

from .gateway import GatewayPolicy,Conflict,digest
from .gateway_google_chat import credentials,scope as account_scope,validate_binding,validate_overlaps
from .gateway_google_chat_custody import Originals
from .gateway_google_chat_receive import Receiver
from .gateway_google_chat_ingress import install,capture_stored,dispatch_stored

STATES=frozenset({'created','connecting','connected-pull','listening-tls','disconnected','closed','revoked',
    'authentication-refused','identity-refused','rate-limited','transport-unavailable','source-unavailable','storage-unavailable'})
BLOCKS=frozenset({'authentication-refused','identity-refused'})


def build(value,*,parent,connector,policy,inbox):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value)
    def snapshot(latest):
        if not isinstance(latest,GatewayPolicy) or latest.connectors.get(connector,{}).get('platform')!='google_chat':
            raise PermissionError('independent Google Chat owner policy required')
        validate_overlaps(latest);rows=[row for row in latest.bindings.values() if row['connector']==connector]
        if not rows or len({row['chat'] for row in rows})>32:raise PermissionError('one to 32 explicitly paired Google Chat spaces required')
        for row in rows:
            validate_binding(row)
            if row['scope']!=account_scope(value) or row['sender']==value['bot_user']:raise PermissionError('Google account scope or self grant differs')
        return digest([latest.publication,connector,sorted(rows,key=lambda row:row['id']),value])
    identity=snapshot(policy())
    def pinned():
        latest=policy()
        if snapshot(latest)!=identity:raise PermissionError('Google Chat owner publication, account or grants changed')
        return latest
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease,scope
    parent=Path(parent);_directory(parent);profile=parent/('google-chat-'+digest(account_scope(value)))
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    lease=acquire_lease(profile);originals=None
    try:
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        from .redaction import Redactor
        aliases=[value['service_account']['private_key']]
        if value['inbound']['mode']=='http':aliases.append(value['inbound']['tls']['private_key'])
        inbox.redactor.secrets=Redactor([*inbox.redactor.secrets,*aliases]).secrets
        environment={'HERMES_SAFE_MODE':'1','GATEWAY_ALLOW_ALL_USERS':'false','GOOGLE_CHAT_ALLOWED_USERS':'',
            'GOOGLE_APPLICATION_CREDENTIALS':'','GOOGLE_CHAT_SERVICE_ACCOUNT_JSON':'','PUBSUB_EMULATOR_HOST':''}
        extra={'service_account_json':json.dumps(value['service_account']), 'project_id':value['service_account']['project_id']}
        if value['inbound']['mode']=='pubsub':extra['subscription_name']=value['inbound']['subscription']
        else:extra.update(http_events_url=value['inbound']['tls']['public_url'],http_events_audience=value['inbound']['audience'],
            http_events_service_account_email=value['inbound']['service_account_email'])
        with scope(home,environment):
            from gateway.config import PlatformConfig
            from plugins.platforms.google_chat import adapter as native
            from .gateway_ingress import durable_adapter
            adapter=install(durable_adapter(native.GoogleChatAdapter(PlatformConfig(enabled=True,extra=extra))))
        adapter._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
        adapter._haos_google_value=value;adapter._haos_google_home=home;adapter._haos_google_environment=environment
        adapter._haos_google_closed=False;adapter._haos_google_stopping=False
        def current():
            require_runtime_identity()
            if adapter._haos_google_closed or adapter._haos_google_stopping:raise PermissionError('private Google Chat profile stopped')
            if adapter._haos_google_value!=value:raise PermissionError('Google Chat account changed')
            return pinned()
        adapter._haos_google_check=current
        originals=Originals(profile/'originals.sqlite',inbox.redactor);adapter._haos_google_originals=originals
        adapter._haos_google_receiver=Receiver(connector,value,originals,pinned,current)
        from .gateway_google_chat_http import single_request_http
        def http(self):
            current()
            from google_auth_httplib2 import AuthorizedHttp
            return AuthorizedHttp(self._credentials,http=single_request_http(current,redactor=inbox.redactor),max_refresh_attempts=0)
        adapter._new_authed_http=MethodType(http,adapter)
        return _lifecycle(adapter,profile,lease,identity)
    except BaseException:
        if originals is not None:originals.close()
        os.close(lease);raise


def _lifecycle(adapter,profile,lease,identity):
    value=adapter._haos_google_value;native=adapter._haos_native;db=native.inbox.db;check=adapter._haos_google_check
    from .gateway_google_chat_delivery import Publisher
    publisher=Publisher(adapter);lifecycle=asyncio.Lock();credential_scope=digest([native.connector,value])
    adapter._haos_google_runner=None;adapter._haos_google_pull=None
    adapter._haos_google_tasks={};adapter._haos_google_publisher=publisher
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,
        credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    previous=db.execute('SELECT status,next_attempt FROM google_chat_profile_status WHERE connector=? AND credential_scope=?',
        (native.connector,credential_scope)).fetchall()
    block=next((row['status'] for row in previous if row['status'] in BLOCKS),None)
    deadline=max([row['next_attempt'] for row in previous]+[0])
    db.execute('INSERT OR IGNORE INTO google_chat_profile_status VALUES(?,?,?,?,?,?)',
        (identity,native.connector,credential_scope,block or 'created',time.time(),deadline))
    budget_scope=account_scope(value)
    db.execute('CREATE TABLE IF NOT EXISTS google_chat_profile_budget(scope TEXT PRIMARY KEY,not_before REAL NOT NULL)')
    db.execute('INSERT OR IGNORE INTO google_chat_profile_budget VALUES(?,?)',(budget_scope,deadline))
    def not_before():return db.execute('SELECT not_before FROM google_chat_profile_budget WHERE scope=?',(budget_scope,)).fetchone()[0]
    def status(state,delay=0):
        if state not in STATES:raise ValueError('finite Google Chat profile state required')
        wait=max(not_before(),time.time()+delay if delay else 0)
        db.execute('UPDATE google_chat_profile_budget SET not_before=? WHERE scope=?',(wait,budget_scope))
        db.execute('UPDATE google_chat_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
            (state,time.time(),wait,identity))
    def health(self):
        result=dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM google_chat_profile_status WHERE identity=?',(identity,)).fetchone())
        result['next_attempt']=max(result['next_attempt'],not_before());return result
    def classify(error):
        if isinstance(error,ImportError):return 'transport-unavailable'
        from .gateway_google_chat_http import TokenError
        if isinstance(error,TokenError):return error.category
        from google.api_core import exceptions as gax
        from google.auth import exceptions as auth
        from googleapiclient.errors import HttpError
        if isinstance(error,(gax.Unauthenticated,auth.RefreshError)) or isinstance(error,HttpError) and error.resp.status==401:return 'authentication-refused'
        if isinstance(error,gax.PermissionDenied) or isinstance(error,HttpError) and error.resp.status in {403,404}:return 'identity-refused'
        if isinstance(error,gax.ResourceExhausted) or isinstance(error,HttpError) and error.resp.status==429:return 'rate-limited'
        if isinstance(error,sqlite3.Error):return 'storage-unavailable'
        if isinstance(error,Conflict):return 'source-unavailable'
        return 'transport-unavailable'
    async def stop():
        # Closing the channel cancels real blocking RPCs, not only their Python
        # awaiter. SQL and listener work stay on the owning asyncio thread.
        pull=adapter._haos_google_pull;adapter._haos_google_pull=None
        if pull is not None:pull.close()
        tasks=[task for task in adapter._haos_google_tasks.values() if task is not asyncio.current_task()]
        adapter._haos_google_tasks={}
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        runner=adapter._haos_google_runner;adapter._haos_google_runner=None
        if runner is not None:await runner.cleanup()
        from .gateway_matrix_profile import scope
        with scope(adapter._haos_google_home,adapter._haos_google_environment):adapter._mark_disconnected()
    async def monitor():
        while True:
            try:check()
            except PermissionError:
                if health(adapter)['status'] not in BLOCKS:status('revoked')
                adapter._haos_google_stopping=True;await stop();return
            await asyncio.sleep(.1)
    async def receive():
        while True:
            check();delay=health(adapter)['next_attempt']-time.time()
            if delay>0:await asyncio.sleep(min(2,delay));continue
            try:
                await adapter._haos_google_pull.step();status('connected-pull')
            except asyncio.CancelledError:raise
            except PermissionError:
                check();status('source-unavailable',2)
            except Exception as error:
                check();state=classify(error)
                from .gateway_google_chat_retry import retry_after
                status(state,max(retry_after(error),getattr(error,'retry_after',0)) if state=='rate-limited' else 2)
                if state in BLOCKS:
                    adapter._haos_google_stopping=True;await stop();return
                await asyncio.sleep(2)
    async def replay():
        while True:
            check();delay=health(adapter)['next_attempt']-time.time()
            if delay>0:await asyncio.sleep(min(2,delay));continue
            try:
                rows=adapter._haos_google_originals.db.execute('SELECT id FROM google_chat_originals WHERE connector=? AND credential_scope=? AND admitted_receipt=? ORDER BY created_at LIMIT 128',
                    (native.connector,credential_scope,'')).fetchall()
                for row in rows:await capture_stored(adapter,row['id'])
                for _ in range(16):
                    key=native.inbox.due(native.connector)
                    if key is None:break
                    await dispatch_stored(adapter,key)
            except asyncio.CancelledError:raise
            except PermissionError:
                check();status('source-unavailable',2)
            except Exception as error:
                check();state=classify(error)
                from .gateway_google_chat_retry import retry_after
                status(state,max(retry_after(error),getattr(error,'retry_after',0)) if state=='rate-limited' else 2)
            await asyncio.sleep(.5)
    def delivery_error(error):
        state=classify(error)
        from .gateway_google_chat_retry import retry_after
        status(state,max(retry_after(error),getattr(error,'retry_after',0)) if state=='rate-limited' else 2)
        if state in BLOCKS:
            adapter._haos_google_stopping=True;asyncio.create_task(stop())
    adapter._haos_google_delivery_error=delivery_error
    async def account_check():
        check()
        from plugins.platforms.google_chat import adapter as upstream
        if not upstream._load_google_modules():raise RuntimeError('frozen Google Chat runtime unavailable')
        from .gateway_matrix_profile import scope
        with scope(adapter._haos_google_home,adapter._haos_google_environment):adapter._credentials=upstream.GoogleChatAdapter._load_sa_credentials(adapter)
        adapter._chat_api=upstream.build_service('chat','v1',http=adapter._new_authed_http(),cache_discovery=False,static_discovery=True)
        spaces=sorted({row['chat'] for row in native.policy().bindings.values() if row['connector']==native.connector})
        member_id=value['bot_user'].split('/',1)[1]
        for space in spaces:
            check()
            member=await asyncio.to_thread(lambda selected=space:adapter._chat_api.spaces().members().get(
                name=selected+'/members/'+member_id).execute(http=adapter._new_authed_http(),num_retries=0))
            check()
            if (not isinstance(member,dict) or member.get('state')!='MEMBER' or not isinstance(member.get('member'),dict)
                    or member['member'].get('name')!=value['bot_user'] or member['member'].get('type')!='BOT'):
                raise PermissionError('Google Chat app membership differs from expected bot identity')
        adapter._bot_user_id=value['bot_user']
    adapter._haos_google_account_check=account_check
    def subscriber():
        from .gateway_google_chat_pubsub import create_client
        return create_client(value,check,redactor=native.inbox.redactor)
    adapter._haos_google_subscriber_factory=subscriber
    async def connect(self):
        async with lifecycle:
            if self._haos_google_closed:raise PermissionError('Google Chat profile closed')
            if self._haos_google_tasks:return self.is_connected
            previous=health(self)
            if previous['status'] in BLOCKS|{'revoked'} or previous['next_attempt']>time.time():return False
            self._haos_google_stopping=False;check();status('connecting')
            try:
                await self._haos_google_account_check();check()
                if value['inbound']['mode']=='pubsub':
                    from .gateway_google_chat_pubsub import PullTransport,create_client,rpc_call
                    client=self._haos_google_subscriber_factory()
                    try:
                        subscription=await rpc_call(client,'get_subscription',request={'subscription':value['inbound']['subscription']},timeout=10)
                        check()
                        if subscription.name!=value['inbound']['subscription'] or subscription.detached:raise PermissionError('saved Google subscription unavailable')
                        self._haos_google_pull=PullTransport(client,self._haos_google_receiver,check)
                    except BaseException:client.close();raise
                    status('connected-pull')
                else:
                    from aiohttp import web
                    from .gateway_line_tls import context
                    from .gateway_google_chat_auth import TokenVerifier
                    from .gateway_google_chat_listener import application
                    inbound=value['inbound'];tls=context(inbound['tls'],profile,webhook_path='/google-chat')
                    self._haos_google_receiver.http_verifier=TokenVerifier(inbound['audience'],inbound['service_account_email'],check)
                    runner=web.AppRunner(application(self._haos_google_receiver),access_log=None,auto_decompress=False,max_field_size=16384,shutdown_timeout=3)
                    self._haos_google_runner=runner;await runner.setup()
                    await web.TCPSite(runner,inbound['tls']['bind_host'],inbound['port'],ssl_context=tls).start();status('listening-tls')
                from .gateway_matrix_profile import scope
                with scope(self._haos_google_home,self._haos_google_environment):self._mark_connected()
                self._haos_google_tasks={'monitor':asyncio.create_task(monitor()),'replay':asyncio.create_task(replay())}
                if value['inbound']['mode']=='pubsub':self._haos_google_tasks['receive']=asyncio.create_task(receive())
                return True
            except asyncio.CancelledError:await stop();raise
            except Exception as error:
                await stop();state='identity-refused' if isinstance(error,PermissionError) else classify(error)
                from .gateway_google_chat_retry import retry_after
                status(state,max(retry_after(error),getattr(error,'retry_after',0)) if state=='rate-limited' else 2);return False
    async def disconnect(self):
        self._haos_google_stopping=True
        async with lifecycle:
            await stop()
            if health(self)['status'] not in BLOCKS|{'revoked','closed'}:status('disconnected')
    async def close(self):
        self._haos_google_stopping=True
        async with lifecycle:
            if self._haos_google_closed:return
            await stop();self._haos_google_closed=True;self._haos_google_originals.close();os.close(lease)
            if health(self)['status'] not in BLOCKS|{'revoked'}:status('closed')
    async def send(self,chat,content,reply_to=None,metadata=None):
        check()
        if not self.is_connected:raise PermissionError('Google Chat private profile is not connected')
        wait=health(self)['next_attempt']-time.time()
        if wait>0:
            from gateway.platforms.base import SendResult
            import math
            return SendResult(success=False,retryable=True,retry_after=min(86400,max(1,math.ceil(wait))),raw_response={'haos_delivery':'not-dispatched'})
        return await publisher.send(chat,content,reply_to,metadata)
    for name,method in {'connect':connect,'disconnect':disconnect,'_haos_close':close,'close_profile':close,
            '_haos_health':health,'native_health':health,'send':send}.items():setattr(adapter,name,MethodType(method,adapter))
    return adapter
