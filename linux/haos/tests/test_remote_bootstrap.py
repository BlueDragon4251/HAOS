import os
from pathlib import Path
import ssl
import stat
import subprocess
import tempfile

import pytest

from haos.remote_pki import generate, validate_hostname
from haos.remote_http import tls_context


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", "IP:127.0.0.1"),
    ("192.168.1.44", "IP:192.168.1.44"),
    ("haos.example.org", "DNS:haos.example.org"),
])
def test_valid_sans(host, expected):
    assert validate_hostname(host) == expected


@pytest.mark.parametrize("bad", ["", "https://haos.example.org", "haos.example.org:8443",
    "http://evil", "*.example.org", "evil.org\nother=1", "::%eth0",
    "224.0.0.1", "0.0.0.0", "fe80::1", "EXAMPLE.ORG"])
def test_untrusted_tls_names_refused(bad):
    with pytest.raises(ValueError): validate_hostname(bad)


@pytest.mark.skipif(not Path("/usr/bin/openssl").exists(), reason="OpenSSL fixture unavailable")
def test_real_private_pki_server_client_ca_and_password():
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp)
        generated = generate(output, "127.0.0.1", "phone-alpha", "test-long-local-password")
        assert len(generated["fingerprint"]) == 64
        assert stat.S_IMODE(generated["server_key"].stat().st_mode) == 0o600
        assert stat.S_IMODE(generated["ca_key"].stat().st_mode) == 0o600
        assert stat.S_IMODE(generated["mobile_p12"].stat().st_mode) == 0o600
        ctx = tls_context(str(generated["server"]), str(generated["server_key"]), str(generated["ca"]))
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        identity = subprocess.run(
            ["/usr/bin/openssl", "pkcs12", "-in", str(generated["mobile_p12"]),
             "-info", "-noout", "-passin", "stdin"],
            input=b"test-long-local-password\n", capture_output=True, timeout=10
        )
        assert identity.returncode == 0
        wrong = subprocess.run(
            ["/usr/bin/openssl", "pkcs12", "-in", str(generated["mobile_p12"]),
             "-info", "-noout", "-passin", "stdin"],
            input=b"wrong-password\n", capture_output=True, timeout=10
        )
        assert wrong.returncode != 0
        with pytest.raises(PermissionError):
            generate(output, "127.0.0.1", "phone-alpha", "test-long-local-password")


def test_private_scratch_and_passphrase_are_mandatory(tmp_path):
    (tmp_path / "bad").mkdir(mode=0o755)
    with pytest.raises(PermissionError):
        generate(tmp_path / "bad", "127.0.0.1", "phone", "test-long-local-password")
    with pytest.raises(ValueError):
        generate(tmp_path, "127.0.0.1", "phone", "short")

def test_owner_renew_does_not_change_identity_mission_or_permissions():
    import time
    from types import SimpleNamespace
    from unittest import mock
    from haos.remote_policy import RemotePolicy
    from haos.remote_setup import owner_remote_locked
    mid = "de305d54-75b4-431b-adb2-eb6b9e546014"
    initial = {
        "version": 1, "bind": "127.0.0.1", "port": 8443,
        "requests_per_minute": 60, "bytes_per_minute": 65536,
        "devices": [{
            "id": "my-phone", "certificate_sha256": "a"*64,
            "expires_at": time.time()-10, "missions": [mid],
            "content": False, "screenshots": False
        }]
    }
    original = dict(initial["devices"][0])
    with mock.patch("haos.remote_setup.load", return_value=RemotePolicy(initial)), \
         mock.patch("haos.remote_setup.persist") as persist, \
         mock.patch("haos.owner.audit") as audit:
        result = owner_remote_locked(SimpleNamespace(remote_action="renew",
                                                     id="my-phone", hours=12))
    assert result["renewed"] == "my-phone"
    new = persist.call_args.args[0]["devices"][0]
    assert {k:v for k,v in new.items() if k!="expires_at"} == {
        k:v for k,v in original.items() if k!="expires_at"
    }
    assert new["expires_at"] > time.time()+11*3600
    assert audit.call_args.args[0] == "remote.renewed"


@pytest.mark.parametrize("hours", [0, 25, -1, True])
def test_owner_renew_rejects_out_of_range_time_without_writing(hours):
    from types import SimpleNamespace
    from unittest import mock
    from haos.remote_setup import owner_remote_locked
    with mock.patch("haos.remote_setup.load", return_value=mock.Mock(value={"devices": []})), \
         mock.patch("haos.remote_setup.persist") as persist, \
         mock.patch("haos.owner.audit"):
        with pytest.raises(ValueError):
            owner_remote_locked(SimpleNamespace(remote_action="renew",
                                                id="my-phone", hours=hours))
        persist.assert_not_called()
