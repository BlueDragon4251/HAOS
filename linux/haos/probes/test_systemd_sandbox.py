"""Launch the real namespace under production systemd hardening on disposable CI."""

import configparser
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from test_kernel import run_agent_filesystem_probe


def test_production_systemd_hardening_allows_only_the_isolated_agent_view():
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("HAOS_DISPOSABLE_CI") == "1"
    assert os.getuid() != 0
    fixture = Path(os.environ["HAOS_SYSTEMD_FIXTURE_DIR"]).resolve(strict=True)
    assert fixture.parent == Path("/run") and fixture.name.startswith("haos-systemd-")
    assert fixture.stat().st_uid == os.getuid()
    keys = ("UMask", "NoNewPrivileges", "CapabilityBoundingSet", "AmbientCapabilities",
            "PrivateDevices", "PrivateTmp", "ProtectSystem", "ProtectHome",
            "ProtectKernelTunables", "ProtectKernelModules", "ProtectControlGroups",
            "ProtectProc", "RestrictSUIDSGID", "RestrictAddressFamilies", "LockPersonality",
            "TasksMax", "MemoryHigh", "MemoryMax")
    # systemd list directives legitimately repeat (e.g. LoadCredential). Read
    # the scalar hardening properties this probe actually launches, retaining
    # strict duplicate/missing-key rejection for every tested restriction.
    # Full unit syntax and credential delivery remain separate actual checks.
    service, selected = False, []
    for line in (Path(__file__).parents[1] / "haos-hermes.service").read_text().splitlines():
        if line.strip().startswith("["):
            service = line.strip() == "[Service]"
        elif service and line.partition("=")[0].strip() in keys:
            selected.append(line)
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read_string("[Service]\n" + "\n".join(selected))
    properties = {key: config["Service"][key] for key in keys}

    with tempfile.TemporaryDirectory(prefix="probe-", dir=fixture) as directory:
        root = Path(directory)

        def launch(args, fd):
            # systemd owns the actual service credential descriptor. No credential
            # value enters the command line or public environment.
            credential = Path(os.readlink(f"/proc/self/fd/{fd}"))
            assert credential.is_relative_to(root)
            arguments = root / "arguments.json"
            arguments.write_text(json.dumps(args))
            stager = root / "launch.py"
            stager.write_text('''import json, os
from pathlib import Path
args = json.loads((Path(__file__).parent / "arguments.json").read_text())
fd = os.open(Path(os.environ["CREDENTIALS_DIRECTORY"]) / "backend-token", os.O_RDONLY | os.O_NOFOLLOW)
os.set_inheritable(fd, True)
args[args.index("--ro-bind-data") + 1] = str(fd)
os.execv(args[0], args)
''')
            unit = "haos-systemd-probe-" + uuid.uuid4().hex
            command = ["sudo", "-n", "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
                       "--unit=" + unit, f"--property=User={os.getuid()}", f"--property=Group={os.getgid()}",
                       "--property=RuntimeMaxSec=45",
                       "--property=WorkingDirectory=" + str(root), "--property=ReadWritePaths=" + str(root),
                       "--property=LoadCredential=backend-token:" + str(credential)]
            command += ["--property=" + key + "=" + value for key, value in properties.items()]
            return subprocess.run(command + ["/usr/bin/python3", "-I", str(stager)],
                                  capture_output=True, text=True, timeout=60)

        proof = run_agent_filesystem_probe(root, launcher=launch)
        print(json.dumps({"production_systemd_hardening": True, **proof}))
