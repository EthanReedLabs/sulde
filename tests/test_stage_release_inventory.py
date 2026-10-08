from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts" / "release" / "stage_plugin.py"


def _load_stager():
    name = "sulde_stage_plugin_inventory_tests"
    spec = importlib.util.spec_from_file_location(name, STAGER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load stager: {STAGER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stage_plugin = _load_stager()
import intent_guardian  # noqa: E402


class ReleaseInventoryTests(unittest.TestCase):
    def write_required_sources(self, root: Path) -> None:
        for relative in stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# required runtime module\n", encoding="utf-8")

    def test_inventory_adds_only_explicit_required_regular_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-inventory-") as name:
            root = Path(name)
            self.write_required_sources(root)
            unknown = root / "scripts" / "kb" / "unknown-local.py"
            unknown.write_text("LOCAL_SECRET = 'not-for-release'\n", encoding="utf-8")
            secret = root / "scripts" / "kb" / "mem-sync.key"
            secret.write_text("not-for-release\n", encoding="utf-8")
            tracked = [stage_plugin.GitEntry(Path("README.md"), 0o100644)]

            with mock.patch.object(stage_plugin, "git_entries", return_value=tracked):
                inventory = stage_plugin.release_entries(root)

        paths = [entry.path for entry in inventory]
        self.assertEqual(
            paths,
            [Path("README.md"), *stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES],
        )
        self.assertNotIn(Path("scripts/kb/unknown-local.py"), paths)
        self.assertNotIn(Path("scripts/kb/mem-sync.key"), paths)

    def test_tracked_required_source_is_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-inventory-") as name:
            root = Path(name)
            self.write_required_sources(root)
            tracked_required = stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES[0]
            tracked = [stage_plugin.GitEntry(tracked_required, 0o100644)]

            with mock.patch.object(stage_plugin, "git_entries", return_value=tracked):
                inventory = stage_plugin.release_entries(root)

        self.assertEqual(
            sum(entry.path == tracked_required for entry in inventory),
            1,
        )
        self.assertEqual(
            {entry.path for entry in inventory},
            set(stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES),
        )

    def test_authorization_digest_covers_every_explicit_release_input(self) -> None:
        self.assertEqual(
            tuple(stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES),
            intent_guardian.EXPLICIT_RELEASE_RUNTIME_INPUTS,
        )
        with tempfile.TemporaryDirectory(prefix="sulde-release-binding-") as name:
            root = Path(name)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked = root / "README.md"
            tracked.write_text("tracked\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.write_required_sources(root)
            baseline = intent_guardian._workspace_tracked_tree_sha256(root)
            unknown = root / "scripts" / "kb" / "unknown-local.py"
            unknown.write_text("LOCAL_SECRET = True\n", encoding="utf-8")
            self.assertEqual(
                intent_guardian._workspace_tracked_tree_sha256(root),
                baseline,
            )
            for index, relative in enumerate(
                stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES
            ):
                changed = root / relative
                original = changed.read_bytes()
                changed.write_text(
                    f"# changed required runtime module {index}\n",
                    encoding="utf-8",
                )
                self.assertNotEqual(
                    intent_guardian._workspace_tracked_tree_sha256(root),
                    baseline,
                    relative,
                )
                changed.write_bytes(original)
                self.assertEqual(
                    intent_guardian._workspace_tracked_tree_sha256(root),
                    baseline,
                    relative,
                )

    def hostile_runtime_allowlists(
        self,
        root: Path,
    ) -> dict[str, tuple[object, ...]]:
        original = stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES
        unknown = Path("scripts/kb/hostile-unknown.py")
        (root / unknown).write_text("HOSTILE=True\n", encoding="utf-8")
        alias_parent = root / "scripts" / "kb" / "alias-parent"
        alias_parent.mkdir()
        parent_alias = Path(
            "scripts/kb/alias-parent/../approval_timeout_policy.py"
        )
        symlink_parent = root / "scripts" / "kb" / "symlink-parent"
        try:
            symlink_parent.symlink_to(".", target_is_directory=True)
        except OSError as error:
            self.skipTest(f"parent symlink fixture unavailable: {error}")
        symlink_alias = Path(
            "scripts/kb/symlink-parent/approval_timeout_policy.py"
        )
        return {
            "exact_duplicate": (*original, original[0]),
            "unknown_regular": (*original, unknown),
            "parent_component_alias": (*original, parent_alias),
            "reordered": (original[1], original[0], *original[2:]),
            "absolute": (*original[:-1], (root / original[-1]).resolve()),
            "parent_symlink_alias": (*original, symlink_alias),
            "wrong_path_type": (*original[:-1], original[-1].as_posix()),
            "empty_path": (*original[:-1], Path("")),
        }

    def test_hostile_allowlists_fail_before_filesystem_or_downstream_touch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-hostile-") as name:
            root = Path(name) / "repo"
            root.mkdir()
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked = root / "README.md"
            tracked.write_text("tracked\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.write_required_sources(root)
            guardian_state = sys.modules[
                intent_guardian._workspace_tracked_tree_sha256.__module__
            ]

            for label, hostile_inputs in self.hostile_runtime_allowlists(
                root
            ).items():
                with self.subTest(side="guardian", attack=label):
                    with (
                        mock.patch.object(
                            guardian_state,
                            "EXPLICIT_RELEASE_RUNTIME_INPUTS",
                            hostile_inputs,
                        ),
                        mock.patch.object(
                            guardian_state.os,
                            "lstat",
                            side_effect=AssertionError("os.lstat was touched"),
                        ) as guardian_lstat,
                        mock.patch.object(
                            guardian_state.os,
                            "readlink",
                            side_effect=AssertionError("os.readlink was touched"),
                        ) as guardian_readlink,
                        mock.patch.object(
                            guardian_state.subprocess,
                            "run",
                            side_effect=AssertionError("Git was touched"),
                        ) as guardian_git,
                        mock.patch.object(
                            guardian_state.hashlib,
                            "sha256",
                            side_effect=AssertionError("SHA-256 was touched"),
                        ) as guardian_hash,
                    ):
                        with self.assertRaisesRegex(
                            intent_guardian.IntentGuardianError,
                            "invalid explicit release runtime input allowlist",
                        ):
                            intent_guardian._workspace_tracked_tree_sha256(root)
                    self.assertEqual(
                        (
                            guardian_lstat.call_count,
                            guardian_readlink.call_count,
                            guardian_git.call_count,
                            guardian_hash.call_count,
                        ),
                        (0, 0, 0, 0),
                    )

                with self.subTest(side="stager", attack=label):
                    output = Path(name) / f"artifact-{label}"
                    with (
                        mock.patch.object(
                            stage_plugin,
                            "REQUIRED_RUNTIME_SOURCE_FILES",
                            hostile_inputs,
                        ),
                        mock.patch.object(
                            stage_plugin.os,
                            "lstat",
                            side_effect=AssertionError("os.lstat was touched"),
                        ) as stager_lstat,
                        mock.patch.object(
                            stage_plugin.os,
                            "readlink",
                            side_effect=AssertionError("os.readlink was touched"),
                        ) as stager_readlink,
                        mock.patch.object(
                            stage_plugin,
                            "git_entries",
                            side_effect=AssertionError("Git was touched"),
                        ) as stager_git,
                        mock.patch.object(
                            stage_plugin.hashlib,
                            "sha256",
                            side_effect=AssertionError("SHA-256 was touched"),
                        ) as stager_hash,
                        mock.patch.object(
                            stage_plugin,
                            "copy_entry",
                            side_effect=AssertionError("copy was touched"),
                        ) as stager_copy,
                        mock.patch.object(
                            stage_plugin,
                            "prepare_output",
                            side_effect=AssertionError("output was touched"),
                        ) as stager_output,
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "invalid required runtime source allowlist",
                        ):
                            stage_plugin.stage_codex(root, output, "posix")
                    self.assertEqual(
                        (
                            stager_lstat.call_count,
                            stager_readlink.call_count,
                            stager_git.call_count,
                            stager_hash.call_count,
                            stager_copy.call_count,
                            stager_output.call_count,
                        ),
                        (0, 0, 0, 0, 0, 0),
                    )
                    self.assertFalse(output.exists())

    def test_real_unknown_and_alias_attacks_create_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-real-") as name:
            root = Path(name) / "repo"
            root.mkdir()
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked = root / "README.md"
            tracked.write_text("tracked\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.write_required_sources(root)
            guardian_state = sys.modules[
                intent_guardian._workspace_tracked_tree_sha256.__module__
            ]
            attacks = self.hostile_runtime_allowlists(root)

            for label in (
                "unknown_regular",
                "parent_component_alias",
                "parent_symlink_alias",
            ):
                hostile_inputs = attacks[label]
                with self.subTest(side="guardian", attack=label):
                    with mock.patch.object(
                        guardian_state,
                        "EXPLICIT_RELEASE_RUNTIME_INPUTS",
                        hostile_inputs,
                    ):
                        with self.assertRaisesRegex(
                            intent_guardian.IntentGuardianError,
                            "invalid explicit release runtime input allowlist",
                        ):
                            intent_guardian._workspace_tracked_tree_sha256(root)

                with self.subTest(side="stager", attack=label):
                    output = Path(name) / f"real-artifact-{label}"
                    with mock.patch.object(
                        stage_plugin,
                        "REQUIRED_RUNTIME_SOURCE_FILES",
                        hostile_inputs,
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "invalid required runtime source allowlist",
                        ):
                            stage_plugin.stage_codex(root, output, "posix")
                    self.assertFalse(output.exists())

    def test_authorization_digest_binds_consumed_tree_not_index_object_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-binding-index-") as name:
            root = Path(name)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked = root / "README.md"
            second = root / "SECOND.md"
            before = {
                tracked: b"before left\n",
                second: b"before right\n",
            }
            for path, content in before.items():
                path.write_bytes(content)
            subprocess.run(
                ["git", "add", "README.md", "SECOND.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Sulde Test",
                    "-c",
                    "user.email=sulde-test@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "base",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.write_required_sources(root)

            def blob_oid(content: bytes) -> str:
                material = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
                return hashlib.sha1(material).hexdigest()

            before_order = blob_oid(before[tracked]) < blob_oid(before[second])
            for index in range(1_000):
                reviewed = b"reviewed left " + str(index).encode("ascii") + b"\n"
                reviewed_second = b"reviewed right " + str(index).encode("ascii") + b"\n"
                if (blob_oid(reviewed) < blob_oid(reviewed_second)) != before_order:
                    break
            else:
                self.fail("fixture did not reverse Git object-id ordering")
            projected = intent_guardian._workspace_tracked_tree_sha256(
                root,
                overrides={
                    tracked.resolve(): reviewed,
                    second.resolve(): reviewed_second,
                },
            )
            tracked.write_bytes(reviewed)
            second.write_bytes(reviewed_second)
            subprocess.run(
                ["git", "add", "README.md", "SECOND.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            after_add = intent_guardian._workspace_tracked_tree_sha256(root)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Sulde Test",
                    "-c",
                    "user.email=sulde-test@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "reviewed",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            after_commit = intent_guardian._workspace_tracked_tree_sha256(root)

            self.assertEqual(projected, after_add)
            self.assertEqual(projected, after_commit)

            tracked.write_text("unreviewed drift\n", encoding="utf-8")
            self.assertNotEqual(
                projected,
                intent_guardian._workspace_tracked_tree_sha256(root),
            )
            tracked.write_bytes(reviewed)
            subprocess.run(
                ["git", "update-index", "--chmod=+x", "README.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.assertNotEqual(
                projected,
                intent_guardian._workspace_tracked_tree_sha256(root),
            )

            subprocess.run(
                ["git", "update-index", "--chmod=-x", "README.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            extra = root / "EXTRA.md"
            extra.write_text("extra tracked path\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "EXTRA.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.assertNotEqual(
                projected,
                intent_guardian._workspace_tracked_tree_sha256(root),
            )

    def test_authorization_digest_rejects_nonzero_index_stage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-binding-stage-") as name:
            root = Path(name)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked = root / "README.md"
            tracked.write_text("tracked\n", encoding="utf-8")
            blob = subprocess.run(
                ["git", "hash-object", "-w", "README.md"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout.strip()
            subprocess.run(
                ["git", "update-index", "--index-info"],
                cwd=root,
                input=f"100644 {blob} 1\tREADME.md\n",
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.write_required_sources(root)

            with self.assertRaisesRegex(
                intent_guardian.IntentGuardianError,
                "unsafe path",
            ):
                intent_guardian._workspace_tracked_tree_sha256(root)

    def test_copy_rejects_a_tracked_symlink_even_when_it_stays_in_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-symlink-") as name:
            root = Path(name) / "root"
            output = Path(name) / "output"
            source = root / "scripts" / "kb" / "runtime.py"
            target = root / "local-secret.py"
            source.parent.mkdir(parents=True)
            output.mkdir()
            target.write_text("SECRET = 'must-not-stage'\n", encoding="utf-8")
            try:
                source.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink fixture unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "not a regular file"):
                stage_plugin.copy_entry(
                    root,
                    output,
                    stage_plugin.GitEntry(Path("scripts/kb/runtime.py"), 0o120000),
                    output / "runtime.py",
                )

    def test_missing_required_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-inventory-") as name:
            root = Path(name)
            with mock.patch.object(stage_plugin, "git_entries", return_value=[]):
                with self.assertRaisesRegex(ValueError, "required runtime source"):
                    stage_plugin.release_entries(root)

    def test_non_regular_required_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-release-inventory-") as name:
            root = Path(name)
            self.write_required_sources(root)
            non_regular = root / stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES[0]
            non_regular.unlink()
            non_regular.mkdir()
            with mock.patch.object(stage_plugin, "git_entries", return_value=[]):
                with self.assertRaisesRegex(ValueError, "not a regular file"):
                    stage_plugin.release_entries(root)

    def test_staged_codex_runtime_imports_allowlisted_modules(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-staged-runtime-") as name:
            output = Path(name) / "codex"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(STAGER),
                    "--target",
                    "codex",
                    "--platform",
                    "posix",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            runtime_modules = (
                output / "plugins" / "sulde" / "runtime" / "scripts" / "kb"
            )
            for relative in stage_plugin.REQUIRED_RUNTIME_SOURCE_FILES:
                staged_relative = relative.relative_to(Path("scripts/kb"))
                self.assertTrue((runtime_modules / staged_relative).is_file())

            imported = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import command_template, decision_kernel, "
                        "local_file_operations, approval_timeout_policy, "
                        "native_decision_journal, operational_readiness, "
                        "production_recovery, production_recovery_control, "
                        "production_recovery_targets, sulde_paths, task_ownership; "
                        "from intent_guardian_parts import native_grant, "
                        "pre_execution_control, pre_execution_proof; "
                        "assert approval_timeout_policy.REASSESS_AFTER_SECONDS == 300; "
                        "assert hasattr(command_template, 'literal_git_add_paths'); "
                        "assert hasattr(decision_kernel, 'prepare_human_grant'); "
                        "assert hasattr(native_grant, 'execute_native_grant_decision'); "
                        "assert hasattr(pre_execution_control, 'finalize_pre_execution_probe'); "
                        "assert hasattr(pre_execution_proof, 'observe_probe'); "
                        "import runpy; cli = runpy.run_path('intent-guardian.py'); "
                        "assert callable(cli['prepare_pre_execution_probe']); "
                        "assert callable(cli['finalize_pre_execution_probe']); "
                        "assert hasattr(task_ownership, 'claim_critic_lane_batch')"
                    ),
                ],
                cwd=runtime_modules,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )

        self.assertEqual(imported.returncode, 0, imported.stderr)


if __name__ == "__main__":
    unittest.main()
