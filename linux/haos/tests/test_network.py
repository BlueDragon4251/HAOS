import subprocess

import pytest

from haos import network


@pytest.mark.parametrize("uid,table", [(0, "haos_agent"), (True, "haos_agent"), (-1, "haos_agent"),
    (2**32 - 1, "haos_agent"), (1001, "filter"), (1001, "haos_test; flush ruleset"), (1001, "haos_\nother")])
def test_untrusted_firewall_identity_cannot_expand_host_authority(uid, table):
    with pytest.raises(ValueError):
        network.rules(uid, table)


def test_unprivileged_agent_cannot_install_a_guard(monkeypatch):
    monkeypatch.setattr(network.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(network.subprocess, "run", lambda *a, **kw: pytest.fail("unprivileged firewall mutation"))
    with pytest.raises(PermissionError):
        network.install(1001)


def test_failed_validation_does_not_apply_or_remove_existing_rules(monkeypatch):
    monkeypatch.setattr(network.os, "geteuid", lambda: 0)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(network.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="network guard refused"):
        network.install(1001)
    assert calls == [[network.NFT, "--check", "--file", "-"]]


def test_reload_is_one_scoped_transaction_and_replies_do_not_allow_agent_initiated_connections(monkeypatch):
    monkeypatch.setattr(network.os, "geteuid", lambda: 0)
    monkeypatch.setattr(network, "read_resolvers", lambda: [])
    scripts = []
    monkeypatch.setattr(network.subprocess, "run", lambda args, **kw: scripts.append(kw["input"]))
    network.install(1001)
    assert len(scripts) == 2 and scripts[0] == scripts[1]
    assert "flush ruleset" not in scripts[1] and "flush table inet haos_agent" in scripts[1]
    filters = [line for line in scripts[1].splitlines() if "add rule" in line]
    assert all("meta skuid 1001 " in rule for rule in filters)
    assert "ct direction reply" in filters[0] and "ct direction original" not in scripts[1]
    assert "ip daddr 127.0.0.1 tcp dport 9119" in filters[1]
    assert sum("ip daddr 127.0.0.53 " in rule and "dport 53" in rule for rule in filters) == 2
    assert any("fib daddr type local" in rule and "reject" in rule for rule in filters)
    assert any("ip6 daddr" in rule and "fc00::/7" in rule for rule in filters)


def test_private_resolver_exception_is_limited_to_exact_address_and_dns_port():
    script = network.rules(1001, resolvers=["10.0.2.3", "2001:db8::53", "10.0.2.3"])
    assert script.count("ip daddr 10.0.2.3 ") == 2
    assert "ip daddr 10.0.2.3 udp dport 53 counter accept" in script
    assert "ip6 daddr 2001:db8::53 tcp dport 53 counter accept" in script
    assert "ip daddr 10.0.2.3 counter accept" not in script
    for address in ("10.0.2.3; flush ruleset", "fe80::1%eth0"):
        with pytest.raises(ValueError):
            network.rules(1001, resolvers=[address])
