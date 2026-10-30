"""Independent signed Buzz route admission before native cursors or credential use."""
import hashlib
import json
import math
import time

from .gateway import digest
from .gateway_buzz import HEX,scope
from .gateway_buzz_crypto import wire,verify


class Refused(PermissionError):
    def __init__(self,reason):
        if reason not in {'unapproved-route','unsupported-content','invalid-time','private-reflection','independent-media-consent-required','mention-required'}:
            raise ValueError('finite Buzz source refusal required')
        super().__init__('Buzz source refused; inspect its exact sender context and owner permission');self.reason=reason


def thread(event):
    marked={'root':set(),'reply':set()}
    for tag in event['tags']:
        if tag[0]!='e':continue
        if len(tag)<2 or not HEX.fullmatch(tag[1]):raise Refused('unsupported-content')
        marker=tag[3].lower() if len(tag)>3 else ''
        if marker in marked:marked[marker].add(tag[1])
    if any(len(values)>1 for values in marked.values()):raise Refused('unsupported-content')
    # Derive the actual legacy/marked NIP-10 behavior from the pinned adapter.
    from plugins.platforms.buzz.adapter import BuzzAdapter
    return BuzzAdapter._extract_thread_root(event) or ''


async def approve(policy,connector,value,raw,redactor,*,received_at=None,own_reply=None):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();event=wire(raw)
    if event['kind'] not in {9,45001,45003}:raise Refused('unsupported-content')
    channels=[tag[1] for tag in event['tags'] if tag[0]=='h' and len(tag)>=2]
    if len(channels)!=1 or channels[0] not in value['channels'] or event['pubkey']==value['public_key']:
        raise Refused('unapproved-route')
    selected_thread=thread(event)
    from plugins.platforms.buzz.adapter import BuzzAdapter,_find_relay_media_refs
    attachments,rejected=BuzzAdapter._parse_imeta_attachments(event)
    references,_=_find_relay_media_refs(event['content'],value['relay_url'])
    if rejected or len(attachments)+len(references)>4:raise Refused('unsupported-content')
    text=event['content'] or ('[Buzz attachment]' if attachments or references else '')
    if not text or redactor.text(text)!=text:raise Refused('private-reflection' if text else 'unsupported-content')
    envelope={'platform':'buzz','sender':event['pubkey'],'chat':channels[0],'scope':scope(value),'thread':selected_thread,
        'message_id':event['id'],'is_bot':False,'text':text}
    try:binding=policy.authorize(connector,envelope)
    except PermissionError:raise Refused('unapproved-route') from None
    received=time.time() if received_at is None else received_at
    if (type(received) not in {int,float} or not math.isfinite(received) or not 0<received<=time.time()+300
            or event['created_at']>received+300 or event['created_at']*1000<binding['since']):raise Refused('invalid-time')
    if binding.get('require_mention',True):
        addressed=any(len(tag)>=2 and tag[0]=='p' and tag[1]==value['public_key'] for tag in event['tags'])
        if not addressed and callable(own_reply):
            from plugins.platforms.buzz.adapter import _event_reply_parent_id
            parent=_event_reply_parent_id(event)
            addressed=bool(parent and own_reply(channels[0],parent) is True)
        if not addressed:raise Refused('mention-required')
    from .gateway_media import approved,MAX_BYTES
    resources=[]
    for index,item in enumerate(attachments):
        mime=item['mime_type'];kind='voice' if mime.startswith('audio/') else 'video' if mime.startswith('video/') else 'image' if mime.startswith('image/') else 'document'
        if item['size']>MAX_BYTES:raise Refused('unsupported-content')
        if not approved(binding,kind):raise Refused('independent-media-consent-required')
        resources.append({'index':index,'mode':'imeta','kind':kind,**item})
    for url in references:
        if not any(binding.get(key) is True for key in ['allow_media','allow_voice','allow_video']):raise Refused('independent-media-consent-required')
        resources.append({'index':len(resources),'mode':'relay-ref','url':url})
    checked=await verify(raw)
    if checked!=event:raise PermissionError('official Buzz verification changed the retained original')
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    canonical=json.dumps(event,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return {'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),'credential_scope':digest([connector,value]),
        'received_at':received,'raw_sha256':hashlib.sha256(canonical).hexdigest(),'resources':resources,
        'event_sha256':event['id'],'signature_sdk':'nostr-0.44.7'}
