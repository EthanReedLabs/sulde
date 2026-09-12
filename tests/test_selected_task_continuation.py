"""Disposable state-machine/adapter tests; actual host evidence is separate."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests import test_intent_guardian as fixtures
from intent_guardian_parts import selected_task, approvals, recovery, state
from intent_guardian_parts.session_workspace import bind_session_workspace, resolve_session_contract, load_session_workspace
from task_ownership import upsert_task_lane
import native_decision_journal as journal


LOCK_PROBE = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from file_lock import lock_exclusive_nonblocking, unlock
result = []
for name in sys.argv[2:]:
    with Path(name).open('a+') as stream:
        try:
            lock_exclusive_nonblocking(stream)
        except BlockingIOError:
            result.append('blocked')
        else:
            unlock(stream)
            result.append('unlocked')
print(json.dumps(result))
"""


class SelectedTaskTests(unittest.TestCase):
    native_permission_payload = fixtures.IntentGuardianTests.native_permission_payload

    def setUp(self):
        fixtures.IntentGuardianTests.setUp(self)
        self.addCleanup(fixtures.IntentGuardianTests.tearDown, self)
        self.home = Path(os.environ["SULDE_KB_HOME"]).resolve()
        self.source = self.home / "intent/workspaces/source.active.json"
        self.contract_path = self.home / "intent/sessions/current.active.json"
        for path, intent, session, confirmed in ((self.source, "source-task", "owner", True),
                (self.contract_path, "new-task", "new-session", False)):
            contract = state.default_contract(intent_id=intent, objective="An isolated local report",
                acceptance_criteria=["A verifiable report"], workspace=self.root, mode="enforce" if confirmed else "shadow",
                confirmed_by="human" if confirmed else "pending", confirmation_required=not confirmed)
            upsert_task_lane(contract, provider="codex", session_id=session, state="bound", source="approved_revision",
                continuation_eligible=confirmed)
            state.write_contract(path, contract)
        bind_session_workspace(self.home, provider="codex", session_id="new-session", contract_path=self.contract_path)

    def prepare(self):
        return selected_task.prepare(self.contract_path, self.source, provider="codex", session_id="new-session")

    def preview(self):
        return approvals.native_decision_preview(self.contract_path, kind="task-continuation", decision="approve",
            target="current", provider="codex", session_id="new-session")

    def allow(self, preview):
        result = approvals.observe_native_permission_request(self.native_permission_payload(preview, session_id="new-session"), provider="codex")
        self.assertEqual(result["action"], "defer", result)

    def execute(self, preview):
        return recovery.execute_native_decision(self.contract_path, kind="task-continuation", decision="approve",
            target=preview["target"], provider="codex", session_id="new-session")

    def test_prepare_is_idempotent_and_source_is_untouched(self):
        before = self.source.read_bytes()
        first = self.prepare()
        current = self.contract_path.read_bytes()
        self.assertEqual(self.prepare(), first)
        self.assertEqual(self.contract_path.read_bytes(), current)
        self.preview()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(resolve_session_contract(self.home, "codex", "new-session"), self.contract_path)

    def test_no_native_allow_means_no_route_change(self):
        self.prepare()
        preview = self.preview()
        self.assertEqual(self.execute(preview)["status"], "awaiting_human")
        self.assertEqual(resolve_session_contract(self.home, "codex", "new-session"), self.contract_path)
        self.assertFalse(state.load_contract(self.source).get("task_continuation_routes"))

    def test_native_allow_commits_without_authority_copy(self):
        self.prepare()
        before = state.load_contract(self.source)
        preview = self.preview()
        self.allow(preview)
        self.assertEqual(self.execute(preview)["status"], "applied")
        self.assertEqual(resolve_session_contract(self.home, "codex", "new-session"), self.source)
        source = state.load_contract(self.source)
        for key in ("approval_receipts", "open_events", "pending_verifications", "authorized_events", "continuation_uses"):
            self.assertEqual(source["runtime"][key], before["runtime"][key])
        self.assertEqual(source["continuation"], before["continuation"])
        self.assertEqual(len(source["runtime"]["task_continuations"]), 1)
        self.assertFalse(source["runtime"]["task_lanes"][-1]["continuation_token"])
        # Journal recovery is idempotent; it must not add a second lane/receipt.
        recovery.recover_native_decisions(self.contract_path)
        self.assertEqual(len(state.load_contract(self.source)["runtime"]["task_continuations"]), 1)

    def test_source_and_destination_revision_drift_are_rejected(self):
        self.prepare()
        preview = self.preview()
        for path in (self.source, self.contract_path):
            with self.subTest(path=path.name):
                before = state.load_contract(path)
                changed = copy.deepcopy(before)
                changed["revision"] += 1
                state.write_contract(path, changed)
                with self.assertRaises(state.IntentGuardianError):
                    self.execute(preview)
                state.write_contract(path, before)
        self.assertEqual(resolve_session_contract(self.home, "codex", "new-session"), self.contract_path)

    def test_route_drift_wrong_session_and_corrupt_selection_are_rejected(self):
        self.prepare()
        preview = self.preview()
        wrong = approvals.observe_native_permission_request(self.native_permission_payload(preview, session_id="other"), provider="codex")
        self.assertEqual(wrong["action"], "deny")
        bind_session_workspace(self.home, provider="codex", session_id="new-session", contract_path=self.contract_path)
        with self.assertRaisesRegex(state.IntentGuardianError, "predecessor"):
            self.preview()
        self.prepare()
        changed = state.load_contract(self.contract_path)
        changed["task_continuation_selection"]["sha256"] = "0" * 64
        state.write_contract(self.contract_path, changed)
        with self.assertRaisesRegex(state.IntentGuardianError, "digest"):
            self.preview()

    def test_cross_workspace_selection_and_busy_destination_are_rejected(self):
        before = state.load_contract(self.source)
        changed = copy.deepcopy(before)
        changed["workspace_root"] = str(self.root.parent)
        state.write_contract(self.source, changed)
        with self.assertRaisesRegex(state.IntentGuardianError, "physical"):
            self.prepare()
        state.write_contract(self.source, before)
        current = state.load_contract(self.contract_path)
        current["runtime"]["pending_proposal_digest"] = "a" * 64
        state.write_contract(self.contract_path, current)
        with self.assertRaisesRegex(state.IntentGuardianError, "unsettled"):
            self.prepare()

    def test_each_interruption_boundary_recovers_exactly_once(self):
        for stage in ("transaction_prepared", "source_staged", "mapping_staged", "source_committed"):
            with self.subTest(stage=stage):
                # Each state-machine branch has independent authoritative logs.
                case = SelectedTaskTests("runTest")
                case.setUp()
                try:
                    case.prepare()
                    preview = case.preview()
                    case.allow(preview)
                    def crash(point):
                        if point == stage:
                            raise RuntimeError("injected interruption")
                    with mock.patch.object(selected_task, "_checkpoint", side_effect=crash):
                        with case.assertRaisesRegex(RuntimeError, "injected"):
                            case.execute(preview)
                    expected = case.source if stage == "source_committed" else case.contract_path
                    case.assertEqual(resolve_session_contract(case.home, "codex", "new-session"), expected)
                    result = recovery.recover_native_decisions(expected, provider="codex", session_id="new-session")
                    case.assertTrue(result)
                    case.assertEqual(resolve_session_contract(case.home, "codex", "new-session"), case.source, result)
                    recovery.recover_native_decisions(case.contract_path)
                    case.assertEqual(len(state.load_contract(case.source)["runtime"]["task_continuations"]), 1)
                finally:
                    case.doCleanups()

    def test_concurrent_prepare_has_one_selection_and_no_source_write(self):
        before = self.source.read_bytes()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.prepare(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.source.read_bytes(), before)

    def receipt_lock_states(self):
        mapping = selected_task.session_workspace_path(self.home, "codex", "new-session")
        paths = [path.with_name("." + path.name + ".lock")
                 for path in (self.contract_path, self.source, mapping)]
        result = subprocess.run(
            [sys.executable, "-B", "-c", LOCK_PROBE, str(fixtures.SCRIPT_DIR),
             *(str(path) for path in paths)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_receipt_tail_and_crash_recovery_hold_both_contracts_and_route(self):
        # Real file locks/receipt writers in disposable state, not live-host proof.
        for boundary in ("after_effect_applied", "after_contract_applied", "after_anchor_receipt"):
            with self.subTest(boundary=boundary):
                case = SelectedTaskTests("runTest")
                case.setUp()
                try:
                    case.prepare()
                    source_before = state.load_contract(case.source)
                    preview = case.preview()
                    case.allow(preview)

                    def interrupt(point):
                        if point == boundary:
                            case.assertEqual(case.receipt_lock_states(), ["blocked"] * 3)
                            raise RuntimeError("receipt boundary interruption")

                    with mock.patch.object(recovery, "_native_decision_failpoint", side_effect=interrupt):
                        with case.assertRaisesRegex(RuntimeError, "receipt boundary interruption"):
                            case.execute(preview)
                    case.assertEqual(case.receipt_lock_states(), ["unlocked"] * 3)
                    original_tail = recovery._advance_native_receipt_chain_locked

                    def locked_tail(*args, **kwargs):
                        case.assertEqual(case.receipt_lock_states(), ["blocked"] * 3)
                        return original_tail(*args, **kwargs)

                    with mock.patch.object(recovery, "_advance_native_receipt_chain_locked",
                                           side_effect=locked_tail) as witnessed:
                        result = recovery.recover_native_decisions(
                            case.source, provider="codex", session_id="new-session")
                    case.assertEqual(witnessed.call_count, 1)
                    case.assertTrue(any(row["stage"] == "committed" for row in result), result)
                    case.assertEqual(case.receipt_lock_states(), ["unlocked"] * 3)
                    case.assertEqual(resolve_session_contract(case.home, "codex", "new-session"), case.source)
                    source_after = state.load_contract(case.source)
                    for key in ("approval_receipts", "open_events", "pending_verifications",
                                "authorized_events", "continuation_uses"):
                        case.assertEqual(source_after["runtime"][key], source_before["runtime"][key])
                    case.assertEqual(source_after["continuation"], source_before["continuation"])
                    case.assertEqual(len(source_after["runtime"]["task_continuations"]), 1)
                    recovery.recover_native_decisions(case.contract_path)
                    transactions = journal.load_projection(case.contract_path)["transactions"]
                    case.assertEqual(len(transactions), 1)
                    transaction = next(iter(transactions.values()))
                    case.assertEqual(transaction["stage"], "committed")
                    for store in (journal.effect_receipt_store_path, journal.contract_receipt_store_path,
                                  journal.external_head_receipt_store_path):
                        rows = [json.loads(line) for line in store(case.contract_path).read_text().splitlines()]
                        case.assertEqual(sum(row["transaction_id"] == transaction["transaction_id"]
                                             for row in rows), 1)
                finally:
                    case.doCleanups()

    def test_non_subjective_shadow_prompt_can_select_without_becoming_authority(self):
        current = state.load_contract(self.contract_path)
        current["confirmation"]["required"] = False
        current["confirmed_by"] = "unconfirmed"
        state.write_contract(self.contract_path, current)
        self.prepare()
        self.assertEqual(self.execute(self.preview())["status"], "awaiting_human")

    def test_staged_route_drift_restores_origin_without_discarding_history(self):
        self.prepare()
        preview = self.preview()
        self.allow(preview)
        def crash(point):
            if point == "mapping_staged":
                raise RuntimeError("interrupted")
        with mock.patch.object(selected_task, "_checkpoint", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.execute(preview)
        source = state.load_contract(self.source)
        source["runtime"]["material_sequence"] += 1
        state.write_contract(self.source, source)
        recovery.recover_native_decisions(self.contract_path)
        self.assertEqual(resolve_session_contract(self.home, "codex", "new-session"), self.contract_path)
        current = state.load_contract(self.contract_path)
        self.assertNotIn("task_continuation_transaction", current)
        self.assertIn(preview["target"], current["task_continuation_history"])
        self.assertIn("selected_task_route_superseded", state.audit_path(self.contract_path).read_text())
        # Same task can be explicitly selected again after terminal revocation.
        self.prepare()
        self.assertNotEqual(self.preview()["target"], preview["target"])

    def test_dependent_memory_invalidates_but_explicit_independent_memory_does_not(self):
        source = state.load_contract(self.source)
        source["decision"] = {"route": "human", "intent_kind": "deterministic", "risk": "low",
            "effects": ["local_write"], "reversibility": "reversible", "cost": "none",
            "rollback": "discard fixture", "unknowns": [], "unattended_policy": "wait"}
        for dependency in ("dependent", "independent"):
            source["constraints"]["memory_dependency"] = dependency
            state.write_contract(self.source, source)
            self.prepare()
            first = self.preview()
            source["runtime"]["material_sequence"] += 1
            source["runtime"]["memory_material_sequence"] = source["runtime"].get("memory_material_sequence", 0) + 1
            state.write_contract(self.source, source)
            second = self.preview()
            self.assertEqual(first["target"] == second["target"], dependency == "independent")

    def test_native_execution_replay_does_not_switch_or_copy_again(self):
        self.prepare()
        preview = self.preview()
        self.allow(preview)
        first = self.execute(preview)
        source = self.source.read_bytes()
        self.assertEqual(self.execute(preview)["transaction_id"], first["transaction_id"])
        self.assertEqual(self.source.read_bytes(), source)

    def test_later_prompt_metadata_does_not_reexecute_a_committed_binding(self):
        self.prepare()
        preview = self.preview()
        self.allow(preview)
        def crash(point):
            if point == "source_committed":
                raise RuntimeError("interrupted after commit")
        with mock.patch.object(selected_task, "_checkpoint", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.execute(preview)
        source = state.load_contract(self.source)
        upsert_task_lane(source, provider="codex", session_id="new-session", state="bound",
            source="task_instance_bound", task_instance_id="later-host-identity")
        state.write_contract(self.source, source)
        result = recovery.recover_native_decisions(self.source, provider="codex", session_id="new-session")
        self.assertTrue(any(row["stage"] == "committed" for row in result), result)
        lane = state.load_contract(self.source)["runtime"]["task_lanes"][-1]
        self.assertEqual(lane["source"], "task_instance_bound")
        self.assertEqual(lane["task_instance_id"], "later-host-identity")

    def test_current_task_instance_change_invalidates_pending_card(self):
        self.prepare()
        preview = self.preview()
        current = state.load_contract(self.contract_path)
        upsert_task_lane(current, provider="codex", session_id="new-session", state="review_required",
            source="explicit_new_task", pending_task_instance_id="a-different-task")
        state.write_contract(self.contract_path, current)
        self.assertNotEqual(self.preview()["target"], preview["target"])
        with self.assertRaisesRegex(state.IntentGuardianError, "stale"):
            self.execute(preview)
        self.assertEqual(resolve_session_contract(self.home, "codex", "new-session"), self.contract_path)

    def test_paused_current_lane_is_not_an_escape_hatch(self):
        current = state.load_contract(self.contract_path)
        upsert_task_lane(current, provider="codex", session_id="new-session", state="paused",
            source="explicit_pause", pause_reason="Needs review")
        state.write_contract(self.contract_path, current)
        with self.assertRaisesRegex(state.IntentGuardianError, "paused"):
            self.prepare()
