from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
from shell_composition import CompositionError, literal_shell_plan
from intent_guardian import GuardianSession, load_contract, normalize_hook_event, write_contract
import intent_guardian as guardian
from tests import test_intent_guardian as fixtures


class ShellPlanTests(unittest.TestCase):
    def test_operators_and_quoted_data_are_preserved(self):
        plan = literal_shell_plan("printf '%s' 'a|b&&c' | head -1 && true || false; pwd\ntrue")
        self.assertEqual([s.after for s in plan], ["start", "|", "&&", "||", ";", ";"])
        self.assertEqual(shlex.split(plan[0].command), ["printf", "%s", "a|b&&c"])

    def test_comments_continuations_and_literal_redirection(self):
        plan = literal_shell_plan("printf x > 'a b' 2>/dev/null &&\\\n true # ; rm x\nfalse")
        self.assertEqual(plan[0].redirects, ((">", "a b"), ("2>", "/dev/null")))
        self.assertEqual([s.after for s in plan], ["start", "&&", ";"])
        self.assertEqual(len(literal_shell_plan("true\n\nfalse;")), 2)
        self.assertEqual(literal_shell_plan("true 2>&1")[0].redirects, (("2>&", "1"),))

    def test_dynamic_and_unbounded_forms_are_not_literal_plans(self):
        for command in (
            "true &&", "true |", "true & false", "true |& false", "true ;; false",
            "true $(rm file)", 'printf "%s" "$TARGET"', 'printf "`pwd`"',
            "cat <(echo x)", "true >", "true 2>&9", "true 9>&1", "cat <<EOF\nx\nEOF",
            "true && cd elsewhere", "true; eval 'touch x'", "true; env X=y sh -c true",
            "true; rm *.txt", "true; command rm x", "true 'unterminated", "true; " * 65,
        ):
            with self.subTest(command=command), self.assertRaises(CompositionError):
                literal_shell_plan(command)


