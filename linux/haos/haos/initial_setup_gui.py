"""Dedicated native graphical *local root seat* HAOS setup, not a web/agent API.

A separate X server with disabled TCP and the physical owner-seat gate is
required. Real UEFI/BIOS and input-device acceptance remains separate.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import initial_setup
from .setup_errors import describe_error
from .hermes_capabilities import provider_rows, gateway_rows
from .provider_registry import http_providers, default_mode, oauth_providers, descriptor, account_providers
from .provider_cloud import CLOUD


def session_allowed(env=None, uid=None):
    env = os.environ if env is None else env
    uid = os.geteuid() if uid is None else uid
    return (uid == 0 and env.get("HAOS_TRUSTED_SETUP") == "1"
            and env.get("DISPLAY") == ":8"
            and not any(env.get(k) for k in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"))
            and not env.get("WAYLAND_DISPLAY"))


class Wizard:
    BG = "#071226"
    PANEL = "#11213c"
    PANEL2 = "#172c49"
    BORDER = "#285473"
    CYAN = "#65e4ff"
    TEXT = "#eaf5ff"
    MUTED = "#a7bdd5"

    def __init__(self, tk):
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("HAOS — Administrator Setup")
        self.root.configure(bg=self.BG)
        # The dedicated root Xorg seat intentionally runs WITHOUT a window
        # manager. Tk's -fullscreen is only an EWMH window-manager hint:
        # without one, Tk remains at its tiny requested widget size in the
        # upper-left corner. Set real X screen geometry directly and make the
        # window override-redirect so there are no decorations or WM requests.
        # Use the reported X screen dimensions; never hard-code an HP model.
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.overrideredirect(True)
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")
        self.root.attributes("-fullscreen", True)
        self.compact = screen_w < 900 or screen_h < 600
        self.label_wrap = max(220, min(780, screen_w - (225 if self.compact else 390)))
        self.root.minsize(min(560, screen_w), min(380, screen_h))
        self.root.bind("<Control-Alt-F12>", lambda _event: self.root.destroy())
        self.page = "security"
        self.codes = []
        self.codes_confirmed = False
        self.owner_username = ""
        self.variables = {}
        self.running = False
        self._build()

    def _label(self, parent, text, *, size=12, color=None, bold=False, wrap=800):
        return self.tk.Label(parent, text=text, font=("DejaVu Sans", size, "bold" if bold else "normal"),
                             fg=color or self.TEXT, bg=parent.cget("bg"),
                             anchor="w", justify="left", wraplength=min(wrap, self.label_wrap))

    def _button(self, parent, text, action, *, primary=False):
        return self.tk.Button(parent, text=text, command=action, relief="flat", bd=0, padx=17, pady=11,
                              bg=self.CYAN if primary else self.PANEL2,
                              fg=self.BG if primary else self.TEXT,
                              activebackground="#9df1ff" if primary else self.BORDER,
                              font=("DejaVu Sans", 11, "bold"), cursor="hand2")

    def _field(self, parent, label, default="", *, secret=False):
        self._label(parent, label, size=10, color=self.MUTED).pack(anchor="w", pady=(14, 4))
        entry = self.tk.Entry(parent, bg=self.PANEL2, fg=self.TEXT, relief="flat", bd=0,
                              insertbackground=self.CYAN, highlightthickness=1,
                              highlightbackground=self.BORDER, highlightcolor=self.CYAN,
                              font=("DejaVu Sans", 13), show="•" if secret else "")
        entry.insert(0, default)
        entry.pack(fill="x", ipady=10)
        return entry

    def _choice(self, parent, label, items, default, *, width=None):
        self._label(parent, label, size=10, color=self.MUTED).pack(anchor="w", pady=(14, 4))
        value = self.tk.StringVar(value=default)
        control = self.tk.OptionMenu(parent, value, *items)
        control.configure(bg=self.PANEL2, fg=self.TEXT, activebackground=self.BORDER,
                          activeforeground=self.TEXT, highlightthickness=0,
                          relief="flat", bd=1, font=("DejaVu Sans", 11))
        if width is not None:
            control.configure(width=width, anchor="w")
        control["menu"].configure(bg=self.PANEL2, fg=self.TEXT, activebackground=self.BORDER,
                                   activeforeground=self.TEXT, font=("DejaVu Sans", 11))
        control.pack(anchor="w")
        return value

    def _catalogue(self, heading, rows):
        """Display pinned upstream availability without granting adapter authority."""
        shell = self.tk.Frame(self.content, bg=self.PANEL)
        shell.pack(fill="x", pady=(14, 12))
        details = self.tk.Frame(shell, bg=self.PANEL2)
        opened = False

        def toggle():
            nonlocal opened
            opened = not opened
            if opened:
                details.pack(fill="x", pady=(5, 0))
                for child in details.winfo_children():
                    child.destroy()
                for name, status in rows:
                    self._label(details, f"{name} — {status}", size=10,
                                color=self.CYAN if status == "GUI" else self.MUTED).pack(
                                    anchor="w", padx=9, pady=2)
            else:
                details.pack_forget()
            control.configure(text=heading + (" ▲" if opened else " ▼"))

        control = self.tk.Button(shell, text=heading + " ▼", command=toggle, bg=self.PANEL2,
                                 fg=self.CYAN, relief="flat", activebackground=self.BORDER,
                                 activeforeground=self.TEXT, font=("DejaVu Sans", 10, "bold"))
        control.pack(anchor="w", fill="x")
        return shell

    def _build(self):
        tk = self.tk
        layout = tk.Frame(self.root, bg=self.BG)
        layout.pack(fill="both", expand=True, padx=13 if self.compact else 45,
                    pady=12 if self.compact else 32)
        sidebar = tk.Frame(layout, bg=self.BG, width=155 if self.compact else 225)
        sidebar.pack(side="left", fill="y", padx=(0, 10 if self.compact else 28))
        sidebar.pack_propagate(False)
        self._label(sidebar, "◇ HAOS", size=27, color=self.CYAN, bold=True).pack(anchor="w", pady=(0, 8))
        self._label(sidebar, "ADMINISTRATOR SETUP", size=9, color=self.MUTED).pack(anchor="w", pady=(0, 28))
        items = [("security", "01  Administrator"),
                 ("user", "02  Normaler Benutzer"),
                 ("region", "03  Sprache / Tastatur"),
                 ("provider", "04  Hermes / Models"),
                 ("updates", "05  Updates / GHCR"),
                 ("gateways", "06  Gateways"),
                 ("finish", "07  Abschluss")]
        for name, title in items:
            self._button(sidebar, title, lambda p=name: self.show(p)).pack(fill="x", pady=5)
        self._label(sidebar, "LOCAL ROOT SETUP\nKein Fernzugriff und keine Agent-Rechte.",
                    size=9, color=self.MUTED, wrap=190).pack(side="bottom", anchor="w", pady=10)
        self.card = tk.Frame(layout, bg=self.PANEL,
                             padx=12 if self.compact else 34,
                             pady=12 if self.compact else 28,
                             highlightthickness=1, highlightbackground=self.BORDER)
        self.card.pack(side="left", fill="both", expand=True)
        self.status = self._label(self.card, "", size=10, color=self.MUTED)
        self.status.pack(side="bottom", fill="x", pady=(15, 0))
        self.error_panel = tk.Frame(self.card, bg=self.PANEL2)
        self.error_panel.pack(side="bottom", fill="x")
        # Scroll the card, not the desktop: keyboard-only users and small
        # firmware framebuffers must still reach every credential field.
        self.viewport = tk.Canvas(self.card, bg=self.PANEL, bd=0,
                                  highlightthickness=0)
        scrollbar = tk.Scrollbar(self.card, orient="vertical",
                                 command=self.viewport.yview)
        self.viewport.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.viewport.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.viewport, bg=self.PANEL)
        self.content_window = self.viewport.create_window(
            (0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _e: self.viewport.configure(
            scrollregion=self.viewport.bbox("all")))
        self.viewport.bind("<Configure>", lambda e: self.viewport.itemconfigure(
            self.content_window, width=e.width))
        self.root.bind_all("<MouseWheel>", lambda e: self.viewport.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))
        self.root.bind_all("<Button-4>", lambda _e: self.viewport.yview_scroll(-1, "units"))
        self.root.bind_all("<Button-5>", lambda _e: self.viewport.yview_scroll(1, "units"))
        self.root.bind_all("<Next>", lambda _e: self.viewport.yview_scroll(1, "pages"))
        self.root.bind_all("<Prior>", lambda _e: self.viewport.yview_scroll(-1, "pages"))
        self.show("security")

    def _head(self, title, subtitle):
        self._label(self.content, title, size=23, bold=True, wrap=770).pack(anchor="w", pady=(0, 8))
        self._label(self.content, subtitle, size=11, color=self.MUTED,
                    wrap=800).pack(anchor="w", pady=(0, 23))

    def _clear_error(self):
        for child in self.error_panel.winfo_children():
            child.destroy()

    def _show_error(self, report):
        self._clear_error()
        self.status.config(text=report.title, fg="#ffafba")
        self._label(self.error_panel, report.title, size=11, color="#ffafba").pack(
            fill="x", padx=8, pady=(5, 2))
        details = self._label(self.error_panel, report.details, size=9, color=self.TEXT)
        details_open = False

        def toggle():
            nonlocal details_open
            details_open = not details_open
            toggle_button.config(text=("Technische Details ausblenden ▲" if details_open
                                       else "Technische Details anzeigen ▼"))
            if details_open:
                details.pack(fill="x", padx=8, pady=(3, 8))
            else:
                details.pack_forget()

        toggle_button = self.tk.Button(
            self.error_panel, text="Technische Details anzeigen ▼", command=toggle,
            bg=self.PANEL2, fg=self.CYAN, relief="flat", bd=0,
            activebackground=self.PANEL2, activeforeground=self.TEXT)
        toggle_button.pack(anchor="w", padx=8, pady=(0, 5))

    def _run(self, action, *, success="Gespeichert."):
        if self.running:
            self.status.config(text="Warte, bis die laufende Systemaktion beendet ist.", fg=self.MUTED)
            return None
        self._clear_error()
        self.status.config(text="Wird sicher angewendet …", fg=self.MUTED)
        self.root.update_idletasks()
        try:
            result = action()
        except Exception as error:
            self._show_error(describe_error(error, area=self.page))
            return None
        self.status.config(text=success, fg=self.CYAN)
        return result

    def _run_async(self, action, *, success="Gespeichert.", completed=None, result_handler=None):
        """Keep Tk's event loop responsive during authenticated slow system actions.

        Exactly one privileged mutation can be underway. No worker thread
        touches Tk; it reports only sanitized success/failure through a queue.
        """
        import queue
        import threading
        if self.running:
            self.status.config(text="Bitte warte, bis die aktuelle Systemaktion abgeschlossen ist.")
            return
        self.running = True
        self._clear_error()
        self.status.config(text="Aktion läuft … Netzwerk und Datenträger können Zeit benötigen.",
                           fg=self.CYAN)
        results = queue.Queue(maxsize=1)

        def worker():
            try:
                result = action()
                results.put((True, result if result_handler is not None else None))
            except Exception as error:
                results.put((False, describe_error(error, area=self.page)))

        threading.Thread(target=worker, daemon=True, name="haos-setup-action").start()

        def poll():
            try:
                ok, report = results.get_nowait()
            except queue.Empty:
                self.root.after(150, poll)
                return
            self.running = False
            if completed is not None:
                completed()
            if ok:
                self.status.config(text=success, fg=self.CYAN)
                if result_handler is not None:
                    try:
                        result_handler(report)
                    except Exception as error:
                        self._show_error(describe_error(error, area=self.page))
            else:
                self._show_error(report)
        self.root.after(150, poll)

    def show(self, name):
        tk = self.tk
        if self.running:
            self.status.config(text="Bitte warte, bis die aktuelle Systemaktion abgeschlossen ist.")
            return
        self.page = name
        self.viewport.yview_moveto(0)
        for child in self.content.winfo_children():
            child.destroy()
        self.status.config(text="", fg=self.MUTED)
        self._clear_error()
        if name == "security":
            self._head("Administrator & Wiederherstellung",
                       "Ein separates Administrator-Konto, niemals das Hermes-Konto. Zugangsdaten bleiben auf diesem Gerät.")
            status = self._run(initial_setup.account_status, success="")
            if status is None:
                return
            if not status["owner"]:
                if status.get("pending", False) or initial_setup.setup_in_progress():
                    self._label(self.content,
                        "Ein früherer Einrichtungsversuch wurde unterbrochen, bevor ein Administratorkonto entstand.",
                        size=11, color="#ffafba").pack(anchor="w", pady=5)
                    def clear_interrupted():
                        result = self._run(initial_setup.retry_failed_new_enrollment,
                                           success="Unterbrochenen Versuch sicher zurückgesetzt.")
                        if result is not None:
                            self.show("security")
                    self._button(self.content, "Unterbrochenen Versuch sicher zurücksetzen",
                                 clear_interrupted).pack(anchor="w", pady=8)
                    return
                username = self._field(self.content, "Administrator-Benutzername (klein geschrieben)")
                password = self._field(self.content, "Passwort · mindestens 20 Zeichen", secret=True)
                repeated = self._field(self.content, "Passwort wiederholen", secret=True)
                def create():
                    name = username.get()
                    secret, confirm = password.get(), repeated.get()
                    password.delete(0, tk.END)
                    repeated.delete(0, tk.END)
                    result = self._run(lambda: initial_setup.create_initial_owner(name, secret, confirm),
                                       success="Administrator erstellt. Wiederherstellungscodes unbedingt sichern.")
                    if result is not None:
                        self.owner_username, self.codes = result
                        self.codes_confirmed = False
                        self.show("security")
                self._button(self.content, "Administrator sicher erstellen", create, primary=True).pack(anchor="w", pady=22)
            elif self.codes and not self.codes_confirmed:
                self._label(self.content, "Einmalige Wiederherstellungscodes — JETZT sichern!",
                            size=14, color=self.CYAN, bold=True).pack(anchor="w")
                box = tk.Text(self.content, height=11, width=46,
                              font=("DejaVu Sans Mono", 9 if self.compact else 10),
                              bg=self.BG, fg=self.TEXT, bd=0, padx=12, pady=8)
                box.insert("1.0", "\n".join(self.codes))
                box.configure(state="disabled")
                box.pack(fill="x", pady=12)
                from tkinter import messagebox
                def accept():
                    if messagebox.askyesno("Recovery", "Sind alle zehn Codes sicher außerhalb des PCs gespeichert?"):
                        result = self._run(lambda: initial_setup.acknowledge_recovery(self.owner_username),
                                           success="Alle Wiederherstellungscodes bestätigt.")
                        if result is not None:
                            self.codes.clear()
                            self.codes_confirmed = True
                            self.show("region")
                self._button(self.content, "Alle Codes sicher gespeichert", accept, primary=True).pack(anchor="w")
            elif status.get("pending", False):
                self._label(self.content,
                    "Unvollständige Wiederherstellung nach Unterbrechung.",
                    size=14, color="#ffafba", bold=True).pack(anchor="w", pady=12)
                self._label(self.content,
                    "Alte Codes können aus Sicherheitsgründen nicht erneut angezeigt werden. "
                    "Du kannst jetzt alle zehn Codes lokal neu erstellen; alte Codes werden ungültig.",
                    size=11, color=self.MUTED).pack(anchor="w")
                def recover():
                    from .owner_recovery import owners
                    username = owners()[0]["username"]
                    codes = self._run(lambda: initial_setup.rotate_unconfirmed_codes(username),
                                      success="Neue Recovery-Codes erzeugt. Jetzt sicher speichern.")
                    if codes is not None:
                        self.owner_username = username
                        self.codes = codes
                        self.codes_confirmed = False
                        self.show("security")
                self._button(self.content, "Wiederherstellungscodes neu ausgeben",
                             recover, primary=True).pack(anchor="w", pady=18)
            else:
                self._label(self.content, "Administrator bereits angelegt.", size=14, color=self.CYAN).pack(anchor="w", pady=7)
                self._label(self.content,
                    "Bestehende Konten und persönliche Daten bleiben unangetastet. Kein automatischer Reset.",
                    color=self.MUTED).pack(anchor="w")
                if status["owner"] and not status["recovery"]:
                    self._label(self.content, "Für diesen Administrator fehlen Recovery-Codes.", color="#ffafba").pack(anchor="w")
                    def migrate_recovery():
                        from .owner_recovery import owners
                        username = owners()[0]["username"]
                        codes = self._run(lambda: initial_setup.issue_missing_recovery(username),
                                          success="Zehn sichere Recovery-Codes erzeugt.")
                        if codes is not None:
                            self.owner_username = username
                            self.codes = codes
                            self.codes_confirmed = False
                            self.show("security")
                    self._button(self.content, "Bestehendes Konto behalten und Recovery-Codes erstellen",
                                 migrate_recovery, primary=True).pack(anchor="w", pady=18)
        elif name == "user":
            self._head("Normalen Benutzer einrichten",
                       "Separat vom Administrator. Das sichere HAOS-Observerkonto bleibt ohne Root- und sudo-Zugriff.")
            self._label(self.content,
                "HAOS verwendet intern den gesperrten technischen Sitzungskontonamen 'hermes'. "
                "Dein persönlicher Anzeigename erscheint im Desktop; persönliche Dateien "
                "werden bei bestehenden Installationen nicht gelöscht.",
                size=11, color=self.MUTED).pack(anchor="w", pady=10)
            name = self._field(self.content, "Dein Anzeigename (1–64 Zeichen)")
            self._button(self.content, "Benutzerprofil sicher übernehmen",
                         lambda: self._run(lambda: initial_setup.configure_normal_user(name.get()),
                                           success="Anzeigename für die normale HAOS-Sitzung gespeichert."),
                         primary=True).pack(anchor="w", pady=20)
        elif name == "region":
            self._head("Sprache & Tastatur",
                       "System- und Konsolensprache werden mit localectl gesetzt. Änderungen gelten nach neuer Anmeldung.")
            languages = ["de_AT.UTF-8", "de_DE.UTF-8", "en_US.UTF-8", "en_GB.UTF-8", "fr_FR.UTF-8"]
            language = self._choice(self.content, "Systemsprache", languages, "de_AT.UTF-8")
            keyboard = self._choice(self.content, "Tastaturlayout", ["at", "de", "us", "gb", "fr", "ch"], "at")
            self._button(self.content, "Sprache und Tastatur übernehmen",
                         lambda: self._run(lambda: initial_setup.configure_region(language.get(), keyboard.get())),
                         primary=True).pack(anchor="w", pady=24)
        elif name == "provider":
            self._head("Hermes · Provider & Modell",
                       "Zugangsdaten bleiben im getrennten Provider-Dienst. Wähle anschließend ein Modell deines Anbieters.")
            provider = self._choice(self.content, "Provider", sorted(http_providers() | oauth_providers() | CLOUD | {"local", "lmstudio", "gemini", "custom", "copilot", "copilot-acp"}), "openai-api")
            model = self._field(self.content, "Modellkennung, vom Provider unterstützt")
            endpoint = self._field(self.content, "URL · leer = Standard des Anbieters")
            mode = self._choice(self.content, "Protokoll · automatisch oder explizit für Modell-/Abo-Varianten",
                                ["auto", "chat_completions", "codex_responses", "anthropic_messages"], "auto")
            secret = self._field(self.content, "API-Schlüssel · nicht gespeichert im GUI", secret=True)
            selection_generation = 0
            model_rows = []
            catalog_status = self._label(self.content, "Modellkennung direkt eingeben oder den Provider-Katalog laden.",
                                         size=10, color=self.MUTED)
            catalog_status.pack(anchor="w", pady=(12, 0))
            model_filter = self._field(self.content, "Modellliste filtern")
            model_frame = tk.Frame(self.content, bg=self.PANEL)
            model_frame.pack(fill="x", pady=5)
            model_list = tk.Listbox(model_frame, height=6, bg=self.PANEL2, fg=self.TEXT,
                selectbackground=self.CYAN, selectforeground=self.BG, relief="flat", exportselection=False,
                font=("DejaVu Sans", 11))
            model_scroll = tk.Scrollbar(model_frame, orient="vertical", command=model_list.yview)
            model_list.configure(yscrollcommand=model_scroll.set)
            model_scroll.pack(side="right", fill="y")
            model_list.pack(side="left", fill="both", expand=True)
            def filter_models(_event=None):
                query = model_filter.get().casefold()
                model_list.delete(0, tk.END)
                for row in model_rows:
                    if query in row["id"].casefold():
                        model_list.insert(tk.END, row["id"])
            model_filter.bind("<KeyRelease>", filter_models)
            def choose_model(_event=None):
                if model_list.curselection():
                    selected = model_list.get(model_list.curselection()[0])
                    model.delete(0, tk.END)
                    model.insert(0, selected)
                    mode.set(next(row["api_mode"] for row in model_rows if row["id"] == selected))
            model_list.bind("<<ListboxSelect>>", choose_model)
            def show_models(value):
                from .provider_discovery import validate_catalog
                validate_catalog(value, provider.get())
                model_rows[:] = value["models"]
                source = ("Model Garden · Projektfreigabe und Inferenz nicht geprüft" if value["diagnostic"] == "publisher-catalog" else "Provider-Katalog · Inferenz noch nicht geprüft" if value["source"] in {"provider-api", "sdk-catalog"}
                          else "Upstream-Vorschläge · Konto und Verfügbarkeit nicht bestätigt" if value["source"] == "upstream-offline"
                          else "Kein Katalog verfügbar · Konto/URL prüfen oder Modellkennung direkt eingeben")
                catalog_status.config(text=source + " · " + str(len(model_rows)) + " Modelle")
                filter_models()
            def load_models():
                snapshot = provider.get(), secret.get(), endpoint.get(), mode.get(), model.get()
                selected, key, url, wire, chosen_model = snapshot
                def receive(value):
                    if self.page != "provider":
                        return
                    if (provider.get(), secret.get(), endpoint.get(), mode.get(), model.get()) == snapshot:
                        show_models(value)
                    else:
                        self.status.config(text="Konfiguration geändert · Modellliste erneut laden.", fg=self.MUTED)
                if selected == "local" and not url:
                    url = "http://127.0.0.1:11434/v1"
                self._run_async(lambda: initial_setup.provider_models(selected, key, url, "" if wire == "auto" else wire, chosen_model),
                                success="Modellkatalog geladen. Auswahl gibt noch keine Inferenz frei.", result_handler=receive)
            self._button(self.content, "Modellliste laden", load_models).pack(anchor="w", pady=8)
            self._label(self.content,
                "Cloud-SDKs: AWS erwartet JSON mit access_key_id / secret_access_key (optional session_token), profile oder bearer_token. "
                "Vertex erwartet Service-Account-/Authorized-User-JSON und die vollständige OpenAPI-URL. "
                "Azure akzeptiert einen API-Key oder JSON mit tenant_id / client_id / client_secret. "
                "Ein leeres Cloud-Feld verwendet ausschließlich die SDK-Identität des getrennten Provider-Dienstes.",
                size=10, color=self.MUTED).pack(anchor="w", pady=8)
            def import_cloud_file():
                if self.running:
                    return
                from tkinter import filedialog
                selected, generation = provider.get(), selection_generation
                filename = filedialog.askopenfilename(parent=self.root, title="Private Cloud-Zugangsdaten auswählen",
                    filetypes=[("JSON-Zugangsdaten", "*.json")])
                if not filename:
                    return
                secret.delete(0, tk.END)
                def imported(value):
                    if generation == selection_generation and provider.get() == selected and secret.winfo_exists():
                        secret.insert(0, value)
                    else:
                        self.status.config(text="Provider-Auswahl geändert; importierte Zugangsdaten verworfen.")
                self._run_async(lambda: initial_setup.import_cloud_credential(selected, filename),
                    success="Private Cloud-Datei in das verdeckte Eingabefeld übernommen. Noch keine Konfiguration oder Inferenz.",
                    result_handler=imported)
            cloud_file_button = self._button(self.content, "Private Cloud-JSON-Datei auswählen", import_cloud_file)
            cloud_file_button.pack(anchor="w", pady=6)
            def account(action):
                if self.running:
                    return
                selected_provider = provider.get()
                account_options = {"endpoint": endpoint.get()} if selected_provider == "minimax-oauth" else {}
                self.root.withdraw()
                self._run_async(lambda: initial_setup.provider_account(selected_provider, action, **account_options),
                                success=("Kontostatus bestätigt. Keine Inferenz geprüft." if action == "status" else
                                         "Konto-Aktion abgeschlossen. Provider anschließend konfigurieren."),
                                completed=self.root.deiconify)
            login_button = self._button(self.content, "Mit Anbieter-Konto anmelden (OAuth / Device-Code)",
                                        lambda: account("login"))
            login_button.pack(anchor="w", pady=8)
            logout_button = self._button(self.content, "Anbieter-Konto abmelden", lambda: account("logout"))
            logout_button.pack(anchor="w", pady=4)
            status_button = self._button(self.content, "Anbieter-Kontostatus prüfen", lambda: account("status"))
            status_button.pack(anchor="w", pady=4)
            self._label(self.content, "MiniMax-Konto: Für China zuerst URL https://api.minimaxi.com/anthropic eingeben; "
                "Anmeldung, Status und Konfiguration verwenden dieselbe gewählte Region.",
                size=10, color=self.MUTED).pack(anchor="w", pady=4)
            def update_provider(*_args):
                nonlocal selection_generation
                selection_generation += 1
                # An old key must never follow a new provider selection.
                secret.delete(0, tk.END)
                endpoint.delete(0, tk.END)
                model.delete(0, tk.END)
                mode.set("auto")
                model_rows.clear()
                model_list.delete(0, tk.END)
                catalog_status.config(text="Modellkennung direkt eingeben oder den Provider-Katalog laden.")
                available = provider.get() in account_providers()
                cloud_file_button.configure(state="normal" if provider.get() in CLOUD else "disabled")
                for button in (login_button, logout_button, status_button):
                    button.configure(state="normal" if available else "disabled")
            provider.trace_add("write", update_provider)
            update_provider()
            def apply():
                key=secret.get()
                secret.delete(0, tk.END)
                selected_provider, selected_model, selected_endpoint, selected_mode = provider.get(), model.get(), endpoint.get(), mode.get()
                if selected_provider == "local" and not selected_endpoint:
                    selected_endpoint = "http://127.0.0.1:11434/v1"
                self._run_async(lambda: initial_setup.configure_provider(
                    selected_provider, selected_model, key, selected_endpoint,
                    "" if selected_mode == "auto" else selected_mode))
            self._button(self.content, "Provider konfigurieren", apply, primary=True).pack(anchor="w", pady=22)
            configured = self._run(initial_setup.provider_state, success="")
            if configured and configured["routes"]:
                route_ids = [row["id"] for row in configured["routes"]]
                selected_route = self._choice(self.content, "Konfigurierte Route · Standard: " + configured["default"],
                                               route_ids, configured["default"])
                fallbacks = self._field(self.content, "Fallback-Routen in Reihenfolge · IDs durch Komma trennen")
                self._label(self.content, ", ".join(row["id"] + ": " + row["model"] for row in configured["routes"]),
                            size=10, color=self.MUTED).pack(anchor="w", pady=6)
                def route_action(action):
                    route = selected_route.get()
                    targets = [item.strip() for item in fallbacks.get().split(",") if item.strip()]
                    self._run_async(lambda: initial_setup.manage_provider_route(route, action, targets),
                                    success="Provider-Routen aktualisiert.", result_handler=lambda _: self.show("provider"))
                for label, action in (("Als Standard wählen", "default"), ("Fallbacks speichern", "fallbacks"),
                                      ("Route entfernen", "remove")):
                    self._button(self.content, label, lambda action=action: route_action(action)).pack(anchor="w", pady=4)
            self._label(self.content,
                        "Der Hermes-Katalog enthält weitere Anbieter. Ein Katalogeintrag "
                        "ist keine HAOS-Integration: Ungetestete Transport- und OAuth-Verfahren "
                        "werden weder freigeschaltet noch mit Zugangsdaten versorgt.",
                        color=self.MUTED).pack(anchor="w")
            self._catalogue(
                "Alle Provider des eingebundenen Hermes-Stands anzeigen",
                [(label, status) for _slug, label, status in provider_rows()])
            self._label(self.content, "Mixture of Agents · freigegebene Provider kombinieren",
                        size=13, color=self.CYAN, bold=True).pack(anchor="w", pady=(18, 4))
            self._button(self.content, "Gespeicherte Provider-Auswahl neu laden",
                         lambda: self.show("provider")).pack(anchor="w", pady=6)
            self._label(self.content,
                "Ein oder zwei Referenzmodelle liefern Vorschläge. Das Aggregator-Modell führt sie zur Antwort zusammen. "
                "Alle ausgewählten Anbieter erhalten deine Nachricht. Wähle ausschließlich bereits eingerichtete und freigegebene Modelle.",
                size=10, color=self.MUTED).pack(anchor="w")
            moa_options = {}
            for row in (configured or {}).get("routes", []):
                for approved in row.get("models", [row["model"]]):
                    label = row["id"] + " · " + approved
                    moa_options[label] = {"route": row["id"], "model": approved}
            if moa_options:
                moa_name = self._field(self.content, "Name des Modellteams", "personal")
                choices = list(moa_options)
                primary_model = next(row["model"] for row in configured["routes"] if row["id"] == configured["default"])
                primary = next((label for label, slot in moa_options.items()
                    if slot["route"] == configured["default"] and slot["model"] == primary_model), choices[0])
                picker_width = 24 if self.compact else 56
                reference_one = self._choice(self.content, "Referenzmodell 1", choices, choices[0], width=picker_width)
                no_second = "Kein zweites Referenzmodell"
                reference_two = self._choice(self.content, "Referenzmodell 2 · optional", [no_second, *choices], no_second, width=picker_width)
                aggregator = self._choice(self.content, "Aggregator-Modell für die gemeinsame Antwort", choices, primary, width=picker_width)
                def apply_moa():
                    import json
                    selected_name = moa_name.get()
                    references = [moa_options[reference_one.get()]]
                    if reference_two.get() != no_second:
                        references.append(moa_options[reference_two.get()])
                    value = json.dumps({"references": references, "aggregator": moa_options[aggregator.get()]})
                    self._run_async(lambda: initial_setup.configure_moa(selected_name, value),
                                    success="Modellteam als Standard gespeichert. Die ausgewählten Anbieter werden bei neuen Anfragen verwendet.")
                self._button(self.content, "Modellteam als Standard aktivieren", apply_moa).pack(anchor="w", pady=10)
            else:
                self._label(self.content, "Richte zuerst mindestens einen Provider mit einem freigegebenen Modell ein. "
                    "Danach kannst du hier dein Modellteam auswählen.", size=10, color=self.MUTED).pack(anchor="w", pady=10)
        elif name == "updates":
            self._head("HAOS Updates",
                       "Stabiler oder privater Entwicklungszweig. Der vorherige bootc-Stand bleibt für Rollback erhalten.")
            username = self._field(self.content, "GitHub Benutzername (nur privater dev-Kanal)")
            token = self._field(self.content, "GHCR Read-only Token", secret=True)
            def save_token():
                secret = token.get()
                token.delete(0, tk.END)
                selected_username = username.get()
                self._run_async(lambda: initial_setup.configure_ghcr(selected_username, secret),
                          success="Privates GHCR-Login geprüft und geschützt gespeichert.")
            self._button(self.content, "Dev-Token sicher hinterlegen", save_token).pack(anchor="w", pady=14)
            channel = self._choice(self.content, "Update-Kanal", ["stable", "dev"], "stable")
            automatic = tk.BooleanVar(value=False)
            tk.Checkbutton(self.content, text="Updates automatisch herunterladen (Neustart manuell)",
                           variable=automatic, bg=self.PANEL, fg=self.TEXT,
                           selectcolor=self.BG, activebackground=self.PANEL).pack(anchor="w", pady=9)
            def apply_channel():
                selected_channel, selected_automatic = channel.get(), automatic.get()
                self._run_async(lambda: initial_setup.configure_update(selected_channel, selected_automatic),
                                success="Bootc-Update vorbereitet. Neustart nach eigener Freigabe.")
            self._button(self.content, "Kanal wählen und bootc-Image prüfen",
                         apply_channel, primary=True).pack(anchor="w", pady=13)
        elif name == "gateways":
            self._head("Hermes · Gateways",
                       "Verbinde einen Bot und autorisiere nur konkrete Absender. Andere Hermes-Adapter müssen zuerst sicher integriert werden.")
            configured_gateways = self._run(initial_setup.gateway_configuration, success="") or {"connectors": [], "bindings": []}
            process_status = self._label(self.content, "Dienststatus noch nicht geprüft.", size=10, color=self.MUTED)
            process_status.pack(anchor="w", pady=6)
            def render_gateway_status(value):
                process_status.configure(text="Gateway-Dienst: " + value["ActiveState"] + " / " + value["SubState"]
                    + " · Ergebnis: " + value["Result"])
            self._button(self.content, "Gateway-Dienststatus prüfen", lambda: self._run_async(initial_setup.gateway_process_status,
                success="Lokaler Dienststatus aktualisiert. Externe Zustellung wird dadurch nicht bestätigt.",
                result_handler=render_gateway_status)).pack(anchor="w", pady=4)
            for action, label in (("start", "Gateway-Dienst starten"), ("stop", "Gateway-Dienst stoppen")):
                self._button(self.content, label, lambda selected_action=action: self._run_async(
                    lambda: initial_setup.manage_gateway(selected_action), success="Gateway-Dienstaktion abgeschlossen.")).pack(anchor="w", pady=4)
            self._button(self.content, "Unterbrochene Gateway-Konfiguration wiederherstellen", lambda: self._run_async(
                lambda: initial_setup.manage_gateway("recover-configuration"),
                success="Freigegebene Konfiguration wiederhergestellt. Dienstneustart und bei Kontowechsel erneute Absenderkopplung erforderlich.",
                result_handler=lambda _: self.show("gateways"))).pack(anchor="w", pady=4)
            connector = self._field(self.content, "Konnektor-ID (z. B. telegram-main)", "telegram-main")
            connector_value=tk.StringVar(value=connector.get());connector.configure(textvariable=connector_value);connector._haos_public_value=connector_value
            platform = self._choice(self.content, "Plattform", ["telegram", "discord", "slack", "mattermost", "matrix", "ntfy"], "telegram")
            token = self._field(self.content, "Bot-Token / Zugangstoken (geschützte Eingabe)", secret=True)
            slack_credentials = tk.Frame(self.content,bg=self.PANEL)
            app_token = self._field(slack_credentials, "Slack App-Token · xapp- · Socket Mode", secret=True)
            self._label(slack_credentials, "In deiner Slack-App Socket Mode aktivieren und einen App-Token mit connections:write erstellen. "
                "Den Bot mit chat:write, users:read, app_mentions:read und den Verlaufsrechten der verwendeten Gespräche installieren "
                "(channels:history, groups:history, im:history bzw. mpim:history). Events app_mention sowie message.channels, "
                "message.groups, message.im und message.mpim passend abonnieren und den Bot in die freigegebenen Kanäle einladen. "
                "Nach Ausfällen wird genehmigter Verlauf seitenweise ab der Freigabe nachgeladen. Anbieterlimits können das verlangsamen; "
                "über 24 Stunden alte Eingänge werden nur erhalten. Gelöschte Slack-Nachrichten sind nicht wiederherstellbar. "
                "Socket Mode benötigt keinen öffentlichen Webhook oder Signing-Secret. Tokens bleiben im privaten Gateway-Dienst.",
                size=10,color=self.MUTED).pack(anchor="w",pady=6)
            mattermost_credentials = tk.Frame(self.content,bg=self.PANEL)
            mm_server = self._field(mattermost_credentials,'Mattermost HTTPS-Server · optional mit Installationspfad')
            self._label(mattermost_credentials,'Im Mattermost-Server einen Bot mit Token-Zugriff einrichten und in die vorgesehenen Kanäle aufnehmen. '
                'Alternativ einen getrennten Dienstbenutzer mit Personal Access Token verwenden. Der HTTPS-Server muss erreichbar sein und ein '
                'vom System vertrautes Zertifikat verwenden. REST API v4 und WebSocket müssen zugänglich sein; ein öffentlicher HAOS-Webhook ist nicht nötig. '
                'Benutzer-, Kanal-, Team- und optionale Root-Post-ID exakt koppeln. In Kanälen den Bot erwähnen. '
                'Verlauf wird nur innerhalb aktueller Owner-Freigaben nachgeladen; gelöschte Nachrichten und fehlende Leserechte sind echte Grenzen. '
                'Token oder Serverwechsel entzieht bisherige Absenderfreigaben. Medien/Voice und beliebige Plugins sind nicht freigegeben.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            ntfy_credentials=tk.Frame(self.content,bg=self.PANEL)
            ntfy_server=self._field(ntfy_credentials,'ntfy HTTPS-Server · optional mit Installationspfad')
            ntfy_server_value=tk.StringVar(value='');ntfy_server.configure(textvariable=ntfy_server_value);ntfy_server._haos_public_value=ntfy_server_value
            ntfy_topic=self._field(ntfy_credentials,'Exaktes privates ntfy-Topic')
            ntfy_topic_value=tk.StringVar(value='');ntfy_topic.configure(textvariable=ntfy_topic_value)
            self._label(ntfy_credentials,'ntfy kennt keine verlässliche Identität einzelner Absender. Die Freigabe gilt für ALLE Publisher dieses Topics. '
                'Verwende ein privates Topic mit serverseitig geprüften Schreibrechten nur für vertrauenswürdige Publisher. '
                'Ein geheimer Topic-Name allein schützt nicht. Ein getrenntes Dienstkonto mit Lese- und Schreibrechten sowie Zugangstoken '
                'oder Benutzer:Passwort-Zugang wird benötigt. Der HTTPS-Server muss ein vom System vertrautes Zertifikat verwenden; '
                'ein öffentlicher HAOS-Webhook ist nicht nötig. Titel und Anzeigenamen verleihen keine Rechte. '
                'Eingang und Antworten verwenden dasselbe Topic; durchgereichte Echo-Markierungen führen keine Mission aus. '
                'Der Servercache begrenzt die Wiederherstellung: bereits gelöschte oder abgelaufene Nachrichten sind nicht nachladbar. '
                'Medien/Voice, einzelne Nutzerfreigaben und Threads sind nicht freigegeben.',size=10,color=self.MUTED).pack(anchor='w',pady=6)
            def retry_ntfy_auth():
                selected_connector=connector.get()
                self._run_async(lambda:initial_setup.retry_ntfy_gateway_auth(selected_connector),
                    success='Gespeicherte Auth-Sperre geprüft. Gateway bleibt gestoppt; nach Prüfung manuell starten. Keine Nachricht gesendet.')
            self._button(ntfy_credentials,'ntfy-Anmeldung erneut erlauben',retry_ntfy_auth).pack(anchor='w',pady=6)
            self._label(ntfy_credentials,'Nach Korrektur von Konto- oder Topic-Rechten auf dem Server kann diese Owner-Aktion eine gespeicherte '
                '401/403-Sperre aufheben. Cursor, Nachrichten und Freigaben bleiben erhalten. Erst ein anschließender Dienststart '
                'prüft die tatsächliche Anmeldung erneut.',size=10,color=self.MUTED).pack(anchor='w',pady=6)
            matrix_credentials=tk.Frame(self.content,bg=self.PANEL)
            matrix_server=self._field(matrix_credentials,'Matrix HTTPS-Homeserver')
            matrix_user=self._field(matrix_credentials,'Matrix-Konto · @benutzer:server')
            matrix_device=self._field(matrix_credentials,'Bestehende Geräte-ID dieses Zugangstokens')
            matrix_recovery=self._field(matrix_credentials,'Vorhandener Recovery-Schlüssel · optional, geschützt',secret=True)
            self._label(matrix_credentials,'Verwende ein getrenntes Matrix-Dienstkonto mit einem bestehenden festen Gerät und dessen Zugangstoken. '
                'Das freigegebene Absenderkonto muss ein anderes Konto sein. '
                'Der Homeserver benötigt ein vom System vertrautes HTTPS-Zertifikat. Lade das Konto selbst in die gewünschten Räume ein und tritt dort bei; '
                'HAOS tritt unbekannten Einladungen nicht automatisch bei. Konto, Gerät und beide Geräteschlüssel werden tatsächlich geprüft. '
                'Recovery-Material wird nur auf ausdrückliche Eingabe verwendet; vorhandene Schlüssel werden nicht zurückgesetzt. '
                'Kontowechsel oder Tokenänderung entzieht bisherige Freigaben. Medien und Voice sind noch nicht freigegeben.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            def configure():
                secret, app_secret = token.get(), app_token.get()
                matrix_values={'homeserver':matrix_server.get(),'user_id':matrix_user.get(),'device_id':matrix_device.get(),
                    'recovery_key':matrix_recovery.get()}
                token.delete(0, tk.END)
                app_token.delete(0, tk.END)
                matrix_recovery.delete(0,tk.END)
                selected_ntfy_server,selected_ntfy_topic=ntfy_server.get(),ntfy_topic.get()
                if platform.get()=='ntfy':trust_publishers.set(False)
                selected_connector, selected_platform, selected_server = connector.get(), platform.get(), mm_server.get()
                self._run_async(lambda: (initial_setup.configure_gateway(
                    selected_connector, selected_platform, secret, app_secret, selected_server) if selected_platform=='mattermost'
                    else initial_setup.configure_gateway(selected_connector,selected_platform,secret,app_secret,**matrix_values)
                    if selected_platform=='matrix' else initial_setup.configure_gateway(selected_connector,selected_platform,secret,
                        server_url=selected_ntfy_server,topic=selected_ntfy_topic) if selected_platform=='ntfy'
                    else initial_setup.configure_gateway(selected_connector, selected_platform, secret, app_secret)),
                    success="Gateway gespeichert. Bei Token-/Kontowechsel Absender erneut koppeln; anschließend Gateway-Dienst neu starten.")
            configure_button = self._button(self.content, "Gateway sicher anlegen", configure, primary=True)
            configure_button.pack(anchor="w", pady=10)
            def platform_changed(*_args):
                token.delete(0, tk.END);app_token.delete(0, tk.END);mm_server.delete(0,tk.END)
                for field in (matrix_server,matrix_user,matrix_device,matrix_recovery):field.delete(0,tk.END)
                for field in (ntfy_server,ntfy_topic):field.delete(0,tk.END)
                if connector.get() in {'telegram-main','discord-main','slack-main','mattermost-main','matrix-main','ntfy-main'}:
                    connector.delete(0,tk.END);connector.insert(0,platform.get()+'-main')
                if platform.get()=='slack':slack_credentials.pack(fill="x",before=configure_button)
                else:slack_credentials.pack_forget()
                if platform.get()=='mattermost':mattermost_credentials.pack(fill='x',before=configure_button)
                else:mattermost_credentials.pack_forget()
                if platform.get()=='ntfy':
                    ntfy_credentials.pack(fill='x',before=configure_button)
                    existing=configured_gateways.get('ntfy',{}).get(connector.get())
                    if existing:
                        ntfy_server.insert(0,existing['server_url']);ntfy_topic.insert(0,existing['topic'])
                else:ntfy_credentials.pack_forget()
                if platform.get()=='matrix':matrix_credentials.pack(fill='x',before=configure_button)
                else:matrix_credentials.pack_forget()
            platform.trace_add("write",platform_changed)
            self._label(self.content, "Genau einen Absender freigeben", color=self.CYAN,
                        size=13, bold=True).pack(anchor="w", pady=(14, 0))
            binding = self._field(self.content, "Freigabe-ID (z. B. mein-handy)", "my-device")
            sender = self._field(self.content, "Absender-ID aus der jeweiligen Plattform")
            chat = self._field(self.content, "Chat-ID der jeweiligen Plattform")
            scope = self._field(self.content, "Bereich · Discord-Server / Slack-Workspace / Mattermost-Team")
            thread = self._field(self.content, "Thread-ID (leer nur für Nachrichten ohne Thread)")
            identity = self._field(self.content, "HAOS-Identität", "personal")
            matrix_pair=tk.Frame(self.content,bg=self.PANEL)
            peer_device=self._field(matrix_pair,'Matrix-Absendergerät · exakte Geräte-ID')
            peer_ed=self._field(matrix_pair,'Öffentlicher Ed25519-Geräteschlüssel · Base64 ohne Leerzeichen')
            peer_curve=self._field(matrix_pair,'Öffentlicher Curve25519-Geräteschlüssel · Base64 ohne Leerzeichen')
            device_candidates=tk.Frame(matrix_pair,bg=self.PANEL);device_candidates.pack(fill='x')
            def load_matrix_devices():
                selected_connector,selected_sender=connector.get(),sender.get()
                def display_devices(value):
                    if platform.get()!='matrix' or connector.get()!=selected_connector or sender.get()!=selected_sender:
                        self.status.configure(text='Konfiguration geändert; Geräteschlüssel erneut laden.')
                        return
                    for child in device_candidates.winfo_children():child.destroy()
                    if not value['devices']:
                        self._label(device_candidates,'Keine signierten Geräte für dieses Konto gefunden.',size=10,color=self.MUTED).pack(anchor='w')
                        return
                    choices={row['device_id']+' · '+row['ed25519'][:8]:row for row in value['devices']}
                    selected=self._choice(device_candidates,'Gerät vom Homeserver · Signatur geprüft, noch nicht freigegeben',
                        list(choices),next(iter(choices)),width=24 if self.compact else 48)
                    def copy_device(*_args):
                        row=choices[selected.get()]
                        for field,key in ((peer_device,'device_id'),(peer_ed,'ed25519'),(peer_curve,'curve25519')):
                            field.delete(0,tk.END);field.insert(0,row[key])
                    selected.trace_add('write',copy_device);copy_device()
                self._run_async(lambda:initial_setup.matrix_gateway_devices(selected_connector,selected_sender),
                    success='Öffentliche Geräteschlüssel geladen; Gateway-Dienst bleibt gestoppt. Vergleiche den Ed25519-Fingerprint mit dem tatsächlichen Gerät, bevor du es freigibst.',
                    result_handler=display_devices)
            self._button(matrix_pair,'Absendergeräte vom Homeserver laden',load_matrix_devices).pack(anchor='w',pady=4)
            approved_devices=[]
            device_summary=self._label(matrix_pair,'Keine Absendergeräte vorgemerkt.',size=10,color=self.MUTED)
            device_summary.pack(anchor='w',pady=4)
            def add_device():
                from .gateway_matrix_policy import opaque,public_key
                item={'device_id':peer_device.get(),'ed25519':peer_ed.get(),'curve25519':peer_curve.get()}
                if (not opaque(item['device_id']) or item['device_id']=='*' or not public_key(item['ed25519'])
                        or not public_key(item['curve25519']) or len(approved_devices)>=16
                        or any(row['device_id']==item['device_id'] for row in approved_devices)):
                    self._show_error(describe_error(ValueError('Genau eine neue Geräte-ID und beide gültigen öffentlichen Geräteschlüssel eingeben.'),area=self.page))
                    return
                approved_devices.append(item)
                device_summary.configure(text='Vorgemerkte Geräte: '+', '.join(row['device_id'] for row in approved_devices))
                for field in (peer_device,peer_ed,peer_curve):field.delete(0,tk.END)
            self._button(matrix_pair,'Absendergerät zur Freigabe vormerken',add_device).pack(anchor='w',pady=4)
            def clear_devices():
                approved_devices.clear();device_summary.configure(text='Keine Absendergeräte vorgemerkt.')
            self._button(matrix_pair,'Vorgemerkte Geräte verwerfen',clear_devices).pack(anchor='w',pady=4)
            allow_plain=tk.BooleanVar(value=False);mention_required=tk.BooleanVar(value=True)
            for label,variable in [('Unverschlüsselte Nachrichten für diese Freigabe ausdrücklich erlauben',allow_plain),
                    ('Bot muss erwähnt werden',mention_required)]:
                tk.Checkbutton(matrix_pair,text=label,variable=variable,bg=self.PANEL,fg=self.TEXT,
                    selectcolor=self.BG,activebackground=self.PANEL,wraplength=self.label_wrap,justify='left').pack(anchor='w')
            self._label(matrix_pair,'Absender als @benutzer:server, Raum als !raum-ID und optional den exakten Root-Ereignis-Thread ($…) angeben. '
                'Bereich bleibt bei Matrix leer. Lade die signierten Geräteschlüssel vom Homeserver oder trage sie selbst ein. '
                'Vergleiche den Ed25519-Fingerprint mit dem tatsächlichen Absendergerät; dessen geprüfte Signatur bindet auch den Curve25519-Schlüssel. '
                'bevor du es vormerkst. Vormerken allein erteilt keine Rechte: Erst die nachfolgende Freigabe speichert Geräte und Rechte gemeinsam. '
                'Neue oder geänderte Geräte werden nicht automatisch vertraut. Ohne Geräte ist nur ausdrücklich erlaubter Klartext möglich.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            def matrix_pair_changed(*_args):
                clear_devices();allow_plain.set(False);mention_required.set(True)
                for child in device_candidates.winfo_children():child.destroy()
                for field in (peer_device,peer_ed,peer_curve):field.delete(0,tk.END)
                if platform.get()=='matrix':matrix_pair.pack(fill='x',before=pairing_note)
                else:matrix_pair.pack_forget()
            platform.trace_add('write',matrix_pair_changed)
            ntfy_pair=tk.Frame(self.content,bg=self.PANEL)
            trust_publishers=tk.BooleanVar(value=False)
            tk.Checkbutton(ntfy_pair,text='Ich vertraue ALLEN Publishern dieses privaten Topics die gewählten Rechte an',
                variable=trust_publishers,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w').pack(anchor='w')
            self._label(ntfy_pair,'Absender und Chat werden aus dem exakten Topic übernommen. Bereich und Thread bleiben leer. '
                'Alle Publisher teilen die gewählte HAOS-Identität und bei Leserecht deren Missionen. '
                'Keine Berechtigung für einzelne Nutzer wird behauptet. Prüfe die Topic-Schreibrechte auf deinem ntfy-Server.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            previous_ntfy=[False]
            def sync_ntfy_topic(*_args):
                if platform.get()!='ntfy':return
                trust_publishers.set(False)
                for field in (sender,chat):
                    field.configure(state='normal');field.delete(0,tk.END);field.insert(0,ntfy_topic_value.get());field.configure(state='disabled')
            ntfy_topic_value.trace_add('write',sync_ntfy_topic)
            connector_value.trace_add('write',lambda *_args:trust_publishers.set(False))
            ntfy_server_value.trace_add('write',lambda *_args:trust_publishers.set(False))
            def ntfy_pair_changed(*_args):
                trust_publishers.set(False)
                active=platform.get()=='ntfy'
                for field in (scope,thread):
                    field.configure(state='normal')
                    if active or previous_ntfy[0]:field.delete(0,tk.END)
                    if active:field.configure(state='disabled')
                if active:
                    ntfy_pair.pack(fill='x',before=pairing_note);sync_ntfy_topic()
                else:
                    ntfy_pair.pack_forget()
                    if previous_ntfy[0]:
                        for field in (sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                previous_ntfy[0]=active
            platform.trace_add('write',ntfy_pair_changed)
            pairing_note=self._label(self.content, "Die Freigabe gilt nur für diese exakte Kombination. Leere Felder sind keine Platzhalter.",
                        size=10, color=self.MUTED)
            pairing_note.pack(anchor="w", pady=6)
            self._label(self.content, "Discord: Server-ID als Bereich angeben. Für einen Thread dessen ID sowohl als Chat-ID "
                "als auch als Thread-ID eintragen. In Server-Kanälen den Bot direkt erwähnen. "
                "Für Wiederherstellung nach Ausfällen benötigt der Bot Kanalansicht und Nachrichtenverlauf. "
                "Neue Freigaben lesen nur Nachrichten nach ihrer Zeitgrenze nach; alte Freigaben ohne Zeitgrenze "
                "müssen dafür ausdrücklich erneut gekoppelt werden. Automatische neue Threads und native Slash-Menüs sind nicht freigegeben.",
                size=10, color=self.MUTED).pack(anchor="w", pady=6)
            self._label(self.content, "Slack: Benutzer-ID U…/W…, Gesprächs-ID C…/G…/D… und Workspace-ID T… angeben, "
                "auch für Direktnachrichten. Für vorhandene Threads den vollständigen thread_ts-Zeitstempel angeben. "
                "In Kanälen und Gruppen den Bot erwähnen. Leerer Thread bedeutet nur Nachrichten außerhalb eines Threads; "
                "Antworten erzeugen keinen neuen Thread. Medien, native Slash-Menüs und interaktive Slack-Schaltflächen sind nicht freigegeben.",
                size=10,color=self.MUTED).pack(anchor="w",pady=6)
            rights = {}
            for capability, label in (("create", "Missionen erstellen"), ("read", "Eigene Missionen lesen"),
                    ("cancel", "Eigene Missionen abbrechen"), ("answer", "Rückfragen und Freigaben beantworten"),
                    ("pause", "Wartende Missionen pausieren"), ("resume", "Pausierte Missionen fortsetzen")):
                variable = tk.BooleanVar(value=capability in {"create", "read"})
                rights[capability] = variable
                tk.Checkbutton(self.content, text=label, variable=variable, bg=self.PANEL, fg=self.TEXT,
                    selectcolor=self.BG, activebackground=self.PANEL).pack(anchor="w")
            def pair_sender():
                selected = (binding.get(), connector.get(), sender.get(), chat.get(), identity.get(),
                            tuple(key for key, value in rights.items() if value.get()))
                selected_scope, selected_thread = scope.get(), thread.get()
                if platform.get()=='ntfy' and not trust_publishers.get():
                    self._show_error(describe_error(ValueError('Bestätige ausdrücklich das Vertrauen in alle Publisher dieses privaten Topics.'),area=self.page))
                    return
                options=({'matrix_devices':[dict(row) for row in approved_devices],'allow_plaintext':allow_plain.get(),
                    'require_mention':mention_required.get()} if platform.get()=='matrix'
                    else {'trust_topic_publishers':trust_publishers.get(),'ntfy_server_url':ntfy_server.get()} if platform.get()=='ntfy' else {})
                self._run_async(lambda: initial_setup.pair_gateway_sender(*selected, scope=selected_scope, thread=selected_thread,**options),
                                success="Absender und ausgewählte Rechte für die exakte Route gespeichert. Gateway-Neustart erforderlich.")
            self._button(self.content, "Absender mit ausgewählten Rechten freigeben",
                         pair_sender, primary=True).pack(anchor="w", pady=(10, 0))
            if configured_gateways["bindings"]:
                binding_labels = {row["id"] + " · " + row["connector"] + " · " + row["scope"] + " / " + row["thread"]: row["id"]
                    for row in configured_gateways["bindings"]}
                revoked_binding = self._choice(self.content, "Bestehende Absenderfreigabe", list(binding_labels), next(iter(binding_labels)), width=24 if self.compact else 48)
                binding_details = self._label(self.content, "", size=10, color=self.MUTED)
                binding_details.pack(anchor="w", pady=4)
                def show_binding_details(*_args):
                    selected_id = binding_labels[revoked_binding.get()]
                    row = next(row for row in configured_gateways["bindings"] if row["id"] == selected_id)
                    binding_details.configure(text="Absender: " + row["sender"] + " · Chat: " + row["chat"]
                        + " · Identität: " + row["identity"] + " · Rechte: " + ", ".join(row["capabilities"])
                        + (" · Gilt für ALLE Publisher dieses Topics" if any(c["id"]==row["connector"] and c["platform"]=="ntfy"
                            for c in configured_gateways["connectors"]) else ""))
                revoked_binding.trace_add("write", show_binding_details)
                show_binding_details()
                def revoke_binding():
                    selected_id = binding_labels[revoked_binding.get()]
                    self._run_async(lambda: initial_setup.manage_gateway("revoke", selected_id),
                        success="Absenderfreigabe entzogen; Gateway-Dienst gestoppt.", result_handler=lambda _: self.show("gateways"))
                self._button(self.content, "Ausgewählte Absenderfreigabe entziehen", revoke_binding).pack(anchor="w", pady=6)
            if configured_gateways["connectors"]:
                connector_labels = {row["id"] + " · " + row["platform"]: row["id"] for row in configured_gateways["connectors"]}
                removed_connector = self._choice(self.content, "Bestehender Konnektor", list(connector_labels), next(iter(connector_labels)), width=24 if self.compact else 48)
                def remove_connector():
                    selected_id = connector_labels[removed_connector.get()]
                    self._run_async(lambda: initial_setup.manage_gateway("remove", selected_id),
                        success="Konnektor, zugehörige Freigaben und Zugangsdaten entfernt; Gateway-Dienst gestoppt.", result_handler=lambda _: self.show("gateways"))
                self._button(self.content, "Konnektor und Zugangsdaten entfernen", remove_connector).pack(anchor="w", pady=6)
            self._button(self.content, "Gateway-Konfiguration neu laden", lambda: self.show("gateways")).pack(anchor="w", pady=6)
            self._label(self.content, "Gateways · gespeicherte Eingänge wiederherstellen",
                color=self.CYAN, size=13, bold=True).pack(anchor="w", pady=(14, 0))
            self._label(self.content, "Die Prüfung stoppt den Gateway-Dienst. Nur fehlgeschlagene Dekodierung innerhalb von 24 Stunden "
                "und mit unveränderter Absenderfreigabe kann erneut versucht werden. Verwerfen erhält die gespeicherten Daten, "
                "führt sie aber nicht aus. Anschließend den Dienst oben manuell starten.",
                size=10, color=self.MUTED).pack(anchor="w", pady=6)
            recovery_frame = tk.Frame(self.content, bg=self.PANEL)
            recovery_frame.pack(fill="x", pady=4)
            def show_ingress(value):
                for child in recovery_frame.winfo_children(): child.destroy()
                history_labels = {'ready':'Verlaufabruf erfolgreich; keine externe Zustellung bestätigt',
                    'permission-denied':'Zugriff verweigert: Kanal-/Thread-ID, Kanalansicht und Nachrichtenverlauf prüfen',
                    'rate-limited':'Anbieter begrenzt Abrufe; Wiederholung erfolgt nach Neustart',
                    'transport-unavailable':'Verbindung zum Verlauf derzeit nicht verfügbar',
                    'storage-unavailable':'Privates Journal nicht beschreibbar; Datenträger prüfen',
                    'invalid-source':'Verlaufantwort passt nicht zur freigegebenen Quelle'}
                transport_labels={'connecting':'Verbindungsaufbau; noch keine bestätigte WebSocket-Anmeldung',
                    'connected':'WebSocket-Anmeldung bestätigt; keine externe Zustellung abgeleitet',
                    'disconnected':'Verbindung getrennt; Gateway-Dienst nach Prüfung neu starten',
                    'authentication-refused':'Anmeldung abgelehnt: privaten Token und Bot-/Dienstkonto prüfen',
                    'transport-unavailable':'Server/TLS/WebSocket nicht verfügbar; Adresse, Zertifikat und Netzwerk prüfen'}
                for item in value.get('transport',[]):
                    matrix_labels={'created':'Privates Profil vorbereitet; noch nicht verbunden','connecting':'Matrix-Anmeldung wird geprüft',
                        'connected':'Matrix-Anmeldung und Sync bestätigt; keine externe Zustellung abgeleitet',
                        'decode-pending':'Eingänge erhalten; fehlende Schlüssel oder Dekodierung werden erneut geprüft',
                        'rate-limited':'Homeserver begrenzt Anfragen; gespeicherte Wartefrist wird eingehalten',
                        'authentication-refused':'Matrix-Anmeldung abgelehnt; privaten Zugangstoken und Gerät prüfen',
                        'identity-refused':'Konto/Gerät/Schlüssel passen nicht; vorhandene Recovery-Daten bleiben erhalten',
                        'policy-unavailable':'Owner-Freigabe entzogen oder nicht lesbar; keine weitere Ausführung',
                        'transport-unavailable':'Matrix-Verbindung oder privater Speicher nicht verfügbar',
                        'disconnected':'Matrix-Verbindung getrennt','closed':'Privates Matrix-Profil geschlossen; Daten erhalten'}
                    ntfy_labels={'created':'Privates Topic-Profil vorbereitet','connecting':'ntfy-Stream wird angemeldet',
                        'ready':'Topic-Profil bereit','streaming':'Authentifizierter ntfy-Stream offen; keine externe Zustellung abgeleitet',
                        'disconnected':'ntfy-Verbindung getrennt','authentication-denied':'ntfy-Zugang abgelehnt; privaten Token und Topic-Rechte prüfen',
                        'source-unavailable':'ntfy-Topic oder Cache-Cursor nicht verfügbar; Topic und serverseitigen Cache prüfen',
                        'rate-limited':'ntfy begrenzt Anfragen; gespeicherte Wartefrist bleibt erhalten',
                        'transport-unavailable':'ntfy-Server/TLS oder privater Speicher nicht verfügbar',
                        'invalid-stream':'ntfy-Streamformat ungültig; keine unvollständigen Frames ausgeführt',
                        'revoked':'Keine aktuelle Topic-Freigabe; zuerst koppeln oder Entzug prüfen. Keine weitere Ausführung',
                        'closed':'Privates ntfy-Profil geschlossen; vorhandene Daten bleiben erhalten'}
                    labels=matrix_labels if item.get('platform')=='matrix' else ntfy_labels if item.get('platform')=='ntfy' else transport_labels
                    import datetime
                    retry_time=(datetime.datetime.fromtimestamp(item['next_sync']).strftime('%d.%m.%Y %H:%M:%S')
                        if item.get('next_sync',0)>0 else 'keine Wartefrist')
                    extra=(' · erhaltene Sync-Seiten '+str(item['pending_pages'])+' · nächste Anfrage: '+retry_time
                        +' · offene Verlaufslücken '+str(item['history_gaps'])
                        +({'rate-limited':' · Verlauf: Homeserver-Limit; Wartefrist gespeichert',
                            'source-unavailable':' · Verlauf: Berechtigung oder Quelle nicht verfügbar',
                            'transport-unavailable':' · Verlauf: Verbindung nicht verfügbar',
                            'invalid-page':' · Verlauf: ungültige oder wiederholte Seite; Cursor bleibt erhalten',
                            '':''}[item['history_error']])
                        +(' · letzter Fehler: '+matrix_labels[item['last_error']] if item['last_error'] else '')) if item.get('platform')=='matrix' else ''
                    if item.get('platform')=='ntfy':
                        deadline=item.get('next_attempt',0)
                        extra=(' · nächste Anfrage: '+(datetime.datetime.fromtimestamp(deadline).strftime('%d.%m.%Y %H:%M:%S') if deadline>0 else 'keine Wartefrist')
                            +(' · letzter Fehler: '+ntfy_labels[item['last_error']] if item.get('last_error') else ''))
                    self._label(recovery_frame,'Letzter Transportstatus · '+item['connector']+' · '+labels[item['status']]
                        +extra+' · Zeitpunkt '+str(item['updated_at']),size=10,color=self.MUTED).pack(anchor='w',pady=3)
                for history in value.get('history',[]):
                    self._label(recovery_frame, "Verlauf · " + history.get('binding_id',history['binding_digest'][:12]) + " · " + history_labels[history['status']],
                        size=10, color=self.MUTED).pack(anchor="w", pady=3)
                rows = value["ingress"]
                if not rows:
                    self._label(recovery_frame, "Keine weiteren ungeklärten Eingänge.", size=10, color=self.MUTED).pack(anchor="w")
                    return
                choices = {row.get('platform','') + " · " + row["ingress_id"] + " · " + row["state"] + " · Versuch " + str(row["attempt"]): row for row in rows}
                selected = self._choice(recovery_frame, "Gespeicherter Eingang", list(choices), next(iter(choices)), width=24 if self.compact else 48)
                note = self._field(recovery_frame, "Prüfnotiz ohne Geheimnisse · gespeichert wird nur der Hash")
                def decide(decision):
                    from tkinter import messagebox
                    row, evidence = choices[selected.get()], note.get()
                    prompt = "Gespeicherte Nachricht erneut dekodieren und bei gültiger Freigabe ausführen?" if decision == "retry" else "Diesen Eingang von der Ausführung ausschließen und seine Daten erhalten?"
                    if messagebox.askyesno("Gespeicherter Gateway-Eingang", prompt):
                        self._run_async(lambda: initial_setup.reconcile_gateway_ingress(row, decision, evidence),
                            success="Owner-Entscheidung gespeichert. Gateway-Dienst bleibt gestoppt.",
                            result_handler=lambda _: load_ingress())
                self._button(recovery_frame, "Fehlgeschlagene Dekodierung erneut versuchen", lambda: decide("retry")).pack(anchor="w", pady=4)
                self._button(recovery_frame, "Eingang verwerfen · Daten erhalten", lambda: decide("discard")).pack(anchor="w", pady=4)
                self._button(recovery_frame, "Nächste Eingänge anzeigen", lambda: load_ingress(value["next_cursor"])).pack(anchor="w", pady=4)
            def load_ingress(after=0):
                self._run_async(lambda: initial_setup.gateway_ingress(after),
                    success="Private Eingangsmetadaten geladen. Gateway-Dienst bleibt gestoppt.", result_handler=show_ingress)
            self._button(self.content, "Gateway-Dienst stoppen und gespeicherte Eingänge prüfen", load_ingress).pack(anchor="w", pady=6)
            self._label(self.content,"Ausgehende Antworten · ungeklärte Zustellung",color=self.CYAN,
                size=13,bold=True).pack(anchor="w",pady=(14,0))
            self._label(self.content,"Diese Prüfung stoppt Gateway, Controller, Hermes und Provider. Prüfe den tatsächlichen "
                "Empfang in der Plattform. Erneutes Senden ist nur nach bestätigter Nichtzustellung erlaubt. "
                "Verwerfen führt keine weitere Zustellung aus und erhält die gespeicherten Daten.",
                size=10,color=self.MUTED).pack(anchor="w",pady=6)
            delivery_frame=tk.Frame(self.content,bg=self.PANEL);delivery_frame.pack(fill="x",pady=4)
            def show_deliveries(value):
                for child in delivery_frame.winfo_children():child.destroy()
                rows=value['deliveries']
                if not rows:
                    self._label(delivery_frame,"Keine weiteren ungeklärten Zustellungen.",size=10,color=self.MUTED).pack(anchor="w")
                    return
                choices={row['delivery_id']+' · '+row['state']+' · Versuch '+str(row['attempt']):row for row in rows}
                selected=self._choice(delivery_frame,"Gespeicherte Zustellung",list(choices),next(iter(choices)),width=24 if self.compact else 48)
                details=self._label(delivery_frame,"",size=10,color=self.MUTED);details.pack(anchor="w",pady=4)
                def delivery_details(*_args):
                    details.configure(text='Mission: '+choices[selected.get()]['mission_id'])
                selected.trace_add('write',delivery_details);delivery_details()
                receipt=self._field(delivery_frame,"Nur für bestätigt zugestellt · tatsächliche Plattform-Nachrichten-ID")
                note=self._field(delivery_frame,"Prüfnotiz ohne Geheimnisse · gespeichert wird nur der Hash")
                not_delivered=tk.BooleanVar(value=False)
                tk.Checkbutton(delivery_frame,text="Ich habe geprüft: Der vorige Versuch wurde nicht zugestellt",
                    variable=not_delivered,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,
                    activebackground=self.PANEL,wraplength=self.label_wrap,justify='left').pack(anchor="w",pady=4)
                def decide_delivery(decision):
                    from tkinter import messagebox
                    row,evidence,remote_id,confirmation=choices[selected.get()],note.get(),receipt.get(),not_delivered.get()
                    prompts={'delivered':'Zustellung anhand der angegebenen Plattform-ID als bestätigt erfassen?',
                        'retry':'Nach geprüfter Nichtzustellung einen weiteren begrenzten Sendeversuch freigeben?',
                        'discard':'Weitere Zustellung ausschließen und die gespeicherten Daten erhalten?'}
                    if messagebox.askyesno('Ausgehende Gateway-Antwort',prompts[decision]):
                        self._run_async(lambda:initial_setup.reconcile_gateway_delivery(row,decision,evidence,remote_id or None,confirmation),
                            success="Owner-Entscheidung gespeichert. Dienste bleiben gestoppt.",
                            result_handler=lambda _:load_deliveries())
                for decision,label in (('delivered','Anhand Plattform-ID als zugestellt erfassen'),
                        ('retry','Nach bestätigter Nichtzustellung erneut versuchen'),('discard','Weitere Zustellung verwerfen · Daten erhalten')):
                    self._button(delivery_frame,label,lambda selected_decision=decision:decide_delivery(selected_decision)).pack(anchor="w",pady=4)
                self._button(delivery_frame,'Nächste Zustellungen anzeigen',lambda:load_deliveries(value['next_cursor'])).pack(anchor="w",pady=4)
            def load_deliveries(after=0):
                self._run_async(lambda:initial_setup.gateway_deliveries(after),
                    success="Private Zustellmetadaten geladen. Alle Missionsdienste bleiben gestoppt.",result_handler=show_deliveries)
            self._button(self.content,'Missionsdienste stoppen und ungeklärte Zustellungen prüfen',load_deliveries).pack(anchor="w",pady=6)
            self._button(self.content,'Missionsdienste nach Wiederherstellung starten',lambda:self._run_async(initial_setup.resume_runtime,
                success="Dienststart angefordert. Aktuellen Status prüfen; dies bestätigt keine externe Zustellung.")).pack(anchor="w",pady=6)
            self._label(self.content,
                        "Hermes bringt weitere Plattformadapter mit. HAOS erlaubt erst nach "
                        "echter Authentifizierung, Zustellung und Absenderprüfung zusätzliche Gateways.",
                        color=self.MUTED).pack(anchor="w", pady=(15, 0))
            self._catalogue("Alle Hermes-Plattformadapter anzeigen", gateway_rows())
        elif name == "finish":
            self._head("Einrichtung abschließen",
                       "Erst nach Administrator + Recovery kann die normale HAOS-Sitzung sicher starten.")
            status = self._run(initial_setup.account_status, success="")
            if status is None:
                return
            profile = self._run(initial_setup.normal_user_ready, success="")
            ready = status["complete"] and profile is True and not (self.codes and not self.codes_confirmed)
            self._label(self.content,
                "✓ Administrator, Recovery und normaler Benutzer eingerichtet" if ready
                else "Administrator, Wiederherstellungscodes und Anzeigename des normalen Benutzers sind erforderlich.",
                size=14, color=self.CYAN if ready else "#ffafba").pack(anchor="w", pady=12)
            self._label(self.content,
                "Für bestehende HAOS-Installationen ist die Datenmigration getrennt zu testen. "
                "Diese Oberfläche löscht keine Laufwerke und startet keine Fernzugriffs-Dienste.",
                color=self.MUTED).pack(anchor="w")
            if ready:
                def finish():
                    result = self._run(initial_setup.finalize,
                                       success="Einrichtung verifiziert. System wird neu gestartet.")
                    if result is not None:
                        # Explicit user action; no reboot after failed validation.
                        import subprocess
                        self.root.destroy()
                        subprocess.run(["/usr/bin/systemctl", "--no-block", "reboot"],
                                       check=True, timeout=15)
                self._button(self.content, "Einrichtung abschließen und neustarten", finish,
                             primary=True).pack(anchor="w", pady=25)

    def run(self):
        self.root.mainloop()


def main():
    if not session_allowed():
        raise SystemExit("Trusted physical setup seat required; remote or regular desktop execution denied.")
    import tkinter
    Wizard(tkinter).run()


if __name__ == "__main__":
    main()
