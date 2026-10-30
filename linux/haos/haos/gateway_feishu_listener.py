"""Fixed Feishu HTTPS receive application; only durable authenticated bytes get ACKs."""
import asyncio
import json
import time

from .gateway import Conflict
from .gateway_feishu_admission import Refused
from .gateway_feishu_webhook import MAX_WIRE


class Limits:
    """Bounded volatile listener admission, never sender authorization or persistence."""
    def __init__(self):self.addresses={};self.active=0;self.tokens=64.;self.last=time.monotonic()
    def admit(self,address):
        now=time.monotonic();self.tokens=min(64.,self.tokens+(now-self.last)*2);self.last=now
        self.addresses={key:value for key,value in self.addresses.items() if now-value[1]<60}
        if self.active>=8 or self.tokens<1:return False
        if address not in self.addresses and len(self.addresses)>=256:return False
        count,last=self.addresses.get(address,(16.,now));count=min(16.,count+(now-last))
        if count<1:return False
        self.addresses[address]=(count-1,now);self.tokens-=1;return True


def application(receiver):
    """Caller must bind with reviewed TLS and AppRunner(auto_decompress=False)."""
    from aiohttp import web
    limits=Limits()
    async def receive(request):
        if not request.secure:return web.Response(status=400,text='HTTPS required')
        if request.query_string or request.headers.get('Content-Encoding','identity').lower()!='identity':
            return web.Response(status=400,text='unsupported request encoding')
        if request.content_type!='application/json':return web.Response(status=415,text='JSON required')
        if request.content_length is not None and request.content_length>MAX_WIRE:
            return web.Response(status=413,text='payload too large')
        if not limits.admit(request.remote or ''):return web.Response(status=429,text='receive rate limited',headers={'Retry-After':'1'})
        limits.active+=1
        try:
            body=await asyncio.wait_for(request.read(),timeout=5)
            result=receiver.receive(list(request.headers.items()),body)
        except web.HTTPRequestEntityTooLarge:return web.Response(status=413,text='payload too large')
        except Refused as error:
            code=401 if error.reason in {'invalid-authentication','stale-authentication','unapproved-route',
                'wrong-application','wrong-tenant','self-or-automated','pre-grant'} else 400
            return web.Response(status=code,text='request refused')
        except Conflict:return web.Response(status=503,text='retained source requires recovery')
        except (asyncio.TimeoutError,ValueError,UnicodeError,TypeError):return web.Response(status=400,text='invalid request')
        except PermissionError:return web.Response(status=401,text='request not authorized')
        except Exception:return web.Response(status=503,text='admission unavailable')
        finally:limits.active-=1
        return web.json_response(result)
    app=web.Application(client_max_size=MAX_WIRE)
    app.router.add_post('/feishu/webhook',receive)
    return app
