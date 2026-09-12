from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kb/governance-review.py"


class GovernanceReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        (self.home / "self-repair").mkdir()
        (self.home / "self-repair/pending.json").write_text("[]", encoding="utf-8")
        (self.home / "golden-candidates.jsonl").write_text("", encoding="utf-8")
        (self.home / "distill-candidates.md").write_text("", encoding="utf-8")
        (self.home / "governance").mkdir()
        (self.home / "governance/report-20260811.md").write_text(
            "## 红队质疑\n\n"
            "**待审提案 P-30（不实施）**：新增覆盖率门禁。\n\n---\n\n"
            "**待审提案 P-31**：修复缺源显示。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_review(self, decisions: list[dict] | None = None, apply: bool = False):
        command = [sys.executable, str(SCRIPT), "--json"]
        if decisions is not None:
            path = self.home / "decisions.json"
            path.write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")
            command.extend(["--decisions", str(path)])
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

    def queue(self) -> dict:
        completed = self.run_review()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def decisions(self) -> list[dict]:
        return [
            {"id": row["id"], "action": action, "reason": reason, "digest": row["digest"]}
            for row, action, reason in zip(
                self.queue()["items"],
                ("accept", "reject"),
                ("approved for later implementation", "not proportionate"),
            )
        ]

    def test_listing_exposes_fingerprints_without_writes(self) -> None:
        result = self.queue()
        self.assertEqual(result["pending"], 2)
        self.assertEqual([row["id"] for row in result["items"]], ["P-30", "P-31"])
        self.assertTrue(all(len(row["digest"]) == 64 for row in result["items"]))
        self.assertFalse((self.home / "l2/registry.json").exists())

    def test_preview_validates_batch_without_writes(self) -> None:
        completed = self.run_review(self.decisions())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(result["writes"], 0)
        self.assertFalse((self.home / "l2/registry.json").exists())

    def test_apply_atomically_records_human_decisions_and_refresh_preserves_them(self) -> None:
        completed = self.run_review(self.decisions(), apply=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["accepted"], ["P-30"])
        self.assertEqual(result["rejected"], ["P-31"])
        self.assertEqual(result["pending"], 0)
        registry = json.loads((self.home / "l2/registry.json").read_text(encoding="utf-8"))
        items = registry["channels"]["threshold_proposal"]["items"]
        self.assertEqual([row["status"] for row in items], ["accepted", "rejected"])
        self.assertEqual({row["actor"] for row in items}, {"human"})
        refreshed = self.queue()
        self.assertEqual(refreshed["pending"], 0)

    def test_stale_digest_rejects_entire_batch(self) -> None:
        decisions = self.decisions()
        decisions[1]["digest"] = "0" * 64
        completed = self.run_review(decisions, apply=True)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("stale proposal digest for P-31", completed.stderr)
        self.assertFalse((self.home / "l2/registry.json").exists())

    def test_unknown_id_rejects_entire_batch(self) -> None:
        decisions = self.decisions()
        decisions[1]["id"] = "P-404"
        completed = self.run_review(decisions, apply=True)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown proposal id P-404", completed.stderr)
        self.assertFalse((self.home / "l2/registry.json").exists())

    def test_apply_requires_decisions(self) -> None:
        completed = self.run_review(apply=True)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--apply requires --decisions", completed.stderr)


if __name__ == "__main__":
    unittest.main()
