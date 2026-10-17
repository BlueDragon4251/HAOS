"""Private on-device mTLS provisioning; passwords never become arguments or env."""
from __future__ import annotations

import hashlib
import ipaddress
import os
from pathlib import Path
import re
import subprocess


def validate_hostname(host):
    if not isinstance(host, str) or not 1 <= len(host) <= 253:
        raise ValueError("explicit TLS host required")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]"
            r"(?:[a-z0-9-]{0,61}[a-z0-9])?", host
        ) or ".." in host:
            raise ValueError("use a plain DNS hostname or literal IP (no URL, port or wildcard)")
        return "DNS:" + host
    if ip.is_multicast or ip.is_unspecified or ip.is_link_local:
        raise ValueError("unusable TLS listener address")
    return "IP:" + str(ip)


def checked(*args, secret=None):
    # OpenSSL accepts the P12 password exclusively through process stdin.
    # No password may appear in argv, inherited environment or exception text.
    try:
        p = subprocess.run(
            ["/usr/bin/openssl", *map(str, args)],
            input=secret.encode() + b"\n" if secret is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("OpenSSL TLS provisioning unavailable") from None
    if p.returncode:
        raise RuntimeError("OpenSSL rejected a local TLS provisioning operation") from None
    return p.stdout


def generate(directory, hostname, device_id, password):
    """Create isolated CA, server leaf, client leaf and encrypted P12.
    
    The caller owns the 0700 scratch directory and decides where persistent
    private files are published. This function never touches system policy.
    """
    san = validate_hostname(hostname)
    if not isinstance(device_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", device_id):
        raise ValueError("device ID must be a single bounded, non-privileged name")
    if (not isinstance(password, str) or not 16 <= len(password) <= 128 or
            any(ord(c) < 32 or ord(c) == 127 for c in password)):
        raise ValueError("PKCS#12 export requires 16-128 non-control characters")
    directory = Path(directory)
    info = directory.stat()
    if not directory.is_dir() or info.st_mode & 0o077:
        raise PermissionError("temporary TLS authority directory must be mode 0700")
    for name in ("ca.pem", "ca.key", "server.pem", "server.key",
                 "phone.pem", "phone.key", "phone.p12", "server.ext", "phone.ext"):
        if (directory / name).exists() or (directory / name).is_symlink():
            raise PermissionError("refuse overwriting any existing certificate or key")
    checked("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
            "-nodes", "-days", "365", "-subj", "/CN=HAOS local device CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", directory / "ca.key", "-out", directory / "ca.pem")
    for role, usage in (("server", "serverAuth"), ("phone", "clientAuth")):
        checked("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                "-nodes", "-subj", "/CN=HAOS " + (hostname if role == "server" else device_id),
                "-keyout", directory / (role + ".key"), "-out", directory / (role + ".csr"))
        lines = ["basicConstraints=critical,CA:FALSE",
                 "keyUsage=critical,digitalSignature", "extendedKeyUsage=" + usage]
        if role == "server":
            lines.append("subjectAltName=" + san)
        (directory / (role + ".ext")).write_text("\n".join(lines) + "\n", encoding="ascii")
        checked("x509", "-req", "-in", directory / (role + ".csr"),
                "-CA", directory / "ca.pem", "-CAkey", directory / "ca.key",
                "-CAcreateserial", "-days", "90",
                "-extfile", directory / (role + ".ext"), "-out", directory / (role + ".pem"))
    checked("verify", "-purpose", "sslserver", "-CAfile",
            directory / "ca.pem", directory / "server.pem")
    checked("verify", "-purpose", "sslclient", "-CAfile",
            directory / "ca.pem", directory / "phone.pem")
    checked("pkcs12", "-export", "-inkey", directory / "phone.key",
            "-in", directory / "phone.pem", "-certfile", directory / "ca.pem",
            "-name", "HAOS " + device_id,
            "-out", directory / "phone.p12", "-passout", "stdin", secret=password)
    checked("pkcs12", "-info", "-noout", "-in",
            directory / "phone.p12", "-passin", "stdin", secret=password)
    for role in ("ca.key", "server.key", "phone.key", "phone.p12"):
        os.chmod(directory / role, 0o600)
    der = checked("x509", "-in", directory / "phone.pem", "-outform", "DER")
    return {
        "ca": directory / "ca.pem", "ca_key": directory / "ca.key",
        "server": directory / "server.pem", "server_key": directory / "server.key",
        "client": directory / "phone.pem", "mobile_p12": directory / "phone.p12",
        "fingerprint": hashlib.sha256(der).hexdigest()
    }
