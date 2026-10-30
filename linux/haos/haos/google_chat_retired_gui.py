"""Owner controls for retained app metadata and explicit withdrawal decisions."""
import json
from copy import deepcopy

from . import google_chat_retired_setup as owner
from .google_chat_retired_process import response,current_policy
from .google_chat_owner_gui import ERRORS


class HistoricalRecoveryForm:
    def __init__(self,wizard,parent):
        self.wizard=wizard;self.epoch=0;self.rows=[];self.kind=None;self.account=None;self.loaded_profile=None
        tk=wizard.tk;self.frame=tk.Frame(parent,bg=wizard.PANEL);self.buttons={}
        wizard._label(self.frame,'Google Chat: entfernte Konten und lokale Altbestände',size=12).pack(anchor='w',pady=5)
        wizard._label(self.frame,'Auch nach Kontoentfernung nutzbar. Diese Prüfungen stoppen den Gateway-Dienst. '
            'Metadaten ersetzen weder ein Konto noch eine Absenderfreigabe. Alte Profile ohne belegte App-Identität '
            'werden ausdrücklich als unbekannt angezeigt.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        self.profile=wizard._field(self.frame,'Erhaltenes Google-Chat-Profil')
        self.profile_var=tk.StringVar();self.profile.configure(textvariable=self.profile_var);self.profile_var.trace_add('write',self.clear)
        self.identity_vars={}
        wizard._label(self.frame,'Nur bei fehlender alter App-Metadatei: ursprüngliche öffentliche Werte eingeben. '
            'Ihr Hash muss exakt dem erhaltenen Profil entsprechen; keine neuen Namen, Schlüssel oder API-Freigaben.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)
        for key,label in [('project_id','Ursprüngliche öffentliche Google-Projekt-ID'),('service_account_email','Ursprüngliche Service-Konto-E-Mail'),
                ('bot_user','Ursprünglicher numerischer Bot: users/<ID>')]:
            entry=wizard._field(self.frame,label);var=tk.StringVar();entry.configure(textvariable=var);self.identity_vars[key]=var
            var.trace_add('write',self.identity_changed)
        for kind,label in [('profiles','Erhaltene Konten auflisten'),('tokens','Nutzerfreigaben prüfen'),
                ('quarantines','Abgelehnte Zugangsdaten prüfen'),('outputs','Lokale Konto-Ausgaben prüfen'),
                ('unassociated-outputs','Unzugeordnete lokale Ausgaben prüfen')]:
            self.button(kind,label,lambda kind=kind:self.load(kind))
        self.list=tk.Listbox(self.frame,height=6,exportselection=False,bg=wizard.BG,fg=wizard.TEXT)
        self.list.pack(fill='x',pady=4);self.list.bind('<<ListboxSelect>>',self.selected)
        self.details=tk.Text(self.frame,height=7,wrap='word',bg=wizard.BG,fg=wizard.TEXT,state='disabled');self.details.pack(fill='x',pady=4)
        self.note=wizard._field(self.frame,'Nicht geheime Prüfbegründung (keine Zugangsdaten)')
        self.confirm=tk.BooleanVar(value=False)
        tk.Checkbutton(self.frame,text='Genau diesen aktuellen Beleg und diese Aktion ausdrücklich bestätigen',variable=self.confirm,
            bg=wizard.PANEL,fg=wizard.TEXT,selectcolor=wizard.BG,wraplength=wizard.label_wrap,justify='left').pack(anchor='w',pady=4)
        self.button('withdraw','Ausgewählte Nutzerfreigabe oder Quarantäne widerrufen',self.withdraw)
        self.button('purge','Ausgewählte lokale Ausgabebytes entsorgen',self.purge)
        self.button('restore','Exakte ursprüngliche öffentliche App-Metadaten wiederherstellen',self.restore)
        wizard._label(self.frame,'Widerruf sperrt zuerst lokal und kann Google kontaktieren; er versendet keine Nachricht. '
            'Ein unklarer Widerruf wird nicht automatisch wiederholt. Lokale Ausgaben lassen sich erst nach Entzug '
            'der ursprünglichen Freigabe entsorgen. Prüfbelege bleiben; entfernte Nachrichten, WAL und Backups '
            'werden damit nicht gelöscht. Danach den Gateway-Dienst bewusst wieder starten.',size=10,color=wizard.MUTED).pack(anchor='w',pady=5)

    def button(self,key,label,action):
        button=self.wizard._button(self.frame,label,action);button.configure(wraplength=max(180,self.wizard.label_wrap-50),justify='left')
        button.pack(anchor='w',pady=3);self.buttons[key]=button

    def render(self,value):
        self.details.configure(state='normal');self.details.delete('1.0',self.wizard.tk.END)
        if value is not None:self.details.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2))
        self.details.configure(state='disabled')

    def reset_consent(self):
        self.confirm.set(False);self.note.delete(0,self.wizard.tk.END)

    def clear(self,*_args):
        self.epoch+=1;self.rows=[];self.kind=None;self.account=None;self.loaded_profile=None
        for variable in getattr(self,'identity_vars',{}).values():variable.set('')
        if hasattr(self,'list'):self.list.delete(0,self.wizard.tk.END);self.render(None);self.reset_consent()

    def identity_changed(self,*_args):
        self.epoch+=1
        if hasattr(self,'confirm'):self.reset_consent()

    def fresh(self,epoch,profile):
        return epoch==self.epoch and profile==self.profile_var.get().strip() and bool(self.frame.winfo_exists())

    def selected(self,*_args):
        self.reset_consent();indices=self.list.curselection()
        row=self.rows[indices[0]] if indices and indices[0]<len(self.rows) else None
        if row is not None and self.kind=='profiles':
            self.profile_var.set(row['profile']);self.wizard.status.configure(text='Profil ausgewählt. Jetzt die gewünschten Belege frisch laden.');return
        self.render(row)

    def load(self,kind):
        if self.wizard.running:return
        profile=self.profile_var.get().strip();self.clear();epoch=self.epoch
        if kind not in {'profiles','unassociated-outputs'} and not profile:
            self.wizard.status.configure(text='Zuerst ein erhaltenes Profil ausdrücklich auswählen.');return
        request={'profile':profile} if kind not in {'profiles','unassociated-outputs'} else {}
        def execute():
            value=(owner.profiles() if kind=='profiles' else owner.unassociated_outputs() if kind=='unassociated-outputs'
                else getattr(owner,kind)(profile))
            # Recheck the real Root publication, including informational active
            # file grants, before any metadata enters the Tk details widget.
            return response(value,kind,request=request,policy=current_policy())
        def show(value):
            if not self.fresh(epoch,profile):return
            if 'error' in value:self.wizard.status.configure(text=ERRORS[value['error']]);return
            self.kind=kind;self.loaded_profile=profile;self.account=deepcopy(value.get('account'))
            if kind=='profiles':
                self.rows=deepcopy(value['profiles'])+[{'profile':name,'identity_missing':True} for name in value['identity_missing']]
                truncated=value['history_truncated']
            else:
                self.rows=deepcopy(value['result']['outputs' if kind=='unassociated-outputs' else kind]);truncated=value['result']['history_truncated']
            for row in self.rows:
                label=(row['profile']+(' · App-Identität unbekannt' if row.get('identity_missing') else '') if kind=='profiles'
                    else row['id']+' · '+str(row.get('status',row.get('state',''))))
                self.list.insert(self.wizard.tk.END,label)
            self.wizard.status.configure(text='Metadaten geladen; keine Nachricht versendet.'+
                (' Weitere historische Belege vorhanden; nach Bereinigung erneut laden.' if truncated else ''))
        self.wizard._run_async(execute,result_handler=show)

    def perform(self,allowed):
        if self.wizard.running:return
        try:
            indices=self.list.curselection()
            if (self.kind not in allowed or self.loaded_profile!=self.profile_var.get().strip() or not indices
                    or indices[0]>=len(self.rows)):raise ValueError('Passenden aktuellen Beleg laden und ausdrücklich auswählen.')
            row=deepcopy(self.rows[indices[0]]);account=deepcopy(self.account);kind=self.kind;note=self.note.get().strip()
            if self.confirm.get() is not True or not 1<=len(note)<=2000:raise ValueError('Aktuellen Beleg bestätigen und eine nicht geheime Prüfbegründung eingeben.')
            if kind in {'outputs','unassociated-outputs'} and row.get('purge_allowed') is not True:
                raise ValueError('Zuerst die ursprüngliche Freigabe entziehen und Zustand neu laden.')
        except ValueError as error:self.wizard.status.configure(text=str(error));return
        epoch=self.epoch;profile=self.profile_var.get().strip();self.reset_consent()
        action={'tokens':'revoke-token','quarantines':'dispose-capsule','outputs':'purge-output','unassociated-outputs':'purge-unassociated-output'}[kind]
        request={'id':row['id']}
        if account:request.update(profile=account['profile'],identity_sha256=account['identity_sha256'])
        def execute():
            if kind=='tokens':return owner.revoke(account,row,note,confirmed=True)
            if kind=='quarantines':return owner.dispose(account,row,note,confirmed=True)
            if kind=='outputs':return owner.purge_output(account,row,note,confirmed=True)
            return owner.purge_unassociated_output(row,note,confirmed=True)
        def done(value):
            if not self.fresh(epoch,profile):return
            try:value=response(value,action,request=request)
            except (ValueError,TypeError,KeyError):
                self.clear();self.wizard.status.configure(text='Ungültigen Entscheidungsbeleg verworfen; Zustand neu laden.');return
            self.clear()
            if 'error' in value:self.wizard.status.configure(text=ERRORS[value['error']]);return
            result=value['result']
            self.wizard.status.configure(text=('Lokale Ausgabebytes entsorgt; keine entfernte Löschung.' if kind in {'outputs','unassociated-outputs'}
                else 'Lokal gesperrt. Google-Widerruf: '+result['remote_status']+'. Keine Nachricht versendet.'))
        self.wizard._run_async(execute,result_handler=done)

    def withdraw(self):self.perform({'tokens','quarantines'})
    def purge(self):self.perform({'outputs','unassociated-outputs'})

    def restore(self):
        w=self.wizard
        if w.running:return
        profile=self.profile_var.get().strip();identity={'version':1,**{key:var.get().strip() for key,var in self.identity_vars.items()}}
        note=self.note.get().strip()
        if self.confirm.get() is not True or not profile or not 1<=len(note)<=2000:
            w.status.configure(text='Ursprüngliche öffentliche Identität für genau dieses erhaltene Profil prüfen, begründen und bestätigen.');return
        epoch=self.epoch;self.reset_consent();request={'profile':profile,'identity':identity}
        def done(value):
            if not self.fresh(epoch,profile):return
            try:value=response(value,'restore-identity',request=request)
            except (ValueError,TypeError,KeyError):
                self.clear();w.status.configure(text='Ungültigen Identitätsbeleg verworfen; erhaltenes Profil neu prüfen.');return
            self.clear();w.status.configure(text=ERRORS[value['error']] if 'error' in value else
                'Ursprüngliche öffentliche App-Metadaten belegt. Zugangsdaten und Freigaben bleiben unverändert; Belege jetzt neu laden.')
        w._run_async(lambda:owner.restore_identity(profile,identity,note,confirmed=True),result_handler=done)
