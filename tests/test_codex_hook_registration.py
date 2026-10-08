from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = runpy.run_path(str(ROOT / "scripts/release/codex_hook_registration.py"))
command = REGISTRATION["stable_hook_command"]
is_stable = REGISTRATION["is_stable_hook_document"]
validate = REGISTRATION["validate_registration"]
PLUGIN = ROOT / "integrations/codex/plugins/sulde"


@unittest.skipIf(os.name == "nt", "POSIX stable transport only")
class StableHookRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sulde registration ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "host home"
        self.home.mkdir()
        self.sulde = self.root / "product home"
        self.env = dict(os.environ, HOME=str(self.home), SULDE_HOME=str(self.sulde))
        self.env.pop("SULDE_KB_HOME", None)

    def bootstrap(self, root=None, body="printf '%s' \"sulde-hook-entry-complete-v1:$1\"\n"):
        path = (root or self.sulde) / "bin/sulde-codex-hook"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o700)
        return path

    def call(self, event="PreToolUse"):
        return subprocess.run(
            ["/bin/sh", "-c", command(event)], input="{}", text=True,
            env=self.env, capture_output=True, encoding="utf-8", errors="replace", timeout=5,
        )

    def assert_deny(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_templates_are_exact_single_registration(self):
        expected = (PLUGIN / "hooks.posix.json").read_bytes()
        self.assertEqual(expected, (PLUGIN / "hooks.json").read_bytes())
        self.assertTrue(is_stable(json.loads(expected)))
        self.assertNotIn("PLUGIN_ROOT", expected.decode())
        self.assertFalse(is_stable(json.loads((PLUGIN / "hooks.windows.json").read_bytes())))

    def test_six_commands_reach_exact_event_without_plugin_root(self):
        self.bootstrap()
        for event, hook in REGISTRATION["EVENTS"].items():
            with self.subTest(event=event):
                result = self.call(event)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), hook)

    def test_stdin_and_exit_status_are_not_forged(self):
        self.bootstrap(body="payload=$(cat)\nprintf '%s' \"sulde-hook-entry-complete-v1:$payload\"\n")
        self.assertEqual(self.call().stdout.strip(), "{}")
        self.bootstrap(body="printf untrusted-partial-output\nexit 1\n")
        result = self.call()
        self.assert_deny(result)
        self.assertNotIn("untrusted-partial", result.stdout)

    def test_missing_bootstrap_denies_before_action(self):
        self.assert_deny(self.call())

    def test_empty_truncated_or_unconfirmed_bootstrap_never_allows(self):
        for body in ("", "exit 0\n", "printf sulde-hook-entry-complete-v\n"):
            with self.subTest(body=body):
                self.bootstrap(body=body)
                self.assert_deny(self.call())
        self.bootstrap(body="printf sulde-hook-entry-complete-v1:\n")
        self.assertEqual(self.call().stdout, "")

    def test_missing_nonpre_reports_blindspot_without_human_decision(self):
        for event in set(REGISTRATION["EVENTS"]) - {"PreToolUse"}:
            result = self.call(event)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("coverage_blind_spot", result.stderr)

    def test_symlink_bootstrap_is_not_executed(self):
        path = self.bootstrap()
        target = path.with_name("unexpected-target")
        path.rename(target)
        path.symlink_to(target)
        self.assert_deny(self.call())

    def test_root_precedence_matches_existing_wrapper(self):
        self.env.pop("SULDE_HOME")
        neutral = self.home / ".sulde"
        self.bootstrap(neutral)
        self.assertEqual(self.call().stdout.strip(), "pre-tool-use")
        self.env["SULDE_KB_HOME"] = str(neutral / "data/kb")
        self.assertEqual(self.call().stdout.strip(), "pre-tool-use")
        portable = self.root / "portable"
        self.env["SULDE_KB_HOME"] = str(portable)
        self.assert_deny(self.call())
        self.bootstrap(portable)
        self.assertEqual(self.call().stdout.strip(), "pre-tool-use")

    def test_new_entry_survives_missing_cache_not_proof_of_old_command(self):
        self.bootstrap()
        missing = self.root / "deleted-cache/scripts/run-hook.sh"
        old = subprocess.run(["/bin/sh", str(missing), "pre-tool-use"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        self.assertNotEqual(old.returncode, 0)
        self.assertEqual(self.call().stdout.strip(), "pre-tool-use")

    def test_unknown_and_duplicate_routes_are_not_migration_proof(self):
        doc = json.loads((PLUGIN / "hooks.posix.json").read_bytes())
        duplicate = copy.deepcopy(doc)
        duplicate["hooks"]["PreToolUse"] *= 2
        self.assertFalse(is_stable(duplicate))
        for field, value in (("matcher", "^never-match-any-tool$"), ("disabled", True)):
            narrowed = copy.deepcopy(doc)
            narrowed["hooks"]["PreToolUse"][0][field] = value
            self.assertFalse(is_stable(narrowed))
        for field, value in (("async", True), ("timeout", 0), ("timeout", True)):
            narrowed = copy.deepcopy(doc)
            narrowed["hooks"]["PreToolUse"][0]["hooks"][0][field] = value
            self.assertFalse(is_stable(narrowed))
        doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"] += "; echo extra"
        self.assertFalse(is_stable(doc))
        plugin = self.root / "artifact"
        self.assertEqual(validate(plugin)["protocol"], "unknown")
        path = plugin / "hooks/hooks.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(validate(plugin)["protocol"], "unknown")


if __name__ == "__main__":
    unittest.main()
