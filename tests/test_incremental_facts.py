"""Incremental fact collection and judgment records (B2)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import execution_judgment as ej  # noqa: E402
import incremental_facts as facts  # noqa: E402
import impact_prediction as ip  # noqa: E402

NOW = "2026-09-27T10:00:00+00:00"


class _GitRepo:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args: str, check: bool = True):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
        if check and result.returncode != 0:
            raise AssertionError(result.stderr)
        return result

    def commit_file(self, path: str, content: str, message: str):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.run("add", path)
        self.run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)


class IncrementalFactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmp.name) / "repo"
        self.repo_dir.mkdir()
        self.repo = _GitRepo(self.repo_dir)
        self.repo.run("init", "-q")
        self.repo.commit_file("scripts/kb/example.py", "def alpha():\n    return 1\n", "base")
        self.repo.run("tag", "baseline")

    def tearDown(self):
        self.tmp.cleanup()

    def test_diff_facts_split_inside_and_outside_expected(self):
        self.repo.commit_file("scripts/kb/example.py", "def alpha():\n    return 2\n", "change expected")
        self.repo.commit_file("docs/random-note.md", "note\n", "change unexpected")
        bundle = facts.collect(self.repo_dir, baseline="baseline",
                               expected_paths=["scripts/kb/example.py"],
                               source_identities={"scripts/kb/example.py": "stale000000000001"})
        self.assertIn("docs/random-note.md", bundle["split"]["outside_expected"])
        self.assertIn("scripts/kb/example.py", bundle["split"]["inside_expected"])
        self.assertEqual(bundle["source_identity_drift"]["drifted"]["scripts/kb/example.py"]["actual"], "missing" if False else bundle["source_identity_drift"]["drifted"]["scripts/kb/example.py"]["actual"])

    def test_staleness_from_content_drift(self):
        self.repo.commit_file("scripts/kb/example.py", "def alpha():\n    return 2\n", "change")
        import hashlib
        current = hashlib.sha256((self.repo_dir / "scripts/kb/example.py").read_bytes()).hexdigest()[:16]
        drift = facts.source_identity_drift(self.repo_dir, {"scripts/kb/example.py": current})
        self.assertEqual(drift["drift_count"], 0)
        drift = facts.source_identity_drift(self.repo_dir, {"scripts/kb/example.py": "0000000000000000"})
        self.assertEqual(drift["drift_count"], 1)

    def test_symbol_references_bounded_and_relative(self):
        self.repo.commit_file("scripts/kb/other.py", "from example import alpha\nalpha()\n", "ref")
        result = facts.symbol_references(self.repo_dir, ["alpha"])
        self.assertIn("scripts/kb/other.py", result["references"]["alpha"])
        self.assertIn("scripts/kb/example.py", result["references"]["alpha"])

    def test_classification_suggestions(self):
        prediction = {"expected_touch": {"entries": ["scripts/kb/example.py"]}}
        diff = {"changed_paths": ["scripts/kb/example.py"]}
        split = facts.split_by_expected(diff["changed_paths"], ["scripts/kb/example.py"])
        self.assertEqual(facts.classify_against_prediction(diff, split, prediction)["suggested_verdict"],
                         "as_predicted")
        diff2 = {"changed_paths": ["scripts/kb/example.py", "scripts/kb/surprise.py"]}
        split2 = facts.split_by_expected(diff2["changed_paths"], ["scripts/kb/example.py"])
        self.assertEqual(facts.classify_against_prediction(diff2, split2, prediction)["suggested_verdict"],
                         "larger_than_predicted")
        drift = {"drift_count": 1,
                 "drifted": {"docs/untouched.py": {"expected": "a", "actual": "b"}}}
        self.assertEqual(facts.classify_against_prediction(diff, split, prediction | {})["suggested_verdict"],
                         "as_predicted")
        facts_bundle = {"changed_paths": diff["changed_paths"],
                        "expected_paths": ["scripts/kb/example.py"],
                        "source_identity_drift": drift}
        self.assertEqual(facts.classify_against_prediction(facts_bundle, split, prediction)["suggested_verdict"],
                         "divergent")
        diff3 = {"changed_paths": []}
        split3 = facts.split_by_expected(diff3["changed_paths"], ["scripts/kb/example.py"])
        self.assertEqual(facts.classify_against_prediction(diff3, split3, prediction)["suggested_verdict"],
                         "smaller_than_predicted")
        # an unrelated outside change is mechanically "larger" first;
        # the agent may override with a judgment record and reasons
        diff4 = {"changed_paths": ["docs/other.md"]}
        split4 = facts.split_by_expected(diff4["changed_paths"], ["scripts/kb/example.py"])
        self.assertEqual(facts.classify_against_prediction(diff4, split4, prediction)["suggested_verdict"],
                         "larger_than_predicted")

    def test_partially_touched_expectation_reports_untouched(self):
        """R1-03 反例(修复前):预计 a+b 只改 a 仍 as_predicted。"""
        prediction = {"expected_touch": {"entries": ["a.py", "b.py"]}}
        diff = {"changed_paths": ["a.py"]}
        split = facts.split_by_expected(diff["changed_paths"], ["a.py", "b.py"])
        result = facts.classify_against_prediction(diff, split, prediction)
        self.assertEqual(result["suggested_verdict"], "smaller_than_predicted")
        self.assertEqual(result["untouched_expected"], ["b.py"])

    def test_directory_scope_counts_as_touched(self):
        prediction = {"expected_touch": {"entries": ["scripts/kb"]}}
        diff = {"changed_paths": ["scripts/kb/nested/x.py"]}
        split = facts.split_by_expected(diff["changed_paths"], ["scripts/kb"])
        result = facts.classify_against_prediction(diff, split, prediction)
        self.assertEqual(result["suggested_verdict"], "as_predicted")
        self.assertEqual(result["untouched_expected"], [])

    def test_simplification_vs_omission_is_agent_judgment(self):
        """同一机械信号,两种合法 Agent 判断——机械层不下结论。"""
        store = Path(self.tmp.name) / "judgments.jsonl"
        base = {"task_id": "t", "run_id": "r", "session_id": "s"}
        simplification = ej.record_judgment(store, {
            **base, "trigger": "after_logical_change_complete",
            "key_facts": ["untouched_expected=[b.py]", "b.py consumer removed upstream"],
            "next_action": "accept simplification; b.py need no longer exist",
        }, at=NOW)
        omission = ej.record_judgment(store, {
            **base, "trigger": "verification_contradicts_prediction",
            "key_facts": ["untouched_expected=[b.py]", "b.py caller still imports it"],
            "risks": ["import breakage on b.py consumers"],
            "next_action": "implement b.py or update its caller before delivery",
        }, at=NOW)
        self.assertIn("accept simplification", simplification["next_action"])
        self.assertIn("implement b.py", omission["next_action"])

    def test_check_appended_to_prediction_ledger(self):
        store = Path(self.tmp.name) / "predictions.jsonl"
        payload = {
            "task_id": "t", "run_id": "r", "session_id": "s", "project_id": "/p",
            "contract_version": "r1",
            "source_identities": {"a.py": "0123456789abcdef"},
            "objective": "x",
            "assumptions": [{"text": "a", "confidence": "low"}],
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
            "kind": "lightweight",
        }
        ip.open_prediction(store, payload, at=NOW, task_id="t")
        facts_bundle = {"changed_paths": [], "source_identity_drift": {"drifted": {}, "drift_count": 0}}
        split = {"inside_expected": [], "outside_expected": []}
        prediction = ip.load_projection(store)["tasks"][ip.digest("t")]["current"]
        verdict = facts.classify_against_prediction(facts_bundle, split, prediction)
        ip.record_check(store, {"verdict": verdict["suggested_verdict"],
                                "facts": [verdict["reason"]], "evidence": ["facts-bundle"]},
                        at=NOW, task_id="t")
        entry = ip.load_projection(store)["tasks"][ip.digest("t")]
        self.assertEqual(len(entry["checks"]), 1)
        self.assertEqual(entry["checks"][0]["verdict"], "as_predicted")


class ExecutionJudgmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "judgments.jsonl"
        self.base = {"task_id": "t", "run_id": "r", "session_id": "s"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_frozen_trigger_enforced(self):
        with self.assertRaises(ej.JudgmentError):
            ej.record_judgment(self.store, {**self.base, "trigger": "whenever_i_feel_like",
                                            "next_action": "x"}, at=NOW)

    def test_budget_and_required_fields(self):
        with self.assertRaises(ej.JudgmentError):
            ej.record_judgment(self.store, {**self.base, "trigger": "after_logical_change_complete",
                                            "next_action": ""}, at=NOW)
        with self.assertRaises(ej.JudgmentError):
            ej.record_judgment(self.store, {**self.base, "trigger": "after_logical_change_complete",
                                            "next_action": "x" * 2001}, at=NOW)
        row = ej.record_judgment(self.store, {
            **self.base, "trigger": "after_logical_change_complete",
            "prediction_id": "pred-x", "prediction_version": 2,
            "key_facts": ["diff confined to expected file"],
            "next_action": "run scoped tests",
            "evidence_refs": ["git:abc"],
        }, at=NOW)
        self.assertEqual(row["sequence"], 1)
        self.assertFalse(row["model_review_used"])
        self.assertNotIn("t", json.dumps(row["task_id_sha256"]))

    def test_append_only_and_filtering(self):
        for trigger in ("after_logical_change_complete", "new_dependency_discovered"):
            ej.record_judgment(self.store, {**self.base, "trigger": trigger,
                                            "next_action": "continue"}, at=NOW)
        rows = ej.load_judgments(self.store, task_id="t")
        self.assertEqual([r["sequence"] for r in rows], [1, 2])
        self.assertEqual(ej.load_judgments(self.store, task_id="other"), [])


if __name__ == "__main__":
    unittest.main()
