#!/usr/bin/env python3
"""Actual Tk A2A owner forms; privileged handoffs/account responses are fixtures."""
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,a2a_owner_setup as owner
    from haos.initial_setup_gui import Wizard
    from haos.gateway import digest
    from haos.a2a_owner_process import response,cursor_token
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    private={'agent_name':'HAOS','port':8448,'peer_tokens':{'alice':'private_gui_peer_fixture_'+'a'*32},
        'tls':{'public_url':'https://a2a.fixture.invalid/a2a','bind_host':'127.0.0.1','public_listener':False,
            'certificate':'private GUI certificate fixture','private_key':'private GUI TLS key fixture'},
        'callbacks':{'alice':{'url':'https://peer.fixture.invalid/callback','secret':'private_gui_signing_fixture_'+'b'*32}}}
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'a2a-main','platform':'a2a'}],'bindings':[],
        'a2a':{'a2a-main':owner.public(private)}}
    calls=[];peer_calls=[];pairs=[];inspections=[];recoveries=[];cases=[]
    def save(*args,**kwargs):
        calls.append((args,kwargs));private.update(agent_name=args[1]['agent_name'],port=args[1]['port'])
        return {'configured':True}
    owner.save_account=save;owner.saved=lambda connector:({}, {},private)
    owner.set_peer=lambda *args,**kwargs:peer_calls.append((args,kwargs)) or {'configured':True}
    owner.pair=lambda *args,**kwargs:pairs.append((args,kwargs)) or {'paired':True}
    row={'profile':'a2a-'+'f'*64,'peer_journal':'peer-'+digest('alice'),'task_id':'task-'+'1'*16,'peer':'alice','context':'ctx-owner',
        'native_state':'TASK_STATE_WORKING','parent_admitted':False,'original_id':'2'*64,'source_key':'3'*64,'binding_id':'owner',
        'binding_digest':'4'*64,'credential_scope':'5'*64,'current_account':False,'current_grant':False,'uncertain_transitions':0,'uncertain_controls':0,'uncertain_results':0,
        'callbacks':{'uncertain':1},'original_retained':True,'resources':{'authentication-refused':1},'resource_attempts':1,'resource_retry_at':1}
    row['snapshot_sha256']=digest(row)
    inventory=response({'tasks':[row],'has_more':True,'cursor':cursor_token([0,0,32]),'message_sent':False,'mission_created':False},'sources')
    def inspect(connector,action='inspect',cursor=''):
        inspections.append((connector,action,cursor))
        return inventory if action=='sources' else {'error':'listener-unavailable'}
    owner.inspect=inspect
    owner.recover=lambda *args,**kwargs:recoveries.append((args,kwargs)) or {'action':args[2],'receipt':'6'*64,'affected':1,'removed_bytes':0,'message_sent':False,'mission_created':False}
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix,cls=tk.Entry):
        label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
        siblings=label.master.winfo_children();return next(w for w in siblings[siblings.index(label)+1:] if isinstance(w,cls))
    def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
    def checkbox(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith(prefix))
    def selected(widget):return bool(wizard.root.getboolean(wizard.root.getvar(widget.cget('variable'))))
    def fill(prefix,value):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,value);wizard.root.update();return entry
    def choice(prefix,value):
        menu=field(prefix,tk.OptionMenu);wizard.root.setvar(menu.cget('textvariable'),value);wizard.root.update()
    def settle():
        end=time.monotonic()+5
        while wizard.running and time.monotonic()<end:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update();choice('Plattform','a2a')
        assert field('Öffentlicher A2A-Servername').winfo_viewable() and not field('Bot-Token').winfo_viewable()
        assert str(field('Privater Bearer-Schlüssel').cget('state'))=='disabled' and not field('Privater Bearer-Schlüssel').get()
        assert not field('Private Schlüsseldatei').get()
        cases.append('actual_Tk_A2A_account_hides_unrelated_token_and_never_loads_saved_peer_or_TLS_keys')
        fill('Öffentlicher A2A-Servername','Owner A2A')
        assert not selected(checkbox('Schlüssel des exakt gespeicherten Peers beibehalten'))
        key=fill('Privater Bearer-Schlüssel','private_gui_replacement_fixture_'+'c'*32)
        assert key.cget('show')
        checkbox('Neu eingegebenen Peer-Schlüssel hier anzeigen').invoke();assert not key.cget('show')
        fill('Öffentliche HTTPS-Adresse','https://a2a.fixture.invalid/a2a');assert not key.get() and key.cget('show')
        cases.append('public_identity_change_clears_private_key_and_explicit_show_choice_in_actual_Tk')
        key=fill('Privater Bearer-Schlüssel','private_gui_replacement_fixture_'+'c'*32)
        button('Gateway sicher anlegen').invoke();settle()
        assert len(calls)==1 and calls[0][0][0]=='a2a-main' and calls[0][0][1]['port']==8448
        assert calls[0][1]=={'keep_tls':True,'keep_token':False} and not key.get()
        assert field('Öffentlicher A2A-Servername').get()=='Owner A2A'
        cases.append('actual_Tk_account_save_hands_typed_fields_and_explicit_reuse_to_private_backend_then_refreshes_only_public_metadata')
        button('A2A lokal ohne Nachricht prüfen').invoke();settle()
        assert inspections[-1]==('a2a-main','inspect','') and 'Port' in wizard.status.cget('text')
        cases.append('actual_Tk_no_send_inspection_surfaces_finite_listener_error_without_claiming_external_reachability')
        fill('Exakter gespeicherter oder neuer Peer-Name','bob')
        fill('Neuer privater Peer-Schlüssel','private_gui_bob_fixture_'+'d'*32)
        fill('Genehmigte HTTPS-Download-Ursprünge','https://files.fixture.invalid')
        fill('Exakte HTTPS-Callback-Adresse','https://bob.fixture.invalid/callback')
        signing=fill('Separater privater Callback-Signierschlüssel','private_gui_bob_signing_fixture_'+'e'*32)
        assert signing.cget('show')
        button('Peer-Einstellungen privat speichern').invoke();settle()
        assert peer_calls[-1][0][:2]==('a2a-main','bob') and peer_calls[-1][1]['download_origins']==['https://files.fixture.invalid']
        assert peer_calls[-1][1]['callback_url']=='https://bob.fixture.invalid/callback' and not signing.get()
        cases.append('actual_Tk_peer_editor_hands_separate_masked_key_download_origins_and_exact_callback_to_backend_and_clears_private_fields')
        fill('Absender-ID','alice');fill('Chat-ID','ctx-owner')
        assert str(field('Bereich').cget('state'))=='disabled' and field('Bereich').get().startswith('a2a:')
        assert str(field('Thread').cget('state'))=='disabled'
        assert str(checkbox('Wartende Missionen pausieren').cget('state'))=='disabled'
        checkbox('Bilder und Dokumente für diesen Kontext').invoke()
        checkbox('Status an den separat gespeicherten HTTPS-Callback').invoke()
        assert selected(checkbox('Bilder und Dokumente für diesen Kontext'))
        fill('Chat-ID','ctx-owner-new');assert not selected(checkbox('Bilder und Dokumente für diesen Kontext'))
        cases.append('actual_Tk_exact_context_edits_reset_all_media_callback_consent_and_unimplemented_native_pause_is_disabled')
        checkbox('Bilder und Dokumente für diesen Kontext').invoke();checkbox('Status an den separat gespeicherten HTTPS-Callback').invoke()
        button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1][0][1:5]==('a2a-main','alice','ctx-owner-new',field('HAOS-Identität').get())
        assert pairs[-1][1]['allow_media'] is True and pairs[-1][1]['allow_callback'] is True and pairs[-1][1]['allow_voice'] is False
        assert not selected(checkbox('Status an den separat gespeicherten HTTPS-Callback'))
        cases.append('actual_Tk_pairing_passes_exact_saved_peer_context_and_separate_flags_then_resets_consent')
        button('A2A-Tasks lokal prüfen').invoke();settle()
        assert inspections[-1]==('a2a-main','sources','')
        texts='\n'.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'authentication-refused' in texts and 'uncertain' in texts and 'Aktuelle exakte Freigabe: nein' in texts
        assert all(secret not in texts for secret in [*private['peer_tokens'].values(),private['callbacks']['alice']['secret'],private['tls']['private_key']])
        button('Nächste A2A-Task-Seite').invoke();settle();assert inspections[-1][2]==inventory['cursor']
        cases.append('actual_Tk_private_history_shows_revoked_account_and_resource_callback_failures_without_keys_and_requests_real_cursor_pages')
        button('Geprüfte A2A-Recovery lokal ausführen').invoke();settle();assert recoveries==[]
        fill('Eigene Prüfung und Entscheidung','fixture owner reviewed the exact retained source')
        checkbox('Diesen Task, Freigaben und unklare Vorgänge geprüft').invoke()
        choice('Explizite lokale Recovery-Aktion','Original und private Eingangssnapshots entfernen')
        assert not selected(checkbox('Diesen Task, Freigaben und unklare Vorgänge geprüft')) and not field('Eigene Prüfung und Entscheidung').get()
        fill('Eigene Prüfung und Entscheidung','fixture owner reviewed revoked terminal source')
        checkbox('Diesen Task, Freigaben und unklare Vorgänge geprüft').invoke()
        button('Geprüfte A2A-Recovery lokal ausführen').invoke();settle()
        assert recoveries[-1][0][0:3]==('a2a-main',row,'purge-source-inputs') and recoveries[-1][1]=={'confirmed':True}
        assert not selected(checkbox('Diesen Task, Freigaben und unklare Vorgänge geprüft')) and not field('Eigene Prüfung und Entscheidung').get()
        assert 'Lokale Recovery quittiert' in wizard.status.cget('text')
        cases.append('actual_Tk_recovery_requires_explicit_review_and_resets_confirmation_on_action_change_then_passes_exact_snapshot_to_backend_fixture')
        choice('Plattform','telegram')
        assert not field('Öffentlicher A2A-Servername').winfo_viewable() and field('Bot-Token').winfo_viewable()
        assert not field('Privater Bearer-Schlüssel').get() and not field('Separater privater Callback-Signierschlüssel').get()
        cases.append('platform_switch_hides_A2A_fields_and_clears_all_transient_private_material')
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk':True,
            'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'privileged_handoffs_and_account_responses_are_fixtures':True,'installed_GUI_public_activation_or_external_delivery':False},indent=2))
    finally:wizard.root.destroy()


if __name__=='__main__':main()
