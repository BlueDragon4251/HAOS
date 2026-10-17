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
