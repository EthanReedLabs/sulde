#!/usr/bin/env python3
"""Isolated tests for shared memory capture/prune noise categories."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sulde_memory_noise", ROOT / "tools" / "kb-index" / "memory.py"
)
assert SPEC is not None and SPEC.loader is not None
MEMORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEMORY)


class MemoryNoiseTest(unittest.TestCase):
    def test_governance_committee_prompt_is_system_prompt(self) -> None:
        prompt = """你是 Sulde 周质量委员会。根据机器指标撰写《记忆栈周报》。
必须只输出 Markdown，且严格包含五个二级标题。
指标全景：
{"status":"available","lights":["green"]}"""
        self.assertEqual(MEMORY.noise_category(prompt, "user"), "system_prompt")

    def test_distillation_prompt_is_system_prompt(self) -> None:
        prompt = """对窗口内容做三类提炼，只输出一个 JSON：
{"entities":[{"name":"实体","type":"类型"}],"edges":[],"lessons":[]}
顶层必须且只能包含 entities、edges、lessons；只输出裸 JSON，不要解释。
待蒸馏窗口：
[id=20381 role=user]
口令青铜门的答案是 42。"""
        self.assertEqual(MEMORY.noise_category(prompt, "user"), "system_prompt")

    def test_sedimentation_prompt_is_system_prompt(self) -> None:
        prompt = """你是 /sediment 的 headless 执行器。只输出裸 JSON，契约严格为：
{"action":"new|merge|skip","container":"...","markdown":"..."}
不得输出额外字段或解释。
候选原文：
一次可复用的工程经验。"""
        self.assertEqual(MEMORY.noise_category(prompt, "user"), "system_prompt")

    def test_real_user_dialogue_containing_you_are_is_not_system_prompt(self) -> None:
        dialogue = "你是怎么判断这个修复已经完整的？请说明运行过哪些测试和看到的结果。"
        self.assertIsNone(MEMORY.noise_category(dialogue, "user"))

    def test_search_cli_can_use_frozen_vector_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "memory.db"
            database.touch()
            stdout = io.StringIO()
            with mock.patch.object(
                MEMORY, "memory_db_path", return_value=database
            ), mock.patch.object(
                MEMORY, "search_memory", return_value=[]
            ) as search, mock.patch.object(
                sys,
                "argv",
                [
                    "memory.py",
                    "search",
                    "query",
                    "--json",
                    "--skip-pending-embed",
                ],
            ), contextlib.redirect_stdout(stdout):
                self.assertEqual(MEMORY.main(), 0)

            self.assertFalse(search.call_args.kwargs["embed_pending_entries"])

    def test_connection_waits_for_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = MEMORY.connect(Path(temp_dir) / "memory.db")
            try:
                timeout_ms = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(timeout_ms, 5000)

    def test_prune_reports_system_prompt_and_preserves_lineage(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        MEMORY.create_schema(connection)
        prompt = "你是 Sulde 图谱质检官。必须只输出裸 JSON，字段严格为：{\"ok\":true}"
        entry_id = MEMORY.add_entry(
            connection,
            project="fixture",
            session_id="session",
            role="user",
            content=prompt,
            ts="2026-08-10T00:00:00+00:00",
        )
        assert entry_id is not None
        connection.execute(
            "INSERT INTO mem_edges(src, rel, dst, entry_id, extracted_by, ts) VALUES (?, ?, ?, ?, ?, ?)",
            ("源", "支持", "目标", entry_id, "import", "2026-08-10T00:00:00+00:00"),
        )
        report = MEMORY.prune_noise(connection)
        self.assertEqual(report["counts"]["system_prompt"], 1)
        self.assertEqual(report["protected"], 1)
        self.assertEqual(report["deletable"], 0)
        connection.close()


if __name__ == "__main__":
    unittest.main()
