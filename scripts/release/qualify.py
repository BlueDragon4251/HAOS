#!/usr/bin/env python3
"""Fail-closed source-matched HAOS build qualification; NEVER publishes a stable release.

The GitHub Actions artifact is an evidence summary only. It does not vouch for
feature completeness, publisher signing or physical hardware compatibility.
"""
import argparse
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WORKFLOWS = {
    "ci": ("CI", None),
    "services": ("HAOS services and kernel boundaries", None),
    "mobile": ("HAOS Native Android Mobile", "haos-mobile-debug-apk"),
    "dual_iso": ("HAOS Dual-Channel Live ISO (release candidate tests)",
                 "haos-dual-channel-iso-{sha}"),
    "netinstall": ("HAOS Netinstall (GHCR + small online installer)",
                   "haos-netinstall-x86_64-{sha}"),
    "offline_iso_and_qemu": ("HAOS x86_64 image and installer build",
                              "haos-qemu-acceptance-{sha}"),
}
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class QualificationError(ValueError):
    pass


def qualifies(source_sha, runs, artifacts_by_run):
    if not SHA.fullmatch(source_sha):
        raise QualificationError("source must be the exact immutable 40-digit commit SHA")
    result = {"schema": 1, "source_commit": source_sha,
              "release_status": "development-candidate-only",
              "production_release": False, "signed": False,
              "complete": False, "checks": {}}
    failures = []
    for key, (name, required_artifact) in WORKFLOWS.items():
        valid = [r for r in runs
                 if r.get("name") == name and r.get("head_sha") == source_sha
                 and r.get("status") == "completed" and r.get("conclusion") == "success"]
        if not valid:
            failures.append(f"{key}: no successful source-matched run")
            result["checks"][key] = {"ok": False, "reason": "missing-successful-run"}
            continue
        # A successful run with a missing or expired artifact is not accepted.
        valid.sort(key=lambda x: int(x["id"]), reverse=True)
        passing = None
        required = required_artifact.format(sha=source_sha) if required_artifact else None
        for run in valid:
            run_id = int(run["id"])
            if not required:
                passing = (run_id, None)
                break
            artifacts = artifacts_by_run.get(run_id, [])
            if any(a.get("name") == required and not a.get("expired", True)
                   and isinstance(a.get("size_in_bytes"), int)
                   and a["size_in_bytes"] > 0 and
                   a.get("workflow_run", {}).get("head_sha") == source_sha
                   for a in artifacts):
                passing = (run_id, required)
                break
        if passing is None:
            failures.append(f"{key}: artifact missing/expired or not tied to this commit")
            result["checks"][key] = {"ok": False, "reason": "missing-valid-artifact"}
        else:
            run_id, artifact = passing
            result["checks"][key] = {"ok": True, "run_id": run_id,
                                     "artifact": artifact}
    result["complete"] = not failures
    result["limitations"] = [
        "development artifacts only: Android APK is debug-signed",
        "no publisher signatures, provenance policy or reproducible stable build",
        "not proof of real hardware, gateway/provider missions, WAN wake or remote desktop",
        "a successful UEFI graphical smoke test does not prove a complete installed desktop",
    ]
    result["blockers"] = failures
    return result


def github_get(path, token):
    req = Request("https://api.github.com" + path,
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def fetch_evidence(repo, source_sha, token):
    # Query exact immutable HEAD across the repository, not today's default branch.
    encoded = urlencode({"head_sha": source_sha, "per_page": 100, "page": 1})
    data = github_get(f"/repos/{repo}/actions/runs?{encoded}", token)
    runs = data["workflow_runs"]
    # Reject incomplete pagination instead of treating a partial page as proof.
    if data.get("total_count", len(runs)) > len(runs):
        raise QualificationError("workflow run list is incomplete; refusing to qualify")
    artifacts = {}
    for run in runs:
        if (run.get("name") in [n for n, _ in WORKFLOWS.values()]
                and run.get("head_sha") == source_sha
                and run.get("conclusion") == "success"
                and any(n == run.get("name") and artifact
                        for n, artifact in WORKFLOWS.values())):
            run_id = int(run["id"])
            page = github_get(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", token)
            if page.get("total_count", len(page["artifacts"])) > len(page["artifacts"]):
                raise QualificationError("artifact list is incomplete")
            artifacts[run_id] = page["artifacts"]
    return runs, artifacts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not SHA.fullmatch(args.sha) or not REPO.fullmatch(args.repo):
        parser.error("expected immutable SHA and owner/repo")
    token = os.environ.get("GH_TOKEN")
    if not token:
        parser.error("GH_TOKEN required for read-only API access")
    runs, artifacts = fetch_evidence(args.repo, args.sha, token)
    report = qualifies(args.sha, runs, artifacts)
    with open(args.output, "x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, sort_keys=True)
        file.write("\n")
    for key, value in report["checks"].items():
        print(f"{key}: {'PASS' if value['ok'] else 'BLOCKED'}")
    if not report["complete"]:
        raise SystemExit("Development candidate NOT qualified; see bounded report")
    print("Source-matched DEVELOPMENT bundle eligible for additional manual release gates.")
    print("Production-ready: NO. Signature and feature/hardware tests are still required.")


if __name__ == "__main__":
    main()
