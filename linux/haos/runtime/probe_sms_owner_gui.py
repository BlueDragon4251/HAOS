#!/usr/bin/env python3
"""Actual SMS Tk controls with explicit nonprivileged owner handoff fixtures."""
import json
from pathlib import Path
import sys
import threading
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from tkinter import filedialog
    from haos import initial_setup
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True
    initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    account='AC'+'a'*32;number='+12025550100';sender='+12025550101';scope=account+':'+number
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'sms-main','platform':'sms'}],'bindings':[],
        'sms':{'sms-main':{'account_sid':account,'from_number':number,'port':8647,
            'public_url':'https://sms.fixture.invalid/webhooks/twilio','bind_host':'127.0.0.1'}}}
    calls=[];pairs=[];retries=[];imports=[];cases=[]
    initial_setup.configure_sms_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    initial_setup.retry_sms_gateway_auth=lambda connector:retries.append(connector) or {'network_requested':False}
    filedialog.askopenfilename=lambda **kwargs:'/fixture/private.pem'
    def import_pem(filename,kind):
        imports.append((filename,kind));return 'PRIVATE-PEM-FIXTURE-'+kind
    initial_setup.import_line_tls_file=import_pem
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix):
        label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
        siblings=label.master.winfo_children();offset=siblings.index(label)
        return next(w for w in siblings[offset+1:] if isinstance(w,tk.Entry))
    def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
    def choice(prefix):
        label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
        siblings=label.master.winfo_children();offset=siblings.index(label)
        return next(w for w in siblings[offset+1:] if isinstance(w,tk.OptionMenu))
    def fill(prefix,value):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,value);wizard.root.update();return entry
    def settle():
        end=time.time()+5
        while wizard.running and time.time()<end:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    def load_material():
        button('SMS-Zertifikatskette laden').invoke();settle();button('SMS-TLS-Schlüssel laden').invoke();settle()
    def checkbox(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith(prefix) and w.winfo_viewable())
    def checked(widget):return bool(wizard.root.getvar(widget.cget('variable')))
    try:
        wizard.show('gateways');wizard.root.update()
        platform=choice('Plattform');wizard.root.setvar(platform.cget('textvariable'),'sms');wizard.root.update()
        assert field('Konnektor-ID').get()=='sms-main'
        assert field('Twilio Account SID').get()==account and field('Eigene Twilio-Empfangsnummer').get()==number
        assert field('SMS lokaler HTTPS-Port').get()=='8647' and field('Bereich').get()==scope
        assert str(field('Bereich').cget('state'))==str(field('Thread-ID').cget('state'))=='disabled'
        assert not field('Bot-Token').master.winfo_manager()
        cases.append('actual_public_sms_dropdown_restores_account_number_tls_context_and_exact_disabled_scope_without_generic_bot_token')
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        for text in ['/webhooks/twilio','Kosten verursachen','Mobilfunkanbieter','500 KB','lokalen Spracherkennungsdienst','Download-Links']:assert text in labels
        cases.append('actual_help_explains_account_webhook_costs_carrier_mms_limits_local_speech_and_download_fallback')
        load_material();secret=fill('Twilio Auth-Token','b'*32);assert secret.cget('show')
        button('Gateway sicher anlegen').invoke();settle();args,value=calls[-1]
        assert args==('sms-main',) and value['account_sid']==account and value['auth_token']=='b'*32 and value['from_number']==number and value['port']==8647
        assert value['tls']=={'public_url':'https://sms.fixture.invalid/webhooks/twilio','bind_host':'127.0.0.1','public_listener':False,
            'certificate':'PRIVATE-PEM-FIXTURE-certificate','private_key':'PRIVATE-PEM-FIXTURE-private_key'}
        assert not secret.get()
        cases.append('actual_sms_setup_captures_private_token_and_pem_then_clears_private_controls')
        fill('Absender-ID',sender);fill('Chat-ID',sender)
        incoming=checkbox('Eingehende SMS-Bilder');voice=checkbox('Eingehende SMS-Sprachnachrichten');video=checkbox('Eingehende SMS-MP4-')
        outgoing=checkbox('Explizit markierte Ergebnisdateien')
        assert not any(checked(w) for w in [incoming,voice,video,outgoing])
        for widget in [incoming,voice,video,outgoing]:widget.invoke()
        button('Absender mit ausgewählten Rechten').invoke();settle()
        assert pairs[-1][0][2:4]==(sender,sender) and pairs[-1][1]['scope']==scope and pairs[-1][1]['thread']==''
        assert all(pairs[-1][1][key] is True for key in ['allow_media','allow_voice','allow_video','allow_outbound_media'])
        assert not any(checked(w) for w in [incoming,voice,video,outgoing])
        cases.append('four_separate_unchecked_media_consents_reach_exact_owner_route_and_reset_after_submit')
        for widget in [incoming,voice,video,outgoing]:widget.invoke()
        fill('Absender-ID','+12025550199');assert not any(checked(w) for w in [incoming,voice,video,outgoing])
        cases.append('sender_edit_withdraws_all_pending_media_consents')
        create=checkbox('Missionen erstellen');voice.invoke();create.invoke()
        assert str(voice.cget('state'))=='disabled' and not checked(voice)
        create.invoke();assert str(voice.cget('state'))=='normal' and not checked(voice)
        cases.append('create_withdrawal_disables_voice_images_and_video_without_restoring_old_consent')
        button('SMS-Konto nach Korrektur erneut prüfen').invoke();settle();assert retries==['sms-main']
        cases.append('actual_auth_recheck_routes_to_owner_backend_without_sending')
        load_material();fill('Twilio Auth-Token','c'*32);fill('SMS öffentliche HTTPS-Adresse','https://new.fixture.invalid/webhooks/twilio')
        assert not secret.get()
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label));assert 'PRIVATE-PEM-FIXTURE' not in labels
        cases.append('public_endpoint_edit_discards_token_and_private_pem_without_displaying_bytes')
        started=threading.Event();release=threading.Event()
        def deferred(_filename,_kind):started.set();assert release.wait(4);return 'STALE-PRIVATE-PEM'
        initial_setup.import_line_tls_file=deferred;button('SMS-TLS-Schlüssel laden').invoke();assert started.wait(2)
        fill('SMS öffentliche HTTPS-Adresse','https://another.fixture.invalid/webhooks/twilio');release.set();settle();initial_setup.import_line_tls_file=import_pem
        assert 'STALE-PRIVATE-PEM' not in ' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        cases.append('stale_background_pem_import_is_refused_after_context_revision')
        bind=choice('SMS Listener-Adresse');wizard.root.setvar(bind.cget('textvariable'),'0.0.0.0');wizard.root.update()
        public=checkbox('Öffentlichen SMS-Listener');assert not checked(public);public.invoke();load_material();fill('Twilio Auth-Token','d'*32)
        button('Gateway sicher anlegen').invoke();settle()
        assert calls[-1][1]['tls']['bind_host']=='0.0.0.0' and calls[-1][1]['tls']['public_listener'] is True and not checked(public)
        cases.append('public_listener_approval_is_captured_separately_and_cleared_after_submit')
        before=len(calls);fill('SMS lokaler HTTPS-Port','private-invalid-port');button('Gateway sicher anlegen').invoke();settle()
        assert len(calls)==before and 'private-invalid-port' not in wizard.status.cget('text')
        cases.append('invalid_listener_port_never_reaches_backend_or_echoes_input')
        fill('Twilio Auth-Token','e'*32);wizard.root.setvar(platform.cget('textvariable'),'telegram');wizard.root.update()
        assert not secret.get() and not secret.master.winfo_manager()
        cases.append('platform_switch_clears_and_hides_sms_private_controls')
        assert wizard.root.winfo_reqwidth()<=max(640,wizard.root.winfo_screenwidth())
        cases.append('actual_owner_controls_fit_available_screen_width')
    finally:wizard.root.destroy()
    result={'passed':len(cases),'cases':cases,'actual_tk':True,'backend_handoffs_are_fixtures':True,'external_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
