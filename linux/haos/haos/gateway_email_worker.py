"""Private disposable native email worker. Never a model-callable command runner."""
import json
import os
from pathlib import Path
import re
import resource
import signal
import sys


def main():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()
    # A killed service must not leave a credential-bearing network worker alive.
    import ctypes
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:
        raise PermissionError('private mail worker parent lifetime guard required')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    signal.signal(signal.SIGALRM,lambda *_args:os._exit(124));signal.alarm(30)
    raw=sys.stdin.buffer.read(262145)
    if len(raw)>262144:raise ValueError('bounded private mail worker request required')
    from .gateway_line_ingress import _object
    def constant(_value):raise ValueError('finite JSON required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=constant)
    if not isinstance(request,dict) or not isinstance(request.get('action'),str) or request['action'] not in {'probe','mailbox','headers','search','message','smtp'}:
        raise ValueError('closed private email worker action required')
    if request['action']!='smtp' and len(raw)>32768:raise ValueError('bounded private mail reader request required')
    extra={'smtp':{'reply'},'probe':set(),'mailbox':set(),'headers':{'uid','uid_validity'},'search':{'page'},'message':{'uid','uid_validity','header_sha256','binding_id','binding_digest'}}[request['action']]
    if (set(request)!=({'action','connector','credentials','policy_sha256','parent_pid'}|extra)
            or type(request.get('parent_pid')) is not int or request['parent_pid']!=parent or os.getppid()!=parent
            or not isinstance(request['connector'],str) or not isinstance(request['policy_sha256'],str)
            or not re.fullmatch(r'[0-9a-f]{64}',request['policy_sha256'])):
        raise ValueError('exact closed private email worker request required')
    from .gateway_email import credentials,authority,scope as mailbox_scope
    value=credentials(request['credentials'])
    def current():return authority(request['connector'],value,request['policy_sha256'])
    current()
    base=Path('/var/lib/haos-gateway');home=base/('email-'+mailbox_scope(value).split(':',1)[1])
    from .gateway_line_profile import _directory
    _directory(base)
    try:home.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(home)
    os.environ['HERMES_SAFE_MODE']='1'
    from .gateway_matrix_profile import scope
    from .gateway_email_transport import Transport
    env={'EMAIL_'+key.upper():str(item) for key,item in value.items() if key!='authserv_id'}
    env.update(EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_IMAP_TLS_VERIFY='true',EMAIL_SMTP_TLS_VERIFY='true',
        EMAIL_TRUST_FROM_HEADER='false',EMAIL_ALLOW_ALL_USERS='false',GATEWAY_ALLOW_ALL_USERS='false',
        EMAIL_ALLOWED_USERS='',GATEWAY_ALLOWED_USERS='')
    from .gateway_email_imap import MailboxChanged
    from .gateway_email_admission import Refused as AdmissionRefused
    streaming=False
    try:
        with scope(home,env):
            from gateway.config import PlatformConfig
            from plugins.platforms.email.adapter import EmailAdapter
            adapter=EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,
                'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))
        transport=Transport(adapter,value,current)
        if request['action']=='smtp':
            from .gateway_email import PreparedEmailPolicy
            from .gateway_email_smtp import publish
            from .sandbox import trusted_json
            def policy():
                current();return PreparedEmailPolicy(trusted_json(Path('/etc/haos/gateways.json')))
            result=publish(adapter,value,policy,request['connector'],request['reply'],current)
        elif request['action']=='probe':result=transport.probe()
        elif request['action']=='mailbox':
            with transport.imap() as connection:
                result={'uid_validity':transport.number(connection,'UIDVALIDITY'),'uid_next':transport.number(connection,'UIDNEXT')}
        elif request['action']=='search':
            from .gateway_email import PreparedEmailPolicy
            from .gateway_email_imap import search
            from .sandbox import trusted_json
            policy=PreparedEmailPolicy(trusted_json(Path('/etc/haos/gateways.json')))
            times=[row['since'] for row in policy.bindings.values() if row['connector']==request['connector']]
            if not times:raise PermissionError('email scan requires an explicit timed sender grant')
            current();result=search(transport,request['page'],min(times))
        elif request['action']=='message':
            from .gateway_email import PreparedEmailPolicy
            from .gateway_email_imap import message
            from .sandbox import trusted_json
            def policy():
                current();return PreparedEmailPolicy(trusted_json(Path('/etc/haos/gateways.json')))
            complete=message(transport,request['uid'],request['uid_validity'],request['header_sha256'],policy,
                request['connector'],value,{'binding_id':request['binding_id'],'binding_digest':request['binding_digest']})
            from .gateway_email_media import manifest,permit
            complete['mime']=manifest(complete['content'])
            permit(policy(),request['connector'],complete['approval']['envelope'],complete['mime'])
            content=complete.pop('content');current();streaming=True
            sys.stdout.buffer.write((json.dumps(complete)+'\n').encode());sys.stdout.buffer.flush()
            for offset in range(0,len(content),49152):
                current();sys.stdout.buffer.write(memoryview(content)[offset:offset+49152])
            sys.stdout.buffer.flush();current();return
        else:
            import base64,hashlib
            from .gateway_email_imap import get_headers
            fetched=get_headers(transport,request['uid'],request['uid_validity']);content=fetched.pop('content')
            result={**fetched,'content_base64':base64.b64encode(content).decode(),'sha256':hashlib.sha256(content).hexdigest()}
        current()
    except Exception as error:
        if streaming:os._exit(1)  # Partial binary output never becomes another JSON record.
        if isinstance(error,MailboxChanged):code='uid-state-changed'
        elif isinstance(error,AdmissionRefused):code=error.reason
        elif isinstance(error,PermissionError):code='authority-or-protocol-refused'
        elif isinstance(error,__import__('ssl').SSLCertVerificationError):code='tls-refused'
        elif isinstance(error,__import__('smtplib').SMTPAuthenticationError):code='smtp-authentication-refused'
        elif isinstance(error,__import__('imaplib').IMAP4.error):code='imap-unavailable'
        else:code='transport-unavailable'
        result={'error':code}
    # No exception strings, protocol responses, addresses, passwords or aliases.
    sys.stdout.write(json.dumps(result)+'\n')


if __name__=='__main__':main()
