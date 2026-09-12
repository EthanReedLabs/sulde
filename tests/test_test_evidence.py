from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "test-evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sulde_test_evidence_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEvidenceTests(unittest.TestCase):
    def test_content_binding_ignores_logs_but_invalidates_inputs_and_test_set(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "scripts").mkdir()
            source = root / "scripts/runner.py"
            source.write_text("pass\n", encoding="utf-8")
            dependency = root / "requirements.txt"
            dependency.write_text("dependency==1\n", encoding="utf-8")
            log = root / "unrelated.log"
            inventory = "scripts/runner.py\0requirements.txt\0unrelated.log\0"
            selected = {"head": "old", "risk": "refactor", "tests": []}
            with mock.patch.object(module, "ROOT", root), mock.patch.object(module, "RUNNER", source), mock.patch.object(module, "_git", return_value=inventory):
                initial = module.evidence_key(selected)
                log.write_text("new diagnostic output", encoding="utf-8")
                self.assertEqual(initial, module.evidence_key({**selected, "head": "log-only-commit"}))
                dependency.write_text("dependency==2\n", encoding="utf-8")
                self.assertNotEqual(initial, module.evidence_key(selected))
                dependency.write_text("dependency==1\n", encoding="utf-8")
                self.assertNotEqual(initial, module.evidence_key({**selected, "tests": ["tests.changed"]}))
                source.write_text("raise RuntimeError()\n", encoding="utf-8")
                self.assertNotEqual(initial, module.evidence_key(selected))

    def test_source_bytecode_cleanup_removes_only_derived_files(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache = root / "scripts" / "pkg" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "module.pyc").write_bytes(b"derived")
            source = root / "scripts" / "pkg" / "module.py"
            source.write_text("value = 1\n", encoding="utf-8")

            result = module.clean_source_bytecode(root)

            self.assertEqual(result["files_removed"], 1)
            self.assertEqual(result["directories_removed"], 1)
            self.assertTrue(source.is_file())
            self.assertFalse(cache.exists())

    def test_risk_tiers_select_targeted_or_full_scope(self) -> None:
        module = load_module()
        self.assertEqual(module.classify(["docs/note.md"]), "small")
        self.assertEqual(
            module.classify([f"feature/file-{index}.py" for index in range(5)]),
            "medium",
        )
        self.assertEqual(
            module.classify(["scripts/kb/intent_guardian_parts/policy.py"]),
            "refactor",
        )
        self.assertEqual(
            module.impacted_tests(["scripts/kb/intervention.py"], "medium"),
            ["tests.test_intervention"],
        )
        self.assertEqual(
            module.impacted_tests(["scripts/kb/intervention.py"], "refactor"),
            [],
        )
        self.assertEqual(
            module.impacted_tests(["scripts/kb/agent-runtime.py"], "small"),
            ["tests.test_agent_runtime"],
        )

    def test_codex_hook_impact_map_names_only_existing_test_modules(self) -> None:
        module = load_module()
        selected = module.impacted_tests(
            ["integrations/codex/plugins/sulde/scripts/user-prompt-submit.py"],
            "small",
        )

        self.assertIn("tests.test_codex_hook_bridge", selected)
        self.assertIn("tests.test_codex_user_prompt_adapter", selected)
        for name in selected:
            self.assertTrue(
                (ROOT / f"{name.replace('.', '/')}.py").is_file(),
                f"planned test module does not exist: {name}",
            )

    def test_reuse_requires_exact_unexpired_passing_key(self) -> None:
        module = load_module()
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for label, key, status, age in (
                ("exact", "a" * 64, "passed", 1),
                ("failed", "b" * 64, "failed", 1),
                ("stale", "c" * 64, "passed", 60),
            ):
                row = {
                    "schema": module.SCHEMA,
                    "run_id": label,
                    "evidence_key": key,
                    "status": status,
                    "ended_at": (now - timedelta(days=age)).isoformat(),
                }
                (root / f"{label}.json").write_text(json.dumps(row), encoding="utf-8")
            self.assertEqual(
                module.reusable_record(root, "a" * 64, current=now)["run_id"],
                "exact",
            )
            self.assertIsNone(module.reusable_record(root, "b" * 64, current=now))
            self.assertIsNone(module.reusable_record(root, "c" * 64, current=now))

    def test_gc_preserves_first_failure_and_latest_full_baseline(self) -> None:
        module = load_module()
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)

            def add(label: str, *, status: str, suite: str, age: int, key: str) -> None:
                log = root / f"{label}.log"
                log.write_text(label, encoding="utf-8")
                row = {
                    "schema": module.SCHEMA,
                    "run_id": label,
                    "evidence_key": key,
                    "status": status,
                    "suite": suite,
                    "ended_at": (now - timedelta(days=age)).isoformat(),
                    "log": log.name,
                }
                (root / f"{label}.json").write_text(json.dumps(row), encoding="utf-8")

            add("first-failure", status="failed", suite="targeted", age=90, key="k")
            add("later-failure", status="failed", suite="targeted", age=80, key="k")
            add("latest-full", status="passed", suite="full", age=60, key="full")
            add("expired-pass", status="passed", suite="targeted", age=60, key="old")

            result = module.gc_records(root, current=now, ttl_days=30, max_records=2)
            self.assertEqual(result["status"], "planned")
            self.assertFalse(result["deletion_performed"])
            self.assertEqual(result["removed"], 0)
            self.assertEqual(result["candidate_count"], 2)
            for label in (
                "first-failure", "latest-full", "later-failure", "expired-pass"
            ):
                self.assertTrue((root / f"{label}.json").is_file())
                self.assertTrue((root / f"{label}.log").is_file())


    def test_partial_or_nonzero_result_is_never_reused_as_success(self) -> None:
        module = load_module()
        now = datetime(2026, 9, 4, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            base = {
                "schema": module.SCHEMA,
                "evidence_key": "d" * 64,
                "status": "passed",
                "ended_at": now.isoformat(),
            }
            for label, changes in (
                ("partial", {"partial": True}),
                ("nonzero", {"exit_code": 1}),
                ("incomplete", {"result": {"complete": False, "verdict": "passed"}}),
                ("failed-result", {"result": {"complete": True, "verdict": "failed"}}),
            ):
                (root / f"{label}.json").write_text(
                    json.dumps({**base, "run_id": label, **changes}),
                    encoding="utf-8",
                )
            self.assertIsNone(
                module.reusable_record(root, "d" * 64, current=now)
            )

    def test_plan_exposes_impact_graph_scope_and_only_verified_experience_strategy(self) -> None:
        module = load_module()
        experience_script = ROOT / "scripts" / "kb" / "agent-experience.py"
        spec = importlib.util.spec_from_file_location("test_evidence_experience", experience_script)
        assert spec is not None and spec.loader is not None
        experience = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(experience)
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            record = experience.build_record(
                task_id="task",
                run_id="run",
                project_id="project",
                session_id="session",
                task_instance_id="lane",
                problem_type="test_selection self repair",
                symptom="scripts kb self repair",
                handling="run focused regression",
                outcome="verified",
                result="tests passed",
                evidence=[],
                source_summary="managed summary",
                occurred_at="2026-09-04T00:00:00Z",
                recommended_tests=["tests.test_agent_experience"],
                affected_components=["scripts/kb/self-repair.py"],
            )
            experience.record(home, record)
            with (
                mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False),
                mock.patch.object(
                    module,
                    "changed_paths",
                    return_value=["scripts/kb/self-repair.py"],
                ),
                mock.patch.object(module, "_git", return_value="a" * 40 + "\n"),
            ):
                selected = module.plan("dev")

        self.assertEqual(selected["risk"], "small")
        self.assertEqual(selected["scope"]["selection"], "impact_graph")
        self.assertIn(
            "tests.test_self_repair",
            selected["impact_graph"]["scripts/kb/self-repair.py"],
        )
        self.assertIn("tests.test_agent_experience", selected["tests"])
        self.assertEqual(
            selected["experience_recall"]["strategy"]["source"],
            "verified_experience",
        )

    def test_installer_impact_mapping_names_the_current_test_module(self) -> None:
        module = load_module()
        with (
            mock.patch.object(
                module,
                "changed_paths",
                return_value=["scripts/release/install_codex_plugin.py"],
            ),
            mock.patch.object(module, "_git", return_value="a" * 40 + "\n"),
        ):
            selected = module.plan("dev", requested="medium")

        self.assertEqual(
            selected["tests"],
            ["tests.test_codex_plugin_install"],
        )


if __name__ == "__main__":
    unittest.main()
