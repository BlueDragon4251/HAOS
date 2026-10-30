"""Trusted local owner Buzz forms with private entry and explicit recovery."""
import json
import re

from . import buzz_owner_setup as owner

ERRORS={'sdk-unavailable':'Gepinnte Buzz-Runtime oder native Programme fehlen.',
    'authentication-refused':'Relay lehnt die Anmeldung ab. Schlüssel, NIP-OA-Freigabe und Relay-Rechte prüfen.',
    'identity-refused':'Privater Schlüssel, nsec-Prüfsumme und erwartete öffentliche Identität passen nicht zusammen.',
    'authority-refused':'Identität, Freigabe oder Prüfbeleg erlaubt diese Aktion nicht. Zustand neu prüfen.',
    'rate-limited':'Relay begrenzt Anfragen. Warten und später erneut prüfen.',
    'storage-unavailable':'Privates Buzz-Journal oder Runtime prüfen. Vorhandene Daten bleiben erhalten.',
    'transport-unavailable':'Relay, TLS, Netzwerk und gespeicherte Kanäle prüfen.',
    'private-reflection':'Antwort enthält private Zugangsdaten und wurde verworfen.'}

LABELS={'created':'Privates Buzz-Profil vorbereitet', 'connecting':'Buzz-Identität und NIP-42-Verbindung werden geprüft',
    'connected-ws':'Buzz-WebSocket verbunden; kein Zustellungsbeleg',
    'connected-poll':'Buzz-Leseverbindung bereit; WebSocket wird wiederhergestellt',
    'disconnected':'Buzz-Verbindung getrennt; gespeicherte Belege bleiben erhalten',
    'closed':'Buzz-Profil geschlossen; gespeicherte Daten bleiben erhalten',
    'revoked':'Buzz-Freigabe geändert oder entzogen; Verbindung geschlossen',
    'authentication-refused':ERRORS['authentication-refused'],'identity-refused':ERRORS['identity-refused'],
    'rate-limited':ERRORS['rate-limited'],'transport-unavailable':ERRORS['transport-unavailable'],
    'source-unavailable':'Gespeicherte Buzz-Quelle oder deren Prüfbeleg ist nicht verfügbar; keine automatische Wiederherstellung',
    'storage-unavailable':ERRORS['storage-unavailable']}


