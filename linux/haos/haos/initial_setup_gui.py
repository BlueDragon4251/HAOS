"""Dedicated native graphical *local root seat* HAOS setup, not a web/agent API.

A separate X server with disabled TCP is required. This component ships
disabled while real UEFI/BIOS and input-device acceptance is pending.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import initial_setup


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
        self.root.attributes("-fullscreen", True)
        self.root.minsize(750, 500)
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
                             anchor="w", justify="left", wraplength=wrap)

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
        self.tk.OptionMenu(parent, value, *items).pack(anchor="w")
        return value

    def _build(self):
        tk = self.tk
        layout = tk.Frame(self.root, bg=self.BG)
        layout.pack(fill="both", expand=True, padx=45, pady=32)
        sidebar = tk.Frame(layout, bg=self.BG, width=225)
        sidebar.pack(side="left", fill="y", padx=(0, 28))
        sidebar.pack_propagate(False)
        self._label(sidebar, "◇ HAOS", size=27, color=self.CYAN, bold=True).pack(anchor="w", pady=(0, 8))
        self._label(sidebar, "ADMINISTRATOR SETUP", size=9, color=self.MUTED).pack(anchor="w", pady=(0, 28))
        items = [("security", "01  Sicherheit / Security"),
                 ("region", "02  Sprache / Keyboard"),
                 ("provider", "03  Hermes / Models"),
                 ("updates", "04  Updates / GHCR"),
                 ("gateways", "05  Gateways"),
                 ("finish", "06  Abschluss / Finish")]
        for name, title in items:
            self._button(sidebar, title, lambda p=name: self.show(p)).pack(fill="x", pady=5)
        self._label(sidebar, "LOCAL ROOT SETUP\nKein Fernzugriff und keine Agent-Rechte.",
                    size=9, color=self.MUTED, wrap=190).pack(side="bottom", anchor="w", pady=10)
        self.card = tk.Frame(layout, bg=self.PANEL, padx=34, pady=28,
                             highlightthickness=1, highlightbackground=self.BORDER)
        self.card.pack(side="left", fill="both", expand=True)
        self.status = self._label(self.card, "", size=10, color=self.MUTED)
        self.status.pack(side="bottom", fill="x", pady=(15, 0))
        self.content = tk.Frame(self.card, bg=self.PANEL)
        self.content.pack(side="top", fill="both", expand=True)
        self.show("security")

    def _head(self, title, subtitle):
        self._label(self.content, title, size=23, bold=True, wrap=770).pack(anchor="w", pady=(0, 8))
        self._label(self.content, subtitle, size=11, color=self.MUTED,
                    wrap=800).pack(anchor="w", pady=(0, 23))

    def _run(self, action, *, success="Gespeichert."):
        from tkinter import messagebox
        if self.running:
            self.status.config(text="Warte, bis die laufende Systemaktion beendet ist.", fg=self.MUTED)
            return None
        self.status.config(text="Wird sicher angewendet …", fg=self.MUTED)
        self.root.update_idletasks()
        try:
            result = action()
        except (RuntimeError, ValueError, PermissionError, OSError) as exc:
            # Credential material never belongs in UI exception text: existing
            # privileged helpers intentionally suppress stdout/stderr.
            self.status.config(text="Vorgang fehlgeschlagen; Änderungen wurden nicht bestätigt.", fg="#ffafba")
            messagebox.showerror("HAOS", "Vorgang nicht abgeschlossen. Prüfe Voraussetzungen oder Verbindung.")
            return None
        self.status.config(text=success, fg=self.CYAN)
        return result

    def _run_async(self, action, *, success="Gespeichert."):
        """Keep Tk's event loop responsive during authenticated slow system actions.

        Exactly one privileged mutation can be underway. No worker thread
        touches Tk; it reports only sanitized success/failure through a queue.
        """
        import queue
        import threading
        from tkinter import messagebox
        if self.running:
            self.status.config(text="Bitte warte, bis die aktuelle Systemaktion abgeschlossen ist.")
            return
        self.running = True
        self.status.config(text="Aktion läuft … Netzwerk und Datenträger können Zeit benötigen.",
                           fg=self.CYAN)
        results = queue.Queue(maxsize=1)

        def worker():
            try:
                action()
                results.put(True)
            except (RuntimeError, ValueError, PermissionError, OSError, TimeoutError):
                results.put(False)

        threading.Thread(target=worker, daemon=True, name="haos-setup-action").start()

        def poll():
            try:
                ok = results.get_nowait()
            except queue.Empty:
                self.root.after(150, poll)
                return
            self.running = False
            if ok:
                self.status.config(text=success, fg=self.CYAN)
            else:
                self.status.config(text="Aktion fehlgeschlagen; keine Bestätigung.", fg="#ffafba")
                messagebox.showerror("HAOS", "Aktion nicht abgeschlossen. Prüfe Internet, Credentials und Systemstatus.")
        self.root.after(150, poll)

    def show(self, name):
        tk = self.tk
        self.page = name
        for child in self.content.winfo_children():
            child.destroy()
        self.status.config(text="", fg=self.MUTED)
        if name == "security":
            self._head("Administrator & Wiederherstellung",
                       "Ein separates Administrator-Konto, niemals das Hermes-Konto. Zugangsdaten bleiben auf diesem Gerät.")
            status = self._run(initial_setup.account_status, success="")
            if status is None:
                return
            if not status["owner"]:
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
                box = tk.Text(self.content, height=11, width=60, font=("DejaVu Sans Mono", 10),
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
                       "Authentifizierte Konfiguration eines Providers. Mehrere aktive Provider/automatische Verteilung folgen nach Broker-Integration.")
            provider = self._choice(self.content, "Provider", ["openai", "openrouter", "local"], "openai")
            model = self._field(self.content, "Modellkennung, vom Provider unterstützt")
            endpoint = self._field(self.content, "Lokale URL nur für local", "http://127.0.0.1:11434/v1")
            secret = self._field(self.content, "API-Schlüssel · nicht gespeichert im GUI", secret=True)
            def apply():
                key=secret.get()
                secret.delete(0, tk.END)
                self._run_async(lambda: initial_setup.configure_provider(
                    provider.get(), model.get(), key, endpoint.get()))
            self._button(self.content, "Provider konfigurieren", apply, primary=True).pack(anchor="w", pady=22)
            self._label(self.content, "Codex-Kontologin und Multi-Provider-Auswahl sind in dieser Stufe noch nicht verfügbar.",
                        color=self.MUTED).pack(anchor="w")
        elif name == "updates":
            self._head("HAOS Updates",
                       "Stabiler oder privater Entwicklungszweig. Der vorherige bootc-Stand bleibt für Rollback erhalten.")
            username = self._field(self.content, "GitHub Benutzername (nur privater dev-Kanal)")
            token = self._field(self.content, "GHCR Read-only Token", secret=True)
            def save_token():
                secret = token.get()
                token.delete(0, tk.END)
                self._run_async(lambda: initial_setup.configure_ghcr(username.get(), secret),
                          success="Privates GHCR-Login geprüft und geschützt gespeichert.")
            self._button(self.content, "Dev-Token sicher hinterlegen", save_token).pack(anchor="w", pady=14)
            channel = self._choice(self.content, "Update-Kanal", ["stable", "dev"], "stable")
            automatic = tk.BooleanVar(value=False)
            tk.Checkbutton(self.content, text="Updates automatisch herunterladen (Neustart manuell)",
                           variable=automatic, bg=self.PANEL, fg=self.TEXT,
                           selectcolor=self.BG, activebackground=self.PANEL).pack(anchor="w", pady=9)
            self._button(self.content, "Kanal wählen und bootc-Image prüfen",
                         lambda: self._run_async(lambda: initial_setup.configure_update(channel.get(), automatic.get()),
                                           success="Bootc-Update vorbereitet. Neustart nach eigener Freigabe."),
                         primary=True).pack(anchor="w", pady=13)
        elif name == "gateways":
            self._head("Hermes · Gateways",
                       "Verbinde einen Bot und autorisiere nur konkrete Absender. Andere Hermes-Adapter müssen zuerst sicher integriert werden.")
            connector = self._field(self.content, "Konnektor-ID (z. B. telegram-main)", "telegram-main")
            platform = self._choice(self.content, "Plattform", ["telegram", "discord"], "telegram")
            token = self._field(self.content, "Bot-Token (wird niemals im GUI gespeichert)", secret=True)
            def configure():
                secret = token.get()
                token.delete(0, tk.END)
                self._run_async(lambda: initial_setup.configure_gateway(
                    connector.get(), platform.get(), secret),
                    success="Gateway gespeichert. Neustart des Gateway-Dienstes erforderlich.")
            self._button(self.content, "Gateway sicher anlegen", configure, primary=True).pack(anchor="w", pady=10)
            self._label(self.content, "Genau einen Absender freigeben", color=self.CYAN,
                        size=13, bold=True).pack(anchor="w", pady=(14, 0))
            binding = self._field(self.content, "Freigabe-ID (z. B. mein-handy)", "my-device")
            sender = self._field(self.content, "Absender-ID aus der jeweiligen Plattform")
            chat = self._field(self.content, "Chat-ID der jeweiligen Plattform")
            identity = self._field(self.content, "HAOS-Identität", "personal")
            self._button(self.content, "Absender mit Lesen/Erstellen freigeben",
                         lambda: self._run_async(lambda: initial_setup.pair_gateway_sender(
                             binding.get(), connector.get(), sender.get(), chat.get(), identity.get()),
                             success="Absender explizit freigegeben. Gateway-Neustart erforderlich."),
                         primary=True).pack(anchor="w", pady=(10, 0))
        elif name == "finish":
            self._head("Einrichtung abschließen",
                       "Erst nach Administrator + Recovery kann die normale HAOS-Sitzung sicher starten.")
            status = self._run(initial_setup.account_status, success="")
            if status is None:
                return
            ready = status["complete"] and not (self.codes and not self.codes_confirmed)
            self._label(self.content,
                "✓ Administratorkonto und Recovery vorhanden" if ready
                else "Administrator und Wiederherstellungscodes müssen zuerst eingerichtet werden.",
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
