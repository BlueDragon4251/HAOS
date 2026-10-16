#!/usr/bin/env python3
"""HAOS live installer operations. No subprocess may hang indefinitely.

Token bytes are used only for stdin of podman login, never CLI arguments,
environment variables, image metadata or logs.
"""
import importlib.util
import datetime
import selectors
import shutil
import ipaddress
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


def execute(args, *, timeout=35, input_data=None, cancel_event=None, output_limit=5000):
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
        result = output.decode("utf-8", errors="replace")
        if output_limit is not None:
            result = result[-output_limit:]
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



def stream_execute(args, *, timeout, cancel_event=None, progress=None):
    """Stream actual Podman/bootc output rather than faking percentage values.

    Output parsing is independent of a pseudo-TTY and handles carriage returns
    emitted by the container engine. Captured diagnostics are bounded.
    """
    import collections
    proc = None
    tail = collections.deque(maxlen=60)
    partial = b""
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        with selectors.DefaultSelector() as selected:
            selected.register(proc.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout
            last_emit = 0.0
            while selected.get_map() or proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise InstallerError("Vorgang vom Benutzer abgebrochen.")
                if time.monotonic() >= deadline:
                    raise InstallerError(f"Zeitüberschreitung ({timeout}s): {args[0]}.")
                for key, _ in selected.select(timeout=0.4):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selected.unregister(key.fileobj)
                        continue
                    partial += chunk
                    # Handle both textual CR-updated and LF-delimited progress.
                    parts = re.split(rb"[\r\n]+", partial)
                    partial = parts.pop()[-8192:]
                    for part in parts:
                        line = part.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        tail.append(line[:1200])
                        if progress is not None and (
                            time.monotonic() - last_emit > 0.2
                            or "error" in line.lower()
                        ):
                            progress(line[:300])
                            last_emit = time.monotonic()
            if partial.strip():
                tail.append(partial.decode("utf-8", errors="replace")[:1200])
            code = proc.wait(timeout=5)
            if code:
                raise InstallerError(
                    f"{args[0]} fehlgeschlagen (Exit {code}).\n"
                    + "\n".join(tail)[-4500:]
                )
            if progress:
                progress("Vorgang erfolgreich abgeschlossen.")
            return "\n".join(tail)
    except OSError as exc:
        raise InstallerError(f"{args[0]} konnte nicht ausgeführt werden: {exc}") from exc
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
        if proc is not None and proc.stdout is not None:
            proc.stdout.close()

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



def _routes(*args):
    """Read the kernel's current IPv4 routes as JSON; no network changes."""
    raw = execute(["ip", "-j", "-4", "route", *args], timeout=8, output_limit=None)
    return json.loads(raw)


def _wifi_devices():
    """Connected WLAN interfaces only, obtained from NetworkManager."""
    lines = execute(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"], timeout=8)
    choices = []
    for line in lines.splitlines():
        bits = line.split(":", 2)
        if len(bits) == 3 and bits[1] == "wifi" and bits[2].startswith("connected"):
            if re.fullmatch(r"[a-zA-Z0-9_.-]{1,32}", bits[0]):
                choices.append(bits[0])
    return choices


def _pxe_root_host():
    """The HTTP-root location must stay reachable after any route change."""
    from urllib.parse import urlsplit
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="utf-8")
        match = re.search(r"(?:^|\s)root=live:(http://[^\s]+)", cmdline)
        if not match:
            return None
        host = urlsplit(match.group(1)).hostname
        return str(ipaddress.IPv4Address(host)) if host else None
    except (OSError, ValueError):
        return None


def _route_device(host):
    routes = _routes("get", host)
    return routes[0].get("dev") if routes else None


def network_diagnostics():
    """Safe, read-only network overview for the graphical installer."""
    output = []
    for label, args in [
        ("Aktive Netzwerkgeräte", ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"]),
        ("IPv4-Adressen", ["ip", "-br", "-4", "address", "show"]),
        ("Standardrouten", ["ip", "-4", "route", "show", "default"]),
        ("DNS-Server", ["nmcli", "-t", "-f", "IP4.DNS", "device", "show"]),
    ]:
        try:
            value = execute(args, timeout=8)
            output.append(f"{label}:\n{value or '(keine)'}")
        except InstallerError as exc:
            output.append(f"{label}: {exc}")
    root = _pxe_root_host()
    if root:
        try:
            output.append(f"iVentoy HTTP root: {root} über {_route_device(root)}")
        except InstallerError as exc:
            output.append(f"iVentoy HTTP root: {exc}")
    try:
        output.append("WLAN mit Verbindung: " + (", ".join(_wifi_devices()) or "(keines)"))
    except InstallerError as exc:
        output.append(f"WLAN-Status: {exc}")
    return "\n\n".join(output)


def prefer_wifi_internet():
    """User-invoked temporary route preference; never disconnect PXE Ethernet.

    Only add a temporary lower-metric WLAN default route. Preserve the route
    that serves dracut's HTTP SquashFS; roll back on failure.
    """
    wifi = _wifi_devices()
    if not wifi:
        raise InstallerError("Kein verbundenes WLAN erkannt. Erst WLAN in F3 verbinden.")
    defaults = _routes("show", "default")
    metrics = [int(route.get("metric", 0)) for route in defaults]
    if not metrics:
        raise InstallerError("Kein IPv4-Gateway vorhanden. Bitte DHCP/WLAN prüfen.")
    best_metric = min(metrics)
    if best_metric < 2:
        raise InstallerError("Eine Standardroute hat Metrik 0 oder 1. Keine sichere automatische Änderung möglich.")
    metric = max(1, min(50, best_metric - 1))
    root_host = _pxe_root_host()
    root_device = _route_device(root_host) if root_host else None
    failures = []
    for iface in wifi:
        wifi_defaults = [r for r in defaults if r.get("dev") == iface and r.get("gateway")]
        if not wifi_defaults:
            failures.append(f"{iface}: WLAN ohne IPv4-Gateway.")
            continue
        gateway = wifi_defaults[0]["gateway"]
        try:
            ipaddress.IPv4Address(gateway)
            # Avoid installing a route unless this specific WLAN can reach GHCR.
            probe = execute(
                ["curl", "-4", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                 "--interface", iface, "--connect-timeout", "6", "--max-time", "10",
                 "https://ghcr.io/v2/"], timeout=13,
            )
            if probe not in ("200", "401", "403"):
                failures.append(f"{iface}: HTTPS über WLAN lieferte {probe}.")
                continue
        except (InstallerError, ValueError) as exc:
            failures.append(f"{iface}: HTTPS nicht erreichbar ({exc}).")
            continue
        route_args = ["default", "via", gateway, "dev", iface, "metric", str(metric)]
        try:
            execute(["ip", "-4", "route", "add", *route_args], timeout=8)
        except InstallerError as exc:
            failures.append(f"{iface}: Route nicht hinzugefügt: {exc}")
            continue
        try:
            if root_host and _route_device(root_host) != root_device:
                raise InstallerError("iVentoy-Verbindung würde den Netzwerkweg wechseln.")
            check_network()
            return (
                f"Internet bevorzugt über WLAN {iface} ({gateway}, Metrik {metric}). "
                f"iVentoy bleibt über {root_device or 'die bestehende lokale Route'} erreichbar."
            )
        except InstallerError as exc:
            try:
                execute(["ip", "-4", "route", "del", *route_args], timeout=8)
            except InstallerError:
                pass
            failures.append(f"{iface}: Prüfung nach Änderung fehlgeschlagen: {exc}")
    raise InstallerError(
        "WLAN konnte nicht als Internetverbindung eingerichtet werden.\n"
        + "\n".join(failures)
        + "\nPrüfe Internetzugang des WLAN-Routers, Gateway und Firewall in F3."
    )

def _lsblk():
    data = execute(["lsblk", "--json", "--bytes", "--paths",
                    "--output", "PATH,NAME,TYPE,SIZE,TRAN,RM,RO,FSTYPE,MODEL,PKNAME"],
                   timeout=12, output_limit=None)
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
        self.api_token = None
        Path(self.authfile).write_text("{}\n", encoding="utf-8")
        os.chmod(self.authfile, 0o600)

    def close(self):
        self.api_token = None
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
            self.api_token = check_token(token)
        except InstallerError as exc:
            raise InstallerError(f"GHCR-Anmeldung fehlgeschlagen: {exc}") from exc

    def tags(self):
        raw = execute(["skopeo", "list-tags", "--authfile", self.authfile,
                       "docker://" + REPO], timeout=45, cancel_event=self.cancel_event,
                       output_limit=None)
        return sorted({t for t in json.loads(raw).get("Tags", [])
                       if TAG_PATTERN.fullmatch(t)}, reverse=True)

    def versions(self):
        """Return dev releases newest first with GHCR package publication timestamps.

        GitHub REST package versions' created_at reflects publication, unlike
        OCI image Created (build time). Use the latter only as a labeled fallback.
        """
        tags = self.tags()
        if not tags:
            return []
        timestamps = {}
        source = "GitHub-Paket erstellt"
        try:
            if not self.api_token:
                raise InstallerError("No token available for package metadata")
            token = check_token(self.api_token)
            # The -K - config flows over stdin, not visible in process argv or env.
            # Escape config-string syntax; ensure no CR or LF can be injected.
            safe_token = token.replace("\\", "\\\\").replace('"', '\\"')
            options = (
                'header = "Accept: application/vnd.github+json"\n'
                + 'header = "Authorization: Bearer ' + safe_token + '"\n'
            ).encode("utf-8")
            response = execute([
                "curl", "-fsSL", "--connect-timeout", "7", "--max-time", "20",
                "-K", "-", "--proto", "=https",
                "https://api.github.com/user/packages/container/haos/versions?per_page=100"
            ], input_data=options, timeout=25, cancel_event=self.cancel_event, output_limit=None)
            versions = json.loads(response)
            if not isinstance(versions, list):
                raise ValueError("API returned no version list")
            for version in versions:
                when = version.get("created_at", "")
                for tag in (version.get("metadata") or {}).get("container", {}).get("tags", []):
                    if TAG_PATTERN.fullmatch(tag) and when:
                        timestamps[tag] = when
        except (InstallerError, ValueError, KeyError, TypeError):
            pass
        finally:
            # No need to keep the token plaintext once Podman authfile exists.
            self.api_token = None

        if not timestamps:
            # Last resort: OCI creation date (not necessarily GHCR publication).
            source = "Image erstellt (UTC)"
            for tag in tags[:30]:
                try:
                    raw = execute([
                        "skopeo", "inspect", "--no-tags",
                        "--authfile", self.authfile, "docker://" + REPO + ":" + tag
                    ], timeout=12, cancel_event=self.cancel_event, output_limit=None)
                    timestamps[tag] = json.loads(raw).get("Created", "")
                except (InstallerError, ValueError, KeyError, TypeError):
                    continue
        entries = [{"tag": tag, "published": timestamps.get(tag, ""), "source": source}
                   for tag in tags]
        # ISO 8601 UTC is lexicographically chronological; unknown dates last.
        return sorted(entries, key=lambda item: item["published"], reverse=True)

    def pin(self, tag):
        if not TAG_PATTERN.fullmatch(tag):
            raise InstallerError("Ungültiger Entwicklungstag.")
        raw = execute(["skopeo", "inspect", "--authfile", self.authfile,
                       "docker://" + REPO + ":" + tag], timeout=45, cancel_event=self.cancel_event,
                       output_limit=None)
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

    def pull(self, image, progress=None):
        if not IMAGE_PATTERN.fullmatch(image):
            raise InstallerError("Das Container-Image hat keinen festen SHA256-Digest.")
        stream_execute(
            ["podman", "pull", "--retry=2", "--retry-delay=3s",
             "--authfile", self.authfile, image],
            timeout=1800, cancel_event=self.cancel_event, progress=progress,
        )

    def install(self, image, disk, progress=None):
        if not IMAGE_PATTERN.fullmatch(image):
            raise InstallerError("Image reference does not have a pinned digest.")
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
        # Ensure the pre-pulled image is available locally before erasing.
        execute(["podman", "image", "exists", image], timeout=15,
                cancel_event=self.cancel_event)
        # bootc normally may copy from docker:// even when a local image was
        # downloaded. Point it explicitly to containers-storage to reuse the
        # existing local OCI layer store and avoid redundant network fetches.
        # Keep target-imgref at the signed-by-digest registry reference so
        # future updates do not use the temporary live session's storage.
        try:
            stream_execute(
                ["podman", "run", "--rm", "--privileged", "--pid=host", "--ipc=host",
                 "--security-opt", "label=disable",
                 "-v", "/var/lib/containers:/var/lib/containers",
                 "-v", "/dev:/dev", "-v", "/run:/run",
                 image, "bootc", "install", "to-disk", "--wipe",
                 "--skip-fetch-check",
                 "--source-imgref", "containers-storage:" + image,
                 "--target-imgref", image, disk],
                timeout=3600, cancel_event=self.cancel_event, progress=progress,
            )
        except InstallerError as exc:
            try:
                diagnosis = execute(
                    ["df", "-h", "/", "/var/lib/containers", "/sysroot"],
                    timeout=8,
                )
            except InstallerError:
                diagnosis = "Partition usage not available after failure."
            raise InstallerError(
                f"bootc-Installation fehlgeschlagen auf {disk}.\n"
                + str(exc)
                + "\nSpeicherbelegung nach Fehler:\n" + diagnosis
                + "\n'no space left on device' kann unzureichenden Platz im "
                  "Live-Zwischenspeicher ODER auf der neu angelegten Zielpartition bedeuten. "
                  "Nicht automatisch wiederholen."
            ) from exc
