"""Prepared local Owner recovery controls backed by private UID actions."""
import json
from copy import deepcopy

from . import google_chat_owner_setup as owner
from .google_chat_owner_process import response

ERRORS={'authority-refused':'Konto, Freigabe, Profilsperre oder Prüfbeleg erlaubt diese Aktion nicht. Zustand neu prüfen.',
    'storage-unavailable':'Privates Google-Chat-Journal prüfen. Vorhandene Daten bleiben erhalten.',
    'runtime-unavailable':'Die installierte private Google-Chat-Runtime fehlt oder ist unvollständig.',
    'authentication-refused':'Google hat die Anmeldung oder Zugangsdaten abgelehnt. Privaten Status prüfen.',
    'identity-refused':'Der signierte Google-Nutzer passt nicht zur gespeicherten numerischen Nutzer-ID. Abgelehnte Zugangsdaten prüfen.',
    'rate-limited':'Google-Wartezeit ist noch aktiv. Später nach Statusprüfung fortsetzen.',
    'transport-unavailable':'Google-Antwort nicht eindeutig erhalten. Zustand prüfen; den begonnenen Austausch nicht wiederholen.'}


class RecoveryForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;self.rows=[];self.kind=None;self.epoch=0;self.loaded_connector=None;self.confirm_connector=None;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL)
        wizard._label(self.frame,'Google Chat: private Belege und Wiederherstellung',size=12).pack(anchor='w',pady=5)
        self.profile=wizard._field(self.frame,'Speicherprofil (leer: aktuelles Konto; alte Profile ausdrücklich auswählen)')
        self.profile_var=tk.StringVar();self.profile.configure(textvariable=self.profile_var);self.profile_var.trace_add('write',self.clear)
        self.buttons={}
        for key,label,action in [('profiles','Erhaltene Google-Chat-Profile anzeigen',lambda:self.load('source-profiles')),
                ('sources','Original-Belege ohne Nachrichteninhalt laden',lambda:self.load('sources')),
                ('outgoing','Antwortteile und Annahmebelege laden',lambda:self.load('outgoing'))]:
            self.buttons[key]=self.button(label,action)
        self.list=tk.Listbox(self.frame,height=7,exportselection=False,bg=wizard.BG,fg=wizard.TEXT);self.list.pack(fill='x',pady=4)
        self.list.bind('<<ListboxSelect>>',self.selected)
        self.details=tk.Text(self.frame,height=6,wrap='word',bg=wizard.BG,fg=wizard.TEXT,state='disabled');self.details.pack(fill='x',pady=4)
        self.note=wizard._field(self.frame,'Nicht geheime Prüfbegründung (keine Zugangsdaten)')
        self.confirm=tk.BooleanVar(value=False);self.not_delivered=tk.BooleanVar(value=False)
        self.confirm.trace_add('write',lambda *_:setattr(self,'confirm_connector',self.connector() if self.confirm.get() else None))
        self.flag('Genau diesen aktuellen Beleg geprüft und diese Aktion ausdrücklich freigegeben',self.confirm)
        self.flag('Genau dieser Antwortteil ist nach unabhängiger Prüfung sicher nicht zugestellt',self.not_delivered)
        self.buttons['retry']=self.button('Genau diesen unklaren Antwortteil einmal freigeben',self.reply)
        self.buttons['purge']=self.button('Original-Nutzdaten nach Freigabeentzug entsorgen',self.purge)
        self.buttons['auth']=self.button('Nach Kontoprüfung lokale Auth-Sperre freigeben; kein Versand',self.auth)
        wizard._label(self.frame,'Diese Aktionen senden nichts. Eine Antwortfreigabe ersetzt nicht die getrennte Controller-Recovery. '
            'Bestätigte Teile bleiben gesperrt. Vor jedem freigegebenen Versuch wird eine verspätete Annahme geprüft; '
            'ID und Inhalt bleiben gleich. Auth-Freigaben verkürzen keine Rate-Limit-Wartezeit. '
            'Entsorgung entfernt private Original-Nutzdaten nach Freigabeentzug, behält aber Prüfbelege. '
            'Andere Missionskopien, Backups und WAL werden damit nicht sicher gelöscht.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)

    def button(self,label,action):
        widget=self.wizard._button(self.frame,label,action);widget.configure(wraplength=max(180,self.wizard.label_wrap-50),justify='left')
        widget.pack(anchor='w',pady=3);return widget

    def flag(self,label,variable):
        self.wizard.tk.Checkbutton(self.frame,text=label,variable=variable,bg=self.wizard.PANEL,fg=self.wizard.TEXT,
            selectcolor=self.wizard.BG,wraplength=self.wizard.label_wrap,justify='left',anchor='w').pack(anchor='w',pady=3)

    def clear(self,*_args):
        self.epoch+=1;self.rows=[];self.kind=None;self.loaded_connector=None;self.list.delete(0,self.wizard.tk.END);self.selected()

    def selected(self,*_args):
        self.confirm.set(False);self.not_delivered.set(False);self.note.delete(0,self.wizard.tk.END)
        chosen=self.list.curselection();row=self.rows[chosen[0]] if chosen and chosen[0]<len(self.rows) else None
        if row is not None and self.kind=='source-profiles':
            self.profile_var.set(row['profile']);self.wizard.status.configure(text='Profil ausgewählt. Jetzt dessen Original-Belege laden.');return
        self.details.configure(state='normal');self.details.delete('1.0',self.wizard.tk.END)
        if row is not None:self.details.insert('1.0',json.dumps(row,ensure_ascii=False,indent=2))
        self.details.configure(state='disabled')

    def fresh(self,epoch,connector):
        return epoch==self.epoch and connector==self.connector() and bool(self.frame.winfo_exists())

    def load(self,kind):
        profile=self.profile_var.get().strip() or None;connector=self.connector();self.clear();epoch=self.epoch
        def show(value):
            if not self.fresh(epoch,connector):return
            try:value=response(value,kind,connector)
            except (ValueError,TypeError,KeyError):
                self.wizard.status.configure(text='Ungültiger oder privater Recovery-Prüfbeleg verworfen.');return
            if 'error' in value:self.wizard.status.configure(text=ERRORS[value['error']]);return
            self.kind=kind;self.loaded_connector=connector
            if kind=='source-profiles':self.rows=[{'profile':p} for p in value['profiles']]
            elif kind=='sources':self.rows=deepcopy(value['sources'])
            else:self.rows=[{'group':deepcopy(group),'part':dict(part)} for group in value['outgoing'] for part in group['parts']]
            for row in self.rows:
                if kind=='source-profiles':label=row['profile']
                elif kind=='sources':label=row['message_id']+' · '+row['state']
                else:label=row['group']['source_id']+' · Teil '+str(row['part']['part']+1)+' · '+row['part']['state']
                self.list.insert(self.wizard.tk.END,label)
            self.wizard.status.configure(text='Private Belege geladen. Keine Nachricht versendet; Zeile ausdrücklich auswählen.')
        self.wizard._run_async(lambda:owner.inspect(connector,kind,profile=profile) if kind=='sources' else owner.inspect(connector,kind),result_handler=show)

    def choice(self,kind):
        selection=self.list.curselection()
        if self.loaded_connector!=self.connector() or self.kind!=kind or not selection or selection[0]>=len(self.rows):raise ValueError('Zuerst passenden aktuellen Beleg laden und auswählen.')
        return deepcopy(self.rows[selection[0]])

    def perform(self,action,kind=None):
        try:
            row=self.choice(kind) if kind else None;confirmed=self.confirm.get();not_delivered=self.not_delivered.get();note=self.note.get()
            if not confirmed or self.confirm_connector!=self.connector() or not 1<=len(note.strip())<=2000:raise ValueError('Aktuellen Beleg ausdrücklich bestätigen und eine nicht geheime Prüfbegründung eingeben.')
            if action=='approve-retry' and (not not_delivered or row['part']['state']!='writing'):
                raise ValueError('Nur einen begonnenen unbestätigten Antwortteil nach unabhängiger Nichtzustellungsprüfung freigeben.')
            if action=='purge-source' and row.get('purge_allowed') is not True:raise ValueError('Vor Entsorgung die ursprüngliche Freigabe entziehen und Beleg neu laden.')
        except ValueError as error:self.wizard.status.configure(text=str(error));return
        connector=self.connector();epoch=self.epoch;self.confirm.set(False);self.not_delivered.set(False);self.note.delete(0,self.wizard.tk.END)
        def execute():
            if action=='approve-retry':return owner.approve_reply(connector,row['group'],row['part']['id'],note,confirmed=confirmed,confirmed_not_delivered=not_delivered)
            if action=='purge-source':return owner.purge_source(connector,row,note,confirmed=confirmed)
            return owner.retry_auth(connector,note,confirmed=confirmed)
        def finished(value):
            if not self.fresh(epoch,connector):return
            try:value=response(value,action,connector)
            except (ValueError,TypeError,KeyError):
                self.clear();self.wizard.status.configure(text='Ungültiger Recovery-Entscheidungsbeleg verworfen; Zustand neu prüfen.');return
            self.clear();self.wizard.status.configure(text=ERRORS[value['error']] if 'error' in value else
                'Owner-Entscheidung gespeichert; kein Versand. Für Antworten getrennte Controller-Recovery prüfen.')
        self.wizard._run_async(execute,result_handler=finished)

    def reply(self):self.perform('approve-retry','outgoing')
    def purge(self):self.perform('purge-source','sources')
    def auth(self):self.perform('retry-auth')


class OAuthForm:
    """Optional stable-user delegation; every action uses the Root/private worker."""
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;self.epoch=0;self.rows=[];self.kind=None
        self.loaded_connector=None;self.session=None;self.session_connector=None;self.confirm_context=None
        tk=wizard.tk;self.frame=tk.Frame(parent,bg=wizard.PANEL);self.buttons={}
        wizard._label(self.frame,'Google Chat: optionale Nutzerfreigabe für Dateien',size=12).pack(anchor='w',pady=5)
        wizard._label(self.frame,'Zuerst Konto und genaue Absender-/Thread-Freigabe speichern. Nur für Dateiversand: '
            'Google-Zustimmung erlaubt Nachrichtenerstellung und Lesen von Nachrichten für die Annahmeprüfung sowie OpenID zur Prüfung '
            'der numerischen Nutzer-ID. HAOS beschränkt die Nutzung zusätzlich auf die gespeicherte Freigabe. '
            'Es wird keine Testnachricht versendet.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        self.binding=wizard._field(self.frame,'Gespeicherte Freigabe-ID für den genauen Google-Nutzer')
        self.binding_var=tk.StringVar();self.binding.configure(textvariable=self.binding_var);self.binding_var.trace_add('write',self.invalidate)
        self.configuration=wizard._field(self.frame,'Privates Google-Desktop-Client-JSON aus demselben Projekt',secret=True)
        self.configuration_var=tk.StringVar();self.configuration.configure(textvariable=self.configuration_var)
        self.configuration_var.trace_add('write',self.invalidate)
        self.note=wizard._field(self.frame,'Nicht geheime Prüfbegründung (keine Zugangsdaten)')
        self.confirm=tk.BooleanVar(value=False)
        self.confirm.trace_add('write',lambda *_:setattr(self,'confirm_context',self.context() if self.confirm.get() else None))
        tk.Checkbutton(self.frame,text='Genau dieses Konto und diese Aktion ausdrücklich freigeben',variable=self.confirm,
            bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
        self.button('begin','Google-Zustimmung für gespeicherte Freigabe vorbereiten',self.begin)
        self.authorization=tk.Text(self.frame,height=5,wrap='char',bg=wizard.BG,fg=wizard.TEXT,state='disabled');self.authorization.pack(fill='x',pady=4)
        wizard._label(self.frame,'Die angezeigte Google-Adresse im eigenen Browser öffnen. Nach Zustimmung ist localhost:1 absichtlich '
            'nicht erreichbar. Die vollständige Rücksprungadresse aus der Browser-Adresszeile unten einfügen; kein einzelner Code. '
            'PKCE-Verifier und Tokens bleiben privat. Die Sitzung läuft nach zehn Minuten ab.',size=10,color=wizard.MUTED).pack(anchor='w',pady=4)
        self.callback=wizard._field(self.frame,'Vollständige Rücksprungadresse (verdeckt; wird nach Übergabe geleert)',secret=True)
        self.button('finish','Genau diese Google-Anmeldung abschließen',self.finish)
        for kind,label in [('sessions','Anmeldesitzungen prüfen'),('tokens','Nutzerfreigaben und Status prüfen'),('quarantines','Abgelehnte Zugangsdaten prüfen')]:
            self.button(kind,label,lambda kind=kind:self.load(kind))
        self.list=tk.Listbox(self.frame,height=5,exportselection=False,bg=wizard.BG,fg=wizard.TEXT);self.list.pack(fill='x',pady=4)
        self.list.bind('<<ListboxSelect>>',self.selected)
        self.details=tk.Text(self.frame,height=6,wrap='word',bg=wizard.BG,fg=wizard.TEXT,state='disabled');self.details.pack(fill='x',pady=4)
        self.button('revoke','Ausgewählte Nutzerfreigabe sofort lokal sperren und bei Google widerrufen',lambda:self.withdraw('tokens'))
        self.button('dispose','Ausgewählte abgelehnte Zugangsdaten bei Google widerrufen und entsorgen',lambda:self.withdraw('quarantines'))
        wizard._label(self.frame,'Lokale Sperre gilt vor dem Widerrufsversuch. Nur eine bestätigte Google-Antwort belegt den entfernten '
            'Widerruf. Ein unklarer Versuch wird nicht automatisch wiederholt. Belege bleiben erhalten; sichere Löschung aus WAL '
            'und Backups wird nicht behauptet. Diese Prüfungen stoppen den Gateway-Dienst; anschließend bewusst wieder starten.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=5)

    def button(self,key,label,action):
        widget=self.wizard._button(self.frame,label,action);widget.configure(wraplength=max(180,self.wizard.label_wrap-50),justify='left')
        widget.pack(anchor='w',pady=3);self.buttons[key]=widget

    def context(self):return self.connector(),self.binding_var.get().strip()

    def reset_choice(self):
        self.confirm.set(False);self.note.delete(0,self.wizard.tk.END)

    def invalidate(self,*_args):
        self.epoch+=1;self.session=None;self.session_connector=None;self.rows=[];self.kind=None;self.loaded_connector=None
        if hasattr(self,'callback'):self.callback.delete(0,self.wizard.tk.END)
        if hasattr(self,'authorization'):self.render(self.authorization,'')
        if hasattr(self,'list'):self.list.delete(0,self.wizard.tk.END);self.render(self.details,'')
        if hasattr(self,'confirm'):self.reset_choice()

    def render(self,widget,text):
        widget.configure(state='normal');widget.delete('1.0',self.wizard.tk.END);widget.insert('1.0',text);widget.configure(state='disabled')

    def selected(self,*_args):
        self.reset_choice();indices=self.list.curselection();row=self.rows[indices[0]] if indices and indices[0]<len(self.rows) else None
        self.render(self.details,json.dumps(row,ensure_ascii=False,indent=2) if row else '')

    def consent(self):
        if self.confirm.get() is not True or self.confirm_context!=self.context() or not 1<=len(self.note.get().strip())<=2000:
            raise ValueError('Aktuelle Auswahl ausdrücklich bestätigen und nicht geheime Prüfbegründung angeben.')
        return self.note.get().strip()

    def submit(self,action,execute,*,request=None,accepted=None):
        if self.wizard.running:return
        epoch=self.epoch;context=self.context();self.reset_choice()
        def done(value):
            if epoch!=self.epoch or context!=self.context() or not self.frame.winfo_exists():return
            try:value=response(value,action,context[0],request=request)
            except (ValueError,TypeError,KeyError):
                self.invalidate();self.wizard.status.configure(text='Ungültigen oder privaten OAuth-Prüfbeleg verworfen; Zustand neu prüfen.');return
            if 'error' in value:
                self.wizard.status.configure(text=ERRORS[value['error']]+(' Wartezeit: '+str(value['retry_after'])+' s.' if value.get('retry_after') else ''));return
            if accepted:accepted(value)
        self.wizard._run_async(execute,result_handler=done)

    def begin(self):
        if self.wizard.running:return
        try:
            note=self.consent();binding=self.binding_var.get().strip();raw=self.configuration.get()
            if not binding or not 1<=len(raw.encode())<=32768:raise ValueError('Gespeicherte Freigabe-ID und begrenztes Desktop-Client-JSON eingeben.')
            from .gateway_line_ingress import _object
            from .gateway_dingtalk_admission import finite
            configuration=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
        except (ValueError,TypeError,RecursionError):
            self.wizard.status.configure(text='Aktuelle Freigabe, ausdrückliche Zustimmung, Prüfbegründung und gültiges Desktop-Client-JSON erforderlich.');return
        connector=self.connector();self.invalidate();self.configuration.delete(0,self.wizard.tk.END)
        def accepted(value):
            self.session=deepcopy(value);self.session_connector=connector;self.render(self.authorization,value['authorization_url'])
            self.wizard.status.configure(text='Google-Adresse vorbereitet. Im eigenen Browser bestätigen und vollständige Rücksprungadresse einfügen.')
        self.submit('oauth-begin',lambda:owner.oauth_begin(connector,binding,configuration,note,confirmed=True),accepted=accepted)

    def finish(self):
        if self.wizard.running:return
        try:
            self.consent()
            if self.session is None or self.session_connector!=self.connector():raise ValueError('Zuerst eine aktuelle Anmeldung vorbereiten.')
            returned=self.callback.get();session=deepcopy(self.session)
            if not 1<=len(returned)<=8192:raise ValueError('Vollständige Rücksprungadresse erforderlich.')
        except ValueError as error:self.wizard.status.configure(text=str(error));return
        connector=self.connector();self.callback.delete(0,self.wizard.tk.END);self.session=None;self.session_connector=None;self.render(self.authorization,'')
        def accepted(value):self.wizard.status.configure(text='Numerischer Google-Nutzer bestätigt; private Nutzerfreigabe gespeichert. Keine Nachricht versendet.')
        self.submit('oauth-finish',lambda:owner.oauth_finish(connector,session,returned,confirmed=True),request={'subject':session['subject'],'id':session['id']},accepted=accepted)

    def load(self,kind):
        if self.wizard.running:return
        self.rows=[];self.kind=None;self.loaded_connector=None;self.list.delete(0,self.wizard.tk.END);self.selected();connector=self.connector()
        def accepted(value):
            self.kind=kind;self.rows=deepcopy(value[kind]);self.loaded_connector=connector
            for row in self.rows:self.list.insert(self.wizard.tk.END,(row.get('subject') or row.get('subject_expected'))+' · '+row.get('status',row.get('state',''))+' · '+row['id'][:12])
            self.wizard.status.configure(text='Private OAuth-Metadaten geprüft. Für Widerruf genau eine Zeile auswählen; keine Nachricht versendet.')
        self.submit('oauth-'+kind,lambda:owner.oauth_inspect(connector,kind),accepted=accepted)

    def withdraw(self,kind):
        if self.wizard.running:return
        try:
            note=self.consent();selection=self.list.curselection()
            if self.kind!=kind or self.loaded_connector!=self.connector() or not selection or selection[0]>=len(self.rows):raise ValueError('Zuerst aktuellen passenden Status laden und genau eine Zeile auswählen.')
            row=deepcopy(self.rows[selection[0]])
        except ValueError as error:self.wizard.status.configure(text=str(error));return
        connector=self.connector();action='oauth-revoke' if kind=='tokens' else 'oauth-dispose'
        def execute():return owner.oauth_revoke(connector,row,note,confirmed=True) if kind=='tokens' else owner.oauth_dispose(connector,row,note,confirmed=True)
        def accepted(value):
            self.rows=[];self.kind=None;self.list.delete(0,self.wizard.tk.END);self.selected()
            self.wizard.status.configure(text=('Google bestätigt den Widerruf; privater Prüfbeleg gespeichert.' if value['remote_revocation_verified'] else
                'Lokale Nutzung gesperrt; entfernter Widerruf nicht bestätigt: '+value['remote_status']+'. Status und Wartezeit prüfen.'))
        self.submit(action,execute,accepted=accepted)


class FileRecoveryForm(RecoveryForm):
    """Payload-free file decisions with the same asynchronous stale-result guard."""
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;self.rows=[];self.kind=None;self.epoch=0;self.loaded_connector=None;self.confirm_connector=None;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.buttons={}
        wizard._label(self.frame,'Google Chat: Dateiversand prüfen und wiederherstellen',size=12).pack(anchor='w',pady=5)
        self.buttons['files']=self.button('Dateioperationen ohne Nutzdaten prüfen',lambda:self.load('files'))
        self.buttons['outputs']=self.button('Lokale Dateikopien ohne Nutzdaten prüfen',lambda:self.load('outputs'))
        self.list=tk.Listbox(self.frame,height=6,exportselection=False,bg=wizard.BG,fg=wizard.TEXT);self.list.pack(fill='x',pady=4)
        self.list.bind('<<ListboxSelect>>',self.selected)
        self.details=tk.Text(self.frame,height=7,wrap='word',bg=wizard.BG,fg=wizard.TEXT,state='disabled');self.details.pack(fill='x',pady=4)
        self.note=wizard._field(self.frame,'Nicht geheime Prüfbegründung (keine Zugangsdaten)')
        self.confirm=tk.BooleanVar(value=False);self.not_delivered=tk.BooleanVar(value=False)
        self.confirm.trace_add('write',lambda *_:setattr(self,'confirm_connector',self.connector() if self.confirm.get() else None))
        self.flag('Genau diesen aktuellen Beleg geprüft und diese Aktion ausdrücklich freigegeben',self.confirm)
        self.flag('Genau diese Dateinachricht nach unabhängiger Prüfung sicher nicht zugestellt; ein GET404 allein genügt nicht',self.not_delivered)
        self.buttons['upload']=self.button('Genau diesen unklaren Upload einmal freigeben',lambda:self.perform_file('retry-upload'))
        self.buttons['retry']=self.button('Genau diese unbestätigte Dateinachricht einmal freigeben',lambda:self.perform_file('retry-file'))
        self.buttons['purge']=self.button('Genau diese lokale Dateikopie nach Freigabeentzug entsorgen',lambda:self.perform_file('output-purge'))
        wizard._label(self.frame,'Diese Entscheidungen senden nichts und ersetzen keine getrennte Controller-Recovery. '
            'Eine Uploadfreigabe gilt nur, solange noch kein Nachrichtenversand begonnen wurde. Die gleiche Datei und derselbe Nutzer bleiben gebunden. '
            'Vor einem freigegebenen Neuversand wird verspätete Annahme unter derselben Nachrichten-ID geprüft; '
            'auch eine abgebrochene Prüfung verbraucht die Freigabe. Bestätigte Nachrichten werden nicht neu versendet. '
            'Entsorgung entfernt nur die gewählte lokale Dateikopie nach Entzug ihrer alten Freigabe. '
            'Google-Kopien, andere lokale Kopien, Prüfbelege, Backups und WAL werden damit nicht sicher gelöscht. '
            'Die Prüfung stoppt den Gateway-Dienst; anschließend bewusst wieder starten.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)

    def load(self,kind):
        connector=self.connector();self.clear();epoch=self.epoch
        def show(value):
            if not self.fresh(epoch,connector):return
            try:value=response(value,kind,connector)
            except (ValueError,TypeError,KeyError):self.clear();self.wizard.status.configure(text='Ungültigen oder privaten Datei-Prüfbeleg verworfen.');return
            if 'error' in value:self.wizard.status.configure(text=ERRORS[value['error']]);return
            self.kind=kind;self.loaded_connector=connector;self.rows=deepcopy(value[kind])
            for row in self.rows:self.list.insert(self.wizard.tk.END,row['filename']+' · '+row['state']+(' · '+row['upload_state'] if kind=='files' else '')+' · '+row['id'][:12])
            self.wizard.status.configure(text='Dateibelege ohne Inhalte oder Zugangsdaten geladen. Genau eine Zeile auswählen.')
        self.wizard._run_async(lambda:owner.inspect(connector,kind),result_handler=show)

    def perform_file(self,action):
        if self.wizard.running:return
        kind='outputs' if action=='output-purge' else 'files'
        try:
            row=self.choice(kind);note=self.note.get().strip();confirmed=self.confirm.get();independent=self.not_delivered.get()
            if not confirmed or self.confirm_connector!=self.connector() or not 1<=len(note)<=2000:raise ValueError('Aktuellen Beleg ausdrücklich bestätigen und nicht geheime Prüfbegründung angeben.')
            field={'retry-upload':'upload_retry_allowed','retry-file':'file_retry_allowed','output-purge':'purge_allowed'}[action]
            if row.get(field) is not True:raise ValueError('Dieser Beleg erlaubt die gewählte Aktion nicht. Freigabe, Quellbeleg, Zustand und Retry-Grenze prüfen.')
            if action=='retry-file' and independent is not True:raise ValueError('Nichtzustellung dieser Dateinachricht unabhängig prüfen und ausdrücklich bestätigen.')
        except ValueError as error:self.wizard.status.configure(text=str(error));return
        connector=self.connector();epoch=self.epoch;self.confirm.set(False);self.not_delivered.set(False);self.note.delete(0,self.wizard.tk.END)
        backend_action='output-purge' if action=='output-purge' else 'file-decide'
        def execute():
            if action=='output-purge':return owner.output_purge(connector,row,note,confirmed=True)
            return owner.file_retry(connector,row,action,note,confirmed=True,confirmed_not_delivered=action=='retry-file' and independent)
        def finished(value):
            if not self.fresh(epoch,connector):return
            try:value=response(value,backend_action,connector,request={'id':row['id'],'action':action})
            except (ValueError,TypeError,KeyError):self.clear();self.wizard.status.configure(text='Ungültigen Datei-Entscheidungsbeleg verworfen. Zustand neu prüfen.');return
            self.clear();self.wizard.status.configure(text=ERRORS[value['error']] if 'error' in value else
                'Lokale Dateikopie entsorgt; keine entfernte Löschung bestätigt.' if action=='output-purge' else
                'Begrenzte Owner-Entscheidung gespeichert; kein Versand. Getrennte Controller-Recovery ausdrücklich prüfen.')
        self.wizard._run_async(execute,result_handler=finished)
