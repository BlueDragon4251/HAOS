"""Bounded native email decoding after exact receiving-server authentication checks."""
from email import policy
from email.message import EmailMessage
from email.parser import BytesHeaderParser
import hashlib
import re

from .gateway_email import address,hostname,message_id

MAX_RAW=48*1024*1024
MAX_HEADERS=65536


def headers(raw,value):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_RAW:raise ValueError('bounded RFC822 source required')
    end=raw.find(b'\r\n\r\n')
    if not 0<end<=MAX_HEADERS:raise ValueError('bounded complete CRLF mail headers required')
    header=BytesHeaderParser(policy=policy.default).parsebytes(raw[:end+4])
    if header.defects or len(header.items())>256:raise ValueError('well-formed bounded mail headers required')
    sources=header.get_all('From',[]);ids=header.get_all('Message-ID',[])
    if (len(sources)!=1 or len(ids)!=1 or sources[0].defects or ids[0].defects
            or len(sources[0].addresses)!=1 or not message_id(str(ids[0]))):
        raise ValueError('one exact From mailbox and Message-ID required')
    sender=address(sources[0].addresses[0].addr_spec.lower())
    results=header.get_all('Authentication-Results',[])
    if not results or len(results)>16:raise PermissionError('receiving-server authentication result required')
    first=' '.join(str(results[0]).split())
    service=first.split(';',1)[0].strip().lower()
    try:hostname(service)
    except ValueError:raise PermissionError('exact receiving authentication service required') from None
    if service!=value['authserv_id']:raise PermissionError('first authentication result is not from configured receiving service')
    # The pinned helper permits suffix-aligned authserv IDs and later matching
    # headers. HAOS independently requires the first exact ID, then gives the
    # actual helper only that header; injected later results cannot gain trust.
    from plugins.platforms.email.adapter import _verify_sender_authentication
    isolated=EmailMessage();isolated['From']=str(sources[0]);isolated['Authentication-Results']=first
    accepted,_reason=_verify_sender_authentication(isolated,sender,authserv_id=value['authserv_id'])
    if accepted is not True:raise PermissionError('receiving server did not authenticate the sender domain')
    return {'sender':sender,'message_id':str(ids[0]),'headers':header}


def decode(adapter,raw,value,uid):
    checked=headers(raw,value)
    if (not isinstance(uid,bytes) or not re.fullmatch(rb'[1-9][0-9]{0,9}',uid) or int(uid)>=2**32
            or adapter._skip_attachments is not True or adapter._require_authenticated_sender is not True
            or adapter._authserv_id!=value['authserv_id'] or adapter._address!=value['address']):
        raise PermissionError('bounded UID and isolated authenticated native email codec required')
    result=adapter._parse_fetched_message(uid,raw)
    if result is None:return None  # Native automated-mail refusal is preserved.
    if (result['sender_addr']!=checked['sender'] or result['message_id']!=checked['message_id']
            or result.get('sender_authenticated') is not True or result.get('attachments')!=[]
            or len(result['body'])>50000 or len(result['subject'])>1024
            or any(c in result['subject'] for c in '\r\n\0')):
        raise ValueError('native email source, authentication or bounded text changed')
    return {**result,'raw_sha256':hashlib.sha256(raw).hexdigest()}
