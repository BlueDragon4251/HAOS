import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("evidence_inspector", Path(__file__).parents[2] / "scripts/inspect-haos-evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def archive(name, content):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr(name, content)
    return stream.getvalue()


def test_digest_and_archive_paths_are_verified():
    data = archive("boot-1.log", "actual fixture")
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    assert evidence.unpack(data, digest) == {"boot-1.log": b"actual fixture"}
    with pytest.raises(ValueError, match="digest differs"):
        evidence.unpack(data, "sha256:" + "a" * 64)
    unsafe = archive("../protected", "fixture")
    with pytest.raises(ValueError, match="unsafe"):
        evidence.unpack(unsafe, "sha256:" + hashlib.sha256(unsafe).hexdigest())


def test_actual_receipt_must_match_guest_output_and_arbitrary_text_is_not_published():
    report = {"stage": 1, "boundary_checked": True, "result": "personal text must not be published"}
    encoded = json.dumps(report).encode()
    files = {"acceptance-1.json": encoded, "boot-1.log": b"HAOS_ACCEPTANCE_JSON=" + encoded + b"\n"}
    result = evidence.inspect(files)
    assert result["guest_receipts"][0]["assertions"] == {"boundary_checked": True}
    assert "personal text" not in str(result)
    files["boot-1.log"] = b"HAOS_ACCEPTANCE_FAILED\nHAOS_ACCEPTANCE_JSON=" + encoded
    with pytest.raises(ValueError, match="differs"):
        evidence.inspect(files)


def test_bounded_failure_diagnostics_are_redacted_and_not_whole_journals():
    report = {"reports": [{"name": "service journal", "output":
        'normal user chat\nPermissionError: Authorization: Bearer disposable-private-token\n'}]}
    files = {"boot-1.log": b"HAOS_DIAGNOSTICS_JSON=" + json.dumps(report).encode() + b"\n"}
    result = evidence.inspect(files)
    assert result["startup_errors"]
    assert "disposable-private-token" not in str(result)
    assert "normal user chat" not in str(result)


def test_build_diagnosis_exposes_only_fixed_size_identity_and_real_process_flags():
    files = {"image.json": json.dumps([{"Id": "sha256:" + "a" * 64, "Size": 12345,
             "Config": {"Env": ["private user content"]}, "History": "private build arguments"}]).encode(),
             "sbom-scanner-status.json": b'{"status":"exited","exit_code":137,"oom_killed":true,"error":"private path"}'}
    result = evidence.inspect_build(files, "b" * 40)
    assert result["scanner"] == {"status": "exited", "exit_code": 137, "oom_killed": True}
    assert result["installed_guest_acceptance"] is False and result["installed_inventory_acceptance"] is False
    assert "private" not in str(result) and result["image_bytes"] == 12345
    files["image.json"] = json.dumps([{"Id": "a" * 64, "Size": 12345}]).encode()
    assert evidence.inspect_build(files, "b" * 40)["image_id"] == "sha256:" + "a" * 64
    files["build-manifest.json"] = json.dumps({"source_commit": "c" * 40}).encode()
    with pytest.raises(ValueError, match="workflow source"):
        evidence.inspect_build(files, "b" * 40)


@pytest.mark.parametrize("field,value", [("Id", "private image text"), ("Size", True), ("Size", -1)])
def test_untrusted_build_identity_is_not_published(field, value):
    image = {"Id": "sha256:" + "a" * 64, "Size": 123}
    image[field] = value
    with pytest.raises(ValueError):
        evidence.inspect_build({"image.json": json.dumps([image]).encode()}, "b" * 40)


def inventory_files():
    index = {"source_commit": "b" * 40, "image_id": "sha256:" + "a" * 64,
        "installed_inventory_checks_passed": True, "complete_release_acceptance": False,
        "scanner": {"version": "1.54.1", "network_disabled": True,
                    "container": "ghcr.io/anchore/syft@sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa"},
        "coverage": {key: 80 if "python" in key else 100 for key in evidence.INVENTORY_COUNTS},
        "document_sha256": {key: "c" * 64 for key in evidence.INVENTORY_DOCUMENTS},
        "document_bytes": {key: 123 for key in evidence.INVENTORY_DOCUMENTS},
        "private": "must never be published"}
    return index, {"image.json": json.dumps([{"Id": "a" * 64, "Size": 12345}]).encode(),
                   "sbom-scanner-status.json": b'{"status":"exited","exit_code":0,"oom_killed":false}'}


def test_small_index_proves_image_inventory_without_claiming_guest_or_publishing_full_catalog():
    index, files = inventory_files()
    files["sbom-index.json"] = json.dumps(index).encode()
    flags = {key: key not in {"real_model_turn", "installed_owner_ui_acceptance"} for key in evidence.UI_FLAGS}
    files["ui-access-build-probe.json"] = json.dumps({**flags, "private": "must never be published"}).encode()
    report = evidence.inspect_build(files, "b" * 40)
    assert report["image_inventory"]["checks_passed"]
    assert not report["installed_guest_acceptance"] and not report["installed_inventory_acceptance"]
    assert not report["image_syft_json"]["present_in_this_artifact"]
    assert report["runtime_ui_boundary"] == flags and not flags["real_model_turn"]
    assert "must never" not in json.dumps(report) and "private" not in json.dumps(report)


@pytest.mark.parametrize("field,value", [("source_commit", "c" * 40), ("image_id", "sha256:" + "d" * 64),
                                        ("complete_release_acceptance", True), ("installed_inventory_checks_passed", 1)])
def test_conflicting_source_image_or_release_claim_in_index_is_denied(field, value):
    index, files = inventory_files()
    index[field] = value
    files["sbom-index.json"] = json.dumps(index).encode()
    with pytest.raises(ValueError, match="inventory index"):
        evidence.inspect_build(files, "b" * 40)


@pytest.mark.parametrize("section,key,value", [("coverage", "python_installed_versions", True),
    ("coverage", "rpm_installed_versions_architectures", 0), ("document_sha256", "image.syft.json", "private text"),
    ("document_bytes", "image.cdx.json", 128 * 1024 ** 2 + 1)])
def test_inventory_counts_hashes_and_document_sizes_remain_bounded(section, key, value):
    index, files = inventory_files()
    index[section][key] = value
    files["sbom-index.json"] = json.dumps(index).encode()
    with pytest.raises(ValueError, match="bounded image inventory"):
        evidence.inspect_build(files, "b" * 40)


def test_index_cannot_hide_scanner_failure_in_the_same_actual_run():
    index, files = inventory_files()
    files["sbom-index.json"] = json.dumps(index).encode()
    files["sbom-scanner-status.json"] = b'{"status":"exited","exit_code":137,"oom_killed":true}'
    with pytest.raises(ValueError, match="inventory index"):
        evidence.inspect_build(files, "b" * 40)


@pytest.mark.parametrize("field,value", [("observer_read_rpc_works", "private text"),
                                        ("real_model_turn", True), ("installed_owner_ui_acceptance", True)])
def test_providerless_build_probe_cannot_claim_a_real_turn_or_installed_owner(field, value):
    _, files = inventory_files()
    flags = {key: key not in {"real_model_turn", "installed_owner_ui_acceptance"} for key in evidence.UI_FLAGS}
    flags[field] = value
    files["ui-access-build-probe.json"] = json.dumps(flags).encode()
    with pytest.raises(ValueError, match="runtime UI boundary"):
        evidence.inspect_build(files, "b" * 40)


@pytest.mark.parametrize("field,value", [("path", ".github/workflows/foreign.yml"),
                                         ("event", "pull_request"), ("head_branch", "foreign-branch")])
def test_foreign_workflow_or_branch_is_denied_before_archive_access(monkeypatch, field, value):
    run = {"head_sha": "a" * 40, "status": "completed", "path": ".github/workflows/haos-image.yml",
           "event": "push", "head_branch": "agent/haos-foundation"}
    run[field] = value
    reads = []
    def get(path, **kwargs):
        reads.append(path)
        return run
    monkeypatch.setenv("HAOS_EVIDENCE_RUN", "123")
    monkeypatch.setattr(evidence, "get", get)
    with pytest.raises(ValueError, match="owner-branch"):
        evidence.main()
    assert reads == ["actions/runs/123"]
