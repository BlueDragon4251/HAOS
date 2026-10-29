"""Reply capabilities refuse route/body changes before optional SDK/network use."""
from types import SimpleNamespace
import pytest
from haos.gateway_feishu import DOMAINS
from haos.gateway_feishu_http import Failure
from haos.gateway_feishu_reply_http import ReplyBoundary,target
from haos.redaction import Redactor
from test_gateway_feishu import account


def exact():return {'chat_id':'oc_'+'c'*32,'reply_to':'om_'+'f'*32,'thread_id':'','msg_type':'text','content':'{"text":"Approved reply."}','uuid':'a'*32}


@pytest.mark.parametrize('change',[{'reply_to':'../other'},{'chat_id':'ou_'+'c'*32},{'thread_id':'om_'+'f'*32},
    {'uuid':'random'},{'msg_type':[]},{'msg_type':'interactive'},{'content':'{"text":true}'},{'content':'{"text":"one","text":"two"}'},
    {'content':'{"text":"one","extra":1e999}'},{'content':'[]'},{'extra':'unapproved'},
])
def test_only_exact_native_text_post_reply_target_can_form_capability(change):
    with pytest.raises(Failure):target({**exact(),**change})


def test_reply_capability_cannot_be_reused_for_bot_lookup_or_native_create():
    value=account();boundary=ReplyBoundary(value,lambda:None,lambda *_:True,Redactor())
    config=SimpleNamespace(app_id=value['app_id'],app_secret=value['app_secret'],domain=DOMAINS[value['domain']])
    with boundary.operation(config,'reply',exact()) as operation:
        calls=[]
        for method,path in [('GET','/open-apis/bot/v3/info'),('POST','/open-apis/im/v1/messages'),
            ('POST','/open-apis/im/v1/messages/om_'+'e'*32+'/reply')]:
            with pytest.raises(Failure):boundary.request(lambda *_a,**_k:calls.append(True),method,boundary.origin+path)
        assert calls==[] and not operation['write_started']
