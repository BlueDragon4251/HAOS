"""Dedicated native graphical *local root seat* HAOS setup, not a web/agent API.

A separate X server with disabled TCP is required. This component ships
disabled while real UEFI/BIOS and input-device acceptance is pending.
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

    def _choice(self, parent, label, items, default):
        self._label(parent, label, size=10, color=self.MUTED).pack(anchor="w", pady=(14, 4))
        value = self.tk.StringVar(value=default)
        control = self.tk.OptionMenu(parent, value, *items)
        control.configure(bg=self.PANEL2, fg=self.TEXT, activebackground=self.BORDER,
                          activeforeground=self.TEXT, highlightthickness=0,
                          relief="flat", bd=1, font=("DejaVu Sans", 11))
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

    def _run_async(self, action, *, success="Gespeichert.", completed=None):
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
                action()
                results.put((True, None))
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
            else:
                self._show_error(report)
        self.root.after(150, poll)

    def show(self, name):
        tk = self.tk
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
            provider = self._choice(self.content, "Provider", sorted(http_providers() | oauth_providers() | CLOUD | {"local", "lmstudio", "gemini", "custom", "copilot"}), "openai-api")
            model = self._field(self.content, "Modellkennung, vom Provider unterstützt")
            endpoint = self._field(self.content, "URL · leer = Standard des Anbieters")
            mode = self._choice(self.content, "Protokoll · automatisch oder explizit für Modell-/Abo-Varianten",
                                ["auto", "chat_completions", "codex_responses", "anthropic_messages"], "auto")
            secret = self._field(self.content, "API-Schlüssel · nicht gespeichert im GUI", secret=True)
            self._label(self.content,
                "Cloud-SDKs: AWS erwartet JSON mit access_key_id / secret_access_key, optional session_token oder profile. "
                "Vertex erwartet Service-Account-/Authorized-User-JSON und die vollständige OpenAPI-URL. "
                "Azure akzeptiert einen API-Key oder JSON mit tenant_id / client_id / client_secret. "
                "Ein leeres Cloud-Feld verwendet ausschließlich die SDK-Identität des getrennten Provider-Dienstes.",
                size=10, color=self.MUTED).pack(anchor="w", pady=8)
            def account(action):
                if self.running:
                    return
                selected_provider = provider.get()
                self.root.withdraw()
                self._run_async(lambda: initial_setup.provider_account(selected_provider, action),
                                success="Konto-Aktion abgeschlossen. Provider anschließend konfigurieren.",
                                completed=self.root.deiconify)
            login_button = self._button(self.content, "Mit Anbieter-Konto anmelden (OAuth / Device-Code)",
                                        lambda: account("login"))
            login_button.pack(anchor="w", pady=8)
            logout_button = self._button(self.content, "Anbieter-Konto abmelden", lambda: account("logout"))
            logout_button.pack(anchor="w", pady=4)
            def update_provider(*_args):
                available = provider.get() in account_providers()
                for button in (login_button, logout_button):
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
            self._label(self.content,
                "Zuerst die beteiligten Provider und Modelle konfigurieren. Ein Preset verwendet ein oder zwei "
                "Referenzmodelle und ein Aggregator-Modell. Alle Anfragen laufen über die bereits freigegebenen Broker-Routen.",
                size=10, color=self.MUTED).pack(anchor="w")
            moa_name = self._field(self.content, "MoA-Presetname", "personal")
            moa_value = self._field(self.content, "Preset-JSON · references und aggregator, jeweils route / model")
            def apply_moa():
                selected_name, value = moa_name.get(), moa_value.get()
                self._run_async(lambda: initial_setup.configure_moa(selected_name, value),
                                success="MoA-Preset mit freigegebenen Broker-Routen als Standard gespeichert.")
            self._button(self.content, "MoA-Preset sicher konfigurieren", apply_moa).pack(anchor="w", pady=10)
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
            connector = self._field(self.content, "Konnektor-ID (z. B. telegram-main)", "telegram-main")
            platform = self._choice(self.content, "Plattform", ["telegram", "discord"], "telegram")
            token = self._field(self.content, "Bot-Token (wird niemals im GUI gespeichert)", secret=True)
            def configure():
                secret = token.get()
                token.delete(0, tk.END)
                selected_connector, selected_platform = connector.get(), platform.get()
                self._run_async(lambda: initial_setup.configure_gateway(
                    selected_connector, selected_platform, secret),
                    success="Gateway gespeichert. Neustart des Gateway-Dienstes erforderlich.")
            self._button(self.content, "Gateway sicher anlegen", configure, primary=True).pack(anchor="w", pady=10)
            self._label(self.content, "Genau einen Absender freigeben", color=self.CYAN,
                        size=13, bold=True).pack(anchor="w", pady=(14, 0))
            binding = self._field(self.content, "Freigabe-ID (z. B. mein-handy)", "my-device")
            sender = self._field(self.content, "Absender-ID aus der jeweiligen Plattform")
            chat = self._field(self.content, "Chat-ID der jeweiligen Plattform")
            identity = self._field(self.content, "HAOS-Identität", "personal")
            def pair_sender():
                selected = (binding.get(), connector.get(), sender.get(), chat.get(), identity.get())
                self._run_async(lambda: initial_setup.pair_gateway_sender(*selected),
                                success="Absender explizit freigegeben. Gateway-Neustart erforderlich.")
            self._button(self.content, "Absender mit Lesen/Erstellen freigeben",
                         pair_sender, primary=True).pack(anchor="w", pady=(10, 0))
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
