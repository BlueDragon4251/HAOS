"""Fixed private Google Chat HTTPS callback; auth and FULL custody before ACK."""
import asyncio

from .gateway import Conflict
from .gateway_google_chat_admission import Refused


def application(receiver):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();receiver.current()
    if receiver.value['inbound']['mode']!='http':raise PermissionError('saved private Google Chat HTTP receiver required')
    from aiohttp import web
    from .gateway_feishu_listener import Limits
    limits=Limits()
    async def receive(request):
        if not request.secure:return web.Response(status=400,text='HTTPS required')
        if request.query_string or request.headers.get('Content-Encoding','identity').lower()!='identity':
            return web.Response(status=400,text='unsupported encoding')
        if request.content_type!='application/json':return web.Response(status=415,text='JSON required')
        if request.content_length is not None and request.content_length>1048576:return web.Response(status=413,text='payload too large')
        if not limits.admit(request.remote or ''):return web.Response(status=429,text='receive rate limited',headers={'Retry-After':'1'})
        limits.active+=1
        try:
            body=await asyncio.wait_for(request.read(),timeout=5)
            headers=[(k.decode('ascii'),v.decode('latin1')) for k,v in request.raw_headers]
            await asyncio.wait_for(receiver.http_async(headers,body),timeout=10)
        except web.HTTPRequestEntityTooLarge:return web.Response(status=413,text='payload too large')
        except Refused as error:
            return web.Response(status=503 if error.reason=='certificate-service-unavailable' else 401,text='authentication unavailable' if error.reason=='certificate-service-unavailable' else 'request refused')
        except PermissionError:return web.Response(status=401,text='request not authorized')
        except Conflict:return web.Response(status=503,text='retained source requires recovery')
        except (ValueError,UnicodeError,TypeError):return web.Response(status=400,text='invalid request')
        except Exception:return web.Response(status=503,text='admission unavailable')
        finally:limits.active-=1
        return web.json_response({})
    app=web.Application(client_max_size=1048576);app.router.add_post('/google-chat',receive)
    return app
