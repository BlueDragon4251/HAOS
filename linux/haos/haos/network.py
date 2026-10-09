"""Root-owned socket-UID guard against direct local/LAN service access."""

import ipaddress
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

TABLE = "haos_agent"
NFT = "/usr/sbin/nft"


def read_resolvers() -> list[str]:
    link = Path("/etc/resolv.conf")
    if not link.exists():
        return []  # An offline machine can still run its local backend.
    path = link.resolve(strict=True)
    for candidate in (link, path, *path.parents):
        metadata = candidate.lstat()
        if metadata.st_uid != 0 or (not stat.S_ISLNK(metadata.st_mode) and metadata.st_mode & 0o022):
            raise PermissionError("untrusted system DNS configuration")
    servers = []
    for line in path.read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if fields and fields[0] == "nameserver":
            if len(fields) != 2 or "%" in fields[1]:
                raise ValueError("unsupported DNS resolver address")
            address = str(ipaddress.ip_address(fields[1]))
            if address not in servers:
                servers.append(address)
    if len(servers) > 8:
        raise ValueError("too many configured DNS resolvers")
    return servers


def rules(uid: int, table: str = TABLE, resolvers: list[str] | None = None) -> str:
    if type(uid) is not int or not 1 <= uid < 2**32 - 1:
        raise ValueError("a non-root service UID is required")
    if not isinstance(table, str) or not re.fullmatch(r"haos_[a-z0-9_]{1,48}", table):
        raise ValueError("unexpected HAOS firewall table")
    prefix = f"add rule inet {table} output meta skuid {uid} "
    # The backend itself uses this UID. Replies to authorized incoming API
    # connections must work; existing agent-initiated local connections are
    # deliberately not grandfathered through a generic established accept.
    commands = [f"add table inet {table}", f"flush table inet {table}",
        f"add chain inet {table} output {{ type filter hook output priority 0; policy accept; }}",
        prefix + "ct state { established, related } ct direction reply counter accept",
        prefix + "ip daddr 127.0.0.1 tcp dport 9119 counter accept"]
    for resolver in dict.fromkeys(["127.0.0.53", *(resolvers or [])]):
        if "%" in resolver:
            raise ValueError("scoped DNS resolver addresses are not supported")
        address = ipaddress.ip_address(resolver)
        for protocol in ("udp", "tcp"):
            commands.append(prefix + f"{'ip' if address.version == 4 else 'ip6'} daddr {address} {protocol} dport 53 counter accept")
    commands += [
        prefix + "fib daddr type local counter reject",
        prefix + "ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, "
                 "172.16.0.0/12, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/4, 240.0.0.0/4 } counter reject",
        prefix + "ip6 daddr { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8 } counter reject"]
    return "\n".join(commands) + "\n"


def install(uid: int, table: str = TABLE):
    if os.geteuid() != 0:
        raise PermissionError("network authority requires root")
    script = rules(uid, table, read_resolvers())
    # Check and apply whole transactions; never flush other host firewall tables.
    for args in ([NFT, "--check", "--file", "-"], [NFT, "--file", "-"]):
        try:
            subprocess.run(args, input=script, text=True, capture_output=True, check=True, timeout=20)
        except subprocess.CalledProcessError as error:
            raise RuntimeError("HAOS network guard refused: " + (error.stderr or "nft transaction failed")[-8000:]) from error


if __name__ == "__main__":
    install(pwd.getpwnam("haos-agent").pw_uid)
