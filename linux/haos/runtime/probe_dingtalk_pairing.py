#!/usr/bin/env python3
"""Actual frozen ChatbotMessage parser, local observation and explicit grant tests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    from haos.gateway_dingtalk_pairing import candidate,Candidates
    from haos.gateway_dingtalk_admission import approve,Refused
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    value={'client_id':'ding_fixture_app','client_secret':'private-dingtalk-observation-fixture',
        'corp_id':'ding_fixture_corp','robot_code':'ding_fixture_robot'}
    now=int(time.time()*1000);request={'nonce':'a'*32,'since':now-1000,'until':now+60000}
    body={'msgId':'actual-native-observation','createAt':now,'senderId':'$:LWCP_v1:$opaque-owner',
        'conversationId':'cidExactConversation/+=','conversationType':'1','chatbotCorpId':value['corp_id'],
        'senderCorpId':value['corp_id'],'robotCode':value['robot_code'],'msgtype':'text',
        'text':{'content':'HAOS koppeln '+request['nonce']},'sessionWebhook':'private route must never be inventoried',
        'senderStaffId':'staff alias must never grant authority','senderNick':'display name is not authority'}
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-pairing-codec-') as temp:
        inbox=NativeInbox(Path(temp)/'native.db',Redactor());store=Candidates(inbox)
        for kind in ['1',1,'2',2]:
            data={**body,'conversationType':kind,'isInAtList':True};raw=json.dumps(data).encode()
            item=candidate(value,request,raw);assert item['sender']==body['senderId'] and item['chat']==body['conversationId']
            assert item['authorized'] is False and not item['mission_created'] and not item['message_sent']
            assert all(thing not in json.dumps(item) for thing in [value['client_secret'],body['sessionWebhook'],body['senderStaffId'],body['senderNick']])
            cases.append('native_identity_'+str(type(kind).__name__)+'_'+str(kind))
        for index,change in enumerate([
            {'senderCorpId':'another_corp'},{'chatbotCorpId':'another_corp'},{'robotCode':'another_robot'},
            {'senderId':value['robot_code']},{'senderIsRobot':True},{'senderIsRobot':0},{'senderId':'https://alias.invalid'},
            {'senderId':'all'},{'conversationId':'all'},{'msgId':'..'},{'conversationType':True},{'conversationType':3},
            {'conversationType':'2','isInAtList':False},{'threadId':'unapproved-thread'},
            {'createAt':request['since']},{'createAt':request['until']+1},{'createAt':False},
        ]):
            try:candidate(value,request,json.dumps({**body,**change}).encode())
            except (ValueError,PermissionError):pass
            else:raise AssertionError('malformed or unrelated candidate accepted')
            cases.append('native_reject_'+str(index))
        for data in [{**body,'text':{'content':'HAOS koppeln '+'b'*32}},{**body,'msgtype':'picture'},
                     {**body,'text':{'content':'ordinary message'}},{**body,'text':None}]:
            assert candidate(value,request,json.dumps(data).encode()) is None;cases.append('nonchallenge_'+str(len(cases)))
        raw=json.dumps(body).encode();item=candidate(value,request,raw);receipt=store.retain('dingtalk',item)
        assert receipt==store.retain('dingtalk',item)
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
        config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[]}
        try:approve(PreparedDingTalkPolicy(config),'dingtalk',value,raw)
        except Refused:pass
        else:raise AssertionError('observation implicitly authorized sender')
        cases.append('retained_native_candidate_is_not_authorization_or_mission')
        config['bindings']=[{'id':'owner','connector':'dingtalk','sender':item['sender'],'chat':item['chat'],
            'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,
            'since':now+1}]
        try:approve(PreparedDingTalkPolicy(config),'dingtalk',value,raw)
        except Refused:pass
        else:raise AssertionError('old challenge became a newly granted mission')
        cases.append('fresh_explicit_grant_does_not_replay_prior_observation')
        inbox.close()
    receipt={'upstream':'f97608f178d1ffeca59860195ab7da295f7c8e5f','cases':cases,
        'scope':'actual frozen native SDK parser and local SQLite/policy; no transport or live DingTalk account',
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'cases':len(cases),'live_delivery_verified':False}))


if __name__=='__main__':main()
