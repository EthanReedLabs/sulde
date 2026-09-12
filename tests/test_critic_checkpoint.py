from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from task_ownership import (  # noqa: E402
    claim_critic_lane_batch as claim_lane_batch,
    critic_claim_world_is_current as claim_world_is_current,
    critic_event_for_claim as event_for_claim,
    normalize_critic_batches as normalize_batches,
    record_critic_local_write as record_local_write,
    settle_critic_claim as settle_claim,
)
import intent_critic as intent_critic_module  # noqa: E402
from intent_critic import TASK_SCOPE_SCHEMA, _read_target, run_critic  # noqa: E402


class HostileString(str):
    """A string subclass whose callbacks must never run at the authority gate."""

    __hash__ = str.__hash__

    def _unexpected(self, *_args, **_kwargs):
        raise AssertionError("malformed authority string callback was invoked")

    __bool__ = _unexpected
    __eq__ = _unexpected
    __fspath__ = _unexpected
    __iter__ = _unexpected
    __ne__ = _unexpected
    __str__ = _unexpected


class HostileDict(dict):
    def _unexpected(self, *_args, **_kwargs):
        raise AssertionError("malformed authority dict callback was invoked")

    __bool__ = _unexpected
    __iter__ = _unexpected
    get = _unexpected
    items = _unexpected
    values = _unexpected


class HostileList(list):
    def _unexpected(self, *_args, **_kwargs):
        raise AssertionError("malformed authority list callback was invoked")

    __bool__ = _unexpected
    __iter__ = _unexpected


class CriticCheckpointTests(unittest.TestCase):
    def contract(self, *, enabled: bool = True) -> dict:
        return {
            "revision": 7,
            "task_epoch": "epoch-current",
            "critic": {"enabled": enabled},
            "runtime": {
                "sequence": 10,
                "material_sequence": 6,
                "critic_batches": [],
            },
        }

    def event(self, **overrides) -> dict:
        event = {
            "phase": "completed",
            "effect": "local_write",
            "success": True,
            "provider": "codex",
            "session_id": "thread-a",
            "sequence": 10,
            "event_id": "event-a",
            "capability": "tool:apply_patch",
            "target": "[local-target-set:opaque]",
            "write_targets": ["one.py", "dir/name,with-comma.py"],
        }
        event.update(overrides)
        return event

    def test_only_successful_completed_local_writes_are_collected(self) -> None:
        for event in (
            self.event(phase="started"),
            self.event(effect="read"),
            self.event(success=False),
        ):
            contract = self.contract()
            self.assertIsNone(record_local_write(contract, event))
            self.assertEqual(contract["runtime"]["critic_batches"], [])

        disabled = self.contract(enabled=False)
        self.assertIsNone(record_local_write(disabled, self.event()))
        self.assertEqual(disabled["runtime"]["critic_batches"], [])

    def test_lane_batch_preserves_structured_targets_including_commas(self) -> None:
        contract = self.contract()
        first = record_local_write(
            contract,
            self.event(),
            now=lambda: "2026-08-17T00:00:00+00:00",
        )
        second = record_local_write(
            contract,
            self.event(
                sequence=12,
                event_id="event-b",
                write_targets=["one.py", "three.py"],
            ),
            now=lambda: "2026-08-17T00:00:01+00:00",
        )

        self.assertIsNotNone(first)
        self.assertEqual(second["completed_writes"], 2)
        self.assertEqual(
            second["targets"],
            ["one.py", "dir/name,with-comma.py", "three.py"],
        )
        self.assertEqual(second["event_ids"], ["event-a", "event-b"])

    def test_claim_is_one_shot_while_model_runs_and_new_writes_wait(self) -> None:
        contract = self.contract()
        record_local_write(contract, self.event())
        claim = claim_lane_batch(
            contract,
            provider="codex",
            session_id="thread-a",
            now=lambda: "2026-08-17T00:00:10+00:00",
            claim_id="claim-one",
        )
        self.assertEqual(claim["state"], "claimed")
        self.assertTrue(claim_world_is_current(contract, claim))
        self.assertIsNone(
            claim_lane_batch(
                contract,
                provider="codex",
                session_id="thread-a",
                now=lambda: "2026-08-17T00:00:11+00:00",
            )
        )

        contract["runtime"]["material_sequence"] += 1
        record_local_write(
            contract,
            self.event(sequence=13, event_id="event-c", write_targets=["later.py"]),
        )
        self.assertFalse(claim_world_is_current(contract, claim))
        self.assertEqual(
            [row["state"] for row in contract["runtime"]["critic_batches"]],
            ["claimed", "collecting"],
        )
        self.assertTrue(settle_claim(contract, claim))
        next_claim = claim_lane_batch(
            contract,
            provider="codex",
            session_id="thread-a",
            claim_id="claim-two",
        )
        self.assertEqual(next_claim["targets"], ["later.py"])

    def test_expired_claim_becomes_inconclusive_candidate_without_retry(self) -> None:
        contract = self.contract()
        record_local_write(contract, self.event())
        claim = claim_lane_batch(
            contract,
            provider="codex",
            session_id="thread-a",
            now=lambda: "2026-08-17T00:00:00+00:00",
            claim_id="claim-expired",
        )
        expired = claim_lane_batch(
            contract,
            provider="codex",
            session_id="thread-a",
            now=lambda: "2026-08-17T00:03:01+00:00",
        )

        self.assertEqual(expired["batch_id"], claim["batch_id"])
        self.assertEqual(expired["claim_id"], "claim-expired")
        self.assertEqual(expired["state"], "abandoned")
        self.assertTrue(settle_claim(contract, expired))
        self.assertEqual(contract["runtime"]["critic_batches"], [])

    def test_claim_event_is_bounded_and_lane_scoped(self) -> None:
        contract = self.contract()
        record_local_write(contract, self.event())
        claim = claim_lane_batch(
            contract,
            provider="codex",
            session_id="thread-a",
            claim_id="claim-event",
        )
        event = event_for_claim(claim)

        self.assertEqual(event["capability"], "guardian:semantic-batch-checkpoint")
        self.assertEqual(event["provider"], "codex")
        self.assertEqual(event["session_id"], "thread-a")
        self.assertEqual(event["write_targets"], claim["targets"])
        self.assertNotIn("claim_id", event)

    def test_normalization_drops_old_task_epochs(self) -> None:
        contract = self.contract()
        record_local_write(contract, self.event())
        current = contract["runtime"]["critic_batches"][0]
        old = {**current, "batch_id": "cb-old", "task_epoch": "epoch-old"}
        normalized = normalize_batches(
            [old, current],
            default_epoch="epoch-current",
        )
        self.assertEqual([row["batch_id"] for row in normalized], [current["batch_id"]])

    def test_post_tool_hook_never_invokes_the_semantic_model(self) -> None:
        source = (ROOT / "hooks" / "post_tool_use.py").read_text(encoding="utf-8")
        self.assertNotIn("intent_critic", source)
        self.assertNotIn("run_critic", source)


class CriticIncrementAttributionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Critic Test")
        self.git("config", "user.email", "critic@example.invalid")
        (self.root / "owned.py").write_text("BASE = True\n", encoding="utf-8")
        (self.root / "other-owned.py").write_text("OTHER = 'base'\n", encoding="utf-8")
        (self.root / "legacy-noise.txt").write_text("legacy base\n", encoding="utf-8")
        self.git("add", "owned.py", "other-owned.py", "legacy-noise.txt")
        self.git("commit", "-q", "-m", "frozen baseline")
        self.baseline = self.git("rev-parse", "HEAD").stdout.strip()
        self.snapshot = self.snapshot_files()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return completed

    @staticmethod
    def fingerprint(path: Path) -> str:
        mode = path.stat().st_mode & 0o7777
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"{mode:o}:{digest}"

    def snapshot_files(self) -> dict[str, str]:
        return {
            path.relative_to(self.root).as_posix(): self.fingerprint(path)
            for path in self.root.iterdir()
            if path.is_file()
        }

    def registered_evidence(self) -> list[dict]:
        return [
            {
                "evidence_id": "e-current",
                "task_id": "T-current",
                "baseline": self.baseline,
                "run_id": "run-current",
                "recorded_sequence": 11,
                "kind": "targeted_tests",
                "verdict": "pass",
                "summary": "CURRENT RUN REGISTERED TEST PASSED",
            },
            {
                "evidence_id": "e-other-task",
                "task_id": "T-parallel",
                "baseline": self.baseline,
                "run_id": "run-current",
                "recorded_sequence": 12,
                "kind": "targeted_tests",
                "verdict": "fail",
                "summary": "CROSS TASK FAILURE MUST NOT LEAK",
            },
            {
                "evidence_id": "e-old-run",
                "task_id": "T-current",
                "baseline": self.baseline,
                "run_id": "run-old",
                "recorded_sequence": 13,
                "kind": "targeted_tests",
                "verdict": "fail",
                "summary": "OLD RUN FAILURE MUST NOT LEAK",
            },
            {
                "evidence_id": "e-before-floor",
                "task_id": "T-current",
                "baseline": self.baseline,
                "run_id": "run-current",
                "recorded_sequence": 5,
                "kind": "targeted_tests",
                "verdict": "fail",
                "summary": "PRE-RUN EVIDENCE MUST NOT LEAK",
            },
            {
                "evidence_id": "e-not-requested",
                "task_id": "T-current",
                "baseline": self.baseline,
                "run_id": "run-current",
                "recorded_sequence": 14,
                "kind": "targeted_tests",
                "verdict": "fail",
                "summary": "UNREGISTERED FOR THIS CHECKPOINT MUST NOT LEAK",
            },
        ]

    def contract(self, **scope_overrides: object) -> dict:
        scope = {
            "schema": TASK_SCOPE_SCHEMA,
            "task_id": "T-current",
            "base_commit": self.baseline,
            "verification_run_id": "run-current",
            "owned_paths": ["owned.py", "other-owned.py"],
            "baseline_snapshot": self.snapshot,
            "evidence_floor_sequence": 10,
            "registered_evidence": self.registered_evidence(),
        }
        scope.update(scope_overrides)
        return {
            "workspace_root": str(self.root),
            "critic": {"task_scope": scope},
        }

    def event(self, **overrides: object) -> dict:
        write_targets = overrides.pop("write_targets", ["owned.py"])
        binding = hashlib.sha256(
            json.dumps(
                write_targets, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        event = {
            "effect": "local_write",
            "target": f"[local-target-set:{binding[:16]}]",
            "write_targets": write_targets,
            "target_count": len(write_targets),
            "target_overflow": max(
                0, len(write_targets) - intent_critic_module.MAX_EVENT_TARGETS
            ),
            "target_binding": binding,
            "task_id": "T-current",
            "baseline": self.baseline,
            "run_id": "run-current",
            "registered_evidence_ids": [
                "e-current",
                "e-other-task",
                "e-old-run",
                "e-before-floor",
            ],
            "verification_evidence": "UNREGISTERED FREEFORM TEST RESULT",
        }
        event.update(overrides)
        return event

    def test_real_increment_uses_only_registered_current_task_run_evidence(self) -> None:
        (self.root / "legacy-noise.txt").write_text(
            "DIRTY BEFORE THIS TASK\n", encoding="utf-8"
        )
        (self.root / "other-owned.py").write_text(
            "OTHER TASK CHANGE\n", encoding="utf-8"
        )
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT_TASK_INCREMENT = True\n", encoding="utf-8"
        )

        evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(missing, "")
        self.assertIn("TARGET: owned.py", evidence)
        self.assertIn("CURRENT_TASK_INCREMENT = True", evidence)
        self.assertIn("CURRENT RUN REGISTERED TEST PASSED", evidence)
        for noise in (
            " BASE = True",
            "DIRTY BEFORE THIS TASK",
            "OTHER TASK CHANGE",
            "CROSS TASK FAILURE MUST NOT LEAK",
            "OLD RUN FAILURE MUST NOT LEAK",
            "PRE-RUN EVIDENCE MUST NOT LEAK",
            "UNREGISTERED FOR THIS CHECKPOINT MUST NOT LEAK",
            "UNREGISTERED FREEFORM TEST RESULT",
        ):
            self.assertNotIn(noise, evidence)

    def test_other_owned_path_does_not_enter_an_unregistered_checkpoint(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        (self.root / "other-owned.py").write_text(
            "PARALLEL OWNED PATH CHANGE\n", encoding="utf-8"
        )

        evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(missing, "")
        self.assertNotIn("other-owned.py", evidence)
        self.assertNotIn("PARALLEL OWNED PATH CHANGE", evidence)

    def test_empty_increment_ignores_even_registered_failing_evidence(self) -> None:
        failing = self.registered_evidence()[0]
        failing.update(verdict="fail", summary="CURRENT REGISTERED FAILURE")
        evidence, missing = _read_target(
            self.contract(registered_evidence=[failing]),
            self.event(),
        )

        self.assertEqual(evidence, "")
        self.assertIn("no non-empty increment", missing)
        self.assertNotIn("CURRENT REGISTERED FAILURE", missing)

    def test_empty_increment_never_invokes_the_model_command(self) -> None:
        marker = self.root / "critic-model-was-called"
        contract = self.contract()
        contract["critic"]["timeout_seconds"] = 10

        result = run_critic(
            contract,
            self.event(),
            provider="codex",
            command=[
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('called')",
            ],
        )

        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["next_action"], "collect_evidence")
        self.assertFalse(marker.exists())

    def test_event_from_another_task_or_run_is_not_attributed(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        for event in (
            self.event(task_id="T-parallel"),
            self.event(run_id="run-old"),
            self.event(baseline="0" * 40),
        ):
            with self.subTest(event=json.dumps(event, sort_keys=True)):
                evidence, missing = _read_target(self.contract(), event)
                self.assertEqual(evidence, "")
                self.assertIn("does not match", missing)

    def test_matching_non_string_scope_and_event_identities_never_call_model(self) -> None:
        invalid_values = (
            7,
            True,
            ["same-looking-identity"],
            {"identity": "same-looking-identity"},
        )
        identity_fields = (
            ("task_id", "task_id"),
            ("verification_run_id", "run_id"),
            ("base_commit", "baseline"),
        )
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )

        for scope_field, event_field in identity_fields:
            for index, value in enumerate(invalid_values):
                with self.subTest(scope_field=scope_field, value_type=type(value).__name__):
                    marker = self.root / f"model-called-{scope_field}-{index}"
                    contract = self.contract(**{scope_field: value})
                    contract["critic"]["timeout_seconds"] = 10
                    contract.update(
                        {
                            "intent_id": "l3:t01-critic-repair4",
                            "revision": 1,
                            "objective": "",
                            "rationale": "strict authority binding",
                            "acceptance_criteria": [],
                            "constraints": {"preserve": [], "reject": []},
                        }
                    )
                    with mock.patch.object(
                        intent_critic_module,
                        "_run_git",
                        wraps=intent_critic_module._run_git,
                    ) as git_spy:
                        result = run_critic(
                            contract,
                            self.event(**{event_field: value}),
                            provider="codex",
                            command=[
                                sys.executable,
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    f"Path({str(marker)!r}).write_text('called'); "
                                    "print('{\"verdict\":\"aligned\","
                                    "\"confidence\":1.0,\"summary\":\"called\","
                                    "\"violated_constraints\":[],\"evidence\":[],"
                                    "\"next_action\":\"continue\"}')"
                                ),
                            ],
                        )

                    self.assertEqual(result["verdict"], "inconclusive")
                    self.assertIn("exact nonempty string", result["summary"])
                    self.assertFalse(marker.exists())
                    git_spy.assert_not_called()

        for index, value in enumerate(invalid_values):
            with self.subTest(scope_field="owned_paths", value_type=type(value).__name__):
                marker = self.root / f"model-called-owned-path-{index}"
                contract = self.contract(owned_paths=[value])
                contract["critic"]["timeout_seconds"] = 10
                contract.update(
                    {
                        "intent_id": "l3:t01-critic-repair4",
                        "revision": 1,
                        "objective": "",
                        "rationale": "strict authority binding",
                        "acceptance_criteria": [],
                        "constraints": {"preserve": [], "reject": []},
                    }
                )
                event = self.event()
                event["write_targets"] = [value]
                with mock.patch.object(
                    intent_critic_module,
                    "_run_git",
                    wraps=intent_critic_module._run_git,
                ) as git_spy:
                    result = run_critic(
                        contract,
                        event,
                        provider="codex",
                        command=[
                            sys.executable,
                            "-c",
                            (
                                "from pathlib import Path; "
                                f"Path({str(marker)!r}).write_text('called')"
                            ),
                        ],
                    )

                self.assertEqual(result["verdict"], "inconclusive")
                self.assertIn("owned path entries", result["summary"])
                self.assertFalse(marker.exists())
                git_spy.assert_not_called()

    def test_nested_string_subclasses_stop_before_git_and_model_selection(self) -> None:
        def nested_case(name: str) -> tuple[dict, dict]:
            contract = self.contract()
            event = self.event()
            hostile_path = HostileString("owned.py")
            if name == "registered_evidence_ids.element":
                event["registered_evidence_ids"] = [HostileString("e-current")]
            elif name == "write_targets.element":
                event["write_targets"] = [hostile_path]
            elif name == "owned_paths.element":
                contract["critic"]["task_scope"]["owned_paths"] = [hostile_path]
            elif name == "baseline_snapshot.key":
                contract["critic"]["task_scope"]["baseline_snapshot"] = {
                    hostile_path: self.snapshot["owned.py"]
                }
            elif name == "baseline_snapshot.digest":
                contract["critic"]["task_scope"]["baseline_snapshot"] = {
                    "owned.py": HostileString(self.snapshot["owned.py"])
                }
            else:  # pragma: no cover - closed test matrix
                raise AssertionError(name)
            return contract, event

        cases = (
            "registered_evidence_ids.element",
            "write_targets.element",
            "owned_paths.element",
            "baseline_snapshot.key",
            "baseline_snapshot.digest",
        )
        for name in cases:
            with self.subTest(name=name):
                contract, event = nested_case(name)
                with (
                    mock.patch.object(intent_critic_module, "_run_git") as run_git,
                    mock.patch.object(
                        intent_critic_module, "select_provider"
                    ) as select_provider,
                ):
                    result = run_critic(contract, event, provider="codex")

                self.assertEqual(result["verdict"], "inconclusive")
                run_git.assert_not_called()
                select_provider.assert_not_called()

        for name, provider, command in (
            ("provider.enum", HostileString("codex"), None),
            ("model_command.container", "codex", HostileList(["model"])),
            ("model_command.path", "codex", [HostileString("model")]),
        ):
            with self.subTest(name=name):
                with (
                    mock.patch.object(intent_critic_module, "_run_git") as run_git,
                    mock.patch.object(
                        intent_critic_module, "select_provider"
                    ) as select_provider,
                ):
                    result = run_critic(
                        self.contract(),
                        self.event(),
                        provider=provider,
                        command=command,
                    )

                self.assertEqual(result["verdict"], "inconclusive")
                run_git.assert_not_called()
                select_provider.assert_not_called()

    def test_authority_string_and_container_matrix_is_callback_free(self) -> None:
        def authority_case(name: str) -> tuple[dict, dict]:
            contract = self.contract()
            event = self.event()
            scope = contract["critic"]["task_scope"]
            row = scope["registered_evidence"][0]
            if name == "scope.schema":
                scope["schema"] = HostileString(TASK_SCOPE_SCHEMA)
            elif name == "event.effect":
                event["effect"] = HostileString("local_write")
            elif name == "event.target_summary":
                event["target"] = HostileString(event["target"])
            elif name == "event.target_binding":
                event["target_binding"] = HostileString(event["target_binding"])
            elif name in {
                "registered_evidence.evidence_id",
                "registered_evidence.task_id",
                "registered_evidence.baseline",
                "registered_evidence.run_id",
                "registered_evidence.scope",
                "registered_evidence.kind",
                "registered_evidence.verdict",
                "registered_evidence.superseded_by",
                "registered_evidence.binding_error",
            }:
                field = name.rsplit(".", 1)[1]
                row[field] = HostileString(row.get(field, "task"))
            elif name == "workspace_root":
                contract["workspace_root"] = HostileString(str(self.root))
            elif name == "scope.container":
                contract["critic"]["task_scope"] = HostileDict(scope)
            elif name == "owned_paths.container":
                scope["owned_paths"] = HostileList(scope["owned_paths"])
            elif name == "snapshot.container":
                scope["baseline_snapshot"] = HostileDict(scope["baseline_snapshot"])
            elif name == "registered_evidence.container":
                scope["registered_evidence"] = HostileList(
                    scope["registered_evidence"]
                )
            elif name == "registered_evidence.row_container":
                scope["registered_evidence"][0] = HostileDict(row)
            elif name == "event.container":
                event = HostileDict(event)
            elif name == "write_targets.container":
                event["write_targets"] = HostileList(event["write_targets"])
            elif name == "registered_evidence_ids.container":
                event["registered_evidence_ids"] = HostileList(
                    event["registered_evidence_ids"]
                )
            else:  # pragma: no cover - closed test matrix
                raise AssertionError(name)
            return contract, event

        cases = (
            "scope.schema",
            "event.effect",
            "event.target_summary",
            "event.target_binding",
            "registered_evidence.evidence_id",
            "registered_evidence.task_id",
            "registered_evidence.baseline",
            "registered_evidence.run_id",
            "registered_evidence.scope",
            "registered_evidence.kind",
            "registered_evidence.verdict",
            "registered_evidence.superseded_by",
            "registered_evidence.binding_error",
            "workspace_root",
            "scope.container",
            "owned_paths.container",
            "snapshot.container",
            "registered_evidence.container",
            "registered_evidence.row_container",
            "event.container",
            "write_targets.container",
            "registered_evidence_ids.container",
        )
        for name in cases:
            with self.subTest(name=name):
                contract, event = authority_case(name)
                with (
                    mock.patch.object(intent_critic_module, "_run_git") as run_git,
                    mock.patch.object(
                        intent_critic_module, "select_provider"
                    ) as select_provider,
                ):
                    result = run_critic(contract, event, provider="codex")

                self.assertEqual(result["verdict"], "inconclusive")
                run_git.assert_not_called()
                select_provider.assert_not_called()

    def test_workspace_head_outside_frozen_baseline_is_inconclusive(self) -> None:
        self.git("checkout", "-q", "--orphan", "unrelated")
        (self.root / "owned.py").write_text("UNRELATED HEAD\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "unrelated history")

        evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(evidence, "")
        self.assertIn("HEAD drifted", missing)

    def test_dirty_target_at_task_freeze_is_not_reclassified_as_increment(self) -> None:
        (self.root / "owned.py").write_text("OLD WORKSPACE DIRT\n", encoding="utf-8")
        dirty_snapshot = self.snapshot_files()
        (self.root / "owned.py").write_text(
            "OLD WORKSPACE DIRT\nCURRENT TASK EDIT\n", encoding="utf-8"
        )

        evidence, missing = _read_target(
            self.contract(baseline_snapshot=dirty_snapshot),
            self.event(),
        )

        self.assertEqual(evidence, "")
        self.assertIn("not clean at the frozen task baseline", missing)

    def test_new_task_owned_file_is_a_real_increment(self) -> None:
        (self.root / "new-owned.py").write_text(
            "NEW_TASK_FILE = True\n", encoding="utf-8"
        )
        evidence, missing = _read_target(
            self.contract(
                owned_paths=["new-owned.py"],
                baseline_snapshot={"new-owned.py": "!missing"},
            ),
            self.event(write_targets=["new-owned.py"]),
        )

        self.assertEqual(missing, "")
        self.assertIn("TARGET: new-owned.py", evidence)
        self.assertIn("+NEW_TASK_FILE = True", evidence)

    def test_unowned_registered_target_cannot_supply_a_verdict(self) -> None:
        (self.root / "legacy-noise.txt").write_text(
            "OTHER TASK ONLY\n", encoding="utf-8"
        )
        evidence, missing = _read_target(
            self.contract(),
            self.event(write_targets=["legacy-noise.txt"]),
        )

        self.assertEqual(evidence, "")
        self.assertIn("no registered target owned", missing)

    def test_missing_task_scope_fails_closed_without_reading_workspace_noise(self) -> None:
        (self.root / "owned.py").write_text(
            "WORKSPACE NOISE MUST NOT BECOME EVIDENCE\n", encoding="utf-8"
        )

        evidence, missing = _read_target(
            {"workspace_root": str(self.root), "critic": {}},
            self.event(),
        )

        self.assertEqual(evidence, "")
        self.assertIn("scope is not registered", missing)
        self.assertNotIn("WORKSPACE NOISE", missing)

    def test_registered_evidence_ids_must_be_an_explicit_list(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        missing_ids = self.event()
        missing_ids.pop("registered_evidence_ids")
        for event in (missing_ids, self.event(registered_evidence_ids="e-current")):
            with self.subTest(event=event):
                evidence, missing = _read_target(self.contract(), event)
                self.assertEqual(evidence, "")
                self.assertIn("registered_evidence_ids", missing)

    def test_empty_registered_evidence_ids_keeps_diff_only_evidence(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nDIFF_ONLY = True\n", encoding="utf-8"
        )

        evidence, missing = _read_target(
            self.contract(), self.event(registered_evidence_ids=[])
        )

        self.assertEqual(missing, "")
        self.assertIn("+DIFF_ONLY = True", evidence)
        self.assertNotIn("REGISTERED CURRENT-RUN EVIDENCE", evidence)

    def test_evidence_floor_must_be_explicit_nonnegative_integer(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        scopes = []
        missing_floor = self.contract()["critic"]["task_scope"]
        missing_floor.pop("evidence_floor_sequence")
        scopes.append(missing_floor)
        for value in (-1, "10", True):
            scopes.append(self.contract(evidence_floor_sequence=value)["critic"]["task_scope"])

        for scope in scopes:
            with self.subTest(scope=scope):
                evidence, missing = _read_target(
                    {
                        "workspace_root": str(self.root),
                        "critic": {"task_scope": scope},
                    },
                    self.event(),
                )
                self.assertEqual(evidence, "")
                self.assertIn("evidence floor", missing)

    def test_every_target_requires_an_explicit_frozen_snapshot_entry(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        snapshot = dict(self.snapshot)
        snapshot.pop("owned.py")

        evidence, missing = _read_target(
            self.contract(baseline_snapshot=snapshot), self.event()
        )

        self.assertEqual(evidence, "")
        self.assertIn("snapshot has no explicit entry", missing)

    def test_old_untracked_file_is_not_reclassified_as_new(self) -> None:
        old = self.root / "old-untracked.py"
        old.write_text("OLD UNTRACKED\n", encoding="utf-8")
        frozen = {"old-untracked.py": self.fingerprint(old)}
        old.write_text("OLD UNTRACKED\nCURRENT EDIT\n", encoding="utf-8")

        evidence, missing = _read_target(
            self.contract(
                owned_paths=["old-untracked.py"], baseline_snapshot=frozen
            ),
            self.event(write_targets=["old-untracked.py"]),
        )

        self.assertEqual(evidence, "")
        self.assertIn("not clean at the frozen task baseline", missing)

    def test_current_target_hardlink_is_rejected(self) -> None:
        os.link(self.root / "owned.py", self.root / "owned-alias.py")
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )

        evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(evidence, "")
        self.assertIn("hardlink", missing)

    def test_target_inventory_overflow_cannot_hide_the_sixty_fifth_target(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        targets = ["owned.py", *[f"noise-{index}.py" for index in range(63)]]
        targets.append("other-owned.py")

        evidence, missing = _read_target(
            self.contract(),
            self.event(write_targets=targets, target_overflow=0),
        )

        self.assertEqual(evidence, "")
        self.assertIn("target inventory", missing)

    def test_target_inventory_rejects_rewritten_or_wrongly_typed_targets(self) -> None:
        cases = (
            (["x" * 2_001], "exceeds"),
            (["owned.py", 7], "strings"),
        )
        for targets, expected in cases:
            with self.subTest(targets=targets):
                evidence, missing = _read_target(
                    self.contract(), self.event(write_targets=targets)
                )
                self.assertEqual(evidence, "")
                self.assertIn(expected, missing)

    def test_target_inventory_count_and_summary_must_match_full_input(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        for override in (
            {"target_count": 2},
            {"target": "[local-target-set:forged]"},
            {"target_binding": "0" * 64},
        ):
            with self.subTest(override=override):
                evidence, missing = _read_target(
                    self.contract(), self.event(**override)
                )
                self.assertEqual(evidence, "")
                self.assertIn("target inventory", missing)

    def test_intermediate_symlink_in_recursive_owned_subtree_is_rejected(self) -> None:
        real = self.root / "real-dir"
        real.mkdir()
        (real / "new.py").write_text("NEW = True\n", encoding="utf-8")
        (self.root / "owned-tree").symlink_to(real, target_is_directory=True)

        evidence, missing = _read_target(
            self.contract(
                owned_paths=["owned-tree/**"],
                baseline_snapshot={"owned-tree/new.py": "!missing"},
            ),
            self.event(write_targets=["owned-tree/new.py"]),
        )

        self.assertEqual(evidence, "")
        self.assertIn("symbolic link", missing)

    def test_parent_rename_during_read_invalidates_declared_path_identity(self) -> None:
        parent = self.root / "owned-tree"
        parent.mkdir()
        target = parent / "new.py"
        target.write_text("NEW = True\n", encoding="utf-8")
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        real_read = os.read
        renamed = False

        def rename_parent_then_read(file_descriptor: int, size: int) -> bytes:
            nonlocal renamed
            opened = os.fstat(file_descriptor)
            if not renamed and (opened.st_dev, opened.st_ino) == target_identity:
                renamed = True
                parent.rename(self.root / "renamed-tree")
                parent.mkdir()
                (parent / "new.py").write_text("REPLACEMENT = True\n", encoding="utf-8")
            return real_read(file_descriptor, size)

        with mock.patch.object(os, "read", side_effect=rename_parent_then_read):
            evidence, missing = _read_target(
                self.contract(
                    owned_paths=["owned-tree/**"],
                    baseline_snapshot={"owned-tree/new.py": "!missing"},
                ),
                self.event(write_targets=["owned-tree/new.py"]),
            )

        self.assertEqual(evidence, "")
        self.assertIn("declared path changed", missing)

    def test_missing_secure_open_capability_fails_before_any_open(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        capability_patches = (
            mock.patch.object(os, "O_NOFOLLOW", 0),
            mock.patch.object(os, "O_DIRECTORY", 0),
            mock.patch.object(os, "supports_dir_fd", frozenset()),
            mock.patch.object(os, "supports_follow_symlinks", frozenset()),
        )
        for capability_patch in capability_patches:
            with self.subTest(capability_patch=capability_patch):
                with capability_patch, mock.patch.object(
                    os, "open", wraps=os.open
                ) as open_spy:
                    evidence, missing = _read_target(self.contract(), self.event())
                self.assertEqual(evidence, "")
                self.assertIn("secure open capability", missing)
                self.assertFalse(open_spy.called)

    def test_nfkc_distinct_file_cannot_expand_exact_ownership(self) -> None:
        distinct = "\N{KELVIN SIGN}.py"
        (self.root / distinct).write_text("DISTINCT = True\n", encoding="utf-8")

        evidence, missing = _read_target(
            self.contract(
                owned_paths=["K.py"], baseline_snapshot={distinct: "!missing"}
            ),
            self.event(write_targets=[distinct]),
        )

        self.assertEqual(evidence, "")
        self.assertIn("ambiguous", missing)

    def test_exact_owned_path_predicate_is_case_sensitive(self) -> None:
        (self.root / "case.py").write_text("CASE = True\n", encoding="utf-8")

        evidence, missing = _read_target(
            self.contract(
                owned_paths=["CASE.py"], baseline_snapshot={"case.py": "!missing"}
            ),
            self.event(write_targets=["case.py"]),
        )

        self.assertEqual(evidence, "")
        self.assertIn("ambiguous", missing)

    def test_mutable_or_abbreviated_baseline_is_rejected(self) -> None:
        self.git("tag", "mutable-baseline")
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        for baseline in ("HEAD", "mutable-baseline", self.baseline[:12], self.baseline.upper()):
            with self.subTest(baseline=baseline):
                evidence, missing = _read_target(
                    self.contract(base_commit=baseline),
                    self.event(baseline=baseline),
                )
                self.assertEqual(evidence, "")
                self.assertIn("full lowercase commit OID", missing)

    def test_attributes_textconv_and_clean_filter_never_execute(self) -> None:
        textconv_marker = self.root / "textconv-ran"
        clean_marker = self.root / "clean-ran"
        (self.root / ".gitattributes").write_text(
            "owned.py diff=hostile filter=hostile\n", encoding="utf-8"
        )
        self.git(
            "config",
            "diff.hostile.textconv",
            f"sh -c 'touch {textconv_marker}' placeholder",
        )
        self.git(
            "config",
            "filter.hostile.clean",
            f"sh -c 'touch {clean_marker}; cat'",
        )
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )

        evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(missing, "")
        self.assertIn("+CURRENT = True", evidence)
        self.assertFalse(textconv_marker.exists())
        self.assertFalse(clean_marker.exists())

    def test_diff_is_generated_from_raw_blob_and_worktree_bytes(self) -> None:
        (self.root / ".gitattributes").write_text("raw.txt -text\n", encoding="utf-8")
        raw = self.root / "raw.txt"
        raw.write_bytes(b"BASE\r\n")
        self.git("add", ".gitattributes", "raw.txt")
        self.git("commit", "-q", "-m", "raw baseline")
        self.baseline = self.git("rev-parse", "HEAD").stdout.strip()
        self.snapshot = self.snapshot_files()
        raw.write_bytes(b"BASE\r\nNEXT\r\n")

        evidence, missing = _read_target(
            self.contract(owned_paths=["raw.txt"]),
            self.event(write_targets=["raw.txt"], baseline=self.baseline),
        )

        self.assertEqual(missing, "")
        self.assertIn("+NEXT\r\n", evidence)

    def test_non_utf8_current_bytes_fail_closed(self) -> None:
        (self.root / "owned.py").write_bytes(b"BASE = True\n\xff")

        evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(evidence, "")
        self.assertIn("UTF-8", missing)

    def test_git_raw_blob_failure_is_inconclusive(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        real_run_git = intent_critic_module._run_git

        def fail_cat_file(root: Path, arguments: list[str], **kwargs):
            if "cat-file" in arguments and "blob" in arguments:
                return subprocess.CompletedProcess(arguments, 91, b"", b"injected")
            return real_run_git(root, arguments, **kwargs)

        with mock.patch.object(
            intent_critic_module, "_run_git", side_effect=fail_cat_file
        ):
            evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(evidence, "")
        self.assertIn("baseline read failed", missing)

    def test_open_read_metadata_drift_fails_closed(self) -> None:
        (self.root / "owned.py").write_text(
            "BASE = True\nCURRENT = True\n", encoding="utf-8"
        )
        real_file_state = getattr(intent_critic_module, "_file_state", None)
        calls = 0

        def drift_after_open(info):
            nonlocal calls
            calls += 1
            observed = real_file_state(info)
            if calls >= 3:
                return (*observed[:-1], observed[-1] + 1)
            return observed

        with mock.patch.object(
            intent_critic_module, "_file_state", side_effect=drift_after_open
        ):
            evidence, missing = _read_target(self.contract(), self.event())

        self.assertEqual(evidence, "")
        self.assertIn("changed while being read", missing)

    def test_public_builder_projection_round_trip(self) -> None:
        current = self.registered_evidence()[0]
        task_projection = {
            "task_id": "T-current",
            "base_commit": self.baseline,
            "verification_run_id": "run-current",
            "owned_paths": ["owned.py"],
            "evidence_floor_sequence": 10,
        }
        scope = intent_critic_module.build_task_critic_scope(
            task_projection,
            [current],
            {"owned.py": self.snapshot["owned.py"]},
        )
        event = intent_critic_module.bind_task_critic_checkpoint_event(
            {"effect": "local_write", "write_targets": ["owned.py"]}, scope
        )
        contract = {
            "workspace_root": str(self.root),
            "critic": {"task_scope": scope.as_projection()},
        }
        (self.root / "owned.py").write_text(
            "BASE = True\nROUND_TRIP = True\n", encoding="utf-8"
        )

        evidence, missing = _read_target(contract, event)

        self.assertEqual(missing, "")
        self.assertEqual(event["registered_evidence_ids"], ["e-current"])
        self.assertIn("+ROUND_TRIP = True", evidence)
        self.assertIn("CURRENT RUN REGISTERED TEST PASSED", evidence)
        self.assertIs(type(scope.as_projection()), dict)
        self.assertTrue(
            all(type(item) is str for item in scope.as_projection()["owned_paths"])
        )
        self.assertTrue(
            all(
                type(path) is str and type(digest) is str
                for path, digest in scope.as_projection()["baseline_snapshot"].items()
            )
        )
        self.assertTrue(
            all(type(item) is str for item in event["write_targets"])
        )
        self.assertTrue(
            all(type(item) is str for item in event["registered_evidence_ids"])
        )
        self.assertIs(type(event["target"]), str)
        self.assertIs(type(event["target_binding"]), str)

    def test_public_builder_rejects_non_string_authority_identities(self) -> None:
        class StringLikeIdentity:
            def __str__(self) -> str:
                return "same-looking-identity"

        invalid_values = (
            7,
            True,
            ["same-looking-identity"],
            {"identity": "same-looking-identity"},
            Path("same-looking-identity"),
            StringLikeIdentity(),
            HostileString("same-looking-identity"),
        )
        projection = {
            "task_id": "T-current",
            "base_commit": self.baseline,
            "verification_run_id": "run-current",
            "owned_paths": ["owned.py"],
            "evidence_floor_sequence": 10,
        }
        for field in ("task_id", "base_commit", "verification_run_id"):
            for value in invalid_values:
                with self.subTest(field=field, value_type=type(value).__name__):
                    with self.assertRaisesRegex(
                        intent_critic_module.IntentGuardianError,
                        "exact nonempty string",
                    ):
                        intent_critic_module.build_task_critic_scope(
                            {**projection, field: value},
                            self.registered_evidence(),
                            {"owned.py": self.snapshot["owned.py"]},
                        )
        for value in invalid_values:
            with self.subTest(field="owned_paths", value_type=type(value).__name__):
                with self.assertRaisesRegex(
                    intent_critic_module.IntentGuardianError,
                    "owned path entries",
                ):
                    intent_critic_module.build_task_critic_scope(
                        {**projection, "owned_paths": [value]},
                        self.registered_evidence(),
                        {"owned.py": self.snapshot["owned.py"]},
                    )
        for field in ("task_id", "baseline", "run_id"):
            for value in invalid_values:
                with self.subTest(
                    field=f"registered_evidence.{field}",
                    value_type=type(value).__name__,
                ):
                    evidence = self.registered_evidence()
                    evidence[0][field] = value
                    with self.assertRaisesRegex(
                        intent_critic_module.IntentGuardianError,
                        "identities must be exact nonempty strings",
                    ):
                        intent_critic_module.build_task_critic_scope(
                            projection,
                            evidence,
                            {"owned.py": self.snapshot["owned.py"]},
                        )
        for field, snapshot in (
            (
                "baseline_snapshot.key",
                {HostileString("owned.py"): self.snapshot["owned.py"]},
            ),
            (
                "baseline_snapshot.digest",
                {"owned.py": HostileString(self.snapshot["owned.py"])},
            ),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    intent_critic_module.IntentGuardianError,
                    "baseline snapshot",
                ):
                    intent_critic_module.build_task_critic_scope(
                        projection,
                        self.registered_evidence(),
                        snapshot,
                    )

    def test_public_event_binder_revalidates_scope_and_target_types(self) -> None:
        projection = {
            "task_id": "T-current",
            "base_commit": self.baseline,
            "verification_run_id": "run-current",
            "owned_paths": ["owned.py"],
            "evidence_floor_sequence": 10,
        }
        scope = intent_critic_module.build_task_critic_scope(
            projection,
            self.registered_evidence(),
            {"owned.py": self.snapshot["owned.py"]},
        )
        invalid_scope = intent_critic_module.TaskCriticScope(
            task_id=7,
            baseline=scope.baseline,
            run_id=scope.run_id,
            owned_paths=scope.owned_paths,
            baseline_snapshot=scope.baseline_snapshot,
            evidence_floor_sequence=scope.evidence_floor_sequence,
            registered_evidence=scope.registered_evidence,
        )

        with self.assertRaisesRegex(
            intent_critic_module.IntentGuardianError, "exact nonempty string"
        ):
            intent_critic_module.bind_task_critic_checkpoint_event(
                {"effect": "local_write", "write_targets": ["owned.py"]},
                invalid_scope,
            )
        for target in (Path("owned.py"), HostileString("owned.py")):
            with self.subTest(target_type=type(target).__name__):
                with self.assertRaisesRegex(
                    intent_critic_module.IntentGuardianError, "entries must be strings"
                ):
                    intent_critic_module.bind_task_critic_checkpoint_event(
                        {"effect": "local_write", "write_targets": [target]},
                        scope,
                    )

    def test_public_builder_binds_the_complete_target_inventory(self) -> None:
        task_projection = {
            "task_id": "T-current",
            "base_commit": self.baseline,
            "verification_run_id": "run-current",
            "owned_paths": ["owned.py"],
            "evidence_floor_sequence": 10,
        }
        scope = intent_critic_module.build_task_critic_scope(
            task_projection,
            self.registered_evidence(),
            {"owned.py": self.snapshot["owned.py"]},
        )
        targets = ["owned.py", *[f"noise-{index}.py" for index in range(64)]]

        event = intent_critic_module.bind_task_critic_checkpoint_event(
            {
                "effect": "local_write",
                "write_targets": targets,
                "target": "[local-target-set:forged]",
                "target_count": 1,
                "target_overflow": 0,
                "target_binding": "0" * 64,
            },
            scope,
        )

        expected_binding = hashlib.sha256(
            json.dumps(
                targets, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(event["write_targets"], targets)
        self.assertEqual(event["target_count"], 65)
        self.assertEqual(event["target_overflow"], 1)
        self.assertEqual(event["target_binding"], expected_binding)
        self.assertEqual(event["target"], f"[local-target-set:{expected_binding[:16]}]")
        evidence, missing = _read_target(
            {
                "workspace_root": str(self.root),
                "critic": {"task_scope": scope.as_projection()},
            },
            event,
        )
        self.assertEqual(evidence, "")
        self.assertIn("target inventory", missing)
        with self.assertRaisesRegex(
            intent_critic_module.IntentGuardianError, "exceeds"
        ):
            intent_critic_module.bind_task_critic_checkpoint_event(
                {"effect": "local_write", "target": "x" * 2_001}, scope
            )


if __name__ == "__main__":
    unittest.main()
