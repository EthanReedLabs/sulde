#!/usr/bin/env python3
"""Isolated tests for recall-log golden candidate expansion."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "golden-expand.py"
NOW = datetime(2026, 8, 8, 12, tzinfo=timezone.utc)

MOCK_LLM = r'''#!/usr/bin/env python3
import json
import sys

prompt = sys.stdin.read()
if "cross_group_blocked" in prompt:
    result = {"action":"draft", "assertion":"forbid_project", "expected":"outside-project", "reason":"高分候选被隔离，应固定组外禁入"}
elif "borderline_injection" in prompt:
    result = {"action":"draft", "assertion":"expect_none", "expected":True, "reason":"贴线注入需负例复核"}
elif "repeated_injection" in prompt:
    result = {"action":"draft", "assertion":"expect_substring", "expected":"稳定事实", "reason":"高频条目需稳定正例"}
elif "suspected_miss" in prompt:
    result = {"action":"draft", "assertion":"expect_substring", "expected":"漏召回事实", "reason":"门线下方疑似漏召回"}
else:
    result = {"action":"skip", "assertion":None, "expected":None, "reason":"无匹配"}
print(json.dumps(result, ensure_ascii=False))
'''


class GoldenExpandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb-home"
        self.home.mkdir()
        self.log = self.home / "recall-log.jsonl"
        self.mock = Path(self.temporary.name) / "mock-llm.py"
        self.mock.write_text(MOCK_LLM, encoding="utf-8")
        recent = NOW - timedelta(hours=1)
        rows = [
            self.row(recent, "/work/alpha", "跨组高分候选不应进入当前项目", [0.81, 0.4], [], "mem"),
            self.row(recent, "/work/alpha", "贴线注入是否其实是噪声", [0.51, 0.2], [101], "mem"),
            self.row(recent, "/work/alpha", "接近门线但没有召回的事实", [0.48, 0.2], [], "mem"),
            self.row(recent, "/work/alpha", "重复事实第一次", [0.9], [101], "mem"),
            self.row(recent, "/work/alpha", "重复事实第二次", [0.88], [101], "mem"),
            self.row(recent, "/work/alpha", "重复事实第三次", [0.87], [101], "mem"),
            self.row(recent, "/work/alpha", "知识库贴线注入不属于 memory golden", [0.56], ["doc-kb"], "kb"),
            self.row(NOW - timedelta(days=8), "/work/old", "过期日志", [0.5], [999], "mem"),
        ]
        self.log.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def row(ts, cwd, query, scores, injected, source):
        row = {
            "ts": ts.isoformat(),
            "cwd": cwd,
            "query_head": query,
            "platform": None,
            "top_scores": scores,
            "injected": injected,
            "source": source,
        }
        if source == "kb":
            row["cli_status"] = "ok"
        else:
            row["session_id"] = "golden-fixture"
            row["channel"] = "claude"
            row["opportunity_id"] = hashlib.sha256(
                f"claude\0golden-fixture\0{cwd}\0{ts.isoformat()}".encode("utf-8")
            ).hexdigest()[:20]
        return row

    def run_expand(self, *extra: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--now",
                NOW.isoformat(),
                "--llm-cmd",
                f"{sys.executable} {self.mock}",
                *extra,
            ],
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def candidates(self) -> list[dict]:
        return [json.loads(line) for line in (self.home / "golden-candidates.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_three_suspicious_shapes_and_suspected_miss_are_drafted(self) -> None:
        completed = self.run_expand()
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("cross_group_blocked=1", completed.stdout)
        self.assertIn("borderline_injection=1", completed.stdout)
        self.assertIn("repeated_injection=1", completed.stdout)
        self.assertIn("suspected_miss=1", completed.stdout)
        candidates = self.candidates()
        self.assertEqual(len(candidates), 4)
        golden_api = runpy.run_path(str(ROOT / "scripts" / "kb" / "mem-golden.py"))
        self.assertEqual(
            len(golden_api["load_cases"](self.home / "golden-candidates.jsonl")),
            4,
        )
        classifications = {row["note"].split(";", 1)[0] for row in candidates}
        self.assertEqual(
            classifications,
            {
                "候选分类=cross_group_blocked",
                "候选分类=borderline_injection",
                "候选分类=repeated_injection",
                "候选分类=suspected_miss",
            },
        )
        for row in candidates:
            self.assertIn("接受前需人工确认完整性", row["note"])
            self.assertEqual(len(set(row) & {"expect_none", "expect_substring", "forbid_project"}), 1)
        report = next(self.home.glob("golden-expand-report-*.md")).read_text(encoding="utf-8")
        self.assertIn("excluded_non_memory_rows: 1", report)

    def test_rerun_is_idempotent_by_evidence_fingerprint(self) -> None:
        first = self.run_expand()
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        before = (self.home / "golden-candidates.jsonl").read_bytes()
        second = self.run_expand()
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertIn("drafted=0 duplicate=4", second.stdout)
        self.assertIn("sources: memory=6 excluded_non_memory=1", second.stdout)
        self.assertEqual((self.home / "golden-candidates.jsonl").read_bytes(), before)

        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.row(
                NOW,
                "/work/alpha",
                "重复事实第四次",
                [0.86],
                [101],
                "mem",
            ), ensure_ascii=False) + "\n")
        third = self.run_expand()
        self.assertEqual(third.returncode, 0, third.stderr + third.stdout)
        self.assertIn("drafted=0 duplicate=4", third.stdout)
        self.assertEqual((self.home / "golden-candidates.jsonl").read_bytes(), before)

    def test_reviewed_candidates_do_not_revive_after_queue_is_consumed(self) -> None:
        first = self.run_expand()
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        reviewed = [
            {"id": row["id"], "action": "reject", "reason": "human reviewed"}
            for row in self.candidates()
        ]
        (self.home / "golden-review-decisions.jsonl").write_text(
            json.dumps({"event_id": "review-1", "decisions": reviewed}) + "\n",
            encoding="utf-8",
        )
        (self.home / "golden-candidates.jsonl").write_text("", encoding="utf-8")
        self.mock.unlink()

        rerun = self.run_expand()
        self.assertEqual(rerun.returncode, 0, rerun.stderr + rerun.stdout)
        self.assertIn("drafted=0 duplicate=4", rerun.stdout)
        self.assertEqual(
            (self.home / "golden-candidates.jsonl").read_text(encoding="utf-8"),
            "",
        )

    def test_dry_run_counts_without_llm_or_output_writes(self) -> None:
        self.mock.unlink()
        completed = self.run_expand("--dry-run")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("GOLDEN EXPAND RESULT: PASS", completed.stdout)
        self.assertIn("cross_group_blocked=1", completed.stdout)
        self.assertIn("borderline_injection=1", completed.stdout)
        self.assertIn("repeated_injection=1", completed.stdout)
        self.assertIn("sources: memory=6 excluded_non_memory=1", completed.stdout)
        self.assertIn("cached_skip=0 skipped=0 errors=0 novel_unique=4", completed.stdout)
        self.assertFalse((self.home / "golden-candidates.jsonl").exists())
        self.assertEqual(list(self.home.glob("golden-expand-report-*.md")), [])

    def test_skip_decisions_are_reused_without_recalling_llm(self) -> None:
        calls = Path(self.temporary.name) / "llm-calls.txt"
        self.mock.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            f"with open({str(calls)!r}, 'a', encoding='utf-8') as handle:\n"
            "    handle.write('called\\n')\n"
            "print(json.dumps({'action':'skip','assertion':None,'expected':None,'reason':'证据不足'}))\n",
            encoding="utf-8",
        )

        first = self.run_expand()
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 4)
        cache = self.home / "golden-expand-skips.jsonl"
        self.assertEqual(len(cache.read_text(encoding="utf-8").splitlines()), 4)

        second = self.run_expand()
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertIn("drafted=0 duplicate=0 cached_skip=4 skipped=0", second.stdout)
        self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 4)

    def test_prior_markdown_report_seeds_skip_cache_for_upgrade(self) -> None:
        self.mock.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps({'action':'skip','assertion':None,'expected':None,'reason':'旧版判定'}))\n",
            encoding="utf-8",
        )
        first = self.run_expand()
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        (self.home / "golden-expand-skips.jsonl").unlink()
        self.mock.unlink()

        dry_run = self.run_expand("--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
        self.assertIn(
            "duplicate=0 cached_skip=4 skipped=0 errors=0 novel_unique=0",
            dry_run.stdout,
        )


if __name__ == "__main__":
    unittest.main()
