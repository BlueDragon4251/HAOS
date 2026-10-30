"""Native A2A file Parts with separate consent and opaque agent-facing carriers."""
import base64
from copy import deepcopy
import hashlib
import re
from urllib.parse import urlsplit

from .gateway import Conflict,digest
from .gateway_media import describe,approved,MAX_BYTES,MAX_FILES,MAX_IMAGE_BYTES

MIME=re.compile('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}\\Z')


def origins(value,peers):
    from .gateway_mattermost import server_url
    if not isinstance(value,dict) or not set(value)<=set(peers):raise ValueError('download origins require exact configured A2A peers')
    result={}
    for peer,items in value.items():
        if not isinstance(items,list) or not 1<=len(items)<=4:raise ValueError('at most four explicit HTTPS media origins per A2A peer')
        normalized=[]
        for item in items:
            origin=server_url(item)
            if urlsplit(origin).path:raise ValueError('A2A download approval is one exact HTTPS origin without path')
            if origin in normalized:raise ValueError('duplicate A2A download origin')
            normalized.append(origin)
        result[peer]=sorted(normalized)
    return dict(sorted(result.items()))


def target(value,peer,url):
    if (not isinstance(url,str) or not 1<=len(url)<=4096 or any(ord(c)<33 or ord(c)>126 for c in url) or '\\' in url):
        raise ValueError('bounded exact A2A HTTPS attachment URL required')
    try:parts=urlsplit(url);host=parts.hostname;port=parts.port
    except ValueError:raise ValueError('invalid A2A attachment URL') from None
    if (parts.scheme!='https' or not host or parts.username is not None or parts.password is not None
            or parts.fragment or '#' in url or port is not None and not 1<=port<=65535):
        raise PermissionError('A2A media needs exact approved HTTPS origin; no credentials, fragments or downgrade')
    authority=('['+host+']') if ':' in host else host.lower()
    if port is not None and port!=443:authority+=':'+str(port)
    origin='https://'+authority
    if origin not in value.get('download_origins',{}).get(peer,[]):raise PermissionError('A2A attachment origin has no independent owner download approval')
    return url


def part(value,peer,item,index):
    if not isinstance(item,dict):raise ValueError('native A2A file Part required')
    if 'raw' in item or 'url' in item:
        if (not set(item)<={'raw','url','filename','mediaType','kind','type'} or ('raw' in item)==('url' in item)
                or 'kind' in item and item['kind']!='file' or 'type' in item and item['type']!='file'):
            raise ValueError('one native file byte or URI member required')
        mime=item.get('mediaType');name=item.get('filename','attachment-'+str(index));url=item.get('url');encoded=item.get('raw')
    elif set(item)<={'file','kind','type'} and isinstance(item.get('file'),dict):
        legacy=item['file']
        if (not {'fileWithUri'}<=set(legacy)<={'fileWithUri','name','mimeType'}
                or 'kind' in item and item['kind']!='file' or 'type' in item and item['type']!='file'):
            raise ValueError('reviewed native legacy URI file Part required')
        mime=legacy.get('mimeType');name=legacy.get('name','attachment-'+str(index));url=legacy['fileWithUri'];encoded=None
    else:raise ValueError('reviewed native A2A file Part required')
    if (not isinstance(mime,str) or not MIME.fullmatch(mime) or not isinstance(name,str) or not 1<=len(name)<=128
            or name!=name.strip() or name in {'.','..'} or any(ord(c)<32 or c in '/\\' for c in name)):
        raise ValueError('bounded path-free native A2A filename and exact MIME required')
    kind='image' if mime.startswith('image/') else 'voice' if mime.startswith('audio/') else 'video' if mime.startswith('video/') else 'document'
    if kind=='image' and mime not in {'image/png','image/jpeg'}:raise ValueError('A2A model images require PNG/JPEG')
    if kind=='video' and mime not in {'video/mp4','video/3gpp','video/3gpp2'}:raise ValueError('A2A video requires reviewed ISO MP4/3GP bytes')
    if encoded is not None:
        if not isinstance(encoded,str) or not 1<=len(encoded)<=4*((MAX_BYTES+2)//3):raise ValueError('bounded canonical native A2A base64 required')
        try:data=base64.b64decode(encoded,validate=True)
        except ValueError:raise ValueError('invalid native A2A file base64') from None
        if base64.b64encode(data).decode()!=encoded:raise ValueError('noncanonical native A2A file base64')
        meta=classify(kind,mime,data);mode='inline';source=meta
    else:
        target(value,peer,url);data=None;meta=None;mode='https';source=hashlib.sha256(url.encode()).hexdigest()
    return {'index':index,'kind':kind,'mime':mime,'name':name,'mode':mode,'source':source},data,url


def classify(kind,mime,data):
    detected=('image' if data.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff')) else
        'voice' if data.startswith((b'fLaC',b'OggS',b'#!AMR',b'ID3')) or data[:4]==b'RIFF' and data[8:12]==b'WAVE' else
        'voice' if len(data)>=12 and data[4:8]==b'ftyp' and data[8:12] in {b'M4A ',b'M4B '} else
        'video' if len(data)>=12 and data[4:8]==b'ftyp' else None)
    if detected is not None and detected!=kind:raise ValueError('native A2A bytes cannot downgrade a known image/audio/video into another consent kind')
    meta=describe(data,kind)
    if kind=='image' and mime!='image/'+meta['format']:raise ValueError('A2A image MIME and original bytes differ')
    if kind=='video' and mime!={'mp4':'video/mp4','3gp':'video/3gpp','3g2':'video/3gpp2'}[meta['format']]:
        raise ValueError('A2A video MIME and original bytes differ')
    return meta


def projection(value,peer,params,redactor,*,binding=None):
    projected=deepcopy(params);resources=[];images=0
    urls=[]
    for item in params['message']['parts']:
        if not isinstance(item,dict):continue
        url=item.get('url')
        if isinstance(item.get('file'),dict):url=item['file'].get('fileWithUri',url)
        if isinstance(url,str):urls.append(target(value,peer,url))
    redactor.secrets=sorted(set(redactor.secrets)|set(urls),key=len,reverse=True)
    for index,item in enumerate(params['message']['parts']):
        if isinstance(item,dict) and 'text' in item:continue
        spec,data,url=part(value,peer,item,index)
        if binding is not None and not approved(binding,spec['kind']):raise PermissionError('A2A attachment kind lacks separate owner consent')
        if data is not None:
            if any(secret.encode() in data for secret in redactor.secrets):raise PermissionError('private credential cannot become A2A file input')
            if spec['kind']=='image':images+=len(data)
        if url is not None:
            carrier='HAOS attachment '+str(len(resources)+1)
            if 'file' in item:projected['message']['parts'][index]['file']['fileWithUri']=carrier
            else:projected['message']['parts'][index]['url']=carrier
        resources.append(spec)
    if len(resources)>MAX_FILES or images>MAX_IMAGE_BYTES:raise ValueError('A2A attachment count or aggregate image budget exceeded')
    return projected,resources
