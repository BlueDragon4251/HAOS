#!/usr/bin/env python3
"""Actual Tk account/pairing controls; privileged backend calls are fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,google_chat_account_setup as owner
    from haos.initial_setup_gui import Wizard
    from haos.google_chat_account_gui import AccountForm,PairForm
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    account={'project_id':'haos-fixture','service_account_email':'gateway@haos-fixture.iam.gserviceaccount.com','bot_user':'users/999',
        'inbound':{'mode':'pubsub','subscription':'projects/haos-fixture/subscriptions/private','trust_topic_publishers':True},
        'saved_service_account':True,'scope':'google-chat:'+'a'*64}
    calls=[];reads=[];mode={'blocked':False};entered=threading.Event();release=threading.Event();selected={'id':'google-main'}
    secret=json.dumps({'private_fixture':'ephemeral-private-Owner-input'})
    def save(connector,bot,inbound,value,**options):
        if mode['blocked']:entered.set();assert release.wait(5)
        calls.append(('account',connector,bot,deepcopy(inbound),value,options));return {'configured':True}
    def pair(*args,**options):calls.append(('pair',args,options));return {'paired':True}
    owner.save_account=save;initial_setup.pair_gateway_sender=pair
    initial_setup.gateway_configuration=lambda:{'google_chat':{selected['id']:deepcopy(account)}}
    initial_setup.read_line_tls_file=lambda path,kind:reads.append((path,kind)) or 'private-TLS-fixture-'+kind
    w=Wizard(tk)
    for child in w.content.winfo_children():child.destroy()
    refreshed=[];form=AccountForm(w,w.content,lambda:selected['id'],lambda value:refreshed.append(deepcopy(value)))
    form.frame.pack(fill='x');pair_form=PairForm(w,w.content,lambda:selected['id'],lambda:deepcopy(account));pair_form.frame.pack(fill='x');w.root.update();cases=[]
    def settle():
        deadline=time.monotonic()+7
        while w.running and time.monotonic()<deadline:w.root.update();time.sleep(.01)
        w.root.update();assert not w.running
    def fill():
        form.variables['bot'].set('users/999');form.variables['subscription'].set(account['inbound']['subscription']);form.variables['account'].set(secret)
    try:
        fill();before=len(calls);form.save_button.invoke();settle();assert len(calls)==before
        form.confirm.set(True);form.save_button.invoke();settle();assert len(calls)==before
        form.trust.set(True);assert not form.confirm.get();form.confirm.set(True);form.save_button.invoke()
        assert not form.variables['account'].get() and form.fields['account'].cget('show');settle()
        assert calls[-1]==('account','google-main','users/999',account['inbound'],secret,{'keep_service_account':False}) and refreshed==[account]
        cases.append('actual_Tk_requires_exact_account_and_separate_publisher_consent_and_clears_masked_private_JSON_before_async_Root_call')
        form.keep.set(True);form.trust.set(True);form.confirm.set(True);form.save_button.invoke();settle()
        assert calls[-1][-2:]==('',{'keep_service_account':True})
        cases.append('actual_Tk_saved_service_identity_reuse_is_explicit_and_does_not_return_or_reenter_its_private_JSON')
        fill();form.trust.set(True);form.confirm.set(True);form.variables['bot'].set('users/998');assert not form.confirm.get()
        before=len(calls);form.save_button.invoke();settle();assert len(calls)==before
        mode['blocked']=True;entered.clear();release.clear();fill();form.trust.set(True);form.confirm.set(True);form.save_button.invoke()
        assert entered.wait(2);form.variables['bot'].set('users/997');release.set();settle();assert len(refreshed)==2
        mode['blocked']=False;cases.append('actual_async_Tk_edits_invalidate_confirmation_and_late_previous_account_response_without_overwriting_new_input')
        form.mode.set('http');assert not form.keep.get() and not form.trust.get() and not form.variables['account'].get()
        form.variables['account'].set(secret);form.variables['bot'].set('users/999')
        for key,value in [('url','https://chat.example.invalid/google-chat'),('audience','https://chat.example.invalid/google-chat'),
                ('caller','chat@system.gserviceaccount.com'),('certificate','/owner/cert.pem'),('key','/owner/key.pem')]:form.variables[key].set(value)
        form.variables['port'].set('bad');form.confirm.set(True);before=len(calls);form.save_button.invoke();settle()
        assert len(calls)==before and not reads
        form.variables['port'].set('8445');form.bind.set('0.0.0.0');form.public.set(True);form.confirm.set(True);form.save_button.invoke();settle()
        assert calls[-1][3]['tls']=={'public_url':'https://chat.example.invalid/google-chat','bind_host':'0.0.0.0','public_listener':True,
            'certificate':'private-TLS-fixture-certificate','private_key':'private-TLS-fixture-private_key'}
        assert reads==[('/owner/cert.pem','certificate'),('/owner/key.pem','private_key')]
        assert not form.variables['key'].get() and not form.variables['account'].get()
        cases.append('actual_Tk_HTTP_requires_bounded_port_and_explicit_listener_choice_then_reads_only_selected_PEM_paths_inside_Root_backend_action')
        for key,value in [('sender','users/123'),('chat','spaces/space1'),('thread','spaces/space1/threads/thread1')]:pair_form.vars[key].set(value)
        before=len(calls);pair_form.save_button.invoke();settle();assert len(calls)==before
        pair_form.flags['allow_media'].set(True);pair_form.flags['allow_outbound_media'].set(True);pair_form.confirm.set(True);pair_form.save_button.invoke();settle()
        last=calls[-1];assert last[0]=='pair' and last[1]==('google-owner','google-main','users/123','spaces/space1','personal',('create','read'))
        assert last[2]=={'thread':'spaces/space1/threads/thread1','scope':account['scope'],'require_mention':True,'all_threads':False,
            'allow_media':True,'allow_voice':False,'allow_video':False,'allow_outbound_media':True}
        assert not pair_form.confirm.get() and not pair_form.flags['allow_media'].get()
        cases.append('actual_Tk_pairing_freezes_exact_saved_app_user_space_thread_rights_and_separate_media_consents_without_test_message')
        pair_form.flags['allow_voice'].set(True);pair_form.flags['all_threads'].set(True);pair_form.confirm.set(True);pair_form.vars['sender'].set('users/124')
        assert not pair_form.confirm.get() and not pair_form.flags['allow_voice'].get() and not pair_form.flags['all_threads'].get()
        cases.append('actual_Tk_route_edit_clears_previous_whole_space_and_media_permissions_and_confirmation')
        w.show('google-chat-setup');w.root.update();w.viewport.yview_moveto(1);w.root.update()
        assert w.page=='google-chat-setup' and w.content.winfo_height()>w.viewport.winfo_height()
        cases.append('actual_Wizard_constructs_complete_scrollable_account_pairing_OAuth_file_and_recovery_page_at_current_screen_size')
        Path(sys.argv[2]).write_text(json.dumps({'passed':len(cases),'cases':cases,'screen':[w.root.winfo_screenwidth(),w.root.winfo_screenheight()],
            'actual_Tk_and_Wizard_async_controls':True,'privileged_backend_and_TLS_file_reads_are_explicit_fixtures':True,
            'live_Google_account_installed_GUI_external_delivery_or_public_acceptance':False},indent=2)+'\n')
        print(json.dumps({'passed':len(cases)}))
    finally:release.set();w.root.destroy()


if __name__=='__main__':main()
