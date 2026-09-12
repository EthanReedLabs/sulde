"""Isolated candidate journey. Hook subprocesses are NOT live native UI evidence."""
from __future__ import annotations

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
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
import launcher_contract as lc
from production_recovery_readiness import provision_recovery_key, observe_recovery_truth
from production_recovery_control import ProductionRecoveryControl, parse_command, route_native_recovery
from production_recovery_targets import RepairTarget, ProductionRepairAdapter, ProductionRepairVerifier
from recovery_lane import RecoveryLaneError


class ProductionRecoveryControlTests(unittest.TestCase):
    def test_shared_parser_preserves_quotes_spaces_and_exact_authority(self):
        runtime = self.base / "runtime with spaces"
        workspace = self.base / "workspace with 'quote'"
        workspace.mkdir()
        argv = [sys.executable, "-B", str(runtime / "scripts/kb/production-recovery.py"),
                "status", "--workspace", str(workspace), "--session-id", "session", "--intent-id", "intent"]
        command = shlex.join(argv)
        parsed = parse_command(command, runtime)
        self.assertEqual(parsed["workspace"], str(workspace))
        self.assertEqual(parsed["operation"], "status")
        bad = [command + suffix for suffix in (
            "; echo injected", " && echo injected", " | cat", " > output", "\ntrue",
            " $(touch injected)", " `touch injected`", " <(true)", " --intent-id other",
            " --extra value", "\0", "\x1b", " '",
        )]
        bad += [command.replace("status", "execute", 1),
                command.replace("-B", "-c", 1), "env " + command,
                command.replace(str(sys.executable), "/untrusted/python3", 1), None, "x" * 65537]
        for value in bad:
            with self.subTest(command=repr(value)[:120]):
                self.assertIsNone(parse_command(value, runtime))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "sulde"
        self.runtime = self.base / "plugin" / "runtime"
        self.workspace = self.base / "task-worktree"
        self.session_cwd = self.base / "session-cwd"
        self.workspace.mkdir()
        self.session_cwd.mkdir()
        scripts = self.runtime / "scripts" / "kb"
        scripts.mkdir(parents=True)
        for filename in (
            "production-recovery.py", "production_recovery_control.py",
            "production_recovery_readiness.py", "production_recovery_targets.py",
            "recovery_lane.py", "supervisor_state.py", "sulde_paths.py", "launcher_contract.py", "command_template.py",
        ):
            shutil.copy2(ROOT / "scripts" / "kb" / filename, scripts / filename)
        plugin = self.runtime.parent
        shutil.copytree(ROOT / "integrations/codex/plugins/sulde/scripts", plugin / "scripts")
        for relative in lc.CODEX_HOOK_SURFACE:
            path = plugin / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}' if path.suffix == '.json' else '# isolated hook fixture\n')
        for spec in lc.LAUNCHERS:
            target = self.runtime / spec.target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text("print('original-task-continued')\n")
        for prefix in lc.RUNTIME_CODE_PREFIXES:
            directory = self.runtime / prefix
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "isolated_fixture.py").write_text("# isolated fixture\n")
        descriptor = plugin / ".codex-plugin" / "generation.json"
        tree = lc.runtime_tree_digest(self.runtime)
        descriptor.write_text(json.dumps({
            "schema": lc.DELIVERY_GENERATION_SCHEMA, "schema_version": 1,
            "provider": "codex", "plugin_version": "test", "runtime_tree_sha256": tree,
            "generation": f"test:{tree}",
        }))
        lc.install_launchers(self.home, self.runtime)
        provision_recovery_key(self.home)
        self.control = ProductionRecoveryControl(self.home, self.runtime)
        self.launcher = self.home / "bin" / "intent-guardian"
        self.original = self.launcher.read_bytes()
        self.launcher.write_text("raise SystemExit(91)\n")
        self.environment = {**os.environ, "SULDE_HOME": str(self.home),
                            "SULDE_KB_HOME": str(self.home), "CODEX_THREAD_ID": "isolated-session",
                            "SULDE_SOURCE_ROOT": str(self.runtime),
                            "SULDE_CODEX_FALLBACK_ONLY": "1", "PYTHONDONTWRITEBYTECODE": "1"}

    def tearDown(self):
        self.control.close()
        self.temp.cleanup()

    def prepare(self, action="repair_launcher", target="intent-guardian"):
        return self.control.prepare(action=action, target=target,
                                    workspace=str(self.workspace), session_id="isolated-session",
                                    intent_id="isolated-task")

    def spec(self, preview):
        return parse_command(shlex.join(preview["command_argv"]), self.runtime)

    def payload(self, preview, *, event="PermissionRequest"):
        payload = {"client": "codex", "session_id": "isolated-session",
                "cwd": str(self.session_cwd), "permission_mode": "default",
                "tool_name": "exec_command", "tool_input": {
                    "cmd": shlex.join(preview["command_argv"])}}
        # Do not give the pre-event the later approval surface's context.
        # These are constructed stage fixtures, not captured live host payloads.
        if event == "PermissionRequest":
            payload["tool_input"]["justification"] = preview["description"]
        return payload

    def hook(self, payload, event):
        script = "post-tool-use.py" if event == "PostToolUse" else "pre-tool-use.py"
        result = subprocess.run(
            [sys.executable, "-B", str(self.runtime.parent / "scripts" / script)],
            input=json.dumps(payload), text=True, encoding="utf-8", errors="replace", capture_output=True,
            env={**self.environment, "SULDE_CODEX_HOOK_EVENT": event}, cwd=self.session_cwd,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_candidate_journey_uses_actual_hook_executor_verifier_and_continues_task(self):
        before = subprocess.run([sys.executable, "-B", str(self.launcher)], capture_output=True)
        self.assertEqual(before.returncode, 91)
        ordinary = self.hook({"tool_name": "exec_command", "tool_input": {"cmd": "touch ordinary"}}, "PreToolUse")
        self.assertEqual(json.loads(ordinary.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        preview = self.prepare()
        payload = self.payload(preview)
        self.assertEqual(self.hook(self.payload(preview, event="PreToolUse"), "PreToolUse").stdout, "")
        denied = subprocess.run(preview["command_argv"], env=self.environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("no paired live", denied.stdout)
        self.assertEqual(self.hook(payload, "PermissionRequest").stdout, "")
        # This subprocess models execution AFTER Allow. It does not claim a
        # human saw or clicked the UI during an automated test.
        result = subprocess.run(preview["command_argv"], env=self.environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["recovery_verified"])
        post = self.hook(payload, "PostToolUse")
        post_context = json.loads(json.loads(post.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertTrue(post_context["recovery_verified"])
        self.assertEqual(post_context["effect_owner"], "independent_recovery_journal")
        self.assertEqual(self.launcher.read_bytes(), self.original)
        resumed = subprocess.run([sys.executable, "-B", str(self.launcher)], env=self.environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn("original-task-continued", resumed.stdout)
        replay = subprocess.run(preview["command_argv"], env=self.environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        starts = self.control.lane._payloads("recovery_dispatch_started")
        self.assertEqual(len(starts), 1)
        status = self.control.status(self.spec(preview))
        self.assertTrue(status["recovery_verified"])
        foreign = self.control.status({**self.spec(preview), "session_id": "another-session"})
        self.assertEqual(foreign["runs"], [])
        self.assertFalse(foreign["recovery_verified"])
        self.launcher.write_text("# later damage\n")
        stale = subprocess.run(preview["command_argv"], env=self.environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertFalse(json.loads(stale.stdout)["recovery_verified"])
        self.assertFalse(self.control.status(self.spec(preview))["recovery_verified"])
        self.assertEqual(self.launcher.read_text(), "# later damage\n")

    def test_pretool_without_approval_text_defers_without_creating_authority(self):
        preview = self.prepare()
        before = self.control.lane.state.snapshot_read_only()
        for context in ({}, {"description": "Run recovery command"},
                        {"justification": "not the later approval card"}):
            with self.subTest(context=context):
                payload = self.payload(preview, event="PreToolUse")
                payload["tool_input"].update(context)
                self.assertEqual(self.hook(payload, "PreToolUse").stdout, "")
                self.assertEqual(self.control.lane.state.snapshot_read_only(), before)
        denied = subprocess.run(preview["command_argv"], env=self.environment,
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("no paired live", denied.stdout)
        self.assertEqual(self.control.lane.state.snapshot_read_only(), before)

    def test_permission_request_requires_exact_text_and_interactive_mode(self):
        preview = self.prepare()
        before = self.control.lane.state.snapshot_read_only()
        for context in ({}, {"justification": ""}, {"justification": None},
                        {"justification": preview["description"] + " altered"},
                        {"description": "different card", "justification": preview["description"]}):
            with self.subTest(context=context):
                payload = self.payload(preview, event="PreToolUse")
                payload["tool_input"].update(context)
                result = self.hook(payload, "PermissionRequest")
                decision = json.loads(result.stdout)["hookSpecificOutput"]["decision"]
                self.assertEqual(decision["behavior"], "deny")
                self.assertIn("description differs", decision["message"])
                self.assertEqual(self.control.lane.state.snapshot_read_only(), before)
        for mode in (None, "", "bypassPermissions"):
            payload = self.payload(preview)
            payload["permission_mode"] = mode
            result = self.hook(payload, "PermissionRequest")
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")
        self.assertEqual(self.control.lane.state.snapshot_read_only(), before)
        # Either supported text field can carry the exact card at this stage.
        payload = self.payload(preview)
        payload["tool_input"]["description"] = payload["tool_input"].pop("justification")
        self.assertEqual(self.hook(payload, "PermissionRequest").stdout, "")
        self.assertEqual(len(self.control._rows("production_recovery_prompt")), 1)
        self.assertEqual(self.control._rows("human_decision_recorded"), [])
        self.assertEqual(self.control._rows("recovery_dispatch_started"), [])

    def test_pretool_still_rejects_wrong_identity_command_expiry_and_target_drift(self):
        preview = self.prepare()
        spec = self.spec(preview)
        before = self.control.lane.state.snapshot_read_only()
        for field, value in (("client", "claude"), ("session_id", "foreign")):
            payload = self.payload(preview, event="PreToolUse")
            payload[field] = value
            with self.assertRaises(RecoveryLaneError):
                self.control.observe(payload, spec, "PreToolUse")
        for field in ("workspace", "session_id", "intent_id", "capability_id"):
            with self.subTest(field=field), self.assertRaises(RecoveryLaneError):
                self.control.observe(self.payload(preview, event="PreToolUse"),
                                     {**spec, field: "foreign"}, "PreToolUse")
        payload = self.payload(preview, event="PreToolUse")
        payload["tool_input"]["cmd"] += " --extra value"
        with self.assertRaisesRegex(RecoveryLaneError, "command differs"):
            self.control.observe(payload, spec, "PreToolUse")
        with mock.patch.object(self.control.lane, "wall_clock",
                               return_value=preview["card"]["expires_at"] + 1):
            with self.assertRaises(RecoveryLaneError):
                self.control.observe(self.payload(preview, event="PreToolUse"), spec, "PreToolUse")
        self.launcher.write_text("# third-party target change\n")
        with self.assertRaises(RecoveryLaneError):
            self.control.observe(self.payload(preview, event="PreToolUse"), spec, "PreToolUse")
        self.assertEqual(self.control.lane.state.snapshot_read_only(), before)

    def test_pretool_still_rejects_generation_drift_without_approval_text(self):
        preview = self.prepare()
        (self.runtime / "source-drift").write_text("drift")
        result = self.hook(self.payload(preview, event="PreToolUse"), "PreToolUse")
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("source generation drifted", decision["permissionDecisionReason"])
        self.assertEqual(self.control._rows("production_recovery_prompt"), [])

    def test_non_dictionary_tool_input_is_not_a_recovery_request(self):
        before = self.control.lane.state.snapshot_read_only()
        for field in ("tool_input", "toolInput"):
            for value in ('text(1);', ["command"], 1, True, None, ""):
                for event in ("PreToolUse", "PermissionRequest", "PostToolUse"):
                    with self.subTest(field=field, value=value, event=event):
                        self.assertIsNone(route_native_recovery(
                            {"toolName": "functions.exec", field: value},
                            runtime=self.runtime, event=event,
                        ))
        self.assertEqual(self.control.lane.state.snapshot_read_only(), before)

    def test_string_wrapper_reaches_ordinary_pre_and_post_adapter_routes(self):
        # Real adapter subprocesses with observable ordinary-runtime fixtures.
        # This proves routing, not a live host decision or full policy proof.
        source = 'const r = await tools.exec_command({cmd:"touch scoped-marker"}); text(r);'
        self.environment["SULDE_CODEX_FALLBACK_ONLY"] = "0"
        before = self.control.lane.state.snapshot_read_only()
        for event, filename in (("PreToolUse", "pre_tool_use.py"),
                                ("PostToolUse", "post_tool_use.py")):
            expected = ({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                         "permissionDecision": "deny",
                         "permissionDecisionReason": "ordinary-policy-route"}}
                        if event == "PreToolUse" else "ordinary-audit-route")
            output = json.dumps(expected) if isinstance(expected, dict) else expected
            (self.runtime / "hooks" / filename).write_text(
                "import json, sys\n"
                "payload = json.load(sys.stdin)\n"
                f"assert payload['tool_input'] == {source!r}\n"
                f"print({output!r})\n"
            )
            observed = self.hook({"toolName": "functions.exec", "toolInput": source}, event)
            self.assertNotIn("AttributeError", observed.stderr)
            result = json.loads(observed.stdout)["hookSpecificOutput"]
            self.assertEqual(result["hookEventName"], event)
            if event == "PreToolUse":
                self.assertEqual(result["permissionDecision"], "deny")
                self.assertEqual(result["permissionDecisionReason"], "ordinary-policy-route")
            else:
                self.assertEqual(result["additionalContext"], "ordinary-audit-route")
        self.assertEqual(self.control.lane.state.snapshot_read_only(), before)

    def test_foreign_identity_stale_card_generation_and_permission_modes_fail_closed(self):
        preview = self.prepare()
        for mutation in ("session", "description", "mode"):
            payload = self.payload(preview)
            if mutation == "session": payload["session_id"] = "foreign"
            if mutation == "description": payload["tool_input"]["justification"] += " altered"
            if mutation == "mode": payload["permission_mode"] = "bypassPermissions"
            result = self.hook(payload, "PermissionRequest")
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")
        spec = self.spec(preview)
        for field in ("workspace", "session_id", "intent_id"):
            forged = {**spec, field: "foreign"}
            with self.assertRaises(RecoveryLaneError): self.control.validate(forged)
        (self.runtime / "source-drift").write_text("drift")
        with self.assertRaisesRegex(RecoveryLaneError, "source generation drifted"):
            self.control.validate(spec)

    def test_corrupt_recovery_ledger_is_not_ready_and_never_rewritten(self):
        self.prepare()
        path = self.home / "state" / "recovery-lane.jsonl"
        with path.open("ab") as stream: stream.write(b"{torn")
        before = path.read_bytes()
        truth = observe_recovery_truth(self.home)
        self.assertFalse(truth["lane_available"])
        self.assertTrue(truth["diagnosis_available"])
        self.assertFalse(truth["recovery_verified"])
        self.assertEqual(path.read_bytes(), before)

    def test_binary_key_whitespace_is_preserved(self):
        from production_recovery import _seal_key
        key = self.home / "control" / "recovery.key"
        raw = b"\n" + b"a" * 30 + b" "
        key.write_bytes(raw)
        self.assertEqual(_seal_key(key), raw)

    def test_unsupported_debt_actions_never_manufacture_effect_truth(self):
        for state in ("verifying", "unknown", "corrupt"):
            ledger = self.workspace / "debt.jsonl"
            ledger.write_text(state)
            for action in ("settle", "abort", "uninstall", "rollback"):
                with self.assertRaisesRegex(RecoveryLaneError, "no production adapter"):
                    self.prepare(action=action)
            self.assertEqual(ledger.read_text(), state)

    def test_bytecode_repair_preserves_sources_and_backups(self):
        self.launcher.write_bytes(self.original)
        cache = self.runtime / "scripts/kb/__pycache__"
        cache.mkdir()
        (cache / "candidate.pyc").write_bytes(b"isolated-generated-bytecode")
        preview = self.prepare("repair_generated_bytecode", "runtime-bytecode")
        self.hook(self.payload(preview), "PermissionRequest")
        with mock.patch.dict(os.environ, self.environment):
            result = self.control.execute(self.spec(preview))
        self.assertTrue(result["recovery_verified"], result)
        self.assertFalse(cache.exists())
        self.assertEqual(lc.delivery_generation(self.runtime)["generation"], preview["card"]["installed_generation"])
        backups = list((self.home / "state/recovery-backups").glob("*/0"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"isolated-generated-bytecode")

    def test_adapter_failure_rolls_back_and_independent_verifier_checks_original(self):
        preview = self.prepare()
        self.hook(self.payload(preview), "PermissionRequest")
        row, target = self.control.validate(self.spec(preview))
        adapter = ProductionRepairAdapter(target)
        request = {"expected_pre_state": row["capability"]["expected_pre_state"],
                   "run_id": "sha256:" + "a" * 64, "effect_id": "sha256:" + "b" * 64,
                   "action": "repair_launcher", "target_identity": "intent-guardian"}
        damaged = self.launcher.read_bytes()
        with mock.patch.object(target, "passed", side_effect=RecoveryLaneError("injected readback failure")):
            result = adapter.repair_launcher(request)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.launcher.read_bytes(), damaged)
        verifier = ProductionRepairVerifier(RepairTarget(self.home, self.runtime, "repair_launcher", "intent-guardian"))
        receipt = verifier.verify({**request, "adapter_result": result, "result_identity": "sha256:" + "c" * 64})
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(receipt["evidence"]["original_restored"])

    def test_helper_drift_outside_frozen_install_does_not_invalidate_repair(self):
        preview = self.prepare()
        helper = self.base / "codex" / "helper.py"
        helper.parent.mkdir()
        helper.write_text("# later host helper generation\n")
        self.control.validate(self.spec(preview))
        self.hook(self.payload(preview), "PermissionRequest")
        with mock.patch.dict(os.environ, self.environment):
            result = self.control.execute(self.spec(preview))
        self.assertTrue(result["recovery_verified"])

    def test_bytecode_failure_restores_frozen_directory_permissions(self):
        cache = self.runtime / "scripts/kb/__pycache__"
        cache.mkdir(mode=0o750)
        cache.chmod(0o750)
        (cache / "candidate.pyc").write_bytes(b"rollback-generated-bytecode")
        preview = self.prepare("repair_generated_bytecode", "runtime-bytecode")
        row, target = self.control.validate(self.spec(preview))
        before = row["capability"]["expected_pre_state"]
        request = {"expected_pre_state": before,
                   "run_id": "sha256:" + "a" * 64, "effect_id": "sha256:" + "b" * 64,
                   "action": "repair_generated_bytecode", "target_identity": "runtime-bytecode"}
        with mock.patch.object(target, "passed", side_effect=RecoveryLaneError("injected failure")):
            result = ProductionRepairAdapter(target).repair_generated_bytecode(request)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(target.snapshot(), before)
        self.assertEqual(cache.stat().st_mode & 0o777, 0o750)

    def test_legacy_denial_is_not_native_confirmation(self):
        # A synthetic legacy adapter has denial output but no native recovery
        # pairing capability. Its output is NOT real-host enforcement evidence.
        # The real production control below must still reject unpaired execution.
        adapter = self.runtime.parent / "scripts/pre-tool-use.py"
        adapter.write_text(
            "import json, sys\njson.load(sys.stdin)\n"
            "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', "
            "'permissionDecision': 'deny', 'permissionDecisionReason': 'synthetic legacy adapter'}}))\n",
            encoding="utf-8")
        preview = self.prepare()
        blocked = self.hook(self.payload(preview), "PreToolUse")
        self.assertEqual(json.loads(blocked.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.control._rows("production_recovery_prompt"), [])
        with mock.patch.dict(os.environ, self.environment):
            with self.assertRaisesRegex(RecoveryLaneError, "no paired live"):
                self.control.execute(self.spec(preview))

    def test_crash_after_apply_reprobes_without_repeating_repair(self):
        preview = self.prepare()
        self.hook(self.payload(preview), "PermissionRequest")
        def crash(boundary):
            if boundary == "after_adapter": raise RuntimeError("isolated crash")
        self.control.lane._failpoint = crash
        with mock.patch.dict(os.environ, self.environment):
            interrupted = self.control.execute(self.spec(preview))
            self.assertFalse(interrupted["recovery_verified"])
            self.control.lane._failpoint = lambda _boundary: None
            repaired = self.control.execute(self.spec(preview))
        self.assertTrue(repaired["recovery_verified"])
        self.assertEqual(len(list((self.home / "state/recovery-backups").glob("*/manifest.json"))), 1)
        self.assertEqual([r["mode"] for r in self.control.lane._payloads("recovery_dispatch_started")],
                         ["apply", "reprobe"])

    def test_symlink_and_composed_commands_never_expand_repair_target(self):
        preview = self.prepare()
        command = shlex.join(preview["command_argv"])
        self.assertIsNone(parse_command(command + "; touch /tmp/forbidden", self.runtime))
        self.assertIsNone(parse_command(command.replace(preview["command_argv"][0], "/tmp/python3"), self.runtime))
        self.launcher.unlink()
        self.launcher.symlink_to(self.workspace / "user-file")
        (self.workspace / "user-file").write_text("preserve\n")
        with self.assertRaises(RecoveryLaneError): self.control.validate(self.spec(preview))
        self.assertEqual((self.workspace / "user-file").read_text(), "preserve\n")


if __name__ == "__main__":
    unittest.main()
