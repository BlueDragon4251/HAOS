#!/usr/bin/env python3
"""Actual Tk owner form; privileged handoffs and account responses are fixtures."""
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,feishu_owner_setup as owner
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    initial_setup.gateway_configuration=lambda:{'connectors':[],'bindings':[]}
    calls=[];checks=[];retries=[];pairs=[];cases=[]
    owner.configure=lambda *args:calls.append(args)
    owner.inspect=lambda connector:checks.append(connector) or {'error':'identity-refused'}
    owner.retry_auth=lambda connector:retries.append(connector)
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix,cls=tk.Entry):
        label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
        siblings=label.master.winfo_children();return next(w for w in siblings[siblings.index(label)+1:] if isinstance(w,cls))
    def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
    def fill(prefix,value):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,value);wizard.root.update();return entry
    def choice(prefix,value):
        menu=field(prefix,tk.OptionMenu);wizard.root.setvar(menu.cget('textvariable'),value);wizard.root.update()
    def settle():
        end=time.monotonic()+5
        while wizard.running and time.monotonic()<end:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update();choice('Plattform','feishu');fill('Konnektor-ID','feishu-main')
        for label,value in [('Feishu-App-ID','cli_0123456789abcdef'),('Feishu-Tenant-Key','tenant_fixture_01'),('Feishu-Bot-Open-ID','ou_'+'a'*32)]:fill(label,value)
        secret=fill('Feishu-App-Secret','private-feishu-form-fixture')
        assert secret.cget('show') and secret.winfo_viewable() and not field('Bot-Token').winfo_viewable()
        cases.append('actual_Tk_Feishu_form_masks_secret_and_hides_unrelated_generic_token')
        fill('Feishu-App-ID','cli_fedcba9876543210');assert secret.get()==''
        cases.append('app_identity_change_clears_private_secret_and_listener_consent')
        fill('Feishu-App-Secret','private-feishu-form-fixture');button('Gateway sicher anlegen').invoke();settle()
        assert len(calls)==1 and calls[0][0]=='feishu-main' and calls[0][1]['connection_mode']=='websocket'
        assert set(calls[0][1])=={'app_id','app_secret','tenant_key','bot_open_id','domain','connection_mode'} and secret.get()==''
        cases.append('websocket_owner_handoff_contains_exact_account_without_unused_webhook_secrets')
        button('Feishu-Konto ohne Nachricht prüfen').invoke();settle()
        assert checks==['feishu-main'] and 'identity-refused' in wizard.status.cget('text')
        button('Feishu-Anmeldung erneut erlauben').invoke();settle();assert retries==['feishu-main']
        cases.append('no_send_account_and_auth_retry_buttons_have_real_separate_owner_handoffs_and_finite_errors')
        fill('Absender-ID','ou_'+'b'*32);fill('Chat-ID','oc_'+'c'*32);fill('Thread-ID','omt_'+'d'*32)
        from haos.gateway_feishu import scope
        expected=scope(calls[0][1]);assert field('Bereich').get()==expected and str(field('Bereich').cget('state'))=='disabled'
        media=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Feishu-Bilder'))
        outbound=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Markierte Ergebnisdateien an diesen Feishu'))
        assert not wizard.root.getvar(media.cget('variable')) and not wizard.root.getvar(outbound.cget('variable'))
        media.invoke();outbound.invoke();fill('Absender-ID','ou_'+'e'*32)
        assert not wizard.root.getvar(media.cget('variable')) and not wizard.root.getvar(outbound.cget('variable'))
        cases.append('exact_app_scope_is_derived_and_sender_edit_resets_separate_default_denied_media_consents')
        media.invoke();outbound.invoke();button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1][0][2:4]==('ou_'+'e'*32,'oc_'+'c'*32)
        assert pairs[-1][1]['scope']==expected and pairs[-1][1]['thread']=='omt_'+'d'*32
        assert pairs[-1][1]['allow_media'] is True and pairs[-1][1]['allow_outbound_media'] is True and pairs[-1][1]['require_mention'] is True
        assert pairs[-1][1]['allow_voice'] is False and not wizard.root.getvar(media.cget('variable'))
        cases.append('exact_open_ID_chat_topic_and_separate_grants_reach_owner_pairing_then_consents_clear')
        choice('Feishu-Verbindung','webhook');assert field('Feishu-Verification-Token').winfo_viewable()
        fill('Feishu-HTTPS-Port','not-a-port');fill('Feishu-App-Secret','private-feishu-form-fixture')
        fill('Feishu-Verification-Token','private-feishu-verification');fill('Feishu-Encrypt-Key','private-feishu-encryption')
        button('Gateway sicher anlegen').invoke();settle();assert len(calls)==1 and secret.get()==''
        assert field('Feishu-Verification-Token').get()==field('Feishu-Encrypt-Key').get()==''
        cases.append('webhook_fields_are_real_and_invalid_port_refuses_handoff_while_clearing_all_secrets')
        choice('Feishu-Verbindung','websocket');assert not field('Feishu-Verification-Token').winfo_viewable()
        fill('Feishu-App-Secret','private-feishu-form-fixture');choice('Plattform','telegram')
        assert secret.get()=='' and not secret.winfo_viewable()
        labels='\n'.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'private-feishu-form-fixture' not in labels+wizard.status.cget('text')
        cases.append('mode_and_platform_switch_clear_secrets_without_secret_in_status_or_labels')
        from tkinter import messagebox
        messagebox.askyesno=lambda *_args,**_kwargs:True
        recovery_calls=[]
        owner.recovery=lambda *args,**kwargs:recovery_calls.append((args,kwargs))
        from haos.feishu_owner_gui import LABELS
        uncertain={'platform':'feishu','connector':'feishu-main','delivery_id':'a'*64,'part':1,'operation':'reply',
            'attempt':1,'state':'uncertain','snapshot_sha256':'b'*64}
        known={**uncertain,'part':0,'state':'confirmed'}
        other={**uncertain,'part':2,'snapshot_sha256':'c'*64}
        initial_setup.gateway_ingress=lambda after=0:{'ingress':[],'history':[],'native_outgoing':[known,uncertain,other],
            'transport':[{'platform':'feishu','connector':'feishu-main','status':state,'updated_at':123,'next_attempt':0} for state in LABELS]}
        wizard.show('gateways');wizard.root.update()
        button('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen').invoke();settle()
        labels='\n'.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert all(label in labels for label in LABELS.values()) and 'API-Annahme ist kein Lesebeleg' in labels
        cases.append('every_finite_Feishu_transport_state_and_distinct_part_acceptance_is_displayed_without_receipt_body')
        button('Geprüfte Feishu-Teilsperre freigeben').invoke();settle();assert not recovery_calls
        cases.append('no_independent_non_acceptance_checkbox_means_no_owner_retry_handoff')
        fill('Feishu-Prüfnotiz','Exact reply non-acceptance independently inspected')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Nichtannahme dieses'))
        check.invoke();button('Geprüfte Feishu-Teilsperre freigeben').invoke();settle()
        assert recovery_calls[-1][0][0]==uncertain and recovery_calls[-1][0][1]=='approve-feishu-part-retry'
        assert recovery_calls[-1][1]=={'confirmed_not_accepted':True}
        cases.append('selected_part_operation_snapshot_and_non_acceptance_confirmation_reach_separate_owner_handoff')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Nichtannahme dieses'))
        check.invoke();menu=field('Geprüfter Feishu-Schreibversuch',tk.OptionMenu)
        options=wizard.root.nametowidget(menu.cget('menu'));assert options.index('end')==1
        options.invoke(1);wizard.root.update();assert not wizard.root.getvar(check.cget('variable'))
        cases.append('changing_selected_part_clears_confirmation_and_confirmed_parts_are_not_retry_choices')
        profile='feishu-'+'d'*64
        retained={'id':'e'*64,'purge_allowed':True,'purged':False,'stored_bytes':100,'snapshot_sha256':'f'*64}
        active={**retained,'id':'1'*64,'purge_allowed':False,'snapshot_sha256':'2'*64}
        def source_inventory(selected_profile=None,kind=None):
            if selected_profile is None:return {'profiles':[{'profile':profile,'kinds':{'original':{}}}]}
            assert selected_profile==profile and kind=='original'
            return {'profile':profile,'kind':kind,'sources':[retained,active]}
        owner.sources=source_inventory
        wizard.show('gateway-feishu-sources');wizard.root.update();button('Feishu-Profile prüfen').invoke();settle()
        button('Feishu-Quellmetadaten laden').invoke();settle()
        before=len(recovery_calls);button('Geprüfte Feishu-Quelldaten entfernen').invoke();settle();assert len(recovery_calls)==before
        fill('Feishu-Löschprüfnotiz','Withdrawn source independently inspected')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Ausgewählte Quelldaten'))
        check.invoke();button('Geprüfte Feishu-Quelldaten entfernen').invoke();settle()
        assert recovery_calls[-1][0][0]=={**retained,'profile':profile,'kind':'original'} and recovery_calls[-1][0][1]=='purge-feishu-source'
        cases.append('explicit_source_disposal_carries_exact_profile_kind_and_snapshot_without_returning_raw_bytes')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Ausgewählte Quelldaten'))
        check.invoke();menu=field('Feishu-Original oder Webhook-Beleg',tk.OptionMenu)
        wizard.root.nametowidget(menu.cget('menu')).invoke(1);wizard.root.update()
        assert not wizard.root.getvar(check.cget('variable'))
        check.invoke();before=len(recovery_calls);button('Geprüfte Feishu-Quelldaten entfernen').invoke();settle();assert len(recovery_calls)==before
        cases.append('source_change_resets_confirmation_and_active_grant_cannot_be_purged_even_with_checkbox')
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk':True,'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'privileged_handoffs_and_account_responses_are_fixtures':True,'public_Feishu_activation_or_external_delivery':False},indent=2))
    finally:wizard.root.destroy()


if __name__=='__main__':main()
