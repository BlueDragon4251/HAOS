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
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    signal.signal(signal.SIGALRM,lambda *_args:os._exit(124));signal.alarm(30)
    raw=sys.stdin.buffer.read(32769)
    if len(raw)>32768:raise ValueError('bounded private mail worker request required')
    from .gateway_line_ingress import _object
    def constant(_value):raise ValueError('finite JSON required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=constant)
    if (not isinstance(request,dict) or set(request)!={'action','connector','credentials','policy_sha256'}
            or request['action']!='probe' or not isinstance(request['connector'],str)
            or not isinstance(request['policy_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',request['policy_sha256'])):
        raise ValueError('exact closed private email worker action required')
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
    try:
        with scope(home,env):
            from gateway.config import PlatformConfig
            from plugins.platforms.email.adapter import EmailAdapter
            adapter=EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,
                'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))
        result=Transport(adapter,value,current).probe();current()
    except PermissionError:result={'error':'authority-or-protocol-refused'}
    except __import__('ssl').SSLCertVerificationError:result={'error':'tls-refused'}
    except __import__('smtplib').SMTPAuthenticationError:result={'error':'smtp-authentication-refused'}
    except __import__('imaplib').IMAP4.error:result={'error':'imap-unavailable'}
    except Exception:result={'error':'transport-unavailable'}
    # No exception strings, protocol responses, addresses, passwords or aliases.
    sys.stdout.write(json.dumps(result)+'\n')


if __name__=='__main__':main()
