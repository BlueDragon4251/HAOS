"""Dedicated graphical Google account and exact-route Owner setup."""
from copy import deepcopy

from . import google_chat_account_setup as owner,initial_setup


class AccountForm:
    def __init__(self,wizard,parent,connector,on_saved):
        self.wizard=wizard;self.connector=connector;self.on_saved=on_saved;self.saved=None;self.epoch=0;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={};self.variables={}
        def field(key,label,default='',secret=False,parent=None):
            entry=wizard._field(parent or self.frame,label,default,secret=secret)
            var=tk.StringVar(value=default);entry.configure(textvariable=var);self.fields[key]=entry;self.variables[key]=var
            var.trace_add('write',self.changed);return entry
        self.confirm=tk.BooleanVar(value=False);self.keep=tk.BooleanVar(value=False);self.trust=tk.BooleanVar(value=False);self.public=tk.BooleanVar(value=False)
        field('bot','Erwarteter unveränderlicher Bot: users/<numerische ID>')
        field('account','Vollständiges privates Service-Account-JSON (verdeckt)',secret=True)
        self.flag(self.frame,'Gespeichertes Service-Konto ausdrücklich weiterverwenden',self.keep)
        self.mode=wizard._choice(self.frame,'Eingehende Verbindung',['pubsub','http'],'pubsub')
        self.pull=tk.Frame(self.frame,bg=wizard.PANEL);self.http=tk.Frame(self.frame,bg=wizard.PANEL)
        field('subscription','Exakte projects/<Projekt>/subscriptions/<Subscription>',parent=self.pull)
        wizard._label(self.pull,'Im Google-Projekt Chat API und Pub/Sub aktivieren. Ein privates Topic und eine Pull-Subscription erstellen. '
            'Dem Google-Prinzipal chat-api-push@system.gserviceaccount.com am Topic Publisher geben; dem dedizierten HAOS-Service-Konto '
            'Subscriber auf der Subscription. Chat-App auf dieses Topic konfigurieren und im gewünschten Space installieren. '
            'Alle weiteren Publisher einschließlich geerbter IAM-Rechte können Absender-IDs behaupten. '
            'HAOS prüft keine vollständige effektive IAM-Konfiguration; diese unabhängig im Google-Projekt prüfen.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        self.flag(self.pull,'Allen berechtigten Publishern dieses privaten Topics nach eigener IAM-Prüfung ausdrücklich vertrauen',self.trust)
        for key,label,default in [('url','Öffentliche vertrauenswürdige https://hostname/google-chat URL',''),
                ('port','Lokaler HTTPS-Port (Router/Reverse-Proxy führt auf diesen Port)','8445'),
                ('audience','Exakte Callback-URL oder numerische Projektnummer als Token-Audience',''),
                ('caller','Erwartete Google-Callback-Service-Konto-E-Mail',''),
                ('certificate','Private lokale PEM-Datei: vertrauenswürdige Zertifikatskette',''),
                ('key','Private lokale PEM-Datei: passender TLS-Schlüssel','')]:field(key,label,default,parent=self.http)
        self.bind=wizard._choice(self.http,'Listener-Adresse',['127.0.0.1','0.0.0.0','::'],'127.0.0.1')
        self.flag(self.http,'Netzwerk-Listener ausdrücklich freigeben; Firewall und HTTPS-Erreichbarkeit separat einrichten',self.public)
        wizard._label(self.http,'Die Chat-App auf die exakte HTTPS-Callback-URL konfigurieren. Audience und authentifizierte Google-Caller-Identität '
            'müssen zur gewählten Google-Chat-Verbindung passen. URL, Zertifikatsname, lokale Bindung und Router-/Proxy-Port sind unterschiedliche Einstellungen. '
            'Es wird keine Routerregel automatisch geöffnet.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        self.flag(self.frame,'Genau dieses Konto und diese Verbindung speichern; bei Änderung bestehende Absender neu koppeln',self.confirm)
        self.save_button=wizard._button(self.frame,'Google-Chat-Konto sicher speichern',self.configure,primary=True);self.save_button.pack(anchor='w',pady=8)
        for var in [self.keep,self.trust,self.public,self.bind]:var.trace_add('write',self.changed)
        self.mode.trace_add('write',self.mode_changed);self.mode_changed()

    def flag(self,parent,label,var):
        w=self.wizard;w.tk.Checkbutton(parent,text=label,variable=var,bg=w.PANEL,fg=w.TEXT,selectcolor=w.BG,
            wraplength=w.label_wrap,justify='left').pack(anchor='w',pady=4)

    def clear_secret(self,*_args):
        self.variables['account'].set('');self.keep.set(False);self.confirm.set(False)
        self.variables['key'].set('');self.trust.set(False);self.public.set(False)

    def changed(self,*_args):
        self.epoch+=1;self.confirm.set(False)

    def mode_changed(self,*_args):
        self.clear_secret();self.pull.pack_forget();self.http.pack_forget()
        (self.pull if self.mode.get()=='pubsub' else self.http).pack(fill='x',before=self.save_button)

    def reset(self,value=None):
        self.clear_secret();self.saved=deepcopy(value)
        if value:
            self.mode.set(value['inbound']['mode']);self.variables['bot'].set(value['bot_user'])
            if value['inbound']['mode']=='pubsub':self.variables['subscription'].set(value['inbound']['subscription'])
            else:
                for field,key in [('url','public_url'),('port','port'),('audience','audience'),('caller','service_account_email')]:
                    self.variables[field].set(str(value['inbound'][key]))
        self.confirm.set(False)

    def configure(self):
        w=self.wizard
        if w.running:return
        try:
            if self.confirm.get() is not True:raise ValueError('Aktuelles Konto und Verbindung ausdrücklich bestätigen.')
            connector=self.connector();bot=self.variables['bot'].get().strip();secret=self.variables['account'].get();keep=self.keep.get();mode=self.mode.get()
            if keep and self.saved is None:raise ValueError('Zuerst das gespeicherte Konto laden oder neues privates JSON eingeben.')
            if mode=='pubsub':
                if self.trust.get() is not True:raise ValueError('Topic-Publisher einschließlich geerbter IAM-Rechte unabhängig prüfen und ausdrücklich freigeben.')
                inbound={'mode':mode,'subscription':self.variables['subscription'].get().strip(),'trust_topic_publishers':True}
                paths=None
            else:
                port=self.variables['port'].get()
                if not port.isascii() or not port.isdecimal() or len(port)>5 or not 1024<=int(port)<=65535:raise ValueError('Google-HTTPS-Port muss von 1024 bis 65535 liegen.')
                inbound={'mode':mode,'port':int(port),'audience':self.variables['audience'].get().strip(),
                    'service_account_email':self.variables['caller'].get().strip(),'tls':{'public_url':self.variables['url'].get().strip(),
                    'bind_host':self.bind.get(),'public_listener':self.public.get()}}
                paths={kind:self.variables[field].get() for kind,field in [('certificate','certificate'),('private_key','key')]}
        except ValueError as error:w.status.configure(text=str(error));return
        self.clear_secret()
        epoch=self.epoch
        def execute():
            if paths:inbound['tls'].update({kind:initial_setup.read_line_tls_file(path,kind) for kind,path in paths.items()})
            result=owner.save_account(connector,bot,inbound,secret,keep_service_account=keep)
            return result,initial_setup.gateway_configuration()['google_chat'][connector]
        def done(value):
            if connector!=self.connector() or epoch!=self.epoch or not self.frame.winfo_exists():return
            result,account=value;self.reset(account);self.on_saved(account)
            w.status.configure(text='Konto gespeichert. Noch keine Live-Abnahme; Absender exakt koppeln und Gateway danach bewusst starten.')
        w._run_async(execute,result_handler=done)


class PairForm:
    def __init__(self,wizard,parent,connector,account):
        self.wizard=wizard;self.connector=connector;self.account=account;tk=wizard.tk;self.frame=tk.Frame(parent,bg=wizard.PANEL)
        self.fields={};self.vars={};self.confirm=tk.BooleanVar(value=False)
        wizard._label(self.frame,'Explizite Google-Chat-Freigabe',size=12).pack(anchor='w',pady=6)
        for key,label,default in [('id','Lokale Freigabe-ID','google-owner'),('sender','Exakter Absender: users/<numerische ID>',''),
                ('chat','Exakter Space: spaces/<ID>',''),('thread','Exakter Thread: spaces/<ID>/threads/<ID>; leer nur für unthreaded',''),
                ('identity','Lokale HAOS-Identität','personal')]:
            var=tk.StringVar(value=default);entry=wizard._field(self.frame,label,default);entry.configure(textvariable=var)
            self.fields[key]=entry;self.vars[key]=var;var.trace_add('write',self.clear)
        self.flags={}
        for key,label,default in [('create','Missionen erstellen',True),('read','Eigene Missionen lesen',True),('answer','Rückfragen beantworten',False),
                ('cancel','Eigene Missionen abbrechen',False),('pause','Eigene Missionen pausieren',False),('resume','Eigene Missionen fortsetzen',False),
                ('require_mention','In Gruppen ausdrückliche Bot-Erwähnung verlangen',True),('all_threads','Alle Threads genau dieses Spaces freigeben (kein Einzelthread)',False),
                ('allow_media','Eingehende Bilder und Dokumente freigeben',False),('allow_voice','Eingehende Sprache mit lokalem Sprachdienst transkribieren',False),
                ('allow_video','Eingehendes Video mit Vorschau freigeben; keine Videoanalyse-Zusage',False),
                ('allow_outbound_media','Ergebnisdateien für genau diesen Nutzer exportieren; zusätzliche Nutzer-OAuth-Freigabe erforderlich',False)]:
            var=tk.BooleanVar(value=default);self.flags[key]=var
            tk.Checkbutton(self.frame,text=label,variable=var,bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,
                wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=3)
            var.trace_add('write',lambda *_:self.confirm.set(False))
        tk.Checkbutton(self.frame,text='Genau diesen bekannten Absender und Bereich samt Thread-/Medienrechten freigeben; Space-Mitglieder können Antworten sehen',
            variable=self.confirm,bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=6)
        self.save_button=wizard._button(self.frame,'Exakten Google-Absender freigeben',self.configure,primary=True);self.save_button.pack(anchor='w',pady=7)

    def clear(self,*_args):
        self.confirm.set(False)
        if hasattr(self,'flags'):
            for name in ['allow_media','allow_voice','allow_video','allow_outbound_media','all_threads']:self.flags[name].set(False)

    def configure(self):
        w=self.wizard
        if w.running:return
        if self.confirm.get() is not True:w.status.configure(text='Aktuelle exakte Freigabe ausdrücklich bestätigen.');return
        if not self.account():w.status.configure(text='Zuerst Google-Konto speichern oder laden.');return
        values={key:var.get().strip() for key,var in self.vars.items()};flags={key:var.get() for key,var in self.flags.items()}
        connector=self.connector();account=deepcopy(self.account());self.clear()
        rights=tuple(key for key in ['create','read','answer','cancel','pause','resume'] if flags.pop(key))
        w._run_async(lambda:initial_setup.pair_gateway_sender(values['id'],connector,values['sender'],values['chat'],values['identity'],rights,
            thread=values['thread'],scope=account['scope'],**flags),success='Exakte Google-Freigabe gespeichert. Gateway bewusst neu starten; keine Testnachricht versendet.')
