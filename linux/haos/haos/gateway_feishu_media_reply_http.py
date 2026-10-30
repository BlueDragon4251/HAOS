"""One exact native media reply, using a separately confirmed private upload key."""
from contextlib import contextmanager
import json

from .gateway_feishu_http import Boundary,Failure,finite
from .gateway_feishu_reply_http import target as reply_target
from .gateway_feishu_admission import bounded,Refused
from .gateway_line_ingress import _object


def target(value):
    if not isinstance(value,dict) or not isinstance(value.get('msg_type'),str) or value.get('msg_type') not in {'post','image','file','audio','media'}:
        raise Failure('unapproved-operation')
    checked=reply_target({**value,'msg_type':'post'});checked['msg_type']=value['msg_type'];return checked


class MediaReplyBoundary(Boundary):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.credential_secrets=tuple(self.redactor.secrets)

    @contextmanager
    def operation(self,config,purpose,blueprint):
        if purpose!='media-reply':raise Failure('unapproved-operation')
        with self._operation(config,purpose,target(blueprint)) as state:
            state['write_started']=False
            yield state

    def api_request(self,state,method,path,data):
        exact=target(state['target'])
        if (state.get('write_started') or method!='POST' or path!='/open-apis/im/v1/messages/'+exact['reply_to']+'/reply'
                or not isinstance(data,bytes) or not 1<=len(data)<=262144):raise Failure('unapproved-operation')
        if any(secret.encode() in data for secret in [*self.credential_secrets,*self.tokens]):raise Failure('credential-reflection')
        try:body=json.loads(data.decode(),object_pairs_hook=_object,parse_constant=finite);bounded(body)
        except (ValueError,UnicodeError,RecursionError,Refused):raise Failure('changed-reply') from None
        if body!={'msg_type':exact['msg_type'],'content':exact['content'],'reply_in_thread':bool(exact['thread_id']),'uuid':exact['uuid']}:
            raise Failure('changed-reply')
        return True

    def api_response(self,state,body):state['reply_response']=body
