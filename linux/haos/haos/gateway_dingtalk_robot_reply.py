"""Stable native Robot SDK replies in the explicitly selected owner reply mode."""
from copy import deepcopy
import json
import re
import time
from urllib.parse import urlsplit

from .gateway import digest
from .gateway_dingtalk_tea import Operation,generated_request,active
from .gateway_dingtalk_http import Boundary as TokenBoundary,Failure
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object


class Reply(Operation):
    def __init__(self,owner,token,target,current):
        if (not isinstance(owner,TokenBoundary) or not isinstance(token,str) or token not in owner.tokens
                or not callable(current) or not isinstance(target,dict) or set(target)!={'url','payload','intent_sha256'}
                or not isinstance(target['intent_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',target['intent_sha256'])):
            raise PermissionError('exact observed-token private Robot reply intent required')
        address=urlsplit(target['url']);payload=target['payload']
        if (address.scheme!='https' or address.netloc!='api.dingtalk.com' or address.query or address.fragment
                or address.path not in {'/v1.0/robot/groupMessages/send','/v1.0/robot/oToMessages/batchSend'}
                or not isinstance(payload,dict)):
            raise PermissionError('reviewed stable Robot reply endpoint required')
        fields={'msgKey','msgParam','robotCode'}|({'openConversationId'} if address.path.endswith('/groupMessages/send') else {'userIds'})
        if set(payload)!=fields or payload['robotCode']!=owner.value['robot_code'] or payload['msgKey']!='sampleMarkdown':
            raise PermissionError('exact native Robot sender and message format required')
        if not isinstance(payload['msgParam'],str) or not 1<=len(payload['msgParam'].encode())<=64000:
            raise PermissionError('bounded native Robot reply content required')
        params=json.loads(payload['msgParam'],object_pairs_hook=_object,parse_constant=finite)
        if (not isinstance(params,dict) or set(params)!={'title','text'} or params['title']!='Hermes'
                or not isinstance(params['text'],str) or not params['text'].strip()
                or owner.redactor.clean(params)!=params):raise PermissionError('private credential or unreviewed reply content refused')
        from .gateway_dingtalk import identity
        if 'openConversationId' in payload:identity(payload['openConversationId'])
        elif not isinstance(payload['userIds'],list) or len(payload['userIds'])!=1:raise PermissionError('one approved direct-bot recipient required')
        else:identity(payload['userIds'][0])
        self.owner=owner;self.token=token;self.target=deepcopy(target);self.path=address.path;self.current=current
        self.used=False;self.write_started=False;self.state='not-dispatched';self.error='';self.retry_after=0
        self.acceptance_id=None;self.query_key=None;self.client=None;self.check()

    def check(self):
        self.current();self.owner.current()
        if self.owner.tokens.get(self.token,{}).get('until',0)<=time.monotonic():raise Failure('invalid-token')

    def reject(self,error,delay=0):
        self.state='rejected';self.error=error;self.retry_after=delay;raise PermissionError('private native Robot reply refused')

    async def request(self,request,runtime):
        self.check()
        if self.used or not active(self):raise PermissionError('one current scoped Robot write per immutable intent required')
        headers,body=generated_request(request,runtime,self.path,self.token,self.target['payload'],max_bytes=128000)
        self.used=True
        import httpx
        self.client=httpx.AsyncClient(trust_env=False,follow_redirects=False,
            timeout=httpx.Timeout(connect=5,read=10,write=10,pool=5),
            limits=httpx.Limits(max_connections=1,max_keepalive_connections=0),headers={'Accept-Encoding':'identity'})
        try:
            self.check();self.write_started=True;self.state='uncertain'
            async with self.client.stream('POST',self.target['url'],headers=headers,content=body) as response:
                self.check();status=response.status_code
                if status in {401,403}:self.reject('authentication-refused')
                if status==429:
                    from .gateway_retry import retry_after
                    self.reject('rate-limited',retry_after(response.headers.get('Retry-After'),default=60,private_values=self.owner.redactor.secrets))
                if (status!=200 or response.headers.get('Content-Encoding','identity').lower() not in {'','identity'}
                        or response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json'):
                    raise PermissionError('native Robot acceptance unavailable')
                length=response.headers.get('Content-Length')
                if length is not None and (not length.isascii() or not length.isdecimal() or len(length)>8 or int(length)>65536):
                    raise PermissionError('bounded native Robot acceptance required')
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    self.check();data.extend(chunk)
                    if len(data)>65536:raise PermissionError('bounded native Robot acceptance required')
                if length is not None and len(data)!=int(length):raise PermissionError('truncated native Robot acceptance')
                decoded=json.loads(bytes(data).decode(),object_pairs_hook=_object,parse_constant=finite)
                if not isinstance(decoded,dict) or not 1<=len(decoded)<=64:raise PermissionError('native Robot result required')
                if 'userIds' in self.target['payload']:
                    recipient=self.target['payload']['userIds'][0]
                    for field,error in [('invalidStaffIdList','native-refused'),('flowControlledStaffIdList','rate-limited')]:
                        values=decoded.get(field,[])
                        if not isinstance(values,list) or any(value!=recipient for value in values) or len(values)>1:
                            raise PermissionError('native Robot recipient decision changed')
                        if values:self.reject(error,60 if error=='rate-limited' else 0)
                key=decoded.get('processQueryKey')
                if (not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_./+=:-]{1,1024}',key)
                        or self.owner.redactor.text(key)!=key):raise PermissionError('native provider queue acceptance required')
                self.check();self.query_key=key
                self.acceptance_id='haos-dingtalk-'+digest([self.target['intent_sha256'],self.target,key])
                self.state='confirmed'
                from darabonba.response import DaraResponse
                result=DaraResponse();result.status_code=200;result.status_message='OK'
                result.headers={'content-type':'application/json','content-length':str(len(data))};result.body=bytes(data)
                return result
        finally:await self.close()

    async def close(self):
        if self.client is not None:
            self.client.cookies.clear();await self.client.aclose();self.client=None


async def invoke(adapter,blueprint,current,redactor):
    from .gateway_dingtalk_send import wire_target
    from .gateway_dingtalk_http import sdk_scope,QuietLogger
    from .gateway_dingtalk_tea import sdk_scope as robot_scope
    from plugins.platforms.dingtalk import adapter as native
    owner=TokenBoundary(adapter._haos_robot_credentials,current,redactor);operation=None;logger=native.logger
    native.logger=QuietLogger();adapter._stream_client=owner.client()
    adapter._robot_sdk=native.dingtalk_robot_client.Client(native.open_api_models.Config(protocol='https',region_id='central'))
    try:
        with sdk_scope(),owner.operation('token',adapter._stream_client):token=await native.DingTalkAdapter._get_access_token(adapter)
        if token is None or token not in owner.tokens:
            return {'state':'rejected','error':owner.failure or 'transport-unavailable','retry_after':owner.retry_after}
        operation=Reply(owner,token,wire_target(adapter,blueprint),current);payload=operation.target['payload']
        try:
            with robot_scope(operation):
                if blueprint['robot_route']=='group':
                    request=native.dingtalk_robot_models.OrgGroupSendRequest(msg_key=payload['msgKey'],msg_param=payload['msgParam'],
                        robot_code=payload['robotCode'],open_conversation_id=payload['openConversationId'])
                    result=await adapter._sdk_call(adapter._robot_sdk.org_group_send_with_options_async,request,native.dingtalk_robot_models.OrgGroupSendHeaders,token)
                else:
                    request=native.dingtalk_robot_models.BatchSendOTORequest(msg_key=payload['msgKey'],msg_param=payload['msgParam'],
                        robot_code=payload['robotCode'],user_ids=payload['userIds'])
                    result=await adapter._sdk_call(adapter._robot_sdk.batch_send_otowith_options_async,request,native.dingtalk_robot_models.BatchSendOTOHeaders,token)
            current()
            if (operation.state=='confirmed' and getattr(getattr(result,'body',None),'process_query_key',None)==operation.query_key):
                return {'state':'confirmed','acceptance_id':operation.acceptance_id,'remote_message_id':None,'recipient_read_verified':False}
        except Exception:
            current()
        if operation.state=='rejected':return {'state':'rejected','error':operation.error,'retry_after':operation.retry_after}
        return {'state':'uncertain'} if operation.write_started else {'state':'rejected','error':'authority-or-protocol-refused','retry_after':0}
    except Exception:
        # Revocation/protocol failures after a possible write cannot authorize
        # an automatic retry, even when the fresh-authority check itself fails.
        if operation is not None and operation.write_started:return {'state':'uncertain'}
        return {'state':'rejected','error':'authority-or-protocol-refused','retry_after':0}
    finally:
        native.logger=logger
        if operation is not None:await operation.close()
        owner.close()