def flag(wizard,parent,label,variable):
    box=wizard.tk.Checkbutton(parent,text=label,variable=variable,bg=wizard.PANEL,fg=wizard.TEXT,
        selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left',anchor='w');box.pack(anchor='w',pady=3)
    return box


def button(wizard,parent,label,action):
    widget=wizard._button(parent,label,action)
    widget.configure(wraplength=max(180,wizard.label_wrap-50),justify='left')
    return widget


class AccountForm:
    def __init__(self,wizard,parent,connector):
        self.wizard=wizard;self.connector=connector;self.on_saved=None;self.resetting=False;self.metadata={};tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL);self.fields={}
        for key,label,secret in [('relay_url','Exakter HTTPS-Relay-Ursprung ohne abschließenden Schrägstrich',False),
                ('public_key','Erwartete öffentliche Nostr-Identität (64 Hex-Zeichen)',False),
                ('private_key','Dedizierter privater Nostr-Schlüssel (Hex oder nsec)',True),
                ('auth_tag','Optionale private NIP-OA-Attestierung (JSON-Array)',True),
                ('channels','Exakte Kanal-UUIDs, durch Komma getrennt (1–32)',False),
                ('attachment_origins','Zusätzlich erlaubte HTTPS-Ursprünge für eingehende Anhänge (optional, maximal 8)',False)]:
            self.fields[key]=wizard._field(self.frame,label,secret=secret)
        self.keep_key=tk.BooleanVar(value=False);self.keep_auth=tk.BooleanVar(value=False);self.show_key=tk.BooleanVar(value=False)
        flag(wizard,self.frame,'Gespeicherten privaten Schlüssel für unveränderte Identität und Relay beibehalten',self.keep_key)
        flag(wizard,self.frame,'Gespeicherte NIP-OA-Attestierung beibehalten',self.keep_auth)
        flag(wizard,self.frame,'Nur hier neu eingegebene private Werte anzeigen',self.show_key)
        self.keep_key.trace_add('write',self.material_state);self.keep_auth.trace_add('write',self.material_state)
        self.show_key.trace_add('write',self.visibility)
        for key in ['relay_url','public_key']:
            variable=tk.StringVar();self.fields[key].configure(textvariable=variable);self.fields[key]._haos_public_value=variable
            variable.trace_add('write',self.changed)
        wizard._label(self.frame,'Eine dedizierte Dienstidentität verwenden. Änderungen am Konto entziehen dessen bisherige Freigaben. '
            'Für jeden gespeicherten Kanal mindestens einen exakten Absender und gegebenenfalls einen exakten Thread freigeben. '
            'Kanalmitgliedschaft und Plugins erteilen keine HAOS-Rechte. Die Kontoprüfung sendet keine Nachricht; sie ersetzt keine Zustellungsabnahme.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        button(wizard,self.frame,'Gespeichertes Buzz-Konto ohne Versand prüfen',self.inspect).pack(anchor='w',pady=4)
        self.auth_confirm=tk.BooleanVar(value=False)
        flag(wizard,self.frame,'Nach Prüfung von Relay und Kontorechten eine erneute Authentifizierung ausdrücklich erlauben',self.auth_confirm)
        button(wizard,self.frame,'Lokale Auth-Sperre freigeben; kein Versand',self.retry_auth).pack(anchor='w',pady=4)
        self.reset()

    def visibility(self,*_args):
        for key in ['private_key','auth_tag']:self.fields[key].configure(show='' if self.show_key.get() else '•')

    def material_state(self,*_args):
        for key,keep in [('private_key',self.keep_key),('auth_tag',self.keep_auth)]:
            entry=self.fields[key];entry.configure(state='normal')
            if keep.get():entry.delete(0,self.wizard.tk.END);entry.configure(state='disabled')

    def changed(self,*_args):
        if self.resetting:return
        self.keep_key.set(False);self.keep_auth.set(False);self.clear_secret()

    def clear_secret(self,*_args):
        self.show_key.set(False);self.auth_confirm.set(False)
        for key in ['private_key','auth_tag']:
            self.fields[key].configure(state='normal');self.fields[key].delete(0,self.wizard.tk.END)
        self.material_state()

    def reset(self,value=None):
        self.resetting=True;self.metadata=value or {}
        try:
            for key,entry in self.fields.items():
                entry.configure(state='normal');entry.delete(0,self.wizard.tk.END)
                if key in {'channels','attachment_origins'}:entry.insert(0,', '.join(self.metadata.get(key,[])))
                elif key in {'relay_url','public_key'}:entry.insert(0,self.metadata.get(key,''))
            self.keep_key.set(self.metadata.get('saved_private_key',False));self.keep_auth.set(self.metadata.get('saved_auth_tag',False))
            self.clear_secret()
        finally:self.resetting=False

    def configure(self):
        connector=self.connector();values={key:entry.get() for key,entry in self.fields.items()}
        keep_key=self.keep_key.get();keep_auth=self.keep_auth.get();self.clear_secret()
        def perform():
            account={key:values[key].strip() for key in ['relay_url','public_key']}
            for key in ['channels','attachment_origins']:
                account[key]=[part for part in re.split(r'[,\s]+',values[key].strip()) if part]
            owner.save_account(connector,account,values['private_key'].strip(),values['auth_tag'].strip(),keep_key=keep_key,keep_auth=keep_auth)
            from .initial_setup import gateway_configuration
            return gateway_configuration()['buzz'][connector]
        self.wizard._run_async(perform,success='Buzz-Konto gespeichert. Absender und Kanäle ausdrücklich freigeben; Dienst bleibt gestoppt.',result_handler=self.saved)

    def saved(self,value):
        if not self.frame.winfo_exists():return
        self.reset(value)
        if self.on_saved is not None:self.on_saved(value)

    def inspect(self):
        connector=self.connector();self.clear_secret()
        def show(value):
            if connector!=self.connector():return
            self.wizard.status.configure(text=ERRORS.get(value.get('error'),
                'Native Identität und gespeicherte Leseabfragen geprüft. Keine Nachricht versendet; externe Zustellung ungeprüft.'))
        self.wizard._run_async(lambda:owner.inspect(connector),result_handler=show)

    def retry_auth(self):
        connector=self.connector();confirmed=self.auth_confirm.get();self.clear_secret()
        self.wizard._run_async(lambda:owner.retry_auth(connector,'Owner requested a new Buzz authentication check',confirmed=confirmed),
            result_handler=lambda value:self.wizard.status.configure(text=ERRORS.get(value.get('error'),
                'Lokale Auth-Sperre geprüft. Dienst bleibt gestoppt; keine Nachricht versendet.')))


class PairForm:
    def __init__(self,wizard,parent,platform,account,sender,chat,scope,thread,rights,before):
        self.wizard=wizard;self.platform=platform;self.account=account;self.scope=scope;self.rights=rights;self.before=before
        self.active=False;tk=wizard.tk;self.frame=tk.Frame(parent,bg=wizard.PANEL)
        self.flags={key:tk.BooleanVar(value=False) for key in ['allow_media','allow_voice','allow_video','allow_outbound_media']}
        self.boxes={};self.mention=tk.BooleanVar(value=True)
        for key,label in [('allow_media','Buzz-Bilder und Dokumente für genau diesen Absender freigeben'),
                ('allow_voice','Buzz-Sprachnachrichten lokal transkribieren'),('allow_video','Buzz-Videoeingang als Datei freigeben'),
                ('allow_outbound_media','Markierte Ergebnisdateien genau dieser Missionen an diesen Chat senden')]:
            self.boxes[key]=flag(wizard,self.frame,label,self.flags[key])
        flag(wizard,self.frame,'Nur bei ausdrücklicher Erwähnung der Dienstidentität reagieren',self.mention)
        wizard._label(self.frame,'Absender: exakter öffentlicher Nostr-Hex-Schlüssel; Chat: eine gespeicherte Kanal-UUID. '
            'Ein leerer Thread erlaubt ausschließlich Nachrichten ohne Thread; für Antworten einen exakten 64-stelligen Root-Event-Hash freigeben. '
            'Keine Platzhalter, Anzeigenamen oder automatische Mitgliedsfreigaben. Jeder gespeicherte Kanal benötigt eine ausdrückliche Route. '
            'Bilder zusammen höchstens 2 MiB; übrige Dateien höchstens 8 MiB, maximal vier. Voice benötigt den eingerichteten lokalen Sprachdienst. '
            'Ergebnisdateien benötigen Leserecht und verlassen über das Relay den Rechner.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        for entry in [sender,chat,thread]:
            variable=getattr(entry,'_haos_public_value',None)
            if variable is None:variable=tk.StringVar(value=entry.get());entry.configure(textvariable=variable);entry._haos_public_value=variable
            variable.trace_add('write',self.clear)
        for key in ['relay_url','public_key']:account.fields[key]._haos_public_value.trace_add('write',self.changed)
        for variable in rights.values():variable.trace_add('write',self.permissions)
        def platform_changed(*_args):
            if platform.get()=='buzz':wizard.root.after_idle(self.changed)
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
        self.clear();active=self.platform.get()=='buzz'
        if active:
            self.frame.pack(fill='x',before=self.before);self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END)
            self.scope.insert(0,self.account.metadata.get('scope',''));self.scope.configure(state='disabled');self.permissions()
        else:
            self.frame.pack_forget()
            if self.active:self.scope.configure(state='normal');self.scope.delete(0,self.wizard.tk.END)
        self.active=active

    def options(self):
        metadata=self.account.metadata
        if (not metadata or any(self.account.fields[key].get().strip()!=metadata.get(key) for key in ['relay_url','public_key'])
                or any(self.account.fields[key].get().strip() for key in ['private_key','auth_tag'])
                or any(sorted([part for part in re.split(r'[,\s]+',self.account.fields[key].get().strip()) if part])!=sorted(metadata.get(key,[]))
                    for key in ['channels','attachment_origins'])):
            raise ValueError('Das Buzz-Konto zuerst vollständig speichern; danach die gespeicherte Route freigeben.')
        return {**{key:value.get() for key,value in self.flags.items()},'require_mention':self.mention.get()}


class RecoveryForm:
    def __init__(self,wizard,parent,connector,account):
        self.wizard=wizard;self.connector=connector;self.account=account;self.rows=[];self.kind=None;self.epoch=0;tk=wizard.tk
        self.frame=tk.Frame(parent,bg=wizard.PANEL)
        wizard._label(self.frame,'Private Uploads und signierte Antworten prüfen',size=12).pack(anchor='w',pady=5)
        self.profile_entry=wizard._field(self.frame,'Speicherprofil (leer: gespeichertes Konto; alte Profile ausdrücklich auswählen)')
        self.profile_var=tk.StringVar();self.profile_entry.configure(textvariable=self.profile_var)
        self.profile_var.trace_add('write',self.clear)
        button(wizard,self.frame,'Erhaltene Buzz-Profile anzeigen',lambda:self.load('source-profiles')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Private Original-Belege laden',lambda:self.load('sources')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Verlaufsprüfbelege laden',lambda:self.load('history')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Private Upload-Belege laden',lambda:self.load('outputs')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Signierte Antwort-Belege laden',lambda:self.load('outgoing')).pack(anchor='w',pady=3)
        self.list=tk.Listbox(self.frame,height=7,exportselection=False,bg=wizard.BG,fg=wizard.TEXT)
        self.list.pack(fill='x',pady=4);self.list.bind('<<ListboxSelect>>',self.selected)
        self.details=tk.Text(self.frame,height=6,wrap='word',bg=wizard.BG,fg=wizard.TEXT,state='disabled')
        self.details.pack(fill='x',pady=4)
        self.note=wizard._field(self.frame,'Nicht geheime Prüfbegründung (keine Zugangsdaten)')
        self.confirm=tk.BooleanVar(value=False);self.not_delivered=tk.BooleanVar(value=False)
        flag(wizard,self.frame,'Genau diesen aktuellen Prüfbeleg geprüft und diese Aktion ausdrücklich freigegeben',self.confirm)
        flag(wizard,self.frame,'Antwort nach unabhängiger Prüfung sicher nicht zugestellt (nur Antwort-Wiederholung)',self.not_delivered)
        button(wizard,self.frame,'Unklaren Upload einmal mit exakt denselben Quelldaten freigeben',lambda:self.decide('retry-upload')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Upload-Nutzdaten nach Freigabeentzug entsorgen; Belege behalten',lambda:self.decide('purge-upload')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Genau dieselbe signierte Antwort für inspizierte Wiederholung freigeben',self.reply).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Original-Nutzdaten nach Freigabeentzug entsorgen',lambda:self.source('purge-source')).pack(anchor='w',pady=3)
        button(wizard,self.frame,'Verlauf für geänderte exakte Freigabe neu prüfen; alte Belege behalten',lambda:self.source('reset-history')).pack(anchor='w',pady=3)
        wizard._label(self.frame,'Diese Aktionen senden nichts. Eine Antwortfreigabe ersetzt nicht die getrennte Controller-Recovery. '
            'Bestätigte Annahmen dürfen nicht erneut versendet werden. Unklare Antworten behalten ID, Signatur und Inhalt. '
            'Vor Entsorgung die ursprüngliche Freigabe entziehen und offene Missionen prüfen. Alte Profile bleiben auswählbar. '
            'Nach Freigabeänderung kann ein alter Verlaufscursor für den neuen Zeitstichtag ausdrücklich neu gestartet werden. '
            'Original-Prüfbelege bleiben erhalten; Nachrichteninhalt wird hier nicht ausgegeben. Andere Missionskopien, Backups und WAL werden nicht sicher gelöscht.',
            size=10,color=wizard.MUTED).pack(anchor='w',pady=5)

    def clear(self,*_args):
        self.epoch+=1;self.rows=[];self.kind=None;self.list.delete(0,self.wizard.tk.END);self.selected()

    def selected(self,*_args):
        self.confirm.set(False);self.not_delivered.set(False);self.note.delete(0,self.wizard.tk.END)
        selected=self.list.curselection();row=self.rows[selected[0]] if selected and selected[0]<len(self.rows) else None
        if row is not None and self.kind=='source-profiles':
            self.profile_var.set(row['profile']);self.wizard.status.configure(text='Erhaltenes Profil ausgewählt. Jetzt Original- oder Verlaufsbelege laden.');return
        self.details.configure(state='normal');self.details.delete('1.0',self.wizard.tk.END)
        if row is not None:self.details.insert('1.0',json.dumps(row,ensure_ascii=False,indent=2))
        self.details.configure(state='disabled')

    def load(self,kind):
        selected_profile=self.profile_var.get().strip() or self.account.metadata.get('profile')
        self.clear();epoch=self.epoch;connector=self.connector()
        def show(value):
            if epoch!=self.epoch or connector!=self.connector() or not self.frame.winfo_exists():return
            if 'error' in value:self.wizard.status.configure(text=ERRORS[value['error']]);return
            self.kind=kind;self.rows=([{'profile':name,'state':'profile'} for name in value['profiles']] if kind=='source-profiles' else value[kind])
            for row in self.rows:self.list.insert(self.wizard.tk.END,
                (row.get('name') or row.get('delivery_id','')[:16] or row.get('event_id','')[:16] or row.get('channel') or row.get('profile',''))+' — '+row['state'])
            self.wizard.status.configure(text='Private Belege geladen. Keine Nachricht versendet; Zeile ausdrücklich auswählen.')
        self.wizard._run_async(lambda:owner.inspect(connector,kind,profile=selected_profile)
            if kind in {'sources','history'} else owner.inspect(connector,kind),result_handler=show)

    def choice(self,kind):
        selected=self.list.curselection()
        if self.kind!=kind or not selected or selected[0]>=len(self.rows):raise ValueError('Zuerst den passenden aktuellen Beleg laden und auswählen.')
        return dict(self.rows[selected[0]])

    def decide(self,action):
        connector=self.connector();confirmed=self.confirm.get();note=self.note.get()
        # Selection is frozen on the UI thread; no Tk access in the worker.
        try:row=self.choice('outputs')
        except ValueError as error:
            message=str(error);self.wizard._run_async(lambda:(_ for _ in ()).throw(ValueError(message)));return
        self.confirm.set(False)
        self.wizard._run_async(lambda:owner.recover_upload(connector,row,action,note,confirmed=confirmed),result_handler=self.finished)

    def reply(self):
        connector=self.connector();confirmed=self.confirm.get();not_delivered=self.not_delivered.get();note=self.note.get()
        try:row=self.choice('outgoing')
        except ValueError as error:
            message=str(error);self.wizard._run_async(lambda:(_ for _ in ()).throw(ValueError(message)));return
        self.confirm.set(False);self.not_delivered.set(False)
        self.wizard._run_async(lambda:owner.approve_reply(connector,row,note,confirmed=confirmed,
            confirmed_not_delivered=not_delivered),result_handler=self.finished)

    def source(self,action):
        connector=self.connector();confirmed=self.confirm.get();note=self.note.get()
        try:row=self.choice('sources' if action=='purge-source' else 'history')
        except ValueError as error:
            message=str(error);self.wizard._run_async(lambda:(_ for _ in ()).throw(ValueError(message)));return
        self.confirm.set(False)
        self.wizard._run_async(lambda:owner.recover_source(connector,row,action,note,confirmed=confirmed),result_handler=self.finished)

    def finished(self,value):
        self.wizard.status.configure(text=ERRORS.get(value.get('error'),
            'Owner-Entscheidung gespeichert; kein Versand. Für Antworten zusätzlich Controller-Recovery prüfen.'))
        self.clear()
