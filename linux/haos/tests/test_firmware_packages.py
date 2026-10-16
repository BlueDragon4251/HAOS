"""Protect laptop Wi-Fi/Bluetooth/audio firmware in every HAOS bootc build.

The installed HP Intel AX211 required iwlwifi-so-a0-gf-a0-89.ucode, which was
absent from the base image. Temporary dnf installs on an unlocked /usr overlay
do not survive reboot, so packages must remain in the image's package manifest.
"""
from pathlib import Path

IMAGE_DIR = Path(__file__).resolve().parents[2] / "image"
FIRMWARE = (
    "iwlwifi-mvm-firmware",
    "iwlwifi-mld-firmware",
    "iwlbluetooth-firmware",
    "alsa-sof-firmware",
)


def test_bootc_image_installs_all_four_intel_firmware_packages():
    manifest = IMAGE_DIR.joinpath("packages.txt").read_text().splitlines()
    packages = [line.strip() for line in manifest if line.strip() and not line.lstrip().startswith("#")]
    assert "NetworkManager-wifi" in packages
    for firmware in FIRMWARE:
        assert packages.count(firmware) == 1, f"{firmware} must be present exactly once"


def test_immutable_image_uses_the_checked_firmware_manifest():
    installer = IMAGE_DIR.joinpath("packages.sh").read_text()
    assert 'list "$LINUX/image/packages.txt"' in installer
    assert 'dnf -y install --setopt=install_weak_deps=False "${PACKAGES[@]}"' in installer


def test_firmware_image_gate_avoids_grep_quiet_sigpipe_under_pipefail():
    # "rpm -ql ... | grep -q" can return 141 (SIGPIPE from rpm) when the
    # match is found early. Image verification must inspect the whole RPM
    # listing without a short-circuiting producer/consumer pipe.
    workflow = (IMAGE_DIR.parent.parent / ".github" / "workflows" / "haos-image.yml").read_text()
    gate = workflow.split("- name: Verify Intel wireless, Bluetooth and audio firmware in the built image", 1)[1]
    gate = gate.split("\n      - name:", 1)[0]
    assert 'firmware_files="$(rpm -ql iwlwifi-mvm-firmware)"' in gate
    assert '<<< "$firmware_files"' in gate
    assert "| grep -q" not in gate
