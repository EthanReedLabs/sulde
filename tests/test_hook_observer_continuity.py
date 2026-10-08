"""Real POSIX wrapper; inject only the external bridge/filesystem boundary.

Set SULDE_CONTINUITY_TEST_SCRIPTS to run identical assertions on a baseline.
These fixtures never execute the tool payload or claim live host acceptance.
"""
import hashlib
import importlib.util
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
SCRIPTS = Path(os.environ.get("SULDE_CONTINUITY_TEST_SCRIPTS", str(
    ROOT / "integrations/codex/plugins/sulde/scripts")))


@unittest.skipIf(os.name == "nt", "POSIX wrapper; Windows not verified")
class ObserverContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def case(self, name, *, disappear=False, tool="Read", command="", broken_store=False,
             missing_observer=False, missing_classifier=False, session="session-one",
             bridge_unavailable=False):
        root = self.root / name
        scripts = root / "plugin/scripts"
        shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
        if missing_observer:
            (scripts / "_hook_observer.py").unlink()
        if missing_classifier:
            (scripts / "_recovery_defer.py").unlink()
        home = root / "sulde"
        bridge = home / "bin/intent-guardian"
        bridge.parent.mkdir(parents=True)
        # The command under test is a genuine wrapper; this stub is only its
        # external launcher failure. The installer-window suite covers B.
        bridge.write_text("#!/bin/sh\n# sulde-observer-in-process-v1\n"
                          "printf x >> \"$TEST_COUNT\"\n" +
                          ('mv "$TEST_SCRIPTS" "$TEST_RETAINED"\n' if disappear else '') +
                          "exit 73\n", encoding="utf-8")
        bridge.chmod(0o700)
        if bridge_unavailable:
            bridge.unlink()
            bridge.symlink_to(root / "missing-bridge")
        kb = home / "data/kb"
        if broken_store:
            kb.parent.mkdir(parents=True)
            kb.write_text("not a directory", encoding="utf-8")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SULDE_", "CODEX_", "CLAUDE_"))}
        env.update(SULDE_HOME=str(home), SULDE_KB_HOME=str(kb),
                   PYTHONDONTWRITEBYTECODE="1", TEST_COUNT=str(root / "calls"),
                   TEST_SCRIPTS=str(scripts), TEST_RETAINED=str(root / "retained"))
        payload = {"tool_name": tool, "tool_input": {"command": command,
                   "file_path": "PRIVATE_PATH_SENTINEL"}, "session_id": session,
                   "call_id": name, "cwd": str(root), "hook_event_name": "PreToolUse"}
        result = subprocess.run(["/bin/sh", str(scripts / "run-hook.sh"), "pre-tool-use"],
                                input=json.dumps(payload), env=env, cwd=root, text=True,
                                encoding="utf-8", errors="replace", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        if bridge_unavailable:
            self.assertFalse((root / "calls").exists())
        else:
            self.assertEqual((root / "calls").read_text(encoding="utf-8"), "x")
        rows = []
        db = kb / "hook-observer/observations.sqlite3"
        if db.is_file():
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                rows = [json.loads(row[0]) for row in conn.execute("select row from observations")]
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        decision = output.get("hookSpecificOutput", {}).get("permissionDecision")
        return result, decision, rows

    def assert_record(self, rows, call, session="session-one"):
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["exit_code"], 73)
        self.assertEqual(row["phase"], "bridge")
        self.assertEqual(row["call_id"], hashlib.sha256(call.encode()).hexdigest())
        self.assertEqual(row["session_id"], hashlib.sha256(session.encode()).hexdigest())
        self.assertEqual(row["loaded_module_generation"], "unknown")
        self.assertEqual(row["artifact_generation"], "unknown")
        self.assertEqual(row["tool_result"], "unknown")
        self.assertEqual(row["authority"], "telemetry_only")
        self.assertNotIn("PRIVATE_PATH_SENTINEL", json.dumps(rows))
        self.assertNotIn("PRIVATE_COMMAND_SENTINEL", json.dumps(rows))

    def test_normal_dependencies_read_and_failure_record(self):
        result, decision, rows = self.case("normal")
        self.assertIsNone(decision, result.stdout)
        self.assert_record(rows, "normal")

    def test_dependencies_disappear_read_and_failure_record(self):
        result, decision, rows = self.case("removed", disappear=True)
        self.assertIsNone(decision, result.stdout)
        self.assert_record(rows, "removed")

    def test_dependencies_disappear_material_and_unknown_still_denied(self):
        for name, tool, cmd in (("write", "Bash", "touch PRIVATE_COMMAND_SENTINEL"),
                                ("unknown", "new_unknown_tool", ""),
                                ("ps", "Bash", "ps -Ao pid,ppid,etime,command"),
                                ("fake-recovery", "Bash", "/tmp/intent-guardian doctor --provider codex")):
            with self.subTest(name=name):
                result, decision, rows = self.case(name, disappear=True, tool=tool, command=cmd)
                self.assertEqual(decision, "deny", result.stdout)
                self.assertNotIn("fallback failed", result.stdout)
                self.assert_record(rows, name)

    def test_recording_failure_is_visible_and_does_not_change_decision(self):
        for name, tool in (("disk-read", "Read"), ("disk-write", "Write")):
            result, decision, rows = self.case(name, disappear=True, tool=tool, broken_store=True)
            self.assertEqual(decision, None if tool == "Read" else "deny")
            self.assertIn("hook_observer_delivery_unavailable", result.stderr)
            self.assertEqual(rows, [])

    def test_missing_observer_reports_coverage_without_granting_write(self):
        result, decision, rows = self.case("missing-observer", missing_observer=True, tool="Write")
        self.assertEqual(decision, "deny")
        self.assertIn("coverage_blind_spot", result.stderr)
        self.assertEqual(rows, [])

    def test_missing_classifier_still_denies_read_without_fabricated_success(self):
        result, decision, rows = self.case("missing-classifier", missing_classifier=True)
        self.assertEqual(decision, "deny")
        self.assertIn("fallback failed", result.stdout)
        self.assert_record(rows, "missing-classifier")

    def test_unavailable_bridge_records_without_reexecuting_or_changing_policy(self):
        for name, tool in (("bridge-read", "Read"), ("bridge-write", "Write")):
            result, decision, rows = self.case(name, tool=tool, bridge_unavailable=True)
            self.assertEqual(decision, None if tool == "Read" else "deny", result.stdout)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["error_category"], "interpreter_or_executable_unavailable")
            self.assertEqual(rows[0]["phase"], "bridge")
            self.assertEqual(rows[0]["tool_result"], "unknown")
            self.assertEqual(rows[0]["authority"], "telemetry_only")

    def test_independent_sessions_have_separate_observation_identities(self):
        _, _, one = self.case("one", disappear=True, session="session-one")
        _, _, two = self.case("two", disappear=True, session="session-two")
        self.assert_record(one, "one", "session-one")
        self.assert_record(two, "two", "session-two")
        self.assertNotEqual(one[0]["lane_id"], two[0]["lane_id"])

    def test_check_to_start_races_keep_independent_failure_observation(self):
        for entry, tool in ((entry, tool) for entry in ("_hook_entry.py", "_hook_observer.py")
                            for tool in ("Read", "Write")):
            with self.subTest(entry=entry, tool=tool):
                root = self.root / (entry + tool)
                scripts = root / "plugin/scripts"
                shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
                if entry == "_hook_observer.py":
                    (scripts / "_hook_entry.py").unlink()
                commands = root / "commands"
                commands.mkdir()
                shim = commands / "python3"
                # Injection is at interpreter startup after the shell's -f
                # check, never inside the function or classifier under test.
                shim.write_text('#!/bin/sh\ncase "$1" in\n*' + entry +
                    ') mv "$TEST_SCRIPTS" "$TEST_RETAINED" ;;\nesac\nexec "' +
                    sys.executable + '" "$@"\n', encoding="utf-8")
                shim.chmod(0o700)
                env = {k: v for k, v in os.environ.items()
                       if not k.startswith(("SULDE_", "CODEX_", "CLAUDE_"))}
                env.update(PATH=str(commands) + os.pathsep + os.environ["PATH"],
                           SULDE_HOME=str(root / "home"), SULDE_KB_HOME=str(root / "kb"),
                           PYTHONDONTWRITEBYTECODE="1", TEST_SCRIPTS=str(scripts),
                           TEST_RETAINED=str(root / "retained"))
                result = subprocess.run(["/bin/sh", str(scripts / "run-hook.sh"), "pre-tool-use"],
                    input=json.dumps({"tool_name": tool, "call_id": entry, "session_id": "race"}),
                    env=env, cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                if tool == "Read":
                    self.assertEqual(result.stdout, "", result.stderr)
                else:
                    self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
                self.assertTrue((root / 'kb/hook-observer/observations.sqlite3').is_file(), result.stderr)
                with sqlite3.connect(f"file:{root / 'kb/hook-observer/observations.sqlite3'}?mode=ro", uri=True) as db:
                    rows = [json.loads(row[0]) for row in db.execute("select row from observations")]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["phase"], "wrapper")
                self.assertNotEqual(rows[0]["exit_code"], 0)
                self.assertEqual(rows[0]["error_category"], "unknown")
                self.assertEqual(rows[0]["permission_decision"], "unknown")
                self.assertEqual(rows[0]["tool_result"], "unknown")


if __name__ == "__main__":
    unittest.main()
