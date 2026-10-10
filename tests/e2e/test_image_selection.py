"""Execute the real workflow selector offline; active or unrelated images cannot be reused."""

import io
import json
from pathlib import Path
import subprocess
import urllib.request

import pytest
import yaml


SOURCE = "a" * 40


def select(monkeypatch, tmp_path, *, requested="", active=False, invalid=None, ancestry=0, build="success"):
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/haos-acceptance.yml").read_text())
    step = next(s for s in workflow["jobs"]["install"]["steps"]
                if s.get("id") == "image")
    code = step["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    output = tmp_path / "output"
    for key, value in {"GITHUB_REPOSITORY": "BlueDragon4251/HAOS", "GITHUB_REF_NAME": "agent/haos-foundation",
                       "GH_TOKEN": "offline-fixture", "REQUESTED_IMAGE_RUN": requested, "GITHUB_OUTPUT": str(output)}.items():
        monkeypatch.setenv(key, value)
    artifact = {"name": "haos-x86_64-build-" + SOURCE, "id": 101, "expired": False,
                "workflow_run": {"id": 10, "head_sha": SOURCE, "head_branch": "agent/haos-foundation"}}
    identity = {"path": ".github/workflows/haos-image.yml", "head_sha": SOURCE,
                "head_branch": "agent/haos-foundation", "status": "in_progress" if active else "completed",
                "conclusion": "failure"}  # A failed guest gate may be repaired; build must have passed.
    if invalid:
        identity[invalid] = "unrelated"
    calls = []

    def urlopen(request, *, timeout):
        prefix = "https://api.github.com/repos/BlueDragon4251/HAOS"
        assert request.full_url.startswith(prefix) and timeout == 30
        path = request.full_url[len(prefix):]
        calls.append(path)
        if path in {"/actions/artifacts?per_page=100", "/actions/runs/10/artifacts?per_page=100"}:
            # In automatic selection a newer active image precedes the eligible
            # completed source. Do not dispatch a second install for that image.
            newer = {**artifact, "id": 102, "name": "haos-x86_64-build-" + "b" * 40,
                     "workflow_run": {**artifact["workflow_run"], "id": 11, "head_sha": "b" * 40}}
            data = {"artifacts": [newer, artifact] if not requested else [artifact]}
        elif path == "/actions/runs/11":
            data = {**identity, "head_sha": "b" * 40, "status": "in_progress"}
        elif path == "/actions/runs/10":
            data = identity
        elif path == "/actions/runs/10/jobs?per_page=100":
            data = {"jobs": [{"name": "build", "conclusion": build}]}
        else:
            pytest.fail("Selector accessed an unexpected endpoint: " + path)
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    def git(args, **kwargs):
        assert args[:3] == ["git", "merge-base", "--is-ancestor"] and args[-1] == "HEAD"
        return subprocess.CompletedProcess(args, ancestry)

    monkeypatch.setattr(subprocess, "run", git)
    exec(compile(code, "actual-haos-image-selector", "exec"), {})
    return output.read_text(), calls


def test_newer_active_install_is_not_duplicated(monkeypatch, tmp_path):
    output, calls = select(monkeypatch, tmp_path)
    assert "run_id=10\n" in output and "sha=" + SOURCE in output
    assert "/actions/runs/11/jobs?per_page=100" not in calls


def test_explicit_failed_guest_run_keeps_its_exact_image(monkeypatch, tmp_path):
    output, calls = select(monkeypatch, tmp_path, requested="10")
    assert "run_id=10\n" in output and calls[0] == "/actions/runs/10/artifacts?per_page=100"


def test_explicit_active_run_is_denied(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="still active"):
        select(monkeypatch, tmp_path, requested="10", active=True)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("requested", ["../10", "1\n0", "1" * 21])
def test_untrusted_requested_run_cannot_select_or_publish(monkeypatch, tmp_path, requested):
    with pytest.raises(ValueError, match="numeric run ID"):
        select(monkeypatch, tmp_path, requested=requested)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("invalid", ["path", "head_sha", "head_branch"])
def test_unrelated_run_identity_cannot_be_selected(monkeypatch, tmp_path, invalid):
    with pytest.raises(RuntimeError, match="No completed"):
        select(monkeypatch, tmp_path, requested="10", invalid=invalid)
    assert not (tmp_path / "output").exists()


def test_unverifiable_ancestry_fails_closed(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="Cannot verify"):
        select(monkeypatch, tmp_path, requested="10", ancestry=128)
    assert not (tmp_path / "output").exists()


def test_failed_build_cannot_be_reused(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="No completed"):
        select(monkeypatch, tmp_path, requested="10", build="failure")
    assert not (tmp_path / "output").exists()
