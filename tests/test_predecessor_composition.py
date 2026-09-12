#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "scripts", "kb", "predecessor_composition.py")
SPEC = importlib.util.spec_from_file_location("predecessor_composition", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
pc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pc)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: str, data: bytes, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    os.chmod(path, mode)


def git(repository: str, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", repository, *arguments],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    if result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", "replace"))
    return result.stdout


class TreePathValidationTests(unittest.TestCase):
    def test_complete_tree_and_delta_target_path_rules_are_separate(self) -> None:
        control_path = "guardian-program/events.jsonl"
        glob_path = "history/[accepted]*?.txt"
        control_oid = "1" * 40
        glob_oid = "2" * 40
        output = (
            f"100644 blob {control_oid}\t{control_path}\0"
            f"100755 blob {glob_oid}\t{glob_path}\0"
        ).encode("utf-8")

        with mock.patch.object(pc, "_git", return_value=output):
            entries = pc._tree_entries("/unused-repository", "base-tree")

        self.assertEqual(entries[control_path], (0o100644, control_oid))
        self.assertEqual(entries[glob_path], (0o100755, glob_oid))

        protected_aliases = (
            "guardian-program/events.jsonl",
            "guardian-program/EVENTS.JSONL",
            "guardian-program/ｅｖｅｎｔｓ.jsonl",
        )
        with (
            mock.patch.object(pc, "_read_accepted_blob") as accepted_blob,
            mock.patch.object(pc, "_git") as git_object,
        ):
            for operation in ("add", "modify", "delete"):
                for path in protected_aliases:
                    with self.subTest(operation=operation, path=path):
                        with self.assertRaises(pc.CompositionError):
                            pc._delta_path(path, f"{operation} target")
        accepted_blob.assert_not_called()
        git_object.assert_not_called()


class Fixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="predecessor-composition-")
        # macOS exposes its temporary root through /var -> /private/var.  Product
        # code intentionally rejects symlink ancestors, so synthetic inputs bind
        # the canonical physical path.
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.repository = os.path.join(self.root, "candidate")
        self.artifacts = os.path.join(self.root, "artifacts")
        self.receipts = os.path.join(self.root, "ready")
        self.control = os.path.join(self.root, "control")
        os.mkdir(self.repository, 0o700)
        os.mkdir(self.artifacts, 0o700)
        os.mkdir(self.receipts, 0o700)
        os.mkdir(self.control, 0o700)
        os.mkdir(os.path.join(self.control, "snapshots"), 0o700)
        os.mkdir(os.path.join(self.control, "accepted-blobs"), 0o700)
        deployment = {
            "schema": pc.CONTROL_DEPLOYMENT_SCHEMA,
            "generation": 14,
        }
        write(os.path.join(self.control, "deployment.json"), pc._canonical_bytes(deployment) + b"\n", 0o600)
        self.control_resolver = pc._test_control_root_resolver(self.control)
        git(self.repository, "init", "-q")
        git(self.repository, "config", "user.name", "Fixture")
        git(self.repository, "config", "user.email", "fixture@example.invalid")
        self.base_modify = b"before modify\n"
        self.base_delete = b"before delete\n"
        self.base_control_path = "guardian-program/events.jsonl"
        self.base_control = b'{"historical":"control"}\n'
        self.base_glob_path = "history/[accepted]*?.txt"
        self.base_glob = b"historical glob-bearing path\n"
        write(os.path.join(self.repository, "modify.txt"), self.base_modify)
        write(os.path.join(self.repository, "delete.txt"), self.base_delete)
        write(os.path.join(self.repository, "keep.txt"), b"keep\n")
        write(os.path.join(self.repository, "nested", "file.txt"), b"nested before\n")
        write(os.path.join(self.repository, self.base_control_path), self.base_control)
        write(os.path.join(self.repository, self.base_glob_path), self.base_glob, 0o755)
        git(
            self.repository,
            "--literal-pathspecs",
            "add",
            "--",
            "modify.txt",
            "delete.txt",
            "keep.txt",
            "nested/file.txt",
            self.base_control_path,
            self.base_glob_path,
        )
        git(self.repository, "commit", "-q", "-m", "base")
        self.base = git(self.repository, "rev-parse", "HEAD").decode("ascii").strip()

        self.after_modify = b"after modify\n"
        self.after_add = b"new accepted bytes\n"
        write(os.path.join(self.repository, "modify.txt"), self.after_modify)
        os.unlink(os.path.join(self.repository, "delete.txt"))
        write(os.path.join(self.repository, "add.txt"), self.after_add)

        self.successor_definition = self._artifact("successor-task.json", b'{"task":"successor"}\n')
        self.successor_brief = self._artifact("successor-brief.md", b"successor brief\n")
        self.task_definition = self._artifact("p1-task.json", b'{"task":"p1"}\n')
        self.event = self._artifact("p1-event.json", b"{}\n")
        self.evidence = self._artifact("p1-evidence.json", b'{"result":"pass"}\n')
        self.plan = {
            "schema": pc.PLAN_SCHEMA,
            "program_id": "guardian-program-test",
            "control_generation": 14,
            "authority_snapshot_id": "snapshot-initial",
            "target_id": "successor-baseline",
            "successor_task_id": "T06-successor",
            "logical_base_commit": self.base,
            "successor_task_definition": self.successor_definition,
            "successor_brief": self.successor_brief,
            "helper_generation": 2,
            "commit": {
                "author_name": "Sulde Composer",
                "author_email": "composer@example.invalid",
                "committer_name": "Sulde Composer",
                "committer_email": "composer@example.invalid",
                "timestamp": 1700000000,
                "timezone": "+0000",
                "message": "synthetic accepted predecessor baseline\n",
            },
            "predecessors": [
                {
                    "task_id": "P1",
                    "status": "accepted",
                    "verification_run": {"id": "verify-1", "status": "accepted"},
                    "accepted_event": {
                        "id": "accepted-P1-7",
                        "sequence": 7,
                        "status": "accepted",
                        "path": self.event["path"],
                        "sha256": self.event["sha256"],
                    },
                    "supersession": {"status": "current", "superseded_by": None},
                    "task_definition": self.task_definition,
                    "source_root_id": "candidate-root",
                    "generation": 1,
                    "parent_generation": 0,
                    "dependencies": [],
                    "dependency_closure": [],
                    "evidence": [
                        {"id": "evidence-1", "path": self.evidence["path"], "sha256": self.evidence["sha256"]}
                    ],
                    "delta": [
                        {
                            "path": "add.txt",
                            "operation": "add",
                            "before_sha256": pc.ZERO_SHA256,
                            "after_sha256": sha(self.after_add),
                            "size": len(self.after_add),
                            "mode": 0o100644,
                            "accepted_blob": self._freeze_blob(self.after_add),
                        },
                        {
                            "path": "modify.txt",
                            "operation": "modify",
                            "before_sha256": sha(self.base_modify),
                            "after_sha256": sha(self.after_modify),
                            "size": len(self.after_modify),
                            "mode": 0o100644,
                            "accepted_blob": self._freeze_blob(self.after_modify),
                        },
                        {
                            "path": "delete.txt",
                            "operation": "delete",
                            "before_sha256": sha(self.base_delete),
                            "after_sha256": pc.ZERO_SHA256,
                            "size": 0,
                            "mode": 0o100644,
                            "accepted_blob": None,
                        },
                    ],
                }
            ],
            "source_roots": [
                {
                    "id": "candidate-root",
                    "path": self.repository,
                    "task_ids": ["P1"],
                    "cumulative_inventory": [
                        {
                            "path": "add.txt",
                            "selected_predecessor": "P1",
                            "state": "present",
                            "sha256": sha(self.after_add),
                            "size": len(self.after_add),
                            "mode": 0o100644,
                        },
                        {
                            "path": "delete.txt",
                            "selected_predecessor": "P1",
                            "state": "absent",
                            "sha256": pc.ZERO_SHA256,
                            "size": 0,
                            "mode": 0o100644,
                        },
                        {
                            "path": "modify.txt",
                            "selected_predecessor": "P1",
                            "state": "present",
                            "sha256": sha(self.after_modify),
                            "size": len(self.after_modify),
                            "mode": 0o100644,
                        },
                    ],
                }
            ],
        }
        self.sync_events(self.plan)

    def _artifact(self, name: str, data: bytes) -> dict[str, str]:
        path = os.path.join(self.artifacts, name)
        write(path, data)
        return {"path": path, "sha256": sha(data)}

    def _freeze_blob(self, data: bytes) -> dict[str, object]:
        digest = sha(data)
        directory = os.path.join(self.control, "accepted-blobs", digest[:2])
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        path = os.path.join(directory, digest)
        if not os.path.exists(path):
            write(path, data, 0o600)
        return {"sha256": digest, "size": len(data)}

    def close(self) -> None:
        self.temporary.cleanup()

    def sync_events(self, plan: dict[str, object]) -> None:
        for predecessor in plan["predecessors"]:
            document = pc._accepted_event_document(plan, predecessor)
            raw = pc._canonical_bytes(document) + b"\n"
            path = predecessor["accepted_event"]["path"]
            existing = None
            try:
                with open(path, "rb") as handle:
                    existing = handle.read()
            except FileNotFoundError:
                pass
            if existing != raw:
                write(path, raw)
            predecessor["accepted_event"]["sha256"] = sha(raw)

    def authority(self, plan: dict[str, object] | None = None) -> object:
        selected = self.plan if plan is None else plan
        self.sync_events(selected)
        seed = copy.deepcopy(selected)
        seed["authority_snapshot_id"] = "snapshot-seed"
        selected["authority_snapshot_id"] = "snapshot-" + sha(pc._canonical_bytes(seed))[:20]
        snapshot = pc._authority_projection(
            pc.validate_plan(selected),
            authority_kind=pc.AUTHORITY_KIND_SYNTHETIC,
            resolver_kind=pc.RESOLVER_KIND_TEST,
        )
        program_dir = os.path.join(self.control, "snapshots", selected["program_id"])
        os.makedirs(program_dir, mode=0o700, exist_ok=True)
        os.chmod(program_dir, 0o700)
        snapshot_path = os.path.join(program_dir, selected["authority_snapshot_id"] + ".json")
        raw = pc._canonical_bytes(snapshot) + b"\n"
        if os.path.exists(snapshot_path):
            with open(snapshot_path, "rb") as handle:
                self_bytes = handle.read()
            if self_bytes != raw:
                raise AssertionError("synthetic authority snapshot id collision")
        else:
            write(snapshot_path, raw, 0o600)
        return pc._load_synthetic_authority_for_test(
            selected["program_id"],
            selected["authority_snapshot_id"],
            capability=self.control_resolver,
        )

    def only_modify(self) -> None:
        try:
            os.unlink(os.path.join(self.repository, "add.txt"))
        except FileNotFoundError:
            pass
        write(os.path.join(self.repository, "delete.txt"), self.base_delete)
        self.plan["predecessors"][0]["delta"] = [self.plan["predecessors"][0]["delta"][1]]
        self.plan["source_roots"][0]["cumulative_inventory"] = [
            self.plan["source_roots"][0]["cumulative_inventory"][2]
        ]

    def add_chained_predecessor(self) -> None:
        self.only_modify()
        first = self.plan["predecessors"][0]
        second = copy.deepcopy(first)
        second["task_id"] = "P2"
        second["verification_run"] = {"id": "verify-2", "status": "accepted"}
        second["accepted_event"]["sequence"] = 8
        second["accepted_event"]["id"] = "accepted-P2-8"
        event = self._artifact("p2-event.json", b"{}\n")
        second["accepted_event"]["path"] = event["path"]
        second["accepted_event"]["sha256"] = event["sha256"]
        second["task_definition"] = self._artifact("p2-task.json", b'{"task":"p2"}\n')
        evidence = self._artifact("p2-evidence.json", b'{"result":"pass2"}\n')
        second["evidence"] = [{"id": "evidence-2", "path": evidence["path"], "sha256": evidence["sha256"]}]
        second["generation"] = 2
        second["parent_generation"] = 1
        second["dependencies"] = ["P1"]
        second["dependency_closure"] = ["P1"]
        second["delta"][0]["before_sha256"] = first["delta"][0]["after_sha256"]
        self.plan["predecessors"].append(second)
        self.plan["source_roots"][0]["task_ids"].append("P2")
        self.plan["source_roots"][0]["cumulative_inventory"][0]["selected_predecessor"] = "P2"
        self.plan["helper_generation"] = 3
        self.sync_events(self.plan)


class CompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()

    def tearDown(self) -> None:
        self.fx.close()

    def assertCompositionError(self, callable_object, *args, **kwargs) -> None:
        with self.assertRaises(pc.CompositionError):
            callable_object(*args, **kwargs)

    def compose(
        self,
        plan: dict[str, object] | None = None,
        receipt_root: str | None = None,
        **kwargs,
    ) -> dict[str, object]:
        selected = self.fx.plan if plan is None else plan
        authority = self.fx.authority(selected)
        return pc.compose(
            selected,
            self.fx.repository,
            self.fx.receipts if receipt_root is None else receipt_root,
            authority=authority,
            **kwargs,
        )

    def verify(
        self,
        plan: dict[str, object] | None = None,
        receipt_root: str | None = None,
        **kwargs,
    ) -> dict[str, object]:
        selected = self.fx.plan if plan is None else plan
        authority = self.fx.authority(selected)
        return pc.verify_receipt(
            selected,
            self.fx.repository,
            self.fx.receipts if receipt_root is None else receipt_root,
            authority=authority,
            **kwargs,
        )

    def recover(
        self,
        plan: dict[str, object] | None = None,
        receipt_root: str | None = None,
    ) -> dict[str, object]:
        selected = self.fx.plan if plan is None else plan
        authority = self.fx.authority(selected)
        return pc.recover(
            selected,
            self.fx.repository,
            self.fx.receipts if receipt_root is None else receipt_root,
            authority=authority,
        )

    def test_compose_add_modify_delete_ready_and_real_synthetic_commit(self) -> None:
        base_entries = pc._tree_entries(self.fx.repository, self.fx.base)
        result = self.compose()
        self.assertEqual(result["state"], "SYNTHETIC_READY")
        self.assertIs(result["consumable"], False)
        self.assertNotEqual(result["commit_oid"], self.fx.base)
        self.assertEqual(git(self.fx.repository, "show", f"{result['commit_oid']}:add.txt"), self.fx.after_add)
        self.assertEqual(git(self.fx.repository, "show", f"{result['commit_oid']}:modify.txt"), self.fx.after_modify)
        final_entries = pc._tree_entries(self.fx.repository, result["tree_oid"])
        self.assertEqual(final_entries[self.fx.base_control_path], base_entries[self.fx.base_control_path])
        self.assertEqual(final_entries[self.fx.base_glob_path], base_entries[self.fx.base_glob_path])
        self.assertEqual(
            git(self.fx.repository, "show", f"{result['commit_oid']}:{self.fx.base_control_path}"),
            self.fx.base_control,
        )
        self.assertEqual(
            git(self.fx.repository, "show", f"{result['commit_oid']}:{self.fx.base_glob_path}"),
            self.fx.base_glob,
        )
        missing = subprocess.run(
            ["git", "-C", self.fx.repository, "cat-file", "-e", f"{result['commit_oid']}:delete.txt"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        with open(result["receipt_path"], "rb") as handle:
            receipt = json.loads(handle.read())
        self.assertEqual(receipt["state_history"], pc.SYNTHETIC_READY_STATES)
        self.assertEqual(receipt["commit_oid"], result["commit_oid"])
        self.assertEqual(os.stat(result["receipt_path"]).st_mode & 0o777, 0o600)
        self.assertEqual(receipt["authority"]["control_root"]["path"], self.fx.control)
        self.assertEqual(receipt["authority"]["control_root"]["mode"], 0o700)
        self.assertEqual(receipt["authority"]["control_root"]["uid"], os.geteuid())
        self.assertEqual(receipt["authority"]["control_root"]["deployment_generation"], 14)

    def test_synthetic_logical_base_preserves_control_entry_after_minimal_delta(self) -> None:
        repository = os.path.join(self.fx.root, "synthetic-logical-base")
        base = self.fx.base
        git(self.fx.repository, "clone", "-q", "--no-local", "--no-checkout", self.fx.repository, repository)
        git(repository, "checkout", "-q", "--detach", base)

        base_entries = pc._tree_entries(repository, base)
        control_path = "guardian-program/events.jsonl"
        self.assertIn(control_path, base_entries)
        preserved_entry = base_entries[control_path]
        preserved_bytes = git(repository, "cat-file", "blob", preserved_entry[1])

        probe_path = "t21-minimal-accepted-delta.txt"
        self.assertNotIn(probe_path, base_entries)
        probe = b"minimal accepted delta for synthetic logical base\n"
        write(os.path.join(repository, probe_path), probe)
        self.fx.repository = repository
        self.fx.base = base
        self.fx.plan["logical_base_commit"] = base
        self.fx.plan["target_id"] = "synthetic-logical-base-regression"
        self.fx.plan["predecessors"][0]["delta"] = [
            {
                "path": probe_path,
                "operation": "add",
                "before_sha256": pc.ZERO_SHA256,
                "after_sha256": sha(probe),
                "size": len(probe),
                "mode": 0o100644,
                "accepted_blob": self.fx._freeze_blob(probe),
            }
        ]
        self.fx.plan["source_roots"][0] = {
            "id": "candidate-root",
            "path": repository,
            "task_ids": ["P1"],
            "cumulative_inventory": [
                {
                    "path": probe_path,
                    "selected_predecessor": "P1",
                    "state": "present",
                    "sha256": sha(probe),
                    "size": len(probe),
                    "mode": 0o100644,
                }
            ],
        }
        self.fx.sync_events(self.fx.plan)

        result = self.compose()
        final_entries = pc._tree_entries(repository, result["tree_oid"])
        self.assertEqual(final_entries[control_path], preserved_entry)
        self.assertEqual(
            git(repository, "cat-file", "blob", final_entries[control_path][1]),
            preserved_bytes,
        )

    def test_same_plan_target_is_idempotent_and_bind_is_pure(self) -> None:
        first = self.compose()
        second = self.compose()
        self.assertEqual(first, second)
        bound = self.verify(bind_run_id="successor-run-9")
        self.assertEqual(bound["state"], "SYNTHETIC_BOUND_TO_RUN")
        self.assertEqual(bound["commit_oid"], first["commit_oid"])

    def test_plan_and_receipt_are_strict_plain_json(self) -> None:
        for mutate in (
            lambda plan: plan.update(extra=True),
            lambda plan: plan.pop("target_id"),
            lambda plan: plan.update(helper_generation=True),
            lambda plan: plan["predecessors"][0]["delta"][0].update(size="19"),
            lambda plan: plan["predecessors"][0]["delta"][0]["accepted_blob"].update(
                path="/caller/selected/blob"
            ),
            lambda plan: plan.update(control_root="/caller/selected/control"),
        ):
            candidate = copy.deepcopy(self.fx.plan)
            mutate(candidate)
            self.assertCompositionError(pc.validate_plan, candidate)
        self.assertCompositionError(pc.load_plan, '{"schema":1,"schema":2}')

        calls = {"count": 0}

        class Magic(dict):
            def items(self):  # pragma: no cover - must never be called
                calls["count"] += 1
                return super().items()

            def __str__(self):  # pragma: no cover - must never be called
                calls["count"] += 1
                return "magic"

        self.assertCompositionError(pc.validate_plan, Magic())
        self.assertEqual(calls["count"], 0)

        result = self.compose()
        with open(result["receipt_path"], "rb") as handle:
            receipt = json.load(handle)
        self.assertEqual(pc.load_receipt(json.dumps(receipt)), receipt)
        bad_bool = copy.deepcopy(receipt)
        bad_bool["blobs"][0]["size"] = True
        self.assertCompositionError(pc.load_receipt, json.dumps(bad_bool))
        bad_unknown = copy.deepcopy(receipt)
        bad_unknown["source_roots"][0]["unexpected"] = "field"
        self.assertCompositionError(pc.load_receipt, json.dumps(bad_unknown))

    def test_artifact_manifest_evidence_and_event_sha_drift(self) -> None:
        authority = self.fx.authority(self.fx.plan)
        paths = [
            self.fx.successor_definition["path"],
            self.fx.task_definition["path"],
            self.fx.event["path"],
            self.fx.evidence["path"],
        ]
        originals = []
        for path in paths:
            with open(path, "rb") as handle:
                originals.append(handle.read())
        for path, original in zip(paths, originals):
            with self.subTest(path=os.path.basename(path)):
                write(path, original + b"drift")
                self.assertCompositionError(
                    pc.compose,
                    self.fx.plan,
                    self.fx.repository,
                    self.fx.receipts,
                    authority=authority,
                )
                write(path, original)

    def test_nonaccepted_superseded_and_verification_status_rejected(self) -> None:
        for field, value in (("status", "superseded"), ("status", "running")):
            candidate = copy.deepcopy(self.fx.plan)
            candidate["predecessors"][0][field] = value
            self.assertCompositionError(pc.validate_plan, candidate)
        candidate = copy.deepcopy(self.fx.plan)
        candidate["predecessors"][0]["verification_run"]["status"] = "failed"
        self.assertCompositionError(pc.validate_plan, candidate)

    def test_authority_requires_fixed_root_attestation_and_event_projection(self) -> None:
        untrusted = pc.compose(
            self.fx.plan,
            self.fx.repository,
            self.fx.receipts,
            authority={"caller": "self-asserted"},
        )
        self.assertEqual(untrusted["state"], pc.AUTHORITY_UNATTESTED)
        self.assertFalse(os.path.exists(os.path.join(self.fx.receipts, "targets")))

        authority = self.fx.authority(self.fx.plan)
        raw_snapshot = authority.raw
        untrusted_bytes = pc.compose(
            self.fx.plan,
            self.fx.repository,
            self.fx.receipts,
            authority=raw_snapshot,
        )
        self.assertEqual(untrusted_bytes["state"], pc.AUTHORITY_UNATTESTED)

        base_event = pc._accepted_event_document(self.fx.plan, self.fx.plan["predecessors"][0])
        mutations = {
            "rejected": lambda event: event.update(task_state="rejected"),
            "blocked": lambda event: event.update(task_state="blocked"),
            "superseded": lambda event: event["supersession"].update(
                status="superseded", superseded_by="accepted-newer"
            ),
            "different-run": lambda event: event["verification_run"].update(id="verify-other"),
            "failed-run": lambda event: event["verification_run"].update(status="failed"),
            "different-event": lambda event: event.update(event_id="accepted-other"),
            "different-task": lambda event: event.update(task_id="P-other"),
            "different-generation": lambda event: event.update(generation=9),
            "different-evidence": lambda event: event.update(evidence_binding_sha256=sha(b"other evidence")),
            "different-delta": lambda event: event.update(delta_binding_sha256=sha(b"other delta")),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = copy.deepcopy(self.fx.plan)
                event = copy.deepcopy(base_event)
                mutate(event)
                raw = pc._canonical_bytes(event) + b"\n"
                write(self.fx.event["path"], raw)
                candidate["predecessors"][0]["accepted_event"]["sha256"] = sha(raw)
                self.assertCompositionError(
                    pc.compose,
                    candidate,
                    self.fx.repository,
                    self.fx.receipts,
                    authority=authority,
                )
        self.fx.sync_events(self.fx.plan)

    def test_synthetic_authority_tree_never_becomes_consumable_ready(self) -> None:
        """F14-007: an internally consistent caller-owned tree is still synthetic."""

        authority = self.fx.authority(self.fx.plan)
        result = pc.compose(
            self.fx.plan,
            self.fx.repository,
            self.fx.receipts,
            authority=authority,
        )
        self.assertEqual(result["state"], "SYNTHETIC_READY")
        self.assertIs(result["consumable"], False)
        self.assertEqual(result["authority_kind"], "synthetic")
        self.assertEqual(result["resolver_kind"], "test")

        copied_token = copy.copy(authority)
        refreshed = pc._refresh_authority(self.fx.plan, copied_token)
        self.assertEqual(refreshed.authority_kind, "synthetic")
        self.assertEqual(refreshed.resolver_kind, "test")
        with self.assertRaises(AttributeError):
            authority.authority_kind = "production"
        with self.assertRaises(AttributeError):
            authority.resolver_kind = "production"

        forged = copy.deepcopy(authority.provenance)
        forged["authority_kind"] = "production"
        forged["resolver_kind"] = "production"
        forged["consumable"] = True
        unattested = pc.compose(
            self.fx.plan,
            self.fx.repository,
            self.fx.receipts,
            authority=forged,
        )
        self.assertEqual(unattested["state"], pc.AUTHORITY_UNATTESTED)

        recovered = pc.recover(
            self.fx.plan,
            self.fx.repository,
            self.fx.receipts,
            authority=authority,
        )
        verified = pc.verify_receipt(
            self.fx.plan,
            self.fx.repository,
            self.fx.receipts,
            authority=authority,
        )
        for nonproduction in (recovered, verified):
            self.assertEqual(nonproduction["state"], "SYNTHETIC_READY")
            self.assertIs(nonproduction["consumable"], False)
            self.assertEqual(nonproduction["authority_kind"], "synthetic")
            self.assertEqual(nonproduction["resolver_kind"], "test")

        with open(result["receipt_path"], "rb") as handle:
            receipt = json.load(handle)
        self.assertEqual(receipt["state"], "SYNTHETIC_READY")
        self.assertIs(receipt["consumable"], False)
        self.assertEqual(receipt["authority_kind"], "synthetic")
        self.assertEqual(receipt["resolver_kind"], "test")
        self.assertIs(receipt["authority"]["consumable"], False)
        self.assertEqual(receipt["authority"]["authority_kind"], "synthetic")
        self.assertEqual(receipt["authority"]["resolver_kind"], "test")
        forged_receipt = copy.deepcopy(receipt)
        forged_receipt["state"] = "READY"
        forged_receipt["consumable"] = True
        forged_receipt["authority_kind"] = "production"
        forged_receipt["resolver_kind"] = "production"
        self.assertCompositionError(pc.load_receipt, json.dumps(forged_receipt))

    def test_public_production_loader_has_no_resolver_override(self) -> None:
        """F14-007: the production entry point cannot accept a caller root."""

        self.fx.authority(self.fx.plan)
        with self.assertRaises(TypeError):
            pc.load_trusted_authority(
                self.fx.plan["program_id"],
                self.fx.plan["authority_snapshot_id"],
                _resolver=self.fx.control_resolver,
            )

    def test_foreign_owned_0755_control_ancestor_fails_before_authority_reads(self) -> None:
        """F14-008: mode 0755 does not make a foreign-owned ancestor trusted."""

        self.fx.authority(self.fx.plan)
        real_fstat = pc.os.fstat
        injected = {"value": False}

        def foreign_first_ancestor(descriptor: int) -> os.stat_result:
            info = real_fstat(descriptor)
            if not injected["value"] and stat.S_ISDIR(info.st_mode):
                injected["value"] = True
                fields = list(info)
                fields[0] = stat.S_IFDIR | 0o755
                fields[4] = os.geteuid() + 1000
                return os.stat_result(fields)
            return info

        with (
            mock.patch.object(pc, "_production_control_root_path", return_value=self.fx.control),
            mock.patch.object(pc.os, "fstat", side_effect=foreign_first_ancestor),
            mock.patch.object(
                pc,
                "_read_control_deployment",
                side_effect=AssertionError("authority bytes were consumed"),
            ) as deployment_read,
        ):
            with self.assertRaisesRegex(pc.CompositionError, "unsafe.*ancestor"):
                pc.load_trusted_authority(
                    self.fx.plan["program_id"],
                    self.fx.plan["authority_snapshot_id"],
                )
        deployment_read.assert_not_called()

        safe_macos_shapes = (
            ("/", 0, 0o755),
            ("/private", 0, 0o755),
            ("/Users", 0, 0o755),
            ("effective-user home", os.geteuid(), 0o700),
            ("root-owned sticky traversal", 0, 0o1777),
        )
        for label, uid, mode in safe_macos_shapes:
            info = os.stat_result((stat.S_IFDIR | mode, 1, 1, 2, uid, 0, 0, 0, 0, 0))
            pc._gate_directory(info, f"macOS production ancestor {label}", leaf=False)

    def test_generation_closure_and_topological_order_fail_closed(self) -> None:
        self.fx.add_chained_predecessor()
        valid = copy.deepcopy(self.fx.plan)
        pc.validate_plan(valid)
        for mutate in (
            lambda plan: plan["predecessors"][1].update(parent_generation=0),
            lambda plan: plan["predecessors"][1].update(dependency_closure=[]),
            lambda plan: plan["predecessors"][0].update(dependencies=["P2"]),
            lambda plan: plan.update(helper_generation=2),
        ):
            candidate = copy.deepcopy(valid)
            mutate(candidate)
            self.assertCompositionError(pc.validate_plan, candidate)

    def test_explicit_dependency_chain_allows_digest_continuous_overwrite(self) -> None:
        self.fx.add_chained_predecessor()
        result = self.compose()
        self.assertEqual(git(self.fx.repository, "show", f"{result['commit_oid']}:modify.txt"), self.fx.after_modify)

    def test_parallel_duplicate_path_is_rejected(self) -> None:
        self.fx.only_modify()
        second = copy.deepcopy(self.fx.plan["predecessors"][0])
        second["task_id"] = "P2"
        second["verification_run"]["id"] = "verify-2"
        second["task_definition"] = self.fx._artifact("p2-task.json", b"p2\n")
        event = self.fx._artifact("p2-event.json", b"event2\n")
        second["accepted_event"].update(path=event["path"], sha256=event["sha256"], sequence=8)
        evidence = self.fx._artifact("p2-evidence.json", b"evidence2\n")
        second["evidence"] = [{"id": "evidence-2", **evidence}]
        self.fx.plan["predecessors"].append(second)
        self.assertCompositionError(self.compose)

    def test_duplicate_and_nfkc_casefold_colliding_paths_rejected(self) -> None:
        duplicate = copy.deepcopy(self.fx.plan)
        duplicate["predecessors"][0]["delta"].append(copy.deepcopy(duplicate["predecessors"][0]["delta"][0]))
        self.assertCompositionError(pc.validate_plan, duplicate)
        collision = copy.deepcopy(self.fx.plan)
        other = copy.deepcopy(collision["predecessors"][0]["delta"][0])
        other["path"] = "ADD.txt"
        collision["predecessors"][0]["delta"].append(other)
        self.assertCompositionError(pc.validate_plan, collision)
        non_nfkc = copy.deepcopy(self.fx.plan)
        non_nfkc["predecessors"][0]["delta"][0]["path"] = "Ａ.txt"
        self.assertCompositionError(pc.validate_plan, non_nfkc)

    def test_path_syntax_glob_magic_and_control_paths_rejected(self) -> None:
        bad_paths = [
            "/absolute",
            "a//b",
            "a/./b",
            "a/../b",
            "a\\b",
            "*.txt",
            ":(glob)x",
            ".git/config",
            ".codex-agent/READY",
            ".coordinator-authority",
            "events.jsonl",
            "completion-evidence/snapshot.json",
            "authority/token",
            "completion/result",
        ]
        for path in bad_paths:
            with self.subTest(path=path):
                candidate = copy.deepcopy(self.fx.plan)
                candidate["predecessors"][0]["delta"][0]["path"] = path
                self.assertCompositionError(pc.validate_plan, candidate)

    def test_all_delta_operations_reject_control_aliases_before_blob_or_git_io(self) -> None:
        protected_aliases = (
            "guardian-program/events.jsonl",
            "guardian-program/EVENTS.JSONL",
            "guardian-program/ｅｖｅｎｔｓ.jsonl",
        )
        with (
            mock.patch.object(pc, "_read_accepted_blob") as accepted_blob,
            mock.patch.object(pc, "_git") as git_object,
        ):
            for operation in ("add", "modify", "delete"):
                for path in protected_aliases:
                    with self.subTest(operation=operation, path=path):
                        candidate = copy.deepcopy(self.fx.plan)
                        entry = candidate["predecessors"][0]["delta"][0]
                        entry["path"] = path
                        entry["operation"] = operation
                        if operation == "modify":
                            entry["before_sha256"] = sha(self.fx.base_modify)
                        elif operation == "delete":
                            entry["before_sha256"] = sha(self.fx.base_modify)
                            entry["after_sha256"] = pc.ZERO_SHA256
                            entry["size"] = 0
                            entry["accepted_blob"] = None
                        self.assertCompositionError(
                            pc.compose,
                            candidate,
                            self.fx.repository,
                            self.fx.receipts,
                            authority=object(),
                        )
        accepted_blob.assert_not_called()
        git_object.assert_not_called()

    def test_symlink_leaf_and_parent_are_rejected(self) -> None:
        self.fx.only_modify()
        target = os.path.join(self.fx.root, "actual.txt")
        write(target, self.fx.after_modify)
        os.unlink(os.path.join(self.fx.repository, "modify.txt"))
        os.symlink(target, os.path.join(self.fx.repository, "modify.txt"))
        self.assertCompositionError(self.compose)

        os.unlink(os.path.join(self.fx.repository, "modify.txt"))
        write(os.path.join(self.fx.repository, "modify.txt"), self.fx.base_modify)
        os.unlink(target)
        directory = os.path.join(self.fx.root, "real-dir")
        os.mkdir(directory)
        nested_after = b"nested after\n"
        write(os.path.join(directory, "file.txt"), nested_after)
        shutil.rmtree(os.path.join(self.fx.repository, "nested"))
        os.symlink(directory, os.path.join(self.fx.repository, "nested"))
        delete_entry = {
            "path": "nested/file.txt",
            "operation": "delete",
            "before_sha256": sha(b"nested before\n"),
            "after_sha256": pc.ZERO_SHA256,
            "size": 0,
            "mode": 0o100644,
        }
        symlink_entry = {
            "path": "nested",
            "operation": "add",
            "before_sha256": pc.ZERO_SHA256,
            "after_sha256": sha(directory.encode("utf-8")),
            "size": len(directory.encode("utf-8")),
            "mode": 0o100644,
        }
        self.fx.plan["predecessors"][0]["delta"] = [delete_entry, symlink_entry]
        self.assertCompositionError(self.compose)

    def test_hardlink_owner_and_mode_gates(self) -> None:
        external = os.path.join(self.fx.root, "external")
        write(external, self.fx.after_add)
        os.unlink(os.path.join(self.fx.repository, "add.txt"))
        os.link(external, os.path.join(self.fx.repository, "add.txt"))
        self.assertCompositionError(self.compose)

        os.unlink(os.path.join(self.fx.repository, "add.txt"))
        write(os.path.join(self.fx.repository, "add.txt"), self.fx.after_add, 0o666)
        self.assertCompositionError(self.compose)

        write(os.path.join(self.fx.repository, "add.txt"), self.fx.after_add)
        with mock.patch.object(pc.os, "geteuid", return_value=os.geteuid() + 1):
            self.assertCompositionError(self.compose)

    def test_extra_or_missing_git_visible_delta_rejected(self) -> None:
        write(os.path.join(self.fx.repository, "extra.txt"), b"extra\n")
        self.assertCompositionError(self.compose)
        os.unlink(os.path.join(self.fx.repository, "extra.txt"))
        staged_only = os.path.join(self.fx.repository, "staged-only.txt")
        write(staged_only, b"staged but absent from worktree\n")
        git(self.fx.repository, "add", "--", "staged-only.txt")
        os.unlink(staged_only)
        self.assertCompositionError(self.compose)
        git(self.fx.repository, "reset", "-q", "--", "staged-only.txt")
        os.unlink(os.path.join(self.fx.repository, "add.txt"))
        self.assertCompositionError(self.compose)

    def test_before_after_size_mode_and_delete_mismatches_rejected(self) -> None:
        mutations = [
            lambda plan: plan["predecessors"][0]["delta"][1].update(before_sha256=sha(b"wrong")),
            lambda plan: plan["predecessors"][0]["delta"][0].update(after_sha256=sha(b"wrong")),
            lambda plan: plan["predecessors"][0]["delta"][0].update(size=999),
            lambda plan: plan["predecessors"][0]["delta"][2].update(mode=0o100755),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(self.fx.plan)
                mutate(candidate)
                self.assertCompositionError(self.compose, candidate)
        write(os.path.join(self.fx.repository, "delete.txt"), self.fx.base_delete)
        self.assertCompositionError(self.compose)

    def test_read_time_truncate_and_rename_are_detected(self) -> None:
        large = b"x" * (3 * 1024 * 1024)
        add_path = os.path.join(self.fx.repository, "add.txt")
        write(add_path, large)
        delta = self.fx.plan["predecessors"][0]["delta"][0]
        accepted_blob = self.fx._freeze_blob(large)
        delta.update(after_sha256=sha(large), size=len(large), accepted_blob=accepted_blob)
        inventory = self.fx.plan["source_roots"][0]["cumulative_inventory"][0]
        inventory.update(sha256=sha(large), size=len(large))
        blob_path = os.path.join(
            self.fx.control,
            "accepted-blobs",
            accepted_blob["sha256"][:2],
            accepted_blob["sha256"],
        )
        inode = os.stat(blob_path).st_ino
        original_read = pc.os.read
        fired = {"value": False}

        def truncating_read(descriptor: int, count: int) -> bytes:
            chunk = original_read(descriptor, count)
            if not fired["value"] and os.fstat(descriptor).st_ino == inode and chunk:
                fired["value"] = True
                with open(blob_path, "r+b") as handle:
                    handle.truncate(len(large) // 2)
            return chunk

        with mock.patch.object(pc.os, "read", side_effect=truncating_read):
            self.assertCompositionError(self.compose)
        self.assertTrue(fired["value"])

        write(blob_path, large, 0o600)
        inode = os.stat(blob_path).st_ino
        fired["value"] = False
        backup = os.path.join(os.path.dirname(blob_path), "renamed-away")

        def renaming_read(descriptor: int, count: int) -> bytes:
            chunk = original_read(descriptor, count)
            if not fired["value"] and os.fstat(descriptor).st_ino == inode and chunk:
                fired["value"] = True
                os.rename(blob_path, backup)
                write(blob_path, large, 0o600)
            return chunk

        with mock.patch.object(pc.os, "read", side_effect=renaming_read):
            self.assertCompositionError(self.compose)
        self.assertTrue(fired["value"])

    def test_concurrent_composers_have_one_ready_inode(self) -> None:
        barrier = threading.Barrier(2)
        first_content_linked = threading.Event()
        release_first_publisher = threading.Event()
        publication_lock = threading.Lock()
        delayed_once = {"value": False}
        plan = copy.deepcopy(self.fx.plan)
        authority = self.fx.authority(plan)
        original_link = pc.os.link
        original_read = pc._read_dir_file

        def delayed_content_publish(
            source: str, target: str, *args: object, **kwargs: object
        ) -> None:
            original_link(source, target, *args, **kwargs)
            if not str(target).endswith(".json"):
                return
            with publication_lock:
                if delayed_once["value"]:
                    return
                delayed_once["value"] = True
            first_content_linked.set()
            self.assertTrue(release_first_publisher.wait(timeout=2.0))

        def observe_missing_ready(
            directory_fd: int, name: str, label: str
        ) -> tuple[bytes, os.stat_result]:
            try:
                return original_read(directory_fd, name, label)
            except FileNotFoundError:
                if label == "READY target" and first_content_linked.is_set():
                    release_first_publisher.set()
                raise

        def run() -> dict[str, object]:
            barrier.wait()
            return pc.compose(
                copy.deepcopy(plan),
                self.fx.repository,
                self.fx.receipts,
                authority=authority,
            )

        try:
            with (
                mock.patch.object(
                    pc.os, "link", side_effect=delayed_content_publish
                ),
                mock.patch.object(
                    pc, "_read_dir_file", side_effect=observe_missing_ready
                ),
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
            ):
                results = list(executor.map(lambda _: run(), range(2)))
        finally:
            release_first_publisher.set()
        self.assertTrue(first_content_linked.is_set())
        self.assertEqual(results[0], results[1])
        target_stat = os.stat(results[0]["target_path"])
        receipt_stat = os.stat(results[0]["receipt_path"])
        self.assertEqual((target_stat.st_dev, target_stat.st_ino), (receipt_stat.st_dev, receipt_stat.st_ino))
        self.assertEqual(len(os.listdir(os.path.join(self.fx.receipts, "targets"))), 1)

    def test_crash_injection_and_recovery_at_every_stage(self) -> None:
        stages = sorted(pc._FAULT_STAGES)
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                receipt_root = os.path.join(self.fx.root, f"ready-{index}")
                os.mkdir(receipt_root, 0o700)
                plan = copy.deepcopy(self.fx.plan)
                plan["target_id"] = f"target-{index}"
                authority = self.fx.authority(plan)
                with self.assertRaises(pc.CompositionCrash):
                    pc.compose(
                        plan,
                        self.fx.repository,
                        receipt_root,
                        fault_stage=stage,
                        authority=authority,
                    )
                recovered = pc.recover(
                    plan,
                    self.fx.repository,
                    receipt_root,
                    authority=authority,
                )
                self.assertEqual(recovered["state"], "SYNTHETIC_READY")
                verified = pc.verify_receipt(
                    plan,
                    self.fx.repository,
                    receipt_root,
                    authority=authority,
                )
                self.assertEqual(verified, recovered)
                leftovers = [name for name in os.listdir(receipt_root) if name.startswith(".tmp-")]
                self.assertEqual(leftovers, [])

    def test_real_process_death_recovers_two_links_at_publish_boundaries(self) -> None:
        stages = (
            "after_receipt_fsync",
            "after_content_publish",
            "after_content_fsync",
            "after_staging_unlink",
            "after_staging_fsync",
            "after_target_publish",
            "after_target_fsync",
        )
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                receipt_root = os.path.join(self.fx.root, f"real-crash-{index}")
                os.mkdir(receipt_root, 0o700)
                plan = copy.deepcopy(self.fx.plan)
                plan["target_id"] = f"real-crash-target-{index}"
                authority = self.fx.authority(plan)
                pid = os.fork()
                if pid == 0:
                    original_fault = pc._fault

                    def fatal_fault(selected: str | None, current: str) -> None:
                        if selected == current == stage:
                            os._exit(91)
                        original_fault(selected, current)

                    pc._fault = fatal_fault
                    pc.compose(
                        plan,
                        self.fx.repository,
                        receipt_root,
                        fault_stage=stage,
                        authority=authority,
                    )
                    os._exit(0)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 91)
                result = pc.recover(
                    plan,
                    self.fx.repository,
                    receipt_root,
                    authority=authority,
                )
                target_info = os.stat(result["target_path"])
                content_info = os.stat(result["receipt_path"])
                self.assertEqual(
                    (target_info.st_dev, target_info.st_ino, target_info.st_nlink),
                    (content_info.st_dev, content_info.st_ino, 2),
                )
                self.assertEqual(
                    [name for name in os.listdir(receipt_root) if name.startswith(".tmp-")],
                    [],
                )

    def test_recovery_checks_source_drift_before_candidate_cleanup(self) -> None:
        receipt_root = os.path.join(self.fx.root, "source-drift-recovery")
        os.mkdir(receipt_root, 0o700)
        plan = copy.deepcopy(self.fx.plan)
        plan["target_id"] = "source-drift-recovery-target"
        authority = self.fx.authority(plan)
        pid = os.fork()
        if pid == 0:
            original_fault = pc._fault

            def fatal_fault(selected: str | None, current: str) -> None:
                if selected == current == "after_content_publish":
                    os._exit(91)
                original_fault(selected, current)

            pc._fault = fatal_fault
            pc.compose(
                plan,
                self.fx.repository,
                receipt_root,
                fault_stage="after_content_publish",
                authority=authority,
            )
            os._exit(0)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 91)
        before = sorted(os.listdir(receipt_root))
        write(os.path.join(self.fx.repository, "add.txt"), b"source drift\n")
        self.assertCompositionError(
            pc.recover,
            plan,
            self.fx.repository,
            receipt_root,
            authority=authority,
        )
        self.assertEqual(sorted(os.listdir(receipt_root)), before)
        target_path, _ = pc._receipt_paths(receipt_root, plan["target_id"])
        self.assertFalse(os.path.lexists(target_path))

    def test_repository_commit_encoding_is_neutralized_before_ready(self) -> None:
        git(self.fx.repository, "config", "i18n.commitEncoding", "ISO-8859-1")
        result = self.compose()
        raw_commit = git(self.fx.repository, "cat-file", "commit", result["commit_oid"])
        self.assertNotIn(b"encoding ", raw_commit)
        self.assertEqual(self.verify(), result)

    def test_content_and_target_directory_fsync_failures_are_recoverable(self) -> None:
        for directory_name in ("receipts", "targets"):
            with self.subTest(directory=directory_name):
                receipt_root = os.path.join(self.fx.root, f"dir-fsync-{directory_name}")
                os.mkdir(receipt_root, 0o700)
                os.mkdir(os.path.join(receipt_root, "targets"), 0o700)
                os.mkdir(os.path.join(receipt_root, "receipts"), 0o700)
                failing_inode = os.stat(os.path.join(receipt_root, directory_name)).st_ino
                plan = copy.deepcopy(self.fx.plan)
                plan["target_id"] = f"dir-fsync-{directory_name}-target"
                authority = self.fx.authority(plan)
                original_fsync = pc.os.fsync
                fired = {"value": False}

                def failing_directory_fsync(descriptor: int) -> None:
                    if not fired["value"] and os.fstat(descriptor).st_ino == failing_inode:
                        fired["value"] = True
                        raise OSError(f"synthetic {directory_name} fsync failure")
                    original_fsync(descriptor)

                with mock.patch.object(pc.os, "fsync", side_effect=failing_directory_fsync):
                    self.assertCompositionError(
                        pc.compose,
                        plan,
                        self.fx.repository,
                        receipt_root,
                        authority=authority,
                    )
                self.assertTrue(fired["value"])
                result = pc.recover(
                    plan,
                    self.fx.repository,
                    receipt_root,
                    authority=authority,
                )
                self.assertEqual(result["state"], "SYNTHETIC_READY")
                self.assertEqual(os.stat(result["target_path"]).st_nlink, 2)

    def test_different_plans_racing_same_target_leave_only_winner_content(self) -> None:
        first = copy.deepcopy(self.fx.plan)
        second = copy.deepcopy(self.fx.plan)
        second["commit"]["message"] = "different concurrent plan\n"
        first_authority = self.fx.authority(first)
        second_authority = self.fx.authority(second)
        barrier = threading.Barrier(2)

        def run(plan: dict[str, object], authority: object) -> object:
            barrier.wait()
            try:
                return pc.compose(
                    plan,
                    self.fx.repository,
                    self.fx.receipts,
                    authority=authority,
                )
            except pc.CompositionError as exc:
                return exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(run, first, first_authority),
                executor.submit(run, second, second_authority),
            )
            outcomes = [future.result() for future in futures]
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        self.assertEqual(sum(isinstance(item, pc.CompositionError) for item in outcomes), 1)
        self.assertEqual(len(os.listdir(os.path.join(self.fx.receipts, "targets"))), 1)
        self.assertEqual(len(os.listdir(os.path.join(self.fx.receipts, "receipts"))), 1)

    def test_git_subprocess_termination_cannot_publish_ready(self) -> None:
        authority = self.fx.authority(self.fx.plan)
        original_run = pc.subprocess.run

        def terminated_run(arguments, *args, **kwargs):
            if "hash-object" in arguments and "commit" in arguments and "-w" in arguments:
                return subprocess.CompletedProcess(arguments, -9, b"", b"killed")
            return original_run(arguments, *args, **kwargs)

        with mock.patch.object(pc.subprocess, "run", side_effect=terminated_run):
            self.assertCompositionError(
                pc.compose,
                self.fx.plan,
                self.fx.repository,
                self.fx.receipts,
                authority=authority,
            )
        target_path, _ = pc._receipt_paths(self.fx.receipts, self.fx.plan["target_id"])
        self.assertFalse(os.path.lexists(target_path))

    def test_disk_write_fsync_and_receipt_link_failures_leave_no_partial_authority(self) -> None:
        scenarios = ("write", "fsync", "link")
        for index, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario):
                receipt_root = os.path.join(self.fx.root, f"io-failure-{index}")
                os.mkdir(receipt_root, 0o700)
                plan = copy.deepcopy(self.fx.plan)
                plan["target_id"] = f"io-target-{index}"
                authority = self.fx.authority(plan)
                if scenario == "write":
                    original_write = pc.os.write

                    def failing_file_write(descriptor: int, data: bytes) -> int:
                        if stat.S_ISREG(os.fstat(descriptor).st_mode):
                            raise OSError("synthetic disk full")
                        return original_write(descriptor, data)

                    patcher = mock.patch.object(pc.os, "write", side_effect=failing_file_write)
                elif scenario == "link":
                    patcher = mock.patch.object(pc.os, "link", side_effect=OSError("synthetic link failure"))
                else:
                    original_fsync = pc.os.fsync

                    def failing_file_fsync(descriptor: int) -> None:
                        if stat.S_ISREG(os.fstat(descriptor).st_mode):
                            raise OSError("synthetic receipt fsync failure")
                        original_fsync(descriptor)

                    patcher = mock.patch.object(pc.os, "fsync", side_effect=failing_file_fsync)
                with patcher:
                    self.assertCompositionError(
                        pc.compose,
                        plan,
                        self.fx.repository,
                        receipt_root,
                        authority=authority,
                    )
                target_dir = os.path.join(receipt_root, "targets")
                if os.path.isdir(target_dir):
                    self.assertEqual(os.listdir(target_dir), [])
                recovered = pc.recover(
                    plan,
                    self.fx.repository,
                    receipt_root,
                    authority=authority,
                )
                self.assertEqual(recovered["state"], "SYNTHETIC_READY")
                leftovers = [name for name in os.listdir(receipt_root) if name.startswith(".tmp-")]
                self.assertEqual(leftovers, [])

    def test_different_plan_cannot_claim_existing_target(self) -> None:
        self.compose()
        other = copy.deepcopy(self.fx.plan)
        other["commit"]["message"] = "different deterministic message\n"
        self.assertCompositionError(self.compose, other)

    def test_ready_receipt_alias_mode_content_and_inode_drift_fail_closed(self) -> None:
        result = self.compose()
        os.unlink(result["receipt_path"])
        write(result["receipt_path"], b"{}\n", 0o600)
        self.assertCompositionError(self.verify)

        shutil.rmtree(self.fx.receipts)
        os.mkdir(self.fx.receipts, 0o700)
        result = self.compose()
        os.chmod(result["receipt_path"], 0o644)
        self.assertCompositionError(self.verify)

    def test_ready_source_artifact_and_commit_drift_fail_closed(self) -> None:
        result = self.compose()
        write(os.path.join(self.fx.repository, "add.txt"), self.fx.after_add + b"later")
        self.assertCompositionError(self.verify)
        write(os.path.join(self.fx.repository, "add.txt"), self.fx.after_add)
        write(self.fx.evidence["path"], b"changed evidence\n")
        self.assertCompositionError(self.verify)
        write(self.fx.evidence["path"], b'{"result":"pass"}\n')
        with open(result["receipt_path"], "rb") as handle:
            receipt = json.load(handle)
        add_blob = next(item["blob_oid"] for item in receipt["blobs"] if item["path"] == "add.txt")
        blob_path = os.path.join(
            self.fx.repository,
            ".git",
            "objects",
            add_blob[:2],
            add_blob[2:],
        )
        os.unlink(blob_path)
        self.assertCompositionError(self.verify)
        restored_blob = git(self.fx.repository, "hash-object", "-w", "--no-filters", "add.txt").decode("ascii").strip()
        self.assertEqual(restored_blob, add_blob)
        object_path = os.path.join(
            self.fx.repository,
            ".git",
            "objects",
            result["commit_oid"][:2],
            result["commit_oid"][2:],
        )
        os.unlink(object_path)
        self.assertCompositionError(self.verify)

    def test_main_index_is_untouched_and_commit_is_reproducible(self) -> None:
        index_path = os.path.join(self.fx.repository, ".git", "index")
        with open(index_path, "rb") as handle:
            before = handle.read()
        first = self.compose()
        with open(index_path, "rb") as handle:
            after = handle.read()
        self.assertEqual(before, after)
        other_receipts = os.path.join(self.fx.root, "ready-other")
        os.mkdir(other_receipts, 0o700)
        second = self.compose(receipt_root=other_receipts)
        self.assertEqual(first["commit_oid"], second["commit_oid"])
        self.assertEqual(first["receipt_sha256"], second["receipt_sha256"])

    def test_shared_source_root_uses_one_cumulative_inventory_for_stacked_tasks(self) -> None:
        root_a = os.path.join(self.fx.root, "stacked-t05-t11")
        root_b = os.path.join(self.fx.root, "stacked-t02-t10")
        git(self.fx.repository, "worktree", "add", "-q", "--detach", root_a, self.fx.base)
        git(self.fx.repository, "worktree", "add", "-q", "--detach", root_b, self.fx.base)
        t05_bytes = b"T05 accepted bytes\n"
        t11_bytes = b"T11 accepted bytes\n"
        t02_bytes = b"T02 accepted bytes\n"
        t10_bytes = b"T10 accepted bytes\n"
        t11_extra = b"T11 independently owned bytes\n"
        write(os.path.join(root_a, "modify.txt"), t11_bytes)
        write(os.path.join(root_a, "t11-extra.txt"), t11_extra)
        write(os.path.join(root_b, "stacked.txt"), t10_bytes)

        def predecessor(
            task_id: str,
            sequence: int,
            source_root_id: str,
            generation: int,
            dependencies: list[str],
            closure: list[str],
            task_delta: dict[str, object] | list[dict[str, object]],
        ) -> dict[str, object]:
            event = self.fx._artifact(f"{task_id}-event.json", b"{}\n")
            definition = self.fx._artifact(f"{task_id}-task.json", f'{{"task":"{task_id}"}}\n'.encode())
            evidence = self.fx._artifact(f"{task_id}-evidence.json", b'{"result":"pass"}\n')
            return {
                "task_id": task_id,
                "status": "accepted",
                "verification_run": {"id": f"verify-{task_id}", "status": "accepted"},
                "accepted_event": {
                    "id": f"accepted-{task_id}-{sequence}",
                    "sequence": sequence,
                    "status": "accepted",
                    **event,
                },
                "supersession": {"status": "current", "superseded_by": None},
                "task_definition": definition,
                "source_root_id": source_root_id,
                "generation": generation,
                "parent_generation": generation - 1,
                "dependencies": dependencies,
                "dependency_closure": closure,
                "evidence": [{"id": f"evidence-{task_id}", **evidence}],
                "delta": task_delta if isinstance(task_delta, list) else [task_delta],
            }

        def delta(path: str, operation: str, before: str, content: bytes) -> dict[str, object]:
            return {
                "path": path,
                "operation": operation,
                "before_sha256": before,
                "after_sha256": sha(content),
                "size": len(content),
                "mode": 0o100644,
                "accepted_blob": self.fx._freeze_blob(content),
            }

        self.fx.plan["predecessors"] = [
            predecessor(
                "T05", 20, "root-t05-t11", 1, [], [],
                delta("modify.txt", "modify", sha(self.fx.base_modify), t05_bytes),
            ),
            predecessor(
                "T02", 21, "root-t02-t10", 1, [], [],
                delta("stacked.txt", "add", pc.ZERO_SHA256, t02_bytes),
            ),
            predecessor(
                "T11", 22, "root-t05-t11", 2, ["T05"], ["T05"],
                [
                    delta("modify.txt", "modify", sha(t05_bytes), t11_bytes),
                    delta("t11-extra.txt", "add", pc.ZERO_SHA256, t11_extra),
                ],
            ),
            predecessor(
                "T10", 23, "root-t02-t10", 2, ["T02"], ["T02"],
                delta("stacked.txt", "modify", sha(t02_bytes), t10_bytes),
            ),
        ]
        self.fx.plan["source_roots"] = [
            {
                "id": "root-t05-t11",
                "path": root_a,
                "task_ids": ["T05", "T11"],
                "cumulative_inventory": [
                    {
                        "path": "modify.txt",
                        "selected_predecessor": "T11",
                        "state": "present",
                        "sha256": sha(t11_bytes),
                        "size": len(t11_bytes),
                        "mode": 0o100644,
                    },
                    {
                        "path": "t11-extra.txt",
                        "selected_predecessor": "T11",
                        "state": "present",
                        "sha256": sha(t11_extra),
                        "size": len(t11_extra),
                        "mode": 0o100644,
                    }
                ],
            },
            {
                "id": "root-t02-t10",
                "path": root_b,
                "task_ids": ["T02", "T10"],
                "cumulative_inventory": [
                    {
                        "path": "stacked.txt",
                        "selected_predecessor": "T10",
                        "state": "present",
                        "sha256": sha(t10_bytes),
                        "size": len(t10_bytes),
                        "mode": 0o100644,
                    }
                ],
            },
        ]
        self.fx.plan["helper_generation"] = 3
        self.fx.sync_events(self.fx.plan)

        result = self.compose()
        self.assertEqual(result["state"], "SYNTHETIC_READY")
        with open(result["receipt_path"], "rb") as handle:
            receipt = json.load(handle)
        self.assertEqual(
            [(item["root_id"], item["task_ids"]) for item in receipt["source_roots"]],
            [("root-t05-t11", ["T05", "T11"]), ("root-t02-t10", ["T02", "T10"])],
        )
        self.assertEqual(git(self.fx.repository, "show", f"{result['commit_oid']}:modify.txt"), t11_bytes)
        self.assertEqual(git(self.fx.repository, "show", f"{result['commit_oid']}:t11-extra.txt"), t11_extra)
        self.assertEqual(git(self.fx.repository, "show", f"{result['commit_oid']}:stacked.txt"), t10_bytes)

    def test_missing_accepted_blob_never_falls_back_to_mutable_source(self) -> None:
        digest = self.fx.plan["predecessors"][0]["delta"][0]["accepted_blob"]["sha256"]
        blob_path = os.path.join(self.fx.control, "accepted-blobs", digest[:2], digest)
        external = os.path.join(self.fx.root, "accepted-blob-hardlink-source")
        write(external, self.fx.after_add, 0o600)

        def missing() -> None:
            os.unlink(blob_path)

        def damaged() -> None:
            write(blob_path, b"damaged accepted bytes\n", 0o600)

        def symlinked() -> None:
            os.unlink(blob_path)
            os.symlink(os.path.join(self.fx.repository, "add.txt"), blob_path)

        def hardlinked() -> None:
            os.unlink(blob_path)
            os.link(external, blob_path)

        def wrong_mode() -> None:
            os.chmod(blob_path, 0o644)

        for name, mutate in (
            ("missing", missing),
            ("damaged", damaged),
            ("symlink", symlinked),
            ("hardlink", hardlinked),
            ("mode", wrong_mode),
        ):
            with self.subTest(name=name):
                if os.path.lexists(blob_path):
                    os.unlink(blob_path)
                write(blob_path, self.fx.after_add, 0o600)
                mutate()
                with self.assertRaises(pc.CompositionError) as raised:
                    self.compose()
                self.assertIn(pc.AUTHORITY_INPUT_MISSING, str(raised.exception))
                target_path, _ = pc._receipt_paths(self.fx.receipts, self.fx.plan["target_id"])
                self.assertFalse(os.path.lexists(target_path))
        if os.path.lexists(blob_path):
            os.unlink(blob_path)
        write(blob_path, self.fx.after_add, 0o600)

    def test_trust_root_is_injected_only_by_explicit_process_seam_and_binds_generation(self) -> None:
        self.assertNotEqual(pc._production_control_root_path(), "/var/lib/sulde-guardian/control")
        with mock.patch.dict(os.environ, {"SULDE_CONTROL_ROOT": self.fx.root, "HOME": self.fx.root}):
            self.assertEqual(
                pc._production_control_root_path(),
                os.path.join(pwd.getpwuid(os.geteuid()).pw_dir, ".sulde", "kb", "control"),
            )
        resolver = pc._test_control_root_resolver(self.fx.control)
        authority = self.fx.authority()
        authority = pc._load_synthetic_authority_for_test(
            self.fx.plan["program_id"], self.fx.plan["authority_snapshot_id"], capability=resolver
        )
        self.assertEqual(authority.provenance["control_root"]["path"], self.fx.control)
        self.assertEqual(
            authority.provenance["control_root"]["deployment_generation"],
            self.fx.plan["control_generation"],
        )

        link = os.path.join(self.fx.root, "control-link")
        os.symlink(self.fx.control, link)
        self.assertCompositionError(
            pc._load_synthetic_authority_for_test,
            self.fx.plan["program_id"],
            self.fx.plan["authority_snapshot_id"],
            capability=pc._test_control_root_resolver(link),
        )
        parent_link = os.path.join(self.fx.root, "control-parent-link")
        os.symlink(self.fx.root, parent_link)
        self.assertCompositionError(
            pc._load_synthetic_authority_for_test,
            self.fx.plan["program_id"],
            self.fx.plan["authority_snapshot_id"],
            capability=pc._test_control_root_resolver(os.path.join(parent_link, "control")),
        )
        unsafe_parent = os.path.join(self.fx.root, "unsafe-control-parent")
        copied_control = os.path.join(unsafe_parent, "control")
        os.mkdir(unsafe_parent, 0o700)
        shutil.copytree(self.fx.control, copied_control)
        os.chmod(copied_control, 0o700)
        os.chmod(unsafe_parent, 0o770)
        self.assertCompositionError(
            pc._load_synthetic_authority_for_test,
            self.fx.plan["program_id"],
            self.fx.plan["authority_snapshot_id"],
            capability=pc._test_control_root_resolver(copied_control),
        )
        os.chmod(unsafe_parent, 0o700)
        os.chmod(self.fx.control, 0o770)
        self.assertCompositionError(
            pc._load_synthetic_authority_for_test,
            self.fx.plan["program_id"],
            self.fx.plan["authority_snapshot_id"],
            capability=resolver,
        )
        os.chmod(self.fx.control, 0o700)

        deployment_path = os.path.join(self.fx.control, "deployment.json")
        drifted = {"schema": pc.CONTROL_DEPLOYMENT_SCHEMA, "generation": 15}
        write(deployment_path, pc._canonical_bytes(drifted) + b"\n", 0o600)
        with self.assertRaises(pc.CompositionError):
            pc.compose(
                self.fx.plan,
                self.fx.repository,
                self.fx.receipts,
                authority=authority,
            )
        target_path, _ = pc._receipt_paths(self.fx.receipts, self.fx.plan["target_id"])
        self.assertFalse(os.path.lexists(target_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
