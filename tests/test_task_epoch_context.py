from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from sulde_config import ConfigLayer, ConfigLayerKind, resolve_config  # noqa: E402
from sulde_effects import DEFAULT_EFFECT_ROUTER  # noqa: E402
from sulde_execution import (  # noqa: E402
    TaskBudgets,
    TaskContextError,
    TaskEpochContext,
)
from sulde_protocol import Provider  # noqa: E402


class TaskEpochContextTests(unittest.TestCase):
    def snapshot(self, limit: int = 100):
        return resolve_config(
            (
                ConfigLayer.build(
                    name="task",
                    kind=ConfigLayerKind.TASK,
                    values={"limits.events": limit},
                ),
            )
        )

    def context(self, limit: int = 100) -> TaskEpochContext:
        return TaskEpochContext.build(
            workspace_id="b" * 64,
            intent_id="intent-one",
            intent_revision=141,
            task_epoch="e" * 24,
            provider=Provider.CODEX,
            native_session_id="session-one",
            task_definition_sha256="1" * 64,
            owned_paths=("scripts/kb", "tests"),
            policy_sha256="2" * 64,
            config_snapshot=self.snapshot(limit),
            effect_router=DEFAULT_EFFECT_ROUTER,
            tool_registry_sha256="3" * 64,
            runtime_generation="4" * 64,
            budgets=TaskBudgets(
                max_events=100,
                max_context_tokens=8000,
                max_effects=20,
                max_runtime_seconds=3600,
            ),
            legacy_cut_id="5" * 64,
        )

    def test_context_round_trips_and_is_deterministic(self) -> None:
        first = self.context()
        second = self.context()
        self.assertEqual(first, second)
        self.assertEqual(TaskEpochContext.from_dict(first.to_dict()), first)
        self.assertEqual(
            first.capability_manifest_sha256,
            DEFAULT_EFFECT_ROUTER.manifest_sha256,
        )

    def test_config_or_runtime_change_creates_next_context(self) -> None:
        current = self.context()
        changed_config = self.context(limit=99)
        changed_runtime = TaskEpochContext.build(
            **{
                key: value
                for key, value in {
                    "workspace_id": current.workspace_id,
                    "intent_id": current.intent_id,
                    "intent_revision": current.intent_revision,
                    "task_epoch": current.task_epoch,
                    "provider": current.provider,
                    "native_session_id": current.native_session_id,
                    "task_definition_sha256": current.task_definition_sha256,
                    "owned_paths": current.owned_paths,
                    "policy_sha256": current.policy_sha256,
                    "config_snapshot": self.snapshot(),
                    "effect_router": DEFAULT_EFFECT_ROUTER,
                    "tool_registry_sha256": current.tool_registry_sha256,
                    "runtime_generation": "6" * 64,
                    "budgets": current.budgets,
                    "legacy_cut_id": current.legacy_cut_id,
                }.items()
            }
        )
        self.assertNotEqual(current.context_id, changed_config.context_id)
        self.assertNotEqual(current.context_id, changed_runtime.context_id)

    def test_context_rejects_path_escape_and_digest_tampering(self) -> None:
        with self.assertRaisesRegex(TaskContextError, "workspace-relative"):
            TaskEpochContext.build(
                workspace_id="b" * 64,
                intent_id="intent-one",
                intent_revision=1,
                task_epoch="e" * 24,
                provider=Provider.CODEX,
                native_session_id="session-one",
                task_definition_sha256="1" * 64,
                owned_paths=("../outside",),
                policy_sha256="2" * 64,
                config_snapshot=self.snapshot(),
                effect_router=DEFAULT_EFFECT_ROUTER,
                tool_registry_sha256="3" * 64,
                runtime_generation="4" * 64,
                budgets=TaskBudgets(1, 1, 1, 1),
            )
        current = self.context()
        with self.assertRaisesRegex(TaskContextError, "does not match"):
            replace(current, context_id="0" * 64)
        with self.assertRaisesRegex(TaskContextError, "collection"):
            TaskEpochContext.build(
                workspace_id="b" * 64,
                intent_id="intent-one",
                intent_revision=1,
                task_epoch="e" * 24,
                provider=Provider.CODEX,
                native_session_id="session-one",
                task_definition_sha256="1" * 64,
                owned_paths="scripts/kb",
                policy_sha256="2" * 64,
                config_snapshot=self.snapshot(),
                effect_router=DEFAULT_EFFECT_ROUTER,
                tool_registry_sha256="3" * 64,
                runtime_generation="4" * 64,
                budgets=TaskBudgets(1, 1, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()
