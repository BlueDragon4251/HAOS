"""Bounded private Twilio catch-up; provider reads never grant sender authority."""
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
import base64
import hashlib
import hmac
import re
import time
from urllib.parse import parse_qsl,urlencode,urlsplit

from .gateway import digest
from .gateway_sms import envelope,validate_binding,MESSAGE


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
    db=adapter._haos_native.inbox.db;connector=adapter._haos_native.connector
    db.execute('CREATE TABLE IF NOT EXISTS sms_recovery_status (connector TEXT PRIMARY KEY,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)')
    try:
        await _recover(adapter)
    except BaseException:
        db.execute('INSERT OR REPLACE INTO sms_recovery_status VALUES(?,?,?,?)',
            (connector,'backfill-unavailable',time.time(),time.time()+30))
        raise
    else:
        db.execute('INSERT OR REPLACE INTO sms_recovery_status VALUES(?,?,?,?)',
            (connector,'backfill-ready',time.time(),time.time()+30))


async def _recover(adapter):
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
            if (values['AccountSid']!=value['account_sid'] or values['From']!=binding['sender']
                    or values['To']!=value['from_number'] or not isinstance(values['MessageSid'],str)
                    or not MESSAGE.fullmatch(values['MessageSid']) or not isinstance(values['Body'],str)
                    or not isinstance(values['NumMedia'],str) or not re.fullmatch(r'(?:[0-9]|10)',values['NumMedia'])):
                raise PermissionError('authenticated recovery resource changed exact source')
            try:source=envelope(values,value)
            except ValueError:
                # An authenticated but unsupported message must not starve later
                # supported messages. Keep a bounded refusal receipt, never a
                # truncated text fallback or an implied mission admission.
                await adapter._haos_sms_rest.message(values,binding,current)
                db.execute('CREATE TABLE IF NOT EXISTS sms_recovery_rejections (identity TEXT PRIMARY KEY,message_sid TEXT NOT NULL,binding_digest TEXT NOT NULL,reason TEXT NOT NULL,created_at REAL NOT NULL)')
                refused=digest([identity,values['MessageSid']])
                if not db.execute('SELECT 1 FROM sms_recovery_rejections WHERE identity=?',(refused,)).fetchone():
                    if db.execute('SELECT COUNT(*) FROM sms_recovery_rejections').fetchone()[0]>=1024:
                        raise PermissionError('bounded SMS recovery refusal inventory is full')
                    db.execute('INSERT INTO sms_recovery_rejections VALUES(?,?,?,?,?)',
                        (refused,values['MessageSid'],digest(binding),'unsupported-content',time.time()))
                continue

            if source['sender']!=binding['sender']:raise PermissionError('provider recovery changed exact sender filter')
            # Local decoder adaptation is explicitly recorded. The original
            # evidence is the authenticated REST resource, never a remote HMAC.
            material=value['tls']['public_url']+''.join(k+values[k] for k in sorted(values))
            signature=base64.b64encode(hmac.new(value['auth_token'].encode(),material.encode(),hashlib.sha1).digest()).decode()
            from .gateway_sms_ingress import _capture
            await _capture(adapter,urlencode(values).encode(),signature,origin='authenticated-api-recovery')
        current()
        db.execute('INSERT OR REPLACE INTO sms_recovery_pages VALUES (?,?)',(identity,following))
