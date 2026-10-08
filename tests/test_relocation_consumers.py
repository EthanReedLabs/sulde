"""Known source consumer: real Git relocation, bounded freeze and writer exclusion."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest import mock

from tests import test_repository_relocation as fixtures
from intent_guardian_parts import repository_relocation as r
from intent_guardian_parts import repository_relocation_consumers as consumer
from intent_guardian_parts.decision_types import IntentGuardianError


def sediment_module():
    spec = importlib.util.spec_from_file_location("relocation_sediment_fixture", fixtures.ROOT / "scripts/kb/auto-sediment.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(sys.platform == "darwin", "real v1 relocation requires macOS")
class RelocationConsumerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepositoryRelocationEvidenceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        self.home, self.contract = f.guardian_fixture()
        (f.linked / "knowledge").mkdir()
        self.config = self.home / consumer.FILENAME
        self.original = {"schema": "sulde-auto-sediment-source-v1", "source_root": str(f.linked),
                         "git_common_dir": str(f.root / ".git")}
        self.write_config(self.original)

    def write_config(self, document):
        self.config.write_text(json.dumps(document, indent=2) + "\n")
        self.config.chmod(0o600)

    def execution(self):
        with mock.patch.object(self.fixture, "guardian_fixture", return_value=(self.home, self.contract)):
            home, path, plan, context = self.fixture.execution_fixture()
        self.fixture.prepare_execution(home, path, plan)
        return plan, context

    def execute(self, plan):
        return r.execute_repository_relocation(self.home, plan["plan_id"], provider="codex", session_id="fixture-session")

    def test_card_freezes_exact_config_and_lock_order(self):
        before = self.config.read_bytes()
        plan, context = self.execution()
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        value = frozen["preflight"]["consumers"]
        self.assertEqual(value["before_text"].encode(), before)
        self.assertEqual(value["after"]["source_root"], str(self.fixture.target / ".worktrees/task"))
        self.assertIn("外部源码绑定", context["card"]["决策内容"])
        _, locks = r._fence_inventory(self.home, frozen["preflight"])
        self.assertEqual(locks[:2], [self.home / "auto-sediment-launch.lock", self.home / "auto-sediment.lock"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_moves_and_resolves_actual_consumer_without_reexecuting(self):
        from native_decision_journal import journal_path
        before = self.config.read_bytes()
        plan, _ = self.execution()
        result = self.execute(plan)
        self.assertEqual(result["status"], "committed")
        after = json.loads(self.config.read_text())
        self.assertEqual(after, {**self.original, "source_root": str(self.fixture.target / ".worktrees/task"),
                                "git_common_dir": str(self.fixture.target / ".git")})
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        binding = sediment_module().resolve_source_binding(argparse.Namespace(source_root=None), self.home)
        self.assertEqual(binding.root, self.fixture.target / ".worktrees/task")
        self.assertEqual(binding.common_dir, self.fixture.target / ".git")
        self.assertEqual(json.loads(Path(plan["plan_path"]).read_text())["preflight"]["consumers"]["before_text"].encode(), before)
        journal = journal_path(self.contract).read_bytes()
        self.assertEqual(self.execute(plan), result)
        self.assertEqual(journal_path(self.contract).read_bytes(), journal)

    def test_process_exit_after_consumer_write_recovers_once(self):
        from native_decision_journal import journal_path
        plan, _ = self.execution()
        script = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
def stop(boundary):
    if boundary == "consumer_written:auto-sediment-source.json":
        os._exit(73)
r._relocation_rebind_boundary = stop
r.execute_repository_relocation(Path(sys.argv[2]), sys.argv[3], provider="codex", session_id="fixture-session")
'''
        child = subprocess.run([sys.executable, "-B", "-c", script, str(fixtures.ROOT / "scripts/kb"),
                                str(self.home), plan["plan_id"]], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
        self.assertTrue(r._read_write_fences(self.home))
        after = self.config.read_bytes()
        sediment = sediment_module()
        binding = sediment.resolve_source_binding(argparse.Namespace(source_root=None), self.home)
        with self.assertRaises(sediment.SedimentError):
            sediment.run_in_isolated_worktree(self.home, binding)
        self.assertFalse(list((self.fixture.target / ".worktrees").glob("auto-sediment-runtime-*")))
        result = self.execute(plan)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(self.config.read_bytes(), after)
        self.assertEqual(r._read_write_fences(self.home), [])
        journal = journal_path(self.contract).read_bytes()
        self.assertEqual(self.execute(plan), result)
        self.assertEqual(journal_path(self.contract).read_bytes(), journal)

    def test_config_drift_after_allow_blocks_before_move(self):
        plan, _ = self.execution()
        self.write_config({**self.original, "source_root": str(self.fixture.root)})
        changed = self.config.read_bytes()
        with self.assertRaises(IntentGuardianError):
            self.execute(plan)
        self.assertTrue(self.fixture.root.exists())
        self.assertFalse(self.fixture.target.exists())
        self.assertEqual(self.config.read_bytes(), changed)

    def test_config_mode_drift_after_allow_blocks_before_move(self):
        plan, _ = self.execution()
        self.config.chmod(0o644)
        with self.assertRaises(IntentGuardianError):
            self.execute(plan)
        self.assertTrue(self.fixture.root.exists())
        self.assertFalse(self.fixture.target.exists())

    def test_absent_config_is_not_created(self):
        self.config.unlink()
        plan, _ = self.execution()
        self.assertEqual(self.execute(plan)["status"], "committed")
        self.assertFalse(self.config.exists())

    def test_unrelated_config_is_not_rewritten(self):
        self.write_config({**self.original, "source_root": str(self.fixture.base / "other"),
                           "git_common_dir": str(self.fixture.base / "other/.git")})
        before = self.config.read_bytes()
        plan, _ = self.execution()
        self.assertEqual(self.execute(plan)["status"], "committed")
        self.assertEqual(self.config.read_bytes(), before)

    def test_mode_link_and_size_fail_before_content_traversal(self):
        original = self.config.read_bytes()
        for fault in ("mode", "symlink", "hardlink", "size", "schema"):
            with self.subTest(fault=fault):
                self.config.unlink()
                self.config.write_bytes(original)
                self.config.chmod(0o600)
                alternate = self.home / ("alternate-" + fault)
                if fault == "mode":
                    self.config.chmod(0o644)
                elif fault == "symlink":
                    self.config.rename(alternate)
                    self.config.symlink_to(alternate)
                elif fault == "hardlink":
                    os.link(self.config, alternate)
                elif fault == "size":
                    self.config.write_bytes(b" " * (consumer.MAX_BYTES + 1))
                else:
                    self.config.write_text("{}")
                with mock.patch.object(r, "_content", side_effect=AssertionError("must fail cheap")):
                    with self.assertRaises(IntentGuardianError):
                        self.fixture.preflight(self.home)

    def test_frozen_consumer_cannot_gain_new_authority(self):
        preflight = self.fixture.preflight(self.home)
        corrupted = copy.deepcopy(preflight)
        corrupted["consumers"]["after"]["source_root"] = str(self.fixture.base / "unreviewed")
        with self.assertRaises(IntentGuardianError):
            consumer.frozen(self.home, corrupted)
        preflight.pop("consumers")
        preflight["preflight_sha256"] = r._digest({key: val for key, val in preflight.items()
                                                 if key != "preflight_sha256"})
        self.assertIsNone(consumer.frozen(self.home, preflight))
        _, locks = r._fence_inventory(self.home, preflight)
        self.assertNotIn(self.home / "auto-sediment-launch.lock", locks)

    def test_stale_source_binding_cannot_recreate_old_root(self):
        sediment = sediment_module()
        binding = sediment.resolve_source_binding(argparse.Namespace(source_root=None), self.home)
        plan, _ = self.execution()
        self.execute(plan)
        with self.assertRaisesRegex(sediment.SedimentError, "source binding changed"):
            sediment.run_in_isolated_worktree(self.home, binding)
        self.assertFalse(self.fixture.root.exists())

    def test_real_migration_locks_exclude_auto_sediment_writers(self):
        # Another interpreter owns each OS lock; ordinary writing launch cannot
        # create a worktree while relocation owns that same lock.
        sediment = sediment_module()
        binding = sediment.resolve_source_binding(argparse.Namespace(source_root=None), self.home)
        script = '''
import fcntl, sys
with open(sys.argv[1], "a+") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    print("locked", flush=True)
    sys.stdin.readline()
'''
        for name in ("auto-sediment-launch.lock", "auto-sediment.lock"):
            with self.subTest(lock=name), subprocess.Popen([sys.executable, "-B", "-c", script, str(self.home / name)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace") as child:
                try:
                    self.assertEqual(child.stdout.readline().strip(), "locked")
                    with self.assertRaisesRegex(sediment.SedimentError, "another auto-sediment"):
                        if name == "auto-sediment-launch.lock":
                            sediment.run_in_isolated_worktree(self.home, binding)
                        else:
                            sediment.acquire_lock(self.home / name)
                    self.assertFalse(list((self.fixture.root / ".worktrees").glob("auto-sediment-runtime-*")))
                finally:
                    child.communicate("release\n", timeout=10)

    def test_real_scale_registry_large_audit_and_consumer_move_together(self):
        import hashlib
        from intent_guardian_parts.state import default_contract, write_contract, audit_path, load_contract
        from intent_guardian_parts.session_workspace import bind_session_workspace, resolve_session_contract
        paths = [self.contract]
        for number in range(1, 24):
            path = self.home / "intent/workspaces" / f"fixture-{number}.active.json"
            write_contract(path, default_contract(intent_id=f"scale-{number}", objective="preserve relocation history",
                acceptance_criteria=["no transferred authority"], workspace=self.fixture.linked,
                mode="enforce", confirmed_by="fixture"))
            paths.append(path)
        for number in range(1, 5):
            bind_session_workspace(self.home, provider="codex", session_id=f"scale-session-{number}",
                                   contract_path=paths[number])
        # Actual bounded JSONL bytes, not a mocked reported size or production log.
        audit = audit_path(paths[-1])
        chunk = (json.dumps({"schema": "synthetic-capacity-observation-v1", "padding": "x" * 1024**2}) + "\n").encode()
        digest = hashlib.sha256()
        with audit.open("wb") as stream:
            for _ in range(96):
                stream.write(chunk)
                digest.update(chunk)
        audit.chmod(0o600)
        plan, _ = self.execution()
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        self.assertEqual(len(frozen["preflight"]["bindings"]["contracts"]), 24)
        self.assertEqual(len(frozen["preflight"]["bindings"]["mappings"]), 5)
        result = self.execute(plan)
        self.assertEqual(result["status"], "committed")
        for path in paths:
            successor = r._relocation_successor_path(frozen["preflight"], path)
            self.assertEqual(load_contract(successor)["status"], "paused")
            self.assertTrue(r._relocation_archive_path(frozen, path).is_file())
        for number in range(1, 5):
            self.assertEqual(resolve_session_contract(self.home, "codex", f"scale-session-{number}"),
                             r._relocation_successor_path(frozen["preflight"], paths[number]))
        actual = hashlib.sha256()
        with audit.open("rb") as stream:
            for block in iter(lambda: stream.read(1024**2), b""):
                actual.update(block)
        self.assertEqual(actual.hexdigest(), digest.hexdigest())
        self.assertEqual(sediment_module().resolve_source_binding(argparse.Namespace(source_root=None), self.home).root,
                         self.fixture.target / ".worktrees/task")
