from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "integrations/codex/plugins/sulde/scripts"
OBSERVER = SCRIPTS / "_hook_observer.py"
spec = importlib.util.spec_from_file_location("closure_observer", OBSERVER)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class HookObserverClosureTests(unittest.TestCase):
    def test_telemetry_hash_backend_matches_public_sha256_for_unicode_and_content(self):
        value = "session:生命体\n" * 100
        self.assertEqual(observer.digest(value), hashlib.sha256(value.encode()).hexdigest())
        path = self.root / "module.py"
        path.write_bytes(bytes(range(256)) * 40)
        self.assertEqual(observer.identity(path), hashlib.sha256(path.read_bytes()).hexdigest())

    @unittest.skipIf(os.name == "nt", "POSIX in-process entry; Windows pending")
    def test_owned_python_entry_preserves_outputs_failures_and_never_repeats(self):
        script = self.root / "adapter.py"
        counter = self.root / "count"
        script.write_text("import json,sys\nfrom pathlib import Path\n"
                          "json.load(sys.stdin)\np=Path(" + repr(str(counter)) + ")\n"
                          "p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
                          "sys.stdout.buffer.write(b'output\\n')\nraise RuntimeError('PRIVATE_SENTINEL')\n")
        payload = json.dumps({"hook_event_name": "PostToolUse", "tool_use_id": "native-call", "tool_response": "", "session_id": "s"})
        argv = [sys.executable, "-B", str(SCRIPTS / "_hook_entry.py"), "sulde:fixture", "adapter", str(script)]
        result = subprocess.run(argv, input=payload, env=self.env, text=True, encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "output\n")
        self.assertEqual(counter.read_text(), "x")
        row, = self.rows()
        self.assertEqual(row["error_category"], "internal_exception")
        self.assertEqual(row["tool_result"], "success")
        self.assertEqual(row["business_effect"], "unverified")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(row))
        # Unavailable recorder cannot change a successful adapter into replay.
        broken = self.root / "broken"
        broken.write_text("file")
        script.write_text("print('normal')\n")
        result = subprocess.run(argv, input=payload, env={**self.env, "SULDE_KB_HOME": str(broken)}, text=True, encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "normal\n")
        self.assertIn("hook_observer_delivery_unavailable", result.stderr)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, "SULDE_HOME": str(self.root), "SULDE_KB_HOME": str(self.root / "kb"),
                    "PYTHONDONTWRITEBYTECODE": "1", "CODEX_THREAD_ID": "isolated-session"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_observer(self, command, call="c1", timeout=3):
        return subprocess.run([sys.executable, str(OBSERVER), "--hook", "fixture", "--stage", "adapter",
                               "--timeout", str(timeout), "--", *command],
                              input=json.dumps({"call_id": call, "session_id": "session-a", "cwd": str(self.root)}),
                              env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)

    def rows(self):
        return observer.read_rows(self.root / "kb")["rows"]

    def test_real_process_failures_and_normal(self):
        cases = [([sys.executable, str(self.root / "missing.py")], 2, "script_missing"),
                 ([str(self.root / "missing-python")], 127, "interpreter_or_executable_unavailable"),
                 ([sys.executable, "-c", "raise RuntimeError('PRIVATE_SECRET_SENTINEL')"], 1, "internal_exception"),
                 ([sys.executable, "-c", "import time; time.sleep(9)"], 124, "timeout"),
                 ([sys.executable, "-c", "print('normal')"], 0, "normal")]
        for index, (command, code, kind) in enumerate(cases):
            with self.subTest(kind=kind):
                result = self.run_observer(command, str(index), timeout=.15 if kind == "timeout" else 3)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(self.rows()[-1]["error_category"], kind)
        self.assertNotIn("PRIVATE_SECRET_SENTINEL", json.dumps(self.rows()))
        self.assertTrue(all(x["tool_result"] == "unknown" for x in self.rows()))

    def test_python_flags_preserve_available_module_identity_and_launch_failure_unknown(self):
        script = self.root / "script with spaces.py"
        script.write_text("raise SystemExit(1)\n")
        result = self.run_observer([sys.executable, "-I", "-B", str(script)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.rows()[0]["loaded_module_generation"], observer.identity(script))
        result = self.run_observer([str(self.root / "missing-python"), "-B", str(script)], "missing-interpreter")
        self.assertEqual(result.returncode, 127)
        self.assertEqual(self.rows()[-1]["loaded_module_generation"], "unknown")
        self.assertEqual(observer.command_module(["python3", "-c", str(script)]), "unknown")

    @unittest.skipIf(os.name == 'nt', 'POSIX owned entry')
    def test_loaded_identity_is_not_replaced_by_self_modified_script(self):
        script = self.root / 'changing.py'
        original = b"from pathlib import Path\nPath(__file__).write_text('# replacement\\n')\n"
        script.write_bytes(original)
        argv = [sys.executable, '-B', str(SCRIPTS / '_hook_entry.py'), 'fixture', 'adapter', str(script)]
        result = subprocess.run(argv, input='{}', env=self.env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        row, = self.rows()
        self.assertEqual(row['loaded_module_generation'], hashlib.sha256(original).hexdigest())
        self.assertNotEqual(row['loaded_module_generation'], observer.identity(script))

    def test_subprocess_replacement_cannot_claim_loaded_identity(self):
        script = self.root / 'changing-child.py'
        script.write_text("from pathlib import Path\nPath(__file__).write_text('# replacement\\n')\n")
        self.assertEqual(self.run_observer([sys.executable, '-B', str(script)]).returncode, 0)
        row, = self.rows()
        self.assertEqual(row['loaded_module_generation'], 'unknown')
        self.assertEqual(row['module_identity_status'], 'changed_during_execution')

    @unittest.skipIf(os.name == 'nt', 'POSIX owned entry')
    def test_artifact_replacement_is_unknown_not_a_mixed_identity(self):
        plugin = self.root / 'plugin'
        scripts = plugin / 'scripts'
        scripts.mkdir(parents=True)
        for name in ('_hook_entry.py', '_hook_observer.py'):
            shutil.copy2(SCRIPTS / name, scripts / name)
        manifest = plugin / '.codex-plugin/generation.json'
        manifest.parent.mkdir()
        manifest.write_text('generation-A')
        script = scripts / 'adapter.py'
        script.write_text('from pathlib import Path\nPath(' + repr(str(manifest)) + ").write_text('generation-B')\n")
        result = subprocess.run([sys.executable, '-B', str(scripts / '_hook_entry.py'), 'fixture', 'adapter', str(script)],
                                input='{}', env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        row, = self.rows()
        self.assertEqual(row['artifact_generation'], 'unknown')
        self.assertEqual(row['artifact_identity_status'], 'changed_during_execution')
        self.assertEqual(row['loaded_module_generation'], observer.identity(script))

    def test_posttool_runtime_replacement_keeps_effect_unknown(self):
        plugin = self.root / 'runtime-fixture'
        shutil.copytree(SCRIPTS, plugin / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        runtime = plugin / 'runtime'
        (runtime / 'hooks').mkdir(parents=True)
        (runtime / 'scripts/kb').mkdir(parents=True)
        target = runtime / 'hooks/post_tool_use.py'
        target.write_text("from pathlib import Path\nPath(__file__).write_text('# replacement\\n')\nraise SystemExit(1)\n")
        payload = json.dumps({'hook_event_name': 'PostToolUse', 'tool_use_id': 'runtime-replacement',
                              'tool_response': '', 'session_id': 'fixture'})
        result = subprocess.run([sys.executable, '-B', str(plugin / 'scripts/post-tool-use.py')],
                                input=payload, env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        row, = self.rows()
        self.assertEqual(row['loaded_module_generation'], 'unknown')
        self.assertEqual(row['module_identity_status'], 'changed_during_execution')
        self.assertEqual(row['business_effect'], 'unverified')

    def test_native_notification_keeps_absent_exit_and_module_unknown(self):
        event = {"method": "hook/completed", "params": {"threadId": "thread", "turnId": None,
                 "run": {"id": "real-run-id", "status": "failed", "eventName": "sessionStart", "source": "project",
                         "sourcePath": "/private/project/hooks.json", "displayOrder": 1, "completedAt": 1788778916,
                         "entries": [{"kind": "error", "text": "PRIVATE_SENTINEL"}], "statusMessage": "PRIVATE_SENTINEL"}}}
        for _ in range(2):
            result = subprocess.run([sys.executable, "-B", str(OBSERVER), "--ingest-codex-notification", "--workspace", str(self.root)],
                                    input=json.dumps(event), env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
        row, = self.rows()
        self.assertIsNone(row["exit_code"])
        self.assertEqual(row["loaded_module_generation"], "unknown")
        self.assertEqual(row["tool_result"], "unknown")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(row))
        self.assertNotIn("/private/project", json.dumps(row))
        self.assertTrue(row["at"].startswith("2026-09-07"))
        event["params"]["run"]["entries"] = [{"kind": "error", "text": "hook exited with code 1"}]
        actual = observer.codex_notification(event, str(self.root))
        self.assertEqual(actual["exit_code"], 1)
        event["params"]["turnId"] = "new-turn-on-resume"
        resumed = observer.codex_notification(event, str(self.root))
        self.assertNotEqual(actual["id"], resumed["id"])
        self.assertEqual(actual["fingerprint"], resumed["fingerprint"])

    def test_recorder_unavailable_does_not_repeat_or_change_tool_result(self):
        sentinel = self.root / "effect-count"
        (self.root / "kb").write_text("not a directory")
        command = [sys.executable, "-c", "from pathlib import Path; p=Path(" + repr(str(sentinel)) + "); p.write_text(p.read_text()+'x' if p.exists() else 'x'); print('success')"]
        result = self.run_observer(command)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "x")
        self.assertIn("hook_observer_delivery_unavailable", result.stderr)
        self.assertEqual(result.stdout.strip(), "success")

    def test_policy_denial_is_not_exception_and_ingestion_is_idempotent(self):
        output = json.dumps({"hookSpecificOutput": {"permissionDecision": "deny"}})
        result = self.run_observer([sys.executable, "-c", "print(" + repr(output) + "); raise SystemExit(2)"])
        self.assertEqual(result.returncode, 2)
        row = self.rows()[0]
        self.assertEqual(row["permission_decision"], "deny")
        self.assertEqual(row["error_category"], "policy_rejection")
        self.assertTrue(observer.record(row, self.root / "kb"))
        self.assertEqual(len(self.rows()), 1)

    def test_capacity_and_worktree_session_identity(self):
        row = observer.facts(hook="fixture", stage="host", payload={"session_id": "one", "cwd": "/a", "call_id": "one"}, code=1, kind="nonzero_exit")
        self.assertTrue(observer.record(row, self.root / "kb"))
        before = observer.CAPACITY
        try:
            observer.CAPACITY = 1
            other = observer.facts(hook="fixture", stage="host", payload={"session_id": "two", "cwd": "/b", "call_id": "one"}, code=1, kind="nonzero_exit")
            self.assertNotEqual(row["lane_id"], other["lane_id"])
            self.assertFalse(observer.record(other, self.root / "kb"))
        finally:
            observer.CAPACITY = before
        self.assertEqual(len(self.rows()), 1)

    def test_host_result_import_drops_raw_content_and_never_claims_effect(self):
        event = {"schema": "sulde-normalized-host-hook-result-v1", "hook_id": "project:missing-script", "exit_code": 1,
                 "error_category": "script_missing", "call_id": "host-call", "session_id": "actual-host-session",
                 "tool_result": "success", "stdout": "PRIVATE_SENTINEL", "prompt": "PRIVATE_SENTINEL"}
        for _ in range(2):
            result = subprocess.run([sys.executable, str(OBSERVER), "--ingest-host-result"], input=json.dumps(event), env=self.env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["tool_result"], "unknown")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(self.rows()))

    @unittest.skipIf(os.name == "nt", "POSIX wrapper; Windows runner must validate PowerShell")
    def test_actual_wrapper_with_missing_adapter_no_guardian_contract(self):
        scripts = self.root / "plugin/scripts"
        scripts.mkdir(parents=True)
        for name in ("run-hook.sh", "_hook_observer.py"):
            shutil.copy2(SCRIPTS / name, scripts / name)
        result = subprocess.run(["bash", str(scripts / "run-hook.sh"), "post-tool-use"], input='{"call_id":"wrapper-call","session_id":"old"}',
                                env=self.env, cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.rows()[0]["exit_code"], 2)
        self.assertEqual(self.rows()[0]["error_category"], "script_missing")
        self.assertIn("degraded_to_native_codex", result.stderr)

    def test_real_help_does_not_install_and_writer_remains_sealed(self):
        sys.path.insert(0, str(ROOT / "scripts/kb"))
        from intent_guardian_parts.resource_preflight import codex_plugin_read_only_maintenance_command, unsealed_sulde_maintenance_invocation
        for name in ("bootstrap.sh", "install-agents.sh"):
            script = ROOT / "scripts/kb" / name
            command = f"bash {script} --help"
            self.assertTrue(codex_plugin_read_only_maintenance_command(command, cwd=ROOT))
            self.assertIsNone(unsealed_sulde_maintenance_invocation(command, cwd=ROOT))
            result = subprocess.run(["bash", str(script), "--help"], env=self.env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.root / "kb").exists())
            self.assertIsNotNone(unsealed_sulde_maintenance_invocation(f"bash {script}", cwd=ROOT))


if __name__ == "__main__":
    unittest.main()
