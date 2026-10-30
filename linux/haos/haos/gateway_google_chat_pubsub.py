"""Dedicated private UID bounded Google SDK pull/ACK transport.

Lifecycle dispatch, owner UI and public activation are separate. SDK retry and
emulator/ADC selection are not used by this production client factory.
"""
import asyncio
import queue

from .gateway_google_chat import credentials


def private_identity():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()


def create_client(value,current,*,redactor=None):
    private_identity();current();value=credentials(value)
    if value['inbound']['mode']!='pubsub':raise PermissionError('saved private Google Pub/Sub account required')
    from google.oauth2 import service_account
    from .redaction import Redactor
    redactor=redactor if redactor is not None else Redactor([value['service_account']['private_key']])
    account=service_account.Credentials.from_service_account_info(value['service_account'],scopes=[
        'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'])
    return _subscriber_client(account,current,redactor)


def _subscriber_client(account,current,redactor,*,target='pubsub.googleapis.com:443',roots=None,token_request=None):
    private_identity();current()
    import re
    if target!='pubsub.googleapis.com:443' and (not isinstance(target,str) or not re.fullmatch(r'localhost:[1-9][0-9]{0,4}',target)
            or not 1<=int(target.split(':')[1])<=65535):raise PermissionError('fixed Google authority or explicit local TLS fixture required')
    from google.oauth2 import service_account
    from google.cloud.pubsub_v1 import SubscriberClient
    from google.pubsub_v1.services.subscriber.transports.grpc import SubscriberGrpcTransport
    from google.auth.transport.grpc import AuthMetadataPlugin
    from google_auth_httplib2 import Request
    from .gateway_google_chat_http import single_request_http,TokenError
    from .redaction import Redactor
    import grpc
    if not isinstance(account,service_account.Credentials) or set(account.scopes or [])!={'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'}:
        raise PermissionError('dedicated Google SDK service account with exact Chat/PubSub scopes required')
    if not isinstance(redactor,Redactor):raise TypeError('shared private Google credential redactor required')
    class ScopedMetadata(AuthMetadataPlugin):
        error=None
        def _get_authorization_headers(self,context):
            try:
                current();headers=super()._get_authorization_headers(context);current()
                aliases=[value for name,value in headers if name.lower()=='authorization']
                secrets=Redactor([*redactor.secrets,*aliases,*[item.split(' ',1)[-1] for item in aliases]]).secrets
                if len(secrets)>4096 or sum(len(s) for s in secrets)>8*1024*1024:raise ValueError('private credential redaction capacity reached')
                redactor.secrets=secrets;self.error=None;return headers
            except Exception as error:
                self.error=error if isinstance(error,TokenError) else TokenError('authentication-refused',0,0,'rpc-auth-refused')
                raise self.error from None
    # Use the actual Google metadata signer, with a per-client bounded refresh
    # request and current-authority checks. Never use ambient ADC or the SDK's
    # independent default requests transport for a private token refresh.
    metadata=ScopedMetadata(account,token_request or Request(http=single_request_http(current,redactor=redactor)),default_host='pubsub.googleapis.com')
    transport_credentials=grpc.composite_channel_credentials(grpc.ssl_channel_credentials(root_certificates=roots),grpc.metadata_call_credentials(metadata))
    channel=grpc.secure_channel(target,transport_credentials,options=[
        ('grpc.max_receive_message_length',2*1024*1024),('grpc.max_send_message_length',65536)])
    try:
        current();client=SubscriberClient(transport=SubscriberGrpcTransport(channel=channel));client._haos_google_auth=metadata;return client
    except BaseException:channel.close();raise


async def rpc_call(client,method,*,request,timeout=10):
    private_identity()
    if method not in {'pull','get_subscription','acknowledge','modify_ack_deadline'}:raise PermissionError('closed private Google RPC operation required')
    try:return await asyncio.to_thread(getattr(client,method),request=request,retry=None,timeout=timeout)
    except Exception:
        metadata=getattr(client,'_haos_google_auth',None)
        if metadata is not None and metadata.error is not None:raise metadata.error from None
        raise


class PullTransport:
    def __init__(self,client,receiver,current):
        private_identity();current()
        from google.cloud.pubsub_v1 import SubscriberClient
        if not isinstance(client,SubscriberClient) or receiver.value['inbound']['mode']!='pubsub':
            raise TypeError('actual private Google SDK subscriber and saved pull receiver required')
        self.client=client;self.receiver=receiver;self.current=current;self.closed=False;self.lock=asyncio.Lock()
        self.subscription=receiver.value['inbound']['subscription']

    def check(self):
        private_identity()
        if self.closed:raise PermissionError('private Google Pub/Sub transport closed')
        self.current()
        if self.receiver.value['inbound']['subscription']!=self.subscription:raise PermissionError('Google subscription identity changed')

    async def _finish(self,message):
        from google.cloud.pubsub_v1.subscriber._protocol.requests import AckRequest,NackRequest
        self.check()
        if isinstance(message,AckRequest):
            await rpc_call(self.client,'acknowledge',request={'subscription':self.subscription,'ack_ids':[message.ack_id]},timeout=10)
        elif isinstance(message,NackRequest):
            await rpc_call(self.client,'modify_ack_deadline',request={'subscription':self.subscription,
                'ack_ids':[message.ack_id],'ack_deadline_seconds':0},timeout=10)
        else:raise PermissionError('unexpected private SDK acknowledgment action')
        self.check()

    async def step(self):
        async with self.lock:
            self.check()
            result=await rpc_call(self.client,'pull',request={'subscription':self.subscription,'max_messages':1},timeout=10)
            self.check()
            if len(result.received_messages)>1:raise PermissionError('Google pull response exceeded selected flow bound')
            if not result.received_messages:return None
            from google.cloud.pubsub_v1.subscriber.message import Message
            item=result.received_messages[0]
            if not item.ack_id or len(item.ack_id)>8192:raise ValueError('bounded Google acknowledgment identity required')
            actions=queue.Queue();message=Message(item.message._pb,item.ack_id,item.delivery_attempt,actions)
            # SQLite remains on the owning asyncio thread. Only network RPCs
            # run in worker threads; no callback crosses SQLite thread affinity.
            try:key=self.receiver.pubsub(message)
            except BaseException:
                if not actions.empty():await self._finish(actions.get_nowait())
                raise
            if actions.qsize()!=1:raise PermissionError('exactly one durable SDK ACK/NACK action required')
            await self._finish(actions.get_nowait());return key

    def close(self):
        private_identity()
        if not self.closed:self.closed=True;self.client.close()
