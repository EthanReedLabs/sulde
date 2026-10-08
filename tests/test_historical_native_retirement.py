"""Historical shapes with real typed approvals, receipts and temporary Git only."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from unittest import mock

from tests import test_historical_retirement as fixtures
from intent_guardian_parts import historical_retirement as retirement
from intent_guardian_parts import recovery
from intent_guardian_parts.approvals import (
    create_revision_proposal, native_decision_preview, observe_native_permission_request,
)
from intent_guardian_parts.state import IntentGuardianError, load_contract, write_contract
from intent_guardian_parts.cli import pause_contract
import native_decision_journal as journal


def seed_legacy(path, workspace, count=5):
    """Pre-seal historical format cannot be created by the current public writer."""
    rows = []
    for index in range(count):
        binding = {"request_id": f"apr-old-{index}", "kind": "resume", "decision": "resume",
            "target": f"old-pause-{index}", "action": "resume", "approval_kind": "intent-confirmation",
            "intent_id": "old-fixture", "intent_revision": 66 + index, "workspace": str(workspace),
            "provider": "codex", "session_id": f"old-{index}", "card_sha256": "z" * 64}
        row = {"schema": journal.EVENT_SCHEMA, "contract_sha256": journal._contract_digest(path),
               "sequence": index + 1, "at": f"2025-01-01T00:00:0{index}+00:00",
               "previous_event_id": rows[-1]["event_id"] if rows else "", "event": "prepared",
               "transaction_id": journal.transaction_id(binding), "binding": binding,
               "details": {"historical_fixture": True}}
        row["event_id"] = journal._source_event_digest(row)
        rows.append(row)
    journal.journal_path(path).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def historical_contract_transactions(source, root):
    """Run 3 proposal applications and 1 resume, interrupt only the receipt tail."""
    target = load_contract(source)
    gaps = target["runtime"]["pre_execution_gaps"]
    target["runtime"]["pre_execution_gaps"] = []
    write_contract(source, target)
    seed_legacy(source, root)
    for revision, kind in ((164, "proposal"), (177, "proposal"), (191, "proposal"), (192, "resume")):
        value = load_contract(source)
        value["revision"] = revision
        write_contract(source, value)
        session = f"old-native-{revision}"
        if kind == "proposal":
            create_revision_proposal(source, objective=f"old fixture {revision}",
                acceptance_criteria=["fixture only"], mode="enforce", allowed_paths=["file.txt"],
                decision_route="human", provider="codex", session_id=session)
        else:
            pause_contract(source, "historical fixture resume", actor="human")
        preview = native_decision_preview(source, kind=kind,
            decision="approve" if kind == "proposal" else "resume", target="current",
            provider="codex", session_id=session)
        observed = observe_native_permission_request({"client": "codex", "session_id": session,
            "cwd": str(root), "intent_contract": str(source), "permission_mode": "default",
            "tool_name": "Bash", "tool_input": {"command": shlex.join(preview["command_argv"]),
            "description": preview["description"]}}, provider="codex")
        if observed.get("action") != "defer":
            raise AssertionError(observed)
        def crash(stage):
            if stage == "after_contract_applied":
                raise RuntimeError("fixture interrupted receipt tail")
        try:
            with mock.patch.object(recovery, "_native_decision_failpoint", side_effect=crash):
                recovery.execute_native_decision(source, kind=kind, decision=preview["decision"],
                    target=preview["target"], provider="codex", session_id=session)
        except RuntimeError as error:
            if str(error) != "fixture interrupted receipt tail":
                raise
        else:
            raise AssertionError("receipt tail did not reach the interruption seam")
    value = load_contract(source)
    value["revision"] = 195
    value["runtime"]["pre_execution_gaps"] = gaps
    value["runtime"]["task_lanes"] = []
    value.pop("resumed_lane", None)
    write_contract(source, value)


class HistoricalNativeRetirementTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.HistoricalRetirementTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        historical_contract_transactions(self.fx.source, self.fx.root)
        self.fx.plan = retirement.prepare(self.fx.home, self.fx.controller, self.fx.source,
            provider="codex", session_id="control-session")
        self.fx.question()
        self.fx.execute()
        self.before = self.fx.source.read_bytes()
        self.prefix = journal.journal_path(self.fx.source).read_bytes()
        self.fx.plan = retirement.prepare(self.fx.home, self.fx.controller, self.fx.source,
            provider="codex", session_id="control-session", native_transactions=True)
        self.plan = retirement._load(self.fx.home, self.fx.plan["plan_id"])
        self.assertEqual(len(self.plan["native_transactions"]), 4)

    def projection(self):
        return journal.load_projection_read_only(self.fx.source)

    def assert_terminal_once(self):
        self.assertEqual(self.fx.source.read_bytes(), self.before)
        payload = journal.journal_path(self.fx.source).read_bytes()
        self.assertTrue(payload.startswith(self.prefix))
        added = [json.loads(line) for line in payload[len(self.prefix):].splitlines()]
        self.assertEqual(len(added), 4)
        self.assertTrue(all(row["event"] == "superseded" for row in added))
        rows = list(self.projection()["transactions"].values())
        self.assertEqual(sum(row["stage"] == "superseded" for row in rows), 4)
        self.assertEqual(sum(journal.is_legacy_unsealed_prepared_diagnostic(row) for row in rows), 5)
        self.assertFalse(any(row["stage"] == "committed" for row in rows))

    def test_preparation_and_missing_allow_never_settle_old_transactions(self):
        self.assertFalse(self.fx.plan["execution_authorized"])
        with self.assertRaisesRegex(IntentGuardianError, "native Allow"):
            self.fx.execute()
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)
        self.assertEqual(self.fx.source.read_bytes(), self.before)

    def test_exact_allow_supersedes_four_once_and_keeps_five_diagnostics(self):
        preview = self.fx.preview()
        self.assertIn("4 笔", preview["description"])
        self.assertIn("不补造成功", preview["description"])
        self.fx.question()
        with mock.patch.object(journal, "produce_contract_receipt", side_effect=AssertionError("replay")), \
                mock.patch.object(journal, "produce_external_head_receipt", side_effect=AssertionError("replay")):
            first = self.fx.execute()
            second = self.fx.execute()
        self.assertEqual(first, second)
        self.assertFalse(first["effect_asserted"])
        self.assertFalse(first["authority_transferred"])
        self.assert_terminal_once()
        assessment = fixtures.relocation.assess_repository_relocation(self.fx.home, self.fx.root,
            self.fx.base / "moved", provider="codex", session_id="control-session")
        self.assertFalse(assessment["execution_authorized"])
        self.assertFalse((self.fx.base / "moved").exists())

    def test_crash_boundaries_resume_without_second_question(self):
        self.fx.question()
        # Reuse the same frozen batch through each successive crash boundary.
        for boundary in ("native_decision_recorded", "native_superseded", "native_committed"):
            def crash(stage):
                if stage == boundary:
                    raise RuntimeError("fixture crash")
            with mock.patch.object(retirement, "_boundary", side_effect=crash):
                with self.assertRaisesRegex(RuntimeError, "fixture crash"):
                    self.fx.execute()
        self.fx.execute()
        self.assert_terminal_once()

    def test_changed_frozen_cut_fails_without_batch_append(self):
        self.fx.question()
        journal.supersede(self.fx.source, self.plan["native_transactions"][0], reason="different decision")
        before = journal.journal_path(self.fx.source).read_bytes()
        with self.assertRaisesRegex(IntentGuardianError, "CAS changed"):
            self.fx.execute()
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), before)

    def test_other_session_cannot_consume_current_question(self):
        self.fx.question()
        with self.assertRaises(IntentGuardianError):
            self.fx.execute(session_id="another-session")
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)

    def test_changed_source_is_not_silently_repaused(self):
        self.fx.question()
        target = load_contract(self.fx.source)
        target["objective"] = "another task"
        write_contract(self.fx.source, target)
        with self.assertRaisesRegex(IntentGuardianError, "source CAS"):
            self.fx.execute()
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)

    def test_original_allow_corruption_rejects_entire_batch(self):
        self.fx.question()
        # Corrupt only a disposable original authority source, never production.
        from approval_invariant import event_store_path
        path = event_store_path(self.fx.source)
        path.write_text(path.read_text().replace('"outcome": "allow"', '"outcome": "deny"'))
        with self.assertRaises(IntentGuardianError):
            self.fx.execute()
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)

    def test_deny_cannot_be_reused_as_allow(self):
        from approval_invariant import load_projection, decide_typed_approval
        self.fx.question()
        request = next(row for row in load_projection(self.fx.controller)["requests"].values()
                       if row.get("status") == "asked" and row.get("typed") is True)
        decide_typed_approval(self.fx.controller, request_id=request["request_id"],
            receipt_id=request["request_identity"], outcome="deny", snapshot=request["snapshot"],
            current_snapshot=request["snapshot"], provider="codex", session_id="control-session",
            decision_owner="human", actor="permission-request:codex")
        with self.assertRaisesRegex(IntentGuardianError, "native Allow"):
            self.fx.execute()
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)

    def test_real_effect_debt_survives_contract_transaction_retirement(self):
        from intervention import begin_attempt, event_store_path
        target = load_contract(self.fx.source)
        begin_attempt(self.fx.source, intent_id=target["intent_id"], intent_revision=target["revision"],
            fingerprint="c" * 64, source_event_id="unfinished-effect", capability="mcp:example:write",
            target="example:item:1", effect="external_write", provider="codex",
            session_id="other-session", idempotency_key="unfinished-effect")
        store = event_store_path(self.fx.source)
        before = store.read_bytes()
        self.fx.question()
        self.fx.execute()
        self.assertEqual(store.read_bytes(), before)
        with self.assertRaisesRegex(IntentGuardianError, "settled effect debt"):
            fixtures.relocation.assess_repository_relocation(self.fx.home, self.fx.root,
                self.fx.base / "moved", provider="codex", session_id="control-session")
        self.assert_terminal_once()

    def test_anchored_append_interruption_recovers_the_same_batch(self):
        self.fx.question()
        atomic = journal._atomic_write_json
        def crash_after_anchor(path, value):
            atomic(path, value)
            if value.get("schema") == journal.HEAD_PENDING_ANCHOR_SCHEMA:
                raise RuntimeError("fixture pending anchor")
        with mock.patch.object(journal, "_atomic_write_json", side_effect=crash_after_anchor):
            with self.assertRaisesRegex(RuntimeError, "pending anchor"):
                self.fx.execute()
        self.assertTrue(journal.head_pending_path(self.fx.source).is_file())
        self.fx.execute()
        self.assertFalse(journal.head_pending_path(self.fx.source).exists())
        self.assert_terminal_once()

    def test_preparation_rejects_nonhistorical_or_noncontract_candidates(self):
        original = self.projection()
        tx_id = self.plan["native_transactions"][0]
        for changes in ({"stage": "prepared"}, {"operation": "effect"}, {"sealed": False},
                        {"status": "committed"}, {"historical_terminal_seen": True}):
            changed = copy.deepcopy(original)
            changed["transactions"][tx_id].update(changes)
            with self.subTest(changes=changes), \
                    mock.patch.object(journal, "load_projection_read_only", return_value=changed), \
                    self.assertRaisesRegex(IntentGuardianError, "nonhistorical or noncontract"):
                retirement.prepare(self.fx.home, self.fx.controller, self.fx.source,
                    provider="codex", session_id="control-session", native_transactions=True)
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)

    def test_source_and_controller_cannot_be_the_same(self):
        with self.assertRaisesRegex(IntentGuardianError, "executing control contract"):
            retirement.prepare(self.fx.home, self.fx.controller, self.fx.controller,
                provider="codex", session_id="control-session", native_transactions=True)

    def test_frozen_batch_validates_selection_before_writing(self):
        for ids in ([], self.plan["native_transactions"] * 2, ["missing"], [None]):
            with self.subTest(ids=ids), self.assertRaises(journal.NativeDecisionJournalError):
                journal.supersede_frozen_contracts(self.fx.source, snapshot=self.plan["native_snapshot"],
                    transaction_ids=ids, reason="invalid fixture selection")
        self.assertEqual(journal.journal_path(self.fx.source).read_bytes(), self.prefix)

    def test_real_process_cannot_acquire_either_contract_lock_inside_boundaries(self):
        self.fx.question()
        script = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from file_lock import lock_exclusive_nonblocking, unlock
for name in sys.argv[2:]:
    path = Path(name)
    with path.with_name('.' + path.name + '.lock').open('a+') as handle:
        try: lock_exclusive_nonblocking(handle)
        except BlockingIOError: print('blocked')
        else: unlock(handle); print('unlocked')
"""
        results = []
        def probe(stage):
            result = subprocess.run([sys.executable, "-c", script, str(fixtures.ROOT / "scripts/kb"),
                str(self.fx.controller), str(self.fx.source)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["blocked", "blocked"])
            results.append(stage)
        with mock.patch.object(retirement, "_boundary", side_effect=probe):
            self.fx.execute()
        self.assertEqual(results, ["native_decision_recorded", "native_superseded", "native_committed"])
        self.assert_terminal_once()


if __name__ == "__main__":
    unittest.main()
