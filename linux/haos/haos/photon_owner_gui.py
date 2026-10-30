"""Owner status and retained-source recovery, independent of account activation."""
from copy import deepcopy
import datetime
import json
import math
import time

from . import photon_owner_setup as owner
from .photon_owner_process import response

ERRORS = {'authority-refused': 'Freigabe geändert, Profil noch aktiv oder Prüfbeleg ungültig. Dienst und Auswahl prüfen.',
    'storage-unavailable': 'Privates Journal nicht lesbar. Daten erhalten und Dateirechte beziehungsweise Speicher prüfen.',
    'runtime-unavailable': 'Installierte Verwaltungs-Laufzeit fehlt. Installation prüfen.'}
STATES = {'not-started': 'Noch keine Meldung', 'created': 'Profil vorbereitet', 'connecting': 'Verbindungsaufbau',
    'local-ready': 'Lokaler Transport gestartet', 'upstream-observed': 'Anbietertransport zuletzt beobachtet',
    'disconnected': 'Getrennt', 'closed': 'Geschlossen', 'revoked': 'Freigabe entzogen',
    'authentication-refused': 'Anmeldung abgelehnt', 'identity-refused': 'Konto oder Leitung abgelehnt',
    'cursor-refused': 'Wiederaufnahme vom Anbieter abgelehnt; Owner-Prüfung erforderlich', 'rate-limited': 'Anbieter-Wartefrist',
    'transport-unavailable': 'Verbindung nicht verfügbar', 'source-unavailable': 'Quellbeleg nicht verfügbar',
    'storage-unavailable': 'Privates Journal nicht verfügbar'}


