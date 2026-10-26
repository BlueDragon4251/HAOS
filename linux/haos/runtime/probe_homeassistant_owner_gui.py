#!/usr/bin/env python3
"""Actual Tk Home Assistant owner controls; no privileged action or network IO."""
import json
from pathlib import Path
import platform
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True
    initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'homeassistant-main','platform':'homeassistant'}],
        'bindings':[{'id':'saved','connector':'homeassistant-main','sender':'system','chat':'sensor.room',
            'scope':'','thread':'','identity':'ha-system','capabilities':['create','read'],
            'homeassistant_shared_notifications':True,'homeassistant_trust_system':True}],
        'homeassistant':{'homeassistant-main':{'server_url':'https://owner.invalid'}}}
    calls=[];pairs=[];retries=[];cases=[]
    initial_setup.configure_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    initial_setup.retry_homeassistant_gateway_auth=lambda connector:retries.append(connector) or {
        'authentication_blocks_cleared':1,'network_requested':False}
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix):
        for widget in widgets(wizard.content):
            if isinstance(widget,tk.Label) and widget.cget('text').startswith(prefix):
                children=widget.master.winfo_children();index=children.index(widget)
                return next(child for child in children[index+1:] if isinstance(child,tk.Entry))
        raise AssertionError('missing actual owner field '+prefix)
    def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
    def check(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith(prefix))
    def fill(prefix,value):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,value);wizard.root.update();return entry
    def settle():
        end=time.time()+4
        while wizard.running and time.time()<end:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update()
        menu=next(w for w in wizard.content.winfo_children() if isinstance(w,tk.OptionMenu))
        wizard.root.setvar(menu.cget('textvariable'),'homeassistant');wizard.root.update()
        assert field('Konnektor-ID').get()=='homeassistant-main'
        assert field('Home Assistant HTTPS-Server').get()=='https://owner.invalid'
        assert str(field('Bereich').cget('state'))==str(field('Thread-ID').cget('state'))=='disabled'
        cases.append('real_tk_selects_homeassistant_restores_public_server_and_disables_invented_scope_thread')
        labels=[w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label)]
        assert any('unbeobachtete Ereignisse' in text and 'nicht mit sicherer Absenderzuordnung' in text for text in labels)
        assert any('Antworten für ALLE Instanzbenutzer' in text and 'System-/Automationsquellen' in text for text in labels)
        cases.append('real_owner_page_and_saved_binding_details_explain_shared_audience_and_unrecoverable_remote_gap')
        for prefix in ['Eigene Missionen abbrechen','Rückfragen und Freigaben beantworten','Wartende Missionen pausieren','Pausierte Missionen fortsetzen']:
            assert str(check(prefix).cget('state'))=='disabled'
        cases.append('native_event_gateway_does_not_offer_nonfunctional_chat_command_rights')
        secret=fill('Bot-Token','disposable-private-homeassistant-gui-token');assert secret.cget('show')
        button('Gateway sicher anlegen').invoke();settle()
        assert calls==[(('homeassistant-main','homeassistant','disposable-private-homeassistant-gui-token'),{'server_url':'https://owner.invalid'})]
        assert secret.get()==''
        cases.append('masked_token_and_https_server_reach_actual_configuration_handoff_then_secret_entry_is_cleared')
        button('Home-Assistant-Anmeldung erneut erlauben').invoke();settle()
        assert retries==['homeassistant-main'] and not pairs
        cases.append('owner_auth_recheck_control_calls_offline_backend_without_pairing_or_send')
        fill('Absender-ID','a'*32);fill('Chat-ID','input_text.owner')
        button('Absender mit ausgewählten Rechten freigeben').invoke();settle();assert not pairs
        cases.append('read_permission_cannot_pair_without_explicit_all_instance_users_notification_consent')
        shared=check('Ich erlaube Missionantworten');system=check('Ich vertraue allen System-')
        shared.invoke();button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1]==(('my-device','homeassistant-main','a'*32,'input_text.owner','personal',('create','read')),
            {'scope':'','thread':'','homeassistant_shared_notifications':True,'homeassistant_trust_system':False,
                'homeassistant_server_url':'https://owner.invalid'})
        cases.append('explicit_human_actor_entity_and_shared_notification_consent_reach_pairing_backend')
        system.invoke();fill('Chat-ID','sensor.kitchen')
        assert field('Absender-ID').get()=='system' and str(field('Absender-ID').cget('state'))=='disabled'
        button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1]==(('my-device','homeassistant-main','system','sensor.kitchen','personal',('create','read')),
            {'scope':'','thread':'','homeassistant_shared_notifications':True,'homeassistant_trust_system':True,
                'homeassistant_server_url':'https://owner.invalid'})
        cases.append('explicit_system_entity_trust_has_distinct_sender_and_no_claim_of_authenticated_human_identity')
        fill('Home Assistant HTTPS-Server','https://other.invalid')
        assert not wizard.root.getvar(shared.cget('variable')) and not wizard.root.getvar(system.cget('variable'))
        assert str(field('Absender-ID').cget('state'))=='normal' and field('Absender-ID').get()==''
        cases.append('server_edit_requires_fresh_system_and_shared_audience_consent_and_clears_system_sender')
        shared.invoke();system.invoke();fill('Konnektor-ID','another-ha')
        assert not wizard.root.getvar(shared.cget('variable')) and not wizard.root.getvar(system.cget('variable'))
        cases.append('connector_edit_cannot_inherit_previous_instance_or_system_authority')
        shared.invoke();system.invoke();fill('Bot-Token','unsubmitted-disposable-secret')
        wizard.root.setvar(menu.cget('textvariable'),'discord');wizard.root.update()
        assert field('Bot-Token').get()=='' and str(field('Absender-ID').cget('state'))=='normal'
        assert str(check('Eigene Missionen abbrechen').cget('state'))=='normal'
        cases.append('platform_switch_clears_private_token_and_restores_other_platform_permissions')
    finally:wizard.root.destroy()
    receipt={'passed':len(cases),'cases':cases,'actual_tk_controls':True,'python':platform.python_version(),
        'backend_handoff_fixture_only':True,'root_authority_and_actual_sdk_acceptance_separate':True,
        'live_network_or_installed_owner_session':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
