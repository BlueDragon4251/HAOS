"""Closed resource capabilities without requiring optional SDK imports."""
from types import SimpleNamespace
import pytest
from haos.gateway_feishu_resource_http import ResourceBoundary,target
from haos.gateway_feishu_http import Failure
from haos.redaction import Redactor
from test_gateway_feishu import account


def exact():return {'message_id':'om_'+'a'*32,'file_key':'img_v3_0000000000000000','types':['image']}


@pytest.mark.parametrize('types',[['image'],['file'],['audio','file'],['media','file']])
def test_resource_capability_matches_only_native_single_read_or_same_key_fallback(types):
    value={**exact(),'types':types};assert target(value)==value


@pytest.mark.parametrize('change',[{'message_id':'other'},{'file_key':'../secret'},{'file_key':'a?type=file'},
    {'file_key':'a/b'},{'types':['file','image']},{'types':['audio']},{'types':['image','file']},
    {'types':[]},{'types':True},{'url':'https://other.invalid'},{'file_key':None}])
def test_resource_refuses_paths_urls_and_broader_native_retry_authority(change):
    with pytest.raises(Failure):target({**exact(),**change})


@pytest.mark.parametrize('method,suffix,kwargs',[
    ('POST','/open-apis/im/v1/messages',{}),
    ('GET','/open-apis/im/v1/messages/om_'+'b'*32+'/resources/img_v3_0000000000000000',{'params':[('type','image')]}),
    ('GET','/open-apis/im/v1/messages/om_'+'a'*32+'/resources/img_v3_0000000000000000',{'params':[('type','file')]}),
    ('GET','/open-apis/im/v1/messages/om_'+'a'*32+'/resources/img_v3_0000000000000000',{'params':[('type','image'),('type','image')]}),
    ('GET','/open-apis/im/v1/messages/om_'+'a'*32+'/resources/img_v3_0000000000000000',{'params':[('type','image')],'verify':False}),
])
def test_resource_request_refused_before_network_for_changed_route_query_or_options(method,suffix,kwargs):
    value=account();boundary=ResourceBoundary(value,lambda:None,lambda *_:True,Redactor([value['app_secret']]))
    conf=SimpleNamespace(app_id=value['app_id'],app_secret=value['app_secret'],domain=boundary.origin)
    calls=[]
    with boundary.operation(conf,'resource',exact()):
        with pytest.raises(Failure):boundary.request(lambda *_a,**_k:calls.append(True),method,boundary.origin+suffix,**kwargs)
    assert not calls


def test_decoded_audio_file_cannot_bypass_separate_voice_consent():
    from haos.gateway_feishu_resource import classify
    spec={'resource':{'type':'file','permissions':['allow_media']},'binding':{'allow_media':True}}
    with pytest.raises(PermissionError):classify(spec,'audio/ogg',b'opaque sound')
    spec['binding']['allow_voice']=True
    assert classify(spec,'audio/ogg',b'opaque sound')['kind']=='voice'


def test_native_video_file_selector_does_not_require_document_consent_or_grant_it():
    from haos.gateway_feishu_resource import classify
    spec={'resource':{'type':'file','permissions':['allow_video']},'binding':{'allow_video':True}}
    data=(16).to_bytes(4,'big')+b'ftypisom'+b'\x00'*4
    assert classify(spec,'video/mp4',data)['kind']=='video'
    spec['binding']={'allow_media':True}
    with pytest.raises(PermissionError):classify(spec,'video/mp4',data)


def test_private_binary_result_is_bound_to_original_request_and_preserves_exact_bytes():
    import base64
    from haos.gateway import digest
    from haos.gateway_media import describe
    from haos.gateway_feishu_resource import response
    item={'source_sha256':'a'*64,'resource_index':0};data=b'owner attachment'
    result={'data_base64':base64.b64encode(data).decode(),'descriptor':describe(data,'document'),
        'mime':'application/octet-stream','request_sha256':digest(item)}
    assert response(result,item,account())['data']==data
    for change in [{'request_sha256':'b'*64},{'data_base64':'!!!!'},{'mime':'bad mime'},
            {'descriptor':{**result['descriptor'],'sha256':'0'*64}},{'filename':'/private/path'}]:
        with pytest.raises((ValueError,TypeError)):response({**result,**change},item,account())
    with pytest.raises(ValueError):response(result,{**item,'resource_index':1},account())
