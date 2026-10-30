"""Exact original-message attachment capabilities and bounded private SDK reads."""
import asyncio
import io
import re
import time
from urllib.parse import urlsplit,parse_qs

from .gateway import digest,Conflict
from .gateway_google_chat_admission import approve,message,Refused
from .gateway_dingtalk_admission import parse
from .gateway_media import authorize,describe,MAX_BYTES,MAX_IMAGE_BYTES


def specifications(policy,connector,value,raw,approval,envelope):
    current=approve(policy,connector,value,raw)
    if current!=approval or {**envelope,'text':''}!=approval['envelope']:raise PermissionError('Google Chat media original or independent source changed')
    msg,_=message(parse(raw));items=msg.get('attachment',[]);result=[]
    for index,item in enumerate(items):
        mime=item.get('contentType')
        if not isinstance(mime,str) or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',mime):
            raise Refused('unsupported-attachment-type')
        kind='image' if mime.startswith('image/') else 'voice' if mime.startswith('audio/') else 'video' if mime.startswith('video/') else 'document'
        if kind=='image' and mime not in {'image/png','image/jpeg'} or kind=='video' and mime not in {'video/mp4','video/3gpp','video/3gpp2'}:
            raise Refused('unsupported-attachment-type')
        authorize(policy,connector,envelope,kind)
        reference=item.get('attachmentDataRef')
        prefix=envelope['message_id']+'/attachments/'
        if (not isinstance(reference,dict) or not {'resourceName'}<=set(reference)<={'resourceName','attachmentUploadToken'} or not isinstance(reference['resourceName'],str)
                or not reference['resourceName'].startswith(prefix)
                or not re.fullmatch('[A-Za-z0-9_-]{1,256}',reference['resourceName'][len(prefix):])):
            # No unbounded downloadUri/anonymous fetch or silent Drive skip.
            raise Refused('attachment-resource-unavailable')
        upload=reference.get('attachmentUploadToken')
        if upload is not None and (not isinstance(upload,str) or not 1<=len(upload)<=16384 or any(not 33<=ord(c)<=126 for c in upload)):
            raise Refused('attachment-resource-unavailable')
        resource=reference['resourceName']
        if item.get('name') is not None and item['name']!=resource:raise Refused('ambiguous-attachment-resource')
        result.append({'index':index,'resource':resource,'mime':mime,'kind':kind})
    policy.current_binding(approval);return result


def classify(spec,data):
    meta=describe(data,spec['kind'])
    if spec['kind']=='image' and {'png':'image/png','jpeg':'image/jpeg'}[meta['format']]!=spec['mime']:
        raise Refused('attachment-type-mismatch')
    if spec['kind']=='video' and {'mp4':'video/mp4','3gp':'video/3gpp','3g2':'video/3gpp2'}[meta['format']]!=spec['mime']:
        raise Refused('attachment-type-mismatch')
    return meta


