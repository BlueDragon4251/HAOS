#!/usr/bin/env python3
"""Actual Tk owner form; privileged handoffs and account responses are fixtures."""
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,dingtalk_owner_setup as owner
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
        wizard.show('gateways');wizard.root.update();choice('Plattform','dingtalk');fill('Konnektor-ID','dingtalk-main')
        for label,value in [('DingTalk Client ID','ding_fixture_app'),('DingTalk Corporation ID','ding_fixture_corp'),('DingTalk Robot Code','ding_fixture_robot')]:fill(label,value)
        secret=fill('DingTalk Client Secret','private-dingtalk-form-fixture')
        assert secret.cget('show') and secret.winfo_viewable() and not field('Bot-Token').winfo_viewable()
        cases.append('actual_Tk_masks_private_app_secret_and_hides_unrelated_token')
        fill('DingTalk Client ID','ding_fixture_other_app');assert not secret.get()
        cases.append('app_identity_change_clears_private_secret')
        fill('DingTalk Client Secret','private-dingtalk-form-fixture');choice('DingTalk-Antwortweg','robot');assert not secret.get()
        fill('DingTalk Client Secret','private-dingtalk-form-fixture');button('Gateway sicher anlegen').invoke();settle()
        assert calls==[('dingtalk-main',{'client_id':'ding_fixture_other_app','client_secret':'private-dingtalk-form-fixture',
            'corp_id':'ding_fixture_corp','robot_code':'ding_fixture_robot','reply_mode':'robot'})] and not secret.get()
        cases.append('exact_app_corporation_robot_and_explicit_reply_mode_reach_owner_handoff_then_secret_clears')
        button('DingTalk-Konto ohne Nachricht prüfen').invoke();settle();assert checks==['dingtalk-main'] and 'identity-refused' in wizard.status.cget('text')
        button('DingTalk-Anmeldung erneut erlauben').invoke();settle();assert retries==['dingtalk-main']
        cases.append('account_inspection_and_auth_recheck_buttons_have_distinct_no_send_handoffs')
        from haos.gateway_dingtalk import scope
        expected=scope(calls[0][1]);assert field('Bereich').get()==expected and str(field('Bereich').cget('state'))=='disabled'
        assert field('Thread-ID').get()=='' and str(field('Thread-ID').cget('state'))=='disabled'
        observations=[]
        def observed(connector,request):
            observations.append((connector,request))
            return {'observed':True,'candidate':{'sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=','scope':expected,'authorized':False}}
        owner.observe=observed
        before=len(pairs);button('DingTalk-IDs ohne Freigabe erfassen').invoke();settle()
        assert observations[-1][0]=='dingtalk-main' and len(observations[-1][1]['nonce'])==32
        assert observations[-1][1]['until']-observations[-1][1]['since']==60000
        assert field('Einmaliger Erfassungscode').get()=='HAOS koppeln '+observations[-1][1]['nonce']
        button('Erfassungscode kopieren').invoke();assert wizard.root.clipboard_get()==field('Einmaliger Erfassungscode').get()
        assert len(pairs)==before and field('Absender-ID').get()=='$:LWCP_v1:$opaque-owner' and field('Chat-ID').get()=='cidExactConversation/+='
        cases.append('actual_Tk_challenge_copy_and_observation_handoff_fill_untrusted_opaque_IDs_without_pairing')
        media=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('DingTalk-Bilder'))
        outbound=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Markierte Ergebnisdateien an diesen DingTalk'))
        assert not wizard.root.getvar(media.cget('variable')) and not wizard.root.getvar(outbound.cget('variable'))
        media.invoke();outbound.invoke();fill('Absender-ID','another-opaque-owner')
        assert not wizard.root.getvar(media.cget('variable')) and not wizard.root.getvar(outbound.cget('variable'))
        media.invoke();outbound.invoke();button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1][0][2:4]==('another-opaque-owner','cidExactConversation/+=')
        assert pairs[-1][1]['scope']==expected and pairs[-1][1]['thread']=='' and pairs[-1][1]['allow_media'] is True
        assert pairs[-1][1]['allow_outbound_media'] is True and pairs[-1][1]['allow_voice'] is False and pairs[-1][1]['require_mention'] is True
        cases.append('explicit_separate_owner_pairing_carries_exact_IDs_scope_and_default_denied_media_flags')
        choice('DingTalk-Antwortweg','session');assert str(outbound.cget('state'))=='disabled' and not wizard.root.getvar(outbound.cget('variable'))
        cases.append('session_reply_mode_cannot_enable_outbound_artifact_consent')
        owner.observe=lambda *_:{'observed':False,'error':'observation-timeout'}
        before=len(pairs);button('DingTalk-IDs ohne Freigabe erfassen').invoke();settle()
        assert len(pairs)==before and 'abgelaufen' in wizard.status.cget('text')
        cases.append('observation_timeout_is_honest_and_never_creates_a_grant')
        fill('DingTalk Client Secret','private-dingtalk-form-fixture');choice('Plattform','telegram')
        assert not secret.get() and not secret.winfo_viewable() and str(field('Thread-ID').cget('state'))=='normal'
        cases.append('platform_switch_clears_private_secret_and_restores_other_platform_thread_field')
        from tkinter import messagebox
        messagebox.askyesno=lambda *_args,**_kwargs:True
        recovery_calls=[]
        owner.recovery=lambda *args,**kwargs:recovery_calls.append((args,kwargs))
        from haos.dingtalk_owner_gui import LABELS
        uncertain={'platform':'dingtalk','connector':'dingtalk-main','delivery_id':'a'*64,'part':1,'operation':'reply',
            'attempt':1,'state':'uncertain','snapshot_sha256':'b'*64}
        known={**uncertain,'part':0,'state':'confirmed'}
        other={**uncertain,'part':2,'snapshot_sha256':'c'*64}
        initial_setup.gateway_ingress=lambda after=0:{'ingress':[],'history':[],'native_outgoing':[known,uncertain,other],
            'native_batches':[{'delivery_id':'9'*64,'parts':2,'confirmed_parts':2,'state':'confirmed','native_acceptance_receipt':'haos-dingtalk-'+'8'*64}],
            'transport':[{'platform':'dingtalk','connector':'dingtalk-main','status':state,'updated_at':123,'next_attempt':0} for state in LABELS]}
        wizard.show('gateways');wizard.root.update()
        button('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen').invoke();settle()
        labels='\n'.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert all(label in labels for label in LABELS.values()) and 'API-Annahme ist kein Lesebeleg' in labels
        assert 'DingTalk-Ergebnisgruppe' in labels and 'haos-dingtalk-'+'8'*64 in labels
        cases.append('every_finite_DingTalk_transport_state_part_and_complete_batch_proof_is_displayed_without_upload_key_or_recipient_read_claim')
        button('Geprüfte DingTalk-Teilsperre freigeben').invoke();settle();assert not recovery_calls
        cases.append('no_independent_non_acceptance_checkbox_means_no_owner_retry_handoff')
        fill('DingTalk-Prüfnotiz','Exact reply non-acceptance independently inspected')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Nichtannahme dieses'))
        check.invoke();button('Geprüfte DingTalk-Teilsperre freigeben').invoke();settle()
        assert recovery_calls[-1][0][0]==uncertain and recovery_calls[-1][0][1]=='approve-dingtalk-part-retry'
        assert recovery_calls[-1][1]=={'confirmed_not_accepted':True}
        cases.append('selected_part_operation_snapshot_and_non_acceptance_confirmation_reach_separate_owner_handoff')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Nichtannahme dieses'))
        check.invoke();menu=field('Geprüfter DingTalk-Schreibversuch',tk.OptionMenu)
        options=wizard.root.nametowidget(menu.cget('menu'));assert options.index('end')==1
        options.invoke(1);wizard.root.update();assert not wizard.root.getvar(check.cget('variable'))
        cases.append('changing_selected_part_clears_confirmation_and_confirmed_parts_are_not_retry_choices')
        profile='dingtalk-'+'d'*64
        retained={'id':'e'*64,'purge_allowed':True,'purged':False,'stored_bytes':100,'snapshot_sha256':'f'*64}
        active={**retained,'id':'1'*64,'purge_allowed':False,'snapshot_sha256':'2'*64}
        def source_inventory(selected_profile=None,kind=None):
            if selected_profile is None:return {'profiles':[{'profile':profile,'kinds':{'original':{}}}]}
            assert selected_profile==profile and kind=='original'
            return {'profile':profile,'kind':kind,'sources':[retained,active]}
        owner.sources=source_inventory
        wizard.show('gateway-dingtalk-sources');wizard.root.update();button('DingTalk-Profile prüfen').invoke();settle()
        button('DingTalk-Quellmetadaten laden').invoke();settle()
        before=len(recovery_calls);button('Geprüfte DingTalk-Quelldaten entfernen').invoke();settle();assert len(recovery_calls)==before
        fill('DingTalk-Löschprüfnotiz','Withdrawn source independently inspected')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Ausgewählte Quelldaten'))
        check.invoke();button('Geprüfte DingTalk-Quelldaten entfernen').invoke();settle()
        assert recovery_calls[-1][0][0]=={**retained,'profile':profile,'kind':'original'} and recovery_calls[-1][0][1]=='purge-dingtalk-source'
        cases.append('explicit_source_disposal_carries_exact_profile_kind_and_snapshot_without_returning_raw_bytes')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Ausgewählte Quelldaten'))
        check.invoke();menu=field('DingTalk-Original',tk.OptionMenu)
        wizard.root.nametowidget(menu.cget('menu')).invoke(1);wizard.root.update()
        assert not wizard.root.getvar(check.cget('variable'))
        check.invoke();before=len(recovery_calls);button('Geprüfte DingTalk-Quelldaten entfernen').invoke();settle();assert len(recovery_calls)==before
        cases.append('source_change_resets_confirmation_and_active_grant_cannot_be_purged_even_with_checkbox')
        output={**retained,'name':'result-0.zip','kind':'file'}
        owner.outputs=lambda:{'outputs':[output],'stored_bytes':100,'history_truncated':False}
        wizard.show('gateway-dingtalk-outputs');wizard.root.update();button('DingTalk-Konvertierungsmetadaten laden').invoke();settle()
        before=len(recovery_calls);button('Geprüfte Konvertierung entfernen').invoke();settle();assert len(recovery_calls)==before
        fill('Prüfnotiz ohne Geheimnisse','Withdrawn conversion independently inspected')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Genau diese Konvertierung'))
        check.invoke();button('Geprüfte Konvertierung entfernen').invoke();settle()
        assert recovery_calls[-1][0][0]==output and recovery_calls[-1][0][1]=='purge-dingtalk-output-cache'
        cases.append('conversion_disposal_requires_explicit_inspection_and_passes_exact_metadata_snapshot')
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk':True,'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'privileged_handoffs_and_account_responses_are_fixtures':True,'public_DingTalk_activation_or_external_delivery':False},indent=2))
    finally:wizard.root.destroy()


if __name__=='__main__':main()
