#!/usr/bin/env python3
"""Full-screen graphical HAOS installation wizard for USB and iVentoy boots."""
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import haos_install_core as core

BG, CARD, EDGE = "#070D1C", "#101D33", "#28415D"
FG, MUTED, CYAN, ERROR = "#E7F1FF", "#92A6C2", "#47F3E0", "#FFAE81"


class Wizard(tk.Tk):
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
        self.title("Herald OS - Installation")
        self.configure(bg=BG)
        w, h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.compact = w < 1000 or h < 650
        self.geometry(f"{w}x{h}+0+0")
        self.attributes("-fullscreen", True)
        self.session = core.RegistrySession()
        self.messages = queue.Queue()
        self.waiting = False
        self.started_install = False
        self.cancel_event = None
        self.timer = 0.0
        self.image = None
        self.disk = None
        self.protocol("WM_DELETE_WINDOW", self.exit)
        self.bind("<Escape>", lambda e: self.exit())
        self.bind("<F3>", lambda e: self.open_network_settings())
        self.bind("<F4>", lambda e: self.cycle_keyboard())
        self.keyboard = 0
        self.keyboards = [("Österreich", "at"), ("Deutschland", "de"), ("US", "us")]
        self.setup()
        self.page_network()
        self.after(150, self.poll)

    def setup(self):
        self.header = tk.Frame(self, bg=BG, padx=20 if self.compact else 60, pady=12)
        self.header.pack(fill="x")
        self.label(self.header, "◈  HERALD OS    /    INSTALLATION",
                   12 if self.compact else 18, CYAN, True)
        self.content = tk.Frame(self, bg=BG, padx=20 if self.compact else 60)
        self.content.pack(fill="both", expand=True)
        self.footer = tk.Frame(self, bg=BG, padx=20 if self.compact else 60, pady=12)
        self.footer.pack(fill="x")
        self.status = tk.StringVar(value="Bereit")
        tk.Label(self.footer, textvariable=self.status, font=("DejaVu Sans", 10),
                 fg=MUTED, bg=BG, anchor="w").pack(side="left")
        self.actions = tk.Frame(self.footer, bg=BG)
        self.actions.pack(side="right")

    def label(self, container, text, size=12, color=FG, bold=False):
        obj = tk.Label(container, text=text, font=("DejaVu Sans", size, "bold" if bold else "normal"),
                       fg=color, bg=container.cget("bg"), justify="left", anchor="w", wraplength=max(300, self.winfo_screenwidth()-140))
        obj.pack(anchor="w", pady=4)
        return obj

    def button(self, text, fn, accent=False):
        b = tk.Button(self.actions, text=text, command=fn, relief="flat",
                      bg=CYAN if accent else EDGE, fg=BG if accent else FG,
                      activebackground="#5798FF", font=("DejaVu Sans", 11, "bold"),
                      padx=15, pady=8, takefocus=True, cursor="hand2")
        b.pack(side="right", padx=4)
        return b

    def reset(self, title, description):
        for c in self.content.winfo_children(): c.destroy()
        for c in self.actions.winfo_children(): c.destroy()
        self.label(self.content, title, 20 if self.compact else 32, FG, True)
        self.label(self.content, description, 10 if self.compact else 13, MUTED)
        tk.Frame(self.content, bg=EDGE, height=2).pack(fill="x", pady=10)
        self.status.set("USB / iVentoy HTTP PXE  ·  Noch keine Datenträgeränderungen")
        self.button("Abbrechen", self.exit)

    def entry(self, caption, *, secret=False, preset=""):
        self.label(self.content, caption, 11, CYAN)
        widget = tk.Entry(self.content, bg=CARD, fg=FG, insertbackground=CYAN,
                          font=("DejaVu Sans Mono", 12), relief="flat",
                          show="●" if secret else "", width=50)
        widget.insert(0, preset)
        widget.pack(anchor="w", fill="x", pady=(0, 9))
        return widget

    def page_network(self):
        self.reset("Netzwerkverbindung",
                   "GHCR benötigt Internet über HTTPS (Port 443). Der PXE-Start über LAN reicht dafür nicht aus.")
        self.label(self.content, "Die Prüfung testet DNS UND die echte TLS-Verbindung zu ghcr.io.", 12)
        self.button("Verbindung prüfen", self.verify_network, True)
        self.button("Netzwerk einrichten (F3)", self.open_network_settings)
        self.verify_network()

    def verify_network(self):
        def done(result):
            self.label(self.content, result, 12, CYAN)
            self.button("Weiter →", self.page_auth if self.channel == "dev" else self.fetch_stable, True)
        self.async_action("Verbinde mit ghcr.io:443", core.check_network, done,
                          retry=self.page_network)

    def open_network_settings(self):
        import subprocess
        try:
            subprocess.Popen(["xterm", "-T", "Netzwerkverbindung (nmtui)",
                              "-fa", "DejaVu Sans Mono", "-fs", "12",
                              "-e", "/usr/bin/nmtui"])
        except OSError as err:
            messagebox.showerror("Netzwerk", str(err), parent=self)

    def cycle_keyboard(self):
        import subprocess
        self.keyboard = (self.keyboard + 1) % len(self.keyboards)
        label, layout = self.keyboards[self.keyboard]
        try:
            subprocess.run(["setxkbmap", "-layout", layout], check=True, timeout=4)
            self.status.set("Tastaturlayout: " + label)
        except Exception as exc:
            self.error(exc, self.page_network)

    def page_auth(self):
        self.reset("Entwicklerzugang", "Privates GHCR-Image: Token per USB, HTTPS oder manuell.")
        self.label(self.content, "GitHub Benutzername", 11, CYAN)
        self.user = self.entry("", preset="BlueDragon4251")
        self.mode = tk.StringVar(value="usb")
        row = tk.Frame(self.content, bg=BG)
        row.pack(anchor="w", pady=6)
        for caption, val in [("USB-Stick", "usb"), ("HTTPS", "https"), ("Manuell", "manual")]:
            tk.Radiobutton(row, text=caption, variable=self.mode, value=val,
                           fg=FG, bg=BG, selectcolor=CARD, activebackground=BG,
                           activeforeground=CYAN, command=self.auth_mode).pack(side="left", padx=6)
        self.auth_area = tk.Frame(self.content, bg=BG)
        self.auth_area.pack(fill="x", pady=3)
        self.auth_mode()
        self.button("Verbinden →", self.connect_registry, True)
        self.button("← Netzwerk", self.page_network)

    def auth_mode(self):
        for child in self.auth_area.winfo_children(): child.destroy()
        self.usb_choices = []
        if self.mode.get() == "usb":
            try:
                self.usb_choices = core.token_partitions()
            except Exception as exc:
                self.label(self.auth_area, "USB-Erkennung: "+str(exc), 10, ERROR)
            self.label(self.auth_area, "Nur USB-Partitionen mit Dateisystem (kein /dev/sda-Laufwerk).", 10)
            choices = [f'{d["path"]}  ({d["size"]//(1024**2)} MiB, {d["fstype"]})'
                       for d in self.usb_choices]
            self.usb_value = tk.StringVar(value=choices[0] if choices else "")
            if choices:
                tk.OptionMenu(self.auth_area, self.usb_value, *choices).pack(anchor="w")
            else:
                self.label(self.auth_area, "Kein Token-USB-Stick gefunden.", 11, ERROR)
            tk.Button(self.auth_area, text="USB neu suchen", command=self.auth_mode,
                      bg=EDGE, fg=FG).pack(anchor="w", pady=5)
            self.label(self.auth_area, "Datei: HAOS-DEV/token.txt oder token.txt", 10, MUTED)
        elif self.mode.get() == "https":
            self.url_field = self.entry_in(self.auth_area, "Geschützte HTTPS-Token-URL")
            self.label(self.auth_area, "Keine Zugangsdaten über iVentoy HTTP/TFTP übertragen.", 10, ERROR)
        else:
            self.token_field = self.entry_in(self.auth_area, "GitHub-Token (unsichtbar)", secret=True)

    def entry_in(self, parent, caption, secret=False):
        self.label(parent, caption, 11, CYAN)
        widget = tk.Entry(parent, bg=CARD, fg=FG, insertbackground=CYAN,
                          font=("DejaVu Sans Mono", 12), relief="flat",
                          show="●" if secret else "")
        widget.pack(anchor="w", fill="x", pady=5)
        return widget

    def connect_registry(self):
        username = self.user.get().strip()
        kind = self.mode.get()
        if kind == "usb":
            selected = self.usb_value.get().split()[0] if self.usb_choices else ""
            if not selected:
                self.error(core.InstallerError("USB-Stick wählen oder einstecken."), self.page_auth)
                return
            source = selected
        elif kind == "https":
            source = self.url_field.get().strip()
        else:
            source = self.token_field.get()
            self.token_field.delete(0, "end")

        def connect():
            core.check_network()
            if kind == "usb": token = core.read_usb_token(source)
            elif kind == "https": token = core.https_token(source)
            else: token = core.check_token(source)
            self.session.login(username, token)
            return self.session.tags()

        def done(tags):
            if not tags:
                self.error(core.InstallerError("Keine HAOS dev-Images gefunden."), self.page_auth)
            else:
                self.page_tags(tags)
        self.async_action("Anmeldung und Versionsliste laden", connect, done,
                          retry=self.page_auth)

    def page_tags(self, tags):
        self.reset("Entwicklungsimage auswählen",
                   "Eintrag auswählen: Der feste SHA256-Digest wird automatisch ermittelt.")
        self.tags = list(tags)
        self.tag_list = tk.Listbox(self.content, bg=CARD, fg=FG, selectbackground=EDGE,
                                   font=("DejaVu Sans Mono", 12), height=8,
                                   exportselection=False, relief="flat")
        self.tag_list.pack(anchor="w", fill="x")
        for tag in tags: self.tag_list.insert("end", tag)
        self.label(self.content, "Die Sortierung nach Tag ist keine bestätigte Veröffentlichungsreihenfolge.", 10, MUTED)
        self.button("Image prüfen →", self.select_tag, True)
        self.button("← Anmeldung", self.page_auth)

    def select_tag(self):
        sel = self.tag_list.curselection()
        if not sel:
            messagebox.showwarning("Image", "Bitte erst einen Container auswählen.", parent=self)
            return
        tag = self.tags[sel[0]]
        def done(image):
            self.image = image
            self.page_disks()
        self.async_action("SHA256-Digest von GHCR abrufen", lambda: self.session.pin(tag),
                          done, retry=lambda: self.page_tags(self.tags))

    def fetch_stable(self):
        def done(image):
            self.image = image
            self.page_disks()
        self.async_action("Öffentliches Stable-Manifest prüfen",
                          self.session.public_image, done, retry=self.page_network)

    def page_disks(self):
        def done(disks):
            self.display_disks(disks)
        self.async_action("Nur geeignete interne Datenträger erkennen",
                          core.internal_disks, done, retry=self.page_disks)

    def display_disks(self, disks):
        self.reset("Zielfestplatte auswählen",
                   "USB-Sticks, Netzwerk-Blockgeräte, RAM, Loops und zu kleine Laufwerke werden ausgeblendet.")
        self.disks = disks
        self.disk_list = tk.Listbox(self.content, bg=CARD, fg=FG, selectbackground=EDGE,
                                   font=("DejaVu Sans Mono", 11), height=5,
                                   exportselection=False, relief="flat")
        self.disk_list.pack(fill="x", anchor="w")
        for d in disks:
            self.disk_list.insert("end", f'{d["path"]}  |  {int(d["size"])/(1024**3):.0f} GiB  |  {d.get("model") or "Interne SSD"}')
        if not disks:
            self.label(self.content, "Keine geeignete interne SSD erkannt. F5 Diagnose im Hauptmenü.", 12, ERROR)
        self.label(self.content, "WARNUNG: Auf dem ausgewählten Datenträger werden ALLE Partitionen gelöscht.", 12, ERROR)
        self.button("Image herunterladen →", self.choose_disk, True)
        self.button("← Image-Auswahl", lambda: self.page_tags(self.tags) if self.channel == "dev" else self.page_network)

    def choose_disk(self):
        selected = self.disk_list.curselection()
        if not selected:
            messagebox.showwarning("Ziellaufwerk", "Interne SSD ausdrücklich auswählen.", parent=self)
            return
        self.disk = self.disks[selected[0]]["path"]
        def download():
            core.check_network()
            self.session.pull(self.image)
            return True
        self.async_action("HAOS-Container herunterladen (bis 30 Minuten)", download,
                          lambda _result: self.page_confirm(), retry=self.page_disks)

    def page_confirm(self):
        self.reset("Installation ausdrücklich bestätigen",
                   "Der Container wurde geladen. Das nächste Bestätigen überschreibt die gesamte SSD.")
        self.label(self.content, f"Ziel: {self.disk}", 15, ERROR, True)
        self.label(self.content, "Zur Bestätigung die exakte Geräteadresse eintippen:", 11)
        self.disk_confirm = self.entry("", preset="")
        self.label(self.content, "Zusätzlich WIPE eintippen:", 11)
        self.wipe_confirm = self.entry("")
        self.button("Unwiderruflich installieren", self.confirm_install, True)
        self.button("← Zielfestplatte", self.page_disks)

    def confirm_install(self):
        if self.disk_confirm.get().strip() != self.disk or self.wipe_confirm.get().strip() != "WIPE":
            messagebox.showerror("Nicht bestätigt", "Vollständiger Datenträgerpfad und WIPE müssen genau übereinstimmen.", parent=self)
            return
        if not messagebox.askyesno("ALLE DATEN LÖSCHEN",
                                  f"Wirklich ALLE Partitionen und Daten auf {self.disk} löschen?\n"
                                  "Dieser Schritt lässt sich NICHT rückgängig machen.", parent=self):
            return
        self.started_install = True
        self.async_action("HAOS auf die SSD installieren (bis 60 Minuten)",
                          lambda: self.session.install(self.image, self.disk),
                          lambda _: self.done(), retry=None)

    def done(self):
        self.reset("Installation abgeschlossen",
                   "HAOS wurde auf die SSD geschrieben. Token und Installationsmedium entfernen, dann neu starten.")
        self.label(self.content, "Private GHCR-Updates benötigen später eine eigene Read-only-Anmeldung.", 11, MUTED)
        self.button("Schließen", self.exit, True)

    def error(self, exc, retry):
        detail = str(exc)[-1500:]
        self.reset("Aktion fehlgeschlagen", "Es wurde kein weiterer Installationsschritt automatisch gestartet.")
        self.label(self.content, detail, 11, ERROR)
        if self.started_install:
            self.label(self.content,
                       "Die SSD kann teilweise verändert sein. NICHT automatisch erneut installieren.",
                       11, ERROR, True)
        elif retry:
            self.button("Erneut versuchen / zurück", retry, True)
        self.button("Netzwerk einrichten", self.open_network_settings)
        self.status.set("Fehler – du kannst zurück, erneut versuchen oder abbrechen.")

    def async_action(self, description, operation, callback, retry=None):
        if self.waiting: return
        self.waiting = True
        self.timer = time.monotonic()
        self.status.set(description + " …")
        for widget in self.actions.winfo_children():
            widget.configure(state="disabled")
        self.cancel_event = threading.Event()
        self.session.cancel_event = self.cancel_event
        self.stop_button = self.button("Vorgang abbrechen", self.cancel_operation)
        def run():
            try:
                result = operation()
                if self.cancel_event.is_set():
                    raise core.InstallerError("Vorgang vom Benutzer abgebrochen.")
                self.messages.put((True, result, callback, retry))
            except Exception as exc:
                self.messages.put((False, exc, callback, retry))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                success, value, callback, retry = self.messages.get_nowait()
                self.waiting = False
                if hasattr(self, "stop_button") and self.stop_button.winfo_exists():
                    self.stop_button.destroy()
                for widget in self.actions.winfo_children():
                    widget.configure(state="normal")
                if success: callback(value)
                else: self.error(value, retry)
        except queue.Empty:
            pass
        if self.waiting:
            seconds = int(time.monotonic() - self.timer)
            self.status.set(f"Bitte warten: Vorgang läuft seit {seconds} Sekunden (mit Zeitlimit).")
        self.after(300, self.poll)

    def cancel_operation(self):
        if self.cancel_event is not None:
            self.cancel_event.set()
            if hasattr(self, "stop_button") and self.stop_button.winfo_exists():
                self.stop_button.configure(state="disabled")
            self.status.set("Vorgang wird abgebrochen … bitte kurz warten.")

    def exit(self):
        if self.waiting:
            messagebox.showwarning("Vorgang läuft",
                                   "Du kannst den laufenden Vorgang über 'Vorgang abbrechen' beenden. "
                                   "Eine begonnene Installation kann dadurch unvollständig bleiben.", parent=self)
            return
        self.session.close()
        self.destroy()


if __name__ == "__main__":
    mode = "--stable" if "--stable" in sys.argv[1:] else "--dev"
    Wizard("stable" if mode == "--stable" else "dev").mainloop()
