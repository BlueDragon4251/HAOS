"""Owner Feishu forms; secrets are captured only for the private setup handoff."""
from . import initial_setup
from . import feishu_owner_setup as owner

LABELS={'created':'Feishu-Profil vorbereitet','connecting':'Feishu-App wird geprüft',
    'listening-tls':'Feishu-HTTPS-Empfang aktiv; externe Erreichbarkeit ungeprüft',
    'connected-ws':'Feishu-WebSocket verbunden; keine externe Zustellung bestätigt',
    'storage-unavailable':'Feishu-Speicher nicht verfügbar; erhaltene Quellen prüfen',
    'tls-refused':'Feishu-TLS abgelehnt; Zertifikat und Endpunkt prüfen',
    'identity-refused':'Feishu-Bot-ID stimmt nicht; App und Konto prüfen',
    'authentication-refused':'Feishu-Anmeldung abgelehnt; App-Rechte und Secret prüfen',
    'source-unavailable':'Feishu-Quelle nicht verfügbar; Originale bleiben erhalten',
    'rate-limited':'Feishu begrenzt Anfragen; gespeicherte Wartefrist gilt',
    'transport-unavailable':'Feishu-Verbindung nicht verfügbar; Netzwerk und App prüfen',
    'revoked':'Feishu-Freigabe entzogen','disconnected':'Feishu getrennt; Daten erhalten',
    'closed':'Feishu-Profil geschlossen; Daten erhalten'}


class AccountForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={}
        self.brand=wizard._choice(self.frame,'Feishu-Region',['feishu','lark'],'feishu')
        self.mode=wizard._choice(self.frame,'Feishu-Verbindung',['websocket','webhook'],'websocket')
        for key,label,secret in [('app_id','Feishu-App-ID',False),('app_secret','Feishu-App-Secret',True),
                ('tenant_key','Feishu-Tenant-Key',False),('bot_open_id','Feishu-Bot-Open-ID',False)]:
            self.fields[key]=wizard._field(self.frame,label,secret=secret)
        self.webhook=tk.Frame(self.frame,bg=wizard.PANEL)
        for key,label,secret in [('verification_token','Feishu-Verification-Token',True),('encrypt_key','Feishu-Encrypt-Key',True),
                ('port','Feishu-HTTPS-Port',False),('public_url','Feishu-Webhook-URL',False),
                ('certificate_path','Feishu-Zertifikatdatei',False),('private_key_path','Feishu-Schlüsseldatei',False)]:
            self.fields[key]=wizard._field(self.webhook,label,secret=secret)
        self.bind=wizard._choice(self.webhook,'Feishu-Listener',['127.0.0.1','0.0.0.0','::'],'127.0.0.1')
        self.public=tk.BooleanVar(value=False)
        tk.Checkbutton(self.webhook,text='Öffentlichen Feishu-HTTPS-Listener ausdrücklich freigeben',variable=self.public,
            bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w')
        wizard._label(self.frame,'In der Feishu/Lark-App im.message.receive_v1 und die passenden Bot-, Nachrichten- und Medienrechte konfigurieren. '
            'WebSocket benötigt keinen eingehenden Port. Webhook benötigt Verification-Token, Encrypt-Key, HTTPS /feishu/webhook und passende Weiterleitung. '
            'Tenant-Key und Bot-Open-ID exakt angeben; die Kontoprüfung bestätigt nur die Bot-ID. Kontoänderungen entziehen bestehende Absenderfreigaben.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        wizard._button(self.frame,'Feishu-Konto ohne Nachricht prüfen',self.inspect).pack(anchor='w',pady=4)
        wizard._button(self.frame,'Feishu-Anmeldung erneut erlauben',self.retry).pack(anchor='w',pady=4)
        for key,entry in self.fields.items():
            if key in {'app_secret','verification_token','encrypt_key'}:continue
            variable=tk.StringVar(value=entry.get());entry.configure(textvariable=variable);entry._haos_public_value=variable
            variable.trace_add('write',self.clear_secret)
        self.brand.trace_add('write',self.clear_secret);self.mode.trace_add('write',self.mode_changed);self.bind.trace_add('write',self.clear_secret)
        self.reset()

    def clear_secret(self,*_args):
        for key in ['app_secret','verification_token','encrypt_key']:self.fields[key].delete(0,self.wizard.tk.END)
        self.public.set(False)

    def mode_changed(self,*_args):
        self.clear_secret()
        if self.mode.get()=='webhook':self.webhook.pack(fill='x')
        else:self.webhook.pack_forget()

    def reset(self,existing=None):
        self.clear_secret();value=existing or {};tk=self.wizard.tk
        for key,entry in self.fields.items():
            entry.delete(0,tk.END)
            if key not in {'app_secret','verification_token','encrypt_key'}:entry.insert(0,str(value.get(key,'8648' if key=='port' else '')))
        self.brand.set(value.get('domain','feishu'));self.mode.set(value.get('connection_mode','websocket'));self.bind.set(value.get('bind_host','127.0.0.1'))
        self.mode_changed()

    def configure(self):
        w=self.wizard;values={key:entry.get() for key,entry in self.fields.items()}
        brand,mode,bind,public,connector=self.brand.get(),self.mode.get(),self.bind.get(),self.public.get(),self.connector()
        self.clear_secret()
        def save():
            value={key:values[key] for key in ['app_id','app_secret','tenant_key','bot_open_id']}
            value.update(domain=brand,connection_mode=mode)
            if mode=='webhook':
                port=values['port']
                if not port.isascii() or not port.isdecimal() or len(port)>5 or not 1024<=int(port)<=65535:raise ValueError('Feishu-HTTPS-Port: 1024 bis 65535 erforderlich')
                value.update(verification_token=values['verification_token'],encrypt_key=values['encrypt_key'],port=int(port),
                    tls={'public_url':values['public_url'],'bind_host':bind,'public_listener':public,
                        'certificate':initial_setup.read_line_tls_file(values['certificate_path'],'certificate'),
                        'private_key':initial_setup.read_line_tls_file(values['private_key_path'],'private_key')})
            return owner.configure(connector,value)
        w._run_async(save,success='Feishu-Konto gespeichert. Ohne Versand prüfen und exakte Absender neu freigeben; Dienst bleibt gestoppt.')

    def inspect(self):
        connector=self.connector();self.clear_secret();w=self.wizard
        def show(value):
            w.status.configure(text=('Feishu-Kontoprüfung abgelehnt: '+value['error'] if 'error' in value else
                'Feishu-Bot-ID bestätigt. Tenant-Zuordnung und externe Zustellung nicht bestätigt; keine Nachricht gesendet.'))
        w._run_async(lambda:owner.inspect(connector),result_handler=show)

    def retry(self):
        connector=self.connector();self.clear_secret()
        self.wizard._run_async(lambda:owner.retry_auth(connector),success='Neue Feishu-Anmeldung erlaubt. Wartefristen und unklare Zustellungen bleiben geschützt; Dienst bleibt gestoppt.')


class PairForm:
    def __init__(self,wizard,parent,platform,account,sender,chat,scope,thread,rights,before):
        self.wizard=wizard;self.platform=platform;self.account=account;self.scope=scope;self.rights=rights;self.before=before
        tk=wizard.tk;self.frame=tk.Frame(parent,bg=wizard.PANEL);self.active=False
        self.flags={key:tk.BooleanVar(value=False) for key in ['allow_media','allow_voice','allow_video','allow_outbound_media']}
        self.mention=tk.BooleanVar(value=True);self.boxes={}
        for key,label in [('allow_media','Feishu-Bilder und Dokumente ausdrücklich freigeben'),('allow_voice','Feishu-Sprachnachrichten ausdrücklich freigeben'),
                ('allow_video','Feishu-Videoeingang ausdrücklich freigeben'),('allow_outbound_media','Markierte Ergebnisdateien an diesen Feishu-Chat senden')]:
            box=tk.Checkbutton(self.frame,text=label,variable=self.flags[key],bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,
                wraplength=wizard.label_wrap,justify='left');box.pack(anchor='w',pady=4);self.boxes[key]=box
        tk.Checkbutton(self.frame,text='In Gruppen exakte Bot-Erwähnung verlangen',variable=self.mention,bg=wizard.PANEL,
            fg=wizard.TEXT,selectcolor=wizard.BG).pack(anchor='w')
        wizard._label(self.frame,'Absender: ou_… · Chat: oc_… · optionaler nativer Topic-Thread: omt_… . '
            'Ein leerer Thread erlaubt ausschließlich Nachrichten ohne Topic-Thread. Keine Anzeigenamen, Platzhalter oder zitierten om_-IDs. '
            'Voice und die Konvertierung nicht-Opus-Audioausgaben benötigen den lokalen Sprachdienst; Ergebnisdateien benötigen Leserecht. Unbekannte Absender bleiben gesperrt.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
        for field in (sender,chat,thread):
            variable=getattr(field,'_haos_public_value',None)
            if variable is None:variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
            variable.trace_add('write',self.clear)
        for key in ['app_id','tenant_key','bot_open_id']:account.fields[key]._haos_public_value.trace_add('write',self.changed)
        account.brand.trace_add('write',self.changed)
        for value in rights.values():value.trace_add('write',self.permissions)
        def platform_changed(*_args):
            if platform.get()=='feishu':wizard.root.after_idle(self.changed)
            else:self.changed()
        platform.trace_add('write',platform_changed)

    def clear(self,*_args):
        for value in self.flags.values():value.set(False)
        self.mention.set(True)

    def permissions(self,*_args):
        for key,box in self.boxes.items():
            allowed=self.rights['read' if key=='allow_outbound_media' else 'create'].get()
            if not allowed:self.flags[key].set(False)
            box.configure(state='normal' if allowed else 'disabled')

    def changed(self,*_args):
        self.clear();active=self.platform.get()=='feishu'
        if active:
            self.frame.pack(fill='x',before=self.before);self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END)
            from .gateway_feishu import scope
            value={key:self.account.fields[key].get() for key in ['app_id','tenant_key','bot_open_id']};value['domain']=self.account.brand.get()
            self.scope.insert(0,scope(value));self.scope.configure(state='disabled');self.permissions()
        else:
            self.frame.pack_forget()
            if self.active:self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END)
        self.active=active

    def options(self):return {**{key:value.get() for key,value in self.flags.items()},'require_mention':self.mention.get()}


def recovery(wizard,parent,value,reload):
    tk=wizard.tk
    rows=[row for row in value.get('native_outgoing',[]) if row.get('platform')=='feishu']
    for row in rows:
        wizard._label(parent,'Feishu-Ausgang · '+row['delivery_id']+' · '+row.get('operation','Text')
            +' · Teil '+str(row.get('part','–'))+' · Versuch '+str(row['attempt'])+' · '+row['state']
            +' · API-Annahme ist kein Lesebeleg',size=10,color=wizard.MUTED).pack(anchor='w',pady=3)
    uncertain=[row for row in rows if row['state'] in {'writing','uncertain','rejected'} and row['attempt']<5]
    if not uncertain:return
    choices={row['delivery_id']+' · '+row.get('operation','Text')+' / '+str(row.get('part','–'))+' / '+str(row['attempt']):row for row in uncertain}
    selected=wizard._choice(parent,'Geprüfter Feishu-Schreibversuch',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
    note=wizard._field(parent,'Feishu-Prüfnotiz ohne Geheimnisse');confirmed=tk.BooleanVar(value=False)
    selected.trace_add('write',lambda *_:confirmed.set(False))
    tk.Checkbutton(parent,text='Nichtannahme dieses exakten Uploads oder dieser Antwort unabhängig geprüft',variable=confirmed,
        bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
    def approve():
        from tkinter import messagebox
        row=dict(choices[selected.get()]);evidence=note.get();checked=confirmed.get()
        if not checked:wizard.status.configure(text='Feishu-Nichtannahme zuerst unabhängig prüfen und bestätigen.');return
        if not messagebox.askyesno('Feishu-Wiederholung','Nur die geprüfte private Teilsperre freigeben? Controller-Zustellung bleibt separat zu prüfen. Jetzt wird nichts gesendet.'):return
        confirmed.set(False)
        action='approve-feishu-part-retry' if 'part' in row else 'approve-feishu-retry'
        wizard._run_async(lambda:owner.recovery(row,action,evidence,True,confirmed_not_accepted=checked),
            success='Private Feishu-Entscheidung gespeichert. Controller separat prüfen; Dienste bleiben gestoppt.',result_handler=lambda _:reload())
    wizard._button(parent,'Geprüfte Feishu-Teilsperre freigeben',approve).pack(anchor='w',pady=4)


def sources(wizard):
    tk=wizard.tk;wizard._head('Feishu-Quellen verwalten','Erhaltene Originale und Webhook-Daten · getrennte Entscheidungen')
    wizard._label(wizard.content,'Diese Prüfung stoppt den Gateway-Dienst. Nur nach Entzug oder Änderung der ursprünglichen Freigabe '
        'können ausgewählte Quelldaten ausdrücklich entfernt werden. Original und Webhook-Daten benötigen getrennte Entscheidungen. '
        'Replay-Sperren und Audit bleiben erhalten. Andere Controller-/Agent-Kopien und Backups bleiben bestehen; keine sichere Datenträgerlöschung.',
        size=10,color=wizard.MUTED).pack(anchor='w',pady=6)
    area=tk.Frame(wizard.content,bg=wizard.PANEL);area.pack(fill='x')
    def show(value):
        for child in area.winfo_children():child.destroy()
        rows=value['sources']
        if not rows:wizard._label(area,'Keine gespeicherten Quellen.',size=10).pack(anchor='w');return
        choices={row['id']+' · '+str(row['stored_bytes'])+' B':row for row in rows}
        selected=wizard._choice(area,'Feishu-Original oder Webhook-Beleg',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        note=wizard._field(area,'Feishu-Löschprüfnotiz ohne Geheimnisse');confirmed=tk.BooleanVar(value=False)
        selected.trace_add('write',lambda *_:confirmed.set(False))
        tk.Checkbutton(area,text='Ausgewählte Quelldaten und entzogene Freigabe unabhängig geprüft',variable=confirmed,
            bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
        def remove():
            from tkinter import messagebox
            row=dict(choices[selected.get()]);row.update(profile=value['profile'],kind=value['kind']);evidence=note.get()
            if not confirmed.get() or not row['purge_allowed'] or row['purged']:
                wizard.status.configure(text='Aktive oder bereits entfernte Quelle bleibt geschützt. Freigabe entziehen und neu prüfen.');return
            if not messagebox.askyesno('Feishu-Quelldaten entfernen','Nur diese geprüften Quelldaten logisch entfernen und Replay-Sperre/Audit behalten?'):return
            confirmed.set(False)
            def perform():
                owner.recovery(row,'purge-feishu-source',evidence,True)
                return owner.sources(value['profile'],value['kind'])
            wizard._run_async(perform,success='Ausgewählte Feishu-Quelldaten entfernt; Belege erhalten.',result_handler=show)
        wizard._button(area,'Geprüfte Feishu-Quelldaten entfernen',remove).pack(anchor='w',pady=5)
    def profiles(value):
        choices={row['profile']+' · '+kind:(row['profile'],kind) for row in value['profiles'] for kind in row['kinds']}
        if not choices:wizard._label(area,'Keine erhaltenen Feishu-Profile.',size=10).pack(anchor='w');return
        selected=wizard._choice(wizard.content,'Feishu-Quellspeicher',list(choices),next(iter(choices)),width=24 if wizard.compact else 48)
        def load():
            profile,kind=choices[selected.get()]
            wizard._run_async(lambda:owner.sources(profile,kind),success='Feishu-Quellmetadaten geladen.',result_handler=show)
        wizard._button(wizard.content,'Feishu-Quellmetadaten laden',load).pack(anchor='w',pady=5)
    wizard._button(wizard.content,'Feishu-Profile prüfen',lambda:wizard._run_async(owner.sources,
        success='Feishu-Profile geladen; Gateway bleibt gestoppt.',result_handler=profiles)).pack(anchor='w',pady=5)
    wizard._button(wizard.content,'Zurück zu Gateways',lambda:wizard.show('gateways')).pack(anchor='w',pady=6)
