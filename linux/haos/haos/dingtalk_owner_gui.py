"""Real owner account, observed-ID pairing, explicit grants and offline recovery."""
from . import initial_setup
from . import dingtalk_owner_setup as owner

LABELS={'created':'DingTalk-Profil vorbereitet','connecting':'DingTalk-App wird geprüft',
    'connected-ws':'DingTalk-Stream verbunden; externe Zustellung ungeprüft',
    'storage-unavailable':'DingTalk-Speicher nicht verfügbar; Belege erhalten',
    'tls-refused':'DingTalk-TLS abgelehnt; Zertifikat und Netzwerk prüfen',
    'authentication-refused':'DingTalk-Anmeldung abgelehnt; App-Rechte und Secret prüfen',
    'rate-limited':'DingTalk begrenzt Anfragen; gespeicherte Wartefrist gilt',
    'transport-unavailable':'DingTalk-Verbindung nicht verfügbar; Netzwerk und App prüfen',
    'revoked':'DingTalk-Freigabe entzogen','disconnected':'DingTalk getrennt; Daten erhalten',
    'closed':'DingTalk-Profil geschlossen; Daten erhalten'}


class AccountForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={}
        for key,label,secret in [('client_id','DingTalk Client ID / AppKey',False),('client_secret','DingTalk Client Secret / AppSecret',True),
                ('corp_id','DingTalk Corporation ID',False),('robot_code','DingTalk Robot Code',False)]:
            self.fields[key]=wizard._field(self.frame,label,secret=secret)
        self.mode=wizard._choice(self.frame,'DingTalk-Antwortweg',['session','robot'],'session')
        wizard._label(self.frame,'Interne Unternehmens-App mit Bot und Stream-Modus aktivieren. Client-ID, Secret, Corporation-ID und Robot-Code exakt aus der DingTalk-App übernehmen. '
            'Stream benötigt keinen eingehenden Port. session nutzt die befristete Antwortadresse; robot nutzt ausdrücklich freigegebene Robot-API-Rechte für Gruppen und Einzelchats und ist für Ergebnisdateien erforderlich. '
            'Kein automatischer Wechsel. Die Kontoprüfung bestätigt nur App-Anmeldung, keine Corporation-/Robot-Zuordnung oder Zustellung. Kontoänderungen entziehen bestehende Freigaben.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        wizard._button(self.frame,'DingTalk-Konto ohne Nachricht prüfen',self.inspect).pack(anchor='w',pady=4)
        wizard._button(self.frame,'DingTalk-Anmeldung erneut erlauben',self.retry).pack(anchor='w',pady=4)
        for key,entry in self.fields.items():
            if key=='client_secret':continue
            variable=tk.StringVar(value=entry.get());entry.configure(textvariable=variable);entry._haos_public_value=variable
            variable.trace_add('write',self.clear_secret)
        self.mode.trace_add('write',self.clear_secret);self.reset()

    def clear_secret(self,*_args):self.fields['client_secret'].delete(0,self.wizard.tk.END)

    def reset(self,existing=None):
        self.clear_secret();value=existing or {};tk=self.wizard.tk
        for key,entry in self.fields.items():
            entry.delete(0,tk.END)
            if key!='client_secret':entry.insert(0,str(value.get(key,'')))
        self.mode.set(value.get('reply_mode','session'))

    def configure(self):
        values={key:entry.get() for key,entry in self.fields.items()};values['reply_mode']=self.mode.get()
        connector=self.connector();self.clear_secret()
        self.wizard._run_async(lambda:owner.configure(connector,values),
            success='DingTalk-Konto gespeichert. Ohne Versand prüfen und Absender ausdrücklich freigeben; Dienst bleibt gestoppt.')

    def inspect(self):
        connector=self.connector();self.clear_secret();w=self.wizard
        def show(value):
            w.status.configure(text=('DingTalk-Kontoprüfung abgelehnt: '+value['error'] if 'error' in value else
                'DingTalk-App-Anmeldung bestätigt. Corporation/Robot und externe Zustellung ungeprüft; keine Nachricht gesendet.'))
        w._run_async(lambda:owner.inspect(connector),result_handler=show)

    def retry(self):
        connector=self.connector();self.clear_secret()
        self.wizard._run_async(lambda:owner.retry_auth(connector),
            success='Neue DingTalk-Anmeldung erlaubt. Wartefristen und unklare Zustellungen bleiben geschützt; Dienst bleibt gestoppt.')


class PairForm:
    def __init__(self,wizard,parent,platform,account,sender,chat,scope,thread,rights,before):
        self.wizard=wizard;self.platform=platform;self.account=account;self.sender=sender;self.chat=chat;self.scope=scope;self.thread=thread
        self.rights=rights;self.before=before;self.active=False;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL)
        self.flags={key:tk.BooleanVar(value=False) for key in ['allow_media','allow_voice','allow_video','allow_outbound_media']}
        self.mention=tk.BooleanVar(value=True);self.boxes={}
        for key,label in [('allow_media','DingTalk-Bilder und Dokumente ausdrücklich freigeben'),('allow_voice','DingTalk-Sprachnachrichten ausdrücklich freigeben'),
                ('allow_video','DingTalk-Videoeingang ausdrücklich freigeben'),('allow_outbound_media','Markierte Ergebnisdateien an diesen DingTalk-Chat senden (robot)')]:
            box=tk.Checkbutton(self.frame,text=label,variable=self.flags[key],bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,
                wraplength=wizard.label_wrap,justify='left');box.pack(anchor='w',pady=4);self.boxes[key]=box
        tk.Checkbutton(self.frame,text='In Gruppen exakte Bot-Erwähnung verlangen',variable=self.mention,bg=wizard.PANEL,
            fg=wizard.TEXT,selectcolor=wizard.BG).pack(anchor='w')
        wizard._label(self.frame,'Exakte opaque senderId und conversationId verwenden; keine staffId oder Anzeigenamen. '
            'Zum Erfassen zuerst Konto speichern. Während der Erfassung selbst den angezeigten Code an den Bot senden; in Gruppen den Bot erwähnen. '
            'Die Erfassung vergibt keine Rechte und startet keine Mission. Anschließend Absender, Chat und Rechte prüfen und ausdrücklich freigeben. '
            'Keine Topic-Threads im gepinnten Adapter. Voice benötigt den lokalen Sprachdienst; Ergebnisse benötigen Leserecht und robot-Antwortweg.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        self.code=wizard._field(self.frame,'Einmaliger Erfassungscode (60 Sekunden)');self.code.configure(state='readonly')
        wizard._button(self.frame,'DingTalk-IDs ohne Freigabe erfassen',self.observe).pack(anchor='w',pady=4)
        wizard._button(self.frame,'Erfassungscode kopieren',self.copy_code).pack(anchor='w',pady=4)
        for field in (sender,chat,thread):
            variable=getattr(field,'_haos_public_value',None)
            if variable is None:variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
            variable.trace_add('write',self.clear)
        for key in ['client_id','corp_id','robot_code']:account.fields[key]._haos_public_value.trace_add('write',self.changed)
        account.mode.trace_add('write',self.changed)
        for value in rights.values():value.trace_add('write',self.permissions)
        def platform_changed(*_args):
            if platform.get()=='dingtalk':wizard.root.after_idle(self.changed)
            else:self.changed()
        platform.trace_add('write',platform_changed)

    def clear(self,*_args):
        for value in self.flags.values():value.set(False)
        self.mention.set(True)

    def permissions(self,*_args):
        for key,box in self.boxes.items():
            allowed=self.rights['read' if key=='allow_outbound_media' else 'create'].get()
            if key=='allow_outbound_media':allowed=allowed and self.account.mode.get()=='robot'
            if not allowed:self.flags[key].set(False)
            box.configure(state='normal' if allowed else 'disabled')

    def changed(self,*_args):
        self.clear();active=self.platform.get()=='dingtalk'
        if active:
            self.frame.pack(fill='x',before=self.before);self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END)
            from .gateway_dingtalk import scope
            self.scope.insert(0,scope({key:self.account.fields[key].get() for key in ['client_id','corp_id','robot_code']}))
            self.scope.configure(state='disabled');self.thread.configure(state='normal');self.thread.delete(0,self.wizard.tk.END)
            self.thread.configure(state='disabled');self.permissions()
        else:
            self.frame.pack_forget()
            if self.active:
                self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END);self.thread.configure(state='normal')
        self.active=active

    def copy_code(self):
        value=self.code.get()
        if value:self.wizard.root.clipboard_clear();self.wizard.root.clipboard_append(value)

    def observe(self):
        import secrets,time
        w=self.wizard
        if w.running:return
        connector=self.account.connector();now=time.time_ns()//1000000
        request={'nonce':secrets.token_hex(16),'since':now,'until':now+60000}
        snapshot=tuple(self.account.fields[key].get() for key in ['client_id','corp_id','robot_code'])
        self.account.clear_secret();self.clear();self.code.configure(state='normal');self.code.delete(0,w.tk.END)
        self.code.insert(0,'HAOS koppeln '+request['nonce']);self.code.configure(state='readonly')
        def show(value):
            if (self.platform.get()!='dingtalk' or self.account.connector()!=connector
                    or tuple(self.account.fields[key].get() for key in ['client_id','corp_id','robot_code'])!=snapshot):
                w.status.configure(text='Konto geändert; erfasste IDs werden nicht übernommen. Neu erfassen.');return
            if not value['observed']:
                w.status.configure(text='DingTalk-Erfassung abgelaufen. Keine Freigabe oder Mission erstellt.');return
            item=value['candidate']
            from .gateway_dingtalk import scope
            if item['scope']!=scope(dict(zip(['client_id','corp_id','robot_code'],snapshot))):
                w.status.configure(text='Gespeichertes Konto stimmt nicht mit Formular überein. Formular neu laden.');return
            for field,key in [(self.sender,'sender'),(self.chat,'chat')]:field.delete(0,w.tk.END);field.insert(0,item[key])
            self.clear();w.status.configure(text='Unberechtigte DingTalk-IDs erfasst. Absender, Chat und Rechte prüfen und separat freigeben; keine Mission gestartet.')
        w._run_async(lambda:owner.observe(connector,request),result_handler=show)

    def options(self):return {**{key:value.get() for key,value in self.flags.items()},'require_mention':self.mention.get()}


