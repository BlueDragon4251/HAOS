#!/usr/bin/env python3
"""Actual native sender authentication combined with independent HAOS source grants."""
from email import policy as email_policy
from email.message import EmailMessage
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_email import PreparedEmailPolicy,scope
    from haos.gateway_email_admission import approve,Refused
    value={'address':'haos@example.invalid','imap_host':'imap.example.invalid','imap_port':993,'authserv_id':'mx.example.invalid'}
    binding={'id':'owner','connector':'email','sender':'owner@example.invalid','chat':'owner@example.invalid',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'b'*64,'since':1}
    config={'version':1,'connectors':[{'id':'email','platform':'email'}],'bindings':[binding]}
    def resource(sender='owner@example.invalid',auth='mx.example.invalid; dmarc=pass',**extra):
        msg=EmailMessage();msg['From']=sender;msg['To']=value['address'];msg['Message-ID']='<goal-1@example.invalid>'
        msg['Date']='Fri, 1 Jan 1999 00:00:00 +0000';msg['Subject']='Actual approved email goal'
        if auth:msg['Authentication-Results']=auth
        for key,item in extra.items():msg[key]=item
        msg.set_content('A real fixture body, not yet fetched through the receiving service.')
        return {'uid':9,'uid_validity':77,'uid_next':10,'size':1000,'internal_at':time.time()-1,'content':msg.as_bytes(policy=email_policy.SMTP)}
    cases=[]
    good=approve(PreparedEmailPolicy(config),'email',value,resource())
    assert good['envelope']['text']=='' and good['rfc_message_id']=='<goal-1@example.invalid>'
    assert good['received_at']>1700000000 and len(good['envelope']['message_id'])==64
    cases.append('native_authenticated_headers_match_exact_owner_source_without_creating_or_inventing_a_body_goal')
    for packet,reason in [(resource(sender='stranger@example.invalid'),'unapproved-sender'),
        (resource(auth=None),'authentication-refused'),(resource(auth='foreign.invalid; dmarc=pass'),'authentication-refused'),
        (resource(sender=value['address']),'self-or-automated'),(resource(**{'auto-submitted':'auto-generated'}),'self-or-automated'),
        (resource(**{'References':'<unapproved@example.invalid>'}),'unapproved-thread')]:
        try:approve(PreparedEmailPolicy(config),'email',value,packet)
        except Refused as error:assert error.reason==reason
        else:raise AssertionError('unapproved header source accepted')
        cases.append(reason+'_source_refused_before_full_body_or_attachments')
    old=resource();old['internal_at']=time.time()-100
    binding['since']=int((time.time()-10)*1000)
    try:approve(PreparedEmailPolicy(config),'email',value,old)
    except Refused as error:assert error.reason=='pre-grant'
    else:raise AssertionError('pre-grant message approved by sender Date instead of server INTERNALDATE')
    cases.append('new_owner_epoch_cannot_promote_old_received_mail')
    binding['thread']='<root@example.invalid>';binding['since']=1
    result=approve(PreparedEmailPolicy(config),'email',value,resource(**{
        'References':'<root@example.invalid> <later@example.invalid>','In-Reply-To':'<later@example.invalid>'}))
    assert result['envelope']['thread']=='<root@example.invalid>'
    cases.append('exact_root_thread_remains_stable_across_nested_replies')
    report={'passed':len(cases),'cases':cases,'actual_native_header_auth_and_independent_owner_policy':True,
        'prepared_only_not_public':True,'full_body_mission_or_external_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
