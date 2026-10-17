"""Netinstall is a small, source-pinned Fedora installer, NOT an offline image."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "scripts/netinstall/render.py"
TEMPLATE = ROOT / "scripts/netinstall/netinstall.ks.in"
WORKFLOW = ROOT / ".github/workflows/haos-netinstall.yml"
digest = "a" * 64
valid = f"ghcr.io/bluedragon4251/haos@sha256:{digest}"

spec = importlib.util.spec_from_file_location("haos_netinstall_renderer", TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_source_digest_is_mandatory_and_no_credentials_or_path_injection():
    assert module.validate_source(valid) == valid
    for value in [
        "https://ghcr.io/bluedragon4251/haos:latest",
        "ghcr.io/bluedragon4251/haos:latest",
        "ghcr.io/bluedragon4251/haos@sha256:no",
        f"ghcr.io/x/../haos@sha256:{digest}",
        f"ghcr.io/user:pass@registry/haos@sha256:{digest}",
        f"ghcr.io/user/haos@sha256:{digest}\nclearpart --all",
        f"ghcr.io/user/haos@sha256:{digest} --no-signature-verification",
        "http://server.example/image.tar",
    ]:
        with pytest.raises(ValueError):
            module.validate_source(value)


def test_generated_kickstart_prompts_for_storage_and_boot_time_image_override(tmp_path):
    target = tmp_path / "installer.ks"
    subprocess.run([sys.executable, str(TOOL), "--image-ref", valid,
                    "--output", str(target)], check=True)
    text = target.read_text()
    assert "bootc --source-imgref=registry:" in text
    assert valid in text
    assert "haos.image=" in text
    assert "%pre --interpreter=/usr/bin/python3 --erroronfail" in text
    assert "%include /tmp/haos-netinstall-source.ks" in text
    for destructive in ["clearpart --all", "autopart --", "ignoredisk --only-use", "zerombr"]:
        assert not any(line.strip().startswith(destructive) for line in text.splitlines())
    script = text.split("%pre --interpreter=/usr/bin/python3 --erroronfail --log=/tmp/haos-netinstall-pre.log", 1)[1].split("%end", 1)[0]
    compile(script, "<anaconda %pre>", "exec")


def test_fedora_44_pinned_network_iso_and_ghcr_pipeline():
    data = WORKFLOW.read_text()
    assert "workflow_dispatch:" in data
    assert "packages: write" in data
    assert "sha256sum -c -" in data
    assert "bd285201494dd0ba09b54d05ac707de1401668b8512a573edb5922dcf9d7067e" in data
    assert "mkksiso -V HAOS_NETINSTALL" in data
    assert "podman push --digestfile" in data
    assert "registry.fedoraproject.org/fedora:44" in data
    assert "haos-netinstall-x86_64.iso" in data
    assert "quay.io/centos-bootc/bootc-image-builder" not in data
