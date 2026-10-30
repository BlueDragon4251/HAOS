from copy import deepcopy
import hashlib
import json
import time
import pytest
from haos.gateway_feishu import PreparedFeishuPolicy,scope
from haos.gateway_feishu_admission import approve,Refused,MAX_EVENT
from test_gateway_feishu import account,binding


def fixture():
    value=account();grant=binding();stamp=int(time.time()*1000)-1000
    event={'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1',
        'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':str(stamp)},
        'event':{'sender':{'sender_id':{'open_id':grant['sender'],'user_id':'unapproved-alias'},
            'sender_type':'user','tenant_key':value['tenant_key']},'message':{
            'message_id':'om_'+'f'*32,'create_time':str(stamp),'chat_id':grant['chat'],'chat_type':'p2p',
            'message_type':'text','content':json.dumps({'text':'Actual isolated source goal.'}),
            'root_id':'om_'+'a'*32,'parent_id':'om_'+'a'*32}}}
    policy={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[grant]}
    return value,policy,event


def encoded(value):return json.dumps(value,ensure_ascii=False,allow_nan=False).encode()


def test_projection_binds_exact_platform_owner_route_before_any_native_content_or_I_O():
    value,config,event=fixture();raw=encoded(event);before=deepcopy(event)
    result=approve(PreparedFeishuPolicy(config),'feishu',value,raw)
    assert result['raw_sha256']==hashlib.sha256(raw).hexdigest() and event==before
    assert result['envelope']['sender']==config['bindings'][0]['sender']
    assert result['envelope']['scope']==scope(value) and result['envelope']['thread']==''
    assert result['envelope']['text']=='' and result['envelope']['is_bot'] is False
    assert result['received_at']==int(event['event']['message']['create_time'])/1000
    assert value['app_secret'] not in json.dumps(result)


@pytest.mark.parametrize('where,field,new,reason',[
    ('header','app_id','cli_other_application','wrong-application'),
    ('header','tenant_key','different_tenant','wrong-tenant'),
    ('sender','tenant_key','different_tenant','wrong-tenant'),
    ('sender','sender_type','app','self-or-automated'),('sender','sender_type','bot','self-or-automated'),
    ('header','event_type','card.action.trigger','unsupported-event'),
    ('header','event_type','drive.notice.comment_add_v1','unsupported-event'),
    ('message','chat_id','oc_'+'d'*32,'unapproved-route'),
    ('message','thread_id','omt_'+'d'*32,'unapproved-route'),
    ('message','thread_id',False,'unsupported-content'),
    ('message','message_id','../../owner','unsupported-content'),
    ('message','message_type','plugin-command','unsupported-content'),
    ('message','chat_type','broadcast','unsupported-content'),
    ('message','mentions',False,'unsupported-content'),
    ('message','content','{"text":true}','unsupported-content'),
    ('message','content','{"text":"one","text":"two"}','unsupported-content'),
    ('message','content','{"text":"one","extra":1e999}','unsupported-content'),
])
def test_projection_refuses_cross_app_tenant_chat_thread_bot_plugin_and_ambiguous_content(where,field,new,reason):
    value,config,event=fixture()
    target=event['header'] if where=='header' else event['event'][where]
    target[field]=new
    with pytest.raises(Refused) as error:approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))
    assert error.value.reason==reason


@pytest.mark.parametrize('source',[None,{'user_id':'ou_'+'b'*32},{'union_id':'ou_'+'b'*32},{'open_id':'Display Name'},{'open_id':'ou_'+'a'*32}])
def test_sender_aliases_never_gain_open_id_authority_and_own_bot_is_denied(source):
    value,config,event=fixture();event['event']['sender']['sender_id']=source
    with pytest.raises(Refused):approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))


@pytest.mark.parametrize('field',['header','message'])
@pytest.mark.parametrize('stamp',[True,False,0,-1,123.5,' 123','0123','nan','1e12',2**53])
def test_time_is_exact_bounded_milliseconds_without_boolean_or_float_coercion(field,stamp):
    value,config,event=fixture();target=event['header'] if field=='header' else event['event']['message'];target['create_time']=stamp
    with pytest.raises(Refused) as error:approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))
    assert error.value.reason=='invalid-time'


@pytest.mark.parametrize('field',['header','message'])
@pytest.mark.parametrize('direction',['past','future'])
def test_grant_time_and_future_bound_apply_to_both_message_and_platform_event(field,direction):
    value,config,event=fixture();target=event['header'] if field=='header' else event['event']['message']
    target['create_time']=str(config['bindings'][0]['since'] if direction=='past' else int(time.time()*1000)+600000)
    with pytest.raises(Refused) as error:approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))
    assert error.value.reason=='pre-grant'


def test_group_mention_needs_exact_bot_open_id_metadata_not_text_name_alias_or_all():
    value,config,event=fixture();message=event['event']['message'];message['chat_type']='group'
    message['content']=json.dumps({'text':'@FixtureBot please act'})
    for mentions in [[],[{'id':{'user_id':value['bot_open_id']},'name':'FixtureBot'}],[{'key':'@_all'}]]:
        message['mentions']=mentions
        with pytest.raises(Refused) as error:approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))
        assert error.value.reason=='mention-required'
    message['mentions']=[{'id':{'open_id':value['bot_open_id']},'key':'@_user_1','name':'FixtureBot'}]
    assert approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))['envelope']['chat']==message['chat_id']


def test_topic_uses_only_native_thread_id_and_cannot_inherit_quoted_root_authority():
    value,config,event=fixture();thread='omt_'+'d'*32;config['bindings'][0]['thread']=thread
    with pytest.raises(Refused):approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))
    event['event']['message']['thread_id']=thread
    assert approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))['envelope']['thread']==thread
    event['event']['message']['root_id']='om_'+'c'*32
    assert approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))['envelope']['thread']==thread


def test_json_duplicate_nonfinite_deep_oversized_and_surrogate_events_are_refused():
    value,config,event=fixture();policy=PreparedFeishuPolicy(config)
    for raw in [b'{"schema":"2.0","schema":"2.0"}',b'{"value":NaN}',b'{"value":1e999}',
            b'{"bad":"\\ud800"}',b'{"\\ud800":1}',b'['*100+b'0'+b']'*100,b' '*MAX_EVENT+b'{}']:
        with pytest.raises(Refused):approve(policy,'feishu',value,raw)


def test_explicit_group_mention_opt_out_still_requires_exact_current_sender_chat_scope_and_epoch():
    value,config,event=fixture();config['bindings'][0]['require_mention']=False;event['event']['message']['chat_type']='group'
    assert approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))['binding_id']=='owner'
    config['bindings']=[]
    with pytest.raises(Refused):approve(PreparedFeishuPolicy(config),'feishu',value,encoded(event))
