#!/usr/bin/env python3
"""Actual pinned MIME builder/SMTP lifecycle against disposable TLS servers."""
import asyncio
import base64
from copy import deepcopy
from email import policy as email_policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest
    from haos.gateway_email import PreparedEmailPolicy,scope as mailbox_scope
    from haos.gateway_email_smtp import publish,identity
    from haos.gateway_matrix_profile import scope
    from gateway.config import PlatformConfig
    from plugins.platforms.email.adapter import EmailAdapter
    from webhook_tls_fixture import create
    cases=[]
    async def exercise(root):
        create(root,'mail.fixture.invalid');os.environ['SSL_CERT_FILE']=str(root/'ca.pem');os.environ['HERMES_SAFE_MODE']='1'
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        mode=['success'];allowed=[True];commands=[];messages=[];errors=[]
        async def smtp(reader,writer):
            encrypted=bool(writer.get_extra_info('ssl_object'))
            try:
                writer.write(b'220 localhost private SMTP\r\n');await writer.drain()
                while line:=await reader.readline():
                    verb=line.split()[0].upper();commands.append(verb)
                    if verb==b'EHLO':writer.write(b'250-localhost\r\n250-STARTTLS\r\n250 AUTH PLAIN\r\n')
                    elif verb==b'STARTTLS':
                        assert not encrypted;writer.write(b'220 begin TLS\r\n');await writer.drain();await writer.start_tls(tls);encrypted=True;continue
                    elif verb==b'AUTH':
                        assert encrypted and base64.b64decode(line.split()[2])==b'\0haos@example.invalid\0private-email-fixture'
                        writer.write(b'535 5.7.8 rejected\r\n' if mode[0]=='auth' else b'235 authenticated\r\n')
                    elif verb==b'MAIL':
                        assert line.lower()==b'mail from:<haos@example.invalid>\r\n';writer.write(b'250 sender accepted\r\n')
                    elif verb==b'RCPT':
                        assert line.lower()==b'rcpt to:<owner@example.invalid>\r\n'
                        if mode[0]=='revoke':allowed[0]=False
                        writer.write(b'550 recipient refused\r\n' if mode[0]=='recipient' else b'250 recipient accepted\r\n')
                    elif verb==b'RSET':writer.write(b'250 reset\r\n')
                    elif verb==b'DATA':
                        writer.write(b'354 message body\r\n');await writer.drain();body=bytearray()
                        while (piece:=await reader.readline())!=b'.\r\n':
                            assert piece and len(body)<256000
                            body.extend(piece[1:] if piece.startswith(b'..') else piece)
                        messages.append(bytes(body))
                        if mode[0]=='drop':return
                        if mode[0]=='longline':writer.write(b'500 '+b'x'*8192+b'\r\n')
                        elif mode[0]=='multiline':writer.write((b'500-'+b'x'*1020+b'\r\n')*70+b'500 rejected\r\n')
                        else:
                            writer.write(b'451 retry later\r\n' if mode[0]=='temporary' else b'550 rejected\r\n' if mode[0]=='permanent' else b'250 queued\r\n')
                    else:raise AssertionError('unexpected native SMTP command')
                    await writer.drain()
            except (ConnectionError,ssl.SSLError):pass
            except BaseException as error:errors.append(error);raise
            finally:
                writer.close()
                try:await writer.wait_closed()
                except (ConnectionError,ssl.SSLError):pass
        for security in ['tls','starttls']:
            server=await asyncio.start_server(smtp,'127.0.0.1',0,ssl=tls if security=='tls' else None)
            value={'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'localhost','imap_port':993,
                'imap_security':'tls','smtp_host':'localhost','smtp_port':server.sockets[0].getsockname()[1],
                'smtp_security':security,'authserv_id':'mx.example.invalid'}
            binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid',
                'scope':mailbox_scope(value),'thread':'<root@example.invalid>','identity':'personal','capabilities':['create','read'],
                'generation':'b'*64,'since':1}
            config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]}
            def policy():return PreparedEmailPolicy(config)
            env={'EMAIL_'+key.upper():str(item) for key,item in value.items() if key!='authserv_id'}
            env.update(EMAIL_IMAP_TLS_VERIFY='true',EMAIL_SMTP_TLS_VERIFY='true',EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_TRUST_FROM_HEADER='false')
            with scope(root/('home-'+security),env):adapter=EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,
                'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))
            item={'binding_id':'owner','binding_digest':digest(binding),'delivery_id':'d'*64,'attempt':1,'source_id':'e'*64,
                'rfc_message_id':'<specific-source@example.invalid>','root_message_id':binding['thread'],'subject':'Specific retained source',
                'body':'A native reply. Grüße!\n.Line beginning with a dot.','created_at':int(time.time()),'recipient':binding['chat'],'files':[]}
            def current():
                if not allowed[0]:raise PermissionError('fixture owner grant withdrawn')
            try:
                mode[0]='success';before_messages=len(messages);result=await asyncio.to_thread(publish,adapter,value,policy,'email',item,current)
                assert result['accepted'] is True and result['recipient_receipt_verified'] is False
                assert result['receipt'].startswith('smtp_accept_') and len(messages)==before_messages+1
                message=BytesParser(policy=email_policy.default).parsebytes(messages[-1])
                assert str(message['From'])==value['address'] and str(message['To'])==item['recipient']
                assert str(message['Message-ID']).strip()==identity(value,item) and str(message['In-Reply-To']).strip()==item['rfc_message_id'],repr(message['Message-ID'])
                assert str(message['References'])==item['root_message_id']+' '+item['rfc_message_id']
                assert str(message['Subject'])=='Re: Specific retained source'
                body=message.get_payload()[0].get_payload(decode=True).decode('utf-8')
                assert body.replace('\r\n','\n')==item['body']
                cases.append(security+'_actual_native_builder_and_smtp_lifecycle_deliver_exact_single_recipient_thread_and_unicode_body_to_fixture')
                for field,replacement in [('recipient','other@example.invalid'),('root_message_id','<other@example.invalid>'),('subject','bad\r\nBcc: other@example.invalid')]:
                    before=len(commands)
                    try:await asyncio.to_thread(publish,adapter,value,policy,'email',{**item,field:replacement},current)
                    except (PermissionError,ValueError):pass
                    else:raise AssertionError('changed native SMTP authority accepted')
                    assert len(commands)==before
                cases.append(security+'_changed_recipient_thread_or_header_injection_refused_before_any_connection')
                for failure,expected in [('auth','smtp-authentication-refused'),('recipient','smtp-permanent-refusal'),
                        ('temporary','smtp-temporary-refusal'),('permanent','smtp-permanent-refusal')]:
                    mode[0]=failure
                    result=await asyncio.to_thread(publish,adapter,value,policy,'email',item,current)
                    assert result=={'error':expected}
                    cases.append(security+'_'+failure+'_uses_finite_explicit_rejection_without_server_body_or_credentials')
                mode[0]='drop'
                try:await asyncio.to_thread(publish,adapter,value,policy,'email',item,current)
                except __import__('smtplib').SMTPServerDisconnected:pass
                else:raise AssertionError('lost terminal SMTP response was confirmed')
                cases.append(security+'_disconnect_after_data_remains_unknown_not_confirmed_or_retried')
                for failure in ['longline','multiline']:
                    mode[0]=failure
                    try:await asyncio.to_thread(publish,adapter,value,policy,'email',item,current)
                    except ValueError:pass
                    else:raise AssertionError('incomplete or oversized terminal reply became a safe rejection/acceptance')
                    cases.append(security+'_'+failure+'_terminal_response_is_bounded_and_unknown_instead_of_a_local_500_safe_rejection')
                mode[0]='revoke';before=commands.count(b'DATA')
                try:await asyncio.to_thread(publish,adapter,value,policy,'email',item,current)
                except PermissionError:pass
                else:raise AssertionError('revoked SMTP write continued')
                assert commands.count(b'DATA')==before
                cases.append(security+'_owner_withdrawal_after_recipient_command_blocks_data_and_cleanup_sends_no_new_mail')
            finally:allowed[0]=True;server.close();await server.wait_closed()
        assert not errors,errors
    with tempfile.TemporaryDirectory(prefix='haos-email-smtp-') as name:asyncio.run(exercise(Path(name)))
    report={'passed':len(cases),'cases':cases,'actual_native_mime_builder_and_smtp_lifecycle':True,'loopback_tls_server_only':True,
        'public_registry_enabled':True,'durable_intent_worker_supervision_external_delivery_or_recipient_receipt':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
