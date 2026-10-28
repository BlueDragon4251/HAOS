"""Exact private IMAP fetch metadata; mail Date headers never establish grant time."""
from datetime import datetime,timedelta,timezone
import re

from .gateway_email_codec import MAX_HEADERS,MAX_RAW

_MONTHS={name:index+1 for index,name in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}


def uid_number(value):
    if type(value) is not int or not 0<value<2**32:raise ValueError('exact bounded IMAP UID required')
    return value


def internal_date(value):
    match=re.fullmatch(r'([ 0-9][0-9])-([A-Z][a-z]{2})-([0-9]{4}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) ([+-])([0-9]{2})([0-9]{2})',value,flags=re.IGNORECASE)
    if not match:raise ValueError('exact authenticated IMAP INTERNALDATE required')
    day,month,year,hour,minute,second,sign,zone_hour,zone_minute=match.groups()
    try:
        if int(zone_minute)>59 or int(zone_hour)>23:raise ValueError
        offset=timedelta(hours=int(zone_hour),minutes=int(zone_minute))*(1 if sign=='+' else -1)
        created=datetime(int(year),_MONTHS[month.title()],int(day),int(hour),int(minute),int(second),tzinfo=timezone(offset))
        stamp=created.timestamp()
        if stamp<=0:raise ValueError
    except (KeyError,ValueError,OverflowError):raise ValueError('valid bounded authenticated IMAP creation time required') from None
    return stamp


def fetched(data,uid,*,section='HEADER'):
    uid_number(uid)
    if section not in {'HEADER',''}:raise ValueError('closed private mail body section required')
    if (not isinstance(data,list) or len(data)!=2 or not isinstance(data[0],tuple) or len(data[0])!=2
            or data[1]!=b')' or not all(isinstance(part,bytes) for part in data[0])):
        raise ValueError('one exact complete private IMAP literal required')
    prefix,content=data[0]
    if not 1<=len(prefix)<=MAX_HEADERS or not 1<=len(content)<=(MAX_HEADERS if section else MAX_RAW):
        raise ValueError('bounded private mail fetch required')
    try:text=prefix.decode('ascii')
    except UnicodeError:raise ValueError('ASCII mail resource metadata required') from None
    sources=re.findall(r'(?:^|[ (])UID ([0-9]+)(?=[ )])',text)
    sizes=re.findall(r'(?:^|[ (])RFC822.SIZE ([0-9]+)(?=[ )])',text)
    dates=re.findall(r'(?:^|[ (])INTERNALDATE "([^"]*)"',text)
    literal=re.search(r'BODY\['+section+r'\] \{([0-9]+)\}$',text)
    if (len(sources)!=1 or len(sizes)!=1 or len(dates)!=1 or len(sources[0])>10 or int(sources[0])!=uid
            or len(sizes[0])>10 or not len(content)<=int(sizes[0])<=MAX_RAW
            or literal is None or len(literal[1])>10 or int(literal[1])!=len(content)):
        raise ValueError('private mail UID, size or literal differs from requested resource')
    return {'uid':uid,'internal_at':internal_date(dates[0]),'size':int(sizes[0]),'content':content}


class MailboxChanged(ValueError):
    pass


def get_headers(transport,uid,validity):
    """Fetch bounded metadata/header bytes without changing remote read flags."""
    uid_number(uid);uid_number(validity)
    with transport.imap() as connection:
        transport.check()
        actual_validity=transport.number(connection,'UIDVALIDITY');next_uid=transport.number(connection,'UIDNEXT')
        if actual_validity!=validity or uid>=next_uid:raise MailboxChanged('mailbox UID state changed before header fetch')
        status,data=connection.uid('FETCH',str(uid),'(UID INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER])')
        transport.check()
        if status!='OK':raise ConnectionError('authenticated mailbox header resource unavailable')
        return {**fetched(data,uid),'uid_validity':actual_validity,'uid_next':next_uid}


