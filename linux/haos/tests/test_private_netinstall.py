from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/netinstall/private-install.sh"
def test_private_bootstrap_invariants():
    s = SCRIPT.read_text()
    assert 'set -Eeuo pipefail' in s
    assert 'read -r -s -p' in s
    assert 'REGISTRY_AUTH_FILE=' in s
    assert "read -r -p 'Type WIPE" in s
    assert 'bootc install to-disk --wipe --skip-fetch-check' in s
    assert 'rm -rf -- "$AUTHDIR"' in s
    assert '--password-stdin' in s
    assert 'findmnt -rn -S' in s
