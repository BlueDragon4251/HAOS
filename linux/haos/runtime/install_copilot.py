#!/usr/bin/env python3
"""Image build: bounded official archive, exact reviewed digest and fixed binary."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def main():
    source = json.loads(Path(__file__).with_name("copilot-source.json").read_text())
    target = Path(sys.argv[1])
    target.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="haos-copilot-build-") as directory:
        archive = Path(directory) / "copilot.tar.gz"
        subprocess.run(["/usr/bin/curl", "--fail", "--silent", "--show-error", "--location", "--proto", "=https",
                        "--max-time", "180", "--max-filesize", "150000000", "--output", str(archive), source["url"]], check=True)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != source["sha256"]:
            raise PermissionError("Copilot archive differs from reviewed source digest")
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            if len(members) != 1 or members[0].name != "copilot" or not members[0].isfile() or members[0].size > 400000000:
                raise PermissionError("unexpected Copilot archive layout")
            data = bundle.extractfile(members[0]).read()
            if not data.startswith(b"\x7fELF"):
                raise ValueError("Copilot image requires the native Linux binary")
            (target / "copilot").write_bytes(data)
            (target / "copilot").chmod(0o755)
    version = subprocess.check_output([str(target / "copilot"), "--version"], text=True, timeout=15)
    if "GitHub Copilot CLI " + source["version"] + "." not in version:
        raise ValueError("Copilot version differs from pinned provenance")
    (target / "source.json").write_text(json.dumps(source, indent=2) + "\n")


if __name__ == "__main__":
    main()
