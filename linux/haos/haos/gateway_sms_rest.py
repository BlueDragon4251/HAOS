"""Fixed verified Twilio account/message reads, never an arbitrary HTTP client."""
from email.utils import parsedate_to_datetime
import json
import re
from urllib.parse import quote
import time

from .gateway_retry import retry_after
from .gateway_sms import MESSAGE

BASE='https://api.twilio.com/2010-04-01/Accounts/'


class Refused(ValueError):
    def __init__(self,status,delay=0):
        super().__init__('Twilio lookup unavailable; inspect account, number and retained wait period')
        self.status=status;self.delay=delay


class Rest:
    def __init__(self,value,redactor):
        self.value=value;self.redactor=redactor;self.client=None;self._fixture_origin=None

    async def get(self,path,current):
        import aiohttp
        sid=self.value['account_sid'];prefix=BASE+sid
        allowed=path in {'.json','/IncomingPhoneNumbers.json?PhoneNumber='+quote(self.value['from_number'],safe='')}
        if not allowed and not re.fullmatch(r'/Messages/(?:SM|MM)[0-9a-fA-F]{32}\.json',path):
            raise PermissionError('fixed private Twilio resource required')
        current()
        if self.client is None:
            self.client=aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),timeout=aiohttp.ClientTimeout(total=10));self.client._retry_connection=False
        # Actual pinned adapter's native Basic-auth codec; keys stay private.
        from plugins.platforms.sms.adapter import _basic_auth
        auth=_basic_auth(sid,self.value['auth_token'])
        url=(self._fixture_origin+sid if self._fixture_origin else prefix)+path
        async with self.client.get(url,headers={'Authorization':auth,'Accept-Encoding':'identity'},
                allow_redirects=False,auto_decompress=False) as response:
            if response.status!=200:
                raise Refused(response.status,retry_after(response.headers.get('Retry-After'),private_values=self.redactor.secrets) if response.status==429 else 0)
            if response.headers.get('Content-Encoding','identity').lower()!='identity':raise Refused(415)
            raw=bytearray()
            async for block in response.content.iter_chunked(4096):
                current();raw.extend(block)
                if len(raw)>65536:raise Refused(413)
            current()
            from .gateway_line_ingress import _object
            try:proof=json.loads(raw,object_pairs_hook=_object)
            except (ValueError,UnicodeError):raise Refused(502) from None
            if not isinstance(proof,dict):raise Refused(502)
            return proof

    async def verify(self,current):
        sid=self.value['account_sid'];number=self.value['from_number']
        account=await self.get('.json',current)
        if account.get('sid')!=sid or account.get('status')!='active':raise PermissionError('active exact Twilio account required')
        phones=await self.get('/IncomingPhoneNumbers.json?PhoneNumber='+quote(number,safe=''),current)
        rows=phones.get('incoming_phone_numbers')
        if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict)
                or rows[0].get('account_sid')!=sid or rows[0].get('phone_number')!=number
                or not isinstance(rows[0].get('capabilities'),dict) or rows[0]['capabilities'].get('sms') is not True):
            raise PermissionError('exact owned SMS-capable Twilio phone number required')
        return {'sms':True,'mms':rows[0]['capabilities'].get('mms') is True}

    async def message(self,values,binding,current):
        sid=values['MessageSid']
        if not isinstance(sid,str) or not MESSAGE.fullmatch(sid):raise ValueError('exact message SID required')
        proof=await self.get('/Messages/'+sid+'.json',current)
        if proof.get('status')=='receiving':raise Refused(503)
        if (proof.get('sid')!=sid or proof.get('account_sid')!=self.value['account_sid']
                or proof.get('from')!=values['From'] or proof.get('to')!=values['To']
                or proof.get('body')!=values['Body'] or proof.get('direction')!='inbound'
                or proof.get('status')!='received' or str(proof.get('num_media','0'))!='0'):
            raise PermissionError('SMS webhook differs from its authenticated provider message resource')
        try:
            created=parsedate_to_datetime(proof['date_created'])
            if created.tzinfo is None:raise ValueError
            stamp=created.timestamp()
        except (ValueError,TypeError,KeyError,OverflowError):raise PermissionError('authenticated SMS creation timestamp required') from None
        if not binding['since']<stamp*1000 or stamp>time.time()+300:
            raise PermissionError('SMS was not created after this exact owner grant')
        return stamp

    async def close(self):
        if self.client is not None:await self.client.close();self.client=None
