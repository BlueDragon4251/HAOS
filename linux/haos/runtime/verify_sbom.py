#!/usr/bin/env python3
"""Bind actual image catalogs to build inputs and reject missing installed packages."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

SYFT_IMAGE = "ghcr.io/anchore/syft@sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa"
SYFT_VERSION = "1.54.1"
NPM_VERSION = "10.9.4"
LIMIT = 128 * 1024 * 1024


def read(path):
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("SBOM input exceeds its bound")
    return data


def load(path):
    return json.loads(read(path))


def digest(path):
    # Real image catalogs are large. Hash the unchanged document without a
    # second whole-file allocation, retaining the same input size boundary.
    value, length = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            length += len(chunk)
            if length > LIMIT:
                raise ValueError("SBOM input exceeds its bound")
            value.update(chunk)
    return value.hexdigest()


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def python_versions(text):
    result = set()
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if match:
            result.add((normalized(match[1]), match[2]))
    if not result:
        raise ValueError("empty Python package inventory")
    return result


def package_url(value):
    if not isinstance(value, str) or not value.startswith("pkg:"):
        return None
    parts = urlsplit(value)
    kind, separator, rest = parts.path.partition("/")
    name, version_separator, version = rest.rpartition("@")
    if not separator or not version_separator:
        return None
    kind = kind.removeprefix("pkg:")
    name = unquote(name.rsplit("/", 1)[-1] if kind == "rpm" else name)
    version = unquote(version)
    qualifiers = parse_qs(parts.query)
    if kind == "pypi":
        name = normalized(name)
    if kind == "rpm":
        epoch = qualifiers.get("epoch", ["0"])
        if len(epoch) != 1 or not re.fullmatch(r"[0-9]{1,10}", epoch[0]):
            raise ValueError("invalid RPM epoch qualifier")
        number = int(epoch[0])
        if version.startswith("0:"):
            version = version[2:]
        if number:
            prefix = str(number) + ":"
            if re.match(r"^[0-9]+:", version) and not version.startswith(prefix):
                raise ValueError("contradictory RPM epoch")
            if not version.startswith(prefix):
                version = prefix + version
    return kind, name, version, qualifiers.get("arch", [""])[0]


def cdx_packages(value):
    if value.get("bomFormat") != "CycloneDX" or value.get("specVersion") not in {"1.5", "1.6"}:
        raise ValueError("expected a supported CycloneDX 1.5/1.6 SBOM")
    components = value.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("empty SBOM components")
    references = [row.get("bom-ref") for row in components]
    if any(not isinstance(ref, str) or not ref for ref in references) or len(set(references)) != len(references):
        raise ValueError("ambiguous SBOM component references")
    return {package for row in components if (package := package_url(row.get("purl"))) is not None}


def normalize_npm(value):
    """Preserve identical npm package occurrences/edges under one unambiguous ref."""
    result = json.loads(json.dumps(value))
    components, seen = [], {}
    for row in result.get("components", []):
        ref = row.get("bom-ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("npm component lacks its reference")
        if ref not in seen:
            seen[ref] = row
            components.append(row)
            continue
        prior = seen[ref]
        if ({k: v for k, v in prior.items() if k != "properties"}
                != {k: v for k, v in row.items() if k != "properties"}):
            raise ValueError("conflicting npm packages share a component reference")
        # npm 10.9.4 emits the same component ref at multiple install paths.
        # Keep every actual occurrence property; never resolve a version/hash
        # conflict by dropping a row.
        prior.setdefault("properties", [])
        for prop in row.get("properties", []):
            if prop not in prior["properties"]:
                prior["properties"].append(prop)
    result["components"] = components
    dependencies, seen = [], {}
    for row in result.get("dependencies", []):
        if not isinstance(row, dict) or set(row) - {"ref", "dependsOn"}:
            raise ValueError("unsupported npm dependency record")
        ref = row.get("ref")
        if not isinstance(ref, str) or not isinstance(row.get("dependsOn", []), list):
            raise ValueError("invalid npm dependency reference")
        if ref not in seen:
            seen[ref] = row
            dependencies.append(row)
            continue
        prior = seen[ref]
        prior.setdefault("dependsOn", [])
        for target in row.get("dependsOn", []):
            if target not in prior["dependsOn"]:
                prior["dependsOn"].append(target)
    result["dependencies"] = dependencies
    cdx_packages(result)
    return result


def verify(directory, commit):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("SBOM evidence requires an exact Git commit")
    catalog = load(directory / "image.syft.json")
    descriptor = catalog.get("descriptor", {})
    if descriptor.get("name") != "syft" or descriptor.get("version") != SYFT_VERSION:
        raise ValueError("image catalog tool version differs from the pinned scanner")
    source = catalog.get("source", {})
    image = load(directory / "image.json")
    if not isinstance(image, list) or len(image) != 1:
        raise ValueError("expected one built image identity")
    identifier = image[0].get("Id", "")
    if not identifier.startswith("sha256:"):
        identifier = "sha256:" + identifier
    if (not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier) or source.get("type") != "image"
            or source.get("version") != commit or source.get("metadata", {}).get("imageID") != identifier):
        raise ValueError("catalog source does not match the built image and commit")
    packages = cdx_packages(load(directory / "image.cdx.json"))
    # Keep the npm build graph as a separate CycloneDX document. Bundled web
    # code/ASAR need this evidence even when image file catalogers miss it.
    raw_npm = load(directory / "npm.raw.cdx.json")
    tools = raw_npm.get("metadata", {}).get("tools", [])
    if not any(tool.get("vendor") == "npm" and tool.get("version") == NPM_VERSION for tool in tools):
        raise ValueError("npm SBOM tool differs from the pinned version")
    npm_document = load(directory / "npm.cdx.json")
    if normalize_npm(raw_npm) != npm_document:
        raise ValueError("normalized npm graph differs from its preserved original")
    npm = cdx_packages(npm_document)
    if not any(package[0] == "npm" for package in npm):
        raise ValueError("the build npm graph is missing")
    installed = python_versions(read(directory / "python-runtime-installed.txt").decode())
    frozen = python_versions(read(directory / "python-runtime-requirements.txt").decode())
    discovered = {(name, version) for kind, name, version, _ in packages if kind == "pypi"}
    if not frozen.issubset(installed) or not installed.issubset(discovered):
        raise ValueError("installed/frozen Python versions are missing from the actual image SBOM")
    rpm = set()
    for line in read(directory / "rpm-with-epochs.txt").decode().splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("invalid installed RPM inventory")
        name, version, arch = fields
        # RPM key pseudo-packages have no architecture; retain the record and
        # normalize rpm's textual '(none)' to the absent PURL qualifier.
        rpm.add((name, version.removeprefix("0:"), "" if arch == "(none)" else arch))
    discovered_rpm = {(name, version, arch) for kind, name, version, arch in packages if kind == "rpm"}
    if not rpm or not rpm.issubset(discovered_rpm):
        raise ValueError("installed RPM name/version/architecture is missing from the actual image SBOM")
    paths = ["image.cdx.json", "image.syft.json", "npm.cdx.json", "npm.raw.cdx.json", "image.json",
             "python-runtime-installed.txt", "python-runtime-requirements.txt", "rpm-with-epochs.txt"]
    return {"schema": 1, "source_commit": commit, "image_id": identifier,
            "scanner": {"version": SYFT_VERSION, "container": SYFT_IMAGE, "network_disabled": True},
            "npm_generator": {"version": NPM_VERSION, "original_retained": True,
                              "normalized_component_occurrences": len(raw_npm["components"]) - len(npm_document["components"])},
            "document_sha256": {name: digest(directory / name) for name in paths},
            "document_bytes": {name: (directory / name).stat().st_size for name in paths},
            "coverage": {"python_installed_versions": len(installed), "python_frozen_versions": len(frozen),
                         "rpm_installed_versions_architectures": len(rpm),
                         "image_package_types": dict(sorted(Counter(row[0] for row in packages).items())),
                         "npm_build_packages": sum(row[0] == "npm" for row in npm)},
            "installed_inventory_checks_passed": True, "complete_release_acceptance": False,
            "limitations": ["catalogs are not proof that every embedded/vendored component was identified",
                            "npm build graph and image catalog are distinct documents, not a merged dependency graph",
                            "vulnerability, licensing, provenance, signing, hardware and behavioral acceptance are separate gates"]}


def main():
    if sys.platform.startswith("linux"):
        import resource
        # Bound this verifier process independently of the image scanner. Never
        # raise a smaller enclosing limit; callers importing verify() retain
        # control of their own process limits.
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = 2 * 1024 ** 3 if hard == resource.RLIM_INFINITY else min(hard, 2 * 1024 ** 3)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument("--commit")
    parser.add_argument("--normalize-npm", type=Path, nargs=2, metavar=("RAW", "OUTPUT"))
    args = parser.parse_args()
    if args.normalize_npm:
        if args.directory or args.commit:
            parser.error("npm normalization and image verification are separate commands")
        original, destination = args.normalize_npm
        with destination.open("x") as stream:
            json.dump(normalize_npm(load(original)), stream, indent=2)
            stream.write("\n")
        return
    if not args.directory or not args.commit:
        parser.error("image verification requires the evidence directory and exact --commit")
    report = verify(args.directory, args.commit)
    destination = args.directory / "sbom-index.json"
    with destination.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"source_commit": report["source_commit"], "image_id": report["image_id"],
                      "installed_inventory_checks_passed": True, "coverage": report["coverage"]}))


if __name__ == "__main__":
    main()
