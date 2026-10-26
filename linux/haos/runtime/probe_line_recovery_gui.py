#!/usr/bin/env python3
"""Actual trusted Tk recovery display backed by real private LINE SQLite metadata."""
import json
import platform
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup
    from haos.initial_setup_gui import Wizard
    from haos.gateway_raw import NativeInbox
    from haos.gateway_raw_recovery import unresolved
    from haos.redaction import Redactor
    cases=[]
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True
    initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    initial_setup.gateway_configuration=lambda:{'connectors':[],'bindings':[]}
    with tempfile.TemporaryDirectory(prefix='haos-line-owner-inspection-') as td:
        inbox=NativeInbox(Path(td)/'native.db',Redactor())
        inbox.db.execute('CREATE TABLE line_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
        for status in ['created','listening','disconnected','authentication-refused','identity-refused','rate-limited','transport-unavailable','revoked','closed']:
            inbox.db.execute('INSERT INTO line_profile_status VALUES(?,?,?,?,?,?)',(status,'line-main','private-scope-hash',status,123,time.time()+30 if status=='rate-limited' else 0))
        inbox.db.execute('CREATE TABLE line_delivery_intents(delivery_id TEXT,attempt INTEGER,fingerprint TEXT,state TEXT,receipt TEXT,updated_at REAL)')
        for identity,state,receipt in [('a','confirmed','line_push_'+'b'*64),('c','writing',''),('d','uncertain','')]:
            inbox.db.execute('INSERT INTO line_delivery_intents VALUES(?,?,?,?,?,?)',(identity*64,1,'private-fingerprint',state,receipt,123))
        def read(after=0):
            snapshot=NativeInbox(Path(td)/'native.db',Redactor())
            try:return unresolved(snapshot,after)
            finally:snapshot.close()
        initial_setup.gateway_ingress=read
        wizard=Wizard(tk)
        def widgets(parent):
            for child in parent.winfo_children():yield child;yield from widgets(child)
        try:
            wizard.show('gateways');wizard.root.update()
            menu=next(w for w in wizard.content.winfo_children() if isinstance(w,tk.OptionMenu))
            options=wizard.root.nametowidget(menu.cget('menu'))
            assert 'line' not in [options.entrycget(i,'label') for i in range(options.index('end')+1)]
            cases.append('prepared_line_stays_absent_from_public_setup_choices')
            button=next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen'))
            button.invoke()
            end=time.time()+5
            while wizard.running and time.time()<end:wizard.root.update();time.sleep(.01)
            wizard.root.update();assert not wizard.running
            labels=' '.join(str(w.cget('text')) for w in widgets(wizard.content) if isinstance(w,tk.Label))
            assert 'Lokaler LINE-Listener bereit; öffentliche HTTPS-Erreichbarkeit nicht bestätigt' in labels
            cases.append('actual_sqlite_profile_listening_does_not_claim_public_tls_or_external_webhook_readiness')
            assert 'LINE-Anmeldung abgelehnt' in labels and 'LINE-Bot-ID passt nicht zum Zugangstoken' in labels
            cases.append('actual_owner_sees_distinct_authentication_and_bot_identity_refusals')
            assert 'LINE begrenzt Anfragen; gespeicherte Wartefrist bleibt erhalten' in labels and 'nächste Anfrage:' in labels
            cases.append('actual_owner_sees_retained_throttle_deadline')
            assert 'LINE-Freigabe entzogen oder geändert' in labels and 'gespeicherte Eingänge bleiben erhalten' in labels
            cases.append('actual_owner_sees_revocation_and_data_preservation')
            assert 'Serverannahme-Beleg line_push_'+'b'*64 in labels and 'keine Empfangsbestätigung' in labels
            assert 'writing' in labels and 'uncertain' in labels
            assert 'private-scope-hash' not in labels and 'private-fingerprint' not in labels
            cases.append('actual_private_outgoing_states_and_server_acceptance_proof_never_claim_recipient_receipt_or_expose_private_internal_hashes')
            inbox.db.execute("UPDATE line_delivery_intents SET receipt='untrusted-receipt' WHERE state='confirmed'")
            try:unresolved(inbox)
            except ValueError:pass
            else:raise AssertionError('invalid retained LINE proof exposed to owner as confirmed')
            cases.append('actual_sqlite_invalid_retained_proof_is_refused_before_ui_rendering')
        finally:wizard.root.destroy();inbox.close()
    receipt={'passed':len(cases),'cases':cases,'actual_tk_and_private_sqlite_metadata':True,'python':platform.python_version(),
        'backend_handoff_fixture_only':True,'root_authority_checked_separately':True,
        'public_line_enabled':False,'external_or_installed_owner_acceptance':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
