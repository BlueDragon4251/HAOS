"""Original-event-bound private resource capabilities and native cache decoding."""
import base64
import hashlib
import re

from .gateway import digest
from .gateway_feishu_admission import MAX_EVENT,approve,normalize
from .gateway_media import describe,approved,MAX_BYTES
from .redaction import Redactor


def specification(value,policy,connector,item,redactor):
    fields={'binding_id','binding_digest','source_base64','source_sha256','resource_index'}
    if not isinstance(item,dict) or set(item)!=fields:raise ValueError('exact retained resource proof required')
    if not isinstance(redactor,Redactor):raise PermissionError('private resource redaction required')
    if (not isinstance(item['binding_id'],str) or type(item['resource_index']) is not int or not 0<=item['resource_index']<4
            or any(not isinstance(item[key],str) or not re.fullmatch('[0-9a-f]{64}',item[key]) for key in ['binding_digest','source_sha256'])
            or not isinstance(item['source_base64'],str) or not 1<=len(item['source_base64'])<=4*((MAX_EVENT+2)//3)):
        raise ValueError('bounded original resource proof required')
    raw=base64.b64decode(item['source_base64'],validate=True)
    if (not 1<=len(raw)<=MAX_EVENT or base64.b64encode(raw).decode()!=item['source_base64']
            or hashlib.sha256(raw).hexdigest()!=item['source_sha256']):raise ValueError('original resource bytes changed')
    binding=policy.current_binding({'binding_id':item['binding_id'],'binding_digest':item['binding_digest']})
    proof=approve(policy,connector,value,raw);projection=normalize(policy,connector,value,raw,proof,redactor)
    if (proof['binding_id']!=binding['id'] or proof['binding_digest']!=digest(binding)
            or binding['connector']!=connector or 'create' not in binding['capabilities']
            or projection['envelope']['text'].lstrip().startswith('/') or redactor.clean(projection)!=projection):
        raise PermissionError('current exact media/create source required')
    if item['resource_index']>=len(projection['resources']):raise PermissionError('resource absent from approved original')
    resource=projection['resources'][item['resource_index']];kind=resource['type']
    types=[kind,'file'] if kind in {'audio','media'} else [kind]
    from .gateway_feishu_resource_http import target
    return {'target':target({'message_id':projection['envelope']['message_id'],'file_key':resource['key'],'types':types}),
        'resource':resource,'binding':dict(binding),'envelope':projection['envelope']}


def classify(spec,mime,data):
    """Native wire selector is never permission for ASR, video or model images."""
    resource=spec['resource'];permissions=resource['permissions']
    kind=('voice' if 'allow_voice' in permissions else 'video' if 'allow_video' in permissions
        else 'image' if resource['type']=='image' or mime in {'image/png','image/jpeg'}
        else 'voice' if mime.startswith('audio/') else 'video' if mime.startswith('video/') else 'document')
    if not approved(spec['binding'],kind):raise PermissionError('decoded resource kind lacks separate owner consent')
    meta=describe(data,kind)
    if kind=='image' and mime!='image/'+meta['format']:raise ValueError('native image MIME and original bytes disagree')
    if kind=='voice' and not (mime.startswith('audio/') or mime=='application/octet-stream'):
        raise ValueError('native voice MIME differs from approved resource')
    return meta


def fetch(request,value,home,current,redactor):
    """Execute the actual native SDK/cache helper only in the disposable UID worker."""
    import asyncio
    import os
    from pathlib import Path
    import stat
    import tempfile
    from .gateway_feishu import PreparedFeishuPolicy,DOMAINS
    from .gateway_feishu_http import Failure,sdk_scope
    from .gateway_feishu_resource_http import ResourceBoundary
    from .gateway_matrix_profile import scope
    from .sandbox import trusted_json
    def policy():
        current();return PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    blueprint=specification(value,policy(),request['connector'],request['resource'],redactor)
    def authorize(purpose,target):
        latest=specification(value,policy(),request['connector'],request['resource'],redactor)
        return purpose=='resource' and latest==blueprint and target==latest['target']
    adapter=None
    try:
        with tempfile.TemporaryDirectory(prefix='resource-',dir=home) as name,scope(Path(name),{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu import adapter as native
            from gateway.config import PlatformConfig
            if not native._load_lark_oapi():raise Failure('sdk-unavailable')
            adapter=native.FeishuAdapter(PlatformConfig(enabled=True))
            boundary=ResourceBoundary(value,current,authorize,redactor)
            with sdk_scope():
                client=native._build_lark_client(value['app_id'],value['app_secret'],DOMAINS[value['domain']]);adapter._client=client
                exact=blueprint['target']
                with boundary.operation(client._config,'resource',exact) as operation:
                    if exact['types']==['image']:
                        path,mime=asyncio.run(adapter._download_feishu_image(message_id=exact['message_id'],image_key=exact['file_key']))
                    else:
                        path,mime=asyncio.run(adapter._download_feishu_message_resource(message_id=exact['message_id'],file_key=exact['file_key'],
                            resource_type=exact['types'][0],fallback_filename='attachment.bin'))
                    if operation.get('resource_blocked'):raise Failure(operation['resource_blocked'])
                    if not path:raise Failure(operation.get('resource_failure','invalid-response'))
                    if not Path(path).resolve().is_relative_to(Path(name).resolve()):raise Failure('invalid-response')
                    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                    try:
                        metadata=os.fstat(fd)
                        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.geteuid() or metadata.st_nlink!=1
                                or not 1<=metadata.st_size<=MAX_BYTES or metadata.st_mode&0o022):raise Failure('invalid-response')
                        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(MAX_BYTES+1)
                    finally:os.close(fd)
                    if len(data)!=metadata.st_size or any(secret.encode() in data for secret in redactor.secrets):
                        raise Failure('invalid-response')
                    latest=specification(value,policy(),request['connector'],request['resource'],redactor)
                    if latest!=blueprint:raise PermissionError('resource source or consent changed')
                    descriptor=classify(latest,mime,data);current()
                    return {'data_base64':base64.b64encode(data).decode(),'descriptor':descriptor,'mime':mime,
                        'request_sha256':digest(request['resource'])}
    finally:
        if adapter is not None:adapter._shutdown_sdk_executor()


def response(result,item,value):
    from .gateway_feishu_process import ERRORS
    from .gateway_media import descriptor
    if isinstance(result,dict) and set(result)=={'error'}:
        if isinstance(result['error'],str) and result['error'] in ERRORS:return result
        raise ValueError('finite private resource error required')
    if (not isinstance(result,dict) or set(result)!={'data_base64','descriptor','mime','request_sha256'}
            or result['request_sha256']!=digest(item) or not isinstance(result['data_base64'],str)
            or not 1<=len(result['data_base64'])<=4*((MAX_BYTES+2)//3)
            or not isinstance(result['mime'],str) or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',result['mime'])):
        raise ValueError('exact bounded private resource result required')
    data=base64.b64decode(result['data_base64'],validate=True);meta=descriptor(result['descriptor'])
    if (base64.b64encode(data).decode()!=result['data_base64'] or describe(data,meta['kind'])!=meta
            or value['app_secret'].encode() in data):raise ValueError('private resource bytes or descriptor changed')
    return {'data':data,'descriptor':meta,'mime':result['mime']}
