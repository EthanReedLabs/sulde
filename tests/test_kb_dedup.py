from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "kb-dedup.py"


def vector_blob(values: tuple[float, ...]) -> bytes:
    return array("f", values).tobytes()


class KbDedupTest(unittest.TestCase):
    def make_home(self, root: Path) -> Path:
        home = root / "kb-home"
        home.mkdir()
        connection = sqlite3.connect(home / "kb.db")
        connection.executescript(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, title TEXT NOT NULL,
                section TEXT NOT NULL, container TEXT NOT NULL, platform TEXT NOT NULL,
                source_path TEXT NOT NULL, text TEXT NOT NULL
            );
            CREATE TABLE vectors (chunk_id TEXT PRIMARY KEY, dim INTEGER NOT NULL, emb BLOB NOT NULL);
            CREATE TABLE edges (
                src_doc_id TEXT NOT NULL, dst_doc_id TEXT NOT NULL, rel TEXT NOT NULL,
                PRIMARY KEY (src_doc_id, dst_doc_id, rel)
            );
            """
        )
        fixtures = (
            ("dup-a", "重复 A", (1.0, 0.0, 0.0), "同一缓存失效根因与修复"),
            ("dup-b", "重复 B", (0.99, 0.05, 0.0), "同一缓存失效根因的重复写法"),
            ("series-a", "系列 A", (0.0, 1.0, 0.0), "流式响应生命周期问题"),
            ("series-b", "系列 B", (0.0, 0.99, 0.05), "流式响应分帧的不同根因"),
            ("other", "无关", (0.0, 0.0, 1.0), "完全无关的模型校验主题"),
        )
        for doc_id, title, vector, text in fixtures:
            for index in range(2):
                chunk_id = f"{doc_id}#{index:04d}"
                connection.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, '', 'tech-docs', 'none', ?, ?)",
                    (chunk_id, doc_id, title, f"knowledge/{doc_id}.md", f"{text} chunk {index}"),
                )
                connection.execute(
                    "INSERT INTO vectors VALUES (?, ?, ?)",
                    (chunk_id, len(vector), vector_blob(vector)),
                )
        connection.execute("INSERT INTO edges VALUES ('series-a', 'series-b', 'related')")
        connection.commit()
        connection.close()
        return home

    def make_mock(self, root: Path) -> Path:
        mock = root / "mock_llm.py"
        mock.write_text(
            """import json, sys
prompt = sys.stdin.read()
assert 'dup-a' in prompt and 'dup-b' in prompt
assert 'series-a' not in prompt
print(json.dumps({'verdict': 'duplicate', 'retain_doc_id': 'dup-a', 'reason': '同一根因与修复'}))
""",
            encoding="utf-8",
        )
        return mock

    def run_script(self, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["SULDE_KB_HOME"] = str(home)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def snapshot(self, home: Path) -> dict[str, str]:
        return {
            path.relative_to(home).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in home.rglob("*")
            if path.is_file()
        }

    def test_classifies_duplicate_series_and_unrelated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = self.make_home(root)
            mock = self.make_mock(root)
            before = (home / "kb.db").read_bytes()
            completed = self.run_script(home, "--threshold", "0.95", "--llm-cmd", f"{sys.executable} {mock}")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("clusters=2", completed.stdout)
            report = next((home / "governance").glob("dedup-*.md")).read_text(encoding="utf-8")
            self.assertIn("疑似重复；建议合并（待人工确认）", report)
            self.assertIn("建议保留：`dup-a`", report)
            self.assertIn("系列确认（已有 `related` 互链，不提合并）", report)
            self.assertIn("建议保留：全部保留", report)
            self.assertNotIn("`other`", report)
            self.assertEqual((home / "kb.db").read_bytes(), before)
            artifact = json.loads(next((home / "governance").glob("dedup-*.json")).read_text())
            self.assertEqual(artifact["knowledge_mutations"], 0)
            self.assertTrue(all(row["human_confirmation_required"] and not row["applied"]
                                for row in artifact["candidates"]))


    def test_fifteen_semantic_clusters_only_emit_human_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = self.make_home(root)
            with sqlite3.connect(home / "kb.db") as db:
                db.execute("DELETE FROM chunks")
                db.execute("DELETE FROM vectors")
                db.execute("DELETE FROM edges")
                for cluster in range(15):
                    vector = tuple(1.0 if index == cluster else 0.0 for index in range(15))
                    for suffix in ("a", "b"):
                        identifier = f"cluster-{cluster + 1:02d}-{suffix}"
                        db.execute("INSERT INTO chunks VALUES(?, ?, ?, '', 'tech-docs', 'none', ?, ?)",
                                   (identifier, identifier, identifier, f"knowledge/{identifier}.md", "root cause fixture"))
                        db.execute("INSERT INTO vectors VALUES(?,15,?)", (identifier, vector_blob(vector)))
            mock_llm = root / "fifteen_llm.py"
            mock_llm.write_text(
                'import json,sys\n'
                'p=json.loads(sys.stdin.read().split("候选簇：",1)[1])\n'
                'print(json.dumps(dict(verdict="duplicate",retain_doc_id=p["documents"][0]["doc_id"],reason="fixture overlap")))\n')
            before = (home / "kb.db").read_bytes()
            result = self.run_script(home, "--threshold", "0.95", "--llm-cmd", f"{sys.executable} -B {mock_llm}")
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(next((home / "governance").glob("dedup-*.json")).read_text())
            self.assertEqual(len(evidence["candidates"]), 15)
            for number in (1, 8, 10, 11, 15):
                row = evidence["candidates"][number - 1]
                self.assertEqual(row["cluster"], number)
                self.assertTrue(row["human_confirmation_required"])
                self.assertFalse(row["applied"])
            self.assertEqual((home / "kb.db").read_bytes(), before)


    def test_dry_run_is_zero_write_and_threshold_changes_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = self.make_home(Path(temp_dir))
            before = self.snapshot(home)
            high = self.run_script(home, "--dry-run", "--threshold", "0.95", "--llm-cmd", "does-not-exist")
            after = self.snapshot(home)
            low = self.run_script(home, "--dry-run", "--threshold", "0.0", "--llm-cmd", "does-not-exist")
            self.assertEqual(high.returncode, 0, high.stderr)
            self.assertEqual(before, after)
            self.assertFalse((home / "governance").exists())
            self.assertIn("clusters=2", high.stdout)
            self.assertIn("writes=0", high.stdout)
            self.assertIn("clusters=1", low.stdout)
            self.assertNotEqual(high.stdout, low.stdout)


if __name__ == "__main__":
    unittest.main()
