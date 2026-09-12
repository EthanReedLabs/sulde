#!/usr/bin/env python3
"""Isolated deterministic tests for mem injection adoption signals."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mem_capture", ROOT / "hooks" / "lib" / "mem_capture.py"
)
assert SPEC is not None and SPEC.loader is not None
MEM_CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEM_CAPTURE)


class MemAdoptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.connection = sqlite3.connect(self.home / "memory.db")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE mem_entries(
                id INTEGER PRIMARY KEY,
                project TEXT NOT NULL,
                content TEXT NOT NULL,
                ts TEXT NOT NULL
            )
            """
        )
        self.entry_ts = "2026-08-09T01:00:00+00:00"
        self.connection.execute(
            "INSERT INTO mem_entries VALUES (?, ?, ?, ?)",
            (1, "fixture-project", "发布前必须运行隔离测试并核对完整输出摘要", self.entry_ts),
        )
        self.connection.commit()
        self.recall_ts = datetime(2026, 8, 9, 1, 5, tzinfo=timezone.utc)
        self.cwd = "/tmp/fixture-project"

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary.cleanup()

    def write_recall(self, *, injected: list[int] | None = None) -> None:
        session_id = "session-fixture"
        channel = "claude"
        opportunity_id = hashlib.sha256(
            f"{channel}\0{session_id}\0{self.cwd}\0{self.recall_ts.isoformat()}".encode("utf-8")
        ).hexdigest()[:20]
        record = {
            "ts": self.recall_ts.isoformat(),
            "cwd": self.cwd,
            "query_head": "fixture",
            "platform": None,
            "top_scores": [0.9],
            "injected": [1] if injected is None else injected,
            "source": "mem",
            "session_id": session_id,
            "opportunity_id": opportunity_id,
            "channel": channel,
        }
        (self.home / "recall-log.jsonl").write_text(
            json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def detect(self, text: str, *, elapsed: timedelta = timedelta(minutes=1)):
        return MEM_CAPTURE.detect_adoptions(
            self.connection,
            home=self.home,
            assistant_text=text,
            assistant_ts=(self.recall_ts + elapsed).isoformat(),
            session_id="session-fixture",
            cwd=self.cwd,
        )

    def test_contiguous_fragment_is_adopted(self) -> None:
        self.write_recall()
        events = self.detect("结论：发布前必须运行隔离测试并核对，然后再发布。")
        self.assertEqual(events[0]["verdict"], "adopted")
        self.assertEqual(events[0]["matched_by"], "exact_span")
        written = json.loads((self.home / "mem-adoption-log.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(written["entry_id"], 1)
        self.assertEqual(written["session_id"], "session-fixture")
        self.assertRegex(written["opportunity_id"], r"^[0-9a-f]{20}$")
        health = json.loads((self.home / "mem-adoption-health.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(health["status"], "classified")

    def test_unreferenced_entry_is_ignored(self) -> None:
        self.write_recall()
        events = self.detect("已完成检查，没有引用历史条目的内容。")
        self.assertEqual(events[0]["verdict"], "ignored")
        self.assertIsNone(events[0]["matched_by"])

    def test_answer_token_is_adopted(self) -> None:
        self.connection.execute(
            "INSERT INTO mem_entries VALUES (?, ?, ?, ?)",
            (2, "fixture-project", "青铜门压缩验证的答案是 42。", self.entry_ts),
        )
        self.connection.commit()
        self.write_recall(injected=[2])
        events = self.detect("答案是 **42**，压缩后的记忆仍然有效。")
        self.assertEqual(events[0]["verdict"], "adopted")
        self.assertEqual(events[0]["matched_by"], "answer_token")

    def test_entity_overlap_is_adopted(self) -> None:
        self.connection.execute(
            "INSERT INTO mem_entries VALUES (?, ?, ?, ?)",
            (2, "fixture-project", "支付网关校验请求，订单服务创建记录，库存中心扣减余量。", self.entry_ts),
        )
        self.connection.commit()
        self.write_recall(injected=[2])
        events = self.detect("由支付网关完成鉴权；订单服务随后落库；库存中心负责扣减。")
        self.assertEqual(events[0]["verdict"], "adopted")
        self.assertEqual(events[0]["matched_by"], "entity_overlap")

    def test_generic_words_do_not_trigger_entity_overlap(self) -> None:
        self.connection.execute(
            "INSERT INTO mem_entries VALUES (?, ?, ?, ?)",
            (2, "fixture-project", "这个问题需要系统后续进行处理。", self.entry_ts),
        )
        self.connection.commit()
        self.write_recall(injected=[2])
        events = self.detect("目前系统需要处理该问题，但没有采用具体历史事实。")
        self.assertEqual(events[0]["verdict"], "ignored")
        self.assertIsNone(events[0]["matched_by"])

    def test_injection_outside_time_window_is_not_classified(self) -> None:
        self.write_recall()
        events = self.detect("发布前必须运行隔离测试并核对完整输出摘要", elapsed=timedelta(minutes=11))
        self.assertEqual(events, [])
        self.assertFalse((self.home / "mem-adoption-log.jsonl").exists())

    def test_empty_injection_returns_before_database_query(self) -> None:
        self.write_recall(injected=[])
        started = time.perf_counter()
        events = self.detect("任意回复")
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(events, [])
        self.assertLess(elapsed_ms, 30)
        health = json.loads((self.home / "mem-adoption-health.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(health["skip_reason"], "empty_or_invalid_injected")

    def test_detection_stays_within_capture_budget(self) -> None:
        self.write_recall()
        started = time.perf_counter()
        events = self.detect("发布前必须运行隔离测试并核对完整输出摘要")
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(events[0]["verdict"], "adopted")
        self.assertLess(elapsed_ms, 30)

    def test_noise_prompt_still_scans_prior_assistant_for_adoption(self) -> None:
        transcript = self.home / "session.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")
        connection = mock.Mock()
        add_entry = mock.Mock()
        memory = SimpleNamespace(
            memory_db_path=lambda: self.home / "memory.db",
            is_noise_content=lambda text, role: role == "user",
            connect=lambda _path: connection,
            add_entry=add_entry,
        )
        payload = {
            "prompt": "继续", "session_id": "session-fixture", "cwd": self.cwd,
            "transcript_path": str(transcript),
        }
        with (
            mock.patch.object(MEM_CAPTURE, "_memory_module", return_value=memory),
            mock.patch.object(MEM_CAPTURE, "_scan_transcript", return_value=1) as scan,
        ):
            self.assertEqual(MEM_CAPTURE.run(payload), 1)
        add_entry.assert_not_called()
        scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
