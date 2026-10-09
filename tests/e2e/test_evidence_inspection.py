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
