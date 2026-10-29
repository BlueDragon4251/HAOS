#!/usr/bin/env python3
"""Actual pinned DingTalk SDK models and native pure codecs; no transport auth."""
from copy import deepcopy
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    from haos.gateway_dingtalk_admission import approve,normalize,Refused
    from haos.redaction import Redactor
    import dingtalk_stream
    from plugins.platforms.dingtalk import adapter as native
    expected=json.loads((Path(sys.argv[1])/'runtime/source.json').read_text())['dingtalk_versions']
    assert expected=={'dingtalk-stream':'0.24.3','alibabacloud-dingtalk':'2.2.42'}
    assert {name:version(name) for name in expected}==expected
    assert native.DINGTALK_STREAM_AVAILABLE and native.CARD_SDK_AVAILABLE
    value={'client_id':'ding_private_fixture_app','client_secret':'private-dingtalk-fixture',
        'corp_id':'ding_fixture_corporation','robot_code':'ding_fixture_robot'}
    grant={'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],
        'generation':'a'*64,'since':1,'require_mention':True,
        'allow_media':True,'allow_voice':True,'allow_video':True,'allow_outbound_media':True}
    config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[grant]}
    policy=lambda:PreparedDingTalkPolicy(config)
    now=int(time.time()*1000)
    base={'msgId':'nativeMessage-123','createAt':now-1000,'senderId':grant['sender'],'senderStaffId':'unapproved-staff-alias',
        'senderNick':'Display name is not an identity','isAdmin':True,'conversationId':grant['chat'],'conversationType':'1',
        'chatbotCorpId':value['corp_id'],'senderCorpId':value['corp_id'],'robotCode':value['robot_code'],
        'msgtype':'text','text':{'content':'Approved native goal.'},
        'sessionWebhook':'https://oapi.dingtalk.com/robot/sendBySession?session=private-session-fixture-value','sessionWebhookExpiredTime':now+7200000}
    def project(data,redactor=None):
        raw=json.dumps(data,ensure_ascii=False).encode();approval=approve(policy(),'dingtalk',value,raw)
        return normalize(policy(),'dingtalk',value,raw,approval,redactor or Redactor())
    cases=[]
    # Socket denial is only a codec-purity fixture, never a claimed UID/sandbox proof.
    with patch('socket.socket.connect',side_effect=AssertionError('pure codec attempted a network connection')):
        text=project(base);assert text['envelope']['text']=='Approved native goal.' and text['resources']==[]
        assert text['envelope']['sender']==grant['sender'] and text['native_kind']=='text'
        cases.append('actual_DingTalk_ChatbotMessage_and_pinned_native_text_codec_preserve_canonical_sender_without_staff_display_admin_alias_authority')
        for label,kind,content,expected in [('picture','picture',{'downloadCode':'native-private-image-code'},'image'),
                ('file','file',{'downloadCode':'native-private-document-code','fileName':'report.pdf'},'document'),
                ('image','image',{'downloadCode':'native-private-image-code','fileName':'photo.png'},'image'),
                ('video_file','file',{'downloadCode':'native-private-video-code','fileName':'clip.mp4'},'video')]:
            data={**base,'msgtype':kind,'content':content};data.pop('text')
            result=project(data);assert len(result['resources'])==1 and result['resources'][0]['kind']==expected
            assert result['resources'][0]['code']==content['downloadCode']
            permission='allow_video' if expected=='video' else 'allow_media';grant[permission]=False
            try:project(data)
            except Refused as error:assert error.reason=='unapproved-media'
            else:raise AssertionError('native resource bypassed separate owner permission')
            grant[permission]=True
            cases.append('actual_native_'+label+'_projection_requires_matching_independent_media_permission')
        voice={**base,'msgtype':'audio','content':{'recognition':'DingTalk supplied voice recognition.'}};voice.pop('text')
        result=project(voice);assert result['native_kind']=='voice' and result['resources']==[] and result['envelope']['text']=='DingTalk supplied voice recognition.'
        grant['allow_voice']=False
        try:project(voice)
        except Refused as error:assert error.reason=='unapproved-media'
        else:raise AssertionError('vendor transcript bypassed voice consent')
        grant['allow_voice']=True
        cases.append('actual_native_vendor_voice_transcript_stays_voice_and_requires_voice_consent_without_claiming_local_ASR')
        rich={**base,'msgtype':'richText','content':{'richText':[{'type':'text','text':'Look at the attachment.'},
            {'type':'picture','downloadCode':'native-private-rich-image'}]}};rich.pop('text')
        result=project(rich);assert result['envelope']['text']=='Look at the attachment.' and result['resources'][0]['kind']=='image'
        cases.append('actual_native_rich_text_and_resource_projection_keep_the_same_source_without_remote_resource_resolution')
        alias=deepcopy(rich);alias['content']['richText'][1]={'type':'picture','pictureDownloadCode':'native-private-rich-image'}
        result=project(alias);assert result['resources']==project(rich)['resources']
        assert 'downloadCode' not in alias['content']['richText'][1]
        cases.append('native_resolver_picture_alias_is_canonicalized_for_actual_SDK_codec_without_mutating_original_bytes')
        ambiguous=deepcopy(alias);ambiguous['content']['richText'][1]['downloadCode']='different-private-resource-code'
        try:project(ambiguous)
        except Refused as error:assert error.reason=='ambiguous-resource'
        else:raise AssertionError('conflicting native resource aliases admitted')
        cases.append('conflicting_native_download_aliases_fail_before_any_resource_resolution')
        video=deepcopy(rich);video['content']['richText'][1]['type']='video'
        grant['allow_video']=False
        try:project(video)
        except Refused as error:assert error.reason=='unapproved-media'
        else:raise AssertionError('native video mislabeled as file bypassed video consent')
        grant['allow_video']=True
        assert project(video)['resources'][0]['kind']=='video'
        cases.append('raw_native_rich_video_requires_video_consent_even_when_pinned_codec_labels_it_document')
        for secret in [value['client_secret'],base['sessionWebhook'],'private-session-fixture-value']:
            reflected={**base,'text':{'content':secret}}
            try:project(reflected)
            except Refused as error:assert error.reason=='private-reflection'
            else:raise AssertionError('private app or reply capability became an agent goal')
        cases.append('actual_native_text_projection_refuses_app_secret_full_session_URL_and_decoded_reply_capability_reflection')
        changed=deepcopy(base);changed['senderId']=base['senderStaffId']
        try:project(changed)
        except Refused:pass
        else:raise AssertionError('SDK staff alias widened owner authority')
        cases.append('SDK_staff_alias_does_not_substitute_for_exact_independently_approved_sender_ID')
    report={'passed':len(cases),'cases':cases,'actual_pinned_DingTalk_SDK_and_native_codecs':True,
        'transport_authentication_owner_publication_and_socket_denial_are_fixtures':True,
        'native_vendor_voice_transcript_is_fixture_no_local_ASR':True,'public_dingtalk_enabled':False,
        'network_resources_missions_external_messages_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
