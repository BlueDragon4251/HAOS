#!/usr/bin/env python3
"""Pinned native email MIME/authentication codecs; no account or network connection."""
from email import policy
from email.message import EmailMessage
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_email import credentials
    from haos.gateway_email_codec import decode
    from haos.gateway_matrix_profile import scope
    from gateway.config import PlatformConfig
    from plugins.platforms.email.adapter import EmailAdapter
    value=credentials({'address':'haos@example.invalid','password':'private-email-fixture','imap_host':'imap.example.invalid',
        'imap_port':993,'imap_security':'tls','smtp_host':'smtp.example.invalid','smtp_port':587,'smtp_security':'starttls','authserv_id':'mx.example.invalid'})
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-email-codec-') as name:
        os.environ['HERMES_SAFE_MODE']='1'
        settings={'EMAIL_ADDRESS':value['address'],'EMAIL_PASSWORD':value['password'],'EMAIL_IMAP_HOST':value['imap_host'],
            'EMAIL_SMTP_HOST':value['smtp_host'],'EMAIL_TRUST_FROM_HEADER':'false','EMAIL_AUTHSERV_ID':value['authserv_id'],
            'EMAIL_ALLOW_ALL_USERS':'false','GATEWAY_ALLOW_ALL_USERS':'false'}
        with scope(Path(name),settings):adapter=EmailAdapter(PlatformConfig(enabled=True,extra={'skip_attachments':True,'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))
        def wire(results=None,*,sender='Owner <owner@example.invalid>',attachment=False):
            msg=EmailMessage();msg['From']=sender;msg['To']=value['address'];msg['Message-ID']='<fixture-1@example.invalid>'
            msg['Subject']='A native email goal';msg.set_content('Actual decoded email body. Grüße!')
            for result in results or []:msg['Authentication-Results']=result
            if attachment:msg.add_attachment(b'private attachment fixture',maintype='application',subtype='pdf',filename='../../owner-secret')
            return msg.as_bytes(policy=policy.SMTP)
        for method in ['dmarc=pass header.from=example.invalid','dkim=pass header.d=example.invalid','spf=pass smtp.mailfrom=owner@example.invalid']:
            result=decode(adapter,wire(['mx.example.invalid; '+method]),value,b'1')
            assert result['sender_addr']=='owner@example.invalid' and 'Grüße!' in result['body'] and result['attachments']==[]
            cases.append('actual_native_'+method.split('=')[0]+'_authenticated_mime_body_decode')
        bad=[[],['foreign.invalid; dmarc=pass'],['sub.mx.example.invalid; dmarc=pass'],
            ['mx.example.invalid; dmarc=fail','mx.example.invalid; dmarc=pass'],
            ['foreign.invalid; dmarc=fail','mx.example.invalid; dmarc=pass'],
            ['mx.example.invalid; dkim=pass header.d=foreign.invalid'],['mx.example.invalid; spf=pass smtp.mailfrom=owner@foreign.invalid']]
        for index,results in enumerate(bad):
            try:decode(adapter,wire(results),value,b'2')
            except PermissionError:pass
            else:raise AssertionError('untrusted or injected email authentication accepted')
            cases.append('untrusted_authentication_case_'+str(index)+'_refused_before_native_body_or_attachment_use')
        result=decode(adapter,wire(['mx.example.invalid; dmarc=pass'],attachment=True),value,b'3')
        assert result['attachments']==[]
        assert not list(Path(name).rglob('*.pdf'))
        cases.append('native_header_body_pass_never_writes_or_exposes_unapproved_attachment_paths')
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        folded=MIMEMultipart();folded['From']='owner@example.invalid';folded['Authentication-Results']='mx.example.invalid; dmarc=pass'
        source_id='<'+('a'*64)+'@example.invalid>';folded['Message-ID']=source_id;folded.attach(MIMEText('A native folded ID goal.','plain','utf-8'))
        raw_folded=folded.as_bytes(policy=policy.compat32.clone(linesep='\r\n'))
        assert b'Message-ID: \r\n '+source_id.encode() in raw_folded
        parsed=decode(adapter,raw_folded,value,b'5');assert parsed['message_id']==source_id
        cases.append('actual_native_compat32_folded_message_id_is_canonicalized_only_at_outer_header_whitespace')
        bad_id=raw_folded.replace(source_id.encode(),source_id.encode()+b' <other@example.invalid>')
        try:decode(adapter,bad_id,value,b'6')
        except ValueError:pass
        else:raise AssertionError('fold normalization admitted a second message identifier')
        cases.append('folded_message_id_normalization_cannot_admit_multiple_ids_or_internal_control_syntax')
        raw=wire(['mx.example.invalid; dmarc=pass']).replace(b'From: Owner',b'From: forged@example.invalid\r\nFrom: Owner',1)
        try:decode(adapter,raw,value,b'4')
        except ValueError:pass
        else:raise AssertionError('duplicate From accepted')
        cases.append('duplicate_sender_header_refused_before_native_decode')
        try:decode(adapter,wire(['mx.example.invalid; dmarc=pass']),value,b'4294967296')
        except PermissionError:pass
        else:raise AssertionError('unbounded IMAP UID accepted')
        cases.append('out_of_range_imap_uid_refused')
    report={'passed':len(cases),'cases':cases,'actual_pinned_native_email_codecs':True,'public_registry_enabled':True,
        'network_accounts_delivery_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
