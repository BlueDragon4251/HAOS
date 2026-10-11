#!/usr/bin/env python3
"""Real root-owned file/ELF/lock/revocation gate in an explicit disposable runner.

Only private fixture trees are modified. No host executable is run or changed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from haos.applications import ApplicationRegistry, executable_digest


def denied(call, error=(PermissionError, OSError, ValueError)):
    try:
        call()
    except error:
        return
    raise AssertionError('unauthorized application policy was accepted')


def main():
    if os.geteuid() != 0 or os.environ.get('HAOS_DISPOSABLE_APPLICATION_TEST') != '1':
        raise PermissionError('explicit disposable root fixture required')
    root = Path(tempfile.mkdtemp(prefix='haos-application-gate-', dir='/var/lib'))
    executable_root = Path(tempfile.mkdtemp(prefix='haos-application-gate-', dir='/usr/lib'))
    try:
        # The cloud checkout can be private to its development UID. Give the
        # negative UID only these unchanged, root-owned public Python sources,
        # never the private registry or the rest of the checkout.
        executable_root.chmod(0o755)
        sources = executable_root / 'python' / 'haos'
        sources.mkdir(mode=0o755, parents=True)
        sources.parent.chmod(0o755)
        for module in (Path(__file__).resolve().parents[1] / 'haos').glob('*.py'):
            target = sources / module.name
            shutil.copyfile(module, target); target.chmod(0o644)
        executable = executable_root / 'approved-elf'
        shutil.copyfile('/usr/bin/true', executable); executable.chmod(0o755)
        registry = ApplicationRegistry(root / 'applications.json')
        value = {'id': 'fixture-app', 'class': 'utility', 'executable': str(executable),
                 'sha256': executable_digest(executable), 'argv': [], 'memory_mib': 512, 'runtime_seconds': 30}
        assert registry.read()['applications'] == []
        registry.register(value)
        assert registry.resolve(value['id']) == value
        assert registry.path.stat().st_uid == 0 and registry.path.stat().st_mode & 0o777 == 0o600
        assert ApplicationRegistry(registry.path).resolve(value['id']) == value
        denied(lambda: registry.register(value))
        denied(lambda: registry.resolve('foreign'))
        with registry.lock():
            denied(lambda: ApplicationRegistry(registry.path).revoke(value['id']), BlockingIOError)
        content = executable.read_bytes(); executable.write_bytes(content + b'changed by isolated update')
        denied(lambda: registry.resolve(value['id']))
        executable.write_bytes(content)
        for mode in (0o777, 0o4755, 0o2755):
            executable.chmod(mode); denied(lambda: executable_digest(executable))
        executable.chmod(0o755)
        alias = executable_root / 'alias'; alias.symlink_to(executable)
        denied(lambda: executable_digest(alias)); alias.unlink()
        os.link(executable, alias); denied(lambda: executable_digest(executable)); alias.unlink()
        os.chown(executable, 65534, 65534); denied(lambda: executable_digest(executable)); os.chown(executable, 0, 0)
        script = executable_root / 'script'; script.write_text('#!/bin/sh\nexit 0\n'); script.chmod(0o755)
        denied(lambda: executable_digest(script))
        subprocess.run(['/usr/sbin/runuser', '-u', 'nobody', '--', '/usr/bin/python3', '-c',
            'import os,sys; sys.path.insert(0,sys.argv[1]); from haos.applications import ApplicationRegistry; '
            'assert os.geteuid()!=0; '
            '\ntry: ApplicationRegistry()\nexcept PermissionError: pass\nelse: raise AssertionError("foreign authority accepted")', str(sources.parent)],
            env={'PATH': '/usr/bin:/bin'}, check=True, timeout=10)
        registry.revoke(value['id']); denied(lambda: registry.resolve(value['id']))
        assert ApplicationRegistry(registry.path).read()['applications'] == []
        saved = registry.path.read_bytes()
        alias = root / 'linked-policy'; os.link(registry.path, alias)
        denied(registry.read); alias.unlink()
        registry.path.chmod(0o644); denied(registry.read); registry.path.chmod(0o600)
        registry.path.unlink(); registry.path.symlink_to(root / 'missing-policy'); denied(registry.read)
        registry.path.unlink(); registry.path.write_bytes(saved); registry.path.chmod(0o600)
        registry.path.write_text('{"version":1,"applications":[],"applications":[]}'); denied(registry.read)
        print(json.dumps({'actual_root_elf_grant_resolve_restart': True, 'explicit_revocation_survives_restart': True,
            'changed_executable_denied': True, 'unsafe_executable_owner_mode_links_script_denied': True,
            'unsafe_policy_mode_links_duplicate_keys_denied': True, 'concurrent_mutations_denied': True,
            'actual_unprivileged_grant_denied': True, 'host_application_executed': False}))
    finally:
        shutil.rmtree(root); shutil.rmtree(executable_root)


if __name__ == '__main__':
    main()
