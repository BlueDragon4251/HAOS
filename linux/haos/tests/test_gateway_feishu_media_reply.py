"""Closed media-reply body/route contracts without optional SDK imports."""
import json
from types import SimpleNamespace
import pytest
from haos.gateway_feishu_media_reply_http import MediaReplyBoundary,target
from haos.gateway_feishu_http import Failure
from haos.redaction import Redactor
from test_gateway_feishu import account


def exact():return {'chat_id':'oc_'+'c'*32,'reply_to':'om_'+'f'*32,'thread_id':'',
    'msg_type':'file','content':json.dumps({'file_key':'file_v3_0000000000000000'}),'uuid':'a'*32}


@pytest.mark.parametrize('change',[{'msg_type':'external'},{'msg_type':[]},{'reply_to':'*'},{'thread_id':'*'},
    {'content':'{"file_key":"one","file_key":"two"}'},{'uuid':'random-uuid'},{'url':'https://other.invalid'}])
def test_media_reply_rejects_ambiguous_payload_route_and_extra_capabilities(change):
    with pytest.raises((ValueError,PermissionError)):target({**exact(),**change})


def test_explicit_upload_key_is_allowed_but_private_authentication_cannot_enter_reply_body():
    value=account();redactor=Redactor([value['app_secret']])
    boundary=MediaReplyBoundary(value,lambda:None,lambda *_:True,redactor)
    conf=SimpleNamespace(app_id=value['app_id'],app_secret=value['app_secret'],domain=boundary.origin)
    wanted=exact();boundary.remember('file_v3_0000000000000000')
    def wire(content):return json.dumps({'msg_type':'file','content':content,'reply_in_thread':False,'uuid':wanted['uuid']}).encode()
    with boundary.operation(conf,'media-reply',wanted) as state:
        assert boundary.api_request(state,'POST','/open-apis/im/v1/messages/'+wanted['reply_to']+'/reply',wire(wanted['content'])) is True
        with pytest.raises(Failure) as refused:
            boundary.api_request(state,'POST','/open-apis/im/v1/messages/'+wanted['reply_to']+'/reply',wire(value['app_secret']))
        assert refused.value.kind=='credential-reflection'
