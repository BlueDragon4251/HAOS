from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts/netinstall/haos-install.sh"
def test_stable_not_dev_by_default():
    s=LAUNCHER.read_text()
    assert 'releases/stable-image.txt' in s
    assert 'curl -fsSL' in s
    assert ':dev)' in s
    assert 'private-install.sh" --public' in s
    assert 'validate_image "$image"' in s
