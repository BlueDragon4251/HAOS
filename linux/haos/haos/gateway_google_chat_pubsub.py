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


def create_client(value,current):
    private_identity();current();value=credentials(value)
    if value['inbound']['mode']!='pubsub':raise PermissionError('saved private Google Pub/Sub account required')
    from google.oauth2 import service_account
    from google.cloud.pubsub_v1 import SubscriberClient
    from google.pubsub_v1.services.subscriber.transports.grpc import SubscriberGrpcTransport
    account=service_account.Credentials.from_service_account_info(value['service_account'],scopes=[
        'https://www.googleapis.com/auth/chat.bot','https://www.googleapis.com/auth/pubsub'])
    # A fixed TLS gRPC authority prevents environment emulator/endpoint choices.
    channel=SubscriberGrpcTransport.create_channel('pubsub.googleapis.com:443',credentials=account,options=[
        ('grpc.max_receive_message_length',2*1024*1024),('grpc.max_send_message_length',65536)])
    try:
        current();return SubscriberClient(transport=SubscriberGrpcTransport(channel=channel))
    except BaseException:channel.close();raise


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
            await asyncio.to_thread(self.client.acknowledge,request={'subscription':self.subscription,'ack_ids':[message.ack_id]},retry=None,timeout=10)
        elif isinstance(message,NackRequest):
            await asyncio.to_thread(self.client.modify_ack_deadline,request={'subscription':self.subscription,
                'ack_ids':[message.ack_id],'ack_deadline_seconds':0},retry=None,timeout=10)
        else:raise PermissionError('unexpected private SDK acknowledgment action')
        self.check()

    async def step(self):
        async with self.lock:
            self.check()
            result=await asyncio.to_thread(self.client.pull,request={'subscription':self.subscription,'max_messages':1},retry=None,timeout=10)
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
