#!/usr/bin/env python3
"""Real Tk owner controls; backend handoff only, no privileged or remote actions."""
import base64
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
    initial_setup.gateway_configuration=lambda:{'connectors':[],'bindings':[]}
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    calls=[];pairs=[]
    initial_setup.configure_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs))
    wizard=Wizard(tk);cases=[]
    def widgets(parent):
        for child in parent.winfo_children():
            yield child;yield from widgets(child)
    def field(prefix):
        for widget in widgets(wizard.content):
            if isinstance(widget,tk.Label) and widget.cget('text').startswith(prefix):
                children=widget.master.winfo_children();position=children.index(widget)
                return next(child for child in children[position+1:] if isinstance(child,tk.Entry))
        raise AssertionError('missing Matrix owner input '+prefix)
    def button(label):return next(widget for widget in widgets(wizard.content) if isinstance(widget,tk.Button) and widget.cget('text')==label)
    def fill(prefix,text):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,text);return entry
    def settle():
        deadline=time.monotonic()+5
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(0.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update()
        menu=next(widget for widget in wizard.content.winfo_children() if isinstance(widget,tk.OptionMenu))
        wizard.root.setvar(menu.cget('textvariable'),'matrix');wizard.root.update()
        assert field('Matrix HTTPS-Homeserver').winfo_ismapped()
        token=fill('Bot-Token','disposable-private-gui-token')
        recovery=fill('Vorhandener Recovery-Schlüssel','disposable-private-gui-recovery')
        assert token.cget('show') and recovery.cget('show')
        fill('Matrix HTTPS-Homeserver','https://matrix.example.org')
        fill('Matrix-Konto','@haos:example.org');fill('Bestehende Geräte-ID','HAOS')
        button('Gateway sicher anlegen').invoke();settle()
        assert len(calls)==1 and calls[0]==(('matrix-main','matrix','disposable-private-gui-token',''),
            {'homeserver':'https://matrix.example.org','user_id':'@haos:example.org','device_id':'HAOS','recovery_key':'disposable-private-gui-recovery'})
        assert token.get()=='' and recovery.get()==''
        cases.append('real_tk_complete_private_identity_handoff_and_secret_clearing')
        key=base64.b64encode(b'x'*32).decode().rstrip('=')
        fill('Absender-ID','@owner:example.org')
        queries=[]
        def query(connector,sender):
            queries.append((connector,sender))
            return {'devices':[{'device_id':'PHONE','ed25519':key,'curve25519':key}],
                'signature_checked':True,'owner_approval_required':True}
        initial_setup.matrix_gateway_devices=query
        button('Absendergeräte vom Homeserver laden').invoke();settle()
        assert queries==[('matrix-main','@owner:example.org')] and not pairs
        assert field('Matrix-Absendergerät').get()=='PHONE' and field('Öffentlicher Curve25519').get()==key
        cases.append('actual_device_discovery_control_hands_off_and_prefills_public_keys_without_granting')
        button('Absendergerät zur Freigabe vormerken').invoke()
        assert not pairs
        cases.append('local_device_draft_does_not_grant_backend_authority')
        for prefix,value in [('Absender-ID','@owner:example.org'),('Chat-ID','!room:example.org'),('Thread-ID','$root')]:fill(prefix,value)
        button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert len(pairs)==1 and pairs[0][0]==('my-device','matrix-main','@owner:example.org','!room:example.org','personal',('create','read'))
        assert pairs[0][1]=={'scope':'','thread':'$root','matrix_devices':[{'device_id':'PHONE','ed25519':key,'curve25519':key}],
            'allow_plaintext':False,'require_mention':True}
        cases.append('real_tk_exact_route_devices_rights_and_safe_defaults_reach_pair_backend')
        fill('Bot-Token','disposable-unsubmitted-token');fill('Vorhandener Recovery-Schlüssel','disposable-unsubmitted-recovery')
        wizard.root.setvar(menu.cget('textvariable'),'discord');wizard.root.update()
        assert token.get()=='' and recovery.get()=='' and not field('Matrix HTTPS-Homeserver').winfo_ismapped()
        wizard.root.setvar(menu.cget('textvariable'),'matrix');wizard.root.update()
        assert any(isinstance(widget,tk.Label) and widget.cget('text')=='Keine Absendergeräte vorgemerkt.' for widget in widgets(wizard.content))
        cases.append('platform_changes_clear_private_identity_and_unsubmitted_device_grants')
        initial_setup.gateway_ingress=lambda _after=0:{'ingress':[],'history':[],'transport':[{
            'connector':'matrix-main','platform':'matrix','status':'closed','last_error':'authentication-refused',
            'updated_at':time.time(),'next_sync':0,'pending_pages':1,'history_gaps':1,'history_error':'rate-limited'}],'next_cursor':0}
        button('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen').invoke();settle()
        labels=[widget.cget('text') for widget in widgets(wizard.content) if isinstance(widget,tk.Label)]
        assert any('letzter Fehler: Matrix-Anmeldung abgelehnt' in label and 'offene Verlaufslücken 1' in label for label in labels)
        assert not any('disposable-private-gui-token' in label or 'disposable-private-gui-recovery' in label for label in labels)
        cases.append('actual_owner_status_renders_safe_auth_and_history_errors_without_secrets')
        if wizard.compact:assert wizard.root.winfo_reqwidth()<=640
        assert wizard.viewport.bbox('all')[3]>wizard.viewport.winfo_height()
        cases.append('actual_scrollable_compact_or_normal_owner_layout')
    finally:wizard.root.destroy()
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'privileged_backend_accepted':False,'installed_setup_accepted':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    print(output,end='')


if __name__=='__main__':main()
