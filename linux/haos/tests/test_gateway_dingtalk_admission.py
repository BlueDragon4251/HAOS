import json
import time
from copy import deepcopy
import pytest
from haos.gateway_dingtalk import PreparedDingTalkPolicy
from haos.gateway_dingtalk_admission import approve,parse,session_webhook,Refused
from test_gateway_dingtalk import account,binding


def event():return {'msgId':'nativeMessage-123','createAt':int(time.time()*1000)-1000,'senderId':binding()['sender'],
    'senderStaffId':'unapproved-staff-alias','senderNick':'Owner display name','isAdmin':True,
    'conversationId':binding()['chat'],'conversationType':'1','chatbotCorpId':account()['corp_id'],
    'senderCorpId':account()['corp_id'],'robotCode':account()['robot_code'],'msgtype':'text','text':{'content':'Approved goal.'},
    'sessionWebhook':'https://oapi.dingtalk.com/robot/sendBySession?session=private-session-fixture-value',
    'sessionWebhookExpiredTime':int(time.time()*1000)+7200000}


def policy():return PreparedDingTalkPolicy({'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[binding()]})


def raw(value):return json.dumps(value).encode()


def test_approval_matches_native_ids_not_staff_display_admin_or_reply_URL_authority():
    data=event();approval=approve(policy(),'dingtalk',account(),raw(data))
    assert approval['envelope']['sender']==binding()['sender'] and approval['envelope']['text']==''
    assert approval['binding_id']=='owner' and 'isAdmin' not in approval and 'sessionWebhook' not in approval
    for field in ['senderNick','senderStaffId']:
        changed={**data,'senderId':data[field]}
        with pytest.raises(Refused):approve(policy(),'dingtalk',account(),raw(changed))


@pytest.mark.parametrize('change',[{'senderId':'unknown-user'},{'conversationId':'other-chat'},
    {'senderCorpId':'ding_other_corp'},{'chatbotCorpId':'ding_other_corp'},{'robotCode':'ding_other_robot'},
    {'createAt':123},{'createAt':True},{'createAt':None},{'msgId':''},{'conversationType':True},
    {'threadId':'unapproved-topic'},{'msgtype':'synthetic-plugin'},{'senderIsRobot':True},
    {'sessionWebhook':'https://other.invalid/robot/send?access_token=private-test-token'},
    {'sessionWebhookExpiredTime':0},{'sessionWebhookExpiredTime':True}])
def test_unknown_untimed_cross_account_or_non_native_input_never_reaches_optional_SDK(change):
    with pytest.raises(Refused):approve(policy(),'dingtalk',account(),raw({**event(),**change}))


def test_group_requires_literal_native_bot_mention_and_voice_requires_separate_permission():
    data={**event(),'conversationType':2,'isInAtList':True}
    assert approve(policy(),'dingtalk',account(),raw(data))['binding_id']=='owner'
    for value in [False,1,'true',None]:
        with pytest.raises(Refused):approve(policy(),'dingtalk',account(),raw({**data,'isInAtList':value}))
    with pytest.raises(Refused):approve(policy(),'dingtalk',account(),raw({**event(),'msgtype':'audio','content':{'recognition':'text is still voice'}}))


@pytest.mark.parametrize('data',[b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":"\\ud800"}',b'[]',b'x'*(1024*1024+1)])
def test_strict_bounded_JSON_does_not_accept_duplicates_nonfinite_bad_unicode_or_oversized_events(data):
    with pytest.raises(Refused):parse(data)


@pytest.mark.parametrize('url',['http://oapi.dingtalk.com/robot/send?access_token=private-test-token',
    'https://oapi.dingtalk.com.attacker.invalid/robot/send?access_token=private-test-token',
    'https://user:secret@oapi.dingtalk.com/robot/send?access_token=private-test-token',
    'https://oapi.dingtalk.com/robot/send?access_token=private-test-token&access_token=other-private-token',
    'https://oapi.dingtalk.com/robot/send?access_token=private-test-token#fragment',
    'https://oapi.dingtalk.com/private?access_token=private-test-token'])
def test_source_reply_capability_is_exact_vendor_HTTPS_without_credentials_redirects_or_extra_paths(url):
    with pytest.raises(Refused):session_webhook(url)
