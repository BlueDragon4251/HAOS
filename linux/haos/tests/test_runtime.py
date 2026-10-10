import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("runtime_prepare", Path(__file__).parents[1] / "runtime/prepare.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.fixture
def inputs(tmp_path):
    upstream, overlay = tmp_path / "upstream", tmp_path / "overlay"
    upstream.mkdir()
    overlay.mkdir()
    (upstream / ".herald-os-upstream-sha").write_text("a" * 40 + "\n")
    (upstream / "pyproject.toml").write_text('dependencies = ["PyJWT[crypto]==2.13.0"]\n')
    (upstream / "uv.lock").write_text("fixture upstream lock\n")
    (overlay / "requirements.txt").write_text("pyjwt==2.15.1 \\\n    --hash=sha256:" + "b" * 64 + "\n")
    source = {"upstream_commit": "a" * 40, "python": "3.11", "extras": ["web", "messaging"],
              "security_versions": {"pyjwt": "2.15.1"}}
    for filename, key, root in [("pyproject.toml", "pyproject_sha256", upstream),
                                ("uv.lock", "uv_lock_sha256", upstream),
                                ("requirements.txt", "requirements_sha256", overlay)]:
        source[key] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
    (overlay / "source.json").write_text(json.dumps(source))
    return upstream, overlay


def test_check_does_not_mutate_upstream(inputs):
    runtime.prepare(*inputs, check_only=True)
    assert "2.13.0" in (inputs[0] / "pyproject.toml").read_text()


def test_reviewed_constraint_is_applied(inputs):
    runtime.prepare(*inputs)
    assert '"PyJWT[crypto]==2.15.1"' in (inputs[0] / "pyproject.toml").read_text()


@pytest.mark.parametrize("file,root", [(".herald-os-upstream-sha", 0), ("pyproject.toml", 0),
                                     ("uv.lock", 0), ("requirements.txt", 1)])
def test_changed_inputs_are_refused_before_modification(inputs, file, root):
    path = inputs[root] / file
    path.write_text(path.read_text() + "tampered")
    before = (inputs[0] / "pyproject.toml").read_bytes()
    with pytest.raises(ValueError):
        runtime.prepare(*inputs)
    assert (inputs[0] / "pyproject.toml").read_bytes() == before


def test_mismatched_reviewed_security_version(inputs):
    path = inputs[1] / "source.json"
    source = json.loads(path.read_text())
    source["security_versions"]["pyjwt"] = "2.13.0"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="security version mismatch"):
        runtime.prepare(*inputs)
