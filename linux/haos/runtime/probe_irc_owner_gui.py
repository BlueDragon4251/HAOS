#!/usr/bin/env python3
"""Actual Tk IRC setup/consent/backend handoffs without privileged actions."""
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
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'irc-main','platform':'irc'}],'bindings':[],
        'irc':{'irc-main':{'server':'irc.fixture.invalid','port':6697,'nickname':'haos-bot','channel':'#owner'}}}
    calls=[];pairs=[];retries=[];cases=[]
    initial_setup.configure_irc_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    initial_setup.retry_irc_gateway_auth=lambda connector:retries.append(connector) or {'network_requested':False}
    initial_setup.gateway_ingress=lambda after:{'ingress':[],'next_cursor':after,'transport':[
        {'platform':'irc','connector':'irc-main','status':'streaming','updated_at':123,'next_attempt':0,'gap_since':42}],
        'native_outgoing':[{'platform':'irc','delivery_id':'a'*64,'state':'confirmed','confirmed_chunks':2,
            'chunk_count':2,'server_echo_receipt':'irc_echo_'+'b'*64}]}
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
        wizard.root.setvar(menu.cget('textvariable'),'irc');wizard.root.update()
        assert field('Konnektor-ID').get()=='irc-main'
        assert field('IRC TLS-Server').get()=='irc.fixture.invalid' and field('IRC Kanal').get()=='#owner'
        assert field('Bereich').get()=='irc.fixture.invalid:6697' and field('Chat-ID').get()=='#owner'
        assert str(field('Bereich').cget('state'))==str(field('Thread-ID').cget('state'))=='disabled'
        assert not field('Bot-Token').master.winfo_manager()
        cases.append('actual_owner_dropdown_restores_saved_irc_endpoint_channel_and_bound_scope_without_unused_bot_token')
        labels=[w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label)]
        assert any('Spamfilter können Echos vortäuschen' in x and 'alle Kanalmitglieder' in x for x in labels)
        assert any('niemals nur ein Nickname' in x and 'stabile msgid' in x for x in labels)
        cases.append('actual_owner_help_explains_authenticated_accounts_shared_channel_server_requirements_and_echo_limits')
        anonymous=check('Verbindung ohne SASL-Konto')
        assert not wizard.root.getvar(anonymous.cget('variable'))
        fill('IRC SASL-Konto','bot-account');password=fill('IRC SASL-Passwort','private-gui-sasl-fixture')
        server_password=fill('IRC Server-Passwort','private-gui-server-fixture')
        assert password.cget('show') and server_password.cget('show')
        button('Gateway sicher anlegen').invoke();settle()
        assert calls==[(('irc-main',),{'server':'irc.fixture.invalid','port':6697,'nickname':'haos-bot','channel':'#owner',
            'server_password':'private-gui-server-fixture','sasl_username':'bot-account','sasl_password':'private-gui-sasl-fixture','anonymous':False})]
        assert password.get()==server_password.get()==''
        cases.append('masked_sasl_and_server_passwords_reach_real_backend_handoff_and_are_cleared_after_submit')
        anonymous.invoke();wizard.root.update()
        assert field('IRC SASL-Konto').get()==field('IRC SASL-Passwort').get()==''
        assert str(field('IRC SASL-Konto').cget('state'))=='disabled'
        button('Gateway sicher anlegen').invoke();settle()
        assert calls[-1][1]['anonymous'] is True and calls[-1][1]['sasl_username']==calls[-1][1]['sasl_password']==''
        assert not wizard.root.getvar(anonymous.cget('variable'))
        cases.append('anonymous_connection_requires_explicit_unchecked_choice_and_does_not_inherit_sasl_credentials')
        fill('Absender-ID','Owner-Account')
        button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1]==(('my-device','irc-main','Owner-Account','#owner','personal',('create','read')),
            {'scope':'irc.fixture.invalid:6697','thread':'','irc_server':'irc.fixture.invalid','irc_port':6697,'irc_channel':'#owner'})
        cases.append('actual_exact_account_channel_network_and_rights_reach_owner_pairing_backend')
        button('IRC-Konto nach Korrektur erneut prüfen').invoke();settle();assert retries==['irc-main']
        cases.append('actual_authentication_recheck_control_calls_offline_backend')
        fill('IRC SASL-Konto','other-account');fill('IRC SASL-Passwort','unsubmitted-private-fixture')
        fill('IRC Server-Passwort','unsubmitted-server-fixture');fill('IRC TLS-Server','other.fixture.invalid')
        assert password.get()==server_password.get()==''
        assert field('Bereich').get()=='other.fixture.invalid:6697'
        cases.append('endpoint_change_clears_both_private_credentials_and_updates_visible_exact_scope')
        anonymous.invoke();fill('Konnektor-ID','another-irc')
        assert not wizard.root.getvar(anonymous.cget('variable'))
        cases.append('connector_change_cannot_inherit_anonymous_connection_approval')
        fill('IRC SASL-Konto','bot-account');fill('IRC SASL-Passwort','unsubmitted-private-fixture')
        wizard.root.setvar(menu.cget('textvariable'),'telegram');wizard.root.update()
        assert password.get()==server_password.get()=='' and field('Bot-Token').master.winfo_manager()
        assert str(field('Bereich').cget('state'))==str(field('Thread-ID').cget('state'))=='normal'
        cases.append('platform_switch_clears_private_irc_material_and_restores_other_platform_controls')
        button('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen').invoke();settle()
        labels=' '.join(str(w.cget('text')) for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'IRC angemeldet' in labels and 'nicht verlässlich nachladbar' in labels
        assert 'Server-Echos 2/2' in labels and 'keine Empfangsbestätigung der Kanalmitglieder' in labels
        assert 'irc_echo_'+'b'*64 in labels
        cases.append('actual_owner_inspection_shows_irc_outage_gap_and_server_echo_without_recipient_delivery_claim')
    finally:wizard.root.destroy()
    receipt={'passed':len(cases),'cases':cases,'actual_tk_controls':True,'python':platform.python_version(),
        'backend_handoff_fixture_only':True,'root_authority_and_actual_sdk_acceptance_separate':True,
        'live_network_or_installed_owner_session':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
