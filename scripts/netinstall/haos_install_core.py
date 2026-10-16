#!/usr/bin/env python3
"""HAOS live installer operations. No subprocess may hang indefinitely.

Token bytes are used only for stdin of podman login, never CLI arguments,
environment variables, image metadata or logs.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

REPO = "ghcr.io/bluedragon4251/haos"
RELEASE = "https://raw.githubusercontent.com/BlueDragon4251/HAOS/main/releases/stable-image.txt"
TAG_PATTERN = re.compile(r"dev-[0-9a-f]{12}\Z")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_PATTERN = re.compile(r"ghcr\.io/[a-z0-9_-]+(?:/[a-z0-9_.-]+)+@sha256:[0-9a-f]{64}\Z")
ROOT = Path(__file__).resolve().parent


class InstallerError(Exception):
    pass


def execute(args, *, timeout=35, input_data=None, cancel_event=None):
    """Run commands with a real deadline and optional user cancellation."""
    proc = None
    output = b""
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )
        first = True
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InstallerError("Vorgang vom Benutzer abgebrochen.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstallerError(f"Zeitüberschreitung ({timeout}s): {args[0]}. Verbindung prüfen.")
            try:
                chunk, _ = proc.communicate(
                    input=input_data if first else None,
                    timeout=min(1.0, remaining),
                )
                output = chunk
                break
            except subprocess.TimeoutExpired:
                first = False
        result = output.decode("utf-8", errors="replace")[-5000:]
        if proc.returncode:
            raise InstallerError(f"{args[0]} schlug fehl (Code {proc.returncode}).\n{result.strip()}")
        return result.strip()
    except OSError as exc:
        raise InstallerError(f"Programm {args[0]} konnte nicht gestartet werden: {exc}") from exc
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()


def check_network():
    """DNS alone is insufficient: verify actual TLS route to GHCR on TCP 443."""
    try:
        execute(["getent", "ahostsv4", "ghcr.io"], timeout=8)
        code = execute(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             "--connect-timeout", "7", "--max-time", "12",
             "--proto", "=https", "https://ghcr.io/v2/"], timeout=15,
        )
        if code not in ("200", "401", "403"):
            raise InstallerError(f"GHCR antwortet unerwartet mit HTTP {code}.")
        return "GHCR HTTPS erreichbar (HTTP " + code + ")"
    except InstallerError as exc:
        raise InstallerError(
            f"GHCR über HTTPS (Port 443) nicht erreichbar.\n{exc}\n"
            "PXE-Boot über 192.168.50.1:16000 beweist nur die LAN-Verbindung. "
            "Gateway, Internetfreigabe, DNS und Firewall überprüfen."
        ) from exc


def _lsblk():
    data = execute(["lsblk", "--json", "--bytes", "--paths",
                    "--output", "PATH,NAME,TYPE,SIZE,TRAN,RM,RO,FSTYPE,MODEL,PKNAME"],
                   timeout=12)
    return json.loads(data).get("blockdevices", [])


def token_partitions():
    """Expose only USB-backed filesystems, not loop, nbd, ram or internal disks."""
    choices = []
    def scan(dev, usb=False):
        usb = usb or (dev.get("type") == "disk" and str(dev.get("tran") or "").lower() == "usb")
        if usb and dev.get("path") and dev.get("fstype") and dev.get("type") in ("part", "disk"):
            choices.append({"path": dev["path"], "fstype": dev["fstype"],
                            "size": int(dev.get("size") or 0)})
        for item in dev.get("children") or []:
            scan(item, usb)
    for disk in _lsblk():
        scan(disk)
    return choices


def internal_disks():
    """Reuse the same fail-closed disk filter used by the text installer."""
    spec = importlib.util.spec_from_file_location("haos_disk_safety", ROOT / "haos-disk-safety.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [d for d in module.inspect() if module.is_eligible(d)]


def read_usb_token(device):
    """Mount selected USB filesystem read-only; never mount the entire token disk by guess."""
    options = {v["path"] for v in token_partitions()}
    if device not in options:
        raise InstallerError("Bitte die USB-Partition mit Dateisystem wählen (z. B. /dev/sda1).")
    with tempfile.TemporaryDirectory(prefix="haos-token-", dir="/run") as folder:
        execute(["mount", "-o", "ro,nosuid,nodev,noexec", device, folder], timeout=12)
        try:
            for filename in ("HAOS-DEV/token.txt", "token.txt"):
                path = Path(folder, filename)
                if path.is_file() and not path.is_symlink():
                    if path.stat().st_size > 8192:
                        raise InstallerError("Token-Datei ist ungewöhnlich groß.")
                    lines = path.read_text(encoding="utf-8").splitlines()
                    return check_token(lines[0] if lines else "")
            raise InstallerError("HAOS-DEV/token.txt oder token.txt auf dem USB-Stick fehlt.")
        finally:
            execute(["umount", folder], timeout=12)


def check_token(value):
    value = value.strip()
    if not value or len(value) > 8192 or any(x.isspace() for x in value):
        raise InstallerError("Ungültiges oder leeres Token.")
    return value


def https_token(url):
    if not url.startswith("https://") or "@" in url:
        raise InstallerError("Token-Quelle muss eine vertrauenswürdige HTTPS-URL ohne Zugangsdaten sein.")
    with tempfile.TemporaryDirectory(prefix="haos-https-", dir="/run") as folder:
        path = str(Path(folder, "token"))
        execute(["curl", "-fsS", "-L", "--proto", "=https", "--proto-redir", "=https",
                 "--connect-timeout", "8", "--max-time", "25", "--max-filesize", "8192",
                 "-o", path, url], timeout=30)
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return check_token(lines[0] if lines else "")


class RegistrySession:
    def __init__(self):
        self.folder = tempfile.TemporaryDirectory(prefix="haos-ghcr-", dir="/run")
        self.authfile = str(Path(self.folder.name, "auth.json"))
        self.cancel_event = None
        Path(self.authfile).write_text("{}\n", encoding="utf-8")
        os.chmod(self.authfile, 0o600)

    def close(self):
        self.folder.cleanup()

    def login(self, username, token):
        if not re.fullmatch(r"[A-Za-z0-9-]+", username):
            raise InstallerError("Ungültiger GitHub-Benutzername.")
        # Avoid revealing tokens in commands, arguments or logs.
        try:
            execute(["podman", "login", "--authfile", self.authfile,
                     "ghcr.io", "-u", username, "--password-stdin"],
                    input_data=check_token(token).encode("utf-8"), timeout=35,
                    cancel_event=self.cancel_event)
        except InstallerError as exc:
            raise InstallerError(f"GHCR-Anmeldung fehlgeschlagen: {exc}") from exc

    def tags(self):
        raw = execute(["skopeo", "list-tags", "--authfile", self.authfile,
                       "docker://" + REPO], timeout=45, cancel_event=self.cancel_event)
        return sorted({t for t in json.loads(raw).get("Tags", [])
                       if TAG_PATTERN.fullmatch(t)}, reverse=True)

    def pin(self, tag):
        if not TAG_PATTERN.fullmatch(tag):
            raise InstallerError("Ungültiger Entwicklungstag.")
        raw = execute(["skopeo", "inspect", "--authfile", self.authfile,
                       "docker://" + REPO + ":" + tag], timeout=45, cancel_event=self.cancel_event)
        digest = json.loads(raw).get("Digest", "")
        if not DIGEST_PATTERN.fullmatch(digest):
            raise InstallerError("GHCR lieferte keinen gültigen SHA256-Digest.")
        return REPO + "@" + digest

    def public_image(self):
        raw = execute(["curl", "-fsSL", "--connect-timeout", "8", "--max-time", "20",
                       "--proto", "=https", RELEASE], timeout=25, cancel_event=self.cancel_event).strip()
        if not IMAGE_PATTERN.fullmatch(raw) or ".." in raw:
            raise InstallerError("Es ist noch kein gültiges öffentliches Stable-Image veröffentlicht.")
        return raw

    def pull(self, image):
        if not IMAGE_PATTERN.fullmatch(image):
            raise InstallerError("Das Container-Image hat keinen festen SHA256-Digest.")
        execute(["podman", "pull", "--authfile", self.authfile, image], timeout=1800,
                cancel_event=self.cancel_event)

    def install(self, image, disk):
        # Re-validate target right before the destructive operation.
        safe = {v["path"] for v in internal_disks()}
        if disk not in safe:
            raise InstallerError("Zielfestplatte ist nicht mehr verfügbar oder nicht sicher.")
        for node in execute(["lsblk", "-nrpo", "NAME", disk], timeout=10).splitlines():
            check = subprocess.run(["findmnt", "-rn", "-S", node], capture_output=True, timeout=8)
            if check.returncode == 0:
                raise InstallerError(f"Abbruch: {node} ist eingebunden.")
        swap = subprocess.run(["swapon", "--noheadings", "--raw", "--show=NAME"],
                              capture_output=True, text=True, timeout=8)
        nodes = set(execute(["lsblk", "-nrpo", "NAME", disk], timeout=10).splitlines())
        if nodes.intersection(swap.stdout.splitlines()):
            raise InstallerError("Auf dem Datenträger ist Swap aktiv.")
        execute(
            ["podman", "run", "--rm", "--privileged", "--pid=host", "--ipc=host",
             "--security-opt", "label=disable",
             "-v", "/var/lib/containers:/var/lib/containers",
             "-v", "/dev:/dev", "-v", "/run:/run",
             image, "bootc", "install", "to-disk", "--wipe", "--skip-fetch-check", disk],
            timeout=3600, cancel_event=self.cancel_event,
        )
