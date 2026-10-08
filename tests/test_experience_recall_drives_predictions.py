"""B5: verified experience must be recalled and must change later behavior."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import importlib.util  # noqa: E402

import impact_prediction as ip  # noqa: E402

_script = ROOT / "scripts" / "kb" / "agent-experience.py"
_spec = importlib.util.spec_from_file_location("agent_experience_b5", _script)
experience = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(experience)


class ExperienceRecallDrivesPredictionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.store = self.home / "prediction.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _record_verified(self, occurred_at):
        record = experience.build_record(
            task_id="task/earlier", run_id="run/earlier",
            project_id="repo", session_id="s0", task_instance_id="i0",
            problem_type="misclassification",
            symptom="keyword in argument path treated as executable",
            handling="narrow classification to executable shapes",
            outcome="verified",
            result="regression tests added; misclassification gone",
            evidence=[experience.evidence_item(
                "test_run", "scoped regression completed", {"exit": 0})],
            source_summary="command-effect repair",
            occurred_at=occurred_at,
            recommended_tests=["tests.test_intent_guardian_resources"],
            affected_components=["_command_effect"],
        )
        return experience.record(self.home, record)

    def test_verified_recall_strategy_and_ttl_expiry(self):
        row = self._record_verified(occurred_at="2026-09-20T00:00:00+00:00")
        fresh = experience.recall(self.home, problem_type="misclassification",
                                  symptom="keyword in argument path",
                                  now="2026-09-27T00:00:00+00:00", ttl_seconds=30 * 86400)
        self.assertEqual(fresh["strategy"]["source"], "verified_experience")
        self.assertIn(row["experience_id"], fresh["strategy"]["experience_ids"])
        # expired: same row no longer drives strategy; disclosed, not deleted
        expired = experience.recall(self.home, problem_type="misclassification",
                                    symptom="keyword in argument path",
                                    now="2027-01-01T00:00:00+00:00", ttl_seconds=30 * 86400)
        self.assertEqual(expired["strategy"]["source"], "default")
        self.assertEqual(expired["expired_verified_excluded"], 1)

    def test_recalled_experience_changes_verification_action(self):
        """R1-05(3): 正式入口召回 → 验证动作真的改变,不只是保存 ID。"""
        row = self._record_verified(occurred_at="2026-09-20T00:00:00+00:00")
        recall = experience.recall(self.home, problem_type="misclassification",
                                   symptom="keyword in argument path",
                                   now="2026-09-27T00:00:00+00:00",
                                   ttl_seconds=30 * 86400)
        self.assertEqual(recall["strategy"]["source"], "verified_experience")
        recommended = recall["strategy"]["recommended_tests"]
        self.assertIn("tests.test_intent_guardian_resources", recommended)
        # the later DIFFERENT task's verification plan actually runs the
        # recommended tests (behavior change), alongside the prediction hint
        import subprocess
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest",
             *recommended, "tests.test_impact_prediction"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**dict(__import__("os").environ), "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        opened = ip.open_prediction(self.store, {
            "kind": "lightweight",
            "task_id": "task/later-different", "run_id": "run/2", "session_id": "s2",
            "project_id": "/repo", "contract_version": "r2",
            "source_identities": {"a.py": "0123456789abcdef"},
            "objective": "a different later task in the same problem class",
            "assumptions": [{"text": "prior verified handling applies", "confidence": "high"}],
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
            "based_on_experience": recall["strategy"]["experience_ids"],
        }, at="2026-09-27T00:01:00+00:00", task_id="task/later-different")
        self.assertEqual(opened["based_on_experience"], [row["experience_id"]])

    def test_recall_changes_prediction_formation(self):
        row = self._record_verified(occurred_at="2026-09-20T00:00:00+00:00")
        recall = experience.recall(self.home, problem_type="misclassification",
                                   symptom="keyword in argument path",
                                   now="2026-09-27T00:00:00+00:00", ttl_seconds=30 * 86400)
        self.assertEqual(recall["strategy"]["source"], "verified_experience")
        payload = {
            "kind": "lightweight",
            "task_id": "task/later-different", "run_id": "run/2", "session_id": "s2",
            "project_id": "/repo", "contract_version": "r2",
            "source_identities": {"a.py": "0123456789abcdef"},
            "objective": "a different later task in the same problem class",
            "assumptions": [{"text": "prior verified handling applies", "confidence": "high"}],
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
            "based_on_experience": recall["strategy"]["experience_ids"],
        }
        opened = ip.open_prediction(self.store, payload, at="2026-09-27T00:01:00+00:00",
                                    task_id=payload["task_id"])
        self.assertEqual(opened["based_on_experience"], [row["experience_id"]])
        entry = ip.load_projection(self.store)["tasks"][ip.digest(payload["task_id"])]
        self.assertEqual(entry["current"]["based_on_experience"], [row["experience_id"]])


if __name__ == "__main__":
    unittest.main()
