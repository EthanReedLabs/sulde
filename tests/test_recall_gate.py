from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import mem_recall  # noqa: E402
import kb_recall  # noqa: E402


class RecallGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.group = mock.patch.object(
            mem_recall, "_project_group", return_value=frozenset({"demo"})
        )
        self.group.start()
        self.addCleanup(self.group.stop)

    @staticmethod
    def item(entry_id: int, score: float, rerank_score: float | None = None):
        result = {
            "id": entry_id,
            "project": "demo",
            "content": f"durable memory content for entry {entry_id}",
            "score": score,
        }
        if rerank_score is not None:
            result["rerank_score"] = rerank_score
        return result

    def test_rerank_logit_controls_gate_and_final_top_k(self) -> None:
        results = [
            self.item(1, score=0.10, rerank_score=3.2),
            self.item(2, score=0.20, rerank_score=1.4),
            self.item(3, score=0.99, rerank_score=-0.1),
        ]

        selected = mem_recall.select_recall_items("specific useful query", "demo", results)

        self.assertEqual([item["id"] for item in selected], [1, 2])

    def test_without_rerank_score_preserves_hybrid_score_gate(self) -> None:
        results = [
            self.item(1, score=0.49),
            self.item(2, score=0.50),
            self.item(3, score=0.90),
        ]

        selected = mem_recall.select_recall_items("specific useful query", "demo", results)

        self.assertEqual([item["id"] for item in selected], [2, 3])

    def test_group_isolation_precedes_rerank_gate(self) -> None:
        outside = self.item(1, score=1.0, rerank_score=9.0)
        outside["project"] = "outside"

        selected = mem_recall.select_recall_items(
            "specific useful query", "demo", [outside]
        )

        self.assertEqual(selected, [])

    def test_system_prompt_is_not_a_recall_intent(self) -> None:
        prompt = "你是 /sediment 的 headless 合并成文器。只输出裸 JSON，契约严格为："

        selected = mem_recall.select_recall_items(
            prompt, "demo", [self.item(1, score=1.0, rerank_score=9.0)]
        )

        self.assertEqual(selected, [])

    def test_delegated_file_analyzer_task_is_not_a_recall_intent(self) -> None:
        prompt = (
            "严格按照 file-analyzer 定义分析这个批次，不要创建子代理。\n\n"
            "Project root: /tmp/demo\nProject: demo\nProcess only: batch-01"
        )

        selected = mem_recall.select_recall_items(
            prompt, "demo", [self.item(1, score=1.0, rerank_score=9.0)]
        )

        self.assertEqual(selected, [])

    def test_synthetic_latency_probe_is_not_a_recall_intent(self) -> None:
        selected = mem_recall.select_recall_items(
            "随便一个查询测延迟基线",
            "demo",
            [self.item(1, score=1.0, rerank_score=9.0)],
        )

        self.assertEqual(selected, [])

    def test_real_latency_question_is_not_overfiltered(self) -> None:
        selected = mem_recall.select_recall_items(
            "如何选择查询样本来测试召回延迟基线？",
            "demo",
            [self.item(1, score=1.0, rerank_score=9.0)],
        )

        self.assertEqual([item["id"] for item in selected], [1])


