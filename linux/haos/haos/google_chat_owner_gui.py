"""Prepared local Owner recovery controls backed by private UID actions."""
import json
from copy import deepcopy

from . import google_chat_owner_setup as owner
from .google_chat_owner_process import response

ERRORS={'authority-refused':'Konto, Freigabe, Profilsperre oder Prüfbeleg erlaubt diese Aktion nicht. Zustand neu prüfen.',
    'storage-unavailable':'Privates Google-Chat-Journal prüfen. Vorhandene Daten bleiben erhalten.',
    'runtime-unavailable':'Die installierte private Google-Chat-Runtime fehlt oder ist unvollständig.'}


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
