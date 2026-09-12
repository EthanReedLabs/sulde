from __future__ import annotations

import hashlib
import json
import os
import runpy
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
GRAPH_AUDIT = ROOT / "scripts" / "kb" / "graph-audit.py"


class GraphAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb-home"
        self.home.mkdir()
        self.database = self.home / "memory.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE mem_entries(
                id INTEGER PRIMARY KEY,
                project TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                ts TEXT NOT NULL,
                embedded INTEGER DEFAULT 0
            );
            CREATE TABLE mem_edges(
                id INTEGER PRIMARY KEY,
                src TEXT NOT NULL,
                rel TEXT NOT NULL,
                dst TEXT NOT NULL,
                entry_id INTEGER REFERENCES mem_entries(id) ON DELETE SET NULL,
                extracted_by TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                ts TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO mem_entries VALUES (?, 'fixture', 's1', 'assistant', ?, ?, '2026-08-08T00:00:00Z', 0)",
            [
                (101, "原文明确说。稳定抽样保证同日样本一致。", "hash-101"),
                (102, "原文只讨论天气，与删除图谱边完全无关。", "hash-102"),
                (103, "原文说结果可能相关，但没有给出确定因果关系。", "hash-103"),
            ],
        )
        connection.executemany(
            "INSERT INTO mem_edges VALUES (?, ?, ?, ?, ?, 'claude', ?, '2026-08-08T00:00:00Z')",
            [
                (1, "稳定抽样", "保证", "同日样本一致", 101, 0.95),
                (2, "天气", "要求", "删除图谱边", 102, 0.80),
                (3, "现象甲", "导致", "现象乙", 103, 0.60),
                (4, "共享知识", "适用于", "所有项目", None, 0.70),
            ],
        )
        connection.commit()
        connection.close()

        self.calls = self.home / "mock-calls.jsonl"
        self.mock_llm = Path(self.temporary.name) / "mock_llm.py"
        self.mock_llm.write_text(
            textwrap.dedent(
                """
                import json
                import os
                import re
                import sys

                prompt = sys.stdin.read()
                match = re.search(r'"id":\\s*(\\d+)', prompt)
                edge_id = int(match.group(1))
                with open(os.environ["GRAPH_AUDIT_CALLS"], "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"edge_id": edge_id, "prompt": prompt}, ensure_ascii=False) + "\\n")
                if edge_id == 1:
                    verdict, reason = "supported", "原文明确陈述稳定抽样的效果。"
                elif edge_id == 3:
                    verdict, reason = "uncertain", "原文只有相关性，不能确定因果。"
                else:
                    verdict, reason = "unsupported", "原文没有要求删除边。"
                print(json.dumps({"edge_id": edge_id, "verdict": verdict, "temporal_modal": verdict, "predicate_object": verdict, "reason": reason}, ensure_ascii=False))
                """
            ).lstrip(),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_audit(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        environment["GRAPH_AUDIT_CALLS"] = str(self.calls)
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [
                sys.executable,
                str(GRAPH_AUDIT),
                *arguments,
                "--llm-cmd",
                f"{sys.executable} {self.mock_llm}",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_classifies_sourced_edges_and_accounts_for_null_lineage(self) -> None:
        completed = self.run_audit("--all")

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("GRAPH AUDIT RESULT: FAIL", completed.stdout)
        self.assertIn("supported=1 unsupported=1 uncertain=1 shared_null=1", completed.stdout)
        self.assertIn("ERROR unsupported edge_ids=2", completed.stdout)
        self.assertIn("WARN uncertain edge_ids=3", completed.stdout)

        reports = list((self.home / "governance").glob("graph-audit-*.md"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text(encoding="utf-8")
        self.assertIn("## Supported", report)
        self.assertIn("| 1 | 稳定抽样 —保证→ 同日样本一致", report)
        self.assertIn("## Unsupported（待人工处置）", report)
        self.assertIn("| 2 | 天气 —要求→ 删除图谱边", report)
        self.assertIn("## Uncertain", report)
        self.assertIn("| 3 | 现象甲 —导致→ 现象乙", report)
        self.assertIn("## NULL 血缘共享边（不判）", report)
        self.assertIn("| 4 | 共享知识 —适用于→ 所有项目", report)

        calls = [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call["edge_id"] for call in calls], [1, 2, 3])
        self.assertIn("原文明确说", calls[0]["prompt"])
        self.assertNotIn('"id": 4', "\n".join(call["prompt"] for call in calls))

        first_digest = hashlib.sha256(reports[0].read_bytes()).hexdigest()
        second = self.run_audit("--all")
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(hashlib.sha256(reports[0].read_bytes()).hexdigest(), first_digest)
        self.assertEqual(len(list((self.home / "governance").glob("graph-audit-*.md"))), 1)

    def test_production_shaped_edges_cannot_pass_even_with_loose_llm(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executemany(
            "INSERT INTO mem_entries VALUES (?, 'fixture', 's1', 'assistant', ?, ?, '2026-08-08T00:00:00Z', 0)",
            [(1306, "SyntheticApplication定位为示例检索系统。当前状态 PLANNED/NOT_READY", "hash-1306"),
             (407, "stale build 导致 iOS walkthrough probe 在没有最新 marker 的旧 app 上运行。", "hash-407")])
        connection.execute(
            "INSERT INTO mem_edges VALUES (407, 'stale build', '导致', 'iOS walkthrough probe', 407, 'codex', 1, '2026-08-08T00:00:00Z')")
        connection.execute(
            "INSERT INTO mem_edges VALUES (1306, 'SyntheticApplication', '定位为', '示例检索系统', 1306, 'codex', 1, '2026-08-08T00:00:00Z')")
        connection.commit()
        connection.close()
        self.mock_llm.write_text(
            'import json, re, sys\n'
            'p=sys.stdin.read(); i=int(re.search(r\'"id":\\s*(\\d+)\', p).group(1))\n'
            'print(json.dumps(dict(edge_id=i,verdict="supported",temporal_modal="supported",predicate_object="supported",reason="loose overlap")))\n')
        before = self.database.read_bytes()
        completed = self.run_audit("--all")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report_path = next((self.home / "governance").glob("graph-audit-*.json"))
        report = json.loads(report_path.read_text())
        judgments = {row["edge"]["id"]: row for row in report["judgments"]}
        self.assertEqual(judgments[1306]["temporal_modal"], "uncertain")
        self.assertEqual(judgments[407]["predicate_object"], "uncertain")
        self.assertEqual(judgments[1]["verdict"], "supported")
        self.assertEqual(self.database.read_bytes(), before)
        candidates = list((self.home / "governance/graph-corrections").glob("*.json"))
        frozen = {path: path.read_bytes() for path in candidates}
        self.assertEqual(self.run_audit("--all").returncode, 0)
        self.assertTrue(all(path.read_bytes() == value for path, value in frozen.items()))
        self.assertTrue(all(not row["applied"] and row["decision"] == "pending_human_review"
                            for row in report["review_candidates"]))

    def test_independent_schema_rejects_legacy_and_contradictory_results(self) -> None:
        audit = runpy.run_path(str(GRAPH_AUDIT))
        payload = {"edge_id": 407, "verdict": "supported", "reason": "overlap"}
        with self.assertRaises(audit["AuditError"]):
            audit["parse_judgment"](json.dumps(payload), 407)
        payload.update(temporal_modal="supported", predicate_object="uncertain")
        with self.assertRaises(audit["AuditError"]):
            audit["parse_judgment"](json.dumps(payload), 407)
        payload["verdict"] = "uncertain"
        self.assertEqual(audit["parse_judgment"](json.dumps(payload), 407)[3], "uncertain")


    def test_harmless_paraphrase_can_pass_independent_audit(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE mem_entries SET content=? WHERE id=101",
                           ("每天固定种子抽样，因此当天重复运行会得到相同的一组边。",))
        connection.commit()
        connection.close()
        completed = self.run_audit("--all")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(next((self.home / "governance").glob("graph-audit-*.json")).read_text())
        row = next(row for row in report["judgments"] if row["edge"]["id"] == 1)
        self.assertEqual(row["verdict"], "supported")
        self.assertEqual((row["temporal_modal"], row["predicate_object"]), ("supported", "supported"))

    def test_dry_run_samples_without_llm_or_any_write(self) -> None:
        before_digest = hashlib.sha256(self.database.read_bytes()).hexdigest()
        completed = self.run_audit("--sample", "1", "--dry-run")

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("GRAPH AUDIT DRY-RUN: PASS", completed.stdout)
        self.assertIn("sampled: eligible=3 selected=1 shared_null=1", completed.stdout)
        self.assertIn("writes: 0  llm_calls: 0", completed.stdout)
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.home / "governance").exists())
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before_digest)


if __name__ == "__main__":
    unittest.main()
