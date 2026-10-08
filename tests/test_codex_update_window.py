"""Real installer boundaries with an already-running, old-session shell Hook.

Only the external Codex registry and scheduler are fixtures (same as installer
regression). No policy result, launcher, fallback or observer is mocked. Set
SULDE_UPDATE_WINDOW_SOURCE to repeat identical assertions on a baseline tree.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import unittest
from unittest import mock

from tests import test_codex_plugin_install as fixture
from tests.test_codex_plugin_install import CodexPluginInstallFixture, load_installer

if os.environ.get("SULDE_UPDATE_WINDOW_SOURCE"):
    fixture.ROOT = Path(os.environ["SULDE_UPDATE_WINDOW_SOURCE"]).resolve()
    fixture.INSTALLER = fixture.ROOT / "scripts/release/install_codex_plugin.py"
    fixture.STAGER = fixture.ROOT / "scripts/release/stage_plugin.py"


@unittest.skipIf(os.name == "nt", "POSIX shell continuity; Windows remains unverified")
class UpdateWindowTests(CodexPluginInstallFixture, unittest.TestCase):
    def _old_hook(self):
        self.prepare_artifact()
        old = self.codex_home / "plugins/cache/sulde-local/sulde/0.0.7-window"
        shutil.copytree(self.artifact / "plugins/sulde", old)
        descriptor = old / ".codex-plugin/plugin.json"
        data = json.loads(descriptor.read_text(encoding="utf-8"))
        data["version"] = old.name
        descriptor.write_text(json.dumps(data), encoding="utf-8")
        return old

    def _start_waiting_hook(self, old):
        # The external cat boundary acknowledges that the real wrapper has
        # started and reached stdin capture. No sleeps determine the race.
        ready = self.root / "cat-ready"
        binary = self.root / "bin"
        binary.mkdir()
        cat = binary / "cat"
        cat.write_text(
            '#!/bin/sh\n: > "$SULDE_WINDOW_READY"\nexec /bin/cat "$@"\n',
            encoding="utf-8",
        )
        cat.chmod(0o755)
        environment = dict(os.environ)
        environment.update({
            "PATH": str(binary) + os.pathsep + environment["PATH"],
            "SULDE_WINDOW_READY": str(ready),
            "SULDE_KB_HOME": str(self.kb_home),
            "SULDE_CODEX_FALLBACK_ONLY": "1",
        })
        process = subprocess.Popen(
            ["/bin/sh", str(old / "scripts/run-hook.sh"), "pre-tool-use"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=environment,
        )
        deadline = time.monotonic() + 5
        while not ready.exists():
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                self.fail("real wrapper did not reach stdin boundary")
            time.sleep(0.005)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        return process

    def _assert_read(self, process, *, tool="Read"):
        payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "window-read",
                              "call_id": "window-call", "tool_name": tool,
                              "tool_input": {"file_path": "README.md"}})
        output, error = process.communicate(payload, timeout=15)
        self.assertEqual(process.returncode, 0, error)
        result = json.loads(output) if output.strip() else {}
        decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
        self.assertEqual(decision, None if tool == "Read" else "deny", (output, error))
        self.assertNotIn("fallback failed", output)

    def test_normal_running_old_hook_reads(self):
        self._assert_read(self._start_waiting_hook(self._old_hook()))

    def test_running_old_hook_reads_after_registry_prunes_its_tree(self):
        self._window_and_recovery("registry.after_add")

    def _window_and_recovery(self, boundary, *, tool="Read"):
        old = self._old_hook()
        installer = load_installer()
        before = installer.warm_tree_state(old)
        process = self._start_waiting_hook(old)
        installed = self.run_installer(prune_path=old, failpoint=boundary)
        self.assertEqual(installed.returncode, 86, installed.stderr)
        if boundary in {"registry.after_add", "launcher.before_publish", "launcher.after_publish",
                        "alias.before_publish"}:
            self.assertFalse(old.exists(), "fixture must reach the real registry prune")
        self._assert_read(process, tool=tool)
        if boundary in {"registry.after_add", "launcher.before_publish"}:
            database = self.kb_home / "hook-observer/observations.sqlite3"
            self.assertTrue(database.is_file(), "missing adapter failure must remain observable")
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                rows = [json.loads(row[0]) for row in connection.execute("select row from observations")]
            failures = [row for row in rows if row.get("exit_code") != 0]
            self.assertTrue(failures, rows)
            self.assertTrue(all(row["authority"] == "telemetry_only" for row in failures))
            self.assertTrue(all(row["tool_result"] == "unknown" for row in failures))
        recovered = self.run_installer(recover_only=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)["status"], "recovered_old_generation")
        self.assertFalse(old.is_symlink())
        self.assertEqual(installer.warm_tree_state(old), before)
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())

    def test_running_old_hook_reads_after_registry_remove_and_recovers(self):
        self._window_and_recovery("registry.after_remove")

    def test_running_old_hook_still_denies_write_after_registry_prune(self):
        self._window_and_recovery("registry.after_add", tool="Write")

    def test_running_old_hook_reads_before_launcher_publish_and_recovers(self):
        self._window_and_recovery("launcher.before_publish")

    def test_running_old_hook_reads_after_launcher_publish_and_recovers(self):
        self._window_and_recovery("launcher.after_publish")

    def test_running_old_hook_reads_before_alias_publish_and_recovers(self):
        self._window_and_recovery("alias.before_publish")

    def test_running_old_hook_reads_after_alias_publish_and_recovers(self):
        self._window_and_recovery("alias.after_publish")

    def test_existing_alias_is_reachable_while_new_alias_is_prepared(self):
        installer = load_installer()
        old = self.root / "retired-old"
        new = self.root / "retired-new"
        old.mkdir()
        new.mkdir()
        (old / "identity").write_text("old", encoding="utf-8")
        (new / "identity").write_text("new", encoding="utf-8")
        alias = self.root / "cached-alias"
        alias.symlink_to(old, target_is_directory=True)
        state = installer.warm_tree_state(new)
        plan = installer.CacheRetirement(alias, new, new, state, state.tree_sha256,
                                         self.root / "retirement.json", True, old)
        real_symlink = Path.symlink_to
        observations = []

        def observe_boundary(path, target, target_is_directory=False):
            # External filesystem publication boundary; the original operation
            # still runs. Opening the old identity must never observe ENOENT.
            observations.append((alias / "identity").read_text(encoding="utf-8"))
            return real_symlink(path, target, target_is_directory=target_is_directory)

        with mock.patch.object(Path, "symlink_to", observe_boundary):
            installer._publish_retirement_aliases((plan,))
        self.assertEqual(observations, ["old"])
        self.assertEqual((alias / "identity").read_text(encoding="utf-8"), "new")

    def test_alias_publication_exception_preserves_old_link(self):
        installer = load_installer()
        old = self.root / "old"
        new = self.root / "new"
        old.mkdir()
        new.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(old, target_is_directory=True)
        state = installer.warm_tree_state(new)
        record = self.root / "retirement.json"
        plan = installer.CacheRetirement(alias, new, new, state, state.tree_sha256,
                                         record, True, old)
        with mock.patch.object(installer.os, "replace", side_effect=OSError("injected publish failure")):
            with self.assertRaisesRegex(OSError, "injected publish failure"):
                installer._publish_retirement_aliases((plan,))
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), old.resolve())
        self.assertFalse(record.exists())
        self.assertEqual(list(self.root.glob(".*.link")), [])

    def test_alias_drift_is_rejected_without_overwrite(self):
        installer = load_installer()
        old = self.root / "old"
        new = self.root / "new"
        drift = self.root / "drift"
        for path in (old, new, drift):
            path.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(drift, target_is_directory=True)
        state = installer.warm_tree_state(new)
        plan = installer.CacheRetirement(alias, new, new, state, state.tree_sha256,
                                         self.root / "retirement.json", True, old)
        with self.assertRaisesRegex(installer.InstallError, "alias drifted"):
            installer._publish_retirement_aliases((plan,))
        self.assertEqual(alias.resolve(), drift.resolve())


if __name__ == "__main__":
    unittest.main()
