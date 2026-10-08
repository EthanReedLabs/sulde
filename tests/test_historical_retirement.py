"""Temporary real-Git / typed-ledger retirement tests; never production data."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
from intent_guardian_parts import historical_retirement as retirement
from intent_guardian_parts import repository_relocation as relocation
from intent_guardian_parts.state import (
    IntentGuardianError, active_contract_path, default_contract, load_contract, write_contract,
)
from intent_guardian_parts.session_workspace import bind_session_workspace
from intent_guardian_parts.approvals import native_decision_preview, observe_native_permission_request
from intent_guardian_parts.recovery import execute_native_decision


class HistoricalRetirementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sulde-retirement-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.home = self.base / "kb"
        env = mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        env.start()
        self.addCleanup(env.stop)
        self.root = self.base / "repository"
        self.root.mkdir()
        self.git("init", "-b", "dev")
        (self.root / "file.txt").write_text("fixture\n")
        (self.root / ".gitignore").write_text(".worktrees/\n")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        self.worktree = self.root / ".worktrees/control"
        self.git("worktree", "add", "-b", "task/control", str(self.worktree))
        self.source = active_contract_path(self.home, self.root)
        self.controller = active_contract_path(self.home, self.worktree)
        for path, workspace in [(self.source, self.root), (self.controller, self.worktree)]:
            value = default_contract(intent_id=path.stem, objective="fixture task",
                acceptance_criteria=["preserve history"], workspace=workspace,
                mode="enforce", confirmed_by="fixture")
            write_contract(path, value)
        bind_session_workspace(self.home, provider="codex", session_id="control-session", contract_path=self.controller)
        target = load_contract(self.source)
        target["runtime"]["pre_execution_gaps"] = [{"event_id": "old-event", "at": "2026-08-01T00:00:00+00:00",
            "provider": "codex", "session_id": "old-session", "effect": "local_write",
            "capability": "tool:apply_patch", "reason_code": "policy_denied", "target": "scripts/kb/intent-guardian.py",
            "runtime_generation": "1" * 64}]
        write_contract(self.source, target)
        self.before = self.source.read_bytes()
        self.plan = retirement.prepare(self.home, self.controller, self.source,
                                       provider="codex", session_id="control-session")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=True).stdout

    def preview(self):
        return native_decision_preview(self.controller, kind=retirement.KIND, decision="terminate",
            target=self.plan["plan_id"], provider="codex", session_id="control-session")

    def question(self):
        preview = self.preview()
        result = observe_native_permission_request({"client": "codex", "session_id": "control-session",
            "cwd": str(self.worktree), "intent_contract": str(self.controller), "permission_mode": "default",
            "tool_name": "Bash", "tool_input": {"command": shlex.join(preview["command_argv"]),
            "description": preview["description"]}}, provider="codex")
        self.assertEqual(result["action"], "defer", result)
        return result

    def execute(self, **overrides):
        return execute_native_decision(self.controller, kind=retirement.KIND, decision="terminate",
            target=self.plan["plan_id"], provider="codex", session_id=overrides.get("session_id", "control-session"))

    def expired_history(self):
        from approval_invariant import ask_approval, event_store_path
        contract = load_contract(self.source)
        with mock.patch("approval_invariant.datetime", wraps=datetime) as clock:
            for index, (kind, source) in enumerate((("proposal", "codex_permission_request"),
                                 ("effect-intervention", "session_start_restore"),
                                 ("intent-confirmation", "session_resume_card"))):
                # Each earlier question has expired before the next is asked;
                # otherwise the real API correctly supersedes an open proposal.
                clock.now.return_value = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
                ask_approval(self.source, intent_id=contract["intent_id"],
                    intent_revision=contract["revision"], kind=kind, target="old-" + kind,
                    source=source, provider="codex", session_id="old-session", ttl_seconds=300)
        return event_store_path(self.source)

    @unittest.skipUnless(sys.platform == "darwin", "physical relocation preflight is macOS-only")
    def test_expired_history_after_retirement_passes_real_cli_without_mutation(self):
        from approval_invariant import summary, load_projection
        ledger = self.expired_history()
        self.assertEqual(summary(self.source)["open"], 0)
        self.assertEqual(summary(self.source)["expired"], 3)
        with self.assertRaisesRegex(IntentGuardianError, "settled contract state"):
            relocation.assess_repository_relocation(self.home, self.root, self.base / "moved",
                provider="codex", session_id="control-session")
        self.question()
        self.execute()
        before = {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        command = [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
            "repository-relocation-preflight", str(self.root), str(self.base / "moved"),
            "--home", str(self.home), "--provider", "codex", "--session-id", "control-session",
            "--assessment-only"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["execution_authorized"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()})
        self.assertTrue(all(r["status"] == "asked" for r in load_projection(self.source)["requests"].values()))
        self.assertEqual(ledger.read_bytes(), before[str(ledger)])
        self.assertFalse((self.base / "moved").exists())

    def test_prepare_has_no_permission_or_target_mutation(self):
        self.assertFalse(self.plan["execution_authorized"])
        self.assertEqual(self.source.read_bytes(), self.before)
        with self.assertRaisesRegex(IntentGuardianError, "native Allow"):
            self.execute()
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_allow_retains_original_and_unknown_and_is_idempotent(self):
        self.question()
        first = self.execute()
        self.assertEqual(first["status"], "retired_inconclusive")
        self.assertFalse(first["effect_asserted"])
        after = load_contract(self.source)
        self.assertEqual(after["runtime"]["pre_execution_gaps"], json.loads(self.before)["runtime"]["pre_execution_gaps"])
        self.assertEqual(after["status"], "paused")
        self.assertTrue(after["runtime"]["pause_requires_revision"])
        self.assertEqual(self.execute(), first)
        stored = retirement._load(self.home, self.plan["plan_id"])
        self.assertEqual(stored["source_raw"].encode(), self.before)
        self.assertEqual(len(list((self.home / "intent/historical-retirements").glob("*.committed.json"))), 1)

    def test_typed_deny_leaves_target_unchanged(self):
        from approval_invariant import load_projection, decide_typed_approval
        question = self.question()
        request = load_projection(self.controller)["requests"][question["request_id"]]
        decide_typed_approval(self.controller, request_id=request["request_id"], receipt_id=request["request_identity"],
            outcome="deny", snapshot=request["snapshot"], current_snapshot=request["snapshot"],
            provider="codex", session_id="control-session", decision_owner="human", actor="permission-request:codex")
        with self.assertRaisesRegex(IntentGuardianError, "native Allow"):
            self.execute()
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_cross_session_and_new_material_rejected(self):
        self.question()
        with self.assertRaisesRegex(IntentGuardianError, "lane"):
            self.execute(session_id="other-session")
        value = load_contract(self.source)
        value["runtime"]["pre_execution_gaps"][0]["event_id"] = "new-event"
        write_contract(self.source, value)
        with self.assertRaisesRegex(IntentGuardianError, "CAS"):
            self.execute()
        self.assertEqual(load_contract(self.source)["status"], "active")

    def test_observation_is_not_material_cas(self):
        self.question()
        value = load_contract(self.source)
        value["runtime"]["sequence"] += 1
        value["runtime"]["material_sequence"] += 1
        write_contract(self.source, value)
        self.assertEqual(self.execute()["status"], "retired_inconclusive")

    def test_retirement_invalidates_old_policy_and_requires_human_revision(self):
        from intent_guardian_parts.state import policy_digest
        from intent_guardian_parts.approvals import agent_decision_eligibility, native_decision_context
        before = policy_digest(load_contract(self.source))
        self.question()
        self.execute()
        retired = load_contract(self.source)
        self.assertNotEqual(policy_digest(retired), before)
        allowed, reasons = agent_decision_eligibility(retired, retired)
        self.assertFalse(allowed)
        self.assertTrue(any("历史阶段" in reason for reason in reasons))
        with self.assertRaisesRegex(IntentGuardianError, "retired"):
            native_decision_context(self.source, kind="resume", decision="resume", target="current",
                                    provider="codex", session_id="old-session")

    @unittest.skipUnless(sys.platform == "darwin", "physical relocation preflight is macOS-only")
    def test_real_effect_debt_still_blocks_after_retirement(self):
        from intervention import begin_attempt
        self.expired_history()
        self.question()
        self.execute()
        c = load_contract(self.source)
        begin_attempt(self.source, intent_id=c["intent_id"], intent_revision=c["revision"],
            fingerprint="c" * 64, source_event_id="fixture-external", capability="mcp:example:write",
            target="example:item:1", effect="external_write", provider="codex", session_id="old-session",
            idempotency_key="fixture-effect")
        with self.assertRaisesRegex(IntentGuardianError, "effect debt"):
            relocation.assess_repository_relocation(self.home, self.root, self.base / "moved",
                provider="codex", session_id="control-session")

    def test_controller_policy_change_and_generation_change_reject(self):
        self.question()
        with mock.patch.object(retirement, "ARTIFACT_GENERATION", "new-generation"):
            with self.assertRaisesRegex(IntentGuardianError, "generation"):
                self.execute()
        c = load_contract(self.controller)
        c["objective"] = "another task"
        write_contract(self.controller, c)
        with self.assertRaisesRegex(IntentGuardianError, "policy"):
            self.execute()
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_crash_after_pause_recovers_existing_allow_without_redecision(self):
        self.question()
        def crash(stage):
            if stage == "target_paused":
                raise RuntimeError("fixture crash")
        with mock.patch.object(retirement, "_boundary", side_effect=crash), self.assertRaisesRegex(RuntimeError, "fixture crash"):
            self.execute()
        with self.assertRaises(FileNotFoundError):
            retirement.verify(self.home, self.source, load_contract(self.source))
        from approval_invariant import load_projection
        before = copy.deepcopy(load_projection(self.controller))
        self.assertEqual(self.execute()["status"], "retired_inconclusive")
        self.assertEqual(load_projection(self.controller), before)

    def test_new_records_after_retirement_are_not_hidden(self):
        self.question()
        self.execute()
        value = load_contract(self.source)
        value["runtime"]["pre_execution_gaps"].append({**value["runtime"]["pre_execution_gaps"][0], "event_id": "new"})
        write_contract(self.source, value)
        with self.assertRaisesRegex(IntentGuardianError, "material state"):
            retirement.verify(self.home, self.source, load_contract(self.source))

    def test_decision_and_terminal_crash_boundaries_recover_once(self):
        self.question()
        from approval_invariant import load_projection
        for boundary in ("decision_recorded", "committed"):
            with self.subTest(boundary=boundary):
                def crash(stage):
                    if stage == boundary:
                        raise RuntimeError("fixture crash")
                with mock.patch.object(retirement, "_boundary", side_effect=crash), self.assertRaisesRegex(RuntimeError, "fixture crash"):
                    self.execute()
        before = copy.deepcopy(load_projection(self.controller))
        result = self.execute()
        self.assertEqual(result["status"], "retired_inconclusive")
        self.assertEqual(load_projection(self.controller), before)
        self.assertEqual(len(list((self.home / "intent/historical-retirements").glob("*.committed.json"))), 1)

    @unittest.skipUnless(sys.platform == "darwin", "physical relocation is macOS-only")
    def test_retirement_then_real_move_archives_history_without_copying_authority(self):
        approval_ledger = self.expired_history()
        original_approvals = approval_ledger.read_bytes()
        self.question()
        self.execute()
        retired_bytes = self.source.read_bytes()
        destination = self.base / "moved"
        plan = relocation.prepare_relocation_plan(self.home, self.controller, self.root, destination,
            provider="codex", session_id="control-session")
        preview = native_decision_preview(self.controller, kind=relocation.EXECUTION_KIND, decision="execute",
            target=plan["plan_id"], provider="codex", session_id="control-session")
        observed = observe_native_permission_request({"client": "codex", "session_id": "control-session",
            "cwd": str(self.worktree), "intent_contract": str(self.controller), "permission_mode": "default",
            "tool_name": "Bash", "tool_input": {"command": shlex.join(preview["command_argv"]),
            "description": preview["description"]}}, provider="codex")
        self.assertEqual(observed["action"], "defer", observed)
        command = [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"), *preview["argv"], "--home", str(self.home)]
        executed = subprocess.run(command, cwd=self.base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
        self.assertEqual(json.loads(executed.stdout)["status"], "committed")
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        archive = relocation._relocation_archive_path(frozen, self.source)
        self.assertEqual(archive.read_bytes(), retired_bytes)
        successor = load_contract(relocation._relocation_successor_path(frozen["preflight"], self.source))
        self.assertEqual(successor["status"], "paused")
        self.assertTrue(successor["confirmation"]["required"])
        self.assertFalse(successor["permissions"]["local_write"])
        self.assertNotIn(retirement.MARKER, successor["runtime"])
        self.assertEqual(successor["runtime"]["open_events"], [])
        self.assertEqual((destination / "file.txt").read_text(), "fixture\n")
        self.assertEqual(approval_ledger.read_bytes(), original_approvals)

    def test_control_plane_patch_is_retired_without_claiming_execution_success(self):
        value = load_contract(self.source)
        value["runtime"]["open_events"] = [{"event_id": "old-patch", "sequence": 1,
            "kind": "tool", "effect": "local_write", "capability": "tool:apply_patch",
            "target": "scripts/kb/intent-guardian.py", "provider": "codex", "session_id": "old-session",
            "fingerprint": "f" * 64, "call_id": "old-call", "started_at": "2026-08-01T00:00:00+00:00",
            "runtime_generation": "1" * 64, "task_epoch": value["task_epoch"], "attempt_id": ""}]
        write_contract(self.source, value)
        before = load_contract(self.source)
        self.plan = retirement.prepare(self.home, self.controller, self.source,
            provider="codex", session_id="control-session")
        self.question()
        result = self.execute()
        self.assertFalse(result["effect_asserted"])
        self.assertEqual(load_contract(self.source)["runtime"]["open_events"], before["runtime"]["open_events"])

    def test_current_lane_records_cannot_be_disguised_as_historical(self):
        value = load_contract(self.source)
        value["runtime"]["pre_execution_gaps"][0]["session_id"] = "control-session"
        write_contract(self.source, value)
        with self.assertRaisesRegex(IntentGuardianError, "current session"):
            retirement.prepare(self.home, self.controller, self.source, provider="codex", session_id="control-session")

    def test_broad_permissions_and_symlink_plan_are_rejected(self):
        path = retirement._file(self.home, self.plan["plan_id"])
        path.chmod(0o644)
        with self.assertRaisesRegex(IntentGuardianError, "owner-only"):
            self.preview()
        path.chmod(0o600)
        original = path.with_suffix(".saved")
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaisesRegex(IntentGuardianError, "owner-only"):
            self.preview()

    def test_retired_epoch_cannot_use_previous_grants_even_if_pause_projection_drifts(self):
        from intent_guardian_parts.policy import evaluate_event
        from intent_guardian_parts.resources import normalize_hook_event
        self.question()
        self.execute()
        value = load_contract(self.source)
        value["status"] = "active"
        event = normalize_hook_event({"client": "codex", "session_id": "old-session", "cwd": str(self.root),
            "tool_name": "Write", "tool_input": {"file_path": str(self.root / "file.txt"), "content": "bad"}},
            phase="started", provider="codex")
        self.assertEqual(evaluate_event(value, event, contract_path=self.source).action, "deny")

    @unittest.skipUnless(sys.platform == "darwin", "physical relocation preflight is macOS-only")
    def test_relocation_accepts_verified_retirement_but_not_forged_marker(self):
        self.question()
        self.execute()
        result = relocation.assess_repository_relocation(self.home, self.root, self.base / "moved",
            provider="codex", session_id="control-session")
        self.assertFalse(result["execution_authorized"])
        terminal = retirement._file(self.home, self.plan["plan_id"], ".committed.json")
        value = json.loads(terminal.read_text())
        value["authority"]["decision_identity"] = "forged"
        terminal.write_text(json.dumps(value))
        with self.assertRaisesRegex(IntentGuardianError, "terminal receipt"):
            relocation.assess_repository_relocation(self.home, self.root, self.base / "moved",
                provider="codex", session_id="control-session")


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("codex"), "requires macOS native Codex acceptance")
class InstalledHistoricalRetirementTests(unittest.TestCase):
    def test_installed_native_transactions_allow(self):
        self.run_case(deny=False, native_transactions=True)

    def test_installed_native_transactions_deny(self):
        self.run_case(deny=True, native_transactions=True)

    def test_installed_native_allow(self):
        self.run_case(deny=False)

    def test_installed_native_deny(self):
        self.run_case(deny=True)

    def run_case(self, *, deny, native_transactions=False):
        from tests.test_native_memory_continuation import candidate, model_host
        with tempfile.TemporaryDirectory(prefix="sulde-retirement-native-") as temporary:
            slot, codex = Path(temporary).resolve(), shutil.which("codex")
            installer = candidate.installer
            artifact = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = artifact.descriptor["delivery_generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, artifact.marketplace, runner,
                    expected_version=generation["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                candidate._prepare_isolated_hook_launchers(installed, kb, runner,
                    platform="posix", environment=env)
                installer._smoke_installed(installed, kb, codex=codex,
                    expected_tree_sha256=artifact.plugin_tree_sha256, runner=runner)
                root = slot / "isolated/repository"
                root.mkdir(parents=True)
                def git(*args):
                    result = runner(["git", "-C", str(root), *args], environment=env, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                git("init", "-b", "dev")
                (root / ".gitignore").write_text(".worktrees/\n")
                (root / "preserved.txt").write_text("unchanged\n")
                git("add", ".")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
                worktree = root / ".worktrees/control"
                git("worktree", "add", "-b", "task/control", str(worktree))
                source = active_contract_path(kb, root)
                target = default_contract(intent_id="historical-fixture", objective="old fixture task",
                    acceptance_criteria=["old phase"], workspace=root, mode="enforce", confirmed_by="fixture")
                target["runtime"]["pre_execution_gaps"] = [{"event_id": "old-event", "at": "2026-08-01T00:00:00+00:00",
                    "provider": "codex", "session_id": "old-fixture-session", "effect": "local_write",
                    "capability": "tool:apply_patch", "reason_code": "policy_denied", "target": "preserved.txt",
                    "runtime_generation": "1" * 64}]
                write_contract(source, target)
                if native_transactions:
                    from tests.test_historical_native_retirement import historical_contract_transactions
                    historical_contract_transactions(source, root)
                    target = load_contract(source)
                before = source.read_bytes()
                guardian = Path(env["SULDE_HOME"]) / "bin/intent-guardian"
                with model_host(codex, worktree, env,
                        externally_isolated=bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))) as host:
                    controller, _ = candidate._activate_candidate_enforce_contract(guardian, kb_home=kb,
                        workspace=worktree, session=host.session, environment=env, runner=runner)
                    def control(action, *args):
                        return candidate._parse_json_result(runner([str(guardian), action, *args,
                            "--contract", str(controller), "--provider", "codex", "--session-id", host.session],
                            environment={**env, "CODEX_THREAD_ID": host.session}, timeout=30), label=action)
                    checkpoint = {}
                    if native_transactions:
                        # First genuinely retire the epoch through this disposable
                        # native host. Its approval must NOT authorize the batch.
                        def retire_epoch():
                            plan = control("prepare-historical-retirement", str(source))
                            preview = control("native-decision-preview", retirement.KIND,
                                "--decision", "terminate", "--target", plan["plan_id"])
                            host.commands[0] = host.approval_command(preview)
                            host.commands[0]["yield_time_ms"] = 30000
                        host.before_calls = {0: retire_epoch}
                        host.run_more(["replace with epoch retirement"])
                        self.assertEqual(host.approval_count, 1)
                        before = source.read_bytes()
                    call_index = len(host.calls)
                    def prepare_card():
                        plan = control("prepare-historical-retirement", str(source),
                            *(["--native-transactions"] if native_transactions else []))
                        preview = control("native-decision-preview", retirement.KIND, "--decision", "terminate",
                                          "--target", plan["plan_id"])
                        checkpoint.update(plan=plan)
                        host.commands[call_index] = host.approval_command(preview, decision="decline" if deny else "accept")
                        host.commands[call_index]["yield_time_ms"] = 30000
                    host.before_calls = {call_index: prepare_card}
                    items = host.run_more(["replace after actual UserPromptSubmit"])
                    self.assertEqual(getattr(host, "approval_count", 0), 2 if native_transactions else 1, json.dumps(items)[-2500:])
                    self.assertIsNone(host.expected_approval)
                    terminal = retirement._file(kb, checkpoint["plan"]["plan_id"], ".committed.json")
                    if deny:
                        self.assertEqual(source.read_bytes(), before)
                        self.assertFalse(terminal.exists())
                    else:
                        self.assertTrue(terminal.is_file(), json.dumps(items)[-3500:])
                        self.assertEqual(load_contract(source)["status"], "paused")
                        self.assertEqual(load_contract(source)["runtime"]["pre_execution_gaps"], target["runtime"]["pre_execution_gaps"])
                        # The installed CLI re-enters the exact same consumed decision.
                        again = control("native-decision", retirement.KIND, "--decision", "terminate",
                                        "--target", checkpoint["plan"]["plan_id"])
                        self.assertEqual(again["status"], "retired_inconclusive")
                    if native_transactions:
                        import native_decision_journal as journal
                        rows = list(journal.load_projection_read_only(source)["transactions"].values())
                        self.assertEqual(sum(row["stage"] == "superseded" for row in rows), 0 if deny else 4)
                        self.assertEqual(sum(row["stage"] == "contract_applied" for row in rows), 4 if deny else 0)
                        self.assertEqual(sum(journal.is_legacy_unsealed_prepared_diagnostic(row) for row in rows), 5)
                        self.assertEqual(source.read_bytes(), before)
                    self.assertEqual((root / "preserved.txt").read_text(), "unchanged\n")
                    print("HISTORICAL_RETIREMENT_NATIVE=" + json.dumps({"decision": "deny" if deny else "allow",
                        "generation": generation["generation"], "native_questions": host.approval_count,
                        "native_transactions": native_transactions,
                        "target_paused": load_contract(source)["status"] == "paused",
                        "original_operation_replayed": False}), flush=True)


if __name__ == "__main__":
    unittest.main()
