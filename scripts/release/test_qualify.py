import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("qualify.py")
spec = importlib.util.spec_from_file_location("haos_qualification", PATH)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
SHA = "a" * 40


def fixtures():
    runs = []
    artifacts = {}
    for index, (key, (name, template)) in enumerate(q.WORKFLOWS.items(), 1):
        runs.append({"id": index, "name": name, "head_sha": SHA,
                     "status": "completed", "conclusion": "success"})
        if template:
            artifacts[index] = [{
                "name": template.format(sha=SHA), "expired": False,
                "size_in_bytes": 123,
                "workflow_run": {"head_sha": SHA},
            }]
    return runs, artifacts


class QualificationTests(unittest.TestCase):
    def test_all_source_matched_successful_artifacts_make_candidate_only(self):
        runs, artifacts = fixtures()
        report = q.qualifies(SHA, runs, artifacts)
        self.assertTrue(report["complete"])
        self.assertFalse(report["production_release"])
        self.assertFalse(report["signed"])
        self.assertTrue(all(x["ok"] for x in report["checks"].values()))

    def test_any_old_source_is_denied(self):
        runs, artifacts = fixtures()
        runs[-1]["head_sha"] = "b" * 40
        report = q.qualifies(SHA, runs, artifacts)
        self.assertFalse(report["complete"])
        self.assertFalse(report["checks"]["offline_iso_and_qemu"]["ok"])

    def test_missing_failed_in_progress_or_expired_artifacts_denied(self):
        runs, artifacts = fixtures()
        for change in ("failed", "in_progress", "expired", "missing", "different-source"):
            run_copy, art_copy = fixtures()
            if change == "failed":
                run_copy[2]["conclusion"] = "failure"
            elif change == "in_progress":
                run_copy[2]["status"] = "in_progress"
            elif change == "expired":
                art_copy[3][0]["expired"] = True
            elif change == "missing":
                art_copy[3] = []
            else:
                art_copy[3][0]["workflow_run"]["head_sha"] = "c" * 40
            self.assertFalse(q.qualifies(SHA, run_copy, art_copy)["complete"], change)

    def test_debug_apk_cannot_be_presented_as_signed_stable(self):
        runs, artifacts = fixtures()
        result = q.qualifies(SHA, runs, artifacts)
        self.assertEqual(result["release_status"], "development-candidate-only")
        self.assertIn("debug-signed", result["limitations"][0])

    def test_invalid_source_rejected(self):
        for raw in ("dev-latest", "A" * 40, "a" * 39, "a" * 40 + "\n"):
            with self.assertRaises(q.QualificationError):
                q.qualifies(raw, [], {})


if __name__ == "__main__":
    unittest.main()
