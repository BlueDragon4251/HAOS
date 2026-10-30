#!/usr/bin/env python3
"""Image build only: exact official Node, locked SDK and reviewed native hooks."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

from prepare_photon import prepare, INPUTS


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024): digest.update(block)
    return digest.hexdigest()


def extract(archive, node, work, source):
    if archive.stat().st_size > 64000000 or sha(archive) != source['node']['sha256']:
        raise PermissionError('Node archive differs from reviewed official Photon runtime input')
    prefix = 'node-v' + source['node']['version'] + '-linux-x64/'
    with tarfile.open(archive, 'r:xz') as bundle:
        members = bundle.getmembers()
        if len(members) > 15000: raise ValueError('bounded Node distribution required')
        selected = []; total = 0
        for member in members:
            if member.name == prefix[:-1] and member.isdir(): continue
            if not member.name.startswith(prefix): raise ValueError('unexpected Node archive root')
            relative = member.name[len(prefix):]; parts = PurePosixPath(relative).parts
            if relative.startswith('/') or '..' in parts: raise ValueError('unsafe Node archive path')
            if relative != 'bin/node' and not relative.startswith('lib/node_modules/npm/'): continue
            if member.isdir(): continue
            if not member.isfile() or not 0 <= member.size <= (400000000 if relative == 'bin/node' else 16000000):
                raise ValueError('bounded regular Node/npm build inputs required')
            total += member.size
            if total > 512 * 1024 * 1024: raise ValueError('Node/npm distribution exceeds budget')
            selected.append((member, node if relative == 'bin/node' else work / relative))
        binaries = [entry for entry in selected if entry[1] == node]
        if len(binaries) != 1: raise ValueError('one official Node executable required')
        for member, target in selected:
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = bundle.extractfile(member).read(member.size + 1)
            if len(raw) != member.size: raise ValueError('incomplete Node distribution entry')
            if target == node and (raw[:6] != b'\x7fELF\x02\x01' or raw[18:20] != b'\x3e\x00'):
                raise ValueError('actual Linux x86-64 Node executable required')
            with target.open('xb') as output: output.write(raw)
            target.chmod(0o755 if target == node else 0o644)
    return work / 'lib/node_modules/npm/bin/npm-cli.js'


def install(target, sidecar, *, archive=None):
    if os.geteuid() != 0: raise PermissionError('immutable image build root required; never run from the gateway')
    overlay = Path(__file__).resolve().parent; source = json.loads((overlay / 'photon-source.json').read_text())
    target = Path(target); sidecar = Path(sidecar)
    if (target != Path('/usr/lib/haos/photon') or sidecar != Path('/usr/lib/haos/hermes/plugins/platforms/photon/sidecar')
            or target.resolve() != target or sidecar.resolve() != sidecar
            or (sidecar.parents[3] / '.herald-os-upstream-sha').read_text().strip() != source['hermes_commit']):
        raise PermissionError('exact canonical pinned Hermes/Photon image layout required')
    # Validate all pristine upstream manifests before invoking npm. SDK files
    # are then checked against their actual published hashes by prepare().
    for name, expected in INPUTS.items():
        if name.startswith('node_modules/'): continue
        if sha(sidecar / name) != expected: raise ValueError('Photon source changed before dependency preparation')
    target.mkdir(mode=0o755, parents=True)  # Never overwrite an existing runtime.
    with tempfile.TemporaryDirectory(prefix='haos-photon-build-') as directory:
        work = Path(directory)
        if archive is None:
            archive = work / 'node.tar.xz'
            subprocess.run(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--proto', '=https', '--max-time', '180',
                '--max-filesize', '64000000', '--output', str(archive), source['node']['url']], check=True)
        else: archive = Path(archive)
        node = target / 'node'; npm = extract(archive, node, work, source)
        env = {**os.environ, 'PATH': str(target) + ':/usr/bin:/bin', 'HOME': str(work), 'NODE_OPTIONS': '', 'NODE_PATH': '', 'NPM_CONFIG_UPDATE_NOTIFIER': 'false'}
        version = subprocess.check_output([str(node), '--version'], env=env, text=True, timeout=10).strip()
        if version != 'v' + source['node']['version']: raise ValueError('Node version differs from pinned runtime')
        user_config = work / 'npm-user.conf'; global_config = work / 'npm-global.conf'
        user_config.write_text(''); global_config.write_text('')
        subprocess.run([str(node), str(npm), 'ci', '--prefix', str(sidecar), '--ignore-scripts', '--no-audit', '--no-fund',
            '--cache', str(work / 'npm-cache'), '--userconfig', str(user_config), '--globalconfig', str(global_config)],
            env=env, cwd=str(sidecar), check=True, timeout=300)
        prepared = prepare(sidecar)
        # Public immutable program inputs copied from a private checkout may
        # carry 0700 modes. The installed service must be able to traverse them.
        for directory in [sidecar, *sidecar.parents[:4]]:
            if directory.lstat().st_uid != 0: raise PermissionError('root-owned installed Photon source required')
            directory.chmod(0o755)
        (sidecar.parent / 'adapter.py').chmod(0o644)
        (sidecar.parents[3] / '.herald-os-upstream-sha').chmod(0o644)
        for entry in sidecar.rglob('*'):
            if entry.is_symlink():
                if not entry.resolve().is_relative_to(sidecar): raise PermissionError('Photon dependency link escapes immutable runtime')
                continue
            if entry.lstat().st_uid != 0: raise PermissionError('root-owned Photon dependency required')
            entry.chmod(0o755 if entry.is_dir() else 0o644)
        for filename in ['photon_sidecar.mjs', 'photon_bounded_stream.mjs']:
            shutil.copyfile(overlay / filename, target / filename); (target / filename).chmod(0o644)
        programs = {'node': node, 'launcher': target / 'photon_sidecar.mjs', 'bounded-stream': target / 'photon_bounded_stream.mjs',
            'sidecar': sidecar / 'index.mjs', 'format': sidecar / 'send-format.mjs', 'staleness': sidecar / 'stream-staleness.mjs',
            'compatibility': sidecar / 'patch-spectrum-mixed-attachments.mjs',
            'imessage': sidecar / 'node_modules/@spectrum-ts/imessage/dist/index.js',
            'stream': sidecar / 'node_modules/@spectrum-ts/core/dist/authoring.js', 'adapter': sidecar.parent / 'adapter.py',
            'manifest': sidecar / 'package.json', 'lockfile': sidecar / 'package-lock.json'}
        result = {**source, 'schema': 1, 'prepared': prepared,
            'programs': [{'name': name, 'sha256': sha(path)} for name, path in programs.items()]}
        (target / 'source.json').write_text(json.dumps(result, indent=2) + '\n'); (target / 'source.json').chmod(0o644)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    parser.add_argument('sidecar', type=Path)
    parser.add_argument('--archive', type=Path, help='already downloaded image-build input; the exact digest is still mandatory')
    args = parser.parse_args()
    print(json.dumps(install(args.target, args.sidecar, archive=args.archive)))
