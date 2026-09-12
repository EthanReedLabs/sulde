from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MEM_SYNC_PATH = ROOT / "scripts" / "kb" / "mem-sync.py"


def load_mem_sync():
    spec = importlib.util.spec_from_file_location("test_t27_mem_sync", MEM_SYNC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MEM_SYNC = load_mem_sync()


class MemSyncUpstreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path("/fixture/mem-sync-repo")

    @staticmethod
    def configured_git(_repo: Path, *args: str, capture: bool = False) -> str:
        values = {
            ("symbolic-ref", "--quiet", "--short", "HEAD"): "sync/main",
            ("config", "--get-all", "branch.sync/main.remote"): "origin",
            ("config", "--get-all", "branch.sync/main.merge"): "refs/heads/main",
            ("remote", "get-url", "--all", "origin"): "ssh://git.example/memory.git",
            ("remote", "get-url", "--push", "--all", "origin"): "ssh://git.example/memory.git",
        }
        return values.get(args, "")

    def test_pull_uses_exact_unique_configured_remote_and_merge_ref(self) -> None:
        with mock.patch.object(
            MEM_SYNC, "git", side_effect=self.configured_git
        ) as git_call:
            MEM_SYNC.pull(self.repo)

        git_call.assert_called_with(
            self.repo,
            "pull",
            "--rebase",
            "origin",
            "refs/heads/main",
        )
        self.assertIn(
            mock.call(
                self.repo,
                "config",
                "--get-all",
                "branch.sync/main.remote",
                capture=True,
            ),
            git_call.call_args_list,
        )
        self.assertIn(
            mock.call(
                self.repo,
                "config",
                "--get-all",
                "branch.sync/main.merge",
                capture=True,
            ),
            git_call.call_args_list,
        )

    def test_detached_head_fails_before_pull(self) -> None:
        def detached(_repo: Path, *args: str, capture: bool = False) -> str:
            if args[0] == "symbolic-ref":
                raise MEM_SYNC.SyncError("detached")
            self.fail(f"unexpected git call after detached HEAD: {args}")

        with mock.patch.object(MEM_SYNC, "git", side_effect=detached) as git_call:
            with self.assertRaisesRegex(
                MEM_SYNC.SyncError, "attached to a symbolic branch"
            ):
                MEM_SYNC.pull(self.repo)
        self.assertFalse(any(call.args[1:2] == ("pull",) for call in git_call.call_args_list))

    def test_missing_remote_or_merge_configuration_fails_before_pull(self) -> None:
        for missing_key in ("remote", "merge"):
            with self.subTest(missing_key=missing_key):
                def missing(_repo: Path, *args: str, capture: bool = False) -> str:
                    if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
                        return "main"
                    if args == ("config", "--get-all", f"branch.main.{missing_key}"):
                        raise MEM_SYNC.SyncError("not configured")
                    if args == ("config", "--get-all", "branch.main.remote"):
                        return "origin"
                    return ""

                with mock.patch.object(MEM_SYNC, "git", side_effect=missing) as git_call:
                    with self.assertRaisesRegex(MEM_SYNC.SyncError, "is missing"):
                        MEM_SYNC.pull(self.repo)
                self.assertFalse(
                    any(call.args[1:2] == ("pull",) for call in git_call.call_args_list)
                )

    def test_invalid_remote_or_merge_ref_fails_before_pull(self) -> None:
        for invalid_key in ("remote", "merge"):
            with self.subTest(invalid_key=invalid_key):
                def invalid(_repo: Path, *args: str, capture: bool = False) -> str:
                    if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
                        return "main"
                    if args == ("config", "--get-all", "branch.main.remote"):
                        return "origin"
                    if args == ("config", "--get-all", "branch.main.merge"):
                        return "main" if invalid_key == "merge" else "refs/heads/main"
                    if args in {
                        ("remote", "get-url", "--all", "origin"),
                        ("remote", "get-url", "--push", "--all", "origin"),
                    }:
                        if invalid_key == "remote":
                            raise MEM_SYNC.SyncError("unknown remote")
                        return "ssh://git.example/memory.git"
                    return ""

                with mock.patch.object(MEM_SYNC, "git", side_effect=invalid) as git_call:
                    with self.assertRaisesRegex(MEM_SYNC.SyncError, "is invalid"):
                        MEM_SYNC.pull(self.repo)
                self.assertFalse(
                    any(call.args[1:2] == ("pull",) for call in git_call.call_args_list)
                )

    def test_multi_valued_remote_or_merge_configuration_fails_before_pull(self) -> None:
        for multi_key, multi_value in (
            ("remote", "origin\nbackup"),
            ("merge", "refs/heads/main\nrefs/heads/backup"),
        ):
            with self.subTest(multi_key=multi_key):
                def multi(_repo: Path, *args: str, capture: bool = False) -> str:
                    if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
                        return "main"
                    if args == ("config", "--get-all", f"branch.main.{multi_key}"):
                        return multi_value
                    if args == ("config", "--get-all", "branch.main.remote"):
                        return "origin"
                    return ""

                with mock.patch.object(MEM_SYNC, "git", side_effect=multi) as git_call:
                    with self.assertRaisesRegex(MEM_SYNC.SyncError, "multi-valued"):
                        MEM_SYNC.pull(self.repo)
                self.assertFalse(
                    any(call.args[1:2] == ("pull",) for call in git_call.call_args_list)
                )

    def test_distinct_or_multiple_fetch_push_urls_fail_before_pull(self) -> None:
        def ambiguous(_repo: Path, *args: str, capture: bool = False) -> str:
            values = {
                ("symbolic-ref", "--quiet", "--short", "HEAD"): "main",
                ("config", "--get-all", "branch.main.remote"): "origin",
                ("config", "--get-all", "branch.main.merge"): "refs/heads/main",
                ("remote", "get-url", "--all", "origin"): "one\ntwo",
                ("remote", "get-url", "--push", "--all", "origin"): "one",
            }
            return values.get(args, "")

        with mock.patch.object(MEM_SYNC, "git", side_effect=ambiguous) as git_call:
            with self.assertRaisesRegex(MEM_SYNC.SyncError, "one fetch/push URL"):
                MEM_SYNC.pull(self.repo)
        self.assertFalse(
            any(call.args[1:2] == ("pull",) for call in git_call.call_args_list)
        )


class MemSyncIsolationAndRecoveryTests(unittest.TestCase):
    @staticmethod
    def git(root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return completed.stdout.strip()

    def test_legacy_migration_is_explicit_idempotent_and_rollback_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            legacy = root / "legacy-kb"
            destination = root / ".sulde/data/kb"
            repo = legacy / "mem-sync-repo"
            repo.mkdir(parents=True)
            self.git(repo, "init")
            (repo / "payload.jsonl").write_text("fixture", encoding="utf-8")
            config = {
                "repo_path": str(repo),
                "device_id": "device-a",
                "sync_projects": {},
                "encrypt": False,
            }
            (legacy / MEM_SYNC.CONFIG_NAME).write_text(
                json.dumps(config), encoding="utf-8"
            )
            (legacy / MEM_SYNC.STATE_NAME).write_text(
                json.dumps({"projects": {}}), encoding="utf-8"
            )
            with mock.patch.dict(
                os.environ,
                {"SULDE_KB_HOME": str(destination)},
                clear=False,
            ):
                first = MEM_SYNC.migrate_legacy(legacy)
                second = MEM_SYNC.migrate_legacy(legacy)
                self.assertFalse(first["idempotent"])
                self.assertTrue(second["idempotent"])
                migrated = json.loads(
                    (destination / MEM_SYNC.CONFIG_NAME).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    migrated["repo_path"],
                    str((destination / "mem-sync-repo").resolve(strict=False)),
                )
                self.assertTrue((legacy / MEM_SYNC.CONFIG_NAME).is_file())
                rollback = MEM_SYNC.rollback_legacy_migration()
                self.assertEqual(
                    rollback["removed"],
                    ["mem-sync-repo", MEM_SYNC.STATE_NAME, MEM_SYNC.CONFIG_NAME],
                )
                self.assertFalse(destination.joinpath(MEM_SYNC.CONFIG_NAME).exists())
                self.assertTrue((legacy / "mem-sync-repo/payload.jsonl").is_file())

    def test_legacy_rollback_rejects_migrated_artifact_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            legacy = root / "legacy-kb"
            destination = root / "sulde-kb"
            repo = legacy / "mem-sync-repo"
            repo.mkdir(parents=True)
            self.git(repo, "init")
            config = {
                "repo_path": str(repo),
                "device_id": "device-a",
                "sync_projects": {},
                "encrypt": False,
            }
            (legacy / MEM_SYNC.CONFIG_NAME).write_text(
                json.dumps(config), encoding="utf-8"
            )
            with mock.patch.dict(
                os.environ, {"SULDE_KB_HOME": str(destination)}, clear=False
            ):
                MEM_SYNC.migrate_legacy(legacy)
                migrated = destination / MEM_SYNC.CONFIG_NAME
                migrated.write_text("drift", encoding="utf-8")
                with self.assertRaisesRegex(MEM_SYNC.SyncError, "drifted"):
                    MEM_SYNC.rollback_legacy_migration()
                self.assertTrue(migrated.is_file())
                self.assertTrue((destination / "mem-sync-repo").is_dir())
                self.assertTrue((legacy / MEM_SYNC.CONFIG_NAME).is_file())

    def test_normal_config_read_never_consults_legacy_claude_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            home = Path(directory_name) / "sulde-kb"
            home.mkdir()
            config = {
                "repo_path": str(home / "mem-sync-repo"),
                "device_id": "device-a",
                "sync_projects": {},
                "encrypt": False,
            }
            (home / MEM_SYNC.CONFIG_NAME).write_text(
                json.dumps(config), encoding="utf-8"
            )
            with mock.patch.dict(
                os.environ, {"SULDE_KB_HOME": str(home)}, clear=False
            ), mock.patch.object(
                MEM_SYNC,
                "legacy_kb_home",
                side_effect=AssertionError("legacy lookup"),
            ):
                self.assertEqual(MEM_SYNC.read_config(), config)

    def test_normal_repo_must_be_inside_sulde_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "sulde-kb"
            outside = root / "legacy/mem-sync-repo"
            outside.mkdir(parents=True)
            self.git(outside, "init")
            config = {
                "repo_path": str(outside),
                "device_id": "device-a",
                "sync_projects": {},
                "encrypt": False,
            }
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False):
                with self.assertRaisesRegex(MEM_SYNC.SyncError, "inside the Sulde data root"):
                    MEM_SYNC.require_repo(config)

    def test_import_and_export_share_one_git_common_directory_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name) / "mem-sync-repo"
            repo.mkdir()
            self.git(repo, "init")
            contender = (
                "import runpy,sys; "
                f"m=runpy.run_path({str(MEM_SYNC_PATH)!r}); "
                "repo=__import__('pathlib').Path(sys.argv[1]); "
                "cm=m['sync_transaction_lock'](repo); "
                "cm.__enter__()"
            )
            with MEM_SYNC.sync_transaction_lock(repo):
                completed = subprocess.run(
                    [sys.executable, "-c", contender, str(repo)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    cwd=ROOT,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("transaction lock is busy", completed.stderr)
            with MEM_SYNC.sync_transaction_lock(repo):
                pass

    def test_scheduler_retries_with_bounded_exponential_backoff(self) -> None:
        args = argparse.Namespace(scheduled=True)
        attempts = []

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) < MEM_SYNC.SCHEDULED_MAX_ATTEMPTS:
                raise MEM_SYNC.TransientSyncError("temporary")
            return 0

        with mock.patch.object(MEM_SYNC.time, "sleep") as sleep:
            self.assertEqual(MEM_SYNC.scheduled_retry(args, operation), 0)
        self.assertEqual(attempts, [1, 2, 3])
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [
                MEM_SYNC.SCHEDULED_BACKOFF_SECONDS,
                MEM_SYNC.SCHEDULED_BACKOFF_SECONDS * 2,
            ],
        )

    def test_manual_and_scheduler_transient_failures_have_distinct_exit_codes(self) -> None:
        for scheduled, expected in ((False, 2), (True, 75)):
            with self.subTest(scheduled=scheduled), mock.patch.object(
                MEM_SYNC, "parse_args", return_value=argparse.Namespace(
                    command="export", scheduled=scheduled
                )
            ), mock.patch.object(
                MEM_SYNC,
                "command_export",
                side_effect=MEM_SYNC.TransientSyncError("network unavailable"),
            ):
                self.assertEqual(MEM_SYNC.main(), expected)

    def test_explicit_upstream_is_reused_for_pull_and_push(self) -> None:
        upstream = ("main", "origin", "refs/heads/main")
        repo = Path("/fixture/mem-sync-repo")
        with mock.patch.object(MEM_SYNC, "git", return_value="") as git_call:
            MEM_SYNC.pull(repo, upstream)
            MEM_SYNC.commit_push(repo, "device-a", (1, 0, 0), upstream, [])
        self.assertIn(
            mock.call(repo, "pull", "--rebase", "origin", "refs/heads/main"),
            git_call.call_args_list,
        )
        self.assertIn(
            mock.call(repo, "push", "origin", "HEAD:refs/heads/main"),
            git_call.call_args_list,
        )
        self.assertFalse(
            any(call.args[1:2] == ("symbolic-ref",) for call in git_call.call_args_list)
        )

    def test_failed_push_preserves_committed_truth_and_retry_advances_state_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "sulde-kb"
            home.mkdir()
            remote = root / "remote.git"
            remote.mkdir()
            self.git(remote, "init", "--bare", "--initial-branch=main")
            seed = root / "seed"
            seed.mkdir()
            self.git(seed, "init", "-b", "main")
            self.git(seed, "config", "user.name", "Sulde Test")
            self.git(seed, "config", "user.email", "sulde@example.invalid")
            (seed / "README").write_bytes(b"seed")
            self.git(seed, "add", "--", "README")
            self.git(seed, "commit", "-m", "seed")
            self.git(seed, "remote", "add", "origin", str(remote))
            self.git(seed, "push", "-u", "origin", "main")
            repo = home / "mem-sync-repo"
            completed = subprocess.run(
                ["git", "clone", str(remote), str(repo)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            config = {
                "repo_path": str(repo),
                "device_id": "device-a",
                "sync_projects": {"project-a": {"project_id": "project-a"}},
                "encrypt": False,
            }
            (home / MEM_SYNC.CONFIG_NAME).write_text(
                json.dumps(config), encoding="utf-8"
            )
            memory = MEM_SYNC.memory_module()
            connection = memory.connect(home / "memory.db")
            connection.execute(
                "INSERT INTO mem_entries(project,session_id,source_host,role,content,content_hash,ts) VALUES (?,?,?,?,?,?,?)",
                ("project-a", "session-a", "codex", "user", "hello", "hash-a", "2026-09-04T00:00:00Z"),
            )
            connection.commit()
            connection.close()
            args = argparse.Namespace(project=None, scheduled=False)
            real_git = MEM_SYNC.git
            failed = False

            def fail_first_push(repository: Path, *arguments: str, capture: bool = False):
                nonlocal failed
                if arguments[:1] == ("push",) and not failed:
                    failed = True
                    raise MEM_SYNC.SyncError("injected push failure")
                return real_git(repository, *arguments, capture=capture)

            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False):
                with mock.patch.object(MEM_SYNC, "git", side_effect=fail_first_push):
                    with self.assertRaises(MEM_SYNC.TransientSyncError):
                        MEM_SYNC._command_export_once(args)
                self.assertFalse((home / MEM_SYNC.STATE_NAME).exists())
                self.assertEqual(self.git(repo, "status", "--porcelain"), "")
                self.assertEqual(
                    len((repo / "project-a/device-a.jsonl").read_text(encoding="utf-8").splitlines()),
                    1,
                )
                self.assertEqual(MEM_SYNC._command_export_once(args), 0)
                state = json.loads((home / MEM_SYNC.STATE_NAME).read_text(encoding="utf-8"))
                self.assertEqual(state["projects"]["project-a"]["last_entry_id"], 1)
                self.assertEqual(
                    len((repo / "project-a/device-a.jsonl").read_text(encoding="utf-8").splitlines()),
                    1,
                )
                self.assertEqual(self.git(repo, "status", "--porcelain"), "")

    def test_crash_journal_recovers_only_exact_uncommitted_generated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            repo = root / "mem-sync-repo"
            repo.mkdir()
            self.git(repo, "init")
            self.git(repo, "config", "user.name", "Sulde Test")
            self.git(repo, "config", "user.email", "sulde@example.invalid")
            tracked = repo / "project/device.jsonl"
            tracked.parent.mkdir()
            tracked.write_text("before", encoding="utf-8")
            self.git(repo, "add", "--", "project/device.jsonl")
            self.git(repo, "commit", "-m", "base")
            head = self.git(repo, "rev-parse", "HEAD")
            generated = repo / "project/manifest.json"
            originals = {tracked: tracked.read_bytes(), generated: None}
            with mock.patch.dict(
                os.environ, {"SULDE_KB_HOME": str(root)}, clear=False
            ):
                MEM_SYNC._write_export_journal(repo, originals, head)
                tracked.write_text("after-crash", encoding="utf-8")
                generated.write_text("temporary", encoding="utf-8")
                self.git(
                    repo,
                    "add",
                    "--",
                    "project/device.jsonl",
                    "project/manifest.json",
                )
                self.assertTrue(MEM_SYNC._recover_export_transaction(repo))
                self.assertFalse((root / MEM_SYNC.EXPORT_JOURNAL_NAME).exists())
            self.assertEqual(tracked.read_text(encoding="utf-8"), "before")
            self.assertFalse(generated.exists())
            self.assertEqual(self.git(repo, "status", "--porcelain"), "")

    def test_uncommitted_generation_is_rolled_back_without_touching_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name) / "mem-sync-repo"
            repo.mkdir()
            self.git(repo, "init")
            self.git(repo, "config", "user.name", "Sulde Test")
            self.git(repo, "config", "user.email", "sulde@example.invalid")
            tracked = repo / "project/device.jsonl"
            tracked.parent.mkdir()
            tracked.write_text("before", encoding="utf-8")
            self.git(repo, "add", "--", "project/device.jsonl")
            self.git(repo, "commit", "-m", "base")
            head = self.git(repo, "rev-parse", "HEAD")
            generated = repo / "project/manifest.json"
            originals = {tracked: tracked.read_bytes(), generated: None}
            tracked.write_text("after", encoding="utf-8")
            generated.write_text("temporary", encoding="utf-8")
            self.git(repo, "add", "--", "project/device.jsonl", "project/manifest.json")

            MEM_SYNC._rollback_export_files(repo, originals, head)

            self.assertEqual(tracked.read_text(encoding="utf-8"), "before")
            self.assertFalse(generated.exists())
            self.assertEqual(self.git(repo, "status", "--porcelain"), "")
            self.assertEqual(self.git(repo, "rev-parse", "HEAD"), head)


if __name__ == "__main__":
    unittest.main()
