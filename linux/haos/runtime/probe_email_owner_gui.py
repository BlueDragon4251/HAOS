#!/usr/bin/env python3
"""Actual prepared email account Tk form; explicit nonprivileged owner fixtures."""
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
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    initial_setup.gateway_configuration=lambda:{'connectors':[],'bindings':[]}
    calls=[];checks=[];retries=[];cases=[]
    initial_setup.configure_email_gateway=lambda *args,**kwargs:calls.append((args,kwargs))
    initial_setup.inspect_email_gateway_account=lambda connector:checks.append(connector) or {'authenticated':False,'error':'tls-refused','smtp_message_sent':False}
    initial_setup.retry_email_gateway_auth=lambda connector:retries.append(connector)
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix,cls=tk.Entry):
        label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
        siblings=label.master.winfo_children();return next(w for w in siblings[siblings.index(label)+1:] if isinstance(w,cls))
    def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
    def fill(prefix,value):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,value);wizard.root.update();return entry
    def settle():
        end=time.time()+5
        while wizard.running and time.time()<end:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update()
        menu=field('Plattform',tk.OptionMenu)
        # Prepared page is tested directly; public registry activation is separate.
        wizard.root.setvar(menu.cget('textvariable'),'email');wizard.root.update()
        fill('Konnektor-ID','email-main')
        fill('E-Mail-Dienstkonto','haos@example.invalid');fill('IMAP-Hostname','imap.example.invalid')
        fill('SMTP-Hostname','smtp.example.invalid');fill('Empfangsserver Authentication','mail.example.invalid')
        password=fill('E-Mail-App-Passwort','private-form-fixture')
        assert password.cget('show') and not field('Bot-Token').winfo_viewable()
        cases.append('actual_prepared_email_form_masks_password_and_hides_generic_bot_token')
        check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith('Empfangsserver entfernt'))
        check.invoke();fill('IMAP-Hostname','imap2.example.invalid')
        assert password.get()=='' and not wizard.root.getvar(check.cget('variable'))
        cases.append('endpoint_change_clears_password_and_receiving_server_trust_consent')
        fill('IMAP-Port','not-a-port');fill('E-Mail-App-Passwort','private-form-fixture');check.invoke()
        button('Gateway sicher anlegen').invoke();settle();assert not calls and password.get()==''
        cases.append('invalid_port_is_rejected_before_owner_handoff_and_password_field_is_cleared')
        fill('IMAP-Port','993');fill('E-Mail-App-Passwort','private-form-fixture');check.invoke()
        button('Gateway sicher anlegen').invoke();settle()
        assert len(calls)==1
        account=calls[0][0][1]
        assert calls[0][0][0]=='email-main' and account['imap_port']==993 and account['smtp_port']==465
        assert account['imap_security']==account['smtp_security']=='tls'
        assert account['password']=='private-form-fixture' and calls[0][1]=={'trust_authentication_results':True}
        assert password.get()=='' and not wizard.root.getvar(check.cget('variable'))
        labels='\n'.join(str(w.cget('text')) for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'private-form-fixture' not in labels+str(wizard.status.cget('text'))
        cases.append('explicit_account_snapshot_and_receiving_server_consent_reach_owner_handoff_without_password_in_labels_or_status')
        button('Gespeichertes E-Mail-Konto ohne Versand prüfen').invoke();settle()
        assert checks==['email-main'] and 'tls-refused' in wizard.status.cget('text')
        assert 'authentifiziert' not in wizard.status.cget('text')
        cases.append('finite_account_failure_is_displayed_without_claiming_authentication_or_delivery')
        button('E-Mail-Anmeldung erneut erlauben').invoke();settle();assert retries==['email-main']
        cases.append('authentication_recheck_has_a_real_owner_handoff_and_does_not_send')
        fill('E-Mail-App-Passwort','private-form-fixture');check.invoke()
        wizard.root.setvar(menu.cget('textvariable'),'telegram');wizard.root.update()
        assert password.get()=='' and not wizard.root.getvar(check.cget('variable')) and not password.winfo_viewable()
        cases.append('platform_switch_clears_mail_password_and_consent')
        print(json.dumps({'passed':len(cases),'cases':cases,'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'actual_Tk':True,'owner_handoffs_are_fixtures':True,'prepared_page_not_publicly_enabled':True,
            'external_accounts_or_delivery_or_installed_owner_acceptance':False},indent=2))
    finally:wizard.root.destroy()


if __name__=='__main__':main()
