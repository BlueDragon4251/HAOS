"""Per-profile exact-origin socket hook; native NIP-42 and subscriptions stay native."""
import json
import ssl

from .gateway_buzz import HEX,credentials
from .gateway_buzz_crypto import verify,wire


class AuthenticationRefused(PermissionError):
    pass


class Transport:
    def __init__(self,value,current,capture):
        if not callable(current) or not callable(capture):raise PermissionError('current owner publication and durable event capture required')
        self.value=credentials(value);self.current=current;self.capture=capture;self.connections=set();self.authentication_refused=False
        self.url='wss'+self.value['relay_url'][5:]

    def open(self,**kwargs):
        self.current()
        if self.authentication_refused:raise AuthenticationRefused('saved Buzz authentication was refused; owner recovery required')
        expected={'open_timeout','close_timeout','ping_interval','ping_timeout','max_size','happy_eyeballs_delay'}
        if set(kwargs)!=expected or any(type(value) not in {int,float} for value in kwargs.values()):
            raise PermissionError('exact bounded native Buzz subscription transport required')
        from websockets.asyncio.client import connect,ClientConnection
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        transport=self
        def parsed(raw,limit):
            if not isinstance(raw,str) or not 1<=len(raw.encode())<=limit:raise ValueError('bounded Buzz socket frame required')
            return json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
        class Connection(ClientConnection):
            def __init__(self,*args,**options):
                super().__init__(*args,**options);self.challenge=None;self.auth_id=None;self.authenticated=False;self.subscriptions={}
                transport.connections.add(self)
            def connection_lost(self,exc):
                transport.connections.discard(self);super().connection_lost(exc)
            async def send(self,message,text=None):
                transport.current();frame=parsed(message,65536)
                if not isinstance(frame,list) or not frame or not isinstance(frame[0],str):raise ValueError('closed native Buzz request frame required')
                if frame[0]=='AUTH':
                    if len(frame)!=2 or self.challenge is None or self.auth_id is not None:raise PermissionError('one exact relay challenge response required')
                    event=await verify(json.dumps(frame[1],separators=(',',':'),ensure_ascii=False).encode())
                    tags=[['relay',transport.url],['challenge',self.challenge]]
                    if transport.value.get('auth_tag'):tags.append(json.loads(transport.value['auth_tag']))
                    if event['kind']!=22242 or event['content'] or event['pubkey']!=transport.value['public_key'] or event['tags']!=tags:
                        raise PermissionError('native Buzz authentication changed its exact private identity relay challenge or owner attestation')
                    self.auth_id=event['id']
                elif frame[0]=='REQ':
                    if (not self.authenticated or len(frame)!=3 or not isinstance(frame[1],str) or not 1<=len(frame[1])<=128
                            or not isinstance(frame[2],dict) or len(self.subscriptions)>=33 and frame[1] not in self.subscriptions):
                        raise PermissionError('authenticated bounded native Buzz subscriptions required')
                    selection=frame[2];channel=selection.get('#h')
                    if (channel is not None and (not isinstance(channel,list) or len(channel)!=1 or channel[0] not in transport.value['channels'])
                            or channel is None and selection.get('#p')!=[transport.value['public_key']]
                            or not set(selection)<={'kinds','#h','#p','since','limit'}
                            or not isinstance(selection.get('kinds'),list) or not selection['kinds']
                            or any(type(kind) is not int or kind not in ({9,45001,45003} if channel is not None else {44100}) for kind in selection['kinds'])
                            or any(type(selection[key]) is not int or not 0<=selection[key]<2**53 for key in ['since'] if key in selection)
                            or 'limit' in selection and (type(selection['limit']) is not int or not 1<=selection['limit']<=200)):
                        raise PermissionError('subscription must retain exact selected channels or own membership identity and finite native kinds')
                    self.subscriptions[frame[1]]=channel[0] if channel is not None else None
                elif frame[0]=='CLOSE':
                    if len(frame)!=2 or not isinstance(frame[1],str) or frame[1] not in self.subscriptions:raise PermissionError('exact saved Buzz subscription required for close')
                    self.subscriptions.pop(frame[1])
                else:raise PermissionError('arbitrary WebSocket publish or plugin frames are not available')
                transport.current();return await super().send(message,text=text)
            async def recv(self,decode=None):
                for _ in range(256):
                    transport.current();raw=await super().recv(decode=decode);transport.current();frame=parsed(raw,2000000)
                    if not isinstance(frame,list) or not frame or not isinstance(frame[0],str):raise ValueError('finite native Buzz response frame required')
                    if not self.authenticated:
                        if self.challenge is None:
                            if (len(frame)!=2 or frame[0]!='AUTH' or not isinstance(frame[1],str) or not 1<=len(frame[1])<=512
                                    or any(ord(c)<33 or ord(c)>126 for c in frame[1])):raise AuthenticationRefused('Buzz relay did not provide a bounded NIP-42 challenge')
                            self.challenge=frame[1]
                        elif (len(frame)==4 and frame[0]=='OK' and frame[1]==self.auth_id and type(frame[2]) is bool and isinstance(frame[3],str)):
                            if not frame[2]:
                                transport.authentication_refused=True;raise AuthenticationRefused('Buzz relay refused the saved private identity')
                            self.authenticated=True
                        else:raise AuthenticationRefused('Buzz relay authentication response changed its exact challenge receipt')
                    elif frame[0]=='EVENT':
                        if len(frame)!=3 or not isinstance(frame[1],str) or frame[1] not in self.subscriptions:raise PermissionError('event has no current exact Buzz subscription')
                        event=wire(json.dumps(frame[2],separators=(',',':'),ensure_ascii=False).encode())
                        # Capture must verify signature, account/grant and durable
                        # first custody before native cursors or dispatch can see it.
                        captured=await transport.capture(self.subscriptions[frame[1]],event)
                        if type(captured) is not bool:raise TypeError('explicit durable Buzz source capture decision required')
                        if not captured:continue
                    elif frame[0]=='EOSE':
                        if len(frame)!=2 or not isinstance(frame[1],str) or frame[1] not in self.subscriptions:raise ValueError('exact subscription end receipt required')
                    elif frame[0]=='NOTICE':
                        if len(frame)!=2 or not isinstance(frame[1],str) or len(frame[1].encode())>512:raise ValueError('bounded Buzz relay notice required')
                    elif frame[0]=='CLOSED':
                        if len(frame)!=3 or not isinstance(frame[1],str) or frame[1] not in self.subscriptions or not isinstance(frame[2],str) or len(frame[2].encode())>512:
                            raise ValueError('bounded exact subscription close required')
                    elif frame[0]=='OK':
                        if len(frame)!=4 or not isinstance(frame[1],str) or not HEX.fullmatch(frame[1]) or type(frame[2]) is not bool or not isinstance(frame[3],str) or len(frame[3].encode())>512:
                            raise ValueError('bounded native acknowledgment required')
                    else:raise PermissionError('unsupported Buzz relay control frame')
                    transport.current();return raw
                raise ConnectionError('Buzz input rejection budget reached; bounded reconnect required')
        class ExactSocket(connect):
            def process_redirect(self,exc):return PermissionError('Buzz WebSocket redirect outside its exact owner-approved transport is forbidden')
        return ExactSocket(self.url,proxy=None,ssl=ssl.create_default_context(),create_connection=Connection,
            open_timeout=20,close_timeout=5,ping_interval=20,ping_timeout=20,max_size=2000000,max_queue=16,happy_eyeballs_delay=.25)

    async def close(self):
        import asyncio
        sockets=list(self.connections)
        if sockets:await asyncio.gather(*(socket.close(code=1001,reason='private gateway stopped') for socket in sockets),return_exceptions=True)
