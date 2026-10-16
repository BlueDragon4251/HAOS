#!/usr/bin/env python3
"""HAOS graphical Live installer welcome screen (X11 kiosk, no credentials stored)."""
import subprocess
import tkinter as tk
from tkinter import messagebox

BG = "#070D1C"
CARD = "#101D33"
EDGE = "#28415D"
FG = "#E7F1FF"
MUTED = "#92A6C2"
CYAN = "#47F3E0"
BLUE = "#5798FF"

class Welcome(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Herald OS • Installer")
        self.configure(bg=BG)
        self.attributes("-fullscreen", True)
        self.geometry("1200x740")
        self.bind("<Escape>", lambda e: None)
        self.bind("<Control-Shift-D>", self.open_dev)
        self.bind("<Control-Shift-d>", self.open_dev)
        self.sequence = ""
        self.bind_all("<Key>", self.key_sequence, add="+")
        self.build()
        self.after(1500, self.refresh_network)

    def key_sequence(self, event):
        if not event.char or event.char not in ":dev":
            self.sequence = ""
            return
        self.sequence = (self.sequence + event.char)[-4:]
        if self.sequence == ":dev":
            self.sequence = ""
            self.open_dev()

    def text(self, parent, value, size, color=FG, weight="normal", **kwargs):
        widget = tk.Label(parent, text=value, bg=parent.cget("bg"),
                          fg=color, font=("DejaVu Sans", size, weight), **kwargs)
        widget.pack(anchor="w")
        return widget

    def command(self, parent, label, callback, bg, fg=BG):
        button = tk.Button(
            parent, text=label, command=callback,
            bg=bg, fg=fg, activebackground=BLUE, activeforeground=BG,
            font=("DejaVu Sans", 13, "bold"), relief="flat",
            bd=0, padx=23, pady=14, cursor="hand2", highlightthickness=0
        )
        button.pack(anchor="w", pady=(22, 0))
        return button

    def build(self):
        frame = tk.Frame(self, bg=BG, padx=66, pady=44)
        frame.pack(fill="both", expand=True)
        bar = tk.Frame(frame, bg=BG)
        bar.pack(fill="x")
        tk.Label(bar, text="◈  HERALD OS", fg=CYAN, bg=BG,
                 font=("DejaVu Sans", 17, "bold")).pack(side="left")
        tk.Label(bar, text="HERMES  /  NETWORK INSTALLER",
                 fg=MUTED, bg=BG, font=("DejaVu Sans", 11)).pack(side="right")
        tk.Frame(frame, height=2, bg=EDGE).pack(fill="x", pady=(26, 34))
        self.text(frame, "Welcome to Herald OS", 32, FG, "bold")
        tk.Frame(frame, height=15, bg=BG).pack()
        self.text(frame, "Choose how you want to prepare this computer.",
                  15, MUTED)
        tk.Frame(frame, height=30, bg=BG).pack()
        card = tk.Frame(frame, bg=CARD, highlightbackground=EDGE,
                        highlightthickness=1, padx=28, pady=28)
        card.pack(fill="x")
        self.text(card, "PUBLIC RELEASE", 11, CYAN, "bold")
        tk.Frame(card, height=12, bg=CARD).pack()
        self.text(card, "Install stable HAOS", 24, FG, "bold")
        tk.Frame(card, height=10, bg=CARD).pack()
        self.text(card, "Download an explicitly published, digest-pinned OS image",
                  12, MUTED)
        self.text(card, "and install it to a disk of your choice.", 12, MUTED)
        self.command(card, "Continue to installation   →",
                     lambda: self.open_terminal("HAOS Stable Installation",
                                                "/usr/local/sbin/haos-install.sh",
                                                "--stable"), CYAN)
        tk.Frame(frame, height=26, bg=BG).pack()
        bar2 = tk.Frame(frame, bg=BG)
        bar2.pack(fill="x")
        self.network = tk.Label(bar2, text="● Checking network…",
                                bg=BG, fg=MUTED, font=("DejaVu Sans", 12))
        self.network.pack(side="left")
        tk.Button(bar2, text="Network settings", fg=FG, bg=EDGE,
                  font=("DejaVu Sans", 11), relief="flat", padx=16, pady=10,
                  command=lambda: self.open_terminal("Network Settings",
                                                     "/usr/bin/nmtui")).pack(side="right")
        tk.Label(frame,
                 text="USB / iVentoy PXE  •  Your disk is untouched until installation is confirmed.",
                 bg=BG, fg=MUTED, font=("DejaVu Sans", 10)).pack(side="bottom", anchor="w", pady=(20, 0))

    def open_dev(self, event=None):
        if messagebox.askyesno("Developer channel",
                               "Open private GHCR image selection?\n"
                               "A token is required. Do not install to a disk containing important data."):
            self.open_terminal("HAOS Developer Installation",
                               "/usr/local/sbin/private-install.sh", "--select-dev")

    def open_terminal(self, title, path, *arguments):
        try:
            subprocess.Popen([
                "/usr/bin/xterm", "-hold", "-T", title,
                "-fa", "DejaVu Sans Mono", "-fs", "14",
                "-bg", BG, "-fg", FG, "-geometry", "106x31",
                "-e", "/usr/bin/bash", path, *arguments
            ])
        except OSError as exc:
            messagebox.showerror("Unable to open installer", str(exc))

    def refresh_network(self):
        try:
            status = subprocess.run(
                ["/usr/bin/nmcli", "-t", "-f", "STATE", "general"],
                capture_output=True, text=True, timeout=3
            )
            ok = status.returncode == 0 and "connected" in status.stdout
            self.network.configure(
                text="● Network connected" if ok else "● Network not connected",
                fg=CYAN if ok else "#FFA75E"
            )
        except Exception:
            self.network.configure(text="● Network status unavailable", fg=MUTED)
        self.after(8000, self.refresh_network)

if __name__ == "__main__":
    Welcome().mainloop()
