#!/usr/bin/env python3
"""Actual pinned IMAP/SMTP clients against verified loopback TLS and STARTTLS."""
import asyncio
import base64
import json
import os
from pathlib import Path
import shlex
import ssl
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_email import credentials
    from haos.gateway_email_transport import Transport
    from haos.gateway_email_codec import MAX_HEADERS
    from haos.gateway_matrix_profile import scope
    from gateway.config import PlatformConfig
    from plugins.platforms.email.adapter import EmailAdapter
    from webhook_tls_fixture import create
    cases=[]
    async def exercise(root):
        create(root,'mail.fixture.invalid');os.environ['SSL_CERT_FILE']=str(root/'ca.pem');os.environ['HERMES_SAFE_MODE']='1'
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        commands=[];mode=['success'];allowed=[True]
        message_header=(b'From: owner@example.invalid\r\nTo: haos@example.invalid\r\nMessage-ID: <goal-1@example.invalid>\r\n'
            b'Authentication-Results: mx.example.invalid; dmarc=pass\r\nSubject: Approved goal\r\n'
            b'Date: Fri, 1 Jan 1999 00:00:00 +0000\r\n\r\n')
        message_body=b'Actual scoped email body.\r\n';body_downloads=[]
        async def imap(reader,writer):
            encrypted=bool(writer.get_extra_info('ssl_object'))
            try:
                writer.write(b'* OK HAOS disposable IMAP fixture\r\n');await writer.drain()
                while line:=await reader.readline():
                    parts=shlex.split(line.decode().strip());tag,verb=parts[:2];verb=verb.upper();commands.append(('imap',verb))
                    if verb=='CAPABILITY':writer.write(b'* CAPABILITY IMAP4rev1 STARTTLS AUTH=PLAIN\r\n'+tag.encode()+b' OK capabilities\r\n')
                    elif verb=='STARTTLS':
                        assert not encrypted;writer.write(tag.encode()+b' OK begin TLS\r\n');await writer.drain();await writer.start_tls(tls);encrypted=True;continue
                    elif verb=='LOGIN':
                        assert encrypted and parts[2:]==['haos@example.invalid','private-email-fixture']
                        writer.write(tag.encode()+(b' NO authentication refused\r\n' if mode[0]=='imap-auth-refused' else b' OK authenticated\r\n'))
                    elif verb=='EXAMINE':
                        assert parts[2:] == ['INBOX']
                        writer.write(b'* 0 EXISTS\r\n* OK [UIDVALIDITY '+(b'88' if mode[0]=='changed-validity' else b'77')+b'] stable\r\n* OK [UIDNEXT '+(b'10' if mode[0] in {'headers','changed-uid','changed-validity','search','search-outside','search-duplicate'} or mode[0].startswith('message') else b'3')+b'] next\r\n'+tag.encode()+b' OK [READ-ONLY] examined\r\n')
                    elif verb=='UID':
                        if mode[0].startswith('message'):
                            header=message_header.replace(b'owner@example.invalid',b'other@example.invalid') if mode[0]=='message-unknown' else message_header
                            whole=header+message_body
                            if 'BODY.PEEK[HEADER])' in parts:
                                payload=header;section=b'HEADER'
                            else:
                                assert 'BODY.PEEK[])' in parts;payload=whole;section=b'';body_downloads.append(True)
                                if mode[0]=='message-mutated':payload=whole.replace(b'Approved goal',b'Approved hoax')
                            writer.write(b'* 1 FETCH (UID 9 INTERNALDATE "28-Oct-2026 13:00:00 +0200" RFC822.SIZE '+str(len(whole)).encode()+b' BODY['+section+b'] {'+str(len(payload)).encode()+b'}\r\n'+payload+b')\r\n'+tag.encode()+b' OK fetched\r\n')
                        elif mode[0] in {'search','search-outside','search-duplicate'}:
                            assert parts[2:]==['SEARCH','UID','1:9','SINCE','31-Dec-1969']
                            numbers=b'9 1 3' if mode[0]=='search' else b'1 10' if mode[0]=='search-outside' else b'1 1'
                            writer.write(b'* SEARCH '+numbers+b'\r\n'+tag.encode()+b' OK searched\r\n')
                        elif mode[0] in {'headers','changed-uid'}:
                            assert parts[2:]==['FETCH','9','(UID','INTERNALDATE','RFC822.SIZE','BODY.PEEK[HEADER])']
                            raw=b'Date: Fri, 1 Jan 1999 00:00:00 +0000\r\nFrom: owner@example.invalid\r\nMessage-ID: <mail-9@example.invalid>\r\n\r\n'
                            uid=b'9' if mode[0]=='headers' else b'10'
                            writer.write(b'* 1 FETCH (UID '+uid+b' INTERNALDATE "28-Oct-2026 13:00:00 +0200" RFC822.SIZE 1000 BODY[HEADER] {'+str(len(raw)).encode()+b'}\r\n'+raw+b')\r\n'+tag.encode()+b' OK fetched\r\n')
                        else:
                            assert parts[2:]==['FETCH','1','(BODY.PEEK[HEADER])']
                            # No literal bytes: refusal must precede allocation/read.
                            writer.write(b'* 1 FETCH (BODY[HEADER] {'+str(MAX_HEADERS+1).encode()+b'}\r\n')
                    else:raise AssertionError('unexpected IMAP command; no STORE/CLOSE/EXPUNGE permitted')
                    await writer.drain()
            except (ConnectionError,ssl.SSLError):pass
            finally:
                writer.close()
                try:await writer.wait_closed()
                except (ConnectionError,ssl.SSLError):pass
        async def smtp(reader,writer):
            encrypted=bool(writer.get_extra_info('ssl_object'))
            try:
                writer.write(b'220 localhost HAOS disposable SMTP fixture\r\n');await writer.drain()
                while line:=await reader.readline():
                    verb=line.split(b' ',1)[0].strip().upper();commands.append(('smtp',verb.decode()))
                    if verb in {b'EHLO',b'HELO'}:writer.write(b'250-localhost\r\n250-STARTTLS\r\n250 AUTH PLAIN\r\n')
                    elif verb==b'STARTTLS':
                        assert not encrypted;writer.write(b'220 begin TLS\r\n');await writer.drain();await writer.start_tls(tls);encrypted=True;continue
                    elif verb==b'AUTH':
                        assert encrypted
                        assert base64.b64decode(line.split()[2])==b'\0haos@example.invalid\0private-email-fixture'
                        writer.write(b'535 5.7.8 authentication refused\r\n' if mode[0]=='smtp-auth-refused' else b'235 2.7.0 authenticated\r\n')
                    else:raise AssertionError('unexpected SMTP command; connection probe must never send MAIL/RCPT/DATA')
                    await writer.drain()
            except (ConnectionError,ssl.SSLError):pass
            finally:
                writer.close()
                try:await writer.wait_closed()
                except (ConnectionError,ssl.SSLError):pass
        def current():
            if not allowed[0]:raise PermissionError('fixture owner grant withdrawn')
        for security in ['tls','starttls']:
            imap_server=await asyncio.start_server(imap,'127.0.0.1',0,ssl=tls if security=='tls' else None)
            smtp_server=await asyncio.start_server(smtp,'127.0.0.1',0,ssl=tls if security=='tls' else None)
            value=credentials({'address':'haos@example.invalid','password':'private-email-fixture',
                'imap_host':'localhost','imap_port':imap_server.sockets[0].getsockname()[1],'imap_security':security,
                'smtp_host':'localhost','smtp_port':smtp_server.sockets[0].getsockname()[1],'smtp_security':security,'authserv_id':'mx.example.invalid'})
            def adapter_for(settings):
                env={'EMAIL_'+key.upper():str(item) for key,item in settings.items() if key!='authserv_id'}
                env.update(EMAIL_IMAP_TLS_VERIFY='true',EMAIL_SMTP_TLS_VERIFY='true',EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_TRUST_FROM_HEADER='false')
                with scope(root/('home-'+security),env):return EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))
            adapter=adapter_for(value)
            try:
                result=await asyncio.to_thread(Transport(adapter,value,current).probe)
                assert result=={'imap_authenticated':True,'smtp_authenticated':True,'uid_validity':77,'uid_next':3,'smtp_message_sent':False}
                cases.append('actual_native_'+security+'_imap_and_smtp_authenticate_verified_hostname_and_readonly_uid_state_without_message_send')
                def literal():
                    with Transport(adapter,value,current).imap() as connection:
                        try:connection.uid('FETCH','1','(BODY.PEEK[HEADER])')
                        except ValueError:pass
                        else:raise AssertionError('oversized literal entered the native allocator')
                await asyncio.to_thread(literal)
                cases.append(security+'_announced_oversized_imap_literal_refused_before_reading_its_body')
                def revoked():
                    with Transport(adapter,value,current).imap() as connection:
                        before=len(commands);allowed[0]=False
                        try:connection.noop()
                        except __import__('imaplib').IMAP4.abort as error:
                            assert str(error)=='socket error: fixture owner grant withdrawn'
                        else:raise AssertionError('revoked native IMAP command sent')
                        assert len(commands)==before
                try:await asyncio.to_thread(revoked)
                finally:allowed[0]=True
                cases.append(security+'_owner_revocation_blocks_next_native_command_and_cleanup_does_not_change_remote_mail')
                def mutations():
                    with Transport(adapter,value,current).imap() as connection:
                        before=len(commands)
                        try:connection.store('1','+FLAGS','(\\Deleted)')
                        except __import__('imaplib').IMAP4.abort as error:
                            assert str(error)=='socket error: private mail mutations are not authorized'
                        else:raise AssertionError('mailbox mutation accepted')
                        assert len(commands)==before
                    with Transport(adapter,value,current).smtp() as connection:
                        before=len(commands)
                        try:connection.sendmail(value['address'],'other@example.invalid','unauthorized fixture body')
                        except PermissionError:pass
                        else:raise AssertionError('connection probe gained message-write capability')
                        assert len(commands)==before
                await asyncio.to_thread(mutations)
                cases.append(security+'_imap_delete_flag_mutation_is_denied_before_any_remote_command')
                cases.append(security+'_smtp_probe_cannot_send_mail_without_a_separate_durable_write_capability')
                before=len(commands);adapter._smtp_tls_verify=False
                try:await asyncio.to_thread(Transport(adapter,value,current).probe)
                except PermissionError:pass
                else:raise AssertionError('disabled TLS verification used')
                adapter._smtp_tls_verify=True;assert len(commands)==before
                cases.append(security+'_changed_native_tls_flag_refused_before_connection_or_credentials')
                # The fixture certificate deliberately has DNS SANs, no IP SAN.
                wrong={**value,'imap_host':'127.0.0.1'}
                before=sum(verb=='LOGIN' for protocol,verb in commands)
                try:await asyncio.to_thread(Transport(adapter_for(wrong),wrong,current).probe)
                except ssl.SSLCertVerificationError:pass
                else:raise AssertionError('incorrect peer hostname trusted')
                assert sum(verb=='LOGIN' for protocol,verb in commands)==before
                cases.append(security+'_incorrect_certificate_hostname_refused_before_imap_password')
                for failure in ['imap-auth-refused','smtp-auth-refused']:
                    mode[0]=failure
                    try:await asyncio.to_thread(Transport(adapter,value,current).probe)
                    except (__import__('imaplib').IMAP4.error,__import__('smtplib').SMTPAuthenticationError):pass
                    else:raise AssertionError('native account authentication refusal ignored')
                    cases.append(security+'_'+failure+'_preserved_as_failure_without_outgoing_message')
                mode[0]='headers'
                from haos.gateway_email_imap import get_headers
                from datetime import datetime,timezone
                result=await asyncio.to_thread(get_headers,Transport(adapter,value,current),9,77)
                assert result['internal_at']==datetime(2026,10,28,11,tzinfo=timezone.utc).timestamp()
                assert b'1999' in result['content'] and result['uid']==9
                cases.append(security+'_actual_native_header_fetch_uses_authenticated_internaldate_and_body_peek_not_sender_date_or_read_flags')
                mode[0]='changed-uid'
                try:await asyncio.to_thread(get_headers,Transport(adapter,value,current),9,77)
                except ValueError:pass
                else:raise AssertionError('server changed requested UID without refusal')
                cases.append(security+'_changed_private_uid_resource_is_refused_before_header_admission')
                mode[0]='changed-validity';before=sum(verb=='UID' for protocol,verb in commands)
                from haos.gateway_email_imap import MailboxChanged
                try:await asyncio.to_thread(get_headers,Transport(adapter,value,current),9,77)
                except MailboxChanged:pass
                else:raise AssertionError('reset mailbox epoch reused for a header resource')
                assert sum(verb=='UID' for protocol,verb in commands)==before
                cases.append(security+'_mailbox_epoch_change_is_refused_before_any_private_uid_header_fetch')
                from haos.gateway_email_imap import search
                page={'uid_validity':77,'after':0,'through':9};mode[0]='search'
                result=await asyncio.to_thread(search,Transport(adapter,value,current),page,1)
                assert result=={**page,'uid_next':10,'uids':[1,3,9]}
                cases.append(security+'_actual_native_bounded_uid_search_uses_server_since_date_and_preserves_all_ordered_resources')
                for failure in ['search-outside','search-duplicate']:
                    mode[0]=failure
                    try:await asyncio.to_thread(search,Transport(adapter,value,current),page,1)
                    except ValueError:pass
                    else:raise AssertionError('foreign or duplicate search resources accepted')
                    cases.append(security+'_'+failure+'_is_refused_before_cursor_advance')
                from haos.gateway_email_imap import message
                from haos.gateway_email import PreparedEmailPolicy,scope as mailbox_scope
                from haos.gateway import digest,Conflict
                from haos.gateway_email_admission import Refused
                import hashlib
                binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid',
                    'scope':mailbox_scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}
                config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]}
                policy=lambda:PreparedEmailPolicy(config)
                route={'binding_id':'owner','binding_digest':digest(binding)};mode[0]='message'
                complete=await asyncio.to_thread(message,Transport(adapter,value,current),9,77,hashlib.sha256(message_header).hexdigest(),policy,'email',value,route)
                assert complete['content']==message_header+message_body and complete['approval']['binding_id']=='owner'
                from haos.gateway_email_codec import decode
                assert decode(adapter,complete['content'],value,b'9')['body'].strip()=='Actual scoped email body.'
                cases.append(security+'_actual_full_message_and_native_body_decode_follow_independent_timed_source_approval')
                mode[0]='message-unknown';before=len(body_downloads)
                foreign=message_header.replace(b'owner@example.invalid',b'other@example.invalid')
                try:await asyncio.to_thread(message,Transport(adapter,value,current),9,77,hashlib.sha256(foreign).hexdigest(),policy,'email',value,route)
                except Refused as error:assert error.reason=='unapproved-sender'
                else:raise AssertionError('unapproved sender gained full body access')
                assert len(body_downloads)==before
                cases.append(security+'_unapproved_sender_is_refused_before_full_message_or_attachment_download')
                mode[0]='message';binding['since']=int(time.time()*1000)
                try:await asyncio.to_thread(message,Transport(adapter,value,current),9,77,hashlib.sha256(message_header).hexdigest(),policy,'email',value,route)
                except Refused as error:assert error.reason=='pre-grant'
                else:raise AssertionError('old received email gained a fresh grant')
                assert len(body_downloads)==before;binding['since']=1
                cases.append(security+'_new_grant_does_not_download_old_body_even_with_an_authenticated_sender')
                mode[0]='message-mutated'
                try:await asyncio.to_thread(message,Transport(adapter,value,current),9,77,hashlib.sha256(message_header).hexdigest(),policy,'email',value,route)
                except Conflict:pass
                else:raise AssertionError('full message silently changed approved header resource')
                cases.append(security+'_changed_full_resource_headers_are_refused_before_durable_admission')
                mode[0]='success'
            finally:
                imap_server.close();smtp_server.close();await imap_server.wait_closed();await smtp_server.wait_closed()
        assert not any(verb in {'MAIL','RCPT','DATA','STORE','CLOSE','EXPUNGE'} for protocol,verb in commands)
    with tempfile.TemporaryDirectory(prefix='haos-email-tls-') as name:asyncio.run(exercise(Path(name)))
    report={'passed':len(cases),'cases':cases,'actual_pinned_imap_smtp_clients_and_verified_tls':True,
        'prepared_only_not_public':True,'worker_supervision_is_not_part_of_this_protocol_probe':True,
        'external_accounts_mail_delivery_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
