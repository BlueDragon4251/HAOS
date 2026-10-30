#!/usr/bin/env python3
"""Actual Node/npm image installer in a fresh explicitly disposable namespace."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    if os.geteuid() != 0 or os.getpid() != 1 or os.environ.get('HAOS_DISPOSABLE_PHOTON_INSTALL') != '1':
        raise PermissionError('fresh disposable PID-1 image-build namespace required')
    root = Path('/usr/lib/haos'); root.mkdir(mode=0o755)
    source = Path('/input/hermes')
    if (source / '.herald-os-upstream-sha').read_text().strip() != 'f97608f178d1ffeca59860195ab7da295f7c8e5f':
        raise PermissionError('actual pinned pristine Hermes inputs required')
    shutil.copytree(source, root / 'hermes')
    sys.path.insert(0, '/repo/linux/haos/runtime')
    from install_photon import install
    result = install(root / 'photon', root / 'hermes/plugins/platforms/photon/sidecar', archive=Path('/input/node.tar.xz'))
    output = Path('/output')
    if list(output.iterdir()): raise PermissionError('empty unique fixture output required')
    shutil.copytree(root / 'photon', output / 'photon')
    shutil.copytree(root / 'hermes', output / 'hermes')
    receipt = {'schema': 1, 'actual_installer': True, 'node': result['node']['version'],
        'spectrum': result['spectrum_version'], 'hermes_commit': result['hermes_commit'],
        'runtime_programs': len(result['programs']), 'source_sha256': hashlib.sha256((root / 'photon/source.json').read_bytes()).hexdigest(),
        'dependency_lifecycle_scripts': False, 'network_scope': 'public locked npm dependencies only; no messaging SDK connection',
        'live_Photon_verified': False, 'private_UID_process_verified': False, 'OS_release_artifact': False}
    (output / 'install-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__': main()
