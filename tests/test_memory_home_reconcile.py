from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from memory_home_reconcile import (  # noqa: E402
    RETIREMENT_FILE,
    plan,
    reconcile,
)


SCHEMA = """
CREATE TABLE mem_entries(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL, session_id TEXT NOT NULL,
  source_host TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
  content_hash TEXT NOT NULL, ts TEXT NOT NULL, embedded INTEGER NOT NULL,
  UNIQUE(session_id, content_hash)
);
CREATE VIRTUAL TABLE mem_fts USING fts5(seg_text);
CREATE TABLE mem_vectors(id INTEGER PRIMARY KEY, dim INTEGER NOT NULL, vector BLOB NOT NULL);
CREATE TABLE mem_capture_state(transcript_path TEXT PRIMARY KEY, byte_offset INTEGER NOT NULL);
CREATE TABLE mem_edges(
  id INTEGER PRIMARY KEY, src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL,
  entry_id INTEGER, extracted_by TEXT NOT NULL, confidence REAL, ts TEXT NOT NULL,
  UNIQUE(src,rel,dst)
);
CREATE TABLE mem_entities(name TEXT PRIMARY KEY, type TEXT NOT NULL, first_seen TEXT NOT NULL);
"""


def create_db(path: Path, entries: list[tuple[int, str, str, int]]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    for entry_id, session_id, content_hash, embedded in entries:
        connection.execute(
            "INSERT INTO mem_entries VALUES (?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                "project",
                session_id,
                "codex",
                "user",
                f"content-{content_hash}",
                content_hash,
                "2026-08-30T00:00:00Z",
                embedded,
            ),
        )
        if embedded:
            connection.execute(
                "INSERT INTO mem_vectors VALUES (?,?,?)",
                (entry_id, 1, b"vector-" + content_hash.encode()),
            )
            connection.execute(
                "INSERT INTO mem_fts(rowid,seg_text) VALUES (?,?)",
                (entry_id, f"segmented {content_hash}"),
            )
    connection.commit()
    connection.close()


class MemoryHomeReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.legacy = self.root / "legacy" / "memory.db"
        self.neutral = self.root / "neutral" / "memory.db"
        self.legacy.parent.mkdir()
        self.neutral.parent.mkdir()
        create_db(
            self.legacy,
            [(1, "shared-session", "shared", 1), (2, "legacy-session", "legacy", 1)],
        )
        create_db(
            self.neutral,
            [(1, "shared-session", "shared", 1), (2, "neutral-session", "neutral", 0)],
        )
        legacy = sqlite3.connect(self.legacy)
        legacy.execute("INSERT INTO mem_capture_state VALUES ('legacy.jsonl', 42)")
        legacy.execute("INSERT INTO mem_entities VALUES ('Guardian','component','2026')")
        legacy.execute(
            "INSERT INTO mem_edges(src,rel,dst,entry_id,extracted_by,confidence,ts) "
            "VALUES ('Guardian','uses','memory',2,'codex',1.0,'2026')"
        )
        legacy.commit()
        legacy.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_is_read_only_and_reports_identity_delta(self) -> None:
        before = self.neutral.read_bytes()
        result = plan(self.legacy, self.neutral)
        self.assertEqual(result["missing_entries"], 1)
        self.assertTrue(result["reconcile_required"])
        self.assertEqual(self.neutral.read_bytes(), before)

    @unittest.skipIf(os.name == "nt", "POSIX retirement mode contract")
    def test_reconcile_merges_deduplicates_backs_up_and_retires_legacy(self) -> None:
        result = reconcile(
            self.legacy,
            self.neutral,
            archive_root=self.root / "control" / "memory-migrations",
        )

        self.assertTrue(result["ready"])
        self.assertEqual(result["merge"]["inserted_entries"], 1)
        self.assertEqual(result["after"]["entries"], 3)
        self.assertEqual(stat.S_IMODE(self.legacy.stat().st_mode), 0o444)
        retirement = json.loads(
            (self.legacy.parent / RETIREMENT_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(retirement["status"], "read_only_archive")
        transaction_root = Path(result["archive_root"])
        self.assertTrue((transaction_root / "legacy-memory.db").is_file())
        self.assertTrue((transaction_root / "neutral-before.db").is_file())
        self.assertTrue((transaction_root / "receipt.json").is_file())

        neutral = sqlite3.connect(self.neutral)
        neutral.row_factory = sqlite3.Row
        legacy_entry = neutral.execute(
            "SELECT id FROM mem_entries WHERE session_id='legacy-session'"
        ).fetchone()
        self.assertIsNotNone(legacy_entry)
        self.assertIsNotNone(
            neutral.execute(
                "SELECT 1 FROM mem_vectors WHERE id=?", (legacy_entry["id"],)
            ).fetchone()
        )
        self.assertEqual(
            neutral.execute(
                "SELECT entry_id FROM mem_edges WHERE src='Guardian'"
            ).fetchone()[0],
            legacy_entry["id"],
        )
        self.assertEqual(
            neutral.execute(
                "SELECT byte_offset FROM mem_capture_state WHERE transcript_path='legacy.jsonl'"
            ).fetchone()[0],
            42,
        )
        neutral.close()

        settled = plan(self.legacy, self.neutral)
        self.assertEqual(settled["missing_entries"], 0)
        self.assertFalse(settled["reconcile_required"])


if __name__ == "__main__":
    unittest.main()