@unittest.skipIf(os.name == "nt", "POSIX control composition; Windows behavior is unchanged")
class ControlCompositionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntentGuardianTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root, self.path = self.fixture.root, self.fixture.contract_path
        contract = self.fixture.contract()
        guardian._upsert_task_lane_locked(contract, provider="codex", session_id="composition-test", state="bound", source="test")
        write_contract(self.path, contract)
        self.launcher = shlex.join([sys.executable, str(ROOT / "scripts/kb/intent-guardian.py")])

    def event(self, command, phase="started", **extra):
        return normalize_hook_event({
            "client": "codex", "session_id": "composition-test", "cwd": str(self.root),
            "tool_name": "Bash", "tool_input": {"command": command},
            "call_id": "composition-call", **extra,
        }, phase=phase, provider="codex")

    def observe(self, command, phase="started", **extra):
        return GuardianSession(self.path).observe(self.event(command, phase, **extra))

    def test_help_query_and_data_filter_compositions_are_allowed(self):
        for command in (
            f"{self.launcher} skill-end --help ; {self.launcher} skill-start --help ; jq -n true",
            f"{self.launcher} show --contract {self.path} | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"status\"))'",
            f"{self.launcher} --help && true || printf fallback",
            f"printf prefix ; {self.launcher} --help | head -1",
            f"{self.launcher} --help > help.txt",
            f"{self.launcher} --help ; printf '%%n'",
        ):
            with self.subTest(command=command):
                decision = self.observe(command)
                self.assertEqual(decision.action, "allow", decision.reason)

    def test_composed_host_calls_have_final_canonical_distinct_identity(self):
        command = f"{self.launcher} --help ; touch marker.txt"
        identities = set()
        for session, call in (("composition-test", "one"), ("composition-test", "two"), ("other", "one")):
            event = self.event(command, session_id=session, call_id=call)
            source = "\0".join(str(event.get(key) or "") for key in (
                "kind", "server", "action", "target", "arguments_digest", "provider", "session_id", "call_id"))
            self.assertEqual(event["event_identity_schema"], "sulde-host-call-event-v2")
            self.assertEqual(event["event_id"], hashlib.sha256(source.encode()).hexdigest()[:24])
            self.assertEqual(event["event_id"], self.event(command, "completed", session_id=session, call_id=call)["event_id"])
            identities.add(event["event_id"])
        self.assertEqual(len(identities), 3)

    def test_explicit_skill_steps_use_their_own_contract_and_session(self):
        def command(session):
            return f"{self.launcher} skill-start sulde:intent-guardian --skill-path {self.fixture.skill_path} --contract {self.path} --provider codex --session-id {session}"
        self.assertEqual(self.observe(command("composition-test") + " && true").action, "allow")
        wrong = self.observe(command("other-session") + " && true")
        self.assertEqual(wrong.action, "deny")
        self.assertIn("session/contract", wrong.reason)
        self.assertFalse(wrong.pause)

    def test_native_or_context_changing_step_cannot_authorize_its_tail(self):
        for action in (
            "native-decision resume --decision resume --target current --contract contract.json --provider codex --session-id thread",
            "approve-proposal contract.json digest",
            "apply-proposal contract.json digest",
        ):
            decision = self.observe(f"{self.launcher} {action} && touch not-authorized")
            self.assertEqual(decision.action, "deny", decision.reason)
            self.assertIn("第 1 步", decision.reason)
            self.assertFalse(decision.pause)

    def test_mutating_or_opaque_filter_is_not_laundered_as_read(self):
        for tail in (
            "python3 -c 'import os; os.system(\"rm -rf output\")'",
            "find . -exec sh -c 'touch sneaky' ';'", "sort -o sneaky",
            "sort -no sneaky", "sort --compress-program=unproved",
            "sed -n '1w sneaky'", "opaque-diagnostic", "python3 -m unittest",
            "python3 -c 'from pathlib import Path; Path(\"visible\").write_text(\"x\"); unproved()'",
            "cp -t .codex-agent visible",
            "printf -vPATH /unproved",
            "printf '%n' PATH", "printf -- '%s%n' hello PATH",
            "printf '%%%n' PATH",
        ):
            with self.subTest(tail=tail):
                decision = self.observe(f"{self.launcher} --help | {tail}")
                self.assertEqual(decision.action, "deny", decision.reason)
                self.assertFalse(decision.pause)

    def test_local_write_tail_does_not_inherit_control_plane_exemption(self):
        contract = load_contract(self.path)
        contract["permissions"]["local_write"] = False
        write_contract(self.path, contract)
        for tail in (" && touch marker.txt", " > marker.txt"):
            decision = self.observe(f"{self.launcher} --help{tail}")
            self.assertEqual(decision.action, "deny", decision.reason)
            self.assertFalse(decision.pause)
        state = load_contract(self.path)
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["runtime"]["open_events"], [])
        self.assertEqual(state["runtime"]["pending_verifications"], [])

    def test_destructive_tail_is_denied_and_following_read_still_works(self):
        marker = self.root / "preserve.txt"
        marker.write_text("keep")
        decision = self.observe(f"{self.launcher} --help ; rm -r -- {marker}")
        self.assertEqual(decision.action, "deny", decision.reason)
        self.assertFalse(decision.pause)
        self.assertEqual(self.observe(f"{self.launcher} --help && true").action, "allow")
        self.assertEqual(marker.read_text(), "keep")

    def test_protected_redirection_is_checked_as_a_write(self):
        target = self.root / ".codex-agent/policy.json"
        decision = self.observe(f"{self.launcher} --help > {target}")
        self.assertEqual(decision.action, "deny", decision.reason)
        self.assertFalse(decision.pause)

    def test_high_risk_steps_need_their_own_exact_human_card_scope(self):
        allowed, other = (self.root / "allowed").resolve(), (self.root / "other").resolve()
        allowed.mkdir()
        other.mkdir()
        contract = load_contract(self.path)
        contract.update({
            "confirmed_by": "human-readable-proposal-approval",
            "applied_proposal_digest": "a" * 64, "applied_approval_receipt_id": "b" * 64,
        })
        contract["permissions"]["destructive"] = "confirm"
        contract["decision"] = {"selected_route": "human", "effects": ["local_write", "destructive"]}
        contract["constraints"]["allowed_paths"] = [str(allowed)]
        write_contract(self.path, contract)
        accepted = self.observe(f"{self.launcher} --help && rm -r -- {allowed}")
        self.assertEqual(accepted.action, "allow", accepted.reason)
        rejected = self.observe(f"{self.launcher} --help && rm -r -- {other}")
        self.assertEqual(rejected.action, "deny", rejected.reason)
        self.assertFalse(rejected.pause)
        # This is a policy fixture, not an actual human receipt or deletion.
        self.assertTrue(allowed.is_dir())
        self.assertTrue(other.is_dir())

    def test_unknown_tail_or_redirection_cannot_hide_behind_a_read_step(self):
        for command in (
            f"true ; {self.launcher} --help ; opaque-writer",
            f"{self.launcher} --help > $(printf escaped)",
            f"{self.launcher} --help ; printf '%s' \"$TARGET\"",
            f"{self.launcher} --help ; python3 -c 'import json,sys; json.load(sys.stdin, object_hook=eval)'",
        ):
            decision = self.observe(command)
            self.assertEqual(decision.action, "deny", decision.reason)
            self.assertFalse(decision.pause)

    def test_compound_exit_code_does_not_forge_per_step_success(self):
        command = f"{self.launcher} --help && false; touch marker.txt"
        event = self.event(command, "completed", success=True)
        self.assertTrue(event["success"])
        self.assertEqual(event["composition"]["step_outcomes"], "not_observed")
        self.assertFalse(event["composition"]["automatic_retry"])
        for step in event["composition"]["steps"]:
            self.assertIsNone(step["event"]["success"])
            self.assertEqual(step["outcome"], "not_observed")
            self.assertNotIn("call_id", step["event"])

    def test_original_shell_short_circuit_and_sequence_really_execute(self):
        for number, (operator, expected) in enumerate((("&&", False), (";", True), ("||", True))):
            marker = self.root / ("marker-" + operator.replace("|", "o").replace("&", "a"))
            command = f"{self.launcher} --help && false {operator} touch {shlex.quote(str(marker))}"
            pre = self.observe(command, call_id=f"shell-composition-{number}")
            self.assertEqual(pre.action, "allow", pre.reason)
            completed = subprocess.run(["/bin/sh", "-c", command], cwd=self.root, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(marker.exists(), expected)
            self.observe(command, "completed", success=completed.returncode == 0, call_id=f"shell-composition-{number}")
        state = load_contract(self.path)
        self.assertEqual(state["runtime"]["open_events"], [])
        self.assertEqual(state["runtime"]["pending_verifications"], [])

    def test_unified_exec_preserves_composition_projection(self):
        command = f"{self.launcher} --help && true"
        event = normalize_hook_event({
            "client": "codex", "session_id": "composition-test", "cwd": str(self.root),
            "tool_name": "exec", "tool_input": "await tools.exec_command({cmd: " + json.dumps(command) + "});",
        }, phase="started", provider="codex")
        self.assertEqual(event["orchestrator_wrapper"], "codex_unified_exec")
        self.assertEqual(GuardianSession(self.path).observe(event).action, "allow")

    def test_unified_exec_cannot_launder_a_later_control_decision(self):
        for tail, expected in (("--help && true", "allow"), ("approve-proposal x y", "deny"), ("apply-proposal x y", "deny")):
            commands = [self.launcher + " --help && true", self.launcher + " " + tail]
            source = "\n".join("await tools.exec_command({cmd: " + json.dumps(command) + "});" for command in commands)
            event = normalize_hook_event({
                "client": "codex", "session_id": "composition-test", "cwd": str(self.root),
                "tool_name": "exec", "tool_input": source,
            }, phase="started", provider="codex")
            self.assertEqual(GuardianSession(self.path).observe(event).action, expected)


if __name__ == "__main__":
    unittest.main()
