"""Independent timed sender/mailbox/thread approval before any full mail fetch."""
import hashlib
import re
import time

from .gateway import GatewayPolicy,digest
from .gateway_email import scope,message_id,validate_binding
from .gateway_email_codec import headers


class Refused(PermissionError):
    def __init__(self,reason):
        super().__init__('email source is not approved for full-message admission')
        self.reason=reason


def thread(header):
    values={}
    for field in ['References','In-Reply-To']:
        parts=header.get_all(field,[])
        if len(parts)>1:raise Refused('unsupported-content')
        text=str(parts[0]) if parts else ''
        if len(text)>8192:raise Refused('unsupported-content')
        ids=re.findall(r'<[^<>]+>',text)
        if (len(ids)>32 or any(not message_id(identity) for identity in ids)
                or re.sub(r'<[^<>]+>','',text).strip()):
            raise Refused('unsupported-content')
        values[field]=ids
    if len(values['In-Reply-To'])>1:raise Refused('unsupported-content')
    return (values['References'] or values['In-Reply-To'] or [''])[0]


def approve(policy,connector,value,resource):
    if not isinstance(policy,GatewayPolicy) or policy.connectors.get(connector,{}).get('platform')!='email':
        raise Refused('unapproved-sender')
    try:checked=headers(resource['content'],value)
    except PermissionError:raise Refused('authentication-refused') from None
    except (ValueError,KeyError):raise Refused('unsupported-content') from None
    source=checked['headers'];sender=checked['sender']
    from plugins.platforms.email.adapter import _is_automated_sender
    automated={name:source.get(name,'') for name in ['Auto-Submitted','Precedence','X-Auto-Response-Suppress','List-Unsubscribe']}
    if sender==value['address'] or _is_automated_sender(sender,automated):raise Refused('self-or-automated')
    root=thread(source);mailbox=scope(value)
    source_id=digest([mailbox,sender,checked['message_id']])
    envelope={'platform':'email','sender':sender,'chat':sender,'scope':mailbox,'thread':root,
        'message_id':source_id,'is_bot':False,'text':''}
    try:binding=policy.authorize(connector,envelope)
    except PermissionError:
        known=any(row['connector']==connector and row['sender']==sender and row['scope']==mailbox for row in policy.bindings.values())
        raise Refused('unapproved-thread' if known else 'unapproved-sender') from None
    validate_binding(binding)
    stamp=resource.get('internal_at')
    if type(stamp) not in {int,float} or not binding['since']<stamp*1000 or not 0<stamp<=time.time()+300:
        raise Refused('pre-grant')
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    return {'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),
        'received_at':stamp,'header_sha256':hashlib.sha256(resource['content'][:resource['content'].find(b'\r\n\r\n')+4]).hexdigest(),
        'rfc_message_id':checked['message_id']}
