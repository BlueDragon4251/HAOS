"""Actual native LINE content client behind a bounded fixed-endpoint capability."""
from contextlib import asynccontextmanager
import re

from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES
from .gateway_retry import retry_after

_URL='https://api-data.line.me/v2/bot/message/{message_id}/content'


class Refused(ValueError):
    def __init__(self,status,delay=0):
        super().__init__('LINE media content unavailable; inspect account, expiry, size and connection')
        self.status=status;self.delay=delay


class Content:
    def __init__(self,token,redactor):
        self.token=token;self.redactor=redactor;self.client=None;self.active=None
        self._target=None  # Fixture-only loopback substitution, never an owner field.

    @asynccontextmanager
    async def session(self,timeout):
        if self.active is None or timeout!=30.0:raise PermissionError('no native LINE content capability')
        yield self

    @asynccontextmanager
    async def get(self,url,*,headers):
        import aiohttp
        route=self.active
        if route is None or url!=_URL.format(message_id=route['id']) or headers!={'Authorization':'Bearer '+self.token}:
            raise PermissionError('native LINE content endpoint or credentials changed')
        route['current']()
        if self.client is None:
            self.client=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=30))
            self.client._retry_connection=False
        async with self.client.get(self._target.format(message_id=route['id']) if self._target else url,
                headers={**headers,'Accept-Encoding':'identity'},allow_redirects=False,auto_decompress=False) as response:
            if response.status!=200:
                raise Refused(response.status,retry_after(response.headers.get('Retry-After'),private_values=self.redactor.secrets) if response.status==429 else 0)
            limit=MAX_IMAGE_BYTES if route['kind']=='image' else MAX_BYTES
            if response.headers.get('Content-Encoding','identity').strip().lower()!='identity':raise Refused(415)
            if response.content_length is not None and response.content_length>limit:raise Refused(413)
            class Safe:
                status=200
                async def read(_self):
                    body=bytearray()
                    async for block in response.content.iter_chunked(16384):
                        route['current']();body.extend(block)
                        if len(body)>limit:raise Refused(413)
                    route['current']()
                    if not body:raise Refused(404)
                    if any(secret.encode('utf-8') in body for secret in self.redactor.secrets):raise PermissionError('private credential reflection refused')
                    return bytes(body)
            yield Safe()

    async def fetch(self,message_id,kind,current):
        if (not isinstance(message_id,str) or not re.fullmatch(r'[1-9][0-9]{0,31}',message_id)
                or not isinstance(kind,str) or kind not in {'image','document'} or not callable(current)):
            raise ValueError('exact retained LINE message and media kind required')
        if self.active is not None:raise PermissionError('native LINE content request already active')
        from plugins.platforms.line.adapter import _LineClient
        current();self.active={'id':message_id,'kind':kind,'current':current}
        native=_LineClient(self.token);native._session=self.session
        try:return await native.fetch_content(message_id)
        finally:self.active=None

    async def close(self):
        if self.client is not None:await self.client.close();self.client=None
