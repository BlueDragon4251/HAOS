#!/usr/bin/env python3
"""Actual Tk ntfy controls and secure backend handoff, no privileged/network actions."""
import json
from pathlib import Path
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
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'ntfy-main','platform':'ntfy'}],'bindings':[{'id':'already-paired','connector':'ntfy-main','sender':'private-topic','chat':'private-topic',
        'scope':'','thread':'','identity':'topic-owner','capabilities':['create','read'],'trust_topic_publishers':True}],
        'ntfy':{'ntfy-main':{'server_url':'https://owner.invalid','topic':'private-topic'}}}
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    calls=[];pairs=[];retries=[]
    initial_setup.retry_ntfy_gateway_auth=lambda connector:retries.append(connector) or {"authentication_blocks_cleared":1,"network_requested":False}
    initial_setup.configure_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    wizard=Wizard(tk);cases=[]
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix):
        for widget in widgets(wizard.content):
            if isinstance(widget,tk.Label) and widget.cget('text').startswith(prefix):
                children=widget.master.winfo_children();position=children.index(widget)
                return next(child for child in children[position+1:] if isinstance(child,tk.Entry))
        raise AssertionError('missing ntfy owner field '+prefix)
    def button(label):return next(widget for widget in widgets(wizard.content) if isinstance(widget,tk.Button) and widget.cget('text')==label)
    def fill(prefix,value):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,value);wizard.root.update();return entry
    def settle():
        deadline=time.monotonic()+5
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update()
        menu=next(widget for widget in wizard.content.winfo_children() if isinstance(widget,tk.OptionMenu))
        wizard.root.setvar(menu.cget('textvariable'),'ntfy');wizard.root.update()
        assert field('ntfy HTTPS-Server').get()=='https://owner.invalid' and field('Exaktes privates ntfy-Topic').get()=='private-topic'
        assert field('Absender-ID').get()==field('Chat-ID').get()=='private-topic'
        assert str(field('Absender-ID').cget('state'))=='disabled' and str(field('Bereich').cget('state'))=='disabled'
        cases.append('real_tk_public_metadata_prefills_exact_topic_and_disables_invented_sender_scope_thread')
        labels=[widget.cget('text') for widget in widgets(wizard.content) if isinstance(widget,tk.Label)]
        assert any('ALLE Publisher' in text and 'geheimer Topic-Name allein schützt nicht' in text for text in labels)
        cases.append('real_owner_page_explains_topic_acl_and_absent_individual_sender_identity')
        assert any('Gilt für ALLE Publisher dieses Topics' in text and 'topic-owner' in text for text in labels)
        cases.append('existing_saved_binding_details_explicitly_show_shared_topic_publisher_authority')
        token=fill('Bot-Token','disposable-private-ntfy-gui-token')
        assert token.cget('show')
        button('Gateway sicher anlegen').invoke();settle()
        assert calls==[(('ntfy-main','ntfy','disposable-private-ntfy-gui-token'),{'server_url':'https://owner.invalid','topic':'private-topic'})]
        assert token.get()==''
        cases.append('actual_masked_token_server_and_topic_reach_backend_and_secret_entry_is_cleared')
        button('ntfy-Anmeldung erneut erlauben').invoke();settle()
        assert retries==['ntfy-main'] and not pairs
        cases.append('real_owner_auth_retry_control_calls_offline_backend_without_pairing_or_send')
        button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert not pairs
        cases.append('unchecked_all_publishers_trust_cannot_call_pairing_backend')
        trust=next(widget for widget in widgets(wizard.content) if isinstance(widget,tk.Checkbutton) and widget.cget('text').startswith('Ich vertraue ALLEN'))
        trust.invoke();button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs==[(('my-device','ntfy-main','private-topic','private-topic','personal',('create','read')),
                       {'scope':'','thread':'','trust_topic_publishers':True,'ntfy_server_url':'https://owner.invalid'})]
        cases.append('explicit_topic_publisher_trust_and_selected_rights_reach_exact_pairing_backend')
        fill('Exaktes privates ntfy-Topic','another-topic')
        assert not wizard.root.getvar(trust.cget('variable')) and field('Absender-ID').get()==field('Chat-ID').get()=='another-topic'
        count=len(pairs);button('Absender mit ausgewählten Rechten freigeben').invoke();settle();assert len(pairs)==count
        trust.invoke();fill('ntfy HTTPS-Server','https://another.invalid')
        assert not wizard.root.getvar(trust.cget('variable'))
        trust.invoke();fill('Konnektor-ID','another-connector')
        assert not wizard.root.getvar(trust.cget('variable'))
        cases.append('topic_server_or_connector_edit_requires_fresh_explicit_publisher_confirmation')
        fill('Bot-Token','disposable-unsubmitted-secret')
        wizard.root.setvar(menu.cget('textvariable'),'discord');wizard.root.update()
        assert token.get()=='' and str(field('Absender-ID').cget('state'))=='normal' and field('Absender-ID').get()==''
        assert not field('ntfy HTTPS-Server').winfo_ismapped()
        cases.append('platform_change_clears_secret_and_topic_authority_without_cross_platform_sender_reuse')
        initial_setup.gateway_ingress=lambda _after=0:{'ingress':[],'history':[],'transport':[{
            'connector':'ntfy-main','platform':'ntfy','status':'closed','last_error':'authentication-denied',
            'updated_at':time.time(),'next_attempt':time.time()+19}],'next_cursor':0}
        button('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen').invoke();settle()
        labels=[widget.cget('text') for widget in widgets(wizard.content) if isinstance(widget,tk.Label)]
        assert any('letzter Fehler: ntfy-Zugang abgelehnt' in text and 'nächste Anfrage:' in text for text in labels)
        assert not any('disposable-' in text for text in labels)
        cases.append('actual_owner_status_renders_redacted_ntfy_auth_error_and_persistent_retry_deadline')
        if wizard.compact:
            assert wizard.root.winfo_reqwidth()<=640
            assert trust.winfo_reqwidth()<=wizard.content.winfo_width()
        assert wizard.viewport.bbox('all')[3]>wizard.viewport.winfo_height()
        cases.append('real_scrollable_normal_or_compact_owner_layout')
    finally:wizard.root.destroy()
    receipt={'passed':len(cases),'cases':cases,'external_connections':False,'privileged_backend_accepted':False,'installed_setup_accepted':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
