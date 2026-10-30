"""Independent original-bound resource proof and decoded media consent."""
import base64
import hashlib
import re

from .gateway import digest
from .gateway_dingtalk_admission import MAX_EVENT, approve, normalize
from .gateway_media import approved, describe
from .redaction import Redactor

from .gateway_dingtalk_process import ERRORS as ACCOUNT_ERRORS
ERRORS=ACCOUNT_ERRORS|{'content-refused','content-rate-limited'}


def specification(value, policy, connector, item, redactor):
    fields = {'binding_id', 'binding_digest', 'source_base64', 'source_sha256', 'resource_index'}
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError('exact retained DingTalk resource proof required')
    if not isinstance(redactor, Redactor):
        raise PermissionError('private resource redaction required')
    if (not isinstance(item['binding_id'], str) or type(item['resource_index']) is not int
            or not 0 <= item['resource_index'] < 4
            or any(not isinstance(item[key], str) or not re.fullmatch('[0-9a-f]{64}', item[key]) for key in ('binding_digest', 'source_sha256'))
            or not isinstance(item['source_base64'], str) or not 1 <= len(item['source_base64']) <= 4 * ((MAX_EVENT + 2) // 3)):
        raise ValueError('bounded original DingTalk resource proof required')
    raw = base64.b64decode(item['source_base64'], validate=True)
    if (not 1 <= len(raw) <= MAX_EVENT or base64.b64encode(raw).decode() != item['source_base64']
            or hashlib.sha256(raw).hexdigest() != item['source_sha256']):
        raise ValueError('original DingTalk resource bytes changed')
    binding = policy.current_binding({'binding_id': item['binding_id'], 'binding_digest': item['binding_digest']})
    proof = approve(policy, connector, value, raw)
    projection = normalize(policy, connector, value, raw, proof, redactor)
    if (proof['binding_id'] != binding['id'] or proof['binding_digest'] != digest(binding)
            or binding['connector'] != connector or 'create' not in binding['capabilities']
            or projection['envelope']['text'].lstrip().startswith('/')
            or redactor.clean(projection['envelope']) != projection['envelope']):
        raise PermissionError('current exact DingTalk media/create source required')
    if item['resource_index'] >= len(projection['resources']):
        raise PermissionError('DingTalk resource absent from independently approved original')
    resource = dict(projection['resources'][item['resource_index']])
    if not approved(binding, resource['kind']):
        raise PermissionError('separate DingTalk media permission required')
    return {'resource': resource, 'binding': dict(binding), 'envelope': projection['envelope']}


def classify(spec, mime, data):
    if not isinstance(mime, str) or not isinstance(data, bytes):
        raise ValueError('exact native resource bytes and MIME required')
    kind = spec['resource']['kind']
    video = len(data) >= 16 and data[4:8] == b'ftyp'
    voice = (data.startswith((b'#!AMR\n', b'#!AMR-WB\n', b'OggS', b'fLaC', b'ID3'))
             or len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WAVE'
             or len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224)
    if mime.startswith('video/') or video:
        kind = 'video'
    elif mime.startswith('audio/') or voice:
        kind = 'voice'
    elif mime in {'image/png', 'image/jpeg'} or data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')):
        kind = 'image'
    if not approved(spec['binding'], kind):
        raise PermissionError('decoded DingTalk resource requires separate media/voice/video consent')
    meta = describe(data, kind)
    if kind == 'image' and mime not in {'image/' + meta['format'], 'application/octet-stream'}:
        raise ValueError('native DingTalk image MIME and original bytes disagree')
    if kind == 'voice' and not (mime.startswith('audio/') or mime == 'application/octet-stream'):
        raise ValueError('native DingTalk voice MIME differs from decoded resource')
    if kind == 'video' and not (mime.startswith('video/') or mime == 'application/octet-stream'):
        raise ValueError('native DingTalk video MIME differs from decoded resource')
    return meta


async def fetch(request, value, current, redactor):
    """Only the isolated gateway-UID worker may resolve and read private media."""
    from pathlib import Path
    from .gateway_dingtalk import PreparedDingTalkPolicy
    from .gateway_dingtalk_http import Boundary, sdk_scope, QuietLogger, Failure
    from .gateway_dingtalk_tea import Lookup, sdk_scope as robot_scope
    from .gateway_dingtalk_download import fetch as download
    from .sandbox import trusted_json
    def policy():
        current(); return PreparedDingTalkPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    blueprint = specification(value, policy(), request['connector'], request['resource'], redactor)
    def approved():
        if specification(value, policy(), request['connector'], request['resource'], redactor) != blueprint:
            raise PermissionError('private resource source or decoded consent changed')
    from gateway.config import PlatformConfig
    from plugins.platforms.dingtalk import adapter as native
    from .gateway_ingress import durable_adapter
    adapter = durable_adapter(native.DingTalkAdapter(PlatformConfig(enabled=True, extra={
        'client_id': value['client_id'], 'client_secret': value['client_secret'],
        'robot_code': value['robot_code'], 'card_template_id': ''})))
    owner = Boundary(value, approved, redactor); adapter._stream_client = owner.client()
    adapter._robot_sdk = native.dingtalk_robot_client.Client(native.open_api_models.Config(protocol='https', region_id='central'))
    logger = native.logger; native.logger = QuietLogger(); lookup = None
    try:
        with sdk_scope(), owner.operation('token', adapter._stream_client):
            token = await adapter._get_access_token()
        if token is None or token not in owner.tokens:
            raise Failure(owner.failure or 'invalid-token',owner.retry_after if owner.failure=='rate-limited' else 0)
        approved(); code = blueprint['resource']['code']; carrier = {'downloadCode': code}
        lookup = Lookup(owner, token, code, approved)
        with robot_scope(lookup):
            await adapter._fetch_download_url(code, value['robot_code'], token, carrier, 'downloadCode')
        approved()
        if not lookup.used or lookup.url is None or carrier['downloadCode'] != lookup.url:
            raise Failure(lookup.failure or 'invalid-response',lookup.retry_after if lookup.failure=='rate-limited' else 0)
        data, mime = await download(lookup.url, blueprint['resource']['kind'], approved, redactor)
        approved(); meta = classify(blueprint, mime, data)
        return {'data_base64': base64.b64encode(data).decode(), 'descriptor': meta, 'mime': mime,
                'request_sha256': digest(request['resource'])}
    finally:
        native.logger = logger
        if lookup is not None: await lookup.close()
        owner.close()


def response(result, item, value):
    from .gateway_media import descriptor, MAX_BYTES
    if isinstance(result, dict) and set(result) in ({'error'},{'error','retry_after'}):
        if isinstance(result['error'], str) and result['error'] in ERRORS:
            if set(result)=={'error'}:return result
            if (result['error'] in {'rate-limited','content-rate-limited'} and type(result['retry_after']) is int
                    and 1<=result['retry_after']<=86400):return result
        raise ValueError('finite private DingTalk resource error required')
    if (not isinstance(result, dict) or set(result) != {'data_base64', 'descriptor', 'mime', 'request_sha256'}
            or result['request_sha256'] != digest(item) or not isinstance(result['data_base64'], str)
            or not 1 <= len(result['data_base64']) <= 4 * ((MAX_BYTES + 2) // 3)
            or not isinstance(result['mime'], str)
            or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}', result['mime'])):
        raise ValueError('exact bounded private DingTalk resource result required')
    data = base64.b64decode(result['data_base64'], validate=True); meta = descriptor(result['descriptor'])
    if (base64.b64encode(data).decode() != result['data_base64'] or describe(data, meta['kind']) != meta
            or value['client_secret'].encode() in data):
        raise ValueError('private DingTalk resource bytes or descriptor changed')
    return {'data': data, 'descriptor': meta, 'mime': result['mime']}
