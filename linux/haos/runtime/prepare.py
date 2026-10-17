#!/usr/bin/env python3
"""Apply the reviewed dependency overlay only to its exact upstream snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def prepare(upstream: Path, overlay: Path, *, check_only=False):
    source = json.loads((overlay / "source.json").read_text())
    if (upstream / ".herald-os-upstream-sha").read_text().strip() != source["upstream_commit"]:
        raise ValueError("runtime overlay belongs to another Hermes commit")
    for filename, key in [("pyproject.toml", "pyproject_sha256"), ("uv.lock", "uv_lock_sha256")]:
        if hashlib.sha256((upstream / filename).read_bytes()).hexdigest() != source[key]:
            raise ValueError("upstream input changed: " + filename)
    requirements = (overlay / "requirements.txt").read_bytes()
    if hashlib.sha256(requirements).hexdigest() != source["requirements_sha256"]:
        raise ValueError("hashed runtime requirements changed without review")
    if source["python"] != "3.11" or source["extras"] != ["web", "messaging"]:
        raise ValueError("runtime target changed")
    for name, version in source["security_versions"].items():
        versions = re.findall(rf"^{re.escape(name)}==([^\s;]+)", requirements.decode(), re.M)
        if versions != [version]:
            raise ValueError("security version mismatch: " + name)
    path = upstream / "pyproject.toml"
    text = path.read_text()
    original = '"PyJWT[crypto]==2.13.0"'
    replacement = '"PyJWT[crypto]==' + source["security_versions"]["pyjwt"] + '"'
    if text.count(original) != 1:
        raise ValueError("upstream PyJWT constraint changed; review this overlay")
    if not check_only:
        path.write_text(text.replace(original, replacement))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("overlay", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    prepare(args.upstream, args.overlay, check_only=args.check)
