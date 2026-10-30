"""Trusted owner A2A forms; credentials are entered locally, never read back."""
from . import a2a_owner_setup as owner

ERRORS={'sdk-unavailable':'Gepinnte A2A-Runtime fehlt oder ist unvollständig.',
    'listener-unavailable':'Der gespeicherte lokale Port kann nicht exklusiv gebunden werden.',
    'storage-unavailable':'Gespeichertes A2A-Journal prüfen; Daten bleiben erhalten.',
    'authority-refused':'Identität, Freigabe, Task-Zustand oder Prüfbeleg lässt diese Aktion nicht zu; Liste neu prüfen.'}


def flag(wizard,parent,label,variable):
    box=wizard.tk.Checkbutton(parent,text=label,variable=variable,bg=wizard.PANEL,fg=wizard.TEXT,
        selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left',anchor='w')
    box.pack(anchor='w',pady=3);return box


class AccountForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;self.metadata={};self.resetting=False;self.on_saved=None;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={}
        for key,label,secret in [('agent_name','Öffentlicher A2A-Servername',False),('port','Lokaler HTTPS-Port (1024–65535)',False),
                ('public_url','Öffentliche HTTPS-Adresse mit /a2a',False),('peer','Exakter Name des ersten/ausgewählten Peers',False),
                ('token','Privater Bearer-Schlüssel dieses Peers',True),('certificate','Zertifikatsdatei (PEM, vollständige Kette)',False),
                ('private_key','Private Schlüsseldatei (PEM)',False)]:
            self.fields[key]=wizard._field(self.frame,label,secret=secret)
        self.host=wizard._choice(self.frame,'Lokale Bind-Adresse',['127.0.0.1','0.0.0.0','::'],'127.0.0.1')
        self.public=tk.BooleanVar(value=False);self.keep_tls=tk.BooleanVar(value=False);self.keep_token=tk.BooleanVar(value=False);self.show_key=tk.BooleanVar(value=False)
        flag(wizard,self.frame,'HTTPS-Listener im Netzwerk ausdrücklich freigeben',self.public)
        flag(wizard,self.frame,'Gespeichertes Zertifikat und privaten Schlüssel beibehalten',self.keep_tls)
        flag(wizard,self.frame,'Schlüssel des exakt gespeicherten Peers beibehalten',self.keep_token)
        flag(wizard,self.frame,'Neu eingegebenen Peer-Schlüssel hier anzeigen',self.show_key)
        self.show_key.trace_add('write',lambda *_:self.fields['token'].configure(show='' if self.show_key.get() else '•'))
        wizard._label(self.frame,'Jeder Peer benötigt einen eigenen zufälligen Bearer-Schlüssel. Die öffentliche Adresse verwendet HTTPS auf Port 443; '
            'Router oder Reverse Proxy müssen den gewählten lokalen Port korrekt erreichen. Diese Seite ändert keine Router-Regeln. '
            'Die lokale Prüfung bestätigt Runtime, Zertifikat und Portbindung; externe Erreichbarkeit bleibt ungeprüft. '
            'Kontoänderungen entziehen alle Freigaben dieses Konnektors. Bestehende Tasks und Recovery-Daten bleiben erhalten.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        wizard._button(self.frame,'A2A lokal ohne Nachricht prüfen',self.inspect).pack(anchor='w',pady=4)
        wizard._button(self.frame,'Privaten Peer-Schlüssel erzeugen',self.generate).pack(anchor='w',pady=4)
        self.keep_tls.trace_add('write',self.material_state);self.keep_token.trace_add('write',self.material_state)
        for key in ['agent_name','port','public_url','peer']:
            entry=self.fields[key];variable=tk.StringVar(value=entry.get());entry.configure(textvariable=variable);entry._haos_public_value=variable
            variable.trace_add('write',self.changed)
        self.host.trace_add('write',self.changed);self.reset()

    def clear_secret(self,*_args):
        self.show_key.set(False)
        self.fields['token'].configure(state='normal');self.fields['token'].delete(0,self.wizard.tk.END)
        self.material_state()

    def material_state(self,*_args):
        for key in ['certificate','private_key']:
            self.fields[key].configure(state='normal')
            if self.keep_tls.get():self.fields[key].delete(0,self.wizard.tk.END);self.fields[key].configure(state='disabled')
        self.fields['token'].configure(state='normal')
        if self.keep_token.get():self.fields['token'].delete(0,self.wizard.tk.END);self.fields['token'].configure(state='disabled')

    def changed(self,*_args):
        if self.resetting:return
        self.keep_token.set(False);self.public.set(False);self.clear_secret()

    def reset(self,existing=None):
        self.resetting=True;self.metadata=existing or {};tk=self.wizard.tk
        try:
            self.show_key.set(False)
            defaults={'agent_name':'HAOS','port':8448,'public_url':'','peer':''}
            if self.metadata.get('peers'):defaults['peer']=self.metadata['peers'][0]['name']
            for key,entry in self.fields.items():
                entry.configure(state='normal');entry.delete(0,tk.END)
                if key in defaults:entry.insert(0,str(self.metadata.get(key,defaults[key])))
            self.host.set(self.metadata.get('bind_host','127.0.0.1'));self.public.set(self.metadata.get('public_listener',False))
            self.keep_tls.set(self.metadata.get('saved_tls',False));self.keep_token.set(bool(self.metadata.get('peers')))
        finally:self.resetting=False;self.material_state()

    def generate(self):
        import secrets
        self.keep_token.set(False);self.fields['token'].configure(state='normal')
        self.fields['token'].delete(0,self.wizard.tk.END);self.fields['token'].insert(0,secrets.token_urlsafe(48))

    def configure(self):
        values={key:entry.get() for key,entry in self.fields.items()};host=self.host.get();public=self.public.get()
        keep_tls=self.keep_tls.get();keep_token=self.keep_token.get();connector=self.connector();self.clear_secret()
        def perform():
            port=values['port']
            if not port.isascii() or not port.isdecimal() or not 1<=len(port)<=5:raise ValueError('Lokalen A2A-Port als ganze Zahl eingeben.')
            server={'agent_name':values['agent_name'],'port':int(port),'public_url':values['public_url'],'bind_host':host,'public_listener':public}
            owner.save_account(connector,server,values['peer'],values['token'],values['certificate'],values['private_key'],
                keep_tls=keep_tls,keep_token=keep_token)
            return owner.public(owner.saved(connector)[2])
        self.wizard._run_async(perform,success='A2A-Konto gespeichert. Kontexte ausdrücklich freigeben; der Dienst bleibt gestoppt.',result_handler=self.saved)

    def saved(self,value):
        if not self.frame.winfo_exists():return
        self.reset(value)
        if self.on_saved is not None:self.on_saved(value)

    def inspect(self):
        connector=self.connector();self.clear_secret()
        def show(value):
            self.wizard.status.configure(text=ERRORS.get(value.get('error'),'A2A lokal bereit: Runtime, TLS und Portbindung geprüft. Externe Erreichbarkeit ungeprüft; keine Nachricht gesendet.'))
        self.wizard._run_async(lambda:owner.inspect(connector),result_handler=show)


class PeerForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;self.metadata={};self.resetting=False;self.on_saved=None;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={}
        wizard._label(self.frame,'Weitere Peers, Download-Freigaben und Callbacks',size=12).pack(anchor='w',pady=5)
        self.peers_label=wizard._label(self.frame,'Noch keine gespeicherten Peers.',size=10,color=wizard.MUTED);self.peers_label.pack(anchor='w')
        for key,label,secret in [('peer','Exakter gespeicherter oder neuer Peer-Name',False),('token','Neuer privater Peer-Schlüssel',True),
                ('origins','Genehmigte HTTPS-Download-Ursprünge (maximal vier, durch Komma getrennt)',False),
                ('callback','Exakte HTTPS-Callback-Adresse (optional)',False),('signing','Separater privater Callback-Signierschlüssel',True)]:
            self.fields[key]=wizard._field(self.frame,label,secret=secret)
        self.keep_token=tk.BooleanVar(value=False);self.keep_signing=tk.BooleanVar(value=False);self.show_keys=tk.BooleanVar(value=False)
        flag(wizard,self.frame,'Schlüssel des exakt gespeicherten Peers beibehalten',self.keep_token)
        flag(wizard,self.frame,'Signierschlüssel für denselben Peer und dieselbe Callback-Adresse beibehalten',self.keep_signing)
        flag(wizard,self.frame,'Neu eingegebene private Schlüssel hier anzeigen',self.show_keys)
        self.show_keys.trace_add('write',self.material_state)
        self.keep_token.trace_add('write',self.material_state);self.keep_signing.trace_add('write',self.material_state)
        wizard._label(self.frame,'Download-Ursprünge gelten nur für diesen Peer und benötigen zusätzlich eine Medienfreigabe je Kontext. '
            'Callbacks brauchen einen eigenen Signierschlüssel und die separate Kontextfreigabe. Leere Ursprünge oder Callback-Adresse entziehen diese Einstellung. '
            'Änderungen entziehen bestehende Konnektor-Freigaben. Unklare Callback-Zustellungen werden nicht automatisch wiederholt.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        wizard._button(self.frame,'Peer-Einstellungen privat speichern',self.save).pack(anchor='w',pady=3)
        wizard._button(self.frame,'Ausgewählten Peer entziehen',self.remove).pack(anchor='w',pady=3)
        self.peer_variable=tk.StringVar();self.fields['peer'].configure(textvariable=self.peer_variable)
        self.peer_variable.trace_add('write',self.select_peer)
        self.callback_variable=tk.StringVar();self.fields['callback'].configure(textvariable=self.callback_variable)
        self.callback_variable.trace_add('write',self.callback_changed)

    def clear_secret(self,*_args):
        self.show_keys.set(False)
        for key in ['token','signing']:self.fields[key].configure(state='normal');self.fields[key].delete(0,self.wizard.tk.END)
        self.material_state()

    def material_state(self,*_args):
        for key,keep in [('token',self.keep_token),('signing',self.keep_signing)]:
            self.fields[key].configure(state='normal',show='' if self.show_keys.get() else '•')
            if keep.get():self.fields[key].delete(0,self.wizard.tk.END);self.fields[key].configure(state='disabled')

    def callback_changed(self,*_args):
        if not self.resetting:self.keep_signing.set(False);self.fields['signing'].delete(0,self.wizard.tk.END);self.show_keys.set(False)

    def select_peer(self,*_args):
        if self.resetting:return
        self.resetting=True
        try:
            self.clear_secret();peer=self.peer_variable.get();row=next((row for row in self.metadata.get('peers',[]) if row['name']==peer),{})
            self.keep_token.set(bool(row));self.keep_signing.set(row.get('saved_callback_secret',False))
            for key,value in [('origins',', '.join(row.get('download_origins',[]))),('callback',row.get('callback_url',''))]:
                self.fields[key].delete(0,self.wizard.tk.END);self.fields[key].insert(0,value)
        finally:self.resetting=False

    def reset(self,existing=None):
        self.metadata=existing or {};self.clear_secret()
        self.peers_label.configure(text='Gespeicherte Peers: '+(', '.join(row['name'] for row in self.metadata.get('peers',[])) or 'keine'))
        self.peer_variable.set(self.metadata.get('peers',[{'name':''}])[0]['name'] if self.metadata.get('peers') else '')
        self.select_peer()

    def save(self):
        values={key:entry.get() for key,entry in self.fields.items()};connector=self.connector()
        keep_token=self.keep_token.get();keep_signing=self.keep_signing.get();self.clear_secret()
        origins=[item.strip() for item in values['origins'].split(',') if item.strip()]
        def perform():
            owner.set_peer(connector,values['peer'],values['token'],keep_token=keep_token,
                download_origins=origins,callback_url=values['callback'],callback_secret=values['signing'],keep_callback_secret=keep_signing)
            return owner.public(owner.saved(connector)[2])
        self.wizard._run_async(perform,success='A2A-Peer gespeichert. Frühere Konnektor-Freigaben sind entzogen; Kontexte erneut ausdrücklich freigeben.',result_handler=self.saved)

    def saved(self,value):
        if not self.frame.winfo_exists():return
        self.reset(value)
        if self.on_saved is not None:self.on_saved(value)

    def remove(self):
        from tkinter import messagebox
        connector=self.connector();peer=self.peer_variable.get();self.clear_secret()
        if not messagebox.askyesno('A2A-Peer entziehen','Diesen Peer entfernen und die Konnektor-Freigaben entziehen? Historische Daten bleiben erhalten.'):return
        def perform():
            owner.remove_peer(connector,peer)
            return owner.public(owner.saved(connector)[2])
        self.wizard._run_async(perform,success='A2A-Peer entzogen; gespeicherte Task- und Recovery-Daten bleiben erhalten.',result_handler=self.saved)


class PairForm:
    def __init__(self,wizard,parent,platform,account,sender,chat,scope,thread,rights,rights_widgets,before):
        self.wizard=wizard;self.platform=platform;self.account=account;self.sender=sender;self.chat=chat;self.scope=scope;self.thread=thread
        self.rights=rights;self.rights_widgets=rights_widgets;self.before=before;self.active=False;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.flags={};self.boxes={}
        for key,label in [('allow_media','Bilder und Dokumente für diesen Kontext freigeben'),('allow_voice','Automatische lokale Transkription von Sprache freigeben'),
                ('allow_video','Videoeingang für diesen Kontext freigeben'),('allow_outbound_media','Markierte Ergebnisdateien aus dem Agent-Dateisystem freigeben'),
                ('allow_callback','Status an den separat gespeicherten HTTPS-Callback senden')]:
            self.flags[key]=tk.BooleanVar(value=False);self.boxes[key]=flag(wizard,self.frame,label,self.flags[key])
        wizard._label(self.frame,'Exakten gespeicherten Peer-Namen als Absender und eine gemeinsame Kontext-ID aus Buchstaben, Zahlen, Unterstrich und Bindestrich eingeben. '
            'Bereich wird aus dem gespeicherten Server und Peer abgeleitet; separate Topic-Threads gelten nicht. Kein unbekannter Peer erhält Rechte. '
            'Der native Schutz erlaubt maximal fünf angenommene Turns pro Stunde und Kontext. Neue Freigaben gelten ab jetzt und autorisieren keine historischen Nachrichten. '
            'Callbacks und Agent-Dateien sind getrennte Freigaben. Ein vollständiger Textanhang verwendet das bestehende Leserecht.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        for field in [sender,chat]:
            variable=getattr(field,'_haos_public_value',None)
            if variable is None:variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
            variable.trace_add('write',self.route_changed)
        for value in rights.values():value.trace_add('write',self.permissions)
        def changed(*_args):
            if platform.get()=='a2a':wizard.root.after_idle(self.changed)
            else:self.changed()
        platform.trace_add('write',changed)

    def clear(self,*_args):
        for value in self.flags.values():value.set(False)

    def route_changed(self,*_args):
        self.clear()
        if self.platform.get()=='a2a':self.display_scope()

    def display_scope(self):
        self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END)
        url=self.account.metadata.get('public_url')
        if url and self.sender.get() in {row['name'] for row in self.account.metadata.get('peers',[])}:
            from .gateway_a2a import scope
            try:self.scope.insert(0,scope({'tls':{'public_url':url}},self.sender.get()))
            except ValueError:pass
        self.scope.configure(state='disabled');self.thread.configure(state='normal');self.thread.delete(0,self.wizard.tk.END);self.thread.configure(state='disabled')

    def permissions(self,*_args):
        if self.platform.get()!='a2a':return
        for key,box in self.boxes.items():
            allowed=self.rights['read' if key in {'allow_callback','allow_outbound_media'} else 'create'].get()
            if not allowed:self.flags[key].set(False)
            box.configure(state='normal' if allowed else 'disabled')
        for key in ['pause','resume']:
            if self.rights[key].get():self.rights[key].set(False)
            self.rights_widgets[key].configure(state='disabled')

    def changed(self,*_args):
        self.clear();active=self.platform.get()=='a2a'
        if active:
            self.frame.pack(fill='x',before=self.before);self.display_scope();self.permissions()
        else:
            self.frame.pack_forget()
            if self.active:
                for field in [self.scope,self.thread]:field.configure(state='normal');field.delete(0,self.wizard.tk.END)
                for key in ['pause','resume']:self.rights_widgets[key].configure(state='normal')
        self.active=active

    def apply(self,selection):
        binding,connector,peer,context,identity,caps=selection;options={key:value.get() for key,value in self.flags.items()};self.clear()
        self.wizard._run_async(lambda:owner.pair(binding,connector,peer,context,identity,caps,**options),
            success='A2A-Peer und exakter Kontext mit ausgewählten Rechten gespeichert; Gateway-Neustart erforderlich.')


class RecoveryForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;tk=wizard.tk;self.cursor=''
        self.frame=tk.Frame(parent,bg=wizard.PANEL)
        wizard._label(self.frame,'A2A-Tasks und private Recovery-Belege',size=12).pack(anchor='w',pady=5)
        wizard._label(self.frame,'Die Prüfung stoppt den Gateway-Dienst und liest lokale Journale in der getrennten Gateway-Identität. '
            'Historische Tasks bleiben nach einem Entzug sichtbar; die Anzeige gibt ihnen keine neuen Rechte. '
            'Eine lokale Inbox-Quittung bestätigt noch keine Mission. Eine Callback-HTTP-Antwort bestätigt keinen Empfang durch eine Person. '
            'Originalnachrichten, private Download-Adressen und Schlüssel werden hier nicht angezeigt.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        wizard._button(self.frame,'A2A-Tasks lokal prüfen',lambda:self.load('')).pack(anchor='w',pady=3)
        self.area=tk.Frame(self.frame,bg=wizard.PANEL);self.area.pack(fill='x')

    def load(self,cursor):
        connector=self.connector()
        self.wizard._run_async(lambda:owner.inspect(connector,'sources',cursor),
            success='Private A2A-Journale gelesen. Der Gateway-Dienst bleibt gestoppt; keine Nachricht gesendet.',result_handler=self.show)

    def show(self,value):
        if not self.frame.winfo_exists():return
        for child in self.area.winfo_children():child.destroy()
        if 'error' in value:self.wizard.status.configure(text=ERRORS[value['error']]);return
        self.cursor=value['cursor'];rows=value['tasks'];w=self.wizard
        if not rows:w._label(self.area,'Keine weiteren gespeicherten A2A-Tasks.',size=10).pack(anchor='w')
        else:
            states={'TASK_STATE_SUBMITTED':'native Vorbereitung','TASK_STATE_WORKING':'native Verarbeitung',
                'TASK_STATE_INPUT_REQUIRED':'Rückfrage','TASK_STATE_COMPLETED':'nativ abgeschlossen',
                'TASK_STATE_FAILED':'nativ fehlgeschlagen','TASK_STATE_CANCELED':'nativ abgebrochen','TASK_STATE_REJECTED':'nativ abgewiesen'}
            choices={row['task_id']+' · '+row['peer']+' · '+row['context']:row for row in rows}
            selection=w._choice(self.area,'Gespeicherter A2A-Task',list(choices),next(iter(choices)),width=24 if w.compact else 48)
            details=w._label(self.area,'',size=10,color=w.MUTED);details.pack(anchor='w',pady=5)
            def describe(*_args):
                row=choices[selection.get()]
                details.configure(text='Status: '+states[row['native_state']]+'\nPeer: '+row['peer']+' · Kontext: '+row['context']
                    +'\nAktuelle Konto-Identität: '+('ja' if row['current_account'] else 'nein')
                    +' · Aktuelle exakte Freigabe: '+('ja' if row['current_grant'] else 'nein')
                    +'\nLokale Inbox-Aufnahme quittiert: '+('ja' if row['parent_admitted'] else 'nein')
                    +' · Originaldaten erhalten: '+('ja' if row['original_retained'] else 'nein')
                    +'\nUnklare Übergänge: '+str(row['uncertain_transitions'])+' · Unklare Steueranfragen: '+str(row['uncertain_controls'])+' · Unklare Ergebnisse: '+str(row['uncertain_results'])
                    +'\nEingangsmedien: '+(', '.join(key+': '+str(count) for key,count in row['resources'].items()) or 'keine')
                    +' · Versuche: '+str(row['resource_attempts'])
                    +'\nCallbacks: '+(', '.join(key+': '+str(count) for key,count in row['callbacks'].items()) or 'keine')
                    +'\nBeleg: '+row['snapshot_sha256'])
            actions={'Authentifizierung der Eingangsdatei erneut versuchen':'retry-source-auth',
                'Original und private Eingangssnapshots entfernen':'purge-source-inputs',
                'Private Ausgangsdateien entfernen':'purge-task-outputs'}
            action=w._choice(self.area,'Explizite lokale Recovery-Aktion',list(actions),next(iter(actions)),width=24 if w.compact else 48)
            note=w._field(self.area,'Eigene Prüfung und Entscheidung (max. 2000 Zeichen)')
            confirmed=w.tk.BooleanVar(value=False)
            w.tk.Checkbutton(self.area,text='Diesen Task, Freigaben und unklare Vorgänge geprüft',variable=confirmed,
                bg=w.PANEL,fg=w.TEXT,selectcolor=w.BG,wraplength=w.label_wrap).pack(anchor='w',pady=4)
            w._label(self.area,'Ein erneuter Authentifizierungsversuch gibt nur die unveränderte HTTPS-Quelle für den nächsten Gateway-Start frei. '
                'Es werden jetzt keine Nachricht und keine Mission erzeugt. Entfernen ist nur bei entzogenem Recht und terminalem Task möglich. '
                'Entfernt werden die logischen Bytes dieses privaten Journals; Metadaten und Wiederholungsschutz bleiben bestehen. '
                'Dies ist kein sicheres Löschen von Datenträgern, Mediencache, Agentendaten oder Backups.',size=10,color=w.MUTED).pack(anchor='w',pady=4)
            def clear(*_args):confirmed.set(False);note.delete(0,w.tk.END)
            def changed(*_args):clear();describe()
            def apply():
                row=choices[selection.get()];selected=actions[action.get()];review=note.get();approved=confirmed.get()
                if not approved or not 1<=len(review.strip())<=2000:
                    w.status.configure(text='Task prüfen, Entscheidung eintragen und explizit bestätigen.');return
                connector=self.connector();clear()
                def shown(result):
                    if 'error' in result:w.status.configure(text=ERRORS[result['error']]);return
                    w.status.configure(text='Lokale Recovery quittiert: '+result['receipt']+' · Entfernte Bytes: '+str(result['removed_bytes'])
                        +'. Liste vor einer weiteren Aktion neu prüfen; Gateway bleibt gestoppt.')
                w._run_async(lambda:owner.recover(connector,row,selected,review,confirmed=approved),
                    success='Lokale Recovery geprüft; keine Nachricht gesendet.',result_handler=shown)
            w._button(self.area,'Geprüfte A2A-Recovery lokal ausführen',apply).pack(anchor='w',pady=3)
            selection.trace_add('write',changed);action.trace_add('write',clear);describe()
        if value['has_more']:w._button(self.area,'Nächste A2A-Task-Seite',lambda:self.load(self.cursor)).pack(anchor='w',pady=3)
        w._button(self.area,'A2A-Task-Liste von Anfang laden',lambda:self.load('')).pack(anchor='w',pady=3)
