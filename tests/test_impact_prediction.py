"""Versioned impact-prediction artifact semantics (B1)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import impact_prediction as ip  # noqa: E402

NOW = "2026-09-27T08:00:00+00:00"
LATER = "2026-09-27T09:00:00+00:00"

FULL_PAYLOAD = {
    "task_id": "task/predictive-execution",
    "run_id": "run-aaaaaaaaaaaaaaaaaaaaaaaa",
    "session_id": "session-1",
    "project_id": "/repo",
    "contract_version": "rev-7",
    "source_identities": {"scripts/kb/example.py": "aaaabbbbccccdddd1"},
    "objective": "narrow the deploy branch of _command_effect",
    "assumptions": [
        {"text": "execution_domains is populated by the structured parser", "confidence": "high"},
        {"text": "opaque compounds never reach the deploy branch", "confidence": "medium"},
    ],
    "unknowns": ["wrappers seen in the wild"],
    "expected_touch": {"entries": ["_command_effect"], "callers": ["normalize_hook_event"]},
    "invariants": ["real deploy stays external_write"],
    "new_risks": [{"description": "wrapper allowlist too broad", "trigger": "env FOO=bar deploy"}],
    "alternatives": [{"option": "keyword blocklist", "rationale": "rejected: brittle"}],
    "falsification_probe": "classify 'env FOO=1 deploy --env x' expect external_write",
    "recovery_path": "revert commit; regenerate tests",
    "impact_bounds": {
        "lower": "classification of deploy-argument commands only",
        "upper": "any command whose parsed executable is deploy",
        "unknown": "third-party wrappers composing deploy",
    },
}


class ImpactPredictionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "predictions.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self, **overrides):
        payload = {**FULL_PAYLOAD, **overrides}
        return ip.open_prediction(self.store, payload, at=NOW, task_id=payload["task_id"])

    def test_open_stores_digests_not_raw_identities(self):
        row = self._open()
        self.assertEqual(row["version"], 1)
        self.assertTrue(row["prediction_id"].startswith("pred-"))
        self.assertNotIn("task/predictive-execution", json.dumps(row))
        self.assertEqual(row["task_id_sha256"], ip.digest("task/predictive-execution"))

    def test_projection_replays_current_version(self):
        self._open()
        projection = ip.load_projection(self.store)
        entry = projection["tasks"][ip.digest(FULL_PAYLOAD["task_id"])]
        self.assertEqual(entry["current"]["version"], 1)
        self.assertEqual(entry["current"]["status"], "open")
        self.assertEqual(len(entry["versions"]), 1)

    def test_second_open_while_open_is_rejected(self):
        self._open()
        with self.assertRaises(ip.PredictionError):
            self._open()

    def test_revise_appends_and_preserves_prior_version(self):
        self._open()
        rows_before = self.store.read_text(encoding="utf-8")
        revised = ip.revise_prediction(
            self.store,
            {
                "new_evidence": ["parser emits execution_domains for compound commands"],
                "revision_reason": "assumption about opaque compounds proven by probe",
                "assumptions": [{"text": "compounds classified conservatively", "confidence": "high"}],
            },
            at=LATER,
            task_id=FULL_PAYLOAD["task_id"],
        )
        self.assertEqual(revised["version"], 2)
        self.assertEqual(revised["supersedes_version"], 1)
        self.assertIn("parser emits", json.dumps(revised["new_evidence"]))
        # append-only: the version-1 row is byte-identical before/after
        self.assertTrue(self.store.read_text(encoding="utf-8").startswith(rows_before))
        projection = ip.load_projection(self.store)
        entry = projection["tasks"][ip.digest(FULL_PAYLOAD["task_id"])]
        self.assertEqual(entry["current"]["version"], 2)
        self.assertEqual([v["version"] for v in entry["versions"]], [1, 2])
        self.assertEqual(entry["versions"][0]["assumptions"], FULL_PAYLOAD["assumptions"])

    def test_revise_requires_evidence_and_reason(self):
        self._open()
        with self.assertRaises(ip.PredictionError):
            ip.revise_prediction(self.store, {"revision_reason": "because"}, at=LATER,
                                 task_id=FULL_PAYLOAD["task_id"])
        with self.assertRaises(ip.PredictionError):
            ip.revise_prediction(self.store, {"new_evidence": ["x"]}, at=LATER,
                                 task_id=FULL_PAYLOAD["task_id"])

    def test_full_prediction_requires_probe_and_recovery(self):
        with self.assertRaises(ip.PredictionError):
            self._open(falsification_probe="", recovery_path="")
        lightweight = self._open(kind="lightweight", falsification_probe="", recovery_path="")
        self.assertEqual(lightweight["kind"], "lightweight")

    def test_impact_bounds_are_required_and_split(self):
        for bound in ("lower", "upper", "unknown"):
            payload = {**FULL_PAYLOAD, "impact_bounds": {b: "x" for b in ("lower", "upper", "unknown") if b != bound}}
            with self.assertRaises(ip.PredictionError):
                ip.open_prediction(self.store, payload, at=NOW, task_id=FULL_PAYLOAD["task_id"])

    def test_stale_marks_current_and_allows_revision(self):
        self._open()
        ip.mark_stale(self.store, task_id=FULL_PAYLOAD["task_id"],
                      input_changed={"scripts/kb/example.py": "bbbbccccdddd00002"}, at=LATER)
        entry = ip.load_projection(self.store)["tasks"][ip.digest(FULL_PAYLOAD["task_id"])]
        self.assertEqual(entry["current"]["status"], "stale")
        self.assertEqual(len(entry["stales"]), 1)
        ip.revise_prediction(self.store, {"new_evidence": ["re-read parser"], "revision_reason": "input moved"},
                             at=LATER, task_id=FULL_PAYLOAD["task_id"])
        entry = ip.load_projection(self.store)["tasks"][ip.digest(FULL_PAYLOAD["task_id"])]
        self.assertEqual(entry["current"]["status"], "open")

    def test_check_records_verdict_with_evidence(self):
        self._open()
        row = ip.record_check(self.store, {"verdict": "larger_than_predicted",
                                           "facts": ["new caller discovered in scheduler"],
                                           "evidence": ["audit:seq-12"]},
                              at=LATER, task_id=FULL_PAYLOAD["task_id"])
        self.assertEqual(row["verdict"], "larger_than_predicted")
        with self.assertRaises(ip.PredictionError):
            ip.record_check(self.store, {"verdict": "optimal", "facts": ["x"], "evidence": ["y"]},
                            at=LATER, task_id=FULL_PAYLOAD["task_id"])

    def test_revise_after_close_is_rejected(self):
        """R1-01 反例(修复前):closed 后 revise 仍被接受并变回 open。"""
        self._open()
        ip.close_prediction(self.store, task_id=FULL_PAYLOAD["task_id"], outcome="resolved", at=LATER)
        with self.assertRaises(ip.PredictionError):
            ip.revise_prediction(self.store, {"new_evidence": ["late"], "revision_reason": "zombie"},
                                 at=LATER, task_id=FULL_PAYLOAD["task_id"])
        entry = ip.load_projection(self.store)["tasks"][ip.digest(FULL_PAYLOAD["task_id"])]
        self.assertEqual(entry["current"]["status"], "closed")
        self.assertEqual([v["version"] for v in entry["versions"]], [1])

    def test_duplicate_close_is_rejected(self):
        self._open()
        ip.close_prediction(self.store, task_id=FULL_PAYLOAD["task_id"], outcome="resolved", at=LATER)
        with self.assertRaises(ip.PredictionError):
            ip.close_prediction(self.store, task_id=FULL_PAYLOAD["task_id"], outcome="abandoned", at=LATER)

    def test_revise_after_stale_is_allowed(self):
        self._open()
        ip.mark_stale(self.store, task_id=FULL_PAYLOAD["task_id"],
                      input_changed={"a.py": "ffff000000000001"}, at=LATER)
        revised = ip.revise_prediction(self.store, {"new_evidence": ["re-read"], "revision_reason": "inputs moved"},
                                       at=LATER, task_id=FULL_PAYLOAD["task_id"])
        self.assertEqual(revised["version"], 2)

    def test_close_then_new_thread_allowed(self):
        self._open()
        ip.close_prediction(self.store, task_id=FULL_PAYLOAD["task_id"], outcome="resolved", at=LATER)
        entry = ip.load_projection(self.store)["tasks"][ip.digest(FULL_PAYLOAD["task_id"])]
        self.assertEqual(entry["current"]["status"], "closed")
        self.assertEqual(entry["closed_outcome"], "resolved")
        row = self._open()
        self.assertEqual(row["version"], 1)
        self.assertNotEqual(row["prediction_id"], entry["versions"][0]["prediction_id"])

    def test_sequence_contiguity_enforced(self):
        self._open()
        with self.store.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema": "x", "type": "prediction.checked", "sequence": 5}) + "\n")
        with self.assertRaises(ip.PredictionError) as caught:
            ip.load_projection(self.store)
        self.assertIn("contiguous", str(caught.exception))

    def test_reopen_after_close_gets_independent_thread(self):
        self._open()
        ip.close_prediction(self.store, task_id=FULL_PAYLOAD["task_id"], outcome="abandoned", at=LATER)
        fresh = self._open()
        self.assertTrue(fresh["prediction_id"].startswith("pred-"))


if __name__ == "__main__":
    unittest.main()
