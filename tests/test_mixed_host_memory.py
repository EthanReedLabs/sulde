from __future__ import annotations

import hashlib
import importlib.util
import json
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
import memory  # noqa: E402


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MIGRATION = load_script(
    "test_migrate_session_identity",
    ROOT / "scripts" / "kb" / "migrate-session-identity.py",
)
HARVEST = load_script(
    "test_codex_harvest_mixed_host",
    ROOT / "scripts" / "kb" / "codex-harvest.py",
)
MEM_CAPTURE = load_script(
    "test_mem_capture_mixed_host",
    ROOT / "hooks" / "lib" / "mem_capture.py",
)
MEM_SYNC = load_script(
    "test_mem_sync_mixed_host",
    ROOT / "scripts" / "kb" / "mem-sync.py",
)
CODEX_ADAPTER_DIR = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts"
sys.path.insert(0, str(CODEX_ADAPTER_DIR))
CODEX_ADAPTER = load_script(
    "test_codex_user_prompt_adapter",
    CODEX_ADAPTER_DIR / "user-prompt-submit.py",
)


class MixedHostMemoryTests(unittest.TestCase):
    def test_existing_database_schema_gains_provenance_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "memory.db"
            raw = sqlite3.connect(database)
            raw.execute(
                """CREATE TABLE mem_entries(
                       id INTEGER PRIMARY KEY, project TEXT NOT NULL,
                       session_id TEXT NOT NULL, role TEXT NOT NULL,
                       content TEXT NOT NULL, content_hash TEXT NOT NULL,
                       ts TEXT NOT NULL, embedded INTEGER DEFAULT 0,
                       UNIQUE(session_id,content_hash))"""
            )
            raw.commit()
            raw.close()

            upgraded = memory.connect(database)
            try:
                columns = {
                    str(row[1])
                    for row in upgraded.execute("PRAGMA table_info(mem_entries)")
                }
            finally:
                upgraded.close()
            self.assertIn("source_host", columns)

    def test_codex_adapter_overrides_untrusted_client_label(self) -> None:
        payload = {
            "client": "claude",
            "sessionId": "abc",
            "prompt": "混合宿主来源归属",
        }
        with mock.patch.object(
            sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False))
        ):
            adapted = CODEX_ADAPTER._payload()
        self.assertEqual(adapted["client"], "codex")
        self.assertEqual(adapted["session_id"], "abc")

    def test_identity_accepts_legacy_spelling_and_host_hint(self) -> None:
        self.assertEqual(
            memory.normalize_session_identity("codex_abc", "unknown"),
            ("codex:abc", "codex"),
        )
        self.assertEqual(
            memory.normalize_session_identity("abc", "claude"),
            ("claude:abc", "claude"),
        )
        self.assertEqual(
            memory.normalize_session_identity("codex:abc", "claude"),
            ("codex:abc", "codex"),
        )

    def test_codex_hook_and_harvest_share_one_business_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            database = home / "memory.db"
            memory.initialize(database)
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
                inserted = MEM_CAPTURE.run(
                    {
                        "client": "codex",
                        "session_id": "abc",
                        "cwd": str(home / "project"),
                        "prompt": "同一个 Codex prompt 只能写入一次",
                    }
                )
                connection = memory.connect(database)
                try:
                    duplicate = memory.add_entry(
                        connection,
                        project="project",
                        session_id="codex_abc",
                        source_host="codex",
                        role="user",
                        content="同一个 Codex prompt 只能写入一次",
                        ts="2026-08-12T00:00:00+00:00",
                    )
                    connection.commit()
                    row = connection.execute(
                        "SELECT session_id,source_host FROM mem_entries"
                    ).fetchone()
                finally:
                    connection.close()
            self.assertEqual(inserted, 1)
            self.assertIsNone(duplicate)
            self.assertEqual(tuple(row), ("codex:abc", "codex"))

    def test_harvest_emits_canonical_codex_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "rollout-fixture.jsonl"
            records = [
                {
                    "type": "session_meta",
                    "payload": {"id": "abc", "cwd": "/work/demo"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-08-12T00:00:00+00:00",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "混合宿主的会话标识出现了重复记录，需要统一数据契约",
                            }
                        ],
                    },
                },
            ]
            source.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            entries, processed, errors = HARVEST.parse_file(source, 0)
            self.assertEqual(processed, 2)
            self.assertEqual(errors, 0)
            self.assertEqual(entries[0]["session_id"], "codex:abc")
            self.assertEqual(entries[0]["source_host"], "codex")

    def test_migration_merges_duplicates_without_losing_lineage_or_search(self) -> None:
        native_id = "11111111-2222-3333-4444-555555555555"
        content = "需要保留向量、FTS 与关系边"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "memory.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            memory.create_schema(connection)
            connection.execute(
                """INSERT INTO mem_entries(
                       id,project,session_id,source_host,role,content,content_hash,ts,embedded
                   ) VALUES (1,'demo',?,'unknown','user',?,?,?,0)""",
                (native_id, content, digest, "2026-08-12T00:00:00+00:00"),
            )
            connection.execute(
                """INSERT INTO mem_entries(
                       id,project,session_id,source_host,role,content,content_hash,ts,embedded
                   ) VALUES (2,'demo',?,'codex','user',?,?,?,1)""",
                (f"codex_{native_id}", content, digest, "2026-08-12T00:01:00+00:00"),
            )
            connection.execute(
                "INSERT INTO mem_fts(rowid,seg_text) VALUES (2,'保留 搜索')"
            )
            connection.execute(
                "INSERT INTO mem_vectors(id,dim,vector) VALUES (2,1,?)", (b"1234",)
            )
            connection.execute(
                """INSERT INTO mem_edges(
                       src,rel,dst,entry_id,extracted_by,ts
                   ) VALUES ('源','支持','目标',2,'codex','2026-08-12T00:02:00+00:00')"""
            )
            connection.commit()

            groups, identities = MIGRATION.plan_groups(
                connection,
                known_claude=set(),
                known_codex={native_id},
            )
            report = MIGRATION.apply_groups(connection, groups, identities)

            row = connection.execute(
                "SELECT id,session_id,source_host,embedded FROM mem_entries"
            ).fetchone()
            edge_entry = connection.execute(
                "SELECT entry_id FROM mem_edges"
            ).fetchone()[0]
            vector_entry = connection.execute(
                "SELECT id FROM mem_vectors"
            ).fetchone()[0]
            fts_entry = connection.execute(
                "SELECT rowid FROM mem_fts"
            ).fetchone()[0]
            connection.close()

            self.assertEqual(report["duplicates_removed"], 1)
            self.assertEqual(
                tuple(row), (1, f"codex:{native_id}", "codex", 1)
            )
            self.assertEqual(edge_entry, 1)
            self.assertEqual(vector_entry, 1)
            self.assertEqual(fts_entry, 1)

    def test_recall_migration_attributes_host_without_rekeying_opportunity(self) -> None:
        native_id = "11111111-2222-3333-4444-555555555555"
        timestamp = "2026-08-12T00:00:00+00:00"
        opportunity = hashlib.sha256(
            f"claude\0{native_id}\0/work/demo\0{timestamp}".encode("utf-8")
        ).hexdigest()[:20]
        row = {
            "ts": timestamp,
            "cwd": "/work/demo",
            "query_head": "fixture",
            "platform": None,
            "top_scores": [],
            "injected": [],
            "source": "mem",
            "session_id": native_id,
            "channel": "claude",
            "opportunity_id": opportunity,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "recall-log.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            changed, backup = MIGRATION.migrate_recall_log(
                path,
                known_claude=set(),
                known_codex={native_id},
                apply=True,
            )
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(changed, 1)
            self.assertIsNotNone(backup)
            self.assertEqual(migrated["source_host"], "codex")
            self.assertEqual(migrated["session_id"], native_id)
            self.assertEqual(migrated["channel"], "claude")
            self.assertEqual(migrated["opportunity_id"], opportunity)

    def test_migration_cli_backs_up_and_applies_atomically(self) -> None:
        content = "CLI 迁移必须先备份再合并"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "memory.db"
            recall = root / "recall-log.jsonl"
            recall.write_text("", encoding="utf-8")
            connection = sqlite3.connect(database)
            memory.create_schema(connection)
            for identifier in ("codex_abc", "codex:abc"):
                connection.execute(
                    """INSERT INTO mem_entries(
                           project,session_id,source_host,role,content,content_hash,ts,embedded
                       ) VALUES ('demo',?,'codex','user',?,?,?,0)""",
                    (identifier, content, digest, "2026-08-12T00:00:00+00:00"),
                )
            connection.commit()
            connection.close()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "kb" / "migrate-session-identity.py"),
                    "--database",
                    str(database),
                    "--recall-log",
                    str(recall),
                    "--codex-sessions-root",
                    str(root / "no-codex"),
                    "--claude-projects-root",
                    str(root / "no-claude"),
                    "--apply",
                ],
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["duplicates_removed"], 1)
            self.assertTrue(Path(report["database_backup"]).is_file())
            connection = sqlite3.connect(database)
            row = connection.execute(
                "SELECT session_id,source_host,COUNT(*) FROM mem_entries"
            ).fetchone()
            connection.close()
            self.assertEqual(row, ("codex:abc", "codex", 1))

    def test_mem_sync_legacy_codex_edge_follows_canonical_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "memory.db"
            memory.initialize(database)
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "remote.jsonl").write_text(
                json.dumps(
                    {
                        "session_id": "codex_abc",
                        "source_host": "codex",
                        "role": "user",
                        "content": "跨设备混合宿主关系边",
                        "content_hash": "hash-1",
                        "ts": "2026-08-12T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (incoming / "remote.edges.jsonl").write_text(
                json.dumps(
                    {
                        "src": "源",
                        "rel": "支持",
                        "dst": "目标",
                        "extracted_by": "codex",
                        "confidence": 1.0,
                        "ts": "2026-08-12T00:01:00+00:00",
                        "session_id": "codex_abc",
                        "source_host": "codex",
                        "content_hash": "hash-1",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            connection = memory.connect(database)
            try:
                with mock.patch.object(memory, "segmented", return_value="跨设备 混合宿主"):
                    report = MEM_SYNC.import_project(
                        connection,
                        memory,
                        incoming,
                        "demo",
                        "local-device",
                        None,
                    )
                entry = connection.execute(
                    "SELECT id,session_id,source_host FROM mem_entries"
                ).fetchone()
                edge_entry = connection.execute(
                    "SELECT entry_id FROM mem_edges"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(report["entries"], 1)
            self.assertEqual(report["edges"], 1)
            self.assertEqual(tuple(entry)[1:], ("codex:abc", "codex"))
            self.assertEqual(edge_entry, entry[0])


if __name__ == "__main__":
    unittest.main()
