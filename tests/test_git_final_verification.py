"""Git final-read reachability; no production hooks or approvals are replayed."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
from intent_guardian import normalize_hook_event
from intent_guardian_parts import audit, repository_relocation, state
from command_template import git_execution_passthrough, git_stdin_review_pipeline
from intervention import (begin_attempt, mark_attempt_unknown, load_projection,
                          event_store_path, canonical_resource_key, blocking_attempts)

SPEC = importlib.util.spec_from_file_location(
    "git_review_recovery_defer",
    ROOT / "integrations/codex/plugins/sulde/scripts/_recovery_defer.py",
)
fallback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fallback)

PURE_GIT = (
    "git status --short", "git rev-parse HEAD", "git diff --stat",
    "git status && git diff --stat", "cd /tmp && git status",
    "cd -- '/tmp/path with spaces' && git rev-parse HEAD",
    'cd "./relative path" && git status && git diff --stat',
)
READ_PIPELINES = (
    "git status | head -n 20", "git diff --stat | tail -n 10",
    "git status --short | head -n 20 | wc -l",
    "cd '/tmp/path with spaces' && git status | head -n 20",
)
UNPROVEN = (
    "cd /tmp; git status", "cd /tmp || git status", "cd && git status",
    "cd - && git status", "cd $TARGET && git status",
    'cd "$(pwd)" && git status', "cd /tmp/* && git status",
    "cd /tmp && git status | tee status.txt", "git status > status.txt",
    "git status | head -n 20 > status.txt", "git status | head -n 20; touch file",
    "git status | head -n 20 && git status", "git status | head private.txt",
    "git status | wc --files0-from=secret", "git status | sed 'w out'",
    "git status | sort -o out", "git status | head -n $(touch out)",
    "git status | head -n 20 &", "git status | head -n 20 || touch out",
    "git status | /tmp/head", "git status | head -n 20 | tee out",
)


class GitFinalVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sulde-final-git-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def payload(self, command, phase="started"):
        return dict(client="codex", session_id="synthetic-final-check",
                    cwd=str(self.root), intent_contract=str(self.root / "intent.json"),
                    tool_name="Bash", tool_input={"command": command},
                    call_id="synthetic-call", success=phase == "completed")

    def degraded_deny(self, payload):
        return fallback.payload_requires_fail_closed(
            payload, runtime_root=self.root / "absent-runtime",
            launcher_home=self.root / "absent-home")

    def test_literal_cwd_is_git_in_both_independent_classifiers(self):
        for command in PURE_GIT:
            with self.subTest(command=command):
                self.assertTrue(git_execution_passthrough(command))
                self.assertFalse(self.degraded_deny(self.payload(command)))

    def test_bounded_stdin_filters_are_read_in_both_paths(self):
        for command in READ_PIPELINES:
            with self.subTest(command=command):
                event = normalize_hook_event(self.payload(command), phase="started", provider="codex")
                self.assertEqual(event["effect"], "read")
                self.assertFalse(self.degraded_deny(self.payload(command)))

    def test_unknown_and_additional_writes_are_not_git_or_degraded_allow(self):
        for command in UNPROVEN:
            with self.subTest(command=command):
                self.assertFalse(git_execution_passthrough(command))
                self.assertTrue(self.degraded_deny(self.payload(command)))

    def test_pipeline_bounds_and_shell_near_misses(self):
        cases = (*UNPROVEN, "git status | head -n 12345678",
                 "git status" + " | head" * 8, "git status " + "x" * 65536 + " | head",
                 "git status | head -n '20; touch out'", "git status | head -n ${COUNT}",
                 "git status | head -n 20\\", 'git status | head "unterminated')
        for command in cases:
            with self.subTest(command=command[:100]):
                self.assertFalse(git_stdin_review_pipeline(command))
                self.assertFalse(fallback.git_stdin_review_pipeline(command))

    def test_failed_literal_cd_keeps_shell_short_circuit_semantics(self):
        missing = self.root / "missing"
        command = f"cd {shlex.quote(str(missing))} && git status --short"
        self.assertTrue(git_execution_passthrough(command))
        with mock.patch.dict("os.environ", {"GIT_TRACE": "1"}):
            result = subprocess.run(["/bin/sh", "-c", command], cwd=self.root,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("built-in: git", result.stderr)
        self.assertFalse(missing.exists())

    def process(self, command, phase, *, mapping_error=False):
        payload = self.payload(command, phase)
        with mock.patch.object(repository_relocation, "route_relocation_recovery", return_value=None), \
             mock.patch.object(audit, "route_production_recovery", return_value=None), \
             mock.patch.object(audit, "kb_home", return_value=self.root), \
             mock.patch.object(audit, "resolve_contract_path", **(
                 {"side_effect": state.IntentGuardianError("synthetic missing mapping")}
                 if mapping_error else {"return_value": self.root / "intent.json"}
             )):
            return audit.process_hook(payload, phase=phase, provider="codex")[0]

    def test_started_and_completed_remain_reachable_with_missing_mapping(self):
        for command in PURE_GIT + READ_PIPELINES:
            for phase in ("started", "completed"):
                with self.subTest(command=command, phase=phase):
                    decision = self.process(command, phase, mapping_error=True)
                    self.assertEqual(decision.action, "allow")
                    self.assertFalse(decision.verification_required)

    def test_paused_and_unreadable_ledger_does_not_gate_git(self):
        # Independent Git authority must not deserialize or repair this state.
        contract = self.root / "intent.json"
        contract.write_text('{"status":"paused","runtime":{"pending_verifications":["unproved"]}}')
        ledger = self.root / "intent.effects.events.jsonl"
        ledger.write_text("unreadable synthetic ledger\n")
        before = (contract.read_bytes(), ledger.read_bytes())
        for command in PURE_GIT:
            self.assertEqual(self.process(command, "started").action, "allow")
            self.assertEqual(self.process(command, "completed").action, "allow")
        self.assertEqual(before, (contract.read_bytes(), ledger.read_bytes()))

    def test_existing_unknown_external_effect_remains_unresolved_after_reads(self):
        contract = self.root / "intent.json"
        state.write_contract(contract, state.default_contract(
            intent_id="synthetic-final-check", objective="local Git review",
            acceptance_criteria=["readback without granting effect success"],
            workspace=self.root, mode="enforce", allowed_paths=["**"],
            confirmed_by="human-readable-proposal-approval"))
        attempt = begin_attempt(
            contract, intent_id="synthetic-final-check", intent_revision=1,
            fingerprint="f" * 64, source_event_id="historical-event",
            capability="mcp:docs:update_document", target="doc://synthetic",
            resource_key=canonical_resource_key("doc://synthetic", kind="uri"),
            effect="external_write", provider="codex", session_id="old-thread",
            idempotency_key="synthetic-existing-debt", verification_kind="existence")
        mark_attempt_unknown(contract, attempt["attempt_id"], reason="synthetic lost completion")
        before = event_store_path(contract).read_bytes()
        self.assertTrue(blocking_attempts(load_projection(contract)))
        for command in PURE_GIT + READ_PIPELINES:
            for phase in ("started", "completed"):
                self.assertEqual(self.process(command, phase).action, "allow")
        self.assertEqual(before, event_store_path(contract).read_bytes())
        self.assertTrue(blocking_attempts(load_projection(contract)))

    def test_actual_adapter_failure_output_preserves_only_proven_reads(self):
        from tests.test_codex_hook_bridge import load_pre_tool_adapter
        import production_recovery_control
        module = load_pre_tool_adapter()
        for command in PURE_GIT + READ_PIPELINES + UNPROVEN:
            with self.subTest(command=command):
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(module, "_payload", return_value=self.payload(command)), \
                     mock.patch.object(module, "run_runtime", side_effect=OSError("synthetic unavailable")), \
                     mock.patch.object(production_recovery_control, "route_native_recovery", return_value=None), \
                     mock.patch.object(module.sys, "stdout", stdout), \
                     mock.patch.object(module.sys, "stderr", stderr):
                    self.assertEqual(module.main(), 0)
                if command in UNPROVEN:
                    self.assertEqual(json.loads(stdout.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")
                else:
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("degraded_to_native_codex", stderr.getvalue())

    def test_static_and_stable_fallbacks_match_the_full_review_matrix(self):
        import codex_recovery_defer
        for command in PURE_GIT + READ_PIPELINES + UNPROVEN:
            with self.subTest(command=command):
                self.assertEqual(self.degraded_deny(self.payload(command)),
                    codex_recovery_defer.payload_requires_fail_closed(
                        self.payload(command), runtime_root=self.root / "absent-runtime",
                        launcher_home=self.root / "absent-home"))

    def test_real_local_commit_then_synthetic_hook_final_reads(self):
        # Real local Git; synthetic Hook payloads are not live host evidence.
        repo = self.root / "repo with spaces"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True, encoding="utf-8", errors="replace").strip()
        git("init", "-q")
        git("config", "user.name", "Synthetic Test")
        git("config", "user.email", "test@example.invalid")
        git("config", "commit.gpgsign", "false")
        git("config", "core.hooksPath", str(self.root / "no-hooks"))
        (repo / "item.txt").write_text("synthetic\n")
        git("add", "--", "item.txt")
        commit = f"cd {shlex.quote(str(repo))} && git commit -qm synthetic"
        self.assertEqual(self.process(commit, "started", mapping_error=True).action, "allow")
        subprocess.run(["/bin/sh", "-c", commit], check=True)
        self.assertEqual(self.process(commit, "completed", mapping_error=True).action, "allow")
        expected = git("rev-parse", "HEAD")
        commands = [f"cd {shlex.quote(str(repo))} && git {suffix}" for suffix in
                    ("status --short", "rev-parse HEAD", "diff --stat", "status --short | head -n 20")]
        for command in commands:
            self.assertEqual(self.process(command, "started", mapping_error=True).action, "allow")
            self.assertFalse(self.degraded_deny(self.payload(command)))
            result = subprocess.check_output(["/bin/sh", "-c", command], text=True, encoding="utf-8", errors="replace").strip()
            self.assertEqual(result, expected if "rev-parse" in command else "")
            self.assertEqual(self.process(command, "completed", mapping_error=True).action, "allow")
        self.assertEqual(git("rev-list", "--count", "HEAD"), "1")
        self.assertFalse((self.root / "intent.json").exists())
        self.assertFalse(list(self.root.glob("*.jsonl")))
        contract = self.root / "intent.json"
        state.write_contract(contract, state.default_contract(
            intent_id="synthetic-final-check", objective="local Git review",
            acceptance_criteria=["one local commit and no Git verification debt"],
            workspace=self.root, mode="enforce", allowed_paths=["**"],
            confirmed_by="human-readable-proposal-approval"))
        for command in commands:
            for phase in ("started", "completed"):
                self.assertEqual(self.process(command, phase).action, "allow")
        with mock.patch.object(audit, "resolve_contract_path", return_value=contract):
            self.assertEqual(audit.finalize_host_turn(
                {"client":"codex", "session_id":"synthetic-final-check", "cwd":str(self.root)},
                provider="codex"), "")
        runtime = state.load_contract(contract)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(load_projection(contract)["attempts"], {})
        self.assertEqual(git("rev-list", "--count", "HEAD"), "1")


if __name__ == "__main__":
    unittest.main()
