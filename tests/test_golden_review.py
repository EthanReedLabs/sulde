from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kb/golden-review.py"


def case(identifier: str, query: str = "query") -> dict:
    return {
        "id": identifier,
        "query": query,
        "project": "project",
        "expect_none": True,
        "note": "draft",
    }


class GoldenReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        self.candidates = self.home / "golden-candidates.jsonl"
        self.golden = Path(self.temporary.name) / "golden.jsonl"
        self.write_jsonl(self.candidates, [case("candidate-1"), case("candidate-2")])
        self.write_jsonl(self.golden, [case("existing")])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write_jsonl(path: Path, rows: list[dict]) -> None:
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    @staticmethod
    def read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def run_review(self, decisions: list[dict] | None = None, apply: bool = False):
        command = [
            sys.executable,
            str(SCRIPT),
            "--candidates",
            str(self.candidates),
            "--golden",
            str(self.golden),
            "--json",
        ]
        if decisions is not None:
            decision_path = Path(self.temporary.name) / "decisions.json"
            decision_path.write_text(json.dumps(decisions), encoding="utf-8")
            command.extend(["--decisions", str(decision_path)])
        if apply:
            command.append("--apply")
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        return subprocess.run(
            command,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_list_reports_pending_without_writes(self) -> None:
        before_candidates = self.candidates.read_bytes()
        before_golden = self.golden.read_bytes()
        completed = self.run_review()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["pending"], 2)
        self.assertEqual(self.candidates.read_bytes(), before_candidates)
        self.assertEqual(self.golden.read_bytes(), before_golden)

    def test_invalid_unrelated_candidate_is_reported_without_blocking_batch(self) -> None:
        invalid = case("candidate-invalid")
        invalid["project"] = ""
        self.write_jsonl(self.candidates, [case("candidate-1"), invalid])
        listed = self.run_review()
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)["invalid"], ["candidate-invalid"])
        applied = self.run_review(
            [{"id": "candidate-1", "action": "reject", "reason": "not useful"}],
            apply=True,
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        result = json.loads(applied.stdout)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(result["invalid"], ["candidate-invalid"])

    def test_invalid_candidate_can_be_rejected_or_corrected(self) -> None:
        invalid = case("candidate-1")
        invalid["project"] = ""
        self.write_jsonl(self.candidates, [invalid, case("candidate-2")])
        corrected = dict(invalid)
        corrected["project"] = "sulde-cc"
        accepted = self.run_review(
            [{"id": "candidate-1", "action": "accept", "reason": "project restored", "case": corrected}],
            apply=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(self.read_jsonl(self.golden)[-1]["project"], "sulde-cc")

    def test_preview_validates_batch_without_writes(self) -> None:
        decisions = [
            {"id": "candidate-1", "action": "accept", "reason": "valid regression"},
            {"id": "candidate-2", "action": "reject", "reason": "truncated and ambiguous"},
        ]
        before_candidates = self.candidates.read_bytes()
        completed = self.run_review(decisions)
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(result["writes"], 0)
        self.assertEqual(self.candidates.read_bytes(), before_candidates)

    def test_apply_promotes_accepts_removes_all_decisions_and_audits(self) -> None:
        decisions = [
            {"id": "candidate-1", "action": "accept", "reason": "valid regression"},
            {"id": "candidate-2", "action": "reject", "reason": "ambiguous"},
        ]
        completed = self.run_review(decisions, apply=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.read_jsonl(self.candidates), [])
        golden = self.read_jsonl(self.golden)
        self.assertEqual([row["id"] for row in golden], ["existing", "candidate-1"])
        self.assertIn("人工复核=valid regression", golden[-1]["note"])
        audit = self.read_jsonl(self.home / "golden-review-decisions.jsonl")
        self.assertEqual([row["action"] for row in audit[0]["decisions"]], ["accept", "reject"])

    def test_accept_override_supports_human_correction(self) -> None:
        corrected = case("candidate-1", "complete corrected query")
        corrected.pop("expect_none")
        corrected["expect_substring"] = "expected fact"
        completed = self.run_review(
            [{"id": "candidate-1", "action": "accept", "reason": "corrected truncation", "case": corrected}],
            apply=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        promoted = self.read_jsonl(self.golden)[-1]
        self.assertEqual(promoted["query"], "complete corrected query")
        self.assertEqual(promoted["expect_substring"], "expected fact")

    def test_incomplete_query_head_requires_complete_case_override(self) -> None:
        incomplete = case("candidate-1")
        incomplete["note"] = "draft; 接受前需人工确认完整性"
        self.write_jsonl(self.candidates, [incomplete])
        rejected = self.run_review(
            [{"id": "candidate-1", "action": "accept", "reason": "looks useful"}],
            apply=True,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("acceptance requires a complete case override", rejected.stderr)

        confirmed = dict(incomplete)
        confirmed["note"] = "人工确认完整查询"
        accepted = self.run_review(
            [{
                "id": "candidate-1",
                "action": "accept",
                "reason": "full query confirmed",
                "case": confirmed,
            }],
            apply=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_explicit_stage_accounting_and_terminal_journal_replay(self) -> None:
        rows = [case("pending"), {**case("generated"), "schema": "sulde-golden-candidate-v2", "stage": "generated"},
                {**case("revision"), "project": ""}, case("ready"), case("accepted"), case("rejected")]
        self.write_jsonl(self.candidates, rows)
        decision = self.run_review([
            {"id": "ready", "action": "ready", "reason": "human checked"},
            {"id": "accepted", "action": "accept", "reason": "human accepted"},
            {"id": "rejected", "action": "reject", "reason": "human rejected"},
        ], apply=True)
        self.assertEqual(decision.returncode, 0, decision.stderr)
        listed = self.run_review()
        self.assertEqual(listed.returncode, 0, listed.stderr)
        result = json.loads(listed.stdout)
        self.assertEqual({key: result[key] for key in (
            "raw_total", "generated", "generated_unsubmitted", "pending_review",
            "revision_required", "ready_promotable", "terminal_decisions")},
            {"raw_total": 4, "generated": 6, "generated_unsubmitted": 1, "pending_review": 1,
             "revision_required": 1, "ready_promotable": 1, "terminal_decisions": 2})
        before = self.candidates.read_bytes()
        preview = self.run_review([{"id": "pending", "action": "revise", "reason": "needs source"}])
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(self.candidates.read_bytes(), before)
        self.assertEqual(json.loads(preview.stdout)["stage_accounting"]["revision_required"], 2)

    def test_current_schema_drift_unknown_versions_and_forged_ready_rejected(self) -> None:
        for row in (
            {**case("x"), "schema": "sulde-golden-candidate-v2", "stage": "pending_review", "extra": True},
            {**case("x"), "schema": "sulde-golden-candidate-v3"},
            {**case("x"), "schema": "sulde-golden-candidate-v2", "stage": "ready"},
            {**case("x"), "schema": "sulde-golden-candidate-v2", "stage": []},
        ):
            self.write_jsonl(self.candidates, [row])
            completed = self.run_review()
            self.assertEqual(completed.returncode, 2, completed.stderr)
        self.write_jsonl(self.candidates, [{**case("legacy"), "schema": "sulde-golden-candidate-v1", "project": ""}])
        completed = self.run_review()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["revision_required"], 1)

    def test_conflicting_terminal_decision_fails_before_any_write(self) -> None:
        decision = {"id": "candidate-1", "action": "accept", "reason": "approved"}
        self.assertEqual(self.run_review([decision], apply=True).returncode, 0)
        self.write_jsonl(self.candidates, [case("candidate-1"), case("candidate-2")])
        before = {path: path.read_bytes() for path in (self.candidates, self.golden, self.home / "golden-review-decisions.jsonl")}
        completed = self.run_review([{"id": "candidate-1", "action": "reject", "reason": "conflict"}], apply=True)
        self.assertEqual(completed.returncode, 2)
        self.assertTrue(all(path.read_bytes() == value for path, value in before.items()))


    def test_invalid_batch_is_all_or_nothing(self) -> None:
        before_candidates = self.candidates.read_bytes()
        before_golden = self.golden.read_bytes()
        completed = self.run_review(
            [
                {"id": "candidate-1", "action": "accept", "reason": "valid"},
                {"id": "missing", "action": "reject", "reason": "invalid id"},
            ],
            apply=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown candidate id missing", completed.stderr)
        self.assertEqual(self.candidates.read_bytes(), before_candidates)
        self.assertEqual(self.golden.read_bytes(), before_golden)

    def test_retry_after_golden_write_is_idempotent(self) -> None:
        decision = {"id": "candidate-1", "action": "accept", "reason": "valid regression"}
        promoted = dict(case("candidate-1"))
        promoted["note"] += "; 人工复核=valid regression"
        self.write_jsonl(self.golden, [case("existing"), promoted])
        completed = self.run_review([decision], apply=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["replayed"], ["candidate-1"])
        self.assertEqual([row["id"] for row in self.read_jsonl(self.golden)].count("candidate-1"), 1)
        self.assertEqual([row["id"] for row in self.read_jsonl(self.candidates)], ["candidate-2"])

    def test_retry_after_audit_write_does_not_duplicate_audit_event(self) -> None:
        decision = {"id": "candidate-1", "action": "accept", "reason": "valid regression"}
        first = self.run_review([decision], apply=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        # Restore the candidate to model interruption after the audit became
        # durable but before the queue replacement completed.
        self.write_jsonl(self.candidates, [case("candidate-1"), case("candidate-2")])
        second = self.run_review([decision], apply=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(self.read_jsonl(self.home / "golden-review-decisions.jsonl")), 1)
        self.assertEqual([row["id"] for row in self.read_jsonl(self.candidates)], ["candidate-2"])


if __name__ == "__main__":
    unittest.main()
