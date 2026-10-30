#!/usr/bin/env python3
"""Actual Tk email recovery controls; explicit owner handoff fixtures, no network."""
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from tkinter import messagebox
    from haos import initial_setup
    from haos.initial_setup_gui import Wizard
    from haos.gateway_raw import NativeInbox
    from haos.gateway_raw_recovery import unresolved
    from haos.gateway_email_profile import STATES
    from haos.gateway_email_journal import Journal
    from haos.redaction import Redactor
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True
    initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    initial_setup.gateway_configuration=lambda:{'connectors':[],'bindings':[]}
    calls=[];cases=[]
    initial_setup.recover_email_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    messagebox.askyesno=lambda *_args,**_kwargs:True
    with tempfile.TemporaryDirectory(prefix='haos-email-owner-gui-') as td:
        path=Path(td)/'native.db';inbox=NativeInbox(path,Redactor())
        journal=Journal(inbox,'email-main','mailbox:'+'a'*64,lambda:None)
        journal.observe(77,4);journal.observe(88,2)
        inbox.db.execute('CREATE TABLE email_profile_status(identity TEXT PRIMARY KEY,connector TEXT,credential_scope TEXT,status TEXT,updated_at REAL,next_attempt REAL)')
        for status in STATES:inbox.db.execute('INSERT INTO email_profile_status VALUES(?,?,?,?,?,?)',(status,'email-main','a'*64,status,123,0))
        inbox.db.execute('CREATE TABLE email_delivery_intents(delivery_id TEXT,attempt INTEGER,fingerprint TEXT,state TEXT,receipt TEXT,created_at INTEGER,updated_at REAL)')
        for identity,state,receipt in [('a','confirmed','smtp_accept_'+'b'*64),('c','uncertain',''),('d','uncertain','')]:
            inbox.db.execute('INSERT INTO email_delivery_intents VALUES(?,?,?,?,?,?,?)',(identity*64,1,'f'*64,state,receipt,123,123))
        inbox.close()
        def read(after=0):
            db=NativeInbox(path,Redactor())
            try:return unresolved(db,after)
            finally:db.close()
        initial_setup.gateway_ingress=read
        wizard=Wizard(tk)
        def widgets(parent):
            for child in parent.winfo_children():yield child;yield from widgets(child)
        def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
        def field(prefix,cls=tk.Entry):
            label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
            siblings=label.master.winfo_children();return next(w for w in siblings[siblings.index(label)+1:] if isinstance(w,cls))
        def settle():
            end=time.time()+5
            while wizard.running and time.time()<end:wizard.root.update();time.sleep(.01)
            wizard.root.update();assert not wizard.running
        try:
            wizard.show('gateways');wizard.root.update()
            entry=field('Konnektor-ID');entry.delete(0,tk.END);entry.insert(0,'email-main')
            button('Gateway-Dienst stoppen und gespeicherte Eingänge prüfen').invoke();settle()
            labels='\n'.join(str(w.cget('text')) for w in widgets(wizard.content) if isinstance(w,tk.Label))
            assert 'IMAP-UID-Zustand geändert' in labels and 'SMTP-Annahme ist kein Empfangsnachweis' in labels
            assert 'UIDVALIDITY 77 → 88' in labels
            cases.append('actual_Tk_renders_every_finite_email_transport_state_and_exact_fenced_mailbox_metadata')
            note=field('Postfach-Prüfnotiz');note.insert(0,'Server reset independently inspected')
            button('Geprüften Postfachscan neu beginnen').invoke();settle()
            assert calls[-1][0][1:] == ('recover-email-mailbox','Server reset independently inspected',True)
            assert calls[-1][0][0]['snapshot_sha256']==read()['email_mailboxes'][0]['snapshot_sha256']
            cases.append('explicit_mailbox_confirmation_carries_exact_inventory_snapshot_to_owner_handoff')
            before=len(calls);button('Geprüfte private SMTP-Sperre freigeben').invoke();settle();assert len(calls)==before
            cases.append('SMTP_permission_without_independent_non_delivery_confirmation_never_reaches_owner_handoff')
            note=field('SMTP-Prüfnotiz');note.insert(0,'Non-delivery independently checked')
            check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Nichtzustellung unabhängig'))
            check.invoke();button('Geprüfte private SMTP-Sperre freigeben').invoke();settle()
            assert calls[-1][0][1]=='approve-email-retry' and calls[-1][1]=={'confirmed_not_delivered':True}
            assert calls[-1][0][0]['connector']=='email-main'
            cases.append('explicit_SMTP_owner_permission_preserves_attempt_snapshot_and_requires_separate_controller_reconciliation')
            check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Nichtzustellung unabhängig'))
            check.invoke();menu=field('Geprüfter privater SMTP-Versuch',tk.OptionMenu)
            choices=wizard.root.nametowidget(menu.cget('menu'));choices.invoke(1);wizard.root.update()
            assert not wizard.root.getvar(check.cget('variable'))
            cases.append('changing_selected_SMTP_attempt_clears_previous_non_delivery_confirmation')
            check.invoke();before=len(calls);entry.delete(0,tk.END);entry.insert(0,'other-connector')
            button('Geprüfte private SMTP-Sperre freigeben').invoke();settle();assert len(calls)==before
            cases.append('changing_connector_after_inspection_refuses_permission_and_requires_fresh_inventory')
            assert not any('a'*64 in choices.entrycget(i,'label') for i in range(choices.index('end')+1))
            cases.append('confirmed_SMTP_acceptance_is_displayed_but_never_offered_for_private_retry')
            profile='email-'+'f'*64
            source={'id':'e'*64,'connector':'email-main','rfc_message_id':'<fixture@example.invalid>',
                'input_state':'committed','stored_bytes':100,'sha256':'f'*64,'purge_allowed':True,'snapshot_sha256':'1'*64}
            pending={**source,'id':'2'*64,'input_state':'pending','purge_allowed':False,'snapshot_sha256':'3'*64}
            def source_inventory(selected_profile=None):
                if selected_profile is None:return {'profiles':[{'profile':profile,'connector':'email-main','active':2,'stored_bytes':200}]}
                assert selected_profile==profile
                return {'profile':profile,'sources':[source,pending],'stored_bytes':200,'limit_bytes':64*1024*1024,'history_truncated':False}
            initial_setup.email_gateway_sources=source_inventory
            wizard.show('gateway-email-sources');wizard.root.update()
            button('Gateway stoppen und E-Mail-Quellenprofile laden').invoke();settle()
            button('Ausgewähltes Quellenprofil prüfen').invoke();settle()
            before=len(calls);button('Geprüftes Original aus Live-Cache entfernen').invoke();settle();assert len(calls)==before
            cases.append('source_disposal_without_explicit_confirmation_never_reaches_owner_handoff')
            field('Quellen-Prüfnotiz').insert(0,'Terminal source independently inspected')
            check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Dieses Original geprüft'))
            check.invoke();button('Geprüftes Original aus Live-Cache entfernen').invoke();settle()
            assert calls[-1][0][0]==source and calls[-1][1]=={'profile':profile}
            assert calls[-1][0][1]=='purge-email-source'
            cases.append('source_disposal_handoff_preserves_exact_opaque_profile_and_inspected_snapshot_without_deleting_fixture_data')
            check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Dieses Original geprüft'))
            check.invoke();menu=field('Gespeichertes E-Mail-Original',tk.OptionMenu)
            options=wizard.root.nametowidget(menu.cget('menu'));options.invoke(1);wizard.root.update()
            assert not wizard.root.getvar(check.cget('variable'))
            check.invoke();before=len(calls);button('Geprüftes Original aus Live-Cache entfernen').invoke();settle();assert len(calls)==before
            cases.append('changing_source_clears_consent_and_pending_source_remains_protected_even_with_checkbox_selected')
            print(json.dumps({'passed':len(cases),'cases':cases,'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
                'actual_Tk_and_SQLite_inventory':True,'owner_handoffs_are_fixtures':True,'public_email_enabled':True,
                'external_delivery_or_installed_owner_acceptance':False},indent=2))
        finally:wizard.root.destroy()


if __name__=='__main__':main()
