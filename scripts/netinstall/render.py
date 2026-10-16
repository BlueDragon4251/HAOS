#!/usr/bin/env python3
"""Render the Fedora 44 bootc Anaconda Kickstart using a digest-pinned OCI source.

Used by the isolated GH Actions netinstall builder. The owner may replace the
source at install time with GRUB's haos.image= option (also digest-pinned).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

SOURCE_RE = re.compile(
    r"(?:(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)\.)+[a-z][a-z0-9-]*"
    r"(?::[0-9]{1,5})?/[a-z0-9_]+(?:[./_-][a-z0-9_]+)*"
    r"@sha256:[0-9a-f]{64}\Z"
)


def validate_source(value: str) -> str:
    # No tags, URL parameters, shell metacharacters, HTTP plaintext, or creds.
    if not SOURCE_RE.fullmatch(value) or ".." in value or "//" in value:
        raise ValueError("image source must be an OCI registry hostname/name@sha256:64-hex digest")
    return value


def render_kickstart(image_ref: str, template: Path) -> str:
    source = validate_source(image_ref)
    text = template.read_text(encoding="utf-8")
    assert text.count("__HAOS_DEFAULT_IMAGE__") == 1, "invalid Netinstall template"
    text = text.replace("__HAOS_DEFAULT_IMAGE__", source)
    assert "%include /tmp/haos-netinstall-source.ks" in text
    assert "clearpart" not in "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-ref", required=True, help="public OCI image reference pinned to sha256 digest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template", type=Path, default=Path(__file__).with_name("netinstall.ks.in"))
    args = parser.parse_args()
    output = render_kickstart(args.image_ref, args.template)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
