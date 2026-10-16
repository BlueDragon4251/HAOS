#!/usr/bin/env python3
"""Keyboard-first, screen-sized HAOS live installer kiosk (X11 + Openbox)."""
import subprocess
import tkinter as tk
from tkinter import messagebox

BG, CARD, EDGE = "#070D1C", "#101D33", "#28415D"
FG, MUTED, CYAN = "#E7F1FF", "#92A6C2", "#47F3E0"


def layout_for_screen(width, height):
    """Keep all important controls visible on 640x480 UEFI VGA displays."""
    compact = width < 1024 or height < 650
    return {
        "compact": compact,
        "padx": 18 if compact else 64,
        "pady": 12 if compact else 38,
        "heading": 20 if compact else 32,
        "body": 10 if compact else 14,
        "card_heading": 16 if compact else 24,
        "button": 11 if compact else 13,
        "gap": 10 if compact else 24,
    }


class Welcome(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Herald OS - Installer")
        self.configure(bg=BG, cursor="arrow")
        # Xorg without a window manager may ignore _NET_WM_STATE_FULLSCREEN.
        # Always set the real screen size explicitly; never use 1200x740.
        self.screen_w, self.screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.cfg = layout_for_screen(self.screen_w, self.screen_h)
        self.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
        self.attributes("-fullscreen", True)
        self.resizable(True, True)
        self.bind("<Control-Shift-D>", self.open_dev)
        self.bind("<Control-Shift-d>", self.open_dev)
        self.bind("<F12>", self.open_dev)
        self.bind("<F2>", self.open_text_console)
        self.bind("<F3>", self.open_network)
        self.bind("<F4>", self.cycle_keyboard)
        self.bind("<KeyPress-1>", self.open_stable)
        self.bind("<KeyPress-2>", self.open_network)
        self.bind("<Escape>", self.show_help)
        self.bind_all("<Key>", self.key_sequence, add="+")
        self.sequence = ""
        self.keyboards = [("Deutsch (AT)", "at"), ("Deutsch (DE)", "de"), ("English (US)", "us")]
        self.keyboard_index = 0
        self.build()
        self.after(200, self.acquire_focus)
        self.after(1500, self.refresh_network)

    def acquire_focus(self):
        self.lift()
        self.focus_force()
        self.stable_button.focus_force()
        self.update_idletasks()

    def key_sequence(self, event):
        # Hidden :dev is an alternative to Ctrl+Shift+D / F12.
        char = event.char or ""
        self.sequence = (self.sequence + char)[-4:] if char in ":dev" else ""
        if self.sequence == ":dev":
            self.sequence = ""
            self.open_dev()

    def label(self, parent, text, size=12, color=FG, bold=False, **kwargs):
        widget = tk.Label(
            parent, text=text, bg=parent.cget("bg"), fg=color,
            font=("DejaVu Sans", size, "bold" if bold else "normal"),
            anchor="w", **kwargs
        )
        widget.pack(anchor="w")
        return widget

    def button(self, parent, text, command, accent=False):
        cfg = self.cfg
        widget = tk.Button(
            parent, text=text, command=command, cursor="hand2",
            bg=CYAN if accent else EDGE, fg=BG if accent else FG,
            activebackground="#5798FF", activeforeground=BG,
            font=("DejaVu Sans", cfg["button"], "bold"),
            relief="flat", bd=0, padx=15, pady=7 if cfg["compact"] else 12,
            highlightthickness=2, highlightbackground=EDGE,
            highlightcolor=CYAN, takefocus=True
        )
        widget.pack(anchor="w", pady=(cfg["gap"], 0))
        widget.bind("<Return>", lambda e: (widget.invoke(), "break")[1])
        widget.bind("<space>", lambda e: (widget.invoke(), "break")[1])
        return widget

    def build(self):
        cfg = self.cfg
        main = tk.Frame(self, bg=BG, padx=cfg["padx"], pady=cfg["pady"])
        main.pack(fill="both", expand=True)
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x")
        self.label(header, "◈  HERALD OS", 13 if cfg["compact"] else 17, CYAN, True)
        tk.Frame(main, height=2, bg=EDGE).pack(fill="x", pady=(cfg["gap"], cfg["gap"]))
        self.label(main, "Welcome to Herald OS", cfg["heading"], FG, True)
        self.label(main, "Network installer  ·  USB / iVentoy PXE", cfg["body"], MUTED)
        tk.Frame(main, height=cfg["gap"], bg=BG).pack()
        card = tk.Frame(main, bg=CARD, padx=15 if cfg["compact"] else 26,
                        pady=12 if cfg["compact"] else 24,
                        highlightbackground=EDGE, highlightthickness=1)
        card.pack(fill="x")
        self.label(card, "PUBLIC RELEASE", 10, CYAN, True)
        self.label(card, "Install stable HAOS", cfg["card_heading"], FG, True)
        self.label(card, "Published image only - no development fallback.",
                   cfg["body"], MUTED)
        self.stable_button = self.button(card, "1  Continue to installation",
                                         self.open_stable, accent=True)
        tk.Frame(main, height=cfg["gap"], bg=BG).pack()
        bottom = tk.Frame(main, bg=BG)
        bottom.pack(fill="x")
        self.network = tk.Label(bottom, text="● Checking network...", bg=BG,
                                fg=MUTED, font=("DejaVu Sans", cfg["body"]))
        self.network.pack(side="left")
        self.network_button = tk.Button(
            bottom, text="2  Network settings", command=self.open_network,
            fg=FG, bg=EDGE, activebackground=CYAN, relief="flat",
            font=("DejaVu Sans", cfg["body"], "bold"),
            padx=10, pady=7, cursor="hand2", takefocus=True,
            highlightthickness=2, highlightbackground=EDGE, highlightcolor=CYAN
        )
        self.network_button.pack(side="right")
        self.network_button.bind("<Return>", lambda e: (self.network_button.invoke(), "break")[1])
        keyrow = tk.Frame(main, bg=BG)
        keyrow.pack(fill="x", pady=(cfg["gap"], 2))
        self.keyboard_button = tk.Button(
            keyrow, text="F4  Keyboard: Deutsch (AT)", command=self.cycle_keyboard,
            bg=EDGE, fg=FG, font=("DejaVu Sans", cfg["body"]),
            relief="flat", padx=10, pady=5, takefocus=True
        )
        self.keyboard_button.pack(anchor="w")
        help_text = ("TAB / ENTER navigate   ·   F2 text installer   ·   F3 network settings"
                     if cfg["compact"] else
                     "TAB / ENTER: navigate   |   F2: text installer   |   F3: network settings   |   ESC: help")
        self.label(main, help_text, 9 if cfg["compact"] else 11, MUTED)
        self.label(main, "No disk changes until you explicitly confirm installation.",
                   9 if cfg["compact"] else 10, MUTED)

    def cycle_keyboard(self, event=None):
        self.keyboard_index = (self.keyboard_index + 1) % len(self.keyboards)
        name, layout = self.keyboards[self.keyboard_index]
        try:
            subprocess.run(["/usr/bin/setxkbmap", "-layout", layout],
                           check=True, capture_output=True, timeout=4)
            subprocess.run(["/usr/bin/loadkeys", "us" if layout == "us" else "de"],
                           check=False, capture_output=True, timeout=4)
            self.keyboard_button.configure(text=f"F4  Keyboard: {name}")
        except Exception as exc:
            messagebox.showerror("Keyboard layout failed", str(exc))

    def open_stable(self, event=None):
        self.open_terminal("HAOS Stable Installation", "/usr/local/sbin/haos-install.sh", "--stable")

    def open_network(self, event=None):
        self.open_terminal("Network Settings", "/usr/bin/nmtui")

    def show_help(self, event=None):
        messagebox.showinfo(
            "HAOS keyboard controls",
            "1: Stable installer\n2 or F3: Network settings\n"
            "Tab / Shift+Tab: change button\nEnter: activate button\n"
            "F2: switch to text installer on TTY2\n"
            "F4: change keyboard layout (AT / DE / US)\n"
            "Ctrl+Alt+F2: direct text installer\n"
            "Esc: show this help"
        )

    def open_text_console(self, event=None):
        try:
            subprocess.run(["/usr/bin/chvt", "2"], timeout=3, check=True)
        except Exception as exc:
            messagebox.showerror("Text console unavailable", str(exc))

    def open_dev(self, event=None):
        if messagebox.askyesno(
            "Developer channel",
            "Open authenticated private GHCR image selection?\n"
            "No disk will be erased without confirmation.",
            parent=self
        ):
            self.open_terminal(
                "HAOS Developer Installation", "/usr/local/sbin/private-install.sh",
                "--select-dev"
            )

    def open_terminal(self, title, path, *args):
        # xterm was previously hardcoded to 106x31 and exceeded 640x480 displays.
        cols = max(40, min(106, (self.screen_w - 40) // 9))
        rows = max(12, min(31, (self.screen_h - 65) // 19))
        size = "10" if self.cfg["compact"] else "13"
        try:
            subprocess.Popen([
                "/usr/bin/xterm", "-hold", "-T", title,
                "-fa", "DejaVu Sans Mono", "-fs", size,
                "-bg", BG, "-fg", FG,
                "-geometry", f"{cols}x{rows}+5+5",
                "-e", *(
                    ["/usr/bin/bash", path, *args] if path.endswith(".sh")
                    else [path, *args]
                )
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
            dns = subprocess.run(
                ["/usr/bin/getent", "ahostsv4", "ghcr.io"],
                capture_output=True, text=True, timeout=4
            )
            resolved = ok and dns.returncode == 0
            self.network.configure(
                text=("● Network + GHCR DNS ready" if resolved else
                      "● Network connected, DNS not ready - F3" if ok else
                      "● Network disconnected - F3"),
                fg=CYAN if resolved else "#FFA75E"
            )
        except Exception:
            self.network.configure(text="● Network status unavailable", fg=MUTED)
        self.after(8000, self.refresh_network)


if __name__ == "__main__":
    Welcome().mainloop()
