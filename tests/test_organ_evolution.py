from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kb/organ-evolution.py"
SPEC = importlib.util.spec_from_file_location("organ_evolution", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
EVO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVO)


def l2(pending: int) -> dict:
    return {"channels": {"sediment_draft": {"pending": pending}}}


class OrganEvolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        (self.home / "self-repair").mkdir()
        (self.home / "self-repair/pending.json").write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_drafts_one_highest_priority_experiment_with_baseline(self) -> None:
        registry = EVO.reconcile(self.home, l2(47), {"counts": {}}, True)
        self.assertEqual(registry["active"], 1)
        item = registry["items"][0]
        self.assertEqual(item["organ"], "auto-sediment")
        self.assertEqual(item["baseline_value"], 47)
        brief = Path(item["brief_path"])
        self.assertTrue(brief.is_file())
        pending = json.loads((self.home / "self-repair/pending.json").read_text(encoding="utf-8"))
        self.assertEqual(pending[0]["experiment_id"], item["id"])

    def test_golden_backlog_targets_consumer_not_producer(self) -> None:
        registry = EVO.reconcile(
            self.home,
            {"channels": {"golden_case": {"pending": 37}}},
            {"counts": {}},
            False,
        )
        item = registry["items"][0]
        self.assertEqual(item["organ"], "golden-review")
        self.assertEqual(item["source"], "scripts/kb/golden-review.py")

    def test_governance_backlog_targets_consumer_not_producer(self) -> None:
        registry = EVO.reconcile(
            self.home,
            {"channels": {"threshold_proposal": {"pending": 8}}},
            {"counts": {}},
            False,
        )
        item = registry["items"][0]
        self.assertEqual(item["organ"], "governance-review")
        self.assertEqual(item["source"], "scripts/kb/governance-review.py")

    def test_pending_wp_brief_awaiting_human_is_not_an_organ_opportunity(self) -> None:
        registry = EVO.reconcile(
            self.home,
            {"channels": {"wp_brief": {"pending": 1}}},
            {"counts": {}},
            False,
        )
        self.assertEqual(registry["active"], 0)
        self.assertEqual(registry["items"], [])

    def test_failed_l3_execution_still_targets_self_repair(self) -> None:
        rows = EVO.opportunities(
            {"channels": {"wp_brief": {"pending": 1}}},
            {"counts": {"failed": 1}},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["organ"], "self-repair")
        self.assertEqual(rows[0]["signal"], "l3_failed")

    def test_dry_run_does_not_write(self) -> None:
        registry = EVO.reconcile(self.home, l2(3), {"counts": {}}, False)
        self.assertEqual(registry["active"], 1)
        self.assertFalse((self.home / "evolution").exists())
        self.assertEqual(json.loads((self.home / "self-repair/pending.json").read_text()), [])

    def test_claimed_verified_queue_needs_evidence_and_no_authority_debt(self) -> None:
        self.assertEqual(
            EVO.queue_closure_status(
                {"status": "verified", "closure_status": "verified"}
            ),
            "inconclusive",
        )
        self.assertEqual(
            EVO.queue_closure_status(
                {
                    "status": "verified",
                    "closure_status": "verified",
                    "verification_sha256": "a" * 64,
                    "attempt_ids": ["still-open"],
                }
            ),
            "unresolved",
        )

    def test_two_independent_observations_recommend_retaining_improvement(self) -> None:
        first = EVO.reconcile(self.home, l2(10), {"counts": {}}, True)
        item = first["items"][0]
        pending_path = self.home / "self-repair/pending.json"
        pending = json.loads(pending_path.read_text())
        pending[0].update({"status": "resolved", "resolution_evidence": "verified run"})
        pending_path.write_text(json.dumps(pending), encoding="utf-8")
        second = EVO.reconcile(self.home, l2(8), {"counts": {"resolved": 1}}, True)
        self.assertEqual(second["items"][0]["status"], "observing")
        third = EVO.reconcile(self.home, l2(7), {"counts": {"resolved": 1}}, True)
        self.assertEqual(third["items"][0]["status"], "retain_recommended")

    def test_failed_l3_task_blocks_experiment(self) -> None:
        first = EVO.reconcile(self.home, l2(10), {"counts": {}}, True)
        pending_path = self.home / "self-repair/pending.json"
        pending = json.loads(pending_path.read_text())
        pending[0].update({"status": "failed", "failure_reason": "tests failed"})
        pending_path.write_text(json.dumps(pending), encoding="utf-8")
        second = EVO.reconcile(self.home, l2(10), {"counts": {"failed": 1}}, True)
        self.assertEqual(second["items"][0]["status"], "blocked")

    def test_human_decision_closes_recommended_experiment_with_evidence(self) -> None:
        registry = EVO.reconcile(self.home, l2(10), {"counts": {}}, True)
        identifier = registry["items"][0]["id"]
        registry["items"][0]["status"] = "retain_recommended"
        EVO.atomic_json(self.home / "evolution/registry.json", registry)
        decided = EVO.decide(self.home, identifier, "retain", "reviewed run 42")
        self.assertEqual(decided["items"][0]["status"], "retained")
        self.assertEqual(decided["active"], 0)
        self.assertIn("reviewed run 42", (self.home / "evolution/decisions.jsonl").read_text())

    def test_human_cannot_retain_without_recommendation(self) -> None:
        registry = EVO.reconcile(self.home, l2(10), {"counts": {}}, True)
        with self.assertRaises(ValueError):
            EVO.decide(self.home, registry["items"][0]["id"], "retain", "too early")


if __name__ == "__main__":
    unittest.main()
