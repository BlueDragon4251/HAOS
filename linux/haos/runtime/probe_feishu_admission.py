#!/usr/bin/env python3
"""Actual pinned Feishu model/normalizer after independent HAOS source approval."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_admission import approve,normalize,Refused
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.redaction import Redactor
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-codec-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    grant={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}
    config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[grant]}
    stamp=str(int(time.time()*1000)-1000)
    event={'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1',
        'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
        'event':{'sender':{'sender_id':{'open_id':grant['sender'],'user_id':'other-alias'},'sender_type':'user','tenant_key':value['tenant_key']},
            'message':{'message_id':'om_'+'f'*32,'create_time':stamp,'chat_id':grant['chat'],'chat_type':'p2p','message_type':'text',
                'content':json.dumps({'text':'Actual native text: ä 🤖'})}}}
    def raw(item):return json.dumps(item,ensure_ascii=False).encode()
    redactor=Redactor([value['app_secret']]);cases=[]
    image_key='img_v3_'+'0'*32
    def decode(item,configured=None):
        policy=PreparedFeishuPolicy(config if configured is None else configured);data=raw(item)
        approval=approve(policy,'feishu',value,data)
        return normalize(policy,'feishu',value,data,approval,redactor)
    def refused(item,reason,configured=None):
        try:decode(item,configured)
        except Refused as error:assert error.reason==reason
        else:raise AssertionError('unapproved native content accepted')
    with tempfile.TemporaryDirectory(prefix='haos-feishu-native-admission-') as td:
        with private_scope(Path(td),{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu import adapter as native
            assert native._load_lark_oapi()
            before=sorted(str(path.relative_to(td)) for path in Path(td).rglob('*'))
            result=decode(event);assert result['envelope']['text']=='Actual native text: ä 🤖' and result['resources']==[]
            cases.append('actual_pinned_Lark_model_and_Hermes_normalizer_preserve_approved_UTF8_text')
            mentioned=deepcopy(event);message=mentioned['event']['message'];message['chat_type']='group'
            message['mentions']=[{'key':'@_user_1','id':{'open_id':value['bot_open_id']},'name':'HAOS'}]
            message['content']=json.dumps({'text':'@_user_1 Inspect this harmless fixture.'})
            assert decode(mentioned)['envelope']['text']=='Inspect this harmless fixture.'
            message['content']=json.dumps({'text':'@_user_1 /status fixture-mission'})
            assert decode(mentioned)['envelope']['text']=='/status fixture-mission'
            cases.append('native_exact_self_mention_stripping_preserves_body_commands_without_name_based_authorization')
            post=deepcopy(event);message=post['event']['message'];message['message_type']='post'
            message['content']=json.dumps({'zh_cn':{'title':'Report','content':[[{'tag':'text','text':'bold','style':{'bold':True}}],
                [{'tag':'code_block','language':'python','text':'print(1)'}]]}})
            text=decode(post)['envelope']['text'];assert '**bold**' in text and 'print(1)' in text and 'Report' in text
            cases.append('actual_native_rich_post_markdown_and_code_codec_runs_after_independent_owner_route_approval')
            message['content']=json.dumps({'zh_cn':{'title':'Image','content':[[{'tag':'img','image_key':image_key}]]}})
            refused(post,'media-not-approved')
            approved=deepcopy(config);approved['bindings'][0]['allow_media']=True
            assert decode(post,approved)['resources']==[{'key':image_key,'type':'image','name':'','permissions':['allow_media']}]
            cases.append('native_post_hidden_images_require_separate_media_consent_before_any_resource_download')
            file=deepcopy(event);message=file['event']['message'];message['message_type']='file'
            message['content']=json.dumps({'file_key':'file_v3_fixture','file_name':'source.txt'})
            refused(file,'media-not-approved');result=decode(file,approved)
            assert result['envelope']['text']=='[Feishu attachment]' and result['resources']==[{'key':'file_v3_fixture','type':'file','name':'source.txt','permissions':['allow_media']}]
            cases.append('native_document_descriptor_is_retained_as_a_capability_manifest_without_opening_a_path')
            voice=deepcopy(file);voice['event']['message']['message_type']='audio'
            refused(voice,'media-not-approved',approved)
            voice_config=deepcopy(config);voice_config['bindings'][0]['allow_voice']=True
            assert decode(voice,voice_config)['resources'][0]['type']=='audio'
            cases.append('native_audio_manifest_requires_voice_consent_independently_of_document_consent')
            video=deepcopy(file);video['event']['message']['message_type']='media'
            refused(video,'media-not-approved',approved)
            video_config=deepcopy(config);video_config['bindings'][0]['allow_video']=True
            resource=decode(video,video_config)['resources'][0]
            assert resource['type']=='file' and resource['permissions']==['allow_video']
            cases.append('native_video_manifest_requires_video_consent_independently_of_document_consent')
            for tag in ['media','video']:
                post['event']['message']['content']=json.dumps({'zh_cn':{'content':[[{'tag':tag,'file_key':'file_v3_video','file_name':'clip.mp4'}]]}})
                refused(post,'media-not-approved',approved)
                assert decode(post,video_config)['resources'][0]['permissions']==['allow_video']
            cases.append('native_post_media_and_video_tags_cannot_gain_video_authority_from_generic_file_selectors')
            post['event']['message']['content']=json.dumps({'zh_cn':{'content':[[{'tag':'media','file_key':'file_v3_mixed'},
                {'tag':'file','file_key':'file_v3_mixed'}]]}})
            refused(post,'media-not-approved',approved);refused(post,'media-not-approved',video_config)
            both=deepcopy(video_config);both['bindings'][0]['allow_media']=True
            assert decode(post,both)['resources'][0]['permissions']==['allow_media','allow_video']
            cases.append('same_key_with_multiple_native_post_kinds_requires_every_separate_owner_permission')

            message['content']=json.dumps({'file_key':'../../owner','file_name':'source.txt'})
            refused(file,'unsupported-content',approved)
            cases.append('native_file_key_cannot_become_an_arbitrary_API_route_or_host_path')
            post['event']['message']['content']=json.dumps({'zh_cn':{'content':[[{'tag':'img','image_key':'img_v3_'+str(index)} for index in range(5)]]}})
            refused(post,'unsupported-content',approved)
            cases.append('actual_native_resource_manifest_is_bounded_before_any_resource_fetch')
            reflected=deepcopy(event);reflected['event']['message']['content']=json.dumps({'text':value['app_secret']})
            refused(reflected,'credential-reflection')
            cases.append('private_account_secret_reflection_is_refused_before_agent_ingress')
            policy=PreparedFeishuPolicy(config);approval=approve(policy,'feishu',value,raw(event));changed=deepcopy(event)
            changed['event']['message']['content']=json.dumps({'text':'different body'})
            try:normalize(policy,'feishu',value,raw(changed),approval,redactor)
            except Refused as error:assert error.reason=='changed-source'
            else:raise AssertionError('changed captured source accepted')
            revoked=deepcopy(config);revoked['bindings']=[]
            refused(event,'unapproved-route',revoked)
            cases.append('raw_body_change_and_withdrawn_owner_route_cannot_reuse_old_native_approval')
            assert sorted(str(path.relative_to(td)) for path in Path(td).rglob('*'))==before
            cases.append('pure_native_decode_and_manifest_validation_create_no_local_media_or_credential_files')
    report={'passed':len(cases),'cases':cases,'actual_pinned_Hermes_normalizer_and_Lark_models':True,
        'transport_authentication_and_input_events_are_fixtures':True,'resource_downloads_or_agent_missions':False,
        'public_feishu_enabled':False,'live_accounts_external_messages_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
