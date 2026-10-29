"""Independent approval of authenticated DingTalk bytes before native I/O."""
from copy import deepcopy
import hashlib
import json
import math
import time
from urllib.parse import urlsplit,parse_qsl

from .gateway import GatewayPolicy,digest
from .gateway_dingtalk import credentials,scope,identity,validate_binding
from .gateway_line_ingress import _object

MAX_EVENT=1024*1024
TYPES=frozenset({'text','picture','richText','audio','file','image','card','interactiveCard'})


class Refused(PermissionError):
    def __init__(self,reason,retry_after=0):
        if type(retry_after) is not int or not 0<=retry_after<=86400:raise ValueError('bounded private source retry delay required')
        super().__init__('DingTalk source or content is not approved');self.reason=reason;self.retry_after=retry_after


def finite(_value):raise ValueError('finite DingTalk JSON required')


def parse(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_EVENT:raise Refused('unsupported-content')
    try:data=json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
    except (ValueError,UnicodeError,RecursionError):raise Refused('unsupported-content') from None
    if not isinstance(data,dict):raise Refused('unsupported-content')
    pending=[(data,0)];count=0
    while pending:
        value,depth=pending.pop();count+=1
        if count>16384 or depth>16:raise Refused('unsupported-content')
        if isinstance(value,dict):pending.extend((part,depth+1) for part in [*value.keys(),*value.values()])
        elif isinstance(value,list):pending.extend((part,depth+1) for part in value)
        elif isinstance(value,str):
            try:value.encode('utf-8')
            except UnicodeError:raise Refused('unsupported-content') from None
        elif type(value) is float and not math.isfinite(value):raise Refused('unsupported-content')
        elif type(value) not in {int,float,bool,type(None)}:raise Refused('unsupported-content')
    return data


def milliseconds(value):
    if isinstance(value,str) and value.isascii() and value.isdecimal() and 1<=len(value)<=16 and not value.startswith('0'):value=int(value)
    if type(value) is not int or not 0<value<2**53:raise Refused('invalid-time')
    return value


def session_webhook(url):
    if not isinstance(url,str) or not 1<=len(url)<=16384 or any(not 33<=ord(char)<=126 for char in url):raise Refused('invalid-reply-route')
    try:
        parsed=urlsplit(url);query=parse_qsl(parsed.query,keep_blank_values=True,strict_parsing=True)
        if (parsed.scheme!='https' or parsed.hostname not in {'oapi.dingtalk.com','api.dingtalk.com'}
                or parsed.port not in {None,443} or parsed.username or parsed.password or parsed.fragment
                or parsed.path not in {'/robot/sendBySession','/robot/send'} or len(query)!=1
                or query[0][0]!=('session' if parsed.path=='/robot/sendBySession' else 'access_token')
                or not 16<=len(query[0][1])<=8192 or any(not 33<=ord(char)<=126 for char in query[0][1])):
            raise ValueError
    except (ValueError,UnicodeError):raise Refused('invalid-reply-route') from None
    return url,query[0][1]


def approve(policy,connector,value,raw):
    if not isinstance(policy,GatewayPolicy) or policy.connectors.get(connector,{}).get('platform')!='dingtalk':raise Refused('unapproved-route')
    value=credentials(value);data=parse(raw)
    try:
        if data.get('robotCode')!=value['robot_code'] or data.get('chatbotCorpId')!=value['corp_id'] or data.get('senderCorpId')!=value['corp_id']:
            raise Refused('wrong-account')
        sender=identity(data.get('senderId'));chat=identity(data.get('conversationId'));message=identity(data.get('msgId'))
        if sender==value['robot_code'] or data.get('senderIsRobot',False) is not False:raise Refused('self-or-automated')
        conversation=data.get('conversationType')
        if not (type(conversation) is int and conversation in {1,2} or isinstance(conversation,str) and conversation in {'1','2'}):raise Refused('unsupported-content')
        # Neither staff/display aliases, isAdmin nor quoted messages grant HAOS rights.
        if any(data.get(key) not in (None,'') for key in ['threadId','thread_id','topicId']):raise Refused('unsupported-thread')
        envelope={'platform':'dingtalk','sender':sender,'chat':chat,'scope':scope(value),'thread':'',
            'message_id':message,'is_bot':False,'text':''}
        try:binding=policy.authorize(connector,envelope)
        except PermissionError:raise Refused('unapproved-route') from None
        validate_binding(binding);stamp=milliseconds(data.get('createAt'))
        if not binding['since']<stamp<=time.time()*1000+300000:raise Refused('pre-grant')
        if str(data['conversationType'])=='2' and binding.get('require_mention',True) and data.get('isInAtList') is not True:raise Refused('mention-required')
        if not isinstance(data.get('msgtype'),str) or data['msgtype'] not in TYPES:raise Refused('unsupported-content')
        if data['msgtype']=='audio' and binding.get('allow_voice') is not True:raise Refused('unapproved-media')
        url=data.get('sessionWebhook','');expiry=data.get('sessionWebhookExpiredTime')
        if url:
            session_webhook(url);expiry=milliseconds(expiry)
            if expiry<stamp or expiry>time.time()*1000+86400000:raise Refused('invalid-reply-route')
        elif expiry not in (None,0):raise Refused('invalid-reply-route')
    except Refused:raise
    except (ValueError,KeyError,TypeError):raise Refused('unsupported-content') from None
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    return {'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),'received_at':stamp/1000,
        'raw_sha256':hashlib.sha256(raw).hexdigest(),'credential_scope':digest([connector,value])}


def native_data(data):
    """Canonicalize only native resolver aliases; retain immutable original bytes."""
    result=deepcopy(data)
    if result.get('msgtype')=='richText':
        content=result.get('content')
        items=content.get('richText') if isinstance(content,dict) else None
        if not isinstance(items,list):raise Refused('unsupported-content')
        for item in items:
            if not isinstance(item,dict):continue
            aliases=[item[key] for key in ['downloadCode','download_code','pictureDownloadCode'] if item.get(key)]
            if not aliases:continue
            if any(not isinstance(code,str) or code!=aliases[0] for code in aliases):raise Refused('ambiguous-resource')
            for key in ['download_code','pictureDownloadCode']:item.pop(key,None)
            item['downloadCode']=aliases[0]
    return result


def normalize(policy,connector,value,raw,approval,redactor):
    if approve(policy,connector,value,raw)!=approval:raise Refused('changed-approval')
    from .redaction import Redactor
    if not isinstance(redactor,Redactor):raise Refused('private-redaction-required')
    redactor.secrets=sorted(set([*redactor.secrets,credentials(value)['client_secret']]),key=len,reverse=True)
    data=parse(raw);url=data.get('sessionWebhook','')
    if url:
        _,token=session_webhook(url)
        # Registered only after authenticated bytes have an independent owner route.
        redactor.secrets=sorted(set([*redactor.secrets,url,token]),key=len,reverse=True)
    from dingtalk_stream import ChatbotMessage
    from plugins.platforms.dingtalk.inbound import extract_text,extract_media,collect_download_codes
    try:
        converted=native_data(data);native=ChatbotMessage.from_dict(converted)
        text=extract_text(native);kind,urls,mimes=extract_media(native)
        pairs=collect_download_codes(native)
        codes=[getattr(obj,key) if hasattr(obj,key) else obj[key] for obj,key in pairs]
        envelope=approval['envelope']
        if any(getattr(native,key,None)!=envelope[field] for key,field in [('sender_id','sender'),('conversation_id','chat'),('message_id','message_id')]):
            raise Refused('changed-native-source')
        if (not isinstance(text,str) or len(text)>32000 or not isinstance(urls,list) or len(urls)>4
                or len(urls)!=len(mimes) or any(not isinstance(code,str) or not 16<=len(code)<=8192 or '://' in code
                    or any(not 33<=ord(char)<=126 for char in code) for code in urls)
                or set(codes)!=set(urls)):
            raise Refused('unsupported-content')
        binding=policy.current_binding(approval);resources=[]
        for index,(code,mime) in enumerate(zip(urls,mimes)):
            raw_kinds={item.get('type') for item in converted.get('content',{}).get('richText',[]) if isinstance(item,dict) and item.get('downloadCode')==code} if converted.get('msgtype')=='richText' else set()
            if 'video' in raw_kinds and raw_kinds & {'voice','audio'}:raise Refused('ambiguous-resource')
            if mime=='audio' or raw_kinds & {'voice','audio'}:category='voice'
            elif 'video' in raw_kinds or mime in {'video','video/mp4'}:category='video'
            elif mime=='image' or mime.startswith('image/'):category='image'
            else:category='document'
            permission='allow_voice' if category=='voice' else 'allow_video' if category=='video' else 'allow_media'
            if binding.get(permission) is not True:raise Refused('unapproved-media')
            resources.append({'index':index,'code':code,'kind':category,'mime':mime})
        if not text and not resources:raise Refused('unsupported-content')
        # Platform download codes remain private SDK capabilities. Register
        # escaped spellings too before permitting the textual goal to leave.
        private=set(urls)
        for _ in range(2):
            private|={json.dumps(part,ensure_ascii=ascii)[1:-1] for part in tuple(private) for ascii in (True,False)}
            private|={repr(part)[1:-1] for part in tuple(private)}
        redactor.secrets=sorted(set([*redactor.secrets,*private]),key=len,reverse=True)
        if redactor.text(text)!=text:raise Refused('private-reflection')
    except Refused:raise
    except (ValueError,TypeError,AttributeError,KeyError,UnicodeError):raise Refused('unsupported-content') from None
    if approve(policy,connector,value,raw)!=approval:raise Refused('changed-approval')
    return {'envelope':{**envelope,'text':text or 'Inspect the approved attachment.'},'resources':resources,'native_kind':kind.value}
