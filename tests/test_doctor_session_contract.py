"""Contract routing regressions; fixtures are isolated, not live Hook evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))

# Import this consumer first: routing must not introduce a state import cycle.
import operational_readiness as operational
from approval_invariant import ask_approval, request_binding_receipt
import native_decision_journal as journal
from intent_guardian_parts import readiness, session_workspace
from intent_guardian_parts.state import (
    default_contract,
    session_contract_path,
    write_contract,
)
from intervention import begin_attempt


class DoctorSessionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "kb"
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root / "user"),
            "SULDE_HOME": str(self.root / "sulde"),
            "SULDE_KB_HOME": str(self.home),
            "CODEX_HOME": str(self.root / "codex"),
            "XDG_CONFIG_HOME": str(self.root / "xdg"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        patch = mock.patch.dict(os.environ, self.environment, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.shared = operational._contract_path(self.home, self.workspace)
        self.make_contract(self.shared, "shared", status="paused")
        self.current = session_contract_path(self.home, "codex", "session-one")
        self.make_contract(self.current, "current", session="session-one")
        session_workspace.bind_session_workspace(
            self.home, provider="codex", session_id="session-one",
            contract_path=self.current,
        )

    def make_contract(self, path, name, *, session="", status="active"):
        contract = default_contract(
            intent_id=name, objective=f"Inspect {name}",
            acceptance_criteria=["Only this contract is projected"],
            workspace=self.workspace, mode="enforce", confirmed_by="test-fixture",
        )
        contract["status"] = status
        if session:
            contract["runtime"]["task_lanes"] = [{
                "provider": "codex", "session_id": session,
                "task_epoch": contract["task_epoch"], "state": "bound",
                "source": "fixture",
            }]
        write_contract(path, contract)
        return contract

    def project(self, **kwargs):
        arguments = {
            "provider": "codex", "session_id": "session-one",
            "workspace": self.workspace,
            "scheduler_probe": {"status": "unobserved", "reasons": ["fixture"]},
        }
        arguments.update(kwargs)
        return operational.project(self.home, **arguments)

    def mapping_path(self):
        return session_workspace.session_workspace_path(
            self.home, "codex", "session-one",
        )

    def add_debt(self, path, session):
        return begin_attempt(
            path, intent_id=json.loads(path.read_text())["intent_id"],
            intent_revision=1, fingerprint="a" * 64,
            source_event_id="fixture-event", capability="mcp:test/write",
            target="fixture-resource", effect="external_write",
            provider="codex", session_id=session, idempotency_key="fixture-debt",
        )

    def snapshot(self):
        return {
            str(path.relative_to(self.home)): (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns, path.stat().st_mode,
            )
            for path in self.home.rglob("*") if path.is_file()
        }

    def test_project_uses_current_session_not_paused_shared_contract(self):
        result = self.project()
        self.assertEqual(result["contract_path"], str(self.current))
        self.assertEqual(result["intent_id"], "current")
        self.assertEqual(result["task_lane_state"], "bound")
        self.assertFalse(result["approval_required"])

    def test_doctor_inner_and_outer_contract_match(self):
        result = readiness.guardian_doctor(
            self.home, self.workspace, provider="codex", session_id="session-one",
        )
        self.assertEqual(result["contract_path"], str(self.current))
        self.assertEqual(result["operational_readiness"]["contract_path"], str(self.current))
        self.assertEqual(result["intent_id"], result["operational_readiness"]["intent_id"])

    def test_two_sessions_do_not_share_effect_or_approval_truth(self):
        other = session_contract_path(self.home, "codex", "session-two")
        self.make_contract(other, "other", session="session-two", status="paused")
        session_workspace.bind_session_workspace(
            self.home, provider="codex", session_id="session-two", contract_path=other,
        )
        self.add_debt(other, "session-two")
        ask_approval(
            other, intent_id="other", intent_revision=1, kind="proposal",
            target="b" * 64, provider="codex", session_id="session-two",
            source="codex_permission_request", card={"question": "fixture"},
            workspace=self.workspace, route="human",
            reassess_after_seconds=300, ttl_seconds=86400,
        )
        before = self.snapshot()
        current = self.project()
        sibling = self.project(session_id="session-two")
        self.assertEqual(current["contract_path"], str(self.current))
        self.assertEqual(current["effect_truth"]["status"], "clear")
        self.assertTrue(current["decision_truth"]["settled"])
        self.assertEqual(sibling["contract_path"], str(other))
        self.assertEqual(sibling["effect_truth"]["status"], "blocked")
        self.assertFalse(sibling["decision_truth"]["settled"])
        self.assertEqual(self.snapshot(), before)

    def test_current_debt_is_not_hidden_by_clean_shared_contract(self):
        self.make_contract(self.shared, "shared")
        self.add_debt(self.current, "session-one")
        self.assertEqual(self.project()["effect_truth"]["status"], "blocked")

    def test_pre_execution_gap_uses_selected_contract(self):
        contract = json.loads(self.current.read_text())
        contract["runtime"]["pre_execution_gaps"] = [{
            "provider": "codex", "session_id": "session-one",
            "event_id": "post-only-fixture", "effect": "local_write",
        }]
        write_contract(self.current, contract)
        result = self.project()
        self.assertEqual(result["pre_execution_safety_readiness"]["blocking_gaps"], 1)
        self.assertFalse(result["gates"]["pre_execution_safety_clear"])

    def test_no_mapping_uses_existing_session_contract(self):
        self.mapping_path().unlink()
        self.assertEqual(self.project()["contract_path"], str(self.current))

    def test_implicit_workspace_uses_session_mapping_not_launch_hint(self):
        with mock.patch.dict(os.environ, {"SULDE_WORKSPACE_ROOT": str(self.root)}):
            result = self.project(workspace=None)
        self.assertEqual(result["contract_path"], str(self.current))
        self.assertEqual(result["contract_status"], "active")
        self.assertNotIn("session_contract_workspace_mismatch", result["reasons"])
        self.assertEqual(result["effect_truth"]["status"], "clear")

    def test_completion_anchor_is_not_replaced_by_shared_workspace(self):
        completion = self.home / "intent/sessions/completion-fixture.active.json"
        self.make_contract(completion, "completion:fixture", session="session-one")
        session_workspace.bind_session_workspace(
            self.home, provider="codex", session_id="session-one", contract_path=completion,
        )
        report = readiness.guardian_doctor(
            self.home, self.workspace, provider="codex", session_id="session-one",
        )
        self.assertEqual(report["contract_path"], str(completion))
        self.assertEqual(report["operational_readiness"]["contract_path"], str(completion))

    def test_no_session_contract_preserves_workspace_fallback(self):
        result = self.project(session_id="legacy-session")
        self.assertEqual(result["contract_path"], str(self.shared))

    def test_background_does_not_inherit_interactive_mapping(self):
        result = self.project(session_id=None)
        self.assertEqual(result["readiness_scope"], "scheduler")
        self.assertEqual(result["contract_path"], str(self.shared))

    def test_invalid_mapping_never_falls_back(self):
        original = self.mapping_path().read_bytes()
        for payload in (b"{", b"[]", b'"wrong-type"'):
            with self.subTest(payload=payload):
                self.mapping_path().write_bytes(payload)
                result = self.project()
                self.assertEqual(result["status"], "degraded")
                self.assertIsNone(result["contract_path"])
                self.assertIn("session_contract_invalid", result["reasons"])
        self.mapping_path().write_bytes(original)

    def test_digest_mismatch_never_falls_back(self):
        mapping = json.loads(self.mapping_path().read_text())
        mapping["contract_path"] = str(self.shared)
        self.mapping_path().write_text(json.dumps(mapping))
        result = self.project()
        self.assertIsNone(result["contract_path"])
        self.assertIn("session_contract_invalid", result["reasons"])

    def test_missing_mapping_target_never_falls_back(self):
        self.current.unlink()
        result = self.project()
        self.assertIsNone(result["contract_path"])
        self.assertIn("session_contract_invalid", result["reasons"])

    def test_mapping_and_contract_root_mismatch_never_falls_back(self):
        other = self.root / "other-project"
        other.mkdir()
        contract = json.loads(self.current.read_text())
        contract["workspace_root"] = str(other)
        write_contract(self.current, contract)
        result = self.project()
        self.assertIsNone(result["contract_path"])
        self.assertIn("session_contract_invalid", result["reasons"])

    def test_invalid_mapped_contract_never_falls_back(self):
        self.current.write_text("[]")
        result = self.project()
        self.assertIsNone(result["contract_path"])
        self.assertIn("session_contract_invalid", result["reasons"])

    def test_other_provider_does_not_borrow_codex_session(self):
        result = self.project(provider="claude")
        self.assertEqual(result["contract_path"], str(self.shared))

    def test_explicit_workspace_mismatch_does_not_mix_evidence(self):
        other_workspace = self.root / "other-project"
        other_workspace.mkdir()
        result = self.project(workspace=other_workspace)
        self.assertEqual(result["contract_path"], str(self.current))
        self.assertEqual(result["status"], "degraded")
        self.assertIn("session_contract_workspace_mismatch", result["reasons"])
        self.assertEqual(result["effect_truth"]["status"], "unavailable")

    def test_doctor_pins_contract_across_mapping_change(self):
        actual = readiness.operational_readiness_projection

        def change_mapping_then_project(*args, **kwargs):
            session_workspace.bind_session_workspace(
                self.home, provider="codex", session_id="session-one",
                contract_path=self.shared,
            )
            return actual(*args, **kwargs)

        with mock.patch.object(readiness, "operational_readiness_projection",
                               side_effect=change_mapping_then_project):
            result = readiness.guardian_doctor(
                self.home, self.workspace, provider="codex", session_id="session-one",
            )
        self.assertEqual(result["contract_path"], str(self.current))
        self.assertEqual(result["operational_readiness"]["contract_path"], str(self.current))

    def test_real_cli_doctor_reads_session_contract_without_writes(self):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
             "doctor", "--home", str(self.home), "--workspace", str(self.workspace),
             "--provider", "codex", "--session-id", "session-one"],
            env=dict(os.environ), cwd=self.workspace, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["contract_path"], str(self.current))
        self.assertEqual(report["operational_readiness"]["contract_path"], str(self.current))
        self.assertEqual(self.snapshot(), before)

    def prepare_journal(self):
        card = {"operation_id": "proposal", "decision_id": "approve",
                "action": "approve-proposal", "question": "isolated fixture"}
        request = ask_approval(
            self.current, intent_id="current", intent_revision=1, kind="proposal",
            target="b" * 64, provider="codex", session_id="session-one",
            source="codex_permission_request", card=card,
            workspace=self.workspace, route="human",
        )
        binding = journal.seal_binding(
            self.current, operation="proposal", decision="approve", target="b" * 64,
            action="approve-proposal", intent_id="current", intent_revision=1,
            task_epoch=json.loads(self.current.read_text())["task_epoch"],
            effect_attempt_id="", effect_subject_intent_revision=0,
            workspace=self.workspace, provider="codex", session_id="session-one",
            source="codex_permission_request", card=card,
            request_id=request["request_id"],
            receipt=request_binding_receipt(self.current, request["request_id"]),
        )
        journal.prepare(self.current, binding)

    def test_real_cli_invalid_mapping_fails_without_writes(self):
        self.mapping_path().write_text("[]")
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
             "doctor", "--home", str(self.home), "--workspace", str(self.workspace),
             "--provider", "codex", "--session-id", "session-one"],
            env=dict(os.environ), cwd=self.workspace, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=20, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("session workspace mapping fields are invalid", result.stderr)
        self.assertNotIn(str(self.shared), result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_read_only_head_matches_existing_proof_without_lock_or_recovery(self):
        self.prepare_journal()
        expected = journal.head_proof(self.current)
        before = self.snapshot()
        with mock.patch.object(journal, "_store_lock", side_effect=AssertionError("lock")), \
             mock.patch.object(journal, "_recover_anchored_rows",
                               side_effect=AssertionError("recovery")):
            observed = journal.head_proof_read_only(self.current)
            validated = operational._validated_native_head_proof(self.current)
            journal.load_projection_read_only(self.current)
        self.assertEqual(observed, expected)
        self.assertEqual(validated, expected)
        self.assertTrue(observed["local_consistency_verified"])
        self.assertFalse(observed["external_authority_verified"])
        self.assertEqual(self.snapshot(), before)

    def test_missing_journal_does_not_create_lock_or_claim_verified(self):
        before = self.snapshot()
        proof = journal.head_proof_read_only(self.current)
        self.assertFalse(proof["local_consistency_verified"])
        self.assertFalse(proof["external_authority_verified"])
        self.assertEqual(self.snapshot(), before)

    def test_read_only_head_never_recovers_pending_state(self):
        self.prepare_journal()
        journal.head_pending_path(self.current).write_text("{}")
        before = self.snapshot()
        with self.assertRaisesRegex(journal.NativeDecisionJournalError, "requiring recovery"):
            journal.head_proof_read_only(self.current)
        self.assertEqual(self.snapshot(), before)

    def test_read_only_head_rejects_anchor_tamper(self):
        self.prepare_journal()
        journal.head_anchor_path(self.current).write_text("{}")
        before = self.snapshot()
        with self.assertRaises(journal.NativeDecisionJournalError):
            journal.head_proof_read_only(self.current)
        self.assertEqual(self.snapshot(), before)

    def test_read_only_head_rejects_torn_tail(self):
        self.prepare_journal()
        store = journal.journal_path(self.current)
        store.write_bytes(store.read_bytes() + b'{"incomplete":')
        before = self.snapshot()
        with self.assertRaises(journal.NativeDecisionJournalError):
            journal.head_proof_read_only(self.current)
        self.assertEqual(self.snapshot(), before)

    def test_read_only_head_rejects_concurrent_append(self):
        self.prepare_journal()
        replay = journal.replay
        store = journal.journal_path(self.current)

        def append_after_replay(*args, **kwargs):
            result = replay(*args, **kwargs)
            # Fault injection, not an external writer or authority receipt.
            store.write_bytes(store.read_bytes() + b"\n")
            return result

        with mock.patch.object(journal, "replay", side_effect=append_after_replay), \
             self.assertRaisesRegex(journal.NativeDecisionJournalError, "changed during read"):
            journal.head_proof_read_only(self.current)


if __name__ == "__main__":
    unittest.main()
