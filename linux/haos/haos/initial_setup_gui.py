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
        elif name == "google-chat-history":
            self._head('Google Chat · erhaltene Konten',
                       'Lokale Prüfbelege und ausdrücklicher Widerruf bleiben auch nach einer Kontoentfernung erreichbar.')
            self._button(self.content,'Zur Gateway-Verwaltung',lambda:self.show('gateways')).pack(anchor='w',pady=5)
            from .google_chat_retired_gui import HistoricalRecoveryForm
            historical=HistoricalRecoveryForm(self,self.content);historical.frame.pack(fill='x')
        elif name == "gateways":
            self._head("Hermes · Gateways",
                       "Verbinde einen Bot und autorisiere nur konkrete Absender. Andere Hermes-Adapter müssen zuerst sicher integriert werden.")
            self._button(self.content,'Google Chat: entfernte Konten und lokale Altbestände verwalten',
                         lambda:self.show('google-chat-history')).pack(anchor='w',pady=5)
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
            platform = self._choice(self.content, "Plattform", ["telegram", "discord", "slack", "mattermost", "matrix", "ntfy", "homeassistant", "irc", "line", "sms", "email", "feishu", "dingtalk", "a2a", "buzz"], "telegram")
            token_box=tk.Frame(self.content,bg=self.PANEL);token_box.pack(fill='x')
            token = self._field(token_box, "Bot-Token / Zugangstoken (geschützte Eingabe)", secret=True)
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
            ha_credentials=tk.Frame(self.content,bg=self.PANEL)
            ha_server=self._field(ha_credentials,'Home Assistant HTTPS-Server')
            ha_server_value=tk.StringVar(value='');ha_server.configure(textvariable=ha_server_value);ha_server._haos_public_value=ha_server_value
            self._label(ha_credentials,'Erzeuge im Home-Assistant-Benutzerprofil einen Long-Lived Access Token und trage ihn oben geschützt ein. '
                'Die HTTPS-Adresse benötigt ein vom System vertrautes Zertifikat. HAOS öffnet eine ausgehende WebSocket-Verbindung; '
                'ein öffentlicher HAOS-Webhook ist nicht nötig. Kopple unten eine exakte Entity mit einer echten Benutzer-ID oder '
                'einer ausdrücklich bestätigten Systemquelle. Unbekannte Benutzer werden nicht freigegeben. '
                'Nach einer Trennung sind gespeicherte Eingänge wiederherstellbar; unbeobachtete Ereignisse können über '
                'die native HA-History nicht mit sicherer Absenderzuordnung nachgeladen werden. Diese Lücke bleibt sichtbar. '
                'Dieser Pfad steuert keine Geräte und bietet keine Chat-Befehle, Medien oder Voice.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            def retry_ha_auth():
                selected_connector=connector.get()
                self._run_async(lambda:initial_setup.retry_homeassistant_gateway_auth(selected_connector),
                    success='Home-Assistant-Auth-Sperre geprüft. Keine Nachricht gesendet; Lücken und Rechte bleiben erhalten. Dienst manuell starten.')
            self._button(ha_credentials,'Home-Assistant-Anmeldung erneut erlauben',retry_ha_auth).pack(anchor='w',pady=6)
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
            irc_credentials=tk.Frame(self.content,bg=self.PANEL)
            irc_server=self._field(irc_credentials,'IRC TLS-Server · exakter Hostname')
            irc_port=self._field(irc_credentials,'IRC TLS-Port','6697')
            irc_nick=self._field(irc_credentials,'IRC Bot-Nickname','haos-bot')
            irc_channel=self._field(irc_credentials,'IRC Kanal · exakt #kanal oder &kanal','#haos')
            irc_server_password=self._field(irc_credentials,'IRC Server-Passwort · optional',secret=True)
            irc_channel_password=self._field(irc_credentials,'IRC Kanal-Schlüssel · optional für +k',secret=True)
            irc_user=self._field(irc_credentials,'IRC SASL-Konto · exakter serverseitiger Kontoname')
            irc_password=self._field(irc_credentials,'IRC SASL-Passwort',secret=True)
            irc_anonymous=tk.BooleanVar(value=False)
            def irc_login_mode(*_args):
                for field in (irc_user,irc_password):field.configure(state='normal')
                if irc_anonymous.get():
                    for field in (irc_user,irc_password):field.delete(0,tk.END);field.configure(state='disabled')
            irc_anonymous.trace_add('write',irc_login_mode)
            tk.Checkbutton(irc_credentials,text='Verbindung ohne SASL-Konto ausdrücklich freigeben',variable=irc_anonymous,
                bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w').pack(anchor='w',pady=6)
            self._label(irc_credentials,'Der Server braucht ein vom System vertrautes TLS-Zertifikat, account-tag, server-time und message-tags '
                'sowie stabile msgid-Tags. Für Antworten sind zusätzlich echo-message, labeled-response und batch erforderlich. '
                'Absender ist der tatsächlich angemeldete IRC-Kontoname, niemals nur ein Nickname. In Kanälen den Bot ansprechen: botname: Aufgabe. '
                'Antworten sehen alle Kanalmitglieder. Ein Server-Echo beweist keinen Empfang bei einzelnen Personen; Spamfilter können Echos vortäuschen. '
                'Der gepinnte IRC-Adapter überträgt Text und HTTPS-Links, keine binären Datei- oder Voice-Uploads. '
                'Keine NickServ-Passwortweitergabe oder DCC-Freigabe. Unbekannte Offline-Ereignisse werden nicht als wiederhergestellt behauptet. '
                'Beim Speichern Zugangsdaten erneut eingeben; ohne SASL ist eine ausdrückliche Freigabe nötig.',size=10,color=self.MUTED).pack(anchor='w',pady=6)
            line_credentials=tk.Frame(self.content,bg=self.PANEL)
            line_allow_media=tk.BooleanVar(value=False);line_allow_voice=tk.BooleanVar(value=False)
            line_allow_video=tk.BooleanVar(value=False);line_allow_outbound=tk.BooleanVar(value=False)
            line_destination=self._field(line_credentials,'LINE Bot-Destination · U und 32 kleine Hex-Zeichen')
            line_port=self._field(line_credentials,'LINE lokaler HTTPS-Port · 1024 bis 65535','8646')
            line_url=self._field(line_credentials,'LINE öffentliche HTTPS-Adresse · https://hostname/line/webhook')
            line_bind=self._choice(line_credentials,'LINE Listener-Adresse',['127.0.0.1','0.0.0.0','::'],'127.0.0.1')
            line_public=tk.BooleanVar(value=False)
            tk.Checkbutton(line_credentials,text='Öffentlichen LINE-Listener ausdrücklich freigeben',variable=line_public,
                bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w').pack(anchor='w',pady=6)
            line_secret=self._field(line_credentials,'LINE Channel-Secret · geschützt',secret=True)
            line_access=self._field(line_credentials,'LINE Channel-Access-Token · geschützt',secret=True)
            line_pem={};line_revision=[0]
            line_pem_status=self._label(line_credentials,'Noch kein privates TLS-Material geladen.',size=10,color=self.MUTED)
            line_pem_status.pack(anchor='w',pady=4)
            def reset_line(*_args):
                line_allow_media.set(False);line_allow_voice.set(False);line_allow_video.set(False);line_allow_outbound.set(False)
                line_secret.delete(0,tk.END);line_access.delete(0,tk.END);line_public.set(False)
                line_pem.clear();line_revision[0]+=1
                line_pem_status.configure(text='Noch kein privates TLS-Material geladen.')
            def import_line_pem(kind):
                from tkinter import filedialog
                selected=filedialog.askopenfilename(parent=self.root,title='Private LINE-PEM-Datei auswählen')
                if not selected:return
                revision=line_revision[0]
                def loaded(value):
                    if platform.get()!='line' or line_revision[0]!=revision:
                        self.status.configure(text='LINE-Konfiguration geändert; TLS-Material erneut laden.');return
                    line_pem[kind]=value
                    line_pem_status.configure(text='Privat geladen: '+', '.join('Zertifikatskette' if key=='certificate' else 'Schlüssel' for key in sorted(line_pem)))
                self._run_async(lambda:initial_setup.import_line_tls_file(selected,kind),
                    success='PEM-Datei privat geladen; noch nicht gespeichert oder im Netzwerk verwendet.',result_handler=loaded)
            self._button(line_credentials,'LINE-Zertifikatskette laden',lambda:import_line_pem('certificate')).pack(anchor='w',pady=4)
            self._button(line_credentials,'LINE-TLS-Schlüssel laden',lambda:import_line_pem('private_key')).pack(anchor='w',pady=4)
            self._label(line_credentials,'In der LINE Developers Console Messaging API und Webhook einschalten, Channel-Secret, '
                'Access-Token und exakte Bot-Destination übernehmen. Der feste Pfad ist /line/webhook. '
                'Eine öffentliche HTTPS-DNS-Adresse auf Port 443 mit gültiger Zertifikatskette und passendem privaten PEM-Schlüssel ist erforderlich. '
                'Router oder TCP-Proxy müssen Port 443 auf diesen lokalen TLS-Port weiterleiten; HAOS richtet keine Portfreigabe ein. '
                'Auch die Host-Firewall muss den lokalen Listener-Port ausdrücklich erlauben. '
                'Loopback ist nur über einen entsprechend eingerichteten lokalen TCP-Proxy erreichbar. Hinter CGNAT ist zusätzliche öffentliche Erreichbarkeit erforderlich. '
                'Privates PEM-Material muss dem eingeschriebenen Owner oder root gehören und darf keine Gruppen-/Weltrechte besitzen. '
                'Der Dienst prüft die tatsächliche Bot-Identität. Kanal-/Token-/Zertifikatswechsel entzieht alte Absenderfreigaben. '
                'Einzelnutzer, Gruppen und Räume nur mit exakten U-/C-/R-IDs freigeben. Antworten in Gruppen sehen alle Mitglieder. '
                'Text und Missionsbefehle sind integriert; Bilder und Dokumente benötigen unten eine eigene Freigabe mit Erstellrecht. '
                'Sprachnachrichten benötigen eine eigene Freigabe; Video und ausgehende Ergebnisdateien benötigen jeweils eine eigene Freigabe. '
                'LINE-Serverannahme beweist keinen Empfang beim Empfänger. Die öffentliche Erreichbarkeit ist separat zu prüfen.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            def retry_line():
                selected_connector=connector.get()
                self._run_async(lambda:initial_setup.retry_line_gateway_auth(selected_connector),
                    success='Lokale LINE-Auth-Sperre geprüft; nach Korrektur manuell starten. Keine Nachricht versendet.')
            self._button(line_credentials,'LINE-Konto nach Korrektur erneut prüfen',retry_line).pack(anchor='w',pady=4)
            for field in (line_destination,line_port,line_url):
                variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
                variable.trace_add('write',reset_line)
            line_bind.trace_add('write',reset_line);connector_value.trace_add('write',reset_line)
            def line_port_number(text):
                if not isinstance(text,str) or not text.isascii() or not text.isdecimal() or len(text)>5 or not 1024<=int(text)<=65535:
                    raise ValueError('LINE HTTPS-Port muss eine ganze Zahl von 1024 bis 65535 sein')
                return int(text)
            def irc_port_number(text):
                if not isinstance(text,str) or not text.isascii() or not text.isdecimal() or len(text)>5 or not 1<=int(text)<=65535:
                    raise ValueError('IRC TLS-Port muss eine ganze Zahl von 1 bis 65535 sein')
                return int(text)
            sms_credentials=tk.Frame(self.content,bg=self.PANEL)
            sms_allow_media=tk.BooleanVar(value=False);sms_allow_voice=tk.BooleanVar(value=False)
            sms_allow_video=tk.BooleanVar(value=False);sms_allow_outbound=tk.BooleanVar(value=False)
            sms_account=self._field(sms_credentials,'Twilio Account SID · AC und 32 Hex-Zeichen')
            sms_number=self._field(sms_credentials,'Eigene Twilio-Empfangsnummer · E.164, zum Beispiel +43123456789')
            sms_port=self._field(sms_credentials,'SMS lokaler HTTPS-Port · 1024 bis 65535','8647')
            sms_url=self._field(sms_credentials,'SMS öffentliche HTTPS-Adresse · https://hostname/webhooks/twilio')
            sms_bind=self._choice(sms_credentials,'SMS Listener-Adresse',['127.0.0.1','0.0.0.0','::'],'127.0.0.1')
            sms_public=tk.BooleanVar(value=False)
            tk.Checkbutton(sms_credentials,text='Öffentlichen SMS-Listener ausdrücklich freigeben',variable=sms_public,
                bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w').pack(anchor='w',pady=6)
            sms_secret=self._field(sms_credentials,'Twilio Auth-Token · geschützt',secret=True)
            sms_pem={};sms_revision=[0]
            sms_pem_status=self._label(sms_credentials,'Noch kein privates TLS-Material geladen.',size=10,color=self.MUTED)
            sms_pem_status.pack(anchor='w',pady=4)
            def reset_sms(*_args):
                sms_allow_media.set(False);sms_allow_voice.set(False);sms_allow_video.set(False);sms_allow_outbound.set(False)
                sms_secret.delete(0,tk.END);sms_public.set(False)
                sms_pem.clear();sms_revision[0]+=1
                sms_pem_status.configure(text='Noch kein privates TLS-Material geladen.')
            def import_sms_pem(kind):
                from tkinter import filedialog
                selected=filedialog.askopenfilename(parent=self.root,title='Private SMS-PEM-Datei auswählen')
                if not selected:return
                revision=sms_revision[0]
                def loaded(value):
                    if platform.get()!='sms' or sms_revision[0]!=revision:
                        self.status.configure(text='SMS-Konfiguration geändert; TLS-Material erneut laden.');return
                    sms_pem[kind]=value
                    sms_pem_status.configure(text='Privat geladen: '+', '.join('Zertifikatskette' if key=='certificate' else 'Schlüssel' for key in sorted(sms_pem)))
                self._run_async(lambda:initial_setup.import_line_tls_file(selected,kind),
                    success='PEM-Datei privat geladen; noch nicht gespeichert oder im Netzwerk verwendet.',result_handler=loaded)
            self._button(sms_credentials,'SMS-Zertifikatskette laden',lambda:import_sms_pem('certificate')).pack(anchor='w',pady=4)
            self._button(sms_credentials,'SMS-TLS-Schlüssel laden',lambda:import_sms_pem('private_key')).pack(anchor='w',pady=4)
            self._label(sms_credentials,'In Twilio die eigene SMS-fähige Nummer auswählen und eingehende Nachrichten als HTTPS-POST an '
                'https://hostname/webhooks/twilio konfigurieren. Account SID und Auth-Token stammen aus dem zugehörigen Konto. '
                'Zertifikat, DNS und Weiterleitung müssen die öffentliche HTTPS-Adresse erreichbar machen. '
                'LINE und SMS können mit gleichem Zertifikat und gleicher Listener-Adresse denselben lokalen Port teilen. '
                'SMS/MMS können Kosten verursachen; MMS hängt zusätzlich von Nummer, Land und Mobilfunkanbieter ab. '
                'Ohne MMS-Unterstützung werden freigegebene Ergebnisdateien als zeitlich begrenzte Download-Links gesendet. '
                'Das Speichern sendet keine Nachricht und bestätigt keine externe Erreichbarkeit.',size=10,color=self.MUTED).pack(anchor='w',pady=6)
            def retry_sms():
                selected_connector=connector.get()
                self._run_async(lambda:initial_setup.retry_sms_gateway_auth(selected_connector),
                    success='Lokale SMS-Auth-Sperre geprüft; nach Korrektur manuell starten. Keine Nachricht versendet.')
            self._button(sms_credentials,'SMS-Konto nach Korrektur erneut prüfen',retry_sms).pack(anchor='w',pady=4)
            for field in (sms_account,sms_number,sms_port,sms_url):
                variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
                variable.trace_add('write',reset_sms)
            sms_bind.trace_add('write',reset_sms);connector_value.trace_add('write',reset_sms)
            def sms_port_number(text):
                if not isinstance(text,str) or not text.isascii() or not text.isdecimal() or len(text)>5 or not 1024<=int(text)<=65535:
                    raise ValueError('SMS HTTPS-Port muss eine ganze Zahl von 1024 bis 65535 sein')
                return int(text)
            from .email_owner_gui import AccountForm
            email_form=AccountForm(self,self.content,connector.get)
            connector_value.trace_add('write',email_form.clear_secret)
            from .feishu_owner_gui import AccountForm as FeishuAccountForm
            feishu_form=FeishuAccountForm(self,self.content,connector.get)
            connector_value.trace_add('write',feishu_form.clear_secret)
            from .dingtalk_owner_gui import AccountForm as DingTalkAccountForm
            dingtalk_form=DingTalkAccountForm(self,self.content,connector.get)
            connector_value.trace_add('write',dingtalk_form.clear_secret)
            from .a2a_owner_gui import AccountForm as A2AAccountForm,PeerForm as A2APeerForm,RecoveryForm as A2ARecoveryForm
            a2a_form=A2AAccountForm(self,self.content,connector.get);a2a_peers=A2APeerForm(self,self.content,connector.get)
            a2a_recovery=A2ARecoveryForm(self,self.content,connector.get)
            for form in [a2a_form,a2a_peers]:connector_value.trace_add('write',form.clear_secret)
            def a2a_refreshed(value):
                a2a_form.reset(value);a2a_peers.reset(value);a2a_pair.route_changed()
            a2a_form.on_saved=a2a_refreshed;a2a_peers.on_saved=a2a_refreshed
            from .buzz_owner_gui import AccountForm as BuzzAccountForm,RecoveryForm as BuzzRecoveryForm
            buzz_form=BuzzAccountForm(self,self.content,connector.get);buzz_recovery=BuzzRecoveryForm(self,self.content,connector.get,buzz_form)
            connector_value.trace_add('write',buzz_form.clear_secret);connector_value.trace_add('write',buzz_recovery.clear)
            def buzz_refreshed(value):
                configured_gateways.setdefault('buzz',{})[connector.get()]=value
                configured_gateways['connectors']=[row for row in configured_gateways['connectors'] if row['id']!=connector.get()]+[{'id':connector.get(),'platform':'buzz'}]
                buzz_form.reset(value);buzz_pair.changed();buzz_recovery.clear()
            buzz_form.on_saved=buzz_refreshed
            def configure():
                if platform.get()=='buzz':
                    buzz_form.configure();return
                if platform.get()=='a2a':
                    a2a_form.configure();return
                if platform.get()=='dingtalk':
                    dingtalk_form.configure();return
                if platform.get()=='feishu':
                    feishu_form.configure();return
                if platform.get()=='email':
                    email_form.configure();return
                line_values={'channel_secret':line_secret.get(),'channel_access_token':line_access.get(),
                    'destination':line_destination.get(),'port':line_port.get(),'tls':{'public_url':line_url.get(),
                        'bind_host':line_bind.get(),'public_listener':line_public.get(),**line_pem}}
                sms_values={'account_sid':sms_account.get(),'auth_token':sms_secret.get(),
                    'from_number':sms_number.get(),'port':sms_port.get(),'tls':{'public_url':sms_url.get(),
                        'bind_host':sms_bind.get(),'public_listener':sms_public.get(),**sms_pem}}
                reset_sms()
                reset_line()
                secret, app_secret = token.get(), app_token.get()
                matrix_values={'homeserver':matrix_server.get(),'user_id':matrix_user.get(),'device_id':matrix_device.get(),
                    'recovery_key':matrix_recovery.get()}
                token.delete(0, tk.END)
                app_token.delete(0, tk.END)
                matrix_recovery.delete(0,tk.END)
                selected_ntfy_server,selected_ntfy_topic=ntfy_server.get(),ntfy_topic.get()
                selected_ha_server=ha_server.get()
                irc_values={'server':irc_server.get(),'port':irc_port.get(),'nickname':irc_nick.get(),'channel':irc_channel.get(),
                    'server_password':irc_server_password.get(),'sasl_username':irc_user.get(),'sasl_password':irc_password.get(),
                    'anonymous':irc_anonymous.get()}
                if irc_channel_password.get():irc_values['channel_password']=irc_channel_password.get()
                irc_channel_password.delete(0,tk.END)
                irc_server_password.delete(0,tk.END);irc_password.delete(0,tk.END);irc_anonymous.set(False)
                if platform.get()=='ntfy':trust_publishers.set(False)
                if platform.get()=='homeassistant':reset_ha_consent()
                selected_connector, selected_platform, selected_server = connector.get(), platform.get(), mm_server.get()
                self._run_async(lambda: (initial_setup.configure_sms_gateway(selected_connector,**{**sms_values,'port':sms_port_number(sms_values['port'])})
                    if selected_platform=='sms' else initial_setup.configure_line_gateway(selected_connector,**{**line_values,'port':line_port_number(line_values['port'])})
                    if selected_platform=='line' else initial_setup.configure_irc_gateway(selected_connector,**{**irc_values,'port':irc_port_number(irc_values['port'])})
                    if selected_platform=='irc' else initial_setup.configure_gateway(
                    selected_connector, selected_platform, secret, app_secret, selected_server) if selected_platform=='mattermost'
                    else initial_setup.configure_gateway(selected_connector,selected_platform,secret,app_secret,**matrix_values)
                    if selected_platform=='matrix' else initial_setup.configure_gateway(selected_connector,selected_platform,secret,
                        server_url=selected_ntfy_server,topic=selected_ntfy_topic) if selected_platform=='ntfy'
                    else initial_setup.configure_gateway(selected_connector,selected_platform,secret,server_url=selected_ha_server)
                    if selected_platform=='homeassistant'
                    else initial_setup.configure_gateway(selected_connector, selected_platform, secret, app_secret)),
                    success="Gateway gespeichert. Bei Token-/Kontowechsel Absender erneut koppeln; anschließend Gateway-Dienst neu starten.")
            configure_button = self._button(self.content, "Gateway sicher anlegen", configure, primary=True)
            configure_button.pack(anchor="w", pady=10)
            def platform_changed(*_args):
                reset_sms();reset_line();email_form.reset();feishu_form.reset();dingtalk_form.reset()
                a2a_form.reset();a2a_peers.reset()
                buzz_form.reset();buzz_recovery.clear()
                for form in [buzz_form,buzz_recovery]:form.frame.pack_forget()
                for form in [a2a_form,a2a_peers,a2a_recovery]:form.frame.pack_forget()
                dingtalk_form.frame.pack_forget()
                feishu_form.frame.pack_forget()
                email_form.frame.pack_forget()
                token.delete(0, tk.END);app_token.delete(0, tk.END);mm_server.delete(0,tk.END)
                for field in (matrix_server,matrix_user,matrix_device,matrix_recovery):field.delete(0,tk.END)
                for field in (ntfy_server,ntfy_topic):field.delete(0,tk.END)
                ha_server.delete(0,tk.END)
                irc_server_password.delete(0,tk.END);irc_channel_password.delete(0,tk.END);irc_password.delete(0,tk.END);irc_user.delete(0,tk.END);irc_anonymous.set(False)
                for field,default in ((irc_server,''),(irc_port,'6697'),(irc_nick,'haos-bot'),(irc_channel,'#haos')):
                    field.delete(0,tk.END);field.insert(0,default)
                if platform.get()=='irc':
                    token_box.pack_forget();irc_credentials.pack(fill='x',before=configure_button)
                    existing=configured_gateways.get('irc',{}).get(connector.get())
                    if existing:
                        for field,key in ((irc_server,'server'),(irc_port,'port'),(irc_nick,'nickname'),(irc_channel,'channel')):
                            field.delete(0,tk.END);field.insert(0,str(existing[key]))
                elif platform.get() in {'line','sms','email','feishu','dingtalk','a2a','buzz'}:
                    irc_credentials.pack_forget();token_box.pack_forget()
                else:
                    irc_credentials.pack_forget();token_box.pack(fill='x',before=configure_button)
                if connector.get() in {'telegram-main','discord-main','slack-main','mattermost-main','matrix-main','ntfy-main','homeassistant-main','irc-main','line-main','sms-main','email-main','feishu-main','dingtalk-main','a2a-main','buzz-main'}:
                    connector.delete(0,tk.END);connector.insert(0,platform.get()+'-main')
                    if platform.get()=='a2a':
                        saved_a2a=[row['id'] for row in configured_gateways['connectors'] if row['platform']=='a2a']
                        if len(saved_a2a)==1:connector.delete(0,tk.END);connector.insert(0,saved_a2a[0])
                if platform.get()=='a2a':
                    value=configured_gateways.get('a2a',{}).get(connector.get())
                    a2a_form.reset(value);a2a_peers.reset(value)
                    for form in [a2a_form,a2a_peers,a2a_recovery]:form.frame.pack(fill='x',before=configure_button)
                if platform.get()=='buzz':
                    buzz_form.reset(configured_gateways.get('buzz',{}).get(connector.get()))
                    for form in [buzz_form,buzz_recovery]:form.frame.pack(fill='x',before=configure_button)
                if platform.get()=='irc':
                    existing=configured_gateways.get('irc',{}).get(connector.get())
                    if existing:
                        for field,key in ((irc_server,'server'),(irc_port,'port'),(irc_nick,'nickname'),(irc_channel,'channel')):
                            field.delete(0,tk.END);field.insert(0,str(existing[key]))
                if platform.get()=='dingtalk':
                    dingtalk_form.reset(configured_gateways.get('dingtalk',{}).get(connector.get()))
                    dingtalk_form.frame.pack(fill='x',before=configure_button)
                if platform.get()=='feishu':
                    feishu_form.reset(configured_gateways.get('feishu',{}).get(connector.get()))
                    feishu_form.frame.pack(fill='x',before=configure_button)
                if platform.get()=='email':
                    email_form.reset(configured_gateways.get('email',{}).get(connector.get()))
                    email_form.frame.pack(fill='x',before=configure_button)
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
                if platform.get()=='homeassistant':
                    ha_credentials.pack(fill='x',before=configure_button)
                    existing=configured_gateways.get('homeassistant',{}).get(connector.get())
                    if existing:ha_server.insert(0,existing['server_url'])
                else:ha_credentials.pack_forget()
                if platform.get()=='matrix':matrix_credentials.pack(fill='x',before=configure_button)
                else:matrix_credentials.pack_forget()
                if platform.get()=='line':
                    line_credentials.pack(fill='x',before=configure_button)
                    existing=configured_gateways.get('line',{}).get(connector.get())
                    if existing:
                        for field,key in ((line_destination,'destination'),(line_port,'port'),(line_url,'public_url')):
                            field.delete(0,tk.END);field.insert(0,str(existing[key]))
                        line_bind.set(existing['bind_host'])
                else:line_credentials.pack_forget()
                if platform.get()=='sms':
                    sms_credentials.pack(fill='x',before=configure_button)
                    existing=configured_gateways.get('sms',{}).get(connector.get())
                    if existing:
                        for field,key in ((sms_account,'account_sid'),(sms_number,'from_number'),(sms_port,'port'),(sms_url,'public_url')):
                            field.delete(0,tk.END);field.insert(0,str(existing[key]))
                        sms_bind.set(existing['bind_host'])
                else:sms_credentials.pack_forget()
                self.root.after_idle(irc_pair_changed)
            def reset_irc_secrets(*_args):
                irc_server_password.delete(0,tk.END);irc_channel_password.delete(0,tk.END);irc_password.delete(0,tk.END);irc_anonymous.set(False)
            for field in (irc_server,irc_port):
                variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
                variable.trace_add('write',reset_irc_secrets)
            irc_username_value=tk.StringVar(value='');irc_user.configure(textvariable=irc_username_value);irc_user._haos_public_value=irc_username_value
            irc_username_value.trace_add('write',lambda *_args:irc_password.delete(0,tk.END))
            connector_value.trace_add('write',reset_irc_secrets)
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
            ha_pair=tk.Frame(self.content,bg=self.PANEL)
            share_ha=tk.BooleanVar(value=False);trust_ha_system=tk.BooleanVar(value=False)
            tk.Checkbutton(ha_pair,text='Ich erlaube Missionantworten als Benachrichtigungen für ALLE Benutzer dieser HA-Instanz',
                variable=share_ha,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w').pack(anchor='w')
            tk.Checkbutton(ha_pair,text='Ich vertraue allen System-/Automationsquellen dieser exakten Entity',
                variable=trust_ha_system,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w').pack(anchor='w')
            self._label(ha_pair,'Ohne Systemfreigabe: echte Benutzer-ID mit 32 kleinen Hex-Zeichen als Absender. '
                'Mit Systemfreigabe: Absender system; es wird keine verifizierte Person behauptet. '
                'Chat ist die exakte Entity-ID, zum Beispiel sensor.kitchen oder input_text.owner. '
                'Bereich und Thread bleiben leer. Bei Leserecht sind Antworten für alle Instanzbenutzer sichtbar.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            previous_ha=[False]
            def ha_system_changed(*_args):
                if platform.get()!='homeassistant':return
                was_disabled=str(sender.cget('state'))=='disabled'
                sender.configure(state='normal')
                if trust_ha_system.get():
                    sender.delete(0,tk.END);sender.insert(0,'system');sender.configure(state='disabled')
                elif was_disabled and sender.get()=='system':sender.delete(0,tk.END)
            trust_ha_system.trace_add('write',ha_system_changed)
            def reset_ha_consent(*_args):
                share_ha.set(False);trust_ha_system.set(False)
            ha_server_value.trace_add('write',reset_ha_consent)
            connector_value.trace_add('write',reset_ha_consent)
            def ha_pair_changed(*_args):
                reset_ha_consent();active=platform.get()=='homeassistant'
                if active or previous_ha[0]:
                    for field in (scope,thread):
                        field.configure(state='normal');field.delete(0,tk.END)
                        if active:field.configure(state='disabled')
                    for field in (sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                if active:ha_pair.pack(fill='x',before=pairing_note)
                else:ha_pair.pack_forget()
                for capability,widget in rights_widgets.items():
                    if capability not in {'create','read'}:
                        widget.configure(state='disabled' if active else 'normal')
                        if active:rights[capability].set(False)
                previous_ha[0]=active
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
                if platform.get() in {'homeassistant','irc'}:
                    ntfy_pair.pack_forget();previous_ntfy[0]=False;return
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
            rights = {};rights_widgets={}
            for capability, label in (("create", "Missionen erstellen"), ("read", "Eigene Missionen lesen"),
                    ("cancel", "Eigene Missionen abbrechen"), ("answer", "Rückfragen und Freigaben beantworten"),
                    ("pause", "Wartende Missionen pausieren"), ("resume", "Pausierte Missionen fortsetzen")):
                variable = tk.BooleanVar(value=capability in {"create", "read"})
                rights[capability] = variable
                widget=tk.Checkbutton(self.content, text=label, variable=variable, bg=self.PANEL, fg=self.TEXT,
                    selectcolor=self.BG, activebackground=self.PANEL)
                widget.pack(anchor='w');rights_widgets[capability]=widget
            platform.trace_add('write',ha_pair_changed)
            irc_pair=tk.Frame(self.content,bg=self.PANEL)
            self._label(irc_pair,'IRC: tatsächlichen authentifizierten Kontonamen als Absender freigeben, nicht den Nicknamen. '
                'Kanal und TLS-Server müssen zuerst oben gespeichert werden. Groß-/Kleinschreibung des Kontos exakt übernehmen. '
                'Die Freigabe gilt nur für diesen Kanal dieses Servers; Antworten sind für alle Kanalmitglieder sichtbar. '
                'Ein Server-Echo ist kein Empfangsnachweis für einzelne Personen. Threads werden nicht erzeugt.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            previous_irc=[False]
            def irc_pair_changed(*_args):
                if not irc_pair.winfo_exists():return
                active=platform.get()=='irc'
                if active:
                    irc_pair.pack(fill='x',before=pairing_note)
                    for field in (scope,thread):field.configure(state='normal');field.delete(0,tk.END)
                    scope.insert(0,irc_server.get()+':'+irc_port.get())
                    for field in (scope,thread):field.configure(state='disabled')
                    chat.configure(state='normal');chat.delete(0,tk.END);chat.insert(0,irc_channel.get())
                    if not previous_irc[0]:sender.configure(state='normal');sender.delete(0,tk.END)
                else:
                    irc_pair.pack_forget()
                    if previous_irc[0] and platform.get() not in {'homeassistant','ntfy'}:
                        for field in (scope,thread,sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                previous_irc[0]=active
            platform.trace_add('write',irc_pair_changed)
            for field in (irc_server,irc_port):field._haos_public_value.trace_add('write',irc_pair_changed)
            irc_channel_value=tk.StringVar(value=irc_channel.get());irc_channel.configure(textvariable=irc_channel_value);irc_channel._haos_public_value=irc_channel_value
            irc_channel_value.trace_add('write',lambda *_args:irc_channel_password.delete(0,tk.END))
            irc_channel_value.trace_add('write',irc_pair_changed)
            line_pair=tk.Frame(self.content,bg=self.PANEL)
            line_media_box=tk.Checkbutton(line_pair,text='Eingehende LINE-Bilder und Dokumente für diesen Absender ausdrücklich freigeben',
                variable=line_allow_media,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w')
            line_media_box.pack(anchor='w',pady=6)
            self._label(line_pair,'Benötigt Missionen erstellen. PNG/JPEG: insgesamt höchstens 2 MiB; Dokument: höchstens 8 MiB. '
                'Dateiinhalte gehen in den Agenten innerhalb der bestehenden Owner-Dateisystemgrenzen. Keine Gateway-Pfade oder Tokens werden freigegeben. '
                'Bildanalyse benötigt ein bildfähiges freigegebenes Modell. Voice/Video und ausgehende Medien sind nicht enthalten.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            line_voice_box=tk.Checkbutton(line_pair,text='Eingehende LINE-Sprachnachrichten für diesen Absender ausdrücklich freigeben',
                variable=line_allow_voice,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=self.label_wrap)
            line_voice_box.pack(anchor='w',pady=5)
            self._label(line_pair,'Benötigt den eingerichteten lokalen Spracherkennungsdienst und das Recht zum Erstellen von Missionen. '
                'Bis 8 MiB / zwei Minuten; die Originalaudiodatei bleibt privat, der Agent erhält das lokale Transkript.',
                size=10,color=self.MUTED).pack(anchor='w',pady=5)
            line_video_box=tk.Checkbutton(line_pair,text='Eingehende LINE-MP4-Videos für diesen Absender ausdrücklich freigeben',
                variable=line_allow_video,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,wraplength=self.label_wrap)
            line_video_box.pack(anchor='w',pady=5)
            self._label(line_pair,'Bis 8 MiB / gemeldete zwei Minuten. Die MP4-Datei geht als Datei in die Mission; '
                'eine erfolgreiche Videoanalyse hängt von den freigegebenen Agent-Werkzeugen ab.',size=10,color=self.MUTED).pack(anchor='w',pady=5)
            line_output_box=tk.Checkbutton(line_pair,text='Explizit markierte Ergebnisdateien dieser Missionen an diesen Chat senden',
                variable=line_allow_outbound,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,wraplength=self.label_wrap)
            line_output_box.pack(anchor='w',pady=5)
            self._label(line_pair,'Benötigt Antworten lesen und eine öffentliche HTTPS-Adresse. Höchstens 8 MiB pro Datei; '
                'Bilder höchstens 1 MiB. Dateien werden eine Stunde über nicht erratbare Download-Links bereitgestellt. '
                'Entzug sperrt neue Abrufe sofort; bereits heruntergeladene Kopien bleiben beim Empfänger.',size=10,color=self.MUTED).pack(anchor='w',pady=5)
            def line_media_rights(*_args):
                if not rights['create'].get():line_allow_media.set(False);line_allow_voice.set(False);line_allow_video.set(False);line_allow_outbound.set(False)
                line_media_box.configure(state='normal' if rights['create'].get() else 'disabled')
                line_voice_box.configure(state='normal' if rights['create'].get() else 'disabled')
                line_video_box.configure(state='normal' if rights['create'].get() else 'disabled')
                if not rights['read'].get():line_allow_outbound.set(False)
                line_output_box.configure(state='normal' if rights['read'].get() else 'disabled')
            rights['create'].trace_add('write',line_media_rights)
            rights['read'].trace_add('write',line_media_rights)
            def reset_line_voice_consent(*_args):
                line_allow_media.set(False);line_allow_voice.set(False);line_allow_video.set(False);line_allow_outbound.set(False)
            for field in (sender,chat):
                variable=tk.StringVar(value=field.get());field.configure(textvariable=variable);field._haos_public_value=variable
                variable.trace_add('write',reset_line_voice_consent)
            self._label(line_pair,'LINE: Absender als exakte U-ID, Chat als U-ID derselben Person oder C-/R-ID der Gruppe/des Raums. '
                'Bereich ist die gespeicherte Bot-Destination. Threads werden nicht freigegeben. '
                'Bei Gruppen/Räumen sehen alle Mitglieder die Antworten; nur die ausdrücklich gekoppelten Personen dürfen Missionen steuern.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            previous_line=[False]
            def line_pair_changed(*_args):
                line_allow_media.set(False);line_allow_voice.set(False);line_allow_video.set(False);line_allow_outbound.set(False)
                active=platform.get()=='line'
                if active:
                    line_pair.pack(fill='x',before=pairing_note)
                    for field in (scope,thread):field.configure(state='normal');field.delete(0,tk.END)
                    scope.insert(0,line_destination.get())
                    for field in (scope,thread):field.configure(state='disabled')
                    if not previous_line[0]:
                        for field in (sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                else:
                    line_pair.pack_forget()
                    if previous_line[0] and platform.get() not in {'homeassistant','ntfy','irc','sms'}:
                        for field in (scope,thread,sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                previous_line[0]=active
            platform.trace_add('write',line_pair_changed)
            line_destination._haos_public_value.trace_add('write',line_pair_changed)
            sms_pair=tk.Frame(self.content,bg=self.PANEL)
            sms_media_box=tk.Checkbutton(sms_pair,text='Eingehende SMS-Bilder und Dokumente für diesen Absender ausdrücklich freigeben',
                variable=sms_allow_media,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=max(180,self.label_wrap-50),justify='left',anchor='w')
            sms_media_box.pack(anchor='w',pady=6)
            self._label(sms_pair,'Benötigt Missionen erstellen. PNG/JPEG: insgesamt höchstens 2 MiB; Dokument: höchstens 500 KB. '
                'Dateiinhalte gehen in den Agenten innerhalb der bestehenden Owner-Dateisystemgrenzen. Keine Gateway-Pfade oder Tokens werden freigegeben. '
                'Bildanalyse benötigt ein bildfähiges freigegebenes Modell. Voice/Video und ausgehende Medien sind nicht enthalten.',
                size=10,color=self.MUTED).pack(anchor='w',pady=6)
            sms_voice_box=tk.Checkbutton(sms_pair,text='Eingehende SMS-Sprachnachrichten für diesen Absender ausdrücklich freigeben',
                variable=sms_allow_voice,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,
                wraplength=self.label_wrap)
            sms_voice_box.pack(anchor='w',pady=5)
            self._label(sms_pair,'Benötigt den eingerichteten lokalen Spracherkennungsdienst und das Recht zum Erstellen von Missionen. '
                'Bis 500 KB / zwei Minuten; die Originalaudiodatei bleibt privat, der Agent erhält das lokale Transkript.',
                size=10,color=self.MUTED).pack(anchor='w',pady=5)
            sms_video_box=tk.Checkbutton(sms_pair,text='Eingehende SMS-MP4-/3GP-Videos für diesen Absender ausdrücklich freigeben',
                variable=sms_allow_video,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,wraplength=self.label_wrap)
            sms_video_box.pack(anchor='w',pady=5)
            self._label(sms_pair,'Bis 500 KB. Die Videodatei geht als Datei in die Mission; '
                'eine erfolgreiche Videoanalyse hängt von den freigegebenen Agent-Werkzeugen ab.',size=10,color=self.MUTED).pack(anchor='w',pady=5)
            sms_output_box=tk.Checkbutton(sms_pair,text='Explizit markierte Ergebnisdateien dieser Missionen an diesen Chat senden',
                variable=sms_allow_outbound,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,activebackground=self.PANEL,wraplength=self.label_wrap)
            sms_output_box.pack(anchor='w',pady=5)
            self._label(sms_pair,'Benötigt Antworten lesen und eine öffentliche HTTPS-Adresse. Höchstens 8 MiB pro Datei; '
                'Bilder höchstens 1 MiB. Dateien werden eine Stunde über nicht erratbare Download-Links bereitgestellt. '
                'Entzug sperrt neue Abrufe sofort; bereits heruntergeladene Kopien bleiben beim Empfänger.',size=10,color=self.MUTED).pack(anchor='w',pady=5)
            def sms_media_rights(*_args):
                if not rights['create'].get():sms_allow_media.set(False);sms_allow_voice.set(False);sms_allow_video.set(False);sms_allow_outbound.set(False)
                sms_media_box.configure(state='normal' if rights['create'].get() else 'disabled')
                sms_voice_box.configure(state='normal' if rights['create'].get() else 'disabled')
                sms_video_box.configure(state='normal' if rights['create'].get() else 'disabled')
                if not rights['read'].get():sms_allow_outbound.set(False)
                sms_output_box.configure(state='normal' if rights['read'].get() else 'disabled')
            rights['create'].trace_add('write',sms_media_rights)
            rights['read'].trace_add('write',sms_media_rights)
            def reset_sms_voice_consent(*_args):
                sms_allow_media.set(False);sms_allow_voice.set(False);sms_allow_video.set(False);sms_allow_outbound.set(False)
            for field in (sender,chat):
                field._haos_public_value.trace_add('write',reset_sms_voice_consent)
            self._label(sms_pair,'SMS: Absender und Chat sind dieselbe exakte E.164-Rufnummer. '
                'Bereich ist Account SID und eigene Empfangsnummer; Threads sind nicht freigegeben. '
                'Eine Rufnummernfreigabe ist keine unabhängige Prüfung der tatsächlichen Person. '
                'MMS: höchstens vier Anhänge, PNG/JPEG insgesamt 2 MiB; andere Mediendateien höchstens 500 KB. '
                'Spracherkennung erfolgt lokal; rohe Audiodaten gehen nicht zum Agenten.',size=10,color=self.MUTED).pack(anchor='w',pady=6)
            previous_sms=[False]
            def sms_pair_changed(*_args):
                sms_allow_media.set(False);sms_allow_voice.set(False);sms_allow_video.set(False);sms_allow_outbound.set(False)
                active=platform.get()=='sms'
                if active:
                    sms_pair.pack(fill='x',before=pairing_note)
                    for field in (scope,thread):field.configure(state='normal');field.delete(0,tk.END)
                    scope.insert(0,sms_account.get()+':'+sms_number.get())
                    for field in (scope,thread):field.configure(state='disabled')
                    if not previous_sms[0]:
                        for field in (sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                else:
                    sms_pair.pack_forget()
                    if previous_sms[0] and platform.get() not in {'homeassistant','ntfy','irc','line'}:
                        for field in (scope,thread,sender,chat):field.configure(state='normal');field.delete(0,tk.END)
                previous_sms[0]=active
            platform.trace_add('write',sms_pair_changed)
            sms_account._haos_public_value.trace_add('write',sms_pair_changed)
            sms_number._haos_public_value.trace_add('write',sms_pair_changed)
            from .email_owner_gui import PairForm
            email_pair=PairForm(self,self.content,platform,email_form,sender,chat,scope,thread,rights,pairing_note)
            connector_value.trace_add('write',email_pair.clear)
            from .feishu_owner_gui import PairForm as FeishuPairForm
            feishu_pair=FeishuPairForm(self,self.content,platform,feishu_form,sender,chat,scope,thread,rights,pairing_note)
            connector_value.trace_add('write',feishu_pair.clear)
            from .dingtalk_owner_gui import PairForm as DingTalkPairForm
            dingtalk_pair=DingTalkPairForm(self,self.content,platform,dingtalk_form,sender,chat,scope,thread,rights,pairing_note)
            connector_value.trace_add('write',dingtalk_pair.clear)
            from .a2a_owner_gui import PairForm as A2APairForm
            a2a_pair=A2APairForm(self,self.content,platform,a2a_form,sender,chat,scope,thread,rights,rights_widgets,pairing_note)
            connector_value.trace_add('write',a2a_pair.clear)
            from .buzz_owner_gui import PairForm as BuzzPairForm
            buzz_pair=BuzzPairForm(self,self.content,platform,buzz_form,sender,chat,scope,thread,rights,pairing_note)
            connector_value.trace_add('write',buzz_pair.clear)
            def retry_irc():
                selected_connector=connector.get()
                self._run_async(lambda:initial_setup.retry_irc_gateway_auth(selected_connector),
                    success='Lokale Auth-Sperre geprüft. Der Gateway-Dienst bleibt gestoppt; nach Prüfung neu starten. Es wurde keine Nachricht versendet.')
            self._button(irc_credentials,'IRC-Konto nach Korrektur erneut prüfen',retry_irc).pack(anchor='w',pady=6)
            def pair_sender():
                selected = (binding.get(), connector.get(), sender.get(), chat.get(), identity.get(),
                            tuple(key for key, value in rights.items() if value.get()))
                if platform.get()=='a2a':
                    a2a_pair.apply(selected);return
                buzz_options=None
                if platform.get()=='buzz':
                    try:buzz_options=buzz_pair.options()
                    except ValueError as error:
                        self._show_error(describe_error(error,area=self.page));return
                selected_scope, selected_thread = scope.get(), thread.get()
                requested_irc_port=None
                if platform.get()=='irc':
                    try:requested_irc_port=irc_port_number(irc_port.get())
                    except ValueError as error:
                        self._show_error(describe_error(error,area=self.page));return
                if platform.get()=='ntfy' and not trust_publishers.get():
                    self._show_error(describe_error(ValueError('Bestätige ausdrücklich das Vertrauen in alle Publisher dieses privaten Topics.'),area=self.page))
                    return
                if platform.get()=='homeassistant' and rights['read'].get() and not share_ha.get():
                    self._show_error(describe_error(ValueError('Bestätige ausdrücklich die Sichtbarkeit von Antworten für ALLE Home-Assistant-Instanzbenutzer.'),area=self.page))
                    return
                options=({'matrix_devices':[dict(row) for row in approved_devices],'allow_plaintext':allow_plain.get(),
                    'require_mention':mention_required.get()} if platform.get()=='matrix'
                    else {'trust_topic_publishers':trust_publishers.get(),'ntfy_server_url':ntfy_server.get()} if platform.get()=='ntfy'
                    else buzz_options if platform.get()=='buzz'
                    else dingtalk_pair.options() if platform.get()=='dingtalk'
                    else feishu_pair.options() if platform.get()=='feishu'
                    else email_pair.options() if platform.get()=='email'
                    else {'allow_media':sms_allow_media.get(),'allow_voice':sms_allow_voice.get(),'allow_video':sms_allow_video.get(),'allow_outbound_media':sms_allow_outbound.get()} if platform.get()=='sms'
                    else {'allow_media':line_allow_media.get(),'allow_voice':line_allow_voice.get(),'allow_video':line_allow_video.get(),'allow_outbound_media':line_allow_outbound.get()} if platform.get()=='line'
                    else {'homeassistant_shared_notifications':share_ha.get(),'homeassistant_trust_system':trust_ha_system.get(),
                        'homeassistant_server_url':ha_server.get()} if platform.get()=='homeassistant' else {'irc_server':irc_server.get(),'irc_port':requested_irc_port,'irc_channel':irc_channel.get()} if platform.get()=='irc' else {})
                reset_sms_voice_consent();email_pair.clear();feishu_pair.clear();dingtalk_pair.clear()
                line_allow_media.set(False);line_allow_voice.set(False);line_allow_video.set(False);line_allow_outbound.set(False)
                if platform.get()=='buzz':buzz_pair.clear()
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
                            for c in configured_gateways["connectors"]) else "")
                        + (" · Antworten für ALLE Instanzbenutzer sichtbar" if row.get('homeassistant_shared_notifications') else "")
                        + (" · System-/Automationsquellen dieser Entity ausdrücklich freigegeben" if row.get('homeassistant_trust_system') else ""))
                    media_platform=next((c['platform'] for c in configured_gateways['connectors'] if c['id']==row['connector']),'Gateway')
                    media_label={'line':'LINE','sms':'SMS','email':'E-Mail','feishu':'Feishu','dingtalk':'DingTalk'}.get(media_platform,'Gateway')
                    if row.get('allow_media'):binding_details.configure(text=binding_details.cget('text')+' · '+media_label+'-Bilder/Dokumente ausdrücklich freigegeben')
                    if row.get('allow_video'):binding_details.configure(text=binding_details.cget('text')+' · MP4-Eingang freigegeben')
                    if row.get('allow_outbound_media'):binding_details.configure(text=binding_details.cget('text')+' · Ergebnisdateien für diesen Chat freigegeben')
                    if row.get('allow_voice'):binding_details.configure(text=binding_details.cget('text')+' · '+media_label+'-Sprachnachrichten ausdrücklich freigegeben')
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
                    ha_labels={'created':'Privates HA-Profil vorbereitet','connecting':'Home-Assistant-Anmeldung wird geprüft',
                        'streaming':'Home-Assistant-Stream angemeldet; keine externe Zustellung abgeleitet',
                        'disconnected':'Home Assistant getrennt; gespeicherte Eingänge bleiben erhalten',
                        'authentication-refused':'HA-Anmeldung abgelehnt; Konto/Token prüfen und erneute Anmeldung ausdrücklich erlauben',
                        'rate-limited':'Home Assistant begrenzt Anfragen; gespeicherte Wartefrist bleibt erhalten',
                        'transport-unavailable':'Home Assistant/TLS nicht verfügbar; Adresse, Zertifikat und Netzwerk prüfen',
                        'revoked':'Home-Assistant-Freigabe entzogen oder geändert; keine weitere Ausführung',
                        'closed':'Privates Home-Assistant-Profil geschlossen; Daten erhalten'}
                    irc_labels={**ha_labels,'connecting':'IRC-TLS-Verbindung und Anmeldung werden geprüft',
                        'streaming':'IRC angemeldet; keine Zustellung an Kanalmitglieder bestätigt',
                        'authentication-refused':'IRC-Anmeldung abgelehnt; SASL/Server-Passwort prüfen und erneute Anmeldung ausdrücklich erlauben',
                        'transport-unavailable':'IRC-TLS oder erforderliche Server-Fähigkeiten nicht verfügbar',
                        'disconnected':'IRC getrennt; gespeicherte Eingänge bleiben erhalten',
                        'revoked':'IRC-Freigabe entzogen oder geändert; keine weitere Ausführung',
                        'closed':'Privates IRC-Profil geschlossen; Daten erhalten',
                        'created':'Privates IRC-Profil vorbereitet',
                        'rate-limited':'IRC begrenzt Anfragen; gespeicherte Wartefrist bleibt erhalten'}
                    line_labels={'created':'Privates LINE-Profil vorbereitet','listening':'Lokaler LINE-Listener bereit; öffentliche HTTPS-Erreichbarkeit nicht bestätigt',
                        'listening-tls':'LINE-HTTPS-Listener bereit; externe LINE-Erreichbarkeitsprüfung noch nicht bestätigt',
                        'disconnected':'LINE-Listener getrennt; gespeicherte Eingänge bleiben erhalten',
                        'authentication-refused':'LINE-Anmeldung abgelehnt; privaten Channel-Token prüfen und erneute Anmeldung ausdrücklich erlauben',
                        'identity-refused':'LINE-Bot-ID passt nicht zum Zugangstoken; gespeicherte Daten bleiben erhalten',
                        'rate-limited':'LINE begrenzt Anfragen; gespeicherte Wartefrist bleibt erhalten',
                        'transport-unavailable':'LINE-Identitätsprüfung oder lokaler Listener nicht verfügbar; Netzwerk, Zertifikat und Port prüfen',
                        'tls-refused':'LINE-TLS-Material abgelehnt; gültige Zertifikatskette und passenden privaten Schlüssel laden. Gespeicherte Daten bleiben erhalten',
                        'revoked':'LINE-Freigabe entzogen oder geändert; keine weitere Ausführung',
                        'closed':'Privates LINE-Profil geschlossen; Daten erhalten'}
                    from .email_owner_gui import LABELS as email_labels
                    from .feishu_owner_gui import LABELS as feishu_labels
                    from .dingtalk_owner_gui import LABELS as dingtalk_labels
                    from .buzz_owner_gui import LABELS as buzz_labels
                    labels=(buzz_labels if item.get('platform')=='buzz' else dingtalk_labels if item.get('platform')=='dingtalk' else feishu_labels if item.get('platform')=='feishu' else email_labels if item.get('platform')=='email' else matrix_labels if item.get('platform')=='matrix' else ntfy_labels if item.get('platform')=='ntfy'
                        else {**{key:value.replace('LINE','SMS/Twilio') for key,value in line_labels.items()},
                            'authentication-refused':'SMS/Twilio-Anmeldung abgelehnt; Account SID und privaten Auth-Token prüfen',
                            'identity-refused':'SMS/Twilio-Konto oder eigene Empfangsnummer passt nicht; gespeicherte Daten bleiben erhalten',
                            'backfill-ready':'SMS/Twilio-Nachholen: letzte API-Seite geprüft; kein Beleg für vollständigen Anbieter-Verlauf',
                            'backfill-unavailable':'SMS/Twilio-Nachholen nicht verfügbar; gespeicherter Cursor bleibt erhalten. Konto, Netzwerk und Anbieterantwort prüfen'} if item.get('platform')=='sms'
                        else line_labels if item.get('platform')=='line'
                        else irc_labels if item.get('platform')=='irc'
                        else ha_labels if item.get('platform')=='homeassistant' else transport_labels)
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
                    if item.get('platform') in {'ntfy','line','sms','email','feishu','dingtalk'}:
                        deadline=item.get('next_attempt',0)
                        extra=(' · nächste Anfrage: '+(datetime.datetime.fromtimestamp(deadline).strftime('%d.%m.%Y %H:%M:%S') if deadline>0 else 'keine Wartefrist')
                            +(' · letzter Fehler: '+labels[item['last_error']] if item.get('last_error') else ''))
                    if item.get('platform') in {'homeassistant','irc'}:
                        deadline=item.get('next_attempt',0);gap=item.get('gap_since',0)
                        extra=(' · nächste Anfrage: '+(datetime.datetime.fromtimestamp(deadline).strftime('%d.%m.%Y %H:%M:%S') if deadline>0 else 'keine Wartefrist')
                            +(' · unbeobachtete Ereignisse seit '+datetime.datetime.fromtimestamp(gap).strftime('%d.%m.%Y %H:%M:%S')
                                +' sind nicht verlässlich nachladbar; Wiederverbindung schließt diese Lücke nicht' if gap>0 else ''))
                    if item.get('platform')=='irc' and item.get('last_error'):
                        diagnostics={'protocol-refused':'Serverprotokoll abgelehnt; erforderliche IRCv3-Fähigkeiten prüfen',
                            'required-capabilities':'Server bestätigt erforderliche IRCv3-Fähigkeiten nicht',
                            'unsupported-case-mapping':'Server verwendet eine nicht unterstützte Namenszuordnung',
                            'nickname-in-use':'Bot-Nickname belegt; anderen Namen konfigurieren oder Freigabe abwarten',
                            'channel-full':'Kanal ist voll; Kanalverwaltung prüfen',
                            'channel-invite-required':'Bot muss zuerst in den Kanal eingeladen werden',
                            'channel-banned':'Bot oder Konto ist im Kanal gesperrt; Kanalrechte prüfen',
                            'channel-key-required':'Kanal verlangt einen gültigen privaten +k-Schlüssel',
                            'channel-not-found':'Freigegebener Kanal ist nicht verfügbar',
                            'account-required':'Server verlangt ein angemeldetes Konto; SASL konfigurieren',
                            'channel-forwarding-refused':'Server wollte in einen anderen Kanal umleiten; keine Freigabe geerbt',
                            'authentication-refused':'Server-/SASL-Anmeldung abgelehnt; Zugangsdaten und Konto prüfen',
                            'rate-limited':'Server begrenzt Anfragen; gespeicherte Wartefrist gilt',
                            'permission-revoked':'Owner-Freigabe entzogen oder geändert',
                            'tls-certificate':'TLS-Zertifikat oder Hostname nicht vertrauenswürdig; Serverzertifikat prüfen',
                            'tls-protocol':'Sichere TLS-Verbindung nicht verfügbar',
                            'dns':'Servername konnte nicht aufgelöst werden',
                            'connection-refused':'Server lehnt TCP-Verbindung ab; Adresse, Port und Firewall prüfen',
                            'timeout':'Server antwortet nicht rechtzeitig',
                            'connection-lost':'Verbindung oder vollständiger Protokollrahmen unterbrochen'}
                        extra+=' · letzter Fehler: '+diagnostics[item['last_error']]
                    self._label(recovery_frame,'Letzter Transportstatus · '+item['connector']+' · '+labels[item['status']]
                        +extra+' · Zeitpunkt '+str(item['updated_at']),size=10,color=self.MUTED).pack(anchor='w',pady=3)
                for history in value.get('history',[]):
                    self._label(recovery_frame, "Verlauf · " + history.get('binding_id',history['binding_digest'][:12]) + " · " + history_labels[history['status']],
                        size=10, color=self.MUTED).pack(anchor="w", pady=3)
                for refused in value.get('recovery_rejections',[]):
                    self._label(recovery_frame,'SMS/Twilio-Eingang '+refused['message_sid']+
                        ' abgelehnt: Text- oder Anhanggrenze überschritten bzw. leerer Inhalt. Keine Mission erstellt; spätere zulässige Nachrichten werden weiter nachgeladen.',
                        size=10,color=self.MUTED).pack(anchor='w',pady=3)
                for outgoing in value.get('native_outgoing',[]):
                    if outgoing.get('platform') in {'line','sms'}:
                        self._label(recovery_frame,('LINE' if outgoing['platform']=='line' else 'SMS/Twilio')+'-Ausgang · '+outgoing['delivery_id']+' · '+outgoing['state']
                            +' · Versuch '+str(outgoing['attempt'])+' · keine Empfangsbestätigung'
                            +(' · Serverannahme-Beleg '+outgoing['server_acceptance_receipt'] if outgoing.get('server_acceptance_receipt') else ''),
                            size=10,color=self.MUTED).pack(anchor='w',pady=3)
                    if outgoing.get('platform')=='irc':
                        self._label(recovery_frame,'IRC-Ausgang · '+outgoing['delivery_id']+' · '+outgoing['state']
                            +' · Server-Echos '+str(outgoing['confirmed_chunks'])+'/'+str(outgoing['chunk_count'])
                            +' · keine Empfangsbestätigung der Kanalmitglieder'
                            +(' · Prüfbeleg '+outgoing['server_echo_receipt'] if outgoing.get('server_echo_receipt') else ''),
                            size=10,color=self.MUTED).pack(anchor='w',pady=3)
                from .email_owner_gui import recovery as email_recovery
                email_recovery(self,recovery_frame,value,load_ingress,connector.get)
                from .feishu_owner_gui import recovery as feishu_recovery
                feishu_recovery(self,recovery_frame,value,load_ingress)
                from .dingtalk_owner_gui import recovery as dingtalk_recovery
                dingtalk_recovery(self,recovery_frame,value,load_ingress)
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
                    row=choices[selected.get()]
                    reason={'media-export-unavailable':'Ergebnisdatei vor dem Senden nicht verfügbar: lokalen Hermes-Dienst und Quellsitzung prüfen.',
                        'controller-event-context-damaged':'Controller-Ereigniskontext beschädigt: Dienste stoppen und Quelle sowie Zustellungsbelege unabhängig prüfen.',
                        'media-export-or-format-refused':'Keine Medien gesendet: separate Dateifreigabe, Quellpfad, Größen-/Formatgrenzen und öffentliche HTTPS-Einrichtung prüfen.'}.get(row.get('reason'),'')
                    details.configure(text='Mission: '+row['mission_id']+(' · '+reason if reason else ''))
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
            self._button(self.content,'Gespeicherte DingTalk-Quellen verwalten',lambda:self.show('gateway-dingtalk-sources')).pack(anchor='w',pady=6)
            self._button(self.content,'Gespeicherte DingTalk-Konvertierungen verwalten',lambda:self.show('gateway-dingtalk-outputs')).pack(anchor='w',pady=6)
            self._button(self.content,'Gespeicherte Feishu-Quellen verwalten',lambda:self.show('gateway-feishu-sources')).pack(anchor='w',pady=6)
            self._button(self.content,'Gespeicherte E-Mail-Originale verwalten',lambda:self.show('gateway-email-sources')).pack(anchor='w',pady=6)
            self._button(self.content,'Gespeicherte Gateway-Medien verwalten',lambda:self.show('gateway-media')).pack(anchor='w',pady=6)
            self._button(self.content,'Lokale Spracherkennung verwalten',lambda:self.show('gateway-speech')).pack(anchor='w',pady=6)
            self._catalogue("Alle Hermes-Plattformadapter anzeigen", gateway_rows())
        elif name=='gateway-dingtalk-sources':
            from .dingtalk_owner_gui import sources
            sources(self)
        elif name=='gateway-dingtalk-outputs':
            from .dingtalk_owner_gui import outputs
            outputs(self)
        elif name=='gateway-feishu-sources':
            from .feishu_owner_gui import sources
            sources(self)
        elif name=='gateway-email-sources':
            from .email_owner_gui import sources
            sources(self)
        elif name=='gateway-speech':
            self._head('Lokale Spracherkennung','Tiny · mehrsprachig · Verarbeitung auf diesem Gerät')
            self._label(self.content,'Die Einrichtung lädt einmalig etwa 75 MiB öffentliche Modelldateien über HTTPS. '
                'Audio wird anschließend lokal verarbeitet. Einzelne Gateway-Absender benötigen eine getrennte Freigabe. '
                'LINE-Sprachnachrichten werden erst nach separater Absenderfreigabe angenommen.',color=self.MUTED).pack(anchor='w',pady=8)
            details=self._label(self.content,'Status noch nicht geprüft.');details.pack(anchor='w',pady=8)
            def render(value):
                states=' · '.join(unit+': '+state['ActiveState'] for unit,state in value['services'].items())
                details.configure(text=('Sprachkomponente bereit' if value['runtime_ready'] else 'Lokale Sprachkomponente fehlt oder passt nicht; HAOS aktualisieren')+
                    '\n'+('Modell vollständig geprüft' if value['model_ready'] else 'Modell noch nicht vollständig verfügbar oder nicht lesbar')+
                    '\n'+('Lokaler Dienst konfiguriert' if value['enabled'] else 'Lokaler Dienst nicht aktiviert')+'\n'+states)
                installed=all(state['LoadState']=='loaded' for state in value['services'].values())
                activate.configure(state='normal' if value['runtime_ready'] and installed else 'disabled')
                deactivate.configure(state='normal' if value['enabled'] or any(state['ActiveState']=='active' for state in value['services'].values()) else 'disabled')
            self._button(self.content,'Spracherkennungsstatus prüfen',lambda:self._run_async(initial_setup.gateway_speech_status,
                success='Lokale Runtime, Modell und Dienste geprüft.',result_handler=render)).pack(anchor='w',pady=5)
            activate=self._button(self.content,'Modell laden und lokalen Dienst aktivieren',
                lambda:self._run_async(lambda:initial_setup.configure_gateway_speech(True),
                    success='Lokale Konfiguration gespeichert. Dienststatus und separate Absenderfreigaben beachten.',result_handler=render),primary=True)
            activate.configure(state='disabled');activate.pack(anchor='w',pady=5)
            deactivate=self._button(self.content,'Spracherkennungsdienst stoppen und deaktivieren',
                lambda:self._run_async(lambda:initial_setup.configure_gateway_speech(False),
                    success='Neue lokale Transkriptionen gestoppt; Modelle und Absenderrechte erhalten.',result_handler=render))
            deactivate.configure(state='disabled');deactivate.pack(anchor='w',pady=5)
            self._label(self.content,'Zum Entzug eines Absenders die Kopplung unter Gateways widerrufen. '
                'Das Stoppen des Transkriptionsdienstes ersetzt diesen Rechteentzug nicht.',size=10,color=self.MUTED).pack(anchor='w',pady=8)
            self._button(self.content,'Zurück zu Gateways',lambda:self.show('gateways')).pack(anchor='w',pady=5)
        elif name in {'gateway-media','gateway-cache'}:
            cache_mode=name=='gateway-cache'
            inspect_media=initial_setup.gateway_media_cache_inventory if cache_mode else initial_setup.gateway_media_inventory
            purge_media=initial_setup.purge_gateway_media_cache if cache_mode else initial_setup.purge_gateway_media
            self._head('Gateway-Zwischenspeicher' if cache_mode else 'Gateway-Medien verwalten',
                'Private Uploads prüfen; Missionen und Audit bleiben erhalten.')
            if cache_mode:
                self._label(self.content,'Vor einer Bereinigung zuerst die zugehörige Absenderfreigabe unter Gateways '
                    'entziehen oder ändern. Der private Gateway-Prozess prüft den Entzug erneut; bestehende Eingänge '
                    'und Audit bleiben erhalten.',color=self.MUTED).pack(anchor='w',pady=8)
            self._label(self.content,('Prüfen stoppt den Gateway-Dienst. Nur Cache-Einträge mit entzogener Freigabe können bereinigt werden. ' if cache_mode else
                'Prüfen stoppt Gateway- und Missionsdienste. Nur unzugeordnete Uploads oder Medien abgeschlossener Missionen können bereinigt werden. ') +
                'Dies löscht keine Agent-Kopien oder Backups '
                'und ist keine sichere physische Löschung.',color=self.MUTED).pack(anchor='w',pady=8)
            summary=self._label(self.content,'Noch keine privaten Medien geprüft.');summary.pack(anchor='w')
            selected=self._choice(self.content,'Upload auswählen',['Keine Auswahl'],'Keine Auswahl')
            details=self._label(self.content,'');details.pack(anchor='w',pady=8)
            note=self._field(self.content,'Prüfvermerk ohne Zugangsdaten')
            confirmed=tk.BooleanVar(value=False)
            tk.Checkbutton(self.content,text='Auswahl geprüft; gespeicherte Nutzdaten ausdrücklich entfernen',
                variable=confirmed,bg=self.PANEL,fg=self.TEXT,selectcolor=self.BG,
                wraplength=self.label_wrap).pack(anchor='w',pady=8)
            records={}
            def changed(*_args):
                confirmed.set(False)
                row=records.get(selected.get())
                details.configure(text=(f"Status: {row['state']} · Mission: {row['mission_id'] or 'keine'} · "
                    f"Missionsstatus: {row['mission_state'] or 'keiner'} · Nutzdaten: {row['stored_bytes']} Byte · "
                    +('Bereinigung zulässig' if row['purge_allowed'] else 'Bereinigung gesperrt')) if row else '')
            selected.trace_add('write',changed)
            def render(value):
                records.clear();records.update({row['id']:row for row in value['uploads']})
                summary.configure(text=f"Gespeichert: {value['stored_bytes']} Byte · Reserviert: {value['reserved_bytes']} / {value['limit_bytes']} Byte")
                menu=next(w for w in self.content.winfo_children() if isinstance(w,tk.OptionMenu))
                choices=menu['menu'];choices.delete(0,'end')
                for identity in records or ['Keine Auswahl']:
                    choices.add_command(label=identity,command=lambda key=identity:selected.set(key))
                selected.set(next(iter(records),'Keine Auswahl'))
            self._button(self.content,'Dienste stoppen und Medien prüfen',lambda:self._run_async(inspect_media,
                success='Private Medien geprüft; Dienste bleiben gestoppt.',result_handler=render)).pack(anchor='w',pady=5)
            def purge():
                identity=selected.get();row=records.get(identity);message=note.get();approval=confirmed.get()
                confirmed.set(False)
                if not row or not row['purge_allowed']:
                    def refuse():raise PermissionError('Eine bereinigbare geprüfte Auswahl ist erforderlich.')
                    self._run(refuse);return
                self._run_async(lambda:purge_media(identity,message,approval),
                    success='Ausgewählte Nutzdaten bereinigt; Mission, Audit und Metadaten erhalten.',
                    result_handler=lambda _:self.show(name))
            self._button(self.content,'Ausgewählte Medien bereinigen',purge).pack(anchor='w',pady=5)
            self._button(self.content,'Controller-Speicher anzeigen' if cache_mode else 'Gateway-Zwischenspeicher anzeigen',
                lambda:self.show('gateway-media' if cache_mode else 'gateway-cache')).pack(anchor='w',pady=5)
            self._button(self.content,'Zurück zu Gateways',lambda:self.show('gateways')).pack(anchor='w',pady=5)
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
