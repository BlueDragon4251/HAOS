"""Finite Google HTTP Retry-After and actual gRPC RetryInfo delays."""
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import math


def retry_after(error,default=60):
    delay=default;response=getattr(error,'resp',None)
    if hasattr(response,'get'):
        raw=response.get('retry-after')
        if isinstance(raw,str) and len(raw)<=128:
            if raw.isascii() and raw.isdecimal() and len(raw)<=9:delay=max(delay,int(raw))
            else:
                try:
                    date=parsedate_to_datetime(raw)
                    if date.tzinfo is not None:delay=max(delay,math.ceil((date-datetime.now(timezone.utc)).total_seconds()))
                except (ValueError,TypeError,OverflowError):pass
    details=getattr(error,'details',())
    if isinstance(details,(list,tuple)):
        for part in details[:16]:
            if type(part).__module__=='google.rpc.error_details_pb2' and type(part).__name__=='RetryInfo':
                duration=part.retry_delay
                if 0<=duration.seconds<=86400 and 0<=duration.nanos<10**9:
                    delay=max(delay,duration.seconds+(1 if duration.nanos else 0))
    return min(86400,max(1,int(delay)))
