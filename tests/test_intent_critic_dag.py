from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
sys.path.insert(0, str(SCRIPT_DIR))

import intent_critic  # noqa: E402


class IntentCriticDagTests(unittest.TestCase):
    def test_critic_import_does_not_require_the_guardian_facade(self) -> None:
        source = (SCRIPT_DIR / "intent_critic.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        self.assertNotIn("intent_guardian", imported)

        code = f"""
import importlib.abc
import sys
sys.path.insert(0, {str(SCRIPT_DIR)!r})

class BlockGuardianFacade(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "intent_guardian":
            raise AssertionError("intent_guardian facade import is forbidden")
        return None

sys.meta_path.insert(0, BlockGuardianFacade())
import intent_critic
assert "intent_guardian" not in sys.modules
"""
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_shared_exception_has_one_identity_across_leaf_and_critic(self) -> None:
        from intent_guardian_errors import IntentGuardianError

        leaf_tree = ast.parse(
            (SCRIPT_DIR / "intent_guardian_errors.py").read_text(encoding="utf-8")
        )
        critic_tree = ast.parse(
            (SCRIPT_DIR / "intent_critic.py").read_text(encoding="utf-8")
        )
        self.assertFalse(
            any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(leaf_tree))
        )
        self.assertEqual(
            [
                node.name
                for node in ast.walk(leaf_tree)
                if isinstance(node, ast.ClassDef)
            ],
            ["IntentGuardianError"],
        )
        self.assertFalse(
            any(
                isinstance(node, ast.ClassDef) and node.name == "IntentGuardianError"
                for node in ast.walk(critic_tree)
            )
        )
        self.assertIs(intent_critic.IntentGuardianError, IntentGuardianError)

    def test_public_scope_builder_and_binder_round_trip(self) -> None:
        evidence = {
            "evidence_id": "e-current",
            "task_id": "T-current",
            "baseline": "a" * 40,
            "run_id": "run-current",
            "recorded_sequence": 11,
            "scope": "task",
            "valid": True,
        }
        scope = intent_critic.build_task_critic_scope(
            {
                "task_id": "T-current",
                "base_commit": "a" * 40,
                "verification_run_id": "run-current",
                "owned_paths": ["scripts/kb/intent_critic.py"],
                "evidence_floor_sequence": 10,
            },
            [evidence],
            {"scripts/kb/intent_critic.py": "!missing"},
        )
        projection = scope.as_projection()
        event = intent_critic.bind_task_critic_checkpoint_event(
            {
                "effect": "local_write",
                "write_targets": ["scripts/kb/intent_critic.py"],
            },
            scope,
        )

        self.assertEqual(projection["schema"], intent_critic.TASK_SCOPE_SCHEMA)
        self.assertEqual(event["task_id"], projection["task_id"])
        self.assertEqual(event["baseline"], projection["base_commit"])
        self.assertEqual(event["run_id"], projection["verification_run_id"])
        self.assertEqual(event["registered_evidence_ids"], ["e-current"])
        self.assertEqual(event["target_count"], 1)

    def test_malformed_authority_stops_before_git_and_model_selection(self) -> None:
        class NativeStringSubclass(str):
            pass

        class MagicIdentity:
            def __str__(self) -> str:
                return "T-current"

        scope = intent_critic.build_task_critic_scope(
            {
                "task_id": "T-current",
                "base_commit": "a" * 40,
                "verification_run_id": "run-current",
                "owned_paths": ["scripts/kb/intent_critic.py"],
                "evidence_floor_sequence": 10,
            },
            [],
            {"scripts/kb/intent_critic.py": "!missing"},
        )
        valid_scope = scope.as_projection()
        valid_event = intent_critic.bind_task_critic_checkpoint_event(
            {
                "effect": "local_write",
                "write_targets": ["scripts/kb/intent_critic.py"],
            },
            scope,
        )
        malformed_plain_json = json.loads('{"schema":"malformed-scope-v0"}')
        cases = (
            (malformed_plain_json, valid_event, "unsupported critic task scope schema"),
            (
                {**valid_scope, "task_id": NativeStringSubclass("T-current")},
                valid_event,
                "exact nonempty string",
            ),
            (
                {**valid_scope, "task_id": MagicIdentity()},
                valid_event,
                "exact nonempty string",
            ),
            (
                {key: value for key, value in valid_scope.items() if key != "task_id"},
                valid_event,
                "exact nonempty string",
            ),
            (
                valid_scope,
                {**valid_event, "task_id": NativeStringSubclass("T-current")},
                "exact nonempty string",
            ),
            (
                valid_scope,
                {**valid_event, "task_id": MagicIdentity()},
                "exact nonempty string",
            ),
            (
                valid_scope,
                {key: value for key, value in valid_event.items() if key != "task_id"},
                "exact nonempty string",
            ),
        )

        for raw_scope, event, expected in cases:
            contract = {
                "workspace_root": str(ROOT),
                "critic": {"task_scope": raw_scope},
            }
            with self.subTest(expected=expected, scope_type=type(raw_scope).__name__):
                with (
                    mock.patch.object(intent_critic, "_run_git") as run_git,
                    mock.patch.object(intent_critic, "select_provider") as select_provider,
                ):
                    result = intent_critic.run_critic(
                        contract, event, provider="codex"
                    )

                self.assertEqual(result["verdict"], "inconclusive")
                self.assertEqual(result["next_action"], "collect_evidence")
                self.assertIn(expected, result["summary"])
                run_git.assert_not_called()
                select_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
