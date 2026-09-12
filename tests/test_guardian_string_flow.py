"""Sanitized business shapes and adversarial counterexamples; no business IO."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/kb"))
from intent_guardian_parts.resources import _python_source_effect, normalize_hook_event
from python_data_methods import proven_data_method_calls
from python_string_flow import proven_string_method_calls

BOSS_SOURCE = (
    "from pathlib import Path\n"
    "p=Path('service.py');s=p.read_text();"
    "s=s.replace('before', 'after');p.write_text(s)"
)
KEYS_SOURCE = "[dict(metric_id=k.replace('_','-')) for k in ('verified_count','retained_bytes')]"


class GuardianStringFlowTests(unittest.TestCase):
    def event(self, source: str, *, heredoc: bool = False) -> dict:
        command = ("python3 - <<'PY'\n" + source + "\nPY") if heredoc else shlex.join([
            "python3", "-B", "-c", source])
        return normalize_hook_event({"tool_name": "exec_command", "tool_input": {
            "cmd": command}}, phase="started", provider="codex")

    def test_business_file_read_reassign_write_preserves_local_effect(self):
        for source in (
            BOSS_SOURCE,
            BOSS_SOURCE.replace("from pathlib import Path", "import pathlib as pl").replace("Path(", "pl.Path("),
            BOSS_SOURCE.replace("read_text()", "read_text(encoding='utf-8')"),
            BOSS_SOURCE.replace("read_text", "read_bytes").replace("write_text", "write_bytes").replace("'before', 'after'", "b'before', b'after'"),
            "from pathlib import Path; p=Path('service.py'); s=p.read_text(); t=s; s=t.replace('a','b'); p.write_text(s)",
        ):
            for heredoc in (False, True):
                with self.subTest(source=source, heredoc=heredoc):
                    event = self.event(source, heredoc=heredoc)
                    self.assertEqual(event["effect"], "local_write")
                    self.assertFalse(event.get("invocation_violation"))

    def test_path_alias_has_no_destructive_receiver_violation(self):
        source = BOSS_SOURCE.replace("from pathlib import Path", "from pathlib import Path as P").replace("Path(", "P(")
        self.assertEqual(_python_source_effect(source, cwd=None), "local_write")
        event = self.event(source)
        self.assertFalse(event.get("invocation_violation"))
        # Existing write-target extraction does not resolve this constructor
        # alias; that uncertainty is separate from a destructive-receiver denial.
        self.assertEqual(event["effect"], "unknown")
        self.assertEqual(event["uncertainty_kind"], "unresolved_local_write")

    def test_fresh_immutable_assignment_does_not_require_single_write_or_no_imports(self):
        for source in (
            "text='before'; text=text.replace('b','a'); text=text.replace('a','c'); print(text)",
            "import json; text='before'; print(text.replace('b','a'))",
            "import hashlib; text=b'abc'; text=text.replace(b'a',b'b',1); print(text)",
            "text=unknown; text='abc'; text=text.replace('a','b'); print(text)",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["effect"], "read")

    def test_literal_eager_comprehension_bindings(self):
        for source in (
            KEYS_SOURCE,
            "import json; " + KEYS_SOURCE,
            "[k.replace('_','-') for k in ['verified_count','retained_bytes']]",
            "{k.replace('_','-') for k in ('verified_count',)}",
            "{k.replace('_','-'): k.replace('_',':') for k in ('verified_count',)}",
            "[k.replace(b'_',b'-') for k in (b'verified_count',)]",
        ):
            with self.subTest(source=source):
                event = self.event(source)
                self.assertEqual(event["effect"], "read")
                self.assertFalse(event.get("invocation_violation"))

    def test_local_comprehension_proof_does_not_launder_opaque_script(self):
        for source in (
            "import importlib.util; load_stage(); " + KEYS_SOURCE,
            "for row in records:\n transform(row)\n values=" + KEYS_SOURCE,
        ):
            with self.subTest(source=source):
                event = self.event(source)
                self.assertEqual(event["effect"], "unknown")
                self.assertFalse(event.get("invocation_violation"))

    def test_unknown_rebinding_and_read_origins_do_not_gain_proof(self):
        for source in (
            "s='a'; s=other; s=s.replace('a','b')",
            "s='a'; s=other.read_text(); s=s.replace('a','b')",
            "from pathlib import Path; Path=other; s=Path('p').read_text(); s.replace('a','b')",
            "from pathlib import Path; p=Path('p'); p=other; s=p.read_text(); s.replace('a','b')",
            "from pathlib import Path; Path.read_text=other; s=Path('p').read_text(); s.replace('a','b')",
            "from pathlib import Path; p=Path('p'); mutate(); s=p.read_text(); s.replace('a','b')",
            "from pathlib import Path; s=Path('p').read_text(); obj.callback(s.replace('a','b'))",
            "from pathlib import Path; s=Path('p').read_text(); getter()(s.replace('a','b'))",
            "mutate(); from pathlib import Path; s=Path('p').read_text(); s.replace('a','b')",
            "from pathlib import Path; s=Path(pathlike).read_text(); s.replace('a','b')",
            "from pathlib import Path; s=Path('p').read_text(encoding=custom); s.replace('a','b')",
            "s='a'; print=mutate; print(); s.replace('a','b')",
            "s='a'; namespace.s=other; s.replace('a','b')",
            "s='a'; eval(code); s.replace('a','b')",
            "s='a'\nif flag:\n s=other\ns.replace('a','b')",
            "s='a'\nfor s in objects:\n s.replace('a','b')",
            "s='a'\ndef later():\n return s.replace('a','b')",
            "s='a'; later=lambda:s.replace('a','b')",
            "s='a'; deferred=(s.replace('a','b') for _ in (1,))",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["invocation_violation"]["kind"],
                                 "unresolved-destructive-receiver")

    def test_comprehensions_cannot_borrow_unknown_or_mutated_target(self):
        for source in (
            "[k.replace('a','b') for k in values]",
            "[k.replace('a','b') for k in ('a', other)]",
            "[k.replace('a','b') for k in ('a', b'a')]",
            "[k.replace('a','b') for k in ('a',) if mutate()]",
            "[(mutate(), k.replace('a','b')) for k in ('a',)]",
            "[k.replace('a','b') for k in ('a',) for k in others]",
            "(k.replace('a','b') for k in ('a',))",
            "[lambda:k.replace('a','b') for k in ('a',)]",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["invocation_violation"]["kind"],
                                 "unresolved-destructive-receiver")

    def test_effectful_arguments_and_other_calls_remain_visible(self):
        for source in (
            BOSS_SOURCE + "; receiver.remove('unknown')",
            "s='a'; s=s.replace('a','b', count)",
            "s='a'; s=s.replace(other,'b')",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["invocation_violation"]["kind"],
                                 "unresolved-destructive-receiver")
        for source in (
            "from pathlib import Path; s=Path('p').read_text(); s=s.replace('a','b'); Path('p').replace('q')",
            "import os; s='a'; s=s.replace(str(os.remove('p')),'b')",
            "import os; [k.replace('a',str(os.remove('p'))) for k in ('a',)]",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["effect"], "destructive")

    def test_deferred_scope_does_not_borrow_eager_scope(self):
        tree = ast.parse("s='a'; s=s.replace('a','b')\ndef later():\n return s.replace('a','b')")
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        proved = proven_data_method_calls(tree)
        self.assertIn(id(calls[0]), proved)
        self.assertNotIn(id(calls[1]), proved)

    def test_forward_proof_is_bounded_and_has_no_cross_call_facts(self):
        large = ast.parse("values=[" + ",".join("'a'" for _ in range(20001)) + "]")
        self.assertEqual(proven_string_method_calls(large), set())
        self.assertTrue(proven_string_method_calls(ast.parse("s='a'; s=s.replace('a','b')")))
        self.assertEqual(proven_string_method_calls(ast.parse("s.replace('a','b')")), set())


@unittest.skipIf(os.name == "nt", "Native Windows acceptance remains Windows-owned")
@unittest.skipUnless(shutil.which("codex"), "Native Codex CLI required")
class GuardianStringFlowNativeTests(unittest.TestCase):
    def test_real_candidate_business_shapes_and_retained_pre_denial(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "scripts/release"))
        import candidate_codex_plugin as candidate
        from native_pretool_canary import NativeCanary
        with tempfile.TemporaryDirectory(prefix="sulde-string-native-") as temporary:
            slot = Path(temporary).resolve()
            installer = candidate.installer
            codex = shutil.which("codex")
            prepared = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = prepared.descriptor["delivery_generation"]["generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            # Capture before candidate env stripping, as the supported native
            # fixture does: macOS cannot nest the outer OS test sandbox.
            externally_isolated = bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, prepared.marketplace, runner,
                    expected_version=prepared.descriptor["delivery_generation"]["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                installer._install_launchers(installed, kb, runner, platform="posix")
                installer._smoke_installed(installed, kb, codex=codex,
                    expected_tree_sha256=prepared.plugin_tree_sha256, runner=runner)
                module = "runtime/scripts/kb/python_string_flow.py"
                self.assertEqual((installed / module).read_bytes(), (root / "scripts/kb/python_string_flow.py").read_bytes())
                workspace = Path(env["SULDE_HOME"]) / "string-flow-canary"
                workspace.mkdir()
                fixture = workspace / "service.py"
                fixture.write_text("before\n", encoding="utf-8")
                protected = workspace / "replace-source.txt"
                destination = workspace / "replace-destination.txt"
                protected.write_text("preserve\n", encoding="utf-8")
                guardian = Path(env["SULDE_HOME"]) / "bin/intent-guardian"
                host = NativeCanary(codex, workspace, env,
                                    externally_isolated=externally_isolated)
                with host.start():
                    contract, activation = candidate._activate_candidate_enforce_contract(
                        guardian, kb_home=kb, workspace=workspace, session=host.session,
                        environment=env, runner=runner)
                    control = {**env, "CODEX_THREAD_ID": host.session}

                    def control_call(action, *arguments):
                        return candidate._parse_json_result(runner(
                            [sys.executable, str(guardian), action, *arguments, "--provider", "codex",
                             "--session-id", host.session, "--contract", str(contract)],
                            environment=control, timeout=30), label=action)

                    probe = control_call("pre-execution-proof-prepare")
                    commands = [shlex.join([sys.executable, "-B", "-c", BOSS_SOURCE]),
                                shlex.join([sys.executable, "-B", "-c", "print(" + KEYS_SOURCE + ")"]),
                                probe["command"], shlex.join([sys.executable, "-B", "-c",
                                    "from pathlib import Path; Path('replace-source.txt').replace('replace-destination.txt')"])]
                    items = host.execute(commands)
                    proof = control_call("pre-execution-proof-finalize", "--probe-id", probe["probe_id"])
                if fixture.read_text(encoding="utf-8") != "after\n":
                    fixture_outputs = []
                    for log in (Path(env["CODEX_HOME"]) / "sessions").rglob("*.jsonl"):
                        for line in log.read_text(encoding="utf-8").splitlines():
                            row = json.loads(line)
                            payload = row.get("payload", {})
                            if row.get("type") == "response_item" and payload.get("type") == "function_call_output":
                                fixture_outputs.append(str(payload.get("output", ""))[-2000:])
                    print("STRING_FLOW_NATIVE_FAILURE=" + json.dumps({
                        "fixture_outputs": fixture_outputs,
                        "items": [{key: item.get(key) for key in ("id", "exitCode", "status", "aggregatedOutput")}
                                  for item in items],
                        "items_observed": [row.get("params", {}).get("item", {}) for row in host.notifications
                                           if row.get("method") == "item/completed"],
                        "hooks": [{key: row["params"]["run"].get(key) for key in ("eventName", "status", "durationMs")}
                                  for row in host.notifications if row.get("method") == "hook/completed"]},
                        sort_keys=True)[-12000:], flush=True)
                self.assertEqual(fixture.read_text(encoding="utf-8"), "after\n")
                self.assertEqual(protected.read_text(encoding="utf-8"), "preserve\n")
                self.assertFalse(destination.exists())
                self.assertEqual(sum(item.get("exitCode") == 0 for item in items), 2)
                output = "".join(str(row.get("params", {}).get("delta") or "") for row in host.notifications
                                 if row.get("method") == "item/commandExecution/outputDelta")
                output += "".join(str(item.get("aggregatedOutput") or "") for item in items)
                self.assertIn("verified-count", output)
                self.assertEqual(proof["artifact_generation"], generation)
                self.assertEqual(proof["loaded_module_generation"], probe["loaded_module_generation"])
                self.assertEqual(proof["started_call_id"], "candidate_native_2")
                self.assertFalse(os.path.lexists(probe["target"]))
                audit = contract.with_name(contract.stem + ".events.jsonl")
                events = [candidate._guardian_audit_event(json.loads(line))
                          for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
                evidence = []
                # Successful reads intentionally use the non-material fast
                # path. Prove them by native Hook + output, not fabricated rows.
                # The canonical rm probe is a local-write event with a retained
                # destructive guard; the extra Path.replace is destructive.
                for index, effect in ((0, "local_write"), (2, "local_write"), (3, "destructive")):
                    matching = [event for event in events if event.get("call_id") == f"candidate_native_{index}"
                                and event.get("phase") == "started"]
                    self.assertEqual(len(matching), 1, json.dumps({"index": index, "events": [
                        {key: event.get(key) for key in ("call_id", "phase", "effect", "kind")}
                        for event in events]}, sort_keys=True))
                    event = matching[0]
                    self.assertEqual(event["effect"], effect)
                    self.assertEqual(event["loaded_module_generation"], proof["loaded_module_generation"])
                    self.assertEqual(event["artifact_generation"], generation)
                    self.assertEqual(event["session_id"], host.session)
                    self.assertEqual(event["supervision_status"], "live_verified")
                    evidence.append({key: event.get(key) for key in (
                        "event_id", "call_id", "effect", "phase", "supervision_status")})
                denials = [row for row in host.notifications if row.get("method") == "hook/completed"
                           and row["params"]["run"].get("eventName") == "preToolUse"
                           and row["params"]["run"].get("status") == "blocked"]
                self.assertEqual(len(denials), 2)
                self.assertEqual({row["params"]["run"]["id"].rsplit(":", 1)[-1] for row in denials},
                                 {"candidate_native_2", "candidate_native_3"})
                read_hooks = [row["params"]["run"] for row in host.notifications
                              if row.get("method") == "hook/completed"
                              and row["params"]["run"].get("eventName") == "preToolUse"
                              and row["params"]["run"]["id"].endswith(":candidate_native_1")]
                self.assertEqual(len(read_hooks), 1)
                self.assertEqual(read_hooks[0]["status"], "completed")
                print("STRING_FLOW_NATIVE_EVIDENCE=" + json.dumps({
                    "schema": "guardian-string-flow-native-v1", "transport": "codex-cli-app-server",
                    "executor": "unified_exec", "external_model_requests": 0,
                    "activation": activation, "artifact_generation": generation,
                    "loaded_module_generation": proof["loaded_module_generation"],
                    "proof_id": proof["proof_id"], "events": evidence,
                    "text_write_verified": True, "key_transform_verified": True,
                    "destructive_pre_denied": True, "path_replace_pre_denied": True,
                    "read_native_hook_completed": True, "marker_absent": True}, sort_keys=True), flush=True)


if __name__ == "__main__":
    unittest.main()
