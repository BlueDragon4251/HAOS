"""Inspected email recovery controls; all authority stays in root owner helpers."""
from . import initial_setup

LABELS={'created':'E-Mail-Profil vorbereitet','connecting':'IMAP/SMTP-Anmeldung wird geprüft',
    'receiving':'E-Mail-Empfang aktiv; keine externe Zustellung bestätigt',
    'source-unavailable':'E-Mail-Quelle nicht verfügbar; Eingang und Freigaben prüfen',
    'storage-unavailable':'Privater E-Mail-Speicher voll oder nicht verfügbar; erhaltene Quellen prüfen',
    'tls-refused':'E-Mail-TLS abgelehnt; Hostname, Zertifikat und TLS-Modus prüfen',
    'smtp-authentication-refused':'E-Mail-Anmeldung abgelehnt; Konto/App-Passwort und Serverrechte prüfen',
    'rate-limited':'E-Mail-Server begrenzt Anfragen; gespeicherte Wartefrist gilt',
    'imap-unavailable':'IMAP nicht verfügbar; Server, Netzwerk und Konto prüfen',
    'uid-state-changed':'IMAP-UID-Zustand geändert; Postfach unten ausdrücklich prüfen',
    'revoked':'E-Mail-Freigabe entzogen oder geändert','disconnected':'E-Mail getrennt; Daten erhalten',
    'closed':'E-Mail-Profil geschlossen; Daten erhalten'}