class RecoveryForm:
    def __init__(self, wizard, parent):
        self.wizard = wizard; self.epoch = 0; self.rows = []; self.kind = None; self.loaded = None; self.buttons = {}; self.saved_status = None
        tk = wizard.tk; self.frame = tk.Frame(parent, bg=wizard.PANEL)
        wizard._label(self.frame, 'Photon · aufgezeichneter Status und erhaltene Originale', size=12).pack(anchor='w', pady=5)
        wizard._label(self.frame, 'Der Statusabruf lässt den Dienst laufen. Profil- und Quellenprüfung stoppen den Gateway-Dienst. '
            'Diese Seite richtet kein Photon-Konto ein und erteilt keine Absenderfreigabe.', size=10, color=wizard.MUTED).pack(anchor='w', pady=5)
        self.connector = tk.StringVar(value='phone'); self.profile = tk.StringVar()
        for label, variable in [('Gespeicherte Connector-ID für Status', self.connector), ('Erhaltenes Photon-Profil für Quellenprüfung', self.profile)]:
            entry = wizard._field(self.frame, label); entry.configure(textvariable=variable); variable.trace_add('write', self.clear)
        for key, label in [('status', 'Aufgezeichneten Status lesen'), ('profiles', 'Erhaltene Profile auflisten'), ('sources', 'Originale des ausgewählten Profils prüfen')]:
            self.button(key, label, lambda key=key: self.load(key))
        self.auth_confirm = tk.BooleanVar(value=False)
        tk.Checkbutton(self.frame, text='Den geprüften Anmeldefehler für einen erneuten lokalen Versuch freigeben; Wartefrist erhalten',
            variable=self.auth_confirm, bg=wizard.PANEL, fg=wizard.TEXT, selectcolor=wizard.BG,
            wraplength=wizard.label_wrap, justify='left').pack(anchor='w', pady=4)
        self.button('retry-auth', 'Geprüften Anmeldeversuch erneut erlauben', self.retry_auth)
        self.list = tk.Listbox(self.frame, height=5, exportselection=False, bg=wizard.BG, fg=wizard.TEXT)
        self.list.pack(fill='x', pady=4); self.list.bind('<<ListboxSelect>>', self.selected)
        self.expand = tk.BooleanVar(value=False)
        tk.Checkbutton(self.frame, text='Prüfdetails aufklappen', variable=self.expand, command=self.toggle,
            bg=wizard.PANEL, fg=wizard.TEXT, selectcolor=wizard.BG).pack(anchor='w')
        self.detail_slot = tk.Frame(self.frame, bg=wizard.PANEL); self.detail_slot.pack(fill='x')
        self.details = tk.Text(self.detail_slot, height=7, wrap='word', bg=wizard.BG, fg=wizard.TEXT, state='disabled')
        self.note = wizard._field(self.frame, 'Nicht geheime Prüfbegründung, ohne Zugangsdaten')
        self.confirm = tk.BooleanVar(value=False)
        tk.Checkbutton(self.frame, text='Genau dieses geprüfte Original nach Entzug seiner Freigabe lokal bereinigen', variable=self.confirm,
            bg=wizard.PANEL, fg=wizard.TEXT, selectcolor=wizard.BG, wraplength=wizard.label_wrap, justify='left').pack(anchor='w', pady=4)
        self.button('purge', 'Ausgewähltes entzogenes Original bereinigen', self.purge)
        wizard._label(self.frame, 'Prüfbelege und Wiederholungsschutz bleiben erhalten. Entfernte Nachrichten, andere lokale Kopien, '
            'WAL und Backups werden damit nicht gelöscht. Ein vom Anbieter abgelehnter Cursor bleibt gesperrt. '
            'Nach der Prüfung den Gateway-Dienst bewusst wieder starten.', size=10, color=wizard.MUTED).pack(anchor='w', pady=5)

    def button(self, key, label, action):
        button = self.wizard._button(self.frame, label, action); button.configure(wraplength=max(180, self.wizard.label_wrap - 50), justify='left')
        button.pack(anchor='w', pady=3); self.buttons[key] = button

    def toggle(self):
        if self.expand.get(): self.details.pack(fill='x', pady=4)
        else: self.details.pack_forget()

    def render(self, value):
        self.details.configure(state='normal'); self.details.delete('1.0', self.wizard.tk.END)
        if value is not None: self.details.insert('1.0', json.dumps(value, ensure_ascii=False, indent=2))
        self.details.configure(state='disabled')

    def consent(self):
        self.confirm.set(False); self.note.delete(0, self.wizard.tk.END)
        self.auth_confirm.set(False)

    def clear(self, *_args):
        self.epoch += 1; self.rows = []; self.kind = None; self.loaded = None; self.saved_status = None
        if hasattr(self, 'list'): self.list.delete(0, self.wizard.tk.END); self.render(None); self.consent()

    def fresh(self, epoch, connector, profile):
        return epoch == self.epoch and connector == self.connector.get().strip() and profile == self.profile.get().strip() and bool(self.frame.winfo_exists())

    def selected(self, *_args):
        self.epoch += 1; self.consent(); indices = self.list.curselection()
        if not indices or indices[0] >= len(self.rows): return
        row = self.rows[indices[0]]
        if self.kind == 'profiles':
            self.profile.set(row); self.wizard.status.configure(text='Profil ausgewählt. Originale jetzt frisch prüfen.')
        else: self.render(row)

    def load(self, kind):
        w = self.wizard
        if w.running: return
        connector = self.connector.get().strip(); profile = self.profile.get().strip(); self.clear(); epoch = self.epoch
        if kind == 'sources' and not profile: w.status.configure(text='Zuerst ein erhaltenes Profil auswählen.'); return
        request = {'profile': profile} if kind == 'sources' else {}
        def execute():
            value = owner.status(connector) if kind == 'status' else owner.profiles() if kind == 'profiles' else owner.sources(profile)
            if kind == 'status':
                # The Root backend derives the secret fingerprint. The UI never
                # reads it or accepts a status for another connector.
                value = response(value, kind, None)
                if 'error' not in value and value['result']['connector'] != connector: raise ValueError('selected Photon connector changed')
                return value
            return response(value, kind, request)
        def done(value):
            if not self.fresh(epoch, connector, profile): return
            if 'error' in value: w.status.configure(text=ERRORS[value['error']]); return
            self.kind = kind; self.loaded = profile
            if kind == 'status':
                result = value['result']; self.saved_status = deepcopy(result); self.render(result)
                updated = 'keine Meldung' if result['updated_at'] is None else datetime.datetime.fromtimestamp(result['updated_at'], datetime.timezone.utc).isoformat()
                delay = max(0, math.ceil(result['next_attempt'] - time.time()))
                w.status.configure(text=STATES[result['status']] + '. Stand: ' + updated + '. Wartefrist: ' + str(delay)
                    + ' s. Aufgezeichnete Meldung, keine Live-Prüfung. Dienststatus separat prüfen.'); return
            self.rows = deepcopy(value['profiles'] if kind == 'profiles' else value['sources'])
            for row in self.rows:
                label = row if kind == 'profiles' else row['message_id'] + ' · ' + {'retained': 'erhalten', 'purged': 'bereinigt', 'damaged': 'beschädigt'}[row['state']]
                self.list.insert(w.tk.END, label)
            w.status.configure(text='Lokale Prüfbelege geladen; keine Nachricht versendet.' + (' Weitere Belege vorhanden.' if value['history_truncated'] else ''))
        w._run_async(execute, result_handler=done)

    def retry_auth(self):
        w = self.wizard
        if w.running: return
        connector = self.connector.get().strip(); profile = self.profile.get().strip()
        try:
            if (self.kind != 'status' or self.saved_status is None or self.saved_status['connector'] != connector
                    or self.saved_status['status'] not in {'authentication-refused', 'identity-refused'}):
                raise ValueError('Zuerst den aktuellen Anmeldefehler dieses Connectors frisch laden.')
            note = self.note.get().strip()
            if self.auth_confirm.get() is not True or not 1 <= len(note) <= 2000:
                raise ValueError('Anmeldeversuch gesondert bestätigen und nicht geheime Prüfbegründung eingeben.')
            observed = deepcopy(self.saved_status)
        except ValueError as error: w.status.configure(text=str(error)); return
        self.clear(); epoch = self.epoch
        def execute():
            return response(owner.retry_auth(connector, observed, note, confirmed=True), 'auth-retry', {'connector': connector})
        def done(value):
            if not self.fresh(epoch, connector, profile): return
            if 'error' in value: w.status.configure(text=ERRORS[value['error']]); return
            if value['recorded_decision_replayed']:
                w.status.configure(text='Frühere Entscheidung bereits gespeichert. Kein neuer Versuch freigegeben; aktuellen Status erneut prüfen.')
            else:
                w.status.configure(text='Erneuter Anmeldeversuch lokal freigegeben. Wartefrist erhalten; keine Anmeldung geprüft. Gateway danach bewusst starten.')
        w._run_async(execute, result_handler=done)

    def purge(self):
        w = self.wizard
        if w.running: return
        try:
            indices = self.list.curselection(); profile = self.profile.get().strip(); connector = self.connector.get().strip()
            if self.kind != 'sources' or self.loaded != profile or not indices or indices[0] >= len(self.rows): raise ValueError('Original frisch prüfen und auswählen.')
            row = deepcopy(self.rows[indices[0]]); note = self.note.get().strip()
            if row['purge_allowed'] is not True or row['state'] != 'retained': raise ValueError('Zuerst die ursprüngliche Freigabe entziehen; beschädigte Belege gesondert prüfen.')
            if self.confirm.get() is not True or not 1 <= len(note) <= 2000: raise ValueError('Aktuellen Beleg bestätigen und nicht geheime Begründung eingeben.')
        except ValueError as error: w.status.configure(text=str(error)); return
        self.clear(); epoch = self.epoch
        def execute(): return response(owner.purge(profile, row['id'], row['snapshot_sha256'], note, confirmed=True), 'purge-source', {'id': row['id']})
        def done(value):
            if not self.fresh(epoch, connector, profile): return
            self.clear()
            w.status.configure(text=ERRORS[value['error']] if 'error' in value else 'Original lokal bereinigt. Prüfbeleg erhalten; keine entfernte Löschung und keine Nachricht.')
        w._run_async(execute, result_handler=done)
