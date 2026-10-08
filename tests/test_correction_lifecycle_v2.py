"""B3 correction lifecycle extension: delivered != handled != verified != closed."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import correction_intervention as ci  # noqa: E402


class CorrectionLifecycleV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        proposed = ci.propose_correction(
            self.contract,
            intent_id="intent:test",
            intent_revision=1,
            provider="codex",
            session_id="session-1",
            correction="fix the flaky retry",
            actor="agent",
            source="agent_monitor",
        )
        self.intervention_id = proposed["intervention_id"]
        ci.transition_correction(self.contract, self.intervention_id,
                                 state="queued", boundary="policy_pause",
                                 reason_code="queued_for_delivery", actor="system")
        ci.transition_correction(self.contract, self.intervention_id,
                                 state="applied", boundary="managed_run_monitor",
                                 reason_code="managed_process_tree_interrupted",
                                 actor="system")

    def tearDown(self):
        self.tmp.cleanup()

    def _state(self):
        return ci.load_projection(self.contract)["interventions"][self.intervention_id]["state"]

    def test_applied_keeps_delivered_meaning(self):
        self.assertEqual(self._state(), "applied")
        projection = ci.load_projection(self.contract)
        row = projection["interventions"][self.intervention_id]
        # applied never claims the problem is solved
        self.assertNotEqual(row.get("state"), "verified")

    def test_executor_cannot_verify_or_close(self):
        with self.assertRaises(ci.CorrectionInterventionError):
            ci.transition_correction(self.contract, self.intervention_id,
                                     state="verified", boundary="manual",
                                     reason_code="executor_claims_fixed",
                                     actor="agent_monitor",
                                     evidence_sha256="a" * 32)
        self.assertEqual(self._state(), "applied")

    def test_supervisor_verifies_with_evidence_then_closes(self):
        ci.transition_correction(self.contract, self.intervention_id,
                                 state="acknowledged", boundary="turn_stop",
                                 reason_code="executor_reported_handling",
                                 actor="agent")
        self.assertEqual(self._state(), "acknowledged")
        with self.assertRaises(ci.CorrectionInterventionError):
            ci.transition_correction(self.contract, self.intervention_id,
                                     state="verified", boundary="manual",
                                     reason_code="read_back_without_evidence",
                                     actor="system")
        summary = "independent read-back: rerun confirms the fix"
        ci.transition_correction(self.contract, self.intervention_id,
                                 state="verified", boundary="manual",
                                 reason_code="independent_readback_confirmed",
                                 actor="system",
                                 verification_summary=summary,
                                 evidence_sha256=ci._verification_evidence_digest(
                                     self.intervention_id, summary))
        self.assertEqual(self._state(), "verified")
        ci.transition_correction(self.contract, self.intervention_id,
                                 state="closed", boundary="manual",
                                 reason_code="supervisor_settled", actor="system")
        self.assertEqual(self._state(), "closed")
        with self.assertRaises(ci.CorrectionInterventionError):
            ci.transition_correction(self.contract, self.intervention_id,
                                     state="acknowledged", boundary="manual",
                                     reason_code="reopen_attempt", actor="system")

    def test_v1_ledger_still_replays(self):
        rows = self.contract.with_name("intent.corrections.jsonl").read_text(encoding="utf-8")
        downgrade = rows.replace(ci.EVENT_SCHEMA, ci.EVENT_SCHEMA_V1)
        self.contract.with_name("intent.corrections.jsonl").write_text(downgrade, encoding="utf-8")
        projection = ci.load_projection(self.contract)
        row = projection["interventions"][self.intervention_id]
        self.assertEqual(row["state"], "applied")

    def test_event_schema_is_v2_with_evidence_field(self):
        rows = [json.loads(line) for line in
                self.contract.with_name("intent.corrections.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(r["schema"] == ci.EVENT_SCHEMA for r in rows))
        self.assertTrue(any("evidence_sha256" in r for r in rows))


if __name__ == "__main__":
    unittest.main()


class ReplayInvariantTests(unittest.TestCase):
    """R1-02: the replay must enforce the same settlement invariants as the entry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        proposed = ci.propose_correction(
            self.contract, intent_id="i", intent_revision=1, provider="codex",
            session_id="s1", correction="fix drift", actor="agent", source="agent_monitor")
        self.intervention_id = proposed["intervention_id"]
        ci.transition_correction(self.contract, self.intervention_id, state="queued",
                                 boundary="policy_pause", reason_code="queued", actor="system")
        ci.transition_correction(self.contract, self.intervention_id, state="applied",
                                 boundary="managed_run_monitor",
                                 reason_code="managed_process_tree_interrupted", actor="system")

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        return self.contract.with_name("intent.corrections.jsonl")

    def _append(self, row):
        with self._store().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _last_sequence(self):
        rows = self._store().read_text(encoding="utf-8").splitlines()
        return json.loads(rows[-1])["sequence"]

    def test_forged_agent_verified_without_evidence_is_rejected_on_replay(self):
        """R1-02 反例(修复前):伪造行回放被接受。"""
        self._append({
            "schema": ci.EVENT_SCHEMA,
            "type": "correction.intervention_transitioned",
            "sequence": self._last_sequence() + 1,
            "at": "2026-09-27T13:00:00+00:00",
            "intervention_id": self.intervention_id,
            "state": "verified",
            "boundary": "manual",
            "reason_code": "forged_settlement",
            "actor": "agent",
            "evidence_sha256": "",
        })
        with self.assertRaises(ci.CorrectionInterventionError):
            ci.load_projection(self.contract)

    def test_fresh_thread_accepts_bound_supervisor_verification(self):
        ci.transition_correction(self.contract, self.intervention_id, state="acknowledged",
                                 boundary="turn_stop", reason_code="executor_reported",
                                 actor="agent")
        summary = "independent read-back: rerun shows the drift gone"
        bound = ci._verification_evidence_digest(self.intervention_id, summary)
        ci.transition_correction(self.contract, self.intervention_id, state="verified",
                                 boundary="manual", reason_code="readback", actor="system",
                                 verification_summary=summary,
                                 evidence_sha256=bound)
        self.assertEqual(
            ci.load_projection(self.contract)["interventions"][self.intervention_id]["state"],
            "verified")

    def test_evidence_must_bind_intervention_and_result(self):
        summary = "independent read-back: rerun shows the drift gone"
        bound = ci._verification_evidence_digest(self.intervention_id, summary)
        self._append({
            "schema": ci.EVENT_SCHEMA,
            "type": "correction.intervention_transitioned",
            "sequence": self._last_sequence() + 1,
            "at": "2026-09-27T13:00:00+00:00",
            "intervention_id": self.intervention_id,
            "state": "verified",
            "boundary": "manual",
            "reason_code": "readback",
            "actor": "system",
            "verification_summary": summary,
            "evidence_sha256": "b" * 32,  # 错配:不属于本问题/结果
        })
        with self.assertRaises(ci.CorrectionInterventionError):
            ci.load_projection(self.contract)
