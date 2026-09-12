from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "agent-experience.py"


def load_module():
    spec = importlib.util.spec_from_file_location("agent_experience_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, *, outcome: str = "verified", run_id: str = "run-one"):
        return self.module.build_record(
            task_id="task-one",
            run_id=run_id,
            project_id="project-one",
            session_id="session-one",
            task_instance_id="lane-one",
            problem_type="python test_selection",
            symptom="PyYAML import failed at /Users/private/customer/project",
            handling="used isolated interpreter; password=do-not-store",
            outcome=outcome,
            result="tests passed",
            evidence=[
                self.module.evidence_item(
                    "test_run", "scoped command completed", {"exit": 0}
                )
            ],
            source_summary="managed run summary",
            occurred_at="2026-09-04T00:00:00Z",
            recommended_tests=["tests.test_agent_experience"],
            affected_components=["scripts/kb/agent-experience.py"],
        )

    def test_record_is_structured_redacted_and_includes_no_issue_case(self) -> None:
        record = self.build()
        persisted = self.module.record(self.home, record)

        self.assertEqual(persisted["outcome"], "verified")
        self.assertIn("<redacted-path>", persisted["symptom"])
        self.assertIn("<redacted-secret>", persisted["handling"])
        rendered = json.dumps(persisted, ensure_ascii=False)
        self.assertNotIn("/Users/private", rendered)
        self.assertNotIn("do-not-store", rendered)
        no_issue = self.module.build_record(
            task_id="task-two",
            run_id="run-two",
            project_id="project-one",
            session_id="session-two",
            task_instance_id="lane-two",
            problem_type="none",
            symptom="",
            handling="",
            outcome="verified",
            result="no problems found",
            evidence=[],
            source_summary="managed run summary",
            occurred_at="2026-09-04T00:00:01Z",
        )
        self.assertEqual(no_issue["symptom"], "no issue observed")

    def test_raw_private_path_is_rejected_if_contract_is_bypassed(self) -> None:
        record = self.build()
        record["symptom"] = "/Users/private/raw/tool-output.txt"
        with self.assertRaisesRegex(self.module.ExperienceError, "sensitive"):
            self.module.validate_record(record)

    def test_recall_separates_verified_strategy_from_diagnostic_and_unresolved(self) -> None:
        for outcome, run in (
            ("verified", "run-v"),
            ("inconclusive", "run-i"),
            ("unresolved", "run-u"),
        ):
            self.module.record(self.home, self.build(outcome=outcome, run_id=run))
        recall = self.module.recall(
            self.home,
            problem_type="test_selection",
            symptom="PyYAML import",
            affected_components=["scripts/kb/agent-experience.py"],
        )
        self.assertEqual(recall["strategy"]["source"], "verified_experience")
        self.assertEqual(
            recall["strategy"]["recommended_tests"],
            ["tests.test_agent_experience"],
        )
        self.assertEqual(len(recall["diagnostic_hints"]), 1)
        self.assertEqual(recall["unresolved_retained"], 1)

        candidates = self.module.sedimentation_candidates(self.home)
        self.assertFalse(candidates["knowledge_write_performed"])
        self.assertTrue(candidates["single_writer_required"])
        self.assertEqual(len(candidates["candidates"]), 1)
        self.assertFalse((self.home / "knowledge").exists())

    def test_concurrent_idempotent_writers_leave_one_whole_record(self) -> None:
        record = self.build()
        with ThreadPoolExecutor(max_workers=8) as executor:
            values = list(
                executor.map(
                    lambda _index: self.module.record(self.home, record),
                    range(16),
                )
            )
        self.assertTrue(all(value == record for value in values))
        rows = self.module.load_records(self.home)
        self.assertEqual(rows, [record])
        raw = (self.home / "experience" / "agent.jsonl").read_text(encoding="utf-8")
        self.assertEqual(len(raw.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
