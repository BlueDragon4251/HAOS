"""Fixed-route LINE webhook application; private profile owns binding and TLS."""
import asyncio
import json

from .gateway_line_ingress import capture,snapshot


MAX_BODY=65536


def application(adapter,destination):
    """Create no sockets and expose no native media, health or plugin routes.

    Every 2xx follows independent current-policy admission and SQLite commit.
    Native decoding is separately replayable; it never needs the HTTP request.
    """
    from aiohttp import web
    native=adapter._haos_native
    snapshot(native.policy(),native.connector,destination)

    async def receive(request):
        signatures=request.headers.getall('X-Line-Signature',[])
        if len(signatures)!=1:return web.Response(status=401,text='invalid signature')
        if request.content_length is not None and request.content_length>MAX_BODY:
            return web.Response(status=413,text='payload too large')
        try:
            body=await asyncio.wait_for(request.read(),timeout=5)
            authority=snapshot(native.policy(),native.connector,destination)
            capture(adapter,body,signatures[0],authority)
        except web.HTTPRequestEntityTooLarge:
            return web.Response(status=413,text='payload too large')
        except (asyncio.TimeoutError,UnicodeError,json.JSONDecodeError,ValueError,TypeError):
            return web.Response(status=400,text='invalid request')
        except PermissionError:
            return web.Response(status=401,text='request not authorized')
        except Exception:
            # Never disclose message text, signatures, private paths or database
            # errors. A non-2xx leaves remote redelivery possible after recovery.
            return web.Response(status=503,text='admission unavailable')
        return web.Response(status=200,text='ok')

    app=web.Application(client_max_size=MAX_BODY)
    app.router.add_post('/line/webhook',receive)
    if hasattr(adapter,'_haos_line_output'):
        app.router.add_get('/line/output/{token}',adapter._haos_line_output.receive)
    return app