def recovery(wizard,parent,value,reload,connector):
    tk=wizard.tk
    for row in value.get('email_mailboxes',[]):
        wizard._label(parent,'E-Mail-Postfach · '+row['connector']+' · '+row['status']
            +(' · aktiver Scan' if row['active'] else ' · erhaltener früherer Scan')
            +' · UIDVALIDITY '+str(row['uid_validity'])+' → '+str(row['observed_validity'])
            +' · Cursor '+str(row['cursor']),size=10,color=wizard.MUTED).pack(anchor='w',pady=3)
    fenced=[row for row in value.get('email_mailboxes',[]) if row['active'] and row['status']!='ready']
    if fenced:
        choices={row['connector']+' · '+row['identity']:row for row in fenced}
        selected=wizard._choice(parent,'Geprüfter E-Mail-Postfachscan',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        note=wizard._field(parent,'Postfach-Prüfnotiz ohne Geheimnisse')
        def reset(choices=choices,selected=selected,note=note):
            from tkinter import messagebox
            row,evidence=choices[selected.get()],note.get()
            if messagebox.askyesno('Geändertes E-Mail-Postfach','Serveränderung unabhängig geprüft? Neuen lokalen Scan beginnen und alte Cursor/Belege erhalten? Es werden keine Rechte erweitert.'):
                wizard._run_async(lambda:initial_setup.recover_email_gateway(row,'recover-email-mailbox',evidence,True),
                    success='Neuer Scan gespeichert; alter Verlauf erhalten. Gateway bleibt gestoppt.',result_handler=lambda _:reload())
        wizard._button(parent,'Geprüften Postfachscan neu beginnen',reset).pack(anchor='w',pady=4)
    rows=[row for row in value.get('native_outgoing',[]) if row.get('platform')=='email']
    for row in rows:
        wizard._label(parent,'E-Mail-Ausgang · '+row['delivery_id']+' · '+row['state']+' · Versuch '+str(row['attempt'])
            +' · SMTP-Annahme ist kein Empfangsnachweis'
            +(' · '+row['server_acceptance_receipt'] if row.get('server_acceptance_receipt') else ''),
            size=10,color=wizard.MUTED).pack(anchor='w',pady=3)
    uncertain=[row for row in rows if row['state'] in {'writing','uncertain','rejected'} and row['attempt']<5]
    if uncertain:
        choices={row['delivery_id']+' · Versuch '+str(row['attempt']):row for row in uncertain}
        selected=wizard._choice(parent,'Geprüfter privater SMTP-Versuch',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        note=wizard._field(parent,'SMTP-Prüfnotiz ohne Geheimnisse')
        confirmed=tk.BooleanVar(value=False)
        inspected_connector=connector()
        selected.trace_add('write',lambda *_:confirmed.set(False))
        tk.Checkbutton(parent,text='Nichtzustellung unabhängig geprüft; oben ist der zugehörige E-Mail-Konnektor gewählt',
            variable=confirmed,bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,
            wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
        def approve():
            from tkinter import messagebox
            if connector()!=inspected_connector:
                confirmed.set(False);wizard.status.configure(text='Konnektor geändert; Eingangsmetadaten erneut laden und prüfen.');return
            row={**choices[selected.get()],'connector':inspected_connector};evidence=note.get();checked=confirmed.get()
            if not checked:
                wizard.status.configure(text='Nichtzustellung zuerst unabhängig prüfen und ausdrücklich bestätigen.');return
            if messagebox.askyesno('Unklarer E-Mail-Versand','Private Sperre für einen späteren Versuch freigeben? Anschließend muss die Controller-Zustellung separat geprüft werden. Jetzt wird keine Mail gesendet.'):
                wizard._run_async(lambda:initial_setup.recover_email_gateway(row,'approve-email-retry',evidence,True,confirmed_not_delivered=checked),
                    success='Private Entscheidung gespeichert. Controller-Zustellung separat prüfen; Dienste bleiben gestoppt.',result_handler=lambda _:reload())
        wizard._button(parent,'Geprüfte private SMTP-Sperre freigeben',approve).pack(anchor='w',pady=4)


def sources(wizard):
    tk=wizard.tk
    wizard._head('E-Mail-Quellen verwalten','Private Originale · ausdrückliche geprüfte Entscheidungen')
    wizard._label(wizard.content,'Die Prüfung stoppt den Gateway-Dienst. Offene Eingänge bleiben geschützt. '
        'Nur nach einer endgültigen Eingangsentscheidung darf das ausgewählte Original logisch aus dem Live-Cache entfernt werden. '
        'Metadaten, Prüfbelege und Controller-Verlauf bleiben erhalten; dies löscht keine Backups und garantiert keine sichere Datenträgerlöschung.',
        size=10,color=wizard.MUTED).pack(anchor='w',pady=8)
    area=tk.Frame(wizard.content,bg=wizard.PANEL);area.pack(fill='x')
    def show_sources(value):
        for child in area.winfo_children():child.destroy()
        wizard._label(area,'Gespeicherte Originale: '+str(value['stored_bytes'])+' / '+str(value['limit_bytes'])+' Bytes',size=10).pack(anchor='w',pady=4)
        if value.get('history_truncated'):
            wizard._label(area,'Begrenzte Ansicht; alle aktiven Originale und die jüngsten Prüfbelege werden angezeigt.',size=10,color=wizard.MUTED).pack(anchor='w')
        rows=value['sources']
        if not rows:
            wizard._label(area,'Keine Originale in diesem Profil.',size=10).pack(anchor='w');return
        choices={row['id']+' · '+row['input_state']+' · '+str(row['stored_bytes'])+' Bytes':row for row in rows}
        selected=wizard._choice(area,'Gespeichertes E-Mail-Original',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        details=wizard._label(area,'',size=10,color=wizard.MUTED);details.pack(anchor='w',pady=4)
        note=wizard._field(area,'Quellen-Prüfnotiz ohne Geheimnisse')
        confirmed=tk.BooleanVar(value=False)
        tk.Checkbutton(area,text='Dieses Original geprüft; logische Entfernung aus dem Live-Cache ausdrücklich freigeben',
            variable=confirmed,bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,
            wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
        def changed(*_args):
            confirmed.set(False);row=choices[selected.get()]
            details.configure(text='Konnektor: '+row['connector']+' · Nachricht: '+row['rfc_message_id']
                +' · SHA-256: '+row['sha256']+' · '+('Entfernung nach endgültiger Eingangsentscheidung möglich' if row['purge_allowed'] else 'Original bleibt geschützt oder wurde bereits entfernt'))
        selected.trace_add('write',changed);changed()
        def purge():
            from tkinter import messagebox
            row,evidence,consent=choices[selected.get()],note.get(),confirmed.get()
            if not consent or not row['purge_allowed']:
                wizard.status.configure(text='Nur ein geprüftes, endgültig bearbeitetes Original mit ausdrücklicher Bestätigung darf entfernt werden.');return
            profile=value['profile']
            if messagebox.askyesno('Geprüftes E-Mail-Original','Nur dieses Original logisch aus dem Live-Cache entfernen? Prüfbelege bleiben erhalten. Backups und SQLite-Freiseiten werden nicht gelöscht.'):
                wizard._run_async(lambda:initial_setup.recover_email_gateway(row,'purge-email-source',evidence,True,profile=profile),
                    success='Ausgewähltes Original logisch entfernt; Prüfbeleg erhalten. Gateway bleibt gestoppt.',
                    result_handler=lambda _:load_sources(profile))
        wizard._button(area,'Geprüftes Original aus Live-Cache entfernen',purge).pack(anchor='w',pady=6)
    def load_sources(profile):
        wizard._run_async(lambda:initial_setup.email_gateway_sources(profile),
            success='Private Quellenmetadaten geladen; Gateway bleibt gestoppt.',result_handler=show_sources)
    def show_profiles(value):
        for child in area.winfo_children():child.destroy()
        rows=value['profiles']
        if not rows:
            wizard._label(area,'Keine gespeicherten E-Mail-Profile.',size=10).pack(anchor='w');return
        complete=[row for row in rows if row.get('status')!='incomplete-profile']
        for row in rows:
            wizard._label(area,(row.get('connector') or 'Unvollständiges Profil')+' · '+str(row['active'])+' aktive Originale · '+str(row['stored_bytes'])+' Bytes',size=10,color=wizard.MUTED).pack(anchor='w',pady=3)
        if not complete:return
        choices={(row.get('connector') or 'Leeres Profil')+' · '+row['profile']:row['profile'] for row in complete}
        selected=wizard._choice(area,'Privates E-Mail-Quellenprofil',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        wizard._button(area,'Ausgewähltes Quellenprofil prüfen',lambda:load_sources(choices[selected.get()])).pack(anchor='w',pady=6)
    wizard._button(wizard.content,'Gateway stoppen und E-Mail-Quellenprofile laden',lambda:wizard._run_async(initial_setup.email_gateway_sources,
        success='Private Profilmetadaten geladen; Gateway bleibt gestoppt.',result_handler=show_profiles)).pack(anchor='w',pady=6)
    wizard._button(wizard.content,'Zur Gateway-Verwaltung',lambda:wizard.show('gateways')).pack(anchor='w',pady=6)


class AccountForm:
    """Dedicated mail fields; no credential in a widget label, argv or audit."""
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={};self.modes={}
        for key,label,default in [('address','E-Mail-Dienstkonto · exakte Adresse',''),
                ('password','E-Mail-App-Passwort · geschützt',''),('imap_host','IMAP-Hostname · exakt',''),
                ('imap_port','IMAP-Port','993'),('smtp_host','SMTP-Hostname · exakt',''),
                ('smtp_port','SMTP-Port','465'),('authserv_id','Empfangsserver Authentication-Results authserv-id','')]:
            self.fields[key]=wizard._field(self.frame,label,default,secret=key=='password')
        for protocol in ['imap','smtp']:
            self.modes[protocol+'_security']=wizard._choice(self.frame,protocol.upper()+' TLS-Modus',['tls','starttls'],'tls')
        self.trust=tk.BooleanVar(value=False)
        tk.Checkbutton(self.frame,text='Empfangsserver entfernt gefälschte eigene Authentication-Results und setzt vertrauenswürdige Ergebnisse voran: unabhängig geprüft',
            variable=self.trust,bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,
            wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=6)
        wizard._label(self.frame,'Eigenes Dienstkonto mit IMAP-INBOX-Leserecht und SMTP-Senderecht verwenden. '
            'Nur überprüftes TLS oder STARTTLS; OAuth-only-Konten benötigen ein vom Anbieter freigegebenes App-Passwort. '
            'Die authserv-id muss dem tatsächlich vertrauenswürdigen Empfangsserver entsprechen. Domain-Authentifizierung beweist keine individuelle Person. '
            'Unbekannte Absender und Threads erhalten keine Rechte. Keine Portweiterleitung oder öffentlicher HAOS-Webhook erforderlich. '
            'Konto- oder Passwortwechsel entzieht bestehende Freigaben. Gespeicherte Postfach- und Recovery-Daten bleiben erhalten.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        wizard._button(self.frame,'Gespeichertes E-Mail-Konto ohne Versand prüfen',self.inspect).pack(anchor='w',pady=4)
        wizard._button(self.frame,'E-Mail-Anmeldung erneut erlauben',self.retry).pack(anchor='w',pady=4)
        for key,entry in self.fields.items():
            if key=='password':continue
            variable=tk.StringVar(value=entry.get());entry.configure(textvariable=variable);entry._haos_public_value=variable
            variable.trace_add('write',self.clear_secret)
        for variable in self.modes.values():variable.trace_add('write',self.clear_secret)

    def clear_secret(self,*_args):
        self.fields['password'].delete(0,self.wizard.tk.END);self.trust.set(False)

    def reset(self,existing=None):
        self.clear_secret();tk=self.wizard.tk
        for key,entry in self.fields.items():
            entry.delete(0,tk.END)
            if key!='password':entry.insert(0,str((existing or {}).get(key,{'imap_port':993,'smtp_port':465}.get(key,''))))
        for key,variable in self.modes.items():variable.set((existing or {}).get(key,'tls'))

    def configure(self):
        wizard=self.wizard;account={key:entry.get() for key,entry in self.fields.items()}
        account.update({key:variable.get() for key,variable in self.modes.items()})
        consent=self.trust.get();connector=self.connector();self.clear_secret()
        def save():
            for key in ['imap_port','smtp_port']:
                raw=account[key]
                if not raw.isascii() or not raw.isdecimal() or len(raw)>5 or not 1<=int(raw)<=65535:
                    raise ValueError('IMAP-/SMTP-Port muss eine ganze Zahl von 1 bis 65535 sein')
                account[key]=int(raw)
            return initial_setup.configure_email_gateway(connector,account,trust_authentication_results=consent)
        wizard._run_async(save,success='E-Mail-Konto gespeichert. Konto ohne Versand prüfen und exakte Absender neu freigeben; Gateway bleibt gestoppt.')

    def inspect(self):
        wizard=self.wizard;connector=self.connector();self.clear_secret()
        def result(value):
            if not value['authenticated']:
                wizard.status.configure(text='E-Mail-Kontoprüfung abgelehnt: '+value['error']+'. Konto, TLS-Modus und Serverrechte prüfen.')
        wizard._run_async(lambda:initial_setup.inspect_email_gateway_account(connector),
            success='Gespeichertes IMAP-/SMTP-Konto authentifiziert. Keine Mail gesendet und keine Absenderrechte erteilt.',result_handler=result)

    def retry(self):
        wizard=self.wizard;connector=self.connector();self.clear_secret()
        wizard._run_async(lambda:initial_setup.retry_email_gateway_auth(connector),
            success='Neue Anmeldung ausdrücklich erlaubt. Postfachsperren, Wartefrist und Freigaben bleiben erhalten; Dienst manuell starten.')


class PairForm:
    def __init__(self,wizard,parent,platform,account,sender,chat,scope,thread,rights,before):
        self.wizard=wizard;self.platform=platform;self.account=account;self.sender=sender;self.chat=chat
        self.scope=scope;self.thread=thread;self.rights=rights;self.before=before;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.active=False
        self.flags={key:tk.BooleanVar(value=False) for key in ['allow_media','allow_voice','allow_video','allow_outbound_media']}
        self.boxes={}
        for key,label in [('allow_media','E-Mail-Bilder und Dokumente dieses Absenders ausdrücklich freigeben'),
                ('allow_voice','E-Mail-Sprachnachrichten dieses Absenders ausdrücklich freigeben'),
                ('allow_video','E-Mail-Videodateien dieses Absenders ausdrücklich freigeben'),
                ('allow_outbound_media','Markierte Ergebnisdateien als E-Mail-Anhänge an diesen Absender senden')]:
            box=tk.Checkbutton(self.frame,text=label,variable=self.flags[key],bg=wizard.PANEL,fg=wizard.TEXT,
                selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left');box.pack(anchor='w',pady=5);self.boxes[key]=box
        wizard._label(self.frame,'Absender und Antwortadresse sind dieselbe exakte kanonische E-Mail-Adresse. '
            'Bereich ist ausschließlich die gespeicherte IMAP-INBOX. Ein leerer Thread erlaubt nur Nachrichten ohne Root-Thread; '
            'für Antworten in einem bestehenden Gespräch dessen exakte Root-Message-ID angeben, einschließlich <…>. Keine Platzhalter. '
            'Die Domain-Authentifizierung des Empfangsservers beweist keine individuelle Person. '
            'Höchstens vier Anhänge, je 8 MiB; PNG/JPEG insgesamt 2 MiB. Voice benötigt lokalen Spracherkennungsdienst und Erstellrecht. '
            'Video geht als Datei in die Mission. Ergebnisanhänge benötigen Leserecht; keine öffentliche Download-Adresse erforderlich. '
            'SMTP-Annahme beweist keinen Empfang.',size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        for field in (sender,chat,thread):
            variable=getattr(field,'_haos_public_value',None)
            if variable is None:
                variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
            variable.trace_add('write',self.clear)
        sender._haos_public_value.trace_add('write',self.sender_changed)
        for key in ['address','imap_host','imap_port']:
            account.fields[key]._haos_public_value.trace_add('write',self.changed)
        for variable in rights.values():variable.trace_add('write',self.permissions)
        def platform_changed(*_args):
            if platform.get()=='email':wizard.root.after_idle(self.changed)
            else:self.changed()
        platform.trace_add('write',platform_changed)

    def clear(self,*_args):
        for variable in self.flags.values():variable.set(False)

    def sender_changed(self,*_args):
        if self.platform.get()!='email':return
        self.chat.configure(state='normal');self.chat.delete(0,self.wizard.tk.END);self.chat.insert(0,self.sender.get());self.chat.configure(state='disabled')

    def permissions(self,*_args):
        for key,box in self.boxes.items():
            allowed=self.rights['read' if key=='allow_outbound_media' else 'create'].get()
            if not allowed:self.flags[key].set(False)
            box.configure(state='normal' if allowed else 'disabled')

    def changed(self,*_args):
        self.clear();active=self.platform.get()=='email';tk=self.wizard.tk
        if active:
            self.frame.pack(fill='x',before=self.before)
            self.scope.configure(state='normal');self.scope.delete(0,tk.END)
            from .gateway_email import address,hostname,scope
            try:
                values={key:self.account.fields[key].get() for key in ['address','imap_host','imap_port']}
                address(values['address']);hostname(values['imap_host']);raw=values['imap_port']
                if not raw.isascii() or not raw.isdecimal() or len(raw)>5 or not 1<=int(raw)<=65535:raise ValueError('port')
                values['imap_port']=int(raw);self.scope.insert(0,scope(values))
            except ValueError:pass
            self.scope.configure(state='disabled');self.thread.configure(state='normal')
            if not self.active:
                for field in [self.sender,self.chat,self.thread]:field.configure(state='normal');field.delete(0,tk.END)
            self.sender_changed();self.permissions()
        else:
            self.frame.pack_forget()
            if self.active:
                for field in [self.sender,self.chat,self.scope,self.thread]:field.configure(state='normal');field.delete(0,tk.END)
        self.active=active

    def options(self):return {key:variable.get() for key,variable in self.flags.items()}
