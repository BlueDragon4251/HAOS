"""Negative build-evidence contracts; real image cataloging has a separate gate."""
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("haos_sbom", Path(__file__).parents[1] / "runtime/verify_sbom.py")
sbom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbom)
COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64


def write(directory, name, value):
    (directory / name).write_text(json.dumps(value) if isinstance(value, (dict, list)) else value)


@pytest.fixture
def evidence(tmp_path):
    write(tmp_path, "image.syft.json", {"descriptor": {"name": "syft", "version": sbom.SYFT_VERSION},
          "source": {"type": "image", "version": COMMIT, "metadata": {"imageID": IMAGE}}})
    write(tmp_path, "image.json", [{"Id": IMAGE}])
    write(tmp_path, "image.cdx.json", {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [
          {"bom-ref": "python-example", "purl": "pkg:pypi/example_pkg@1.2.3"},
          {"bom-ref": "system-example", "purl": "pkg:rpm/fedora/example@2.3-1.fc44?arch=x86_64"}]})
    npm = {"bomFormat": "CycloneDX", "specVersion": "1.5", "metadata": {"tools": [{"vendor": "npm", "version": sbom.NPM_VERSION}]},
           "components": [{"bom-ref": "node-example", "purl": "pkg:npm/%40example/widget@1.2.3"}]}
    write(tmp_path, "npm.raw.cdx.json", npm)
    write(tmp_path, "npm.cdx.json", sbom.normalize_npm(npm))
    write(tmp_path, "python-runtime-installed.txt", "example-pkg==1.2.3\n")
    write(tmp_path, "python-runtime-requirements.txt", "example_pkg==1.2.3 \\\n    --hash=sha256:disposable-fixture\n")
    write(tmp_path, "rpm-with-epochs.txt", "example 0:2.3-1.fc44 x86_64\n")
    return tmp_path


def test_exact_image_inputs_and_scoped_package_names(evidence):
    result = sbom.verify(evidence, COMMIT)
    assert result["installed_inventory_checks_passed"]
    assert result["coverage"]["python_installed_versions"] == 1
    assert result["coverage"]["rpm_installed_versions_architectures"] == 1
    assert result["complete_release_acceptance"] is False
    assert result["document_sha256"]["image.cdx.json"] == sbom.digest(evidence / "image.cdx.json")
    assert sbom.package_url("pkg:npm/%40example/widget@1.2.3")[1] == "@example/widget"
    assert sbom.package_url("pkg:rpm/fedora/example@2.3-1.fc44?arch=x86_64&epoch=2")[2] == "2:2.3-1.fc44"


@pytest.mark.parametrize("change", ["commit", "image", "scanner"])
def test_foreign_source_or_scanner_cannot_reuse_evidence(evidence, change):
    value = sbom.load(evidence / "image.syft.json")
    if change == "commit": value["source"]["version"] = "c" * 40
    if change == "image": value["source"]["metadata"]["imageID"] = "sha256:" + "c" * 64
    if change == "scanner": value["descriptor"]["version"] = "unverified"
    write(evidence, "image.syft.json", value)
    with pytest.raises(ValueError):
        sbom.verify(evidence, COMMIT)


def test_missing_installed_python_and_empty_input_fail(evidence):
    write(evidence, "python-runtime-installed.txt", "example-pkg==1.2.3\nmissing-package==9.0\n")
    with pytest.raises(ValueError, match="Python"):
        sbom.verify(evidence, COMMIT)
    write(evidence, "python-runtime-installed.txt", "# no packages\n")
    with pytest.raises(ValueError, match="empty Python"):
        sbom.verify(evidence, COMMIT)


@pytest.mark.parametrize("inventory", ["example 0:2.3-1.fc44 aarch64\n", "example 1:2.3-1.fc44 x86_64\n"])
def test_other_architecture_or_nonzero_epoch_is_not_the_same_rpm(evidence, inventory):
    write(evidence, "rpm-with-epochs.txt", inventory)
    with pytest.raises(ValueError, match="RPM"):
        sbom.verify(evidence, COMMIT)


def test_duplicate_refs_and_empty_npm_graph_fail(evidence):
    value = sbom.load(evidence / "image.cdx.json")
    value["components"][1]["bom-ref"] = value["components"][0]["bom-ref"]
    write(evidence, "image.cdx.json", value)
    with pytest.raises(ValueError, match="ambiguous"):
        sbom.verify(evidence, COMMIT)
    write(evidence, "npm.cdx.json", {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []})
    with pytest.raises(ValueError):
        sbom.cdx_packages(sbom.load(evidence / "npm.cdx.json"))


def test_npm_duplicate_occurrences_preserve_locations_and_dependency_edges():
    npm = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [
        {"bom-ref": "same", "purl": "pkg:npm/example@1", "properties": [{"name": "path", "value": "first"}]},
        {"bom-ref": "same", "purl": "pkg:npm/example@1", "properties": [{"name": "path", "value": "second"}]}],
        "dependencies": [{"ref": "same", "dependsOn": ["first"]}, {"ref": "same", "dependsOn": ["second"]}]}
    result = sbom.normalize_npm(npm)
    assert len(result["components"]) == 1
    assert result["components"][0]["properties"] == [{"name": "path", "value": "first"}, {"name": "path", "value": "second"}]
    assert result["dependencies"] == [{"ref": "same", "dependsOn": ["first", "second"]}]
    assert len(npm["components"]) == 2  # original remains untouched
    npm["components"][1]["purl"] = "pkg:npm/example@2"
    with pytest.raises(ValueError, match="conflicting"):
        sbom.normalize_npm(npm)


def test_real_file_read_and_streamed_hash_keep_the_same_size_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(sbom, "LIMIT", 32)
    path = tmp_path / "catalog.json"
    data = b"x" * 32
    path.write_bytes(data)
    assert sbom.read(path) == data
    assert sbom.digest(path) == hashlib.sha256(data).hexdigest()
    path.write_bytes(data + b"x")
    with pytest.raises(ValueError, match="exceeds its bound"):
        sbom.read(path)
    with pytest.raises(ValueError, match="exceeds its bound"):
        sbom.digest(path)
