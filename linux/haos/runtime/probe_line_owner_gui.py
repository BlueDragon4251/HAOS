#!/usr/bin/env python3
"""Actual LINE Tk controls; backend handoffs are explicit nonprivileged fixtures."""
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
    destination='U'+'d'*32;sender='U'+'a'*32
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'line-main','platform':'line'}],'bindings':[],
        'line':{'line-main':{'destination':destination,'port':8646,'public_url':'https://line.fixture.invalid/line/webhook','bind_host':'127.0.0.1'}}}
    calls=[];pairs=[];retries=[];imports=[];cases=[]
    initial_setup.configure_line_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    initial_setup.retry_line_gateway_auth=lambda connector:retries.append(connector) or {'network_requested':False}
    filedialog.askopenfilename=lambda **kwargs:'/fixture/private.pem'
    def import_pem(filename,kind):
        imports.append((filename,kind));return 'PRIVATE-PEM-FIXTURE-'+kind
    initial_setup.import_line_tls_file=import_pem
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix):
        for widget in widgets(wizard.content):
            if isinstance(widget,tk.Label) and widget.cget('text').startswith(prefix):
                siblings=widget.master.winfo_children();offset=siblings.index(widget)
                return next(child for child in siblings[offset+1:] if isinstance(child,tk.Entry))
        raise AssertionError('missing LINE field '+prefix)
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
        button('LINE-Zertifikatskette laden').invoke();settle()
        button('LINE-TLS-Schlüssel laden').invoke();settle()
    try:
        wizard.show('gateways');wizard.root.update()
        platform=choice('Plattform');wizard.root.setvar(platform.cget('textvariable'),'line');wizard.root.update()
        assert field('Konnektor-ID').get()=='line-main'
        assert field('LINE Bot-Destination').get()==destination and field('LINE lokaler HTTPS-Port').get()=='8646'
        assert not field('Bot-Token').master.winfo_manager()
        assert field('Bereich').get()==destination
        assert str(field('Bereich').cget('state'))==str(field('Thread-ID').cget('state'))=='disabled'
        cases.append('actual_dropdown_restores_public_line_context_and_exact_bot_scope_without_generic_token')
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'CGNAT' in labels and 'Port 443' in labels and 'Video und ausgehende Medien sind noch nicht freigegeben' in labels and 'Sprachnachrichten benötigen eine eigene Freigabe' in labels
        assert 'höchstens 2 MiB' in labels and 'höchstens 8 MiB' in labels
        assert 'keinen Empfang' in labels and 'alle Mitglieder' in labels
        cases.append('actual_help_explains_dns_tls_router_cgnat_shared_replies_and_media_recipient_limits')
        load_material()
        assert imports==[('/fixture/private.pem','certificate'),('/fixture/private.pem','private_key')]
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'Privat geladen: Zertifikatskette, Schlüssel' in labels and 'PRIVATE-PEM-FIXTURE' not in labels
        cases.append('actual_file_buttons_load_separate_private_pem_without_showing_bytes')
        secret=fill('LINE Channel-Secret','a'*32);access=fill('LINE Channel-Access-Token','private-gui-line-access')
        assert secret.cget('show') and access.cget('show')
        button('Gateway sicher anlegen').invoke();settle()
        args,value=calls[-1]
        assert args==('line-main',) and value['channel_secret']=='a'*32 and value['channel_access_token']=='private-gui-line-access'
        assert value['destination']==destination and value['port']==8646
        assert value['tls']=={'public_url':'https://line.fixture.invalid/line/webhook','bind_host':'127.0.0.1','public_listener':False,
            'certificate':'PRIVATE-PEM-FIXTURE-certificate','private_key':'PRIVATE-PEM-FIXTURE-private_key'}
        assert not secret.get() and not access.get()
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'Noch kein privates TLS-Material geladen.' in labels
        cases.append('actual_setup_handoff_captures_all_inputs_then_clears_tokens_and_pem')
        fill('Absender-ID',sender);fill('Chat-ID','C'+'b'*32)
        button('Absender mit ausgewählten Rechten').invoke();settle()
        assert pairs[-1][0][:4]==('my-device','line-main',sender,'C'+'b'*32)
        assert pairs[-1][1]=={'scope':destination,'thread':'','allow_media':False,'allow_voice':False}
        cases.append('actual_pair_handoff_binds_exact_sender_chat_destination_and_selected_mission_rights')
        media=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Eingehende LINE-Bilder'))
        assert not wizard.root.getvar(media.cget('variable'))
        media.invoke();button('Absender mit ausgewählten Rechten').invoke();settle()
        assert pairs[-1][1]['allow_media'] is True and not wizard.root.getvar(media.cget('variable'))
        cases.append('actual_explicit_line_image_document_consent_reaches_owner_backend_and_clears_after_submit')
        media.invoke();fill('Absender-ID','U'+'b'*32)
        assert not wizard.root.getvar(media.cget('variable'))
        fill('Absender-ID',sender)
        cases.append('actual_sender_edit_withdraws_pending_media_consent')
        create=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text')=='Missionen erstellen')
        media.invoke();create.invoke()
        assert not wizard.root.getvar(media.cget('variable')) and str(media.cget('state'))=='disabled'
        create.invoke();assert str(media.cget('state'))=='normal' and not wizard.root.getvar(media.cget('variable'))
        cases.append('actual_no_create_permission_disables_media_without_restoring_earlier_consent')
        voice=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Eingehende LINE-Sprachnachrichten'))
        assert not wizard.root.getvar(voice.cget('variable'))
        voice.invoke();button('Absender mit ausgewählten Rechten').invoke();settle()
        assert pairs[-1][1]['allow_voice'] is True and pairs[-1][1]['allow_media'] is False
        assert not wizard.root.getvar(voice.cget('variable'))
        voice.invoke();fill('Absender-ID','U'+'b'*32)
        assert not wizard.root.getvar(voice.cget('variable'));fill('Absender-ID',sender)
        voice.invoke();create.invoke()
        assert str(voice.cget('state'))=='disabled' and not wizard.root.getvar(voice.cget('variable'))
        create.invoke();assert str(voice.cget('state'))=='normal' and not wizard.root.getvar(voice.cget('variable'))
        cases.append('actual_separate_voice_consent_reaches_owner_backend_without_media_and_resets_on_submit_sender_edit_and_create_withdrawal')

        button('LINE-Konto nach Korrektur erneut prüfen').invoke();settle()
        assert retries==['line-main']
        cases.append('actual_auth_recheck_uses_real_owner_backend_without_sending')
        load_material();fill('LINE Channel-Secret','b'*32);fill('LINE Channel-Access-Token','private-clear-fixture')
        fill('LINE öffentliche HTTPS-Adresse','https://changed.fixture.invalid/line/webhook')
        assert not secret.get() and not access.get()
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'Noch kein privates TLS-Material geladen.' in labels
        cases.append('actual_endpoint_edit_discards_private_tokens_and_certificate_material')
        started=threading.Event();release=threading.Event()
        def deferred_import(_filename,_kind):
            started.set();assert release.wait(4);return 'stale-private-pem-fixture'
        initial_setup.import_line_tls_file=deferred_import
        button('LINE-TLS-Schlüssel laden').invoke()
        assert started.wait(2)
        fill('LINE öffentliche HTTPS-Adresse','https://new.fixture.invalid/line/webhook')
        release.set();settle();initial_setup.import_line_tls_file=import_pem
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'Noch kein privates TLS-Material geladen.' in labels and 'stale-private-pem-fixture' not in labels
        cases.append('actual_background_pem_import_is_discarded_after_context_revision')
        bind=choice('LINE Listener-Adresse');wizard.root.setvar(bind.cget('textvariable'),'0.0.0.0');wizard.root.update()
        public=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Öffentlichen LINE-Listener'))
        assert not wizard.root.getvar(public.cget('variable'))
        public.invoke();load_material();fill('LINE Channel-Secret','c'*32);fill('LINE Channel-Access-Token','private-public-fixture')
        button('Gateway sicher anlegen').invoke();settle()
        assert calls[-1][1]['tls']['bind_host']=='0.0.0.0' and calls[-1][1]['tls']['public_listener'] is True
        assert not wizard.root.getvar(public.cget('variable'))
        cases.append('actual_public_bind_requires_separate_captured_consent_and_clears_it_after_submit')
        before=len(calls);fill('LINE lokaler HTTPS-Port','private-not-a-port');button('Gateway sicher anlegen').invoke();settle()
        assert len(calls)==before and 'private-not-a-port' not in wizard.status.cget('text')
        cases.append('actual_invalid_port_never_reaches_backend_or_echoes_raw_input')
        fill('LINE lokaler HTTPS-Port','8646');load_material();fill('LINE Channel-Secret','d'*32);fill('LINE Channel-Access-Token','private-connector-fixture')
        fill('Konnektor-ID','line-other')
        assert not secret.get() and not access.get()
        cases.append('actual_connector_edit_withdraws_stale_private_inputs')
        fill('LINE Channel-Secret','e'*32);fill('LINE Channel-Access-Token','private-platform-fixture')
        wizard.root.setvar(platform.cget('textvariable'),'telegram');wizard.root.update()
        assert not secret.get() and not access.get() and not line_visible(secret)
        cases.append('actual_platform_change_clears_and_hides_line_credentials')
        wizard.root.update_idletasks()
        assert wizard.root.winfo_reqwidth()<=max(640,wizard.root.winfo_screenwidth())
        cases.append('actual_owner_controls_fit_available_screen_width')
    finally:wizard.root.destroy()
    result={'passed':len(cases),'cases':cases,'actual_tk':True,'backend_handoffs_are_fixtures':True,'external_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


def line_visible(entry):return bool(entry.master.winfo_manager())


if __name__=='__main__':main()