class KnowledgeRecallNoiseGateTest(unittest.TestCase):
    @staticmethod
    def kb_item(
        doc_id: str,
        score: float,
        *,
        applicability: str = "apply",
        evidence_status: str = "verified",
        role: str = "route_positive",
    ) -> dict:
        return {
            "doc_id": doc_id,
            "title": doc_id,
            "source_path": f"knowledge/work-model/{doc_id}.md",
            "platform": "none",
            "score": score,
            "applicability": applicability,
            "evidence_status": evidence_status,
            "role": role,
        }

    def test_system_prompt_skips_kb_search(self) -> None:
        prompt = "你是 /sediment 的 headless 合并成文器。只输出裸 JSON，契约严格为："
        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log") as log, mock.patch.object(
            kb_recall.kb_cli, "run_cli"
        ) as run_cli:
            kb_recall.run({"prompt": prompt, "cwd": "/tmp/demo"})

        run_cli.assert_not_called()
        self.assertEqual(log.call_args.args[6], "skipped")

    def test_delegated_file_analyzer_task_skips_kb_search(self) -> None:
        prompt = (
            "严格按照 file-analyzer 定义分析这个批次，不要创建子代理。\n\n"
            "Project root: /tmp/demo\nProject: demo\nProcess only: batch-01"
        )
        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log") as log, mock.patch.object(
            kb_recall.kb_cli, "run_cli"
        ) as run_cli:
            kb_recall.run({"prompt": prompt, "cwd": "/tmp/demo"})

        run_cli.assert_not_called()
        self.assertEqual(log.call_args.args[6], "skipped")

    def test_long_prompt_search_keeps_bounded_head_and_tail(self) -> None:
        head = "diagnose a real KB timeout under concurrent load: "
        tail = "tail symptom: runner stalls while embedding the query"
        prompt = head + ("x" * 30_000) + tail
        result = kb_recall.kb_cli.CliResult("ok", stdout="[]")

        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log") as log, mock.patch.object(
            kb_recall.kb_cli, "run_cli", return_value=result
        ) as run_cli:
            kb_recall.run({"prompt": prompt, "cwd": "/tmp/demo"})

        query = run_cli.call_args.args[3][0]
        self.assertEqual(
            run_cli.call_args.args[3][-2:], ["--purpose", "route"]
        )
        self.assertEqual(
            len(query), kb_recall.prompt_noise.MAX_RECALL_QUERY_CHARS
        )
        self.assertTrue(query.startswith(head))
        self.assertTrue(query.endswith(tail))
        self.assertEqual(log.call_args.args[2], prompt)

    def test_bounded_query_size_is_disclosed_when_cli_fails(self) -> None:
        prompt = "diagnose a real timeout: " + ("x" * 30_000)
        result = kb_recall.kb_cli.CliResult(
            "timeout", detail="timeout after 5s"
        )

        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log") as log, mock.patch.object(
            kb_recall.kb_cli, "run_cli", return_value=result
        ):
            kb_recall.run({"prompt": prompt, "cwd": "/tmp/demo"})

        detail = log.call_args.args[7]
        self.assertIn(f"prompt_chars={len(prompt)}", detail)
        self.assertIn(
            f"search_chars={kb_recall.prompt_noise.MAX_RECALL_QUERY_CHARS}", detail
        )

    def test_synthetic_latency_probe_skips_kb_search(self) -> None:
        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log"), mock.patch.object(
            kb_recall.kb_cli, "run_cli"
        ) as run_cli:
            kb_recall.run(
                {"prompt": "随便一个查询测延迟基线", "cwd": "/tmp/demo"}
            )

        run_cli.assert_not_called()

    def test_top_route_negative_suppresses_weaker_positive_injection(self) -> None:
        results = [
            self.kb_item(
                "boundary",
                0.95,
                applicability="skip",
                role="route_negative",
            ),
            self.kb_item("generic", 0.80),
        ]
        cli = kb_recall.kb_cli.CliResult(
            "ok", stdout=json.dumps(results, ensure_ascii=False)
        )
        stdout = io.StringIO()
        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log") as log, mock.patch.object(
            kb_recall.kb_cli, "run_cli", return_value=cli
        ), contextlib.redirect_stdout(stdout):
            kb_recall.run(
                {"prompt": "这是一个明确落入排除边界的真实工程问题", "cwd": "/tmp/demo"}
            )

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(log.call_args.args[5], [])

    def test_inconclusive_knowledge_is_not_automatically_injected(self) -> None:
        results = [
            self.kb_item(
                "uncertain",
                0.95,
                applicability="inconclusive",
                evidence_status="inconclusive",
                role="root_cause",
            )
        ]
        cli = kb_recall.kb_cli.CliResult(
            "ok", stdout=json.dumps(results, ensure_ascii=False)
        )
        stdout = io.StringIO()
        with mock.patch.object(
            kb_recall, "_detect_platform", return_value=("/tmp/demo", None)
        ), mock.patch.object(kb_recall, "_log") as log, mock.patch.object(
            kb_recall.kb_cli, "run_cli", return_value=cli
        ), contextlib.redirect_stdout(stdout):
            kb_recall.run(
                {"prompt": "证据不足但可能相关的真实工程问题", "cwd": "/tmp/demo"}
            )

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(log.call_args.args[5], [])


if __name__ == "__main__":
    unittest.main()
