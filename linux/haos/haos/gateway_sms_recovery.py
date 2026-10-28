"""Bounded private Twilio catch-up; provider reads never grant sender authority."""
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
import base64
import hashlib
import hmac
import re
from urllib.parse import parse_qsl,urlencode,urlsplit

from .gateway import digest
from .gateway_sms import envelope,validate_binding


def query(value,binding,continuation=None):
    validate_binding(binding,require_epoch=True)
    day=datetime.fromtimestamp(binding['since']/1000,timezone.utc).date()-timedelta(days=1)
    fixed={'From':binding['sender'],'To':value['from_number'],'DateSent>':str(day),'PageSize':'10'}
    if continuation is not None:
        if not isinstance(continuation,str) or len(continuation)>4096:raise PermissionError('bounded recovery page required')
        target=urlsplit(continuation)
        if (target.scheme or target.netloc or target.fragment or target.path!='/2010-04-01/Accounts/'+value['account_sid']+'/Messages.json'):
            raise PermissionError('recovery pagination escaped exact account resource')
        pairs=parse_qsl(target.query,keep_blank_values=True,strict_parsing=True)
        fields=dict(pairs)
        if (len(fields)!=len(pairs) or any(fields.get(k)!=v for k,v in fixed.items())
                or set(fields)-set(fixed)-{'Page','PageToken'}
                or not fields.get('PageToken') or len(fields['PageToken'])>2048
                or 'Page' in fields and (not fields['Page'].isascii() or not fields['Page'].isdigit() or len(fields['Page'])>10)):
            raise PermissionError('recovery pagination changed filters or token')
        fixed=fields
    return '/Messages.json?'+urlencode(fixed)


def list_path(path,value):
    """REST whitelist, independent of owner/user-supplied URLs."""
    if not isinstance(path,str) or not path.startswith('/Messages.json?') or len(path)>8192:return False
    try:
        pairs=parse_qsl(path.split('?',1)[1],keep_blank_values=True,strict_parsing=True);fields=dict(pairs)
        return (len(pairs)==len(fields) and set(fields) in ({'From','To','DateSent>','PageSize'},
            {'From','To','DateSent>','PageSize','PageToken'},{'From','To','DateSent>','PageSize','PageToken','Page'})
            and fields['To']==value['from_number'] and fields['PageSize']=='10'
            and re.fullmatch(r'\+[1-9][0-9]{7,14}',fields['From']) is not None
            and str(datetime.strptime(fields['DateSent>'],'%Y-%m-%d').date())==fields['DateSent>']
            and ('PageToken' not in fields or 0<len(fields['PageToken'])<=2048)
            and ('Page' not in fields or fields['Page'].isascii() and fields['Page'].isdigit() and len(fields['Page'])<=10))
    except (ValueError,KeyError,TypeError):return False


async def recover(adapter):
    """One persisted page per grant per sweep. Advance only after durable admission."""
    native=adapter._haos_native;db=native.inbox.db;value=adapter._haos_sms_value
    db.execute('CREATE TABLE IF NOT EXISTS sms_recovery_pages (identity TEXT PRIMARY KEY, continuation TEXT)')
    policy=native.policy()
    for binding in policy.bindings.values():
        if binding['connector']!=native.connector:continue
        identity=digest([native.connector,binding]);row=db.execute('SELECT continuation FROM sms_recovery_pages WHERE identity=?',(identity,)).fetchone()
        path=query(value,binding,row['continuation'] if row else None)
        def current():
            adapter._haos_sms_check()
            native.policy().current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        current();page=await adapter._haos_sms_rest.get(path,current)
        messages=page.get('messages');following=page.get('next_page_uri')
        if not isinstance(messages,list) or len(messages)>10:raise ValueError('bounded Twilio recovery page required')
        if following is not None:query(value,binding,following)  # Never follow a provider-supplied URL.
        for item in messages:
            current()
            if not isinstance(item,dict):raise ValueError('exact recovery resource required')
            if item.get('direction')!='inbound' or item.get('status')!='received':continue
            try:
                created=parsedate_to_datetime(item['date_created'])
                if created.tzinfo is None:raise ValueError
            except (KeyError,ValueError,TypeError):raise ValueError('authenticated recovery timestamp required') from None
            if created.timestamp()*1000<=binding['since']:continue
            values={'AccountSid':item.get('account_sid'),'MessageSid':item.get('sid'),'From':item.get('from'),
                'To':item.get('to'),'Body':item.get('body'),'NumMedia':item.get('num_media')}
            source=envelope(values,value)
            if source['sender']!=binding['sender']:raise PermissionError('provider recovery changed exact sender filter')
            # Local decoder adaptation is explicitly recorded. The original
            # evidence is the authenticated REST resource, never a remote HMAC.
            material=value['tls']['public_url']+''.join(k+values[k] for k in sorted(values))
            signature=base64.b64encode(hmac.new(value['auth_token'].encode(),material.encode(),hashlib.sha1).digest()).decode()
            from .gateway_sms_ingress import _capture
            await _capture(adapter,urlencode(values).encode(),signature,origin='authenticated-api-recovery')
        current()
        db.execute('INSERT OR REPLACE INTO sms_recovery_pages VALUES (?,?)',(identity,following))