def search(transport,page,since):
    """One bounded UID range, filtered by server received date, never mail Date."""
    if (not isinstance(page,dict) or set(page)!={'uid_validity','after','through'}
            or type(page['after']) is not int or type(page['through']) is not int
            or not 0<=page['after']<page['through']<2**32 or page['through']-page['after']>100000
            or type(since) is not int or not 0<since<2**53):
        raise ValueError('exact bounded mail search page and owner grant time required')
    uid_number(page['uid_validity'])
    # SINCE compares server INTERNALDATE calendar days. Include the previous UTC
    # day so a receiving server's local offset cannot omit a newly granted mail.
    try:day=datetime.fromtimestamp(since/1000,timezone.utc).date()-timedelta(days=1)
    except (ValueError,OverflowError,OSError):raise ValueError('representable email grant time required') from None
    months=tuple(_MONTHS);date=str(day.day)+'-'+months[day.month-1]+'-'+str(day.year)
    with transport.imap() as connection:
        validity=transport.number(connection,'UIDVALIDITY');next_uid=transport.number(connection,'UIDNEXT')
        if validity!=page['uid_validity'] or page['through']>=next_uid:raise MailboxChanged('mailbox state changed before UID search')
        transport.check()
        status,data=connection.uid('SEARCH',None,'UID',str(page['after']+1)+':'+str(page['through']),'SINCE',date)
        transport.check()
        if status!='OK' or not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],bytes) or len(data[0])>MAX_HEADERS:
            raise ValueError('one bounded complete mail UID search response required')
        parts=data[0].split()
        if len(parts)>1000 or any(not re.fullmatch(rb'[1-9][0-9]{0,9}',part) for part in parts):
            raise ValueError('bounded canonical mail search UID list required')
        uids=[int(part) for part in parts]
        if len(set(uids))!=len(uids) or any(not page['after']<uid<=page['through'] for uid in uids):
            raise ValueError('mail search returned duplicate or out-of-range UID resources')
        return {'uid_validity':validity,'uid_next':next_uid,'after':page['after'],'through':page['through'],'uids':sorted(uids)}


def message(transport,uid,validity,header_sha256,policy,connector,value,route):
    """Retrieve one immutable full resource only after independent header approval."""
    from .gateway import digest,Conflict
    from .gateway_email_admission import approve
    import hashlib
    uid_number(uid);uid_number(validity)
    if (not isinstance(header_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',header_sha256)
            or not isinstance(route,dict) or set(route)!={'binding_id','binding_digest'}):
        raise ValueError('exact current email header and binding proof required')
    with transport.imap() as connection:
        actual_validity=transport.number(connection,'UIDVALIDITY');next_uid=transport.number(connection,'UIDNEXT')
        if actual_validity!=validity or uid>=next_uid:raise MailboxChanged('mailbox changed before full email admission')
        transport.check()
        status,data=connection.uid('FETCH',str(uid),'(UID INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER])')
        if status!='OK':raise ConnectionError('email header resource unavailable')
        metadata=fetched(data,uid)
        if hashlib.sha256(metadata['content']).hexdigest()!=header_sha256:raise Conflict('email headers changed since current source approval')
        approval=approve(policy(),connector,value,metadata)
        if approval['binding_id']!=route['binding_id'] or approval['binding_digest']!=route['binding_digest']:
            raise PermissionError('email recipient or owner binding changed before body fetch')
        policy().current_binding(route);transport.check();connection._haos_literal_limit=MAX_RAW
        status,data=connection.uid('FETCH',str(uid),'(UID INTERNALDATE RFC822.SIZE BODY.PEEK[])')
        if status!='OK':raise ConnectionError('approved email body resource unavailable')
        complete=fetched(data,uid,section='')
        if complete['size']!=len(complete['content']) or any(complete[key]!=metadata[key] for key in ('uid','internal_at','size')):
            raise Conflict('email full resource size or creation metadata changed')
        boundary=complete['content'].find(b'\r\n\r\n')
        if not 0<boundary<=MAX_HEADERS or hashlib.sha256(complete['content'][:boundary+4]).hexdigest()!=header_sha256:
            raise Conflict('email body resource changed its approved headers')
        policy().current_binding(route);transport.check()
        return {**complete,'uid_validity':validity,'uid_next':next_uid,'approval':approval,
            'sha256':hashlib.sha256(complete['content']).hexdigest()}
