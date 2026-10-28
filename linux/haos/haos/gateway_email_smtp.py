"""One exact native reply over verified SMTP; never a general mail capability."""
from copy import deepcopy
from email.utils import formatdate
import hashlib
import os
from pathlib import Path
import re
import smtplib
import stat
import time
from types import MethodType

from .gateway import digest
from .gateway_email import address,message_id,scope
from .gateway_email_transport import Transport
from .gateway_media import MAX_BYTES


def descriptors(values):
    from .gateway_outbound import EXTENSIONS
    if not isinstance(values,list) or len(values)>4:raise ValueError('at most four exact SMTP attachment snapshots required')
    identities=set()
    for index,item in enumerate(values):
        if (not isinstance(item,dict) or set(item)!={'id','sha256','size','name'}
                or any(not isinstance(item[key],str) or not re.fullmatch('[0-9a-f]{64}',item[key]) for key in ('id','sha256'))
                or type(item['size']) is not int or not 1<=item['size']<=MAX_BYTES
                or not isinstance(item['name'],str) or not re.fullmatch('result-'+str(index)+r'\.[a-z0-9]{1,16}',item['name'])
                or Path(item['name']).suffix not in EXTENSIONS or item['id'] in identities):
            raise ValueError('exact bounded path-free SMTP snapshot metadata required')
        identities.add(item['id'])
    return deepcopy(values)


class ReplyReader:
    def __init__(self,stream,current):self.stream=stream;self.current=current;self.reset()
    def reset(self):self.size=0;self.lines=0;self.code=None
    def readline(self,limit):
        self.current()
        if type(limit) is not int or not 1<=limit<=8193:raise ValueError('bounded native SMTP response read required')
        data=self.stream.readline(limit);self.current();self.size+=len(data);self.lines+=1
        if self.lines>128 or self.size>65536 or len(data)>8192:
            raise ValueError('bounded complete SMTP response required; outcome remains unknown')
        if data:
            if not re.fullmatch(rb'[1-5][0-9]{2}(?:[ -][^\r\n]*)?\r\n',data):raise ValueError('well-formed SMTP response required')
            code=int(data[:3])
            if self.code is not None and self.code!=code:raise ValueError('consistent SMTP multiline response required')
            self.code=code
        return data
    def close(self):self.stream.close()


def specification(value,policy,connector,item):
    fields={'binding_id','binding_digest','delivery_id','attempt','source_id','rfc_message_id',
        'root_message_id','subject','body','created_at','recipient','files'}
    if not isinstance(item,dict) or set(item)!=fields:raise ValueError('exact private native email reply required')
    for key in ('binding_digest','delivery_id','source_id'):
        if not isinstance(item[key],str) or not re.fullmatch('[0-9a-f]{64}',item[key]):raise ValueError('exact opaque email reply identity required')
    if type(item['attempt']) is not int or not 1<=item['attempt']<=5:raise ValueError('bounded email outbox attempt required')
    binding=policy.current_binding({key:item[key] for key in ('binding_id','binding_digest')})
    if (policy.connectors.get(connector,{}).get('platform')!='email' or binding['connector']!=connector
            or binding['chat']!=address(item['recipient']) or binding['scope']!=scope(value)
            or binding['thread']!=item['root_message_id'] or 'read' not in binding['capabilities']
            or item['recipient']==value['address']):raise PermissionError('exact current email reply/read grant required')
    if not message_id(item['rfc_message_id']) or item['root_message_id'] and not message_id(item['root_message_id']):
        raise ValueError('exact retained email reply references required')
    if (not isinstance(item['subject'],str) or len(item['subject'])>1024
            or any(c in item['subject'] for c in '\r\n\0')):raise ValueError('bounded native reply subject required')
    files=descriptors(item['files'])
    if files and binding.get('allow_outbound_media') is not True:raise PermissionError('separate current SMTP output-file approval required')
    if (not isinstance(item['body'],str) or len(item['body'])>32000 or not item['body'].strip() and not files
            or len(item['body'].encode())>128000 or '\0' in item['body']):raise ValueError('bounded native reply body required')
    if type(item['created_at']) is not int or not 0<item['created_at']<=int(time.time())+300:raise ValueError('fixed reply creation time required')
    import base64
    aliases=[value['password'],base64.b64encode(value['password'].encode()).decode(),
        base64.b64encode(('\0'+value['address']+'\0'+value['password']).encode()).decode()]
    if any(secret in item[field] for secret in aliases for field in ('subject','body')):
        raise PermissionError('private email credential reflection refused')
    return deepcopy(item)


def identity(value,item):
    domain=value['address'].rsplit('@',1)[1]
    if len(domain)>180:domain='haos.invalid'  # Keep our own exact Message-ID contract bounded.
    return '<haos-'+digest([item['delivery_id'],item['attempt'],item['binding_digest']])+'@'+domain+'>'


