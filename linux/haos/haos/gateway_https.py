"""Closed-route HTTPS multiplexing for independently authorized webhook profiles."""
import asyncio
from dataclasses import dataclass,field
from urllib.parse import urlsplit
import weakref

from .gateway import digest

_ROUTES={'line':{'webhook':'/line/webhook','output':'/line/output/{token}'},
         'sms':{'webhook':'/webhooks/twilio','output':'/sms/output/{token}'}}
_SERVERS={}
_LOCKS=weakref.WeakKeyDictionary()


def lock():
    loop=asyncio.get_running_loop()
    if loop not in _LOCKS:_LOCKS[loop]=asyncio.Lock()
    return _LOCKS[loop]


@dataclass
class Shared:
    fingerprint:str
    runner:object
    registrations:dict=field(default_factory=dict)


class Handle:
    def __init__(self,key,identity,server):self.key=key;self.identity=identity;self.server=server;self.closed=False
    async def cleanup(self):
        async with lock():
            if self.closed:return
            self.closed=True;self.server.registrations.pop(self.identity,None)
            if not self.server.registrations:
                try:await self.server.runner.cleanup()
                finally:
                    if _SERVERS.get(self.key) is self.server:_SERVERS.pop(self.key)


def handlers(platform,application):
    expected=_ROUTES.get(platform)
    if expected is None:raise PermissionError('reviewed webhook platform required')
    found={}
    for route in application.router.routes():
        path=route.resource.canonical
        name=next((name for name,value in expected.items() if value==path),None)
        if name is None or route.method not in ({'POST'} if name=='webhook' else {'GET','HEAD'}):
            raise PermissionError('only fixed independent webhook/media routes may be registered')
        if route.method!='HEAD':found[name]=route.handler
    if 'webhook' not in found:raise PermissionError('fixed authenticated webhook handler required')
    return found


async def start(platform,value,application,context):
    """Share a listener only for identical owner-approved bind/TLS material.

    A profile receives an opaque cleanup lease, never another profile's handler.
    Different public hostnames select their own independently signed receiver.
    """
    from aiohttp import web
    callbacks=handlers(platform,application);tls=value.get('tls')
    host=tls['bind_host'] if tls else '127.0.0.1';port=value['port']
    if context is None and (tls is not None or host!='127.0.0.1'):raise PermissionError('verified TLS required for published listeners')
    if (context is None)!=(tls is None):raise PermissionError('TLS listener/context mismatch')
    public_host=urlsplit(tls['public_url']).hostname if tls else ''
    fingerprint=digest({k:v for k,v in tls.items() if k!='public_url'}) if tls else digest(['private-loopback-only'])
    key=(asyncio.get_running_loop(),host,port)
    async with lock():
        server=_SERVERS.get(key)
        if server is not None and server.fingerprint!=fingerprint:
            raise ValueError('shared HTTPS port requires identical owner certificate, key and bind consent')
        if server is not None and any(r['platform']==platform and r['host']==public_host for r in server.registrations.values()):
            raise PermissionError('webhook profile already owns that exact HTTPS route')
        if server is None:
            app=web.Application(client_max_size=65536)
            server=Shared(fingerprint,None)
            def dispatch(which,kind):
                async def receive(request):
                    candidates=[r for r in server.registrations.values() if r['platform']==which and kind in r['handlers']]
                    try:host_value=urlsplit('https://'+request.host).hostname
                    except ValueError:return web.Response(status=400)
                    exact=[r for r in candidates if r['host']==host_value]
                    selected=exact if exact else candidates if len(candidates)==1 else []
                    if len(selected)!=1:return web.Response(status=404)
                    return await selected[0]['handlers'][kind](request)
                return receive
            for which,paths in _ROUTES.items():
                app.router.add_post(paths['webhook'],dispatch(which,'webhook'))
                app.router.add_get(paths['output'],dispatch(which,'output'))
            runner=web.AppRunner(app,access_log=None,shutdown_timeout=5);server.runner=runner
            try:
                await runner.setup()
                await web.TCPSite(runner,host,port,ssl_context=context).start()
            except BaseException:
                await runner.cleanup();raise
            _SERVERS[key]=server
        identity=object();server.registrations[identity]={'platform':platform,'host':public_host,'handlers':callbacks}
        return Handle(key,identity,server)
