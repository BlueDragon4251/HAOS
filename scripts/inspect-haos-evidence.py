#!/usr/bin/env python3
"""Read bounded, digest-verified HAOS guest evidence; publish no arbitrary artifacts."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux/haos"))
from haos.redaction import Redactor

REPOSITORY = "BlueDragon4251/HAOS"
LIMIT = 2 * 1024 * 1024
EXPANDED_LIMIT = 16 * 1024 * 1024


def get(endpoint, *, binary=False):
    result = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/" + endpoint],
                            capture_output=True, timeout=60)
    if result.returncode:
        # gh errors may contain signed download URLs. Never emit stderr.
        raise RuntimeError("GitHub evidence fetch failed")
    if len(result.stdout) > LIMIT:
        raise ValueError("evidence response exceeds the bounded inspection limit")
    return result.stdout if binary else json.loads(result.stdout)


def unpack(data, digest):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("evidence archive digest differs from GitHub metadata")
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(info.file_size for info in archive.infolist()) > EXPANDED_LIMIT:
            raise ValueError("evidence archive expands beyond the inspection limit")
        for info in archive.infolist():
            path = Path(info.filename)
            if path.is_absolute() or ".." in path.parts or info.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("unsafe evidence archive path")
            if not info.is_dir():
                if path.name in files:
                    raise ValueError("ambiguous evidence archive names")
                files[path.name] = archive.read(info)
    return files


def booleans(value, depth=0):
    """Guest receipts contain fixed test flags; no arbitrary result/chat text."""
    if depth > 4 or not isinstance(value, dict) or len(value) > 100:
        raise ValueError("unexpected acceptance receipt structure")
    result = {}
    for key, item in value.items():
        if not re.fullmatch(r"[a-z0-9_]{1,100}", key):
            raise ValueError("invalid guest evidence label")
        if type(item) is bool:
            result[key] = item
        elif isinstance(item, dict):
            result[key] = booleans(item, depth + 1)
    return result


def inspect(files):
    receipts, errors = [], []
    redactor = Redactor()
    for stage in (1, 2):
        log = files.get(f"boot-{stage}.log", b"").decode(errors="replace")
        failed = "HAOS_ACCEPTANCE_FAILED" in log
        emitted = re.findall(r"HAOS_ACCEPTANCE_JSON=(\{[^\r\n]+\})", log)
        name = f"acceptance-{stage}.json"
        if name in files:
            report = json.loads(files[name])
            if failed or not emitted or json.loads(emitted[-1]) != report or report.get("stage") != stage:
                raise ValueError("saved acceptance receipt differs from actual guest output")
            receipts.append({"stage": stage, "receipt_sha256": hashlib.sha256(files[name]).hexdigest(),
                             "assertions": booleans(report)})
        diagnostics = re.findall(r"HAOS_DIAGNOSTICS_JSON=(\{[^\r\n]+\})", log)
        for raw in diagnostics[-1:]:
            reports = json.loads(raw).get("reports", [])
            if not isinstance(reports, list) or len(reports) > 8:
                raise ValueError("invalid guest diagnostics structure")
            for report in reports:
                text = report.get("output", "")
                if not isinstance(text, str) or len(text) > 50000:
                    raise ValueError("invalid guest diagnostic payload")
                # Only bounded fixed-test startup errors. No complete journal,
                # config, environment, screenshots or personal files are emitted.
                lines = [line for line in text.splitlines() if re.search(r"(?:Error|Exception|Failed|failed|denied|refused|Traceback|File \"|ExecMainStatus=|ActiveState=failed)", line)]
                for line in lines[-20:]:
                    errors.append({"stage": stage, "message": redactor.text(line[:1000])})
        # The acceptance service's own exception can precede its bounded journal.
        for line in log.splitlines():
            if "HAOS_DIAGNOSTICS_JSON=" in line or "HAOS_ACCEPTANCE_JSON=" in line:
                continue
            if re.search(r"haos_guest\.py.*(?:Error|Exception)|(?:RuntimeError|PermissionError|TimeoutError|AssertionError):", line):
                errors.append({"stage": stage, "message": redactor.text(line[:1000])})
    source = None
    if "test-source.json" in files:
        data = json.loads(files["test-source.json"])
        source = {key: data[key] for key in ("image_source_commit", "guest_probe_commit", "harness_commit", "diagnostics_commit") if key in data}
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value) for value in source.values()):
            raise ValueError("invalid source identity receipt")
    return {"guest_receipts": receipts, "source_identities": source, "startup_errors": errors[:40]}


def inspect_build(files, source):
    """Fixed numeric build diagnostics only; never config/env/image history."""
    images = json.loads(files.get("image.json", b"null"))
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise ValueError("a unique actual image identity is required")
    image = images[0]
    identifier = image.get("Id")
    size = image.get("Size")
    if not isinstance(identifier, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", identifier):
        raise ValueError("invalid build image identity")
    if type(size) is not int or not 0 < size < 2 ** 63:
        raise ValueError("invalid build image size")
    if "build-manifest.json" in files and json.loads(files["build-manifest.json"]).get("source_commit") != source:
        raise ValueError("build manifest differs from workflow source")
    result = {"image_id": identifier, "image_bytes": size,
              "installed_guest_acceptance": False,
              "installed_inventory_acceptance": False}
    if "sbom-scanner-status.json" in files:
        state = json.loads(files["sbom-scanner-status.json"])
        if (state.get("status") not in {"created", "running", "exited", "dead"}
                or type(state.get("exit_code")) is not int or not -256 <= state["exit_code"] <= 256
                or type(state.get("oom_killed")) is not bool):
            raise ValueError("invalid scanner process receipt")
        result["scanner"] = {k: state[k] for k in ("status", "exit_code", "oom_killed")}
    for name in ("image.cdx.json", "image.syft.json"):
        data = files.get(name, b"")
        row = {"bytes": len(data), "json_valid": False}
        if data:
            try:
                document = json.loads(data)
                row["json_valid"] = isinstance(document, dict)
            except (ValueError, UnicodeError):
                pass
        result[name.replace(".", "_")] = row
    return result


def main():
    run_id = os.environ.get("HAOS_EVIDENCE_RUN", "")
    if not re.fullmatch(r"[0-9]{1,20}", run_id):
        raise ValueError("a numeric HAOS evidence run ID is required")
    kind = os.environ.get("HAOS_EVIDENCE_KIND", "guest")
    if kind not in {"guest", "build"}:
        raise ValueError("unsupported evidence kind")
    run = get(f"actions/runs/{run_id}")
    source = run["head_sha"]
    if run["status"] != "completed" or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("inspect only completed, source-bound HAOS runs")
    if (run.get("path") != ".github/workflows/haos-image.yml"
            or run.get("event") not in {"push", "workflow_dispatch"}
            or not run.get("head_branch", "").startswith("agent/haos-")):
        raise ValueError("inspect only owner-branch HAOS image workflow evidence")
    artifacts = get(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    accepted = []
    expected = f'haos-qemu-acceptance-{source}' if kind == "guest" else f'haos-build-metadata-{source}'
    for artifact in artifacts:
        if artifact["name"] != expected or artifact["expired"]:
            continue
        if artifact["size_in_bytes"] > LIMIT:
            raise ValueError("guest evidence archive exceeds the inspection limit")
        files = unpack(get(f"actions/artifacts/{artifact['id']}/zip", binary=True), artifact.get("digest", ""))
        accepted.append({"run_id": run_id, "workflow_source_commit": source, "artifact_id": artifact["id"],
                         "archive_digest": artifact["digest"],
                         **(inspect(files) if kind == "guest" else {"build_diagnostics": inspect_build(files, source)})})
    if len(accepted) != 1:
        raise ValueError("completed run has no unique bounded HAOS guest artifact")
    result = accepted[0]
    output = json.dumps(result, ensure_ascii=True)
    print(output, flush=True)
    if kind == "build":
        print("::notice title=HAOS verified bounded build diagnosis::" + output.replace("%", "%25"), flush=True)
        return
    for receipt in result["guest_receipts"]:
        note = json.dumps({key: result[key] for key in ("run_id", "workflow_source_commit", "artifact_id", "archive_digest")}
                          | receipt, ensure_ascii=True).replace("%", "%25")
        print(f"::notice title=HAOS verified guest boot {receipt['stage']}::{note}", flush=True)
    if result["startup_errors"]:
        # GitHub caps per-step annotations. Group bounded diagnostics so the
        # terminal exception is not discarded after earlier unit-state notices.
        note = json.dumps({"run_id": run_id, "errors": result["startup_errors"]}, ensure_ascii=True).replace("%", "%25")
        print(f"::notice title=HAOS bounded startup diagnostic::{note}", flush=True)
    # Owner-created isolated VM evidence only; no automatic success is invented.
    if not result["guest_receipts"] and not result["startup_errors"]:
        raise ValueError("guest artifact has no inspectable receipt or bounded startup diagnosis")


if __name__ == "__main__":
    main()