async def download(adapter,spec,current,*,fixture_origin=None,http=None):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();current()
    from plugins.platforms.google_chat.adapter import GoogleChatAdapter
    if not isinstance(adapter,GoogleChatAdapter):raise TypeError('actual pinned Google Chat adapter required')
    from googleapiclient.http import MediaIoBaseDownload
    request=adapter._chat_api.media().download_media(resourceName=spec['resource']);parsed=urlsplit(request.uri)
    official=parsed.scheme=='https' and parsed.netloc=='chat.googleapis.com'
    if fixture_origin is not None:
        local=urlsplit(fixture_origin)
        if (local.scheme,local.hostname) not in {('http','127.0.0.1'),('https','localhost')} or not local.port or local.path or local.query or local.fragment or local.username:
            raise ValueError('explicit local Google media fixture authority required')
    fixture=fixture_origin is not None and request.uri.startswith(fixture_origin+'/')
    if (not (official or fixture) or parsed.path!='/v1/media/'+spec['resource'] or parse_qs(parsed.query)!={'alt':['media']}
            or parsed.username or parsed.password or parsed.fragment):raise PermissionError('exact source-bound Google media resource URI required')
    redactor=adapter._haos_native.inbox.redactor;deadline=time.monotonic()+45
    def checked():
        require_runtime_identity();current()
        if time.monotonic()>deadline:raise TimeoutError('private Google media deadline')
    transport=http if http is not None else adapter._haos_google_media_http(checked)
    class BoundedBuffer(io.BytesIO):
        def write(self,data):
            if self.tell()+len(data)>MAX_BYTES:raise ValueError('Google attachment exceeds private byte budget')
            return super().write(data)
    class ExactRead:
        count=0;offset=0;total=None
        def request(self,uri,method='GET',body=None,headers=None,**kwargs):
            checked();self.count+=1
            if uri!=request.uri or method!='GET' or body is not None or self.count>32:
                raise PermissionError('bounded source-bound Google media GET required')
            response,data=transport.request(uri,method=method,body=body,headers=headers,**kwargs);checked()
            if not isinstance(data,bytes) or len(data)>MAX_BYTES:raise ValueError('bounded Google media response bytes required')
            if response.status in {200,206}:
                mime=response.get('content-type','application/octet-stream').split(';',1)[0].strip().lower()
                if mime not in {spec['mime'],'application/octet-stream'}:raise Refused('attachment-type-mismatch')
                content_range=response.get('content-range')
                if content_range is not None:
                    match=re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)',content_range)
                    if (not match or not 0<=int(match[1])<=int(match[2])<int(match[3])<=MAX_BYTES
                            or int(match[1])!=self.offset or int(match[2])-int(match[1])+1!=len(data)
                            or self.total is not None and self.total!=int(match[3])):
                        raise ValueError('bounded exact Google media Content-Range required')
                    self.total=int(match[3])
                elif response.status==206 or self.offset:
                    raise ValueError('Google media range response changed or omitted its offset')
                self.offset+=len(data)
            return response,data
    def fetch():
        request.http=ExactRead();buffer=BoundedBuffer();reader=MediaIoBaseDownload(buffer,request,chunksize=512*1024);done=False
        while not done:checked();_status,done=reader.next_chunk(num_retries=0)
        checked();data=buffer.getvalue();classify(spec,data)
        if any(secret.encode() in data for secret in redactor.secrets if secret):raise PermissionError('private credentials cannot become Google Chat media')
        return data
    data=await asyncio.to_thread(fetch);current();return data


async def retained(adapter,raw_id,raw,approval,envelope,specs,*,reader=None):
    from .gateway_media_relay import MediaCache
    native=adapter._haos_native;db=native.inbox.db;cache=MediaCache(native.inbox);result=[];image_ids=set();images=0
    db.execute('''CREATE TABLE IF NOT EXISTS google_chat_input_media(
        raw_id TEXT NOT NULL,resource_index INTEGER NOT NULL,fingerprint TEXT NOT NULL,
        upload_id TEXT NOT NULL,mime TEXT NOT NULL,PRIMARY KEY(raw_id,resource_index))''')
    def current():
        adapter._haos_google_check();policy=native.policy();policy.current_binding(approval)
        if specifications(policy,native.connector,adapter._haos_google_value,raw,approval,envelope)!=specs:
            raise PermissionError('Google attachment source or permission changed')
        return policy
    for spec in specs:
        selected=current();base=digest([raw_id,approval,digest(envelope),spec])
        prior=db.execute('SELECT * FROM google_chat_input_media WHERE raw_id=? AND resource_index=?',(raw_id,spec['index'])).fetchone();cached=None
        if prior is not None:
            if prior['mime']!=spec['mime'] or prior['fingerprint']!=digest([base,prior['upload_id'],prior['mime']]):
                raise Conflict('Google media source, kind, account, grant or retained byte identity changed')
            if db.execute('SELECT 1 FROM native_media_cache WHERE id=?',(prior['upload_id'],)).fetchone():cached=cache.replay(selected,prior['upload_id'])
        if cached is None:
            cache.capacity();data=await (reader or download)(adapter,spec,current);selected=current();meta=classify(spec,data)
            expected=digest([native.connector,digest(selected.current_binding(approval)),digest(envelope),meta])
            if prior is not None:
                if prior['upload_id']!=expected:raise Conflict('Google attachment changed bytes after first custody intent')
            else:db.execute('INSERT INTO google_chat_input_media VALUES(?,?,?,?,?)',(raw_id,spec['index'],digest([base,expected,spec['mime']]),expected,spec['mime']))
            cached=cache.put(selected,native.connector,envelope,data,meta['kind'])
            if cached['id']!=expected:raise Conflict('Google retained bytes differ from durable source intent')
        if cached['envelope_digest']!=digest(envelope) or cached['connector']!=native.connector:raise Conflict('Google media cache points to another source')
        if cached['descriptor']['kind']=='image' and cached['id'] not in image_ids:
            image_ids.add(cached['id']);images+=cached['descriptor']['size']
        if images>MAX_IMAGE_BYTES:raise Refused('aggregate-image-budget')
        result.append({'spec':dict(spec),'item':cached})
    current();return result
