"""One exact native SDK multipart upload; no messages, URLs or host-file capability."""
from contextlib import contextmanager
from copy import deepcopy
from email import policy
from email.parser import BytesParser
import hashlib
import re

from .gateway_feishu_http import Boundary,Failure,active
from .gateway_media import MAX_BYTES


def target(value):
    fields={'kind','name','size','sha256','file_type','duration_ms'}
    if (not isinstance(value,dict) or set(value)!=fields or not isinstance(value['kind'],str) or value['kind'] not in {'image','file'}
            or not isinstance(value['name'],str) or not re.fullmatch(r'result-[0-3]\.[a-z0-9]{1,8}',value['name'])
            or type(value['size']) is not int or not 1<=value['size']<=MAX_BYTES
            or not isinstance(value['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['sha256'])
            or not isinstance(value['file_type'],str) or value['file_type'] not in {'','opus','mp4','pdf','doc','xls','ppt','stream'}
            or type(value['duration_ms']) is not int or not 0<=value['duration_ms']<=3600000
            or value['kind']=='image' and (value['file_type'] or value['duration_ms'])
            or value['kind']=='file' and not value['file_type']):
        raise Failure('unapproved-operation')
    return deepcopy(value)


def multipart(encoder,blueprint):
    """Check actual wire bytes, not just mutable fields on an SDK model."""
    from requests_toolbelt import MultipartEncoder
    exact=target(blueprint)
    if (type(encoder) is not MultipartEncoder or type(encoder.len) is not int
            or not 1<=encoder.len<=exact['size']+16384 or not isinstance(encoder.content_type,str)
            or not re.fullmatch('multipart/form-data; boundary=[A-Za-z0-9_-]{1,70}',encoder.content_type)):
        raise Failure('changed-upload')
    raw=encoder.to_string()
    if len(raw)!=encoder.len:raise Failure('changed-upload')
    try:
        message=BytesParser(policy=policy.default).parsebytes(
            ('MIME-Version: 1.0\r\nContent-Type: '+encoder.content_type+'\r\n\r\n').encode()+raw)
        if message.defects or not message.is_multipart():raise ValueError
        parts={}
        for part in message.iter_parts():
            name=part.get_param('name',header='content-disposition')
            if (part.defects or part.is_multipart() or part.get_content_disposition()!='form-data' or name in parts
                    or len(part.get_all('Content-Disposition',[]))!=1
                    or len(part.get_all('Content-Type',[]))>1
                    or part.get_filename() not in {None,exact['name']}):raise ValueError
            parts[name]=part.get_payload(decode=True)
        file_field='image' if exact['kind']=='image' else 'file'
        data=parts.pop(file_field)
        if not isinstance(data,bytes) or len(data)!=exact['size'] or hashlib.sha256(data).hexdigest()!=exact['sha256']:
            raise ValueError
        expected=({'image_type':b'message'} if exact['kind']=='image' else {'file_type':exact['file_type'].encode(),
            'file_name':exact['name'].encode(),'duration':str(exact['duration_ms']).encode() if exact['duration_ms'] else b''})
        if parts!=expected:raise ValueError
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):raise Failure('changed-upload') from None
    return raw,encoder.content_type


class UploadBoundary(Boundary):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.credential_secrets=tuple(self.redactor.secrets)

    @contextmanager
    def operation(self,config,purpose,blueprint):
        if purpose!='upload':raise Failure('unapproved-operation')
        with self._operation(config,purpose,target(blueprint)) as state:
            state['write_started']=False
            yield state

    def request(self,real,method,url,**kwargs):
        state=active()
        if state['boundary'] is not self:raise Failure('wrong-account')
        if method=='POST' and url==self.origin+('/open-apis/im/v1/images' if state['target']['kind']=='image' else '/open-apis/im/v1/files'):
            self.check(state)
            if state.get('write_started'):raise Failure('unapproved-operation')
            raw,content_type=multipart(kwargs.get('data'),state['target'])
            headers=kwargs.get('headers') or {}
            if not isinstance(headers,dict) or {key.lower():value for key,value in headers.items()}.get('content-type')!=content_type:
                raise Failure('changed-upload')
            if any(secret.encode() in raw for secret in self.redactor.secrets):raise Failure('credential-reflection')
            kwargs['data']=raw;state['wire_sha256']=hashlib.sha256(raw).hexdigest();state['wire_size']=len(raw)
        def identity_encoding(method,url,**options):
            options['headers']={**options['headers'],'Accept-Encoding':'identity'}
            return real(method,url,**options)
        return super().request(identity_encoding,method,url,**kwargs)

    def api_request(self,state,method,path,data):
        expected='/open-apis/im/v1/images' if state['target']['kind']=='image' else '/open-apis/im/v1/files'
        if (state.get('write_started') or method!='POST' or path!=expected or not isinstance(data,bytes)
                or len(data)!=state.get('wire_size') or hashlib.sha256(data).hexdigest()!=state.get('wire_sha256')):
            raise Failure('unapproved-operation')
        return True

    def api_response(self,state,body):
        state['upload_response']=deepcopy(body)
        if body['code']==0:
            key='image_key' if state['target']['kind']=='image' else 'file_key'
            data=body.get('data');value=data.get(key) if isinstance(data,dict) else None
            if not isinstance(value,str) or not re.fullmatch(('img_' if state['target']['kind']=='image' else 'file_')+'[A-Za-z0-9_-]{8,251}',value) or any(secret in value for secret in [*self.credential_secrets,*self.tokens]):
                raise Failure('invalid-response')
            self.remember(value);state['accepted_key']=value
