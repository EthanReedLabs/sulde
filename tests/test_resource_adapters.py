from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from human_grant import EXECUTION_AUTHORITY_SCHEMA  # noqa: E402
from resource_adapters import (  # noqa: E402
    BROKER_DISPATCH_SCHEMA, DispatchLedger, ResourceAdapterError,
    authorize_resource_action, canonical_digest, classify_device,
    classify_figma, classify_git_metadata, classify_git_worktree_lifecycle,
    classify_local_delete,
    classify_workspace, decode_resource, execute_git_action,
    execute_with_adapter, git_write_lease, prepare_delete_action,
    prepare_device_action, prepare_figma_action, prepare_git_action,
    prepare_workspace_action, resource_debt_blocker, verify_git_action,
    verify_git_worktree_lifecycle, verify_resource_readback,
)


class ResourceAdapterTests(unittest.TestCase):
    provider = "codex"
    session_id = "session-h04"
    task_epoch = "1" * 24
    grant_id = "sha256:" + "a" * 64
    dispatch_id = "gbd-h04-dispatch"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.git_env = {
            **os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, repository: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=repository, env=self.git_env,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def repository(self, name: str, branch: str = "feature") -> Path:
        root = self.base / name
        root.mkdir()
        self.git(root, "init", "-b", branch)
        self.git(root, "config", "user.name", "H04 Fixture")
        self.git(root, "config", "user.email", "h04@example.invalid")
        (root / "tracked.txt").write_text("one\n", encoding="utf-8")
        self.git(root, "add", "--", "tracked.txt")
        self.git(root, "commit", "-m", "initial")
        return root

    def prepare(self, function, resource: dict, *args, **kwargs) -> dict:
        return function(
            resource, *args, grant_identity=self.grant_id,
            dispatch_identity=self.dispatch_id, provider=self.provider,
            session_id=self.session_id, task_epoch=self.task_epoch, **kwargs,
        )

    def authorization(self, action: dict, resource: dict) -> dict:
        schema = resource["schema"]
        if "git-metadata" in schema:
            effect = "read" if action["action"] in {
                "status", "diff", "rev-parse", "show",
            } else "local_write"
        elif "local-delete" in schema:
            effect = "destructive"
        elif "workspace-resource" in schema:
            effect = "read"
        elif "figma-resource" in schema:
            effect = resource["effect"]
        else:
            effect = (
                "read" if action["action"] == "read"
                else "destructive" if action["action"] == "cleanup_test_data"
                else "external_write"
            )
        authority = {
            "schema": EXECUTION_AUTHORITY_SCHEMA,
            "grant_sha256": "sha256:" + "b" * 64,
            "binding_sha256": "sha256:" + "c" * 64,
            "authority_sha256": self.grant_id,
            "provider": action["provider"], "session_id": action["session_id"],
            "task_epoch": action["task_epoch"],
            "subject": deepcopy(action["subject"]),
            "capability": {
                "resource_schema": action["resource_schema"],
                "resource_kind": action["resource_kind"],
                "action": action["action"],
            },
            "effect": {"kind": effect},
            "constraints": deepcopy(action["constraints"]),
            "world_state": deepcopy(action["world_state"]),
            "expires_at": "2099-01-01T00:00:00Z",
            "verifier": deepcopy(action["verifier"]),
            "receipt_id": "receipt-h04",
            "execution_authorized": True,
            "default_policy_recheck_required": False,
        }
        dispatch = {
            "schema": BROKER_DISPATCH_SCHEMA, "transaction_id": "gbt-h04",
            "dispatch_id": self.dispatch_id,
            "consumer_id": "resource-adapter-test",
            "provider": action["provider"], "session_id": action["session_id"],
            "task_epoch": action["task_epoch"],
            "authority_sha256": self.grant_id, "effect": {"kind": effect},
            "execution_authorized": True,
            "default_policy_recheck_required": False,
        }
        return authorize_resource_action(
            action, resource, authority=authority, dispatch=dispatch,
            ledger=DispatchLedger(),
        )

    def test_git_linked_worktree_identity_and_common_dir_substitution(self) -> None:
        repository = self.repository("origin")
        self.git(repository, "branch", "linked")
        linked = self.base / "linked"
        self.git(repository, "worktree", "add", str(linked), "linked")
        resource = classify_git_metadata(linked)
        self.assertEqual(resource["worktree_root"], str(linked))
        self.assertNotEqual(resource["gitdir"], resource["common_gitdir"])
        commondir = Path(resource["gitdir"]) / "commondir"
        commondir.write_text(str(self.base), encoding="utf-8")
        with self.assertRaises(ResourceAdapterError):
            classify_git_metadata(linked)

    def test_git_exact_add_commit_and_read_have_independent_verifiers(self) -> None:
        repository = self.repository("git-flow")
        (repository / "tracked.txt").write_text("two\n", encoding="utf-8")
        before = classify_git_metadata(repository)
        add = self.prepare(
            prepare_git_action, before, "add", paths=["tracked.txt"],
            lease_id="lease-add",
        )
        receipt = execute_git_action(add, before, self.authorization(add, before))
        self.assertEqual(verify_git_action(add, before, receipt)["status"], "passed")
        staged = classify_git_metadata(repository)
        commit = self.prepare(
            prepare_git_action, staged, "commit", message="exact commit",
            lease_id="lease-commit",
        )
        receipt = execute_git_action(
            commit, staged, self.authorization(commit, staged)
        )
        self.assertEqual(
            verify_git_action(commit, staged, receipt)["status"], "passed"
        )
        current = classify_git_metadata(repository)
        read = self.prepare(
            prepare_git_action, current, "status", read_arguments=["--short"]
        )
        receipt = execute_git_action(
            read, current, self.authorization(read, current)
        )
        self.assertEqual(
            verify_git_action(read, current, receipt)["status"], "passed"
        )

    def test_git_exact_merge_binds_both_parents_and_ref(self) -> None:
        repository = self.repository("merge-flow")
        base_oid = self.git(repository, "rev-parse", "HEAD")
        self.git(repository, "checkout", "-b", "topic")
        (repository / "topic.txt").write_text("topic\n", encoding="utf-8")
        self.git(repository, "add", "--", "topic.txt")
        self.git(repository, "commit", "-m", "topic")
        topic_oid = self.git(repository, "rev-parse", "HEAD")
        self.git(repository, "checkout", "feature")
        resource = classify_git_metadata(repository)
        action = self.prepare(
            prepare_git_action, resource, "merge", message="merge topic",
            parent_oids=[base_oid, topic_oid], merge_ref="topic",
            lease_id="lease-merge",
        )
        receipt = execute_git_action(
            action, resource, self.authorization(action, resource)
        )
        self.assertEqual(
            verify_git_action(action, resource, receipt)["status"], "passed"
        )

    def test_git_rejects_main_broad_alias_control_and_drift(self) -> None:
        main = self.repository("main-repository", branch="main")
        with self.assertRaisesRegex(ResourceAdapterError, "release branch"):
            self.prepare(
                prepare_git_action, classify_git_metadata(main), "add",
                paths=["tracked.txt"], lease_id="lease-main",
            )
        repository = self.repository("negative-git")
        (repository / "directory").mkdir()
        (repository / "directory" / "nested.txt").write_text("x\n", encoding="utf-8")
        (repository / "alias.txt").symlink_to(repository / "tracked.txt")
        resource = classify_git_metadata(repository)
        for paths in (
            ["."], ["*.txt"], [":(glob)*"], ["directory"], ["alias.txt"],
            [".git/HEAD"],
        ):
            with self.subTest(paths=paths), self.assertRaises(ResourceAdapterError):
                self.prepare(
                    prepare_git_action, resource, "add", paths=paths,
                    lease_id="lease-negative",
                )
        (repository / "tracked.txt").write_text("approved\n", encoding="utf-8")
        current = classify_git_metadata(repository)
        action = self.prepare(
            prepare_git_action, current, "add", paths=["tracked.txt"],
            lease_id="lease-drift",
        )
        authorization = self.authorization(action, current)
        (repository / "tracked.txt").write_text("substituted\n", encoding="utf-8")
        with self.assertRaisesRegex(ResourceAdapterError, "content drifted"):
            execute_git_action(action, current, authorization)

    def test_git_single_writer_and_dispatch_replay_fail_closed(self) -> None:
        resource = classify_git_metadata(self.repository("lease"))
        with git_write_lease(resource, "writer-one"):
            with self.assertRaisesRegex(ResourceAdapterError, "active writer"):
                with git_write_lease(resource, "writer-two"):
                    self.fail("second writer entered")
        ledger = DispatchLedger()
        ledger.consume("dispatch")
        with self.assertRaisesRegex(ResourceAdapterError, "replay"):
            ledger.consume("dispatch")

    def lifecycle_repository(self, name: str) -> tuple[Path, Path]:
        repository = self.repository(name, branch="main")
        (repository / ".worktrees").mkdir()
        self.git(repository, "branch", "dev")
        dev = repository / ".worktrees" / "dev"
        self.git(repository, "worktree", "add", str(dev), "dev")
        return repository, dev

    def test_worktree_attach_existing_accepts_unrelated_primary_dirty_state(self) -> None:
        repository, _dev = self.lifecycle_repository("attach-existing")
        self.git(repository, "branch", "task/as-eric/restored")
        (repository / "tracked.txt").write_text("dirty but preserved\n", encoding="utf-8")
        target = repository / ".worktrees" / "restored"
        resource = classify_git_worktree_lifecycle(
            repository, target, operation="attach_existing",
            branch="task/as-eric/restored", base="task/as-eric/restored",
        )
        self.assertEqual(resource["branch_state"], "present")
        self.assertFalse(resource["branch_checked_out"])
        self.git(
            repository, "worktree", "add", str(target),
            "task/as-eric/restored",
        )
        verification = verify_git_worktree_lifecycle(resource)
        self.assertEqual(verification["status"], "passed", verification)

    def test_worktree_create_branch_binds_local_base_and_post_state(self) -> None:
        repository, _dev = self.lifecycle_repository("create-branch")
        target = repository / ".worktrees" / "new-task"
        resource = classify_git_worktree_lifecycle(
            repository, target, operation="create_branch",
            branch="task/new-task", base="dev",
        )
        self.assertEqual(resource["branch_state"], "absent")
        self.git(
            repository, "worktree", "add", "-b", "task/new-task",
            str(target), "dev",
        )
        verification = verify_git_worktree_lifecycle(resource)
        self.assertEqual(verification["status"], "passed", verification)

    def test_worktree_lifecycle_rejects_identity_and_state_ambiguity(self) -> None:
        repository, dev = self.lifecycle_repository("lifecycle-negative")
        self.git(repository, "branch", "task/restorable")
        outside = self.base / "outside-worktree"
        cases = (
            {
                "target": outside, "operation": "attach_existing",
                "branch": "task/restorable", "base": "task/restorable",
            },
            {
                "target": repository / ".worktrees" / "missing",
                "operation": "attach_existing", "branch": "task/missing",
                "base": "task/missing",
            },
            {
                "target": repository / ".worktrees" / "duplicate",
                "operation": "create_branch", "branch": "task/restorable",
                "base": "dev",
            },
            {
                "target": repository / ".worktrees" / "protected",
                "operation": "attach_existing", "branch": "dev", "base": "dev",
            },
            {
                "target": repository / ".worktrees" / "ref-conflict",
                "operation": "create_branch", "branch": "dev/child",
                "base": "dev",
            },
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ResourceAdapterError):
                classify_git_worktree_lifecycle(repository, **case)
        self.assertTrue(dev.is_dir())

    def test_worktree_verifier_detects_unrelated_status_drift(self) -> None:
        repository, _dev = self.lifecycle_repository("lifecycle-drift")
        self.git(repository, "branch", "task/drift")
        target = repository / ".worktrees" / "drift"
        resource = classify_git_worktree_lifecycle(
            repository, target, operation="attach_existing",
            branch="task/drift", base="task/drift",
        )
        self.git(repository, "worktree", "add", str(target), "task/drift")
        (repository / "tracked.txt").write_text("concurrent drift\n", encoding="utf-8")
        verification = verify_git_worktree_lifecycle(resource)
        self.assertEqual(verification["status"], "failed")
        self.assertFalse(
            verification["evidence"]["primary_status_unchanged"]
        )

    def test_delete_exact_tree_and_parent_verifier(self) -> None:
        workspace = self.base / "delete-workspace"
        target = workspace / "failed-package"
        target.mkdir(parents=True)
        (target / "artifact.tmp").write_text("temporary\n", encoding="utf-8")
        resource = classify_local_delete(
            target, workspace_root=workspace, allowed_effect="delete_tree"
        )
        action = self.prepare(prepare_delete_action, resource, recursive=True)
        def fake_delete(selected: dict, current: dict) -> dict:
            self.assertTrue(selected["constraints"]["exact_target_only"])
            shutil.rmtree(current["target"])
            return {"removed": current["target"]}
        receipt = execute_with_adapter(
            action, resource, self.authorization(action, resource), fake_delete
        )
        verification = verify_resource_readback(action, receipt, {})
        self.assertEqual(verification["status"], "passed")
        self.assertFalse(verification["reusable_authority"])

    def test_delete_rejects_sibling_symlink_roots_and_identity_drift(self) -> None:
        workspace = self.base / "workspace"
        workspace.mkdir()
        sibling = self.base / "sibling"
        sibling.mkdir()
        for target in (sibling, workspace, Path("/"), Path.home()):
            with self.subTest(target=target), self.assertRaises(ResourceAdapterError):
                classify_local_delete(
                    target, workspace_root=workspace, allowed_effect="delete_tree"
                )
        target = workspace / "target"
        target.mkdir()
        (target / "value").write_text("one", encoding="utf-8")
        alias = workspace / "alias"
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ResourceAdapterError):
            classify_local_delete(
                alias, workspace_root=workspace, allowed_effect="delete_tree"
            )
        resource = classify_local_delete(
            target, workspace_root=workspace, allowed_effect="delete_tree"
        )
        action = self.prepare(prepare_delete_action, resource, recursive=True)
        authorization = self.authorization(action, resource)
        (target / "value").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ResourceAdapterError, "identity drifted"):
            execute_with_adapter(action, resource, authorization, lambda *_: {})

    def test_workspace_grant_is_exact_and_rejects_sibling_provider_session(self) -> None:
        original = self.base / "original"
        original.mkdir()
        granted = self.repository("granted")
        sibling = self.repository("ungranted")
        resource = classify_workspace(
            granted, original_workspace=original, provider=self.provider,
            session_id=self.session_id,
        )
        action = self.prepare(prepare_workspace_action, resource)
        receipt = execute_with_adapter(
            action, resource, self.authorization(action, resource),
            lambda selected, current: {"workspace": current["workspace_root"]},
        )
        evidence = {
            "workspace_identity": resource["workspace_identity"],
            "repository_id": resource["repository_id"],
        }
        self.assertEqual(
            verify_resource_readback(action, receipt, evidence)["status"], "passed"
        )
        sibling_resource = classify_workspace(
            sibling, original_workspace=original, provider=self.provider,
            session_id=self.session_id,
        )
        with self.assertRaisesRegex(ResourceAdapterError, "drifted"):
            self.authorization(action, sibling_resource)
        with self.assertRaisesRegex(ResourceAdapterError, "provider/session"):
            prepare_workspace_action(
                resource, grant_identity=self.grant_id,
                dispatch_identity=self.dispatch_id, provider="other",
                session_id=self.session_id, task_epoch=self.task_epoch,
            )

    def test_figma_binds_file_node_page_mutation_payload_and_readback(self) -> None:
        resource = classify_figma(
            "use_figma",
            {
                "url": "https://figma.com/design/File_123/name?node-id=12%3A34",
                "pageId": "page:1", "mutationKind": "set_text",
                "payload": {"text": "approved"},
                "readback": {"kind": "get_design_context", "node": "12:34"},
            },
            provider=self.provider,
        )
        self.assertEqual((resource["file_key"], resource["node_id"]), ("File_123", "12:34"))
        action = self.prepare(prepare_figma_action, resource)
        receipt = execute_with_adapter(
            action, resource, self.authorization(action, resource),
            lambda selected, current: {"fake": True},
        )
        evidence = {
            "resource_id": resource["resource_id"],
            "payload_sha256": resource["payload_sha256"],
            "readback_sha256": resource["readback_sha256"],
        }
        self.assertEqual(
            verify_resource_readback(action, receipt, evidence)["status"], "passed"
        )
        wrong = {**evidence, "readback_sha256": "sha256:" + "0" * 64}
        self.assertEqual(
            verify_resource_readback(action, receipt, wrong)["status"], "failed"
        )
        with self.assertRaisesRegex(ResourceAdapterError, "readback"):
            classify_figma(
                "use_figma", {"fileKey": "File_123", "nodeId": "12:34",
                "mutationKind": "set_text", "payload": {}},
            )
        with self.assertRaisesRegex(ResourceAdapterError, "provider drift"):
            prepare_figma_action(
                resource, grant_identity=self.grant_id,
                dispatch_identity=self.dispatch_id, provider="other",
                session_id=self.session_id, task_epoch=self.task_epoch,
            )

    def test_device_binds_serial_package_artifact_and_denies_unsafe_actions(self) -> None:
        artifact = self.base / "fixture.apk"
        artifact.write_bytes(b"fixture-apk")
        resource = classify_device(
            provider=self.provider, serial="device-01",
            package="com.example.fixture", artifact=artifact,
            data_namespace="test:fixture", original_user_data=False,
        )
        action = self.prepare(prepare_device_action, resource, "install")
        receipt = execute_with_adapter(
            action, resource, self.authorization(action, resource),
            lambda selected, current: {"installed": current["package"]},
        )
        self.assertEqual(
            verify_resource_readback(
                action, receipt,
                {"resource_id": resource["resource_id"], "operation": "install"},
            )["status"], "passed",
        )
        for operation in ("purchase", "uninstall", "data_clear", "clear_data"):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                ResourceAdapterError, "denied"
            ):
                self.prepare(prepare_device_action, resource, operation)
        original_data = classify_device(
            provider=self.provider, serial="device-01",
            package="com.example.fixture", data_namespace="user:original",
            original_user_data=True,
        )
        with self.assertRaisesRegex(ResourceAdapterError, "test data"):
            self.prepare(prepare_device_action, original_data, "cleanup_test_data")
        authorization = self.authorization(action, resource)
        artifact.write_bytes(b"substituted")
        with self.assertRaisesRegex(ResourceAdapterError, "artifact"):
            execute_with_adapter(action, resource, authorization, lambda *_: {})

    def test_strict_decoders_and_resource_scoped_debt_fail_closed(self) -> None:
        resource = classify_figma(
            "use_figma", {"fileKey": "File", "nodeId": "1:2",
            "mutationKind": "set_text", "payload": {"text": "x"},
            "readback": {"node": "1:2"}}, provider=self.provider,
        )
        tampered = deepcopy(resource)
        tampered["unknown"] = True
        with self.assertRaisesRegex(ResourceAdapterError, "fields invalid"):
            decode_resource(tampered)
        material = deepcopy(resource)
        material.pop("resource_id")
        material["effect"] = 1
        malformed = deepcopy(material)
        malformed["resource_id"] = canonical_digest(resource["schema"], material)
        with self.assertRaises(ResourceAdapterError):
            decode_resource(malformed)
        action = self.prepare(prepare_figma_action, resource)
        terminal = [{"resource_id": resource["resource_id"], "resource_kind": "figma",
            "effect": "external_write", "state": "terminal"}]
        pending = [{"resource_id": resource["resource_id"], "resource_kind": "figma",
            "effect": "external_write", "state": "pending"}]
        unrelated = [{"resource_id": "", "resource_kind": "device",
            "effect": "external_write", "state": "pending"}]
        self.assertIsNone(resource_debt_blocker(action, terminal))
        self.assertEqual(resource_debt_blocker(action, pending), pending[0])
        self.assertIsNone(resource_debt_blocker(action, unrelated))


if __name__ == "__main__":
    unittest.main()