def recovery(wizard,parent,value,reload):
    tk=wizard.tk
    rows=[row for row in value.get('native_outgoing',[]) if row.get('platform')=='dingtalk']
    for batch in value.get('native_batches',[]):
        wizard._label(parent,'DingTalk-Ergebnisgruppe · '+batch['delivery_id']+' · '+str(batch['confirmed_parts'])+'/'+str(batch['parts'])
            +' Teile bestätigt · '+batch['state']+(' · lokaler API-Annahmebeleg '+batch['native_acceptance_receipt'] if batch.get('native_acceptance_receipt') else '')
            +' · kein Lesebeleg',size=10,color=wizard.MUTED).pack(anchor='w',pady=3)
    for row in rows:
        wizard._label(parent,'DingTalk-Ausgang · '+row['delivery_id']+' · '+row.get('operation','Text')
            +' · Teil '+str(row.get('part','–'))+' · Versuch '+str(row['attempt'])+' · '+row['state']
            +' · API-Annahme ist kein Lesebeleg'+(' · lokaler Beleg '+row['native_acceptance_receipt'] if row.get('native_acceptance_receipt') else ''),size=10,color=wizard.MUTED).pack(anchor='w',pady=3)
    uncertain=[row for row in rows if row['state'] in {'writing','uncertain','rejected'} and row['attempt']<5]
    if not uncertain:return
    choices={row['delivery_id']+' · '+row.get('operation','Text')+' / '+str(row.get('part','–'))+' / '+str(row['attempt']):row for row in uncertain}
    selected=wizard._choice(parent,'Geprüfter DingTalk-Schreibversuch',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
    note=wizard._field(parent,'DingTalk-Prüfnotiz ohne Geheimnisse');confirmed=tk.BooleanVar(value=False)
    selected.trace_add('write',lambda *_:confirmed.set(False))
    tk.Checkbutton(parent,text='Nichtannahme dieses exakten Uploads oder dieser Antwort unabhängig geprüft',variable=confirmed,
        bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
    def approve():
        from tkinter import messagebox
        row=dict(choices[selected.get()]);evidence=note.get();checked=confirmed.get()
        if not checked:wizard.status.configure(text='DingTalk-Nichtannahme zuerst unabhängig prüfen und bestätigen.');return
        if not messagebox.askyesno('DingTalk-Wiederholung','Nur die geprüfte private Teilsperre freigeben? Controller-Zustellung bleibt separat zu prüfen. Jetzt wird nichts gesendet.'):return
        confirmed.set(False)
        action='approve-dingtalk-part-retry' if 'part' in row else 'approve-dingtalk-retry'
        wizard._run_async(lambda:owner.recovery(row,action,evidence,True,confirmed_not_accepted=checked),
            success='Private DingTalk-Entscheidung gespeichert. Controller separat prüfen; Dienste bleiben gestoppt.',result_handler=lambda _:reload())
    wizard._button(parent,'Geprüfte DingTalk-Teilsperre freigeben',approve).pack(anchor='w',pady=4)


def sources(wizard):
    tk=wizard.tk;wizard._head('DingTalk-Quellen verwalten','Erhaltene Originale · getrennte Entscheidungen')
    wizard._label(wizard.content,'Diese Prüfung stoppt den Gateway-Dienst. Nur nach Entzug oder Änderung der ursprünglichen Freigabe '
        'können ausgewählte Quelldaten ausdrücklich entfernt werden. '
        'Replay-Sperren und Audit bleiben erhalten. Andere Controller-/Agent-Kopien und Backups bleiben bestehen; keine sichere Datenträgerlöschung.',
        size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
    area=tk.Frame(wizard.content,bg=wizard.PANEL);area.pack(fill='x')
    def show(value):
        for child in area.winfo_children():child.destroy()
        rows=value['sources']
        if not rows:wizard._label(area,'Keine gespeicherten Quellen.',size=10).pack(anchor='w');return
        choices={row['id']+' · '+str(row['stored_bytes'])+' B':row for row in rows}
        selected=wizard._choice(area,'DingTalk-Original',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        note=wizard._field(area,'DingTalk-Löschprüfnotiz ohne Geheimnisse');confirmed=tk.BooleanVar(value=False)
        selected.trace_add('write',lambda *_:confirmed.set(False))
        tk.Checkbutton(area,text='Ausgewählte Quelldaten und entzogene Freigabe unabhängig geprüft',variable=confirmed,
            bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
        def remove():
            from tkinter import messagebox
            row=dict(choices[selected.get()]);row.update(profile=value['profile'],kind=value['kind']);evidence=note.get()
            if not confirmed.get() or not row['purge_allowed'] or row['purged']:
                wizard.status.configure(text='Aktive oder bereits entfernte Quelle bleibt geschützt. Freigabe entziehen und neu prüfen.');return
            if not messagebox.askyesno('DingTalk-Quelldaten entfernen','Nur diese geprüften Quelldaten logisch entfernen und Replay-Sperre/Audit behalten?'):return
            confirmed.set(False)
            def perform():
                owner.recovery(row,'purge-dingtalk-source',evidence,True)
                return owner.sources(value['profile'],value['kind'])
            wizard._run_async(perform,success='Ausgewählte DingTalk-Quelldaten entfernt; Belege erhalten.',result_handler=show)
        wizard._button(area,'Geprüfte DingTalk-Quelldaten entfernen',remove).pack(anchor='w',pady=5)
    def profiles(value):
        choices={row['profile']+' · '+kind:(row['profile'],kind) for row in value['profiles'] for kind in row['kinds']}
        if not choices:wizard._label(area,'Keine erhaltenen DingTalk-Profile.',size=10).pack(anchor='w');return
        selected=wizard._choice(wizard.content,'DingTalk-Quellspeicher',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        def load():
            profile,kind=choices[selected.get()]
            wizard._run_async(lambda:owner.sources(profile,kind),success='DingTalk-Quellmetadaten geladen.',result_handler=show)
        wizard._button(wizard.content,'DingTalk-Quellmetadaten laden',load).pack(anchor='w',pady=5)
    wizard._button(wizard.content,'DingTalk-Profile prüfen',lambda:wizard._run_async(owner.sources,
        success='DingTalk-Profile geladen; Gateway bleibt gestoppt.',result_handler=profiles)).pack(anchor='w',pady=5)
    wizard._button(wizard.content,'Zurück zu Gateways',lambda:wizard.show('gateways')).pack(anchor='w',pady=6)


def outputs(wizard):
    tk=wizard.tk;wizard._head('DingTalk-Ausgabecache verwalten','Erhaltene Konvertierungen · Replay-Sperren bleiben bestehen')
    wizard._label(wizard.content,'Die Prüfung stoppt den Gateway-Dienst. Ausgewählte Konvertierungsbytes können nach Entzug oder Änderung der ursprünglichen Freigabe logisch entfernt werden. '
        'Belege und Replay-Sperren bleiben erhalten; keine automatische Wiederherstellung. Originale, Controller-/Agent-Kopien, Backups und WAL sind getrennt zu prüfen.',
        size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
    area=tk.Frame(wizard.content,bg=wizard.PANEL);area.pack(fill='x')
    def show(value):
        for child in area.winfo_children():child.destroy()
        rows=value['outputs']
        if not rows:wizard._label(area,'Keine erhaltenen Konvertierungen.',size=10).pack(anchor='w');return
        choices={row['id']+' · '+row['name']+' · '+str(row['stored_bytes'])+' B':row for row in rows}
        selected=wizard._choice(area,'Geprüfte DingTalk-Konvertierung',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        note=wizard._field(area,'Prüfnotiz ohne Geheimnisse');confirmed=tk.BooleanVar(value=False)
        selected.trace_add('write',lambda *_:confirmed.set(False))
        tk.Checkbutton(area,text='Genau diese Konvertierung und entzogene Freigabe geprüft',variable=confirmed,
            bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w')
        def remove():
            from tkinter import messagebox
            row=dict(choices[selected.get()]);evidence=note.get()
            if not confirmed.get() or not row['purge_allowed'] or row['purged']:
                wizard.status.configure(text='Aktive oder bereits entfernte Konvertierung bleibt geschützt. Freigabe entziehen und neu prüfen.');return
            if not messagebox.askyesno('DingTalk-Konvertierung entfernen','Nur diese geprüften Bytes logisch entfernen und Belege sowie Replay-Sperren erhalten?'):return
            confirmed.set(False)
            def perform():
                owner.recovery(row,'purge-dingtalk-output-cache',evidence,True)
                return owner.outputs()
            wizard._run_async(perform,success='Geprüfte Konvertierungsbytes entfernt; Belege erhalten.',result_handler=show)
        wizard._button(area,'Geprüfte Konvertierung entfernen',remove).pack(anchor='w',pady=5)
        if value['history_truncated']:wizard._label(area,'Weitere historische Belege vorhanden; aktive Bytes werden zuerst angezeigt.',size=10,color=wizard.MUTED).pack(anchor='w')
    wizard._button(wizard.content,'DingTalk-Konvertierungsmetadaten laden',lambda:wizard._run_async(owner.outputs,
        success='DingTalk-Metadaten geladen; Gateway bleibt gestoppt.',result_handler=show)).pack(anchor='w',pady=5)
    wizard._button(wizard.content,'Zurück zu Gateways',lambda:wizard.show('gateways')).pack(anchor='w',pady=6)