def build(adapter,value,item,paths=()):
    """Keep the actual pinned builder; give it only this retained reply context."""
    from plugins.platforms.email.adapter import EmailAdapter
    saved=adapter._thread_context
    adapter._thread_context={item['recipient']:{'subject':item['subject'],'message_id':item['rfc_message_id']}}
    try:msg,_native_id,_subject=EmailAdapter._new_reply(adapter,item['recipient'],item['body'],item['rfc_message_id'],attach_empty_body=True)
    finally:adapter._thread_context=saved
    msg.replace_header('Message-ID',identity(value,item))
    msg.replace_header('Date',formatdate(item['created_at'],usegmt=True))
    references=[item['rfc_message_id']]
    if item['root_message_id'] and item['root_message_id']!=references[0]:references.insert(0,item['root_message_id'])
    msg.replace_header('References',' '.join(references))
    if len(paths)!=len(item['files']):raise ValueError('every SMTP snapshot needs its private byte file')
    from plugins.platforms.email.adapter import _attach_file
    for path,meta in zip(paths,item['files']):
        path=Path(path);own=path.lstat()
        if (not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_nlink!=1
                or own.st_mode&0o077 or own.st_size!=meta['size'] or path.name!=meta['name']
                or hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']):
            raise PermissionError('exact private SMTP snapshot file required')
        _attach_file(msg,path,meta['name'])  # Actual pinned attachment encoder.
    return msg


def publish(adapter,value,policy,connector,item,current,paths=()):
    """Called only in the supervised private worker after durable write intent."""
    from plugins.platforms.email.adapter import EmailAdapter
    item=specification(value,policy(),connector,item);expected=build(adapter,value,item,paths)
    expected_sha256=hashlib.sha256(expected.as_bytes()).hexdigest()
    transport=Transport(adapter,value,current);state={'opened':False,'accepted':False,'rejections':[]}
    def check():
        transport.check();specification(value,policy(),connector,item)
    class Session:
        def __init__(self):
            check()
            if state['opened']:raise PermissionError('one private SMTP connection per write intent')
            state['opened']=True;self.authenticated=False;self.used=False
            self.connection=EmailAdapter._connect_smtp(adapter)
            try:transport.verified(self.connection,value['smtp_host'])
            except BaseException:self.connection.close();raise
            if self.connection.file is None:self.connection.file=self.connection.sock.makefile('rb')
            reader=ReplyReader(self.connection.file,check);self.connection.file=reader
            send,getreply=self.connection.send,self.connection.getreply
            def checked_send(data):check();result=send(data);check();return result
            def checked_reply():
                check();reader.reset()
                try:result=getreply()
                except BaseException:check();raise
                check()
                if 400<=result[0]<=599:state['rejections'].append(result[0])
                return result
            self.connection.send=checked_send;self.connection.getreply=checked_reply
        def login(self,username,password):
            check()
            if self.authenticated or username!=value['address'] or password!=value['password']:
                raise PermissionError('exact single private SMTP authentication required')
            result=self.connection.login(username,password);check();self.authenticated=True;return result
        def send_message(self,msg):
            check()
            if not self.authenticated or self.used or hashlib.sha256(msg.as_bytes()).hexdigest()!=expected_sha256:
                raise PermissionError('exact single native SMTP MIME reply required')
            self.used=True;state['rejections']=[]
            refused=self.connection.send_message(msg,from_addr=value['address'],to_addrs=[item['recipient']])
            check()
            if refused:raise PermissionError('SMTP recipient was not accepted')
            state['accepted']=True
        def close(self):self.connection.close()
        def quit(self):self.close()  # No additional mail command during cleanup.
    previous=adapter._connect_smtp
    adapter._connect_smtp=MethodType(lambda _self:Session(),adapter)
    try:
        # Actual upstream login/send_message/finally lifecycle, not a replacement
        # SMTP implementation. Session admits exactly the native MIME above.
        EmailAdapter._smtp_send(adapter,expected);check()
        if not state['accepted']:raise ConnectionError('native SMTP acceptance is unknown')
        return {'accepted':True,'receipt':'smtp_accept_'+digest([identity(value,item),item['delivery_id'],item['attempt']]),
            'recipient_receipt_verified':False}
    except smtplib.SMTPAuthenticationError:return {'error':'smtp-authentication-refused'}
    except smtplib.SMTPRecipientsRefused as error:
        codes=[value[0] for value in error.recipients.values()]
        if len(codes)==1 and type(codes[0]) is int and codes[0] in state['rejections']:
            return {'error':'smtp-temporary-refusal' if codes[0]<500 else 'smtp-permanent-refusal'}
        return {'error':'smtp-outcome-unknown'}
    except smtplib.SMTPResponseException as error:
        if type(error.smtp_code) is int and error.smtp_code in state['rejections']:
            return {'error':'smtp-temporary-refusal' if error.smtp_code<500 else 'smtp-permanent-refusal'}
        return {'error':'smtp-outcome-unknown'}
    finally:adapter._connect_smtp=previous
