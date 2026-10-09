"""Real nftables/socket probes; use only on the disposable CI runner as root."""

import json
import os
from pathlib import Path
import pwd
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos import network
from haos.network import NFT, install


def run(*args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, timeout=10, **kwargs)


@pytest.fixture
def trusted_resolver(monkeypatch):
    assert os.geteuid() == 0, "use only disposable root-owned resolver fixtures"
    # The runner's DNS files need not meet HAOS's root ownership contract.
    # Keep the real trust checks with a private file under protected /run.
    with tempfile.TemporaryDirectory(prefix="haos-net-resolver-", dir="/run") as directory:
        path = Path(directory) / "resolv.conf"
        path.write_text("nameserver 127.0.0.53\n")
        path.chmod(0o600)
        original = network.Path
        monkeypatch.setattr(network, "Path", lambda value: path if value == "/etc/resolv.conf" else original(value))
        assert network.read_resolvers() == ["127.0.0.53"]
        yield path


def test_agent_local_sockets_are_guarded_without_breaking_backend_replies(trusted_resolver):
    assert os.geteuid() == 0, "run only on the disposable CI runner as root"
    suffix = uuid.uuid4().hex[:10]
    user, table = "haos-net-" + suffix, "haos_test_" + suffix
    created = False
    children, sockets = [], []
    stop = threading.Event()

    def echo(connection):
        with connection:
            connection.settimeout(1)
            while not stop.is_set():
                try:
                    message = connection.recv(1024)
                    if not message:
                        break
                    connection.sendall(message)
                except socket.timeout:
                    continue
                except OSError:
                    break

    def accept(listener):
        listener.settimeout(0.1)
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
                threading.Thread(target=echo, args=(connection,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    try:
        run("/usr/sbin/useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", user, check=True)
        created = True
        account = pwd.getpwnam(user)
        drop = ["/usr/bin/setpriv", f"--reuid={account.pw_uid}", f"--regid={account.pw_gid}",
                "--clear-groups", "--no-new-privs", sys.executable, "-I", "-c"]
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            listener = socket.socket(family, socket.SOCK_STREAM)
            sockets.append(listener)
            if family == socket.AF_INET6:
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind((address, 0))
            listener.listen(32)
            threading.Thread(target=accept, args=(listener,), daemon=True).start()
        owner_port = sockets[0].getsockname()[1]
        client = "import socket,sys;s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=2);s.sendall(b'fixture');assert s.recv(7)==b'fixture';s.close()"
        assert run(*drop, client, "127.0.0.1", str(owner_port)).returncode == 0
        # Keep a real connection open across installation. An unconditional
        # established-connection allow would incorrectly preserve this bypass.
        persistent = subprocess.Popen([*drop,
            "import socket,sys;s=socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=2);s.sendall(b'before');assert s.recv(6)==b'before';print('READY',flush=True);sys.stdin.readline();\ntry:\n s.sendall(b'after');assert s.recv(5)!=b'after'\nexcept OSError:\n pass\nprint('DENIED',flush=True)", str(owner_port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        children.append(persistent)
        # readline has an explicit bound through the child's socket timeout.
        assert persistent.stdout.readline().strip() == "READY"
        install(account.pw_uid, table)
        install(account.pw_uid, table)  # Actual atomic reload, not just initial syntax.
        denied = [run(*drop, client, host, str(port)) for host, port in
            (("127.0.0.1", owner_port), ("::ffff:127.0.0.1", owner_port), ("::1", sockets[1].getsockname()[1]))]
        assert all(result.returncode != 0 for result in denied), [result.stderr for result in denied]
        out, err = persistent.communicate(input="continue\n", timeout=5)
        assert persistent.returncode == 0 and out.strip() == "DENIED", err
        # The allowed backend is also served by the guarded UID, so both its
        # self-connections and replies to independent control/UI clients matter.
        backend = subprocess.Popen([*drop,
            "import socket;s=socket.socket();s.bind(('127.0.0.1',9119));s.listen(8);print('READY',flush=True);\nwhile True:\n c,_=s.accept();c.sendall(c.recv(7));c.close()"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        children.append(backend)
        assert backend.stdout.readline().strip() == "READY"
        assert run(sys.executable, "-I", "-c", client, "127.0.0.1", "9119").returncode == 0
        assert run(*drop, client, "127.0.0.1", "9119").returncode == 0
        mutation = run("/usr/sbin/runuser", "-u", user, "--", NFT, "flush", "table", "inet", table)
        assert mutation.returncode != 0
        assert run(*drop, client, "127.0.0.1", str(owner_port)).returncode != 0
        with socket.create_connection(("127.0.0.1", owner_port), timeout=2) as owner:
            owner.sendall(b"owner")
            assert owner.recv(5) == b"owner"
        print(json.dumps({"agent_ipv4_local_service_denied": True, "agent_ipv6_local_service_denied": True,
            "ipv4_mapped_ipv6_denied": True, "existing_agent_connection_revoked": True,
            "backend_self_connection_permitted": True, "backend_replies_to_owner_permitted": True,
            "agent_firewall_mutation_denied": True, "other_uid_traffic_preserved": True}))
    finally:
        stop.set()
        for listener in sockets:
            listener.close()
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        # Delete only this test's unique table and account, never host policy.
        run(NFT, "delete", "table", "inet", table)
        if created:
            run("/usr/sbin/userdel", user, check=True)
