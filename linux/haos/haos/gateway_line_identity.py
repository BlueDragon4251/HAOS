"""Bounded verified native LINE bot identity lookup before service admission."""
from contextlib import asynccontextmanager
import json

from .gateway_retry import retry_after

_URL='https://api.line.me/v2/bot/info'


class Identity:
    def __init__(self,token,destination):
        self.token=token;self.destination=destination;self._target=_URL;self.client=None;self.active=False
        self.status=None;self.delay=0

    @asynccontextmanager
    async def session(self,timeout):
        if not self.active or timeout!=10.0:raise PermissionError('no native LINE identity capability')
        yield self

    @asynccontextmanager
    async def get(self,url,*,headers):
        import aiohttp
        if not self.active or url!=_URL or headers!={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}:
            raise PermissionError('native LINE identity endpoint or credential changed')
        if self.client is None:
            self.client=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=10))
            self.client._retry_connection=False
        class Safe:
            status=502
            async def json(self):return self.proof
        safe=Safe();safe.proof={}
        async with self.client.get(self._target,headers=headers,allow_redirects=False) as response:
            self.status=response.status;self.delay=retry_after(response.headers.get('Retry-After'),private_values=[self.token])
            if response.status==200:
                body=bytearray()
                async for part in response.content.iter_chunked(4096):
                    body.extend(part)
                    if len(body)>65536:raise ValueError('bounded LINE identity response exceeded')
                from .gateway_line_ingress import _object
                proof=json.loads(body,object_pairs_hook=_object)
                if isinstance(proof,dict) and proof.get('userId')==self.destination:safe.proof={'userId':self.destination}
                else:safe.proof={'userId':None}
            safe.status=response.status
        yield safe

    async def verify(self):
        if self.active:raise PermissionError('native LINE identity lookup already active')
        from plugins.platforms.line.adapter import _LineClient
        native=_LineClient(self.token);native._session=self.session
        self.status=None;self.delay=0;self.active=True
        try:identity=await native.get_bot_user_id()
        finally:self.active=False
        if self.status in {401,403}:return 'authentication-refused',0
        if self.status==429:return 'rate-limited',self.delay
        if self.status==200:return ('verified',0) if identity==self.destination else ('identity-refused',0)
        return 'transport-unavailable',0

    async def close(self):
        if self.client is not None:await self.client.close();self.client=None
