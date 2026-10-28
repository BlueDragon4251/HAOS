"""Prepared fixed-account native mail connections; worker supervision is required."""
from contextlib import contextmanager
import ssl
import re
import time

from .gateway_email import credentials
from .gateway_email_codec import MAX_HEADERS


class Transport:
    def __init__(self,adapter,value,current):
        from plugins.platforms.email.adapter import EmailAdapter
        if not isinstance(adapter,EmailAdapter) or not callable(current):raise TypeError('native private email codec and current authority required')
        self.adapter=adapter;self.value=credentials(value);self.current=current;self.deadline=time.monotonic()+30

    def check(self):
        self.current()
        if time.monotonic()>self.deadline:raise TimeoutError('private mail operation deadline exceeded')
        for field in ['address','password','imap_host','imap_port','imap_security','smtp_host','smtp_port','smtp_security']:
            if getattr(self.adapter,'_'+field)!=self.value[field]:raise PermissionError('native email account or TLS route changed')
        if self.adapter._imap_tls_verify is not True or self.adapter._smtp_tls_verify is not True:
            raise PermissionError('verified email TLS required')

    def verified(self,connection,host):
        self.check();sock=connection.sock
        if (not isinstance(sock,ssl.SSLSocket) or sock.context.verify_mode!=ssl.CERT_REQUIRED
                or sock.context.check_hostname is not True or sock.server_hostname!=host or not sock.version()):
            raise PermissionError('actual verified TLS connection to exact mail host required')

    @contextmanager
    def imap(self):
        from plugins.platforms.email.adapter import EmailAdapter
        self.check();connection=EmailAdapter._connect_imap(self.adapter)
        try:
            self.verified(connection,self.value['imap_host'])
            read,readline,send=connection.read,connection.readline,connection.send
            connection._haos_literal_limit=MAX_HEADERS
            def bounded_read(size):
                self.check()
                if type(size) is not int or not 0<=size<=connection._haos_literal_limit:raise ValueError('bounded mail literal required before allocation')
                data=read(size);self.check();return data
            def bounded_line():
                self.check();data=readline();self.check()
                if len(data)>MAX_HEADERS:raise ValueError('bounded IMAP response line required')
                return data
            def checked_send(data):
                self.check()
                parts=data.split(None,2) if isinstance(data,bytes) else []
                verb=parts[1].upper() if len(parts)>=2 else b''
                if verb not in {b'CAPABILITY',b'LOGIN',b'AUTHENTICATE',b'EXAMINE',b'UID',b'NOOP',b'LOGOUT'}:
                    raise PermissionError('private mail mutations are not authorized')
                if verb==b'UID':
                    command=parts[2].rstrip(b'\r\n') if len(parts)==3 else b''
                    if not (re.fullmatch(rb'SEARCH UID [1-9][0-9]{0,9}:[1-9][0-9]{0,9}',command)
                            or re.fullmatch(rb'FETCH [1-9][0-9]{0,9} \((?:UID |INTERNALDATE |RFC822.SIZE |FLAGS )*BODY.PEEK\[(?:HEADER)?\]\)',command)):
                        raise PermissionError('bounded read-only mail UID command required')
                return send(data)
            connection.read=bounded_read;connection.readline=bounded_line;connection.send=checked_send
            connection.login(connection._quote(self.value['address']),self.value['password']);self.check()
            status,_=connection.select('INBOX',readonly=True)
            if status!='OK':raise PermissionError('exact readable authenticated INBOX required')
            yield connection
        finally:
            # No implicit STORE, EXPUNGE or CLOSE: incoming mail is never deleted
            # or marked read merely by private connection cleanup.
            connection.shutdown()

    @contextmanager
    def smtp(self):
        from plugins.platforms.email.adapter import EmailAdapter
        self.check();connection=EmailAdapter._connect_smtp(self.adapter)
        try:
            self.verified(connection,self.value['smtp_host'])
            send=connection.send
            authenticating=[True]
            def checked_send(data):
                self.check()
                if not authenticating[0]:raise PermissionError('SMTP connection probe has no message-write capability')
                return send(data)
            connection.send=checked_send
            connection.login(self.value['address'],self.value['password']);self.check();authenticating[0]=False
            yield connection
        finally:connection.close()

    @staticmethod
    def number(connection,name):
        kind,values=connection.response(name)
        if (kind!=name or not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],bytes)
                or not values[0].isdigit() or not 0<int(values[0])<2**32):
            raise ValueError('exact bounded mailbox UID state required')
        return int(values[0])

    def probe(self):
        with self.imap() as connection:
            validity=self.number(connection,'UIDVALIDITY');next_uid=self.number(connection,'UIDNEXT')
        with self.smtp():pass  # Authentication only; never MAIL, RCPT or DATA.
        return {'imap_authenticated':True,'smtp_authenticated':True,'uid_validity':validity,'uid_next':next_uid,
            'smtp_message_sent':False}
