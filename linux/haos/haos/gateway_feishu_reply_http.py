"""One exact approved native reply over the existing bounded private SDK TLS path."""
from contextlib import contextmanager
from copy import deepcopy
import json
import re

from .gateway_feishu import CHAT_ID,MESSAGE_ID,THREAD_ID
from .gateway_feishu_admission import bounded,Refused
from .gateway_feishu_http import Boundary,Failure,finite
from .gateway_line_ingress import _object


def target(value):
    if not isinstance(value,dict) or set(value)!={'chat_id','reply_to','thread_id','msg_type','content','uuid'}:
        raise Failure('unapproved-operation')
    for key,pattern in [('chat_id',CHAT_ID),('reply_to',MESSAGE_ID)]:
        if not isinstance(value[key],str) or not pattern.fullmatch(value[key]):raise Failure('unapproved-operation')
    if (not isinstance(value['thread_id'],str) or value['thread_id'] and not THREAD_ID.fullmatch(value['thread_id'])
            or not isinstance(value['msg_type'],str) or value['msg_type'] not in {'text','post'} or not isinstance(value['content'],str)
            or not 1<=len(value['content'].encode())<=128000 or not isinstance(value['uuid'],str)
            or not re.fullmatch('[0-9a-f]{32}',value['uuid'])):raise Failure('unapproved-operation')
    try:body=json.loads(value['content'],object_pairs_hook=_object,parse_constant=finite);bounded(body)
    except (ValueError,UnicodeError,RecursionError,Refused):raise Failure('unapproved-operation') from None
    if not isinstance(body,dict):raise Failure('unapproved-operation')
    if value['msg_type']=='text' and (set(body)!={'text'} or not isinstance(body['text'],str)):
        raise Failure('unapproved-operation')
    return deepcopy(value)


class ReplyBoundary(Boundary):
    @contextmanager
    def operation(self,config,purpose,blueprint):
        if purpose!='reply':raise Failure('unapproved-operation')
        exact=target(blueprint)
        with self._operation(config,'reply',exact) as state:
            state['write_started']=False
            yield state

    def api_request(self,state,method,path,data):
        exact=target(state['target'])
        if state.get('write_started') or method!='POST' or path!='/open-apis/im/v1/messages/'+exact['reply_to']+'/reply':
            raise Failure('unapproved-operation')
        if not isinstance(data,bytes) or not 1<=len(data)<=262144:raise Failure('changed-reply')
        try:body=json.loads(data.decode(),object_pairs_hook=_object,parse_constant=finite);bounded(body)
        except (ValueError,UnicodeError,RecursionError,Refused):raise Failure('changed-reply') from None
        if body!={'msg_type':exact['msg_type'],'content':exact['content'],
                'reply_in_thread':bool(exact['thread_id']),'uuid':exact['uuid']}:raise Failure('changed-reply')
        return True

    def api_response(self,state,body):
        state['reply_response']=deepcopy(body)
