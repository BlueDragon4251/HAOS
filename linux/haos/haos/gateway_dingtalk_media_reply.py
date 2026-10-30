"""Exact native Robot media payloads from source-bound private upload receipts."""
from copy import deepcopy
import json

from .gateway import digest
from .gateway_dingtalk_upload import specification as upload_specification,response as upload_response
from .gateway_dingtalk_send import specification as reply_specification,wire_target as text_target
from .gateway_dingtalk_robot_reply import Reply
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object


def specification(value,policy,connector,item,redactor):
    required={'upload','receipt','duration_ms','width','height','cover'}
    if not isinstance(item,dict) or set(item)!=required:
        raise ValueError('exact source-bound Robot media message intent required')
    checked=upload_specification(value,policy,connector,item['upload'],redactor)
    upload=checked['intent'];target=checked['target'];receipt=upload_response(item['receipt'],target)
    if receipt['state']!='confirmed':raise PermissionError('confirmed private native upload required before message')
    if any(type(item[key]) is not int for key in ['duration_ms','width','height']):
        raise ValueError('exact native duration and display dimensions required')
    kind=target['kind'];key=receipt['media_id'];cover=item['cover']
    if value['client_secret'] in key:raise PermissionError('private app credential cannot become a media key')
    if kind in {'image','file'}:
        if any(item[field]!=0 for field in ['duration_ms','width','height']) or cover is not None:
            raise ValueError('image/document message cannot acquire unrelated audio/video metadata')
        if kind=='image':message_key='sampleImageMsg';params={'photoURL':key}
        else:
            message_key='sampleFile';params={'mediaId':key,'fileName':target['name'],'fileType':target['name'].rsplit('.',1)[1]}
    else:
        if not 1<=item['duration_ms']<=120020:raise ValueError('bounded native voice/video duration required')
        if kind=='voice':
            if item['width'] or item['height'] or cover is not None:raise ValueError('voice cannot acquire unrelated video metadata')
            message_key='sampleAudio';params={'mediaId':key,'duration':str(item['duration_ms'])}
        else:
            if not 1<=item['width']<=4096 or not 1<=item['height']<=4096:
                raise ValueError('bounded video display dimensions required')
            if not isinstance(cover,dict) or set(cover)!={'upload','receipt'}:
                raise ValueError('separately uploaded source-bound video cover required')
            thumbnail=upload_specification(value,policy,connector,cover['upload'],redactor)
            # Both uploads refer to exactly one source/delivery/grant/attempt.
            if any(thumbnail['intent'][field]!=upload[field] for field in upload if field!='output'):
                raise PermissionError('video cover changed source, delivery or independent owner authority')
            if thumbnail['target']['kind']!='image' or not thumbnail['target']['name'].startswith('cover-'):
                raise PermissionError('private image thumbnail upload required')
            cover_receipt=upload_response(cover['receipt'],thumbnail['target'])
            if cover_receipt['state']!='confirmed' or value['client_secret'] in cover_receipt['media_id']:
                raise PermissionError('confirmed credential-free private video cover key required')
            message_key='sampleVideo';params={'duration':str((item['duration_ms']+999)//1000),'videoMediaId':key,
                'videoType':'mp4','picMediaId':cover_receipt['media_id'],'width':item['width'],'height':item['height']}
    base={key:part for key,part in upload.items() if key!='output'}
    blueprint=reply_specification(value,policy,connector,{**base,'body':'Sealed owner-approved output part.'},redactor)
    media={'msg_key':message_key,'params':params,'proof_sha256':digest(item)}
    return {'blueprint':blueprint,'media':media,'intent':deepcopy(item)}


def payload(media):
    if (not isinstance(media,dict) or set(media)!={'msg_key','params','proof_sha256'}
            or not isinstance(media['msg_key'],str) or media['msg_key'] not in {'sampleImageMsg','sampleFile','sampleAudio','sampleVideo'}
            or not isinstance(media['params'],dict) or not isinstance(media['proof_sha256'],str)):
        raise PermissionError('one reviewed native Robot media template required')
    import re
    if not re.fullmatch('[0-9a-f]{64}',media['proof_sha256']):raise PermissionError('exact immutable media intent proof required')
    expected={'sampleImageMsg':{'photoURL'},'sampleFile':{'mediaId','fileName','fileType'},
        'sampleAudio':{'mediaId','duration'},'sampleVideo':{'duration','videoMediaId','videoType','picMediaId','width','height'}}
    if set(media['params'])!=expected[media['msg_key']]:raise PermissionError('exact native media template parameters required')
    from .gateway_dingtalk_upload_http import MEDIA_ID
    for field in {'photoURL','mediaId','videoMediaId','picMediaId'}&set(media['params']):
        key=media['params'][field]
        if not isinstance(key,str) or not MEDIA_ID.fullmatch(key) or '://' in key:
            raise PermissionError('literal private uploaded media key required; no external URL')
    params=media['params']
    if media['msg_key']=='sampleFile':
        from .gateway_dingtalk_upload_http import FORMATS
        if (not isinstance(params['fileType'],str) or params['fileType'] not in FORMATS['file']
                or not isinstance(params['fileName'],str) or not re.fullmatch(r'result-[0-3]\.'+params['fileType'],params['fileName'])):
            raise PermissionError('fixed path-free native document metadata required')
    if 'duration' in params:
        if (not isinstance(params['duration'],str) or not re.fullmatch('[1-9][0-9]{0,5}',params['duration'])
                or int(params['duration'])>(121 if media['msg_key']=='sampleVideo' else 120020)):
            raise PermissionError('bounded native media duration required')
    if media['msg_key']=='sampleVideo':
        if (params['videoType']!='mp4' or any(type(params[key]) is not int or not 1<=params[key]<=4096 for key in ['width','height'])):
            raise PermissionError('exact bounded native MP4 display metadata required')
    return {'msgKey':media['msg_key'],'msgParam':json.dumps(params,ensure_ascii=False,separators=(',',':'))}


def wire_target(adapter,blueprint,media):
    result=text_target(adapter,blueprint);result['payload'].update(payload(media))
    result['intent_sha256']=digest([result['intent_sha256'],media])
    return result


class MediaReply(Reply):
    def __init__(self,owner,token,target,current,media):
        self.media=deepcopy(media);super().__init__(owner,token,target,current)

    def validate_payload(self,owner,actual):
        expected=payload(self.media)
        params=json.loads(actual['msgParam'],object_pairs_hook=_object,parse_constant=finite)
        if (actual['msgKey']!=expected['msgKey'] or actual['msgParam']!=expected['msgParam']
                or params!=self.media['params']):raise PermissionError('native Robot media payload changed immutable uploaded keys or metadata')
        for value in params.values():
            if isinstance(value,str) and any(secret in value for secret in (owner.value['client_secret'],*owner.tokens)):
                raise PermissionError('private account credentials cannot become Robot media content')
        for field in {'photoURL','mediaId','videoMediaId','picMediaId'}&set(params):owner.register(params[field])
